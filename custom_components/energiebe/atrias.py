"""Client for the Atrias sector-data feed (Belgian gross calorific values).

Atrias publishes the official gross calorific value (kWh/m³) once a month for
every GOS -- the reception station a gas meter hangs off. Energie.be quotes gas
in c€/kWh, so that number is what turns the tariff into a price per m³. It
drifts by a percent or so month to month and differs slightly per station.

Two quirks of the feed are handled here:

* The API sits behind an Azure APIM subscription key. Atrias hands an anonymous
  one to every visitor of their own frontend in ``runtime-config.js``; reading
  it from there each time means a key rotation does not break us.
* ``api.atrias.be`` serves its leaf certificate *without* the GoDaddy G2
  intermediate. Browsers paper over that by fetching the missing certificate
  through the certificate's AIA extension; Python does not, so verifying
  against certifi alone fails with CERTIFICATE_VERIFY_FAILED. We supply the
  intermediate ourselves (``gdig2.pem``). The chain still has to validate up to
  the GoDaddy root that certifi already trusts, so this completes the chain
  rather than weakening it. Drop the file once Atrias fixes their server.
"""

from __future__ import annotations

import csv
import re
import ssl
from dataclasses import dataclass
from datetime import date
from os import environ
from pathlib import Path

import aiohttp
import certifi

from homeassistant.exceptions import HomeAssistantError

from .const import ATRIAS_GCV_URL, ATRIAS_RUNTIME_CONFIG_URL

_INTERMEDIATE = Path(__file__).parent / "gdig2.pem"
_KEY_PATTERN = re.compile(r"apimSubscriptionKey:\s*['\"](\w+)['\"]")
_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Atrias publishes a month's file during the month that follows it, so the
# newest file we can expect is last month's. Look a little further back as well,
# so a late publication does not leave us without a value.
_MONTHS_TO_TRY = 3


class AtriasError(HomeAssistantError):
    """Raised when the gross calorific values cannot be read."""


@dataclass(frozen=True)
class GcvStation:
    """One reception station's gross calorific value, in kWh/m³."""

    ean: str
    name: str
    value: float


@dataclass(frozen=True)
class GcvReport:
    """The most recently published set of gross calorific values."""

    month: str
    stations: tuple[GcvStation, ...]

    def station(self, ean: str) -> GcvStation | None:
        """Return the station with this EAN, if it is in the report."""
        return next((station for station in self.stations if station.ean == ean), None)


def create_ssl_context() -> ssl.SSLContext:
    """Build the SSL context used for api.atrias.be.

    Blocking -- it reads certificates from disk, so run it in the executor.
    """
    # Mirrors homeassistant.util.ssl, which we cannot reuse directly because
    # its context is cached and shared; mutating it would affect every caller.
    cafile = environ.get("REQUESTS_CA_BUNDLE", certifi.where())
    context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=cafile)
    context.load_verify_locations(cadata=_INTERMEDIATE.read_text(encoding="ascii"))
    return context


def expected_month(today: date) -> str:
    """Return the newest month Atrias can be expected to have published."""
    year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    return f"{year}-{month:02d}"


def _candidate_months(today: date) -> list[tuple[int, int]]:
    """Return the months worth asking for, newest first."""
    months: list[tuple[int, int]] = []
    year, month = today.year, today.month
    for _ in range(_MONTHS_TO_TRY):
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
        months.append((year, month))
    return months


def _parse(text: str) -> tuple[GcvStation, ...]:
    """Parse the CSV Atrias serves: BOM, comma decimals, quoted values."""
    stations: list[GcvStation] = []
    for row in csv.DictReader(text.lstrip("﻿").splitlines()):
        try:
            value = float(row["GCVValue"].replace(",", "."))
            ean, name = row["ARSEanGSRN"], row["ARSName"]
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        # Decommissioned stations are published with a value of 0.
        if value > 0:
            stations.append(GcvStation(ean=ean, name=name, value=value))
    return tuple(stations)


async def _async_subscription_key(session: aiohttp.ClientSession) -> str:
    """Read the anonymous APIM key Atrias hands to its own web frontend."""
    try:
        async with session.get(ATRIAS_RUNTIME_CONFIG_URL, timeout=_TIMEOUT) as response:
            response.raise_for_status()
            text = await response.text()
    except (TimeoutError, aiohttp.ClientError) as err:
        raise AtriasError(f"Error fetching the Atrias subscription key: {err}") from err

    if not (match := _KEY_PATTERN.search(text)):
        raise AtriasError("No apimSubscriptionKey found in the Atrias runtime config")
    return match.group(1)


async def async_fetch_gcv(
    session: aiohttp.ClientSession,
    ssl_context: ssl.SSLContext,
    today: date,
) -> GcvReport:
    """Fetch the most recently published gross calorific values."""
    key = await _async_subscription_key(session)

    for year, month in _candidate_months(today):
        url = ATRIAS_GCV_URL.format(year=year, month=month)
        try:
            async with session.get(
                url,
                params={"subscription-key": key},
                ssl=ssl_context,
                timeout=_TIMEOUT,
            ) as response:
                # Months that have not been published yet answer 400.
                if response.status in (400, 404):
                    continue
                response.raise_for_status()
                text = await response.text()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise AtriasError(f"Error fetching {url}: {err}") from err

        if stations := _parse(text):
            return GcvReport(month=f"{year}-{month:02d}", stations=stations)

    raise AtriasError("Atrias published no usable calorific values in recent months")
