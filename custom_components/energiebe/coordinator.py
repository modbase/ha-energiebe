"""Data update coordinator for the Energie.be integration."""

from __future__ import annotations

import logging
import re
import ssl
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup, Tag

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .atrias import (
    AtriasError,
    GcvReport,
    async_fetch_gcv,
    create_ssl_context,
    expected_month,
)
from .const import (
    CONF_GOS_EAN,
    DOMAIN,
    FALLBACK_GAS_CONVERSION_FACTOR,
    MAX_SCRAPE_ATTEMPTS,
    RETRY_INTERVAL,
    UPDATE_INTERVAL,
    URL,
)

_LOGGER = logging.getLogger(__name__)
_RETRY_AFTER = RETRY_INTERVAL.total_seconds()

type EnergieBeConfigEntry = ConfigEntry[EnergieBeCoordinator]


@dataclass(frozen=True, kw_only=True)
class EnergieBeData:
    """Everything the sensors read from."""

    electricity: float
    gas_kwh: float
    injection: float
    gas_conversion_factor: float
    gas_conversion_source: str

    @property
    def gas_m3(self) -> float:
        """Gas price per cubic metre."""
        return self.gas_kwh * self.gas_conversion_factor


_ORDER_PATTERN = re.compile(r"order:\s*(-?\d+)")

# The price cards carry no label of their own; the only thing naming a fuel is
# the radio picker beside them, which reads "Elektriciteit | Gas | Zonne-energie".
# energie.be is Dutch only -- it sends lang="nl", ignores Accept-Language and has
# no localised routes -- so there is nothing else to match on. If the wording ever
# changes we fall through to the rendered order and log about it.
_FUEL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "electricity": ("elektriciteit",),
    "gas_kwh": ("gas",),
    "injection": ("zonne", "injectie"),
}

# The one element that only the tariff page carries. Its absence means the
# instance served us some other page, which is a different fault from markup we
# cannot parse -- worth another roll of the dice rather than a day of waiting.
_TARIFF_MARKER = "app-fair-price-item"

_SCRAPE_HOST = urlparse(URL).hostname or ""

# A tariff outside this band means we read the wrong element, or the page
# stopped quoting c€/kWh. Either way, better to fail than to publish it.
_MAX_PLAUSIBLE_PRICE = 5.0


@dataclass(frozen=True)
class _Card:
    """One price card, keyed by the position the page actually renders it at."""

    order: int
    value: float


def _fuel_for(label: str) -> str | None:
    """Map a switch-button label onto one of our keys."""
    folded = label.casefold()
    for key, keywords in _FUEL_KEYWORDS.items():
        if any(keyword in folded for keyword in keywords):
            return key
    return None


def _price_element(item: Tag) -> Tag | None:
    """Return the div holding one card's variable tariff.

    A card renders three figures in the same ``ui-large`` class -- the
    "% goedkoper" badge, the variable tariff and the yearly standing charge --
    so key on the label sitting beside the number, not on the class alone.
    """
    for label in item.find_all("div", class_="d-inline-block"):
        if "kwh" not in label.get_text().casefold():
            continue
        parent = label.parent
        if isinstance(parent, Tag):
            value = parent.find("div", class_="ui-large")
            if isinstance(value, Tag):
                return value
    return None


def _cards(soup: BeautifulSoup) -> list[_Card]:
    """Read every price card, keyed by the position the page lays it out at.

    DOM order and the CSS ``order`` property are allowed to disagree -- the
    latter is what the page actually lays out, so rank on it and hand back
    contiguous positions that the fuel labels can be indexed against.
    """
    found: list[tuple[int, int, float]] = []
    for index, item in enumerate(soup.find_all("app-fair-price-item")):
        element = _price_element(item)
        if not isinstance(element, Tag):
            continue
        try:
            # Tariffs are rendered as c€/kWh, e.g. " 18,77 ".
            value = float(element.get_text().strip().replace(",", ".")) / 100
        except ValueError:
            continue
        match = _ORDER_PATTERN.search(str(item.get("style") or ""))
        found.append((int(match.group(1)) if match else index, index, value))

    found.sort(key=lambda entry: (entry[0], entry[1]))
    return [
        _Card(order=position, value=value)
        for position, (_, _, value) in enumerate(found)
    ]


def _labels(soup: BeautifulSoup) -> list[str]:
    """Read the fuel names from the radio picker, in the order it shows them.

    Scoped to the tariff section: the page carries a second, unrelated picker
    ("Particulier | Professioneel") that must not shift the fuel indices.
    """
    section = soup.find("app-fair-price")
    if not isinstance(section, Tag):
        return []
    return [
        element.get_text().strip()
        for element in section.find_all(class_="radio-label")
    ]


def _parse_prices(html: str) -> dict[str, float]:
    """Pull the tariffs off the Energie.be tariff page.

    Runs in the executor: this parses roughly 800 kB of markup, which is far too
    much blocking work to do on the event loop.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = _cards(soup)
    by_order = {card.order: card.value for card in cards}

    # Preferred: the switch button names each fuel, and its Nth entry belongs to
    # the card rendered at order N.
    prices = {
        fuel: by_order[index]
        for index, label in enumerate(_labels(soup))
        if (fuel := _fuel_for(label)) and index in by_order
    }

    if prices.keys() != _FUEL_KEYWORDS.keys():
        # No usable labels. Fall back to the rendered order, which is still what
        # the page lays out even when the markup order changes, but say so --
        # this is the assumption we cannot verify.
        if not {0, 1, 2} <= by_order.keys():
            raise UpdateFailed(
                f"Could not identify the tariffs on {URL}: "
                f"orders={sorted(by_order)}, labels={_labels(soup)}"
            )
        _LOGGER.warning(
            "Could not match the Energie.be tariffs by name (labels=%s); "
            "falling back to the rendered card order",
            _labels(soup),
        )
        prices = {
            "electricity": by_order[0],
            "gas_kwh": by_order[1],
            "injection": by_order[2],
        }

    for fuel, value in prices.items():
        if not 0 < value < _MAX_PLAUSIBLE_PRICE:
            raise UpdateFailed(f"Implausible {fuel} tariff on {URL}: {value} €/kWh")

    return prices


class EnergieBeCoordinator(DataUpdateCoordinator[EnergieBeData]):
    """Fetch the Energie.be tariffs once on behalf of every sensor."""

    config_entry: EnergieBeConfigEntry

    def __init__(self, hass: HomeAssistant, entry: EnergieBeConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._session = async_get_clientsession(hass)
        self._ssl_context: ssl.SSLContext | None = None
        self._gcv: GcvReport | None = None

    async def _async_update_data(self) -> EnergieBeData:
        """Scrape the tariffs and pair them with the current conversion factor."""
        prices = await self._async_scrape_prices()
        factor, source = await self._async_conversion_factor()
        return EnergieBeData(
            **prices,
            gas_conversion_factor=factor,
            gas_conversion_source=source,
        )

    async def _async_scrape_prices(self) -> dict[str, float]:
        """Fetch and parse the Energie.be tariff page."""
        html = await self._async_fetch_tariff_page()
        return await self.hass.async_add_executor_job(_parse_prices, html)

    async def _async_fetch_tariff_page(self) -> str:
        """Return the tariff page, reasking until an instance serves it.

        See MAX_SCRAPE_ATTEMPTS: the site load-balances across instances whose
        caches hold each other's pages, so asking again is the only way through
        -- but only if we shed the affinity cookie first, otherwise every retry
        goes back to the same instance and gets the same wrong page.
        """
        for attempt in range(1, MAX_SCRAPE_ATTEMPTS + 1):
            self._session.cookie_jar.clear_domain(_SCRAPE_HOST)
            try:
                async with self._session.get(
                    URL, timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    response.raise_for_status()
                    html = await response.text()
            except TimeoutError as err:
                raise UpdateFailed(
                    f"Timeout fetching {URL}", retry_after=_RETRY_AFTER
                ) from err
            except aiohttp.ClientError as err:
                raise UpdateFailed(
                    f"Error fetching {URL}: {err}", retry_after=_RETRY_AFTER
                ) from err

            if _TARIFF_MARKER in html:
                if attempt > 1:
                    _LOGGER.debug(
                        "Got the Energie.be tariff page on attempt %s of %s",
                        attempt,
                        MAX_SCRAPE_ATTEMPTS,
                    )
                return html

        # Every instance we reached served something else. That is the site
        # misbehaving rather than markup we need to relearn, so come back in
        # half an hour instead of waiting for tomorrow's slot.
        raise UpdateFailed(
            f"{URL} served a page without {_TARIFF_MARKER} on all "
            f"{MAX_SCRAPE_ATTEMPTS} attempts",
            retry_after=_RETRY_AFTER,
        )

    async def _async_conversion_factor(self) -> tuple[float, str]:
        """Return the m³ conversion factor and where it came from."""
        ean = self.config_entry.options.get(CONF_GOS_EAN)
        if not ean:
            return FALLBACK_GAS_CONVERSION_FACTOR, "Belgian average (no station set)"

        if (report := await self._async_gcv_report()) and (station := report.station(ean)):
            return station.value, f"{station.name} ({report.month})"

        return FALLBACK_GAS_CONVERSION_FACTOR, "Belgian average (Atrias unavailable)"

    async def _async_gcv_report(self) -> GcvReport | None:
        """Return the newest calorific values, refetching about once a month."""
        if self._gcv is not None and self._gcv.month == expected_month(
            dt_util.now().date()
        ):
            return self._gcv

        if self._ssl_context is None:
            self._ssl_context = await self.hass.async_add_executor_job(
                create_ssl_context
            )

        try:
            self._gcv = await async_fetch_gcv(
                self._session, self._ssl_context, dt_util.now().date()
            )
        except AtriasError as err:
            # The tariffs are the primary data. A missing conversion factor
            # degrades the m³ sensor to the fallback, it does not fail the
            # update, so keep whatever report we already had.
            _LOGGER.warning("Could not refresh the gas conversion factor: %s", err)

        return self._gcv
