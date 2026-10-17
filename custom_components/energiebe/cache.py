"""Carry the last good tariffs across a Home Assistant restart.

energie.be serves the wrong page for a route often enough that a restart can
land in a window where no attempt succeeds -- on 2026-10-17 the rate reached
100% for about ten minutes -- and without a cache that leaves every price
sensor, the cost template and anything reading them unavailable until the site
recovers.

How long a cached price stays right is not a matter of taste: the variable
tariff is re-indexed monthly, so a price scraped in October is the October
tariff for all of October and is simply the wrong number in November. That is
the rule ``is_usable`` implements.

No I/O and no Home Assistant here -- the coordinator owns the Store, this module
owns what is worth storing and when it may still be trusted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .tariffs import Component, TariffComponents

# Bumped when the stored shape changes. A record written by a newer version is
# ignored rather than guessed at: a misread price is worse than a missing one.
CACHE_VERSION = 1


@dataclass(frozen=True)
class CachedData:
    """The last values a successful update produced."""

    electricity: float
    gas_kwh: float
    injection: float
    scraped_at: datetime
    tariffs: TariffComponents | None = None


def to_json(cached: CachedData) -> dict[str, Any]:
    """Return the record as the plain JSON the Store writes."""
    tariffs: dict[str, Any] | None = None
    if cached.tariffs is not None:
        tariffs = {
            "vat_rate": cached.tariffs.vat_rate,
            "components": [
                {
                    "key": component.key,
                    "value": component.value,
                    "source": component.source,
                    "valid_from": component.valid_from.isoformat(),
                    "valid_until": (
                        component.valid_until.isoformat()
                        if component.valid_until
                        else None
                    ),
                }
                for component in cached.tariffs.components
            ],
        }
    return {
        "version": CACHE_VERSION,
        "scraped_at": cached.scraped_at.isoformat(),
        "prices": {
            "electricity": cached.electricity,
            "gas_kwh": cached.gas_kwh,
            "injection": cached.injection,
        },
        "tariffs": tariffs,
    }


def _components(raw: Any) -> TariffComponents | None:
    """Rebuild the components, or nothing if the record cannot be trusted."""
    if not isinstance(raw, Mapping):
        return None
    try:
        components = tuple(
            Component(
                key=str(entry["key"]),
                value=float(entry["value"]),
                source=str(entry["source"]),
                valid_from=date.fromisoformat(entry["valid_from"]),
                valid_until=(
                    date.fromisoformat(entry["valid_until"])
                    if entry.get("valid_until")
                    else None
                ),
            )
            for entry in raw["components"]
        )
        vat_rate = float(raw["vat_rate"])
    except (KeyError, TypeError, ValueError):
        return None
    return TariffComponents(components=components, vat_rate=vat_rate) if components else None


def from_json(raw: Any) -> CachedData | None:
    """Return the stored record, or nothing if there is nothing usable.

    Anything unreadable counts as no cache at all: this runs at startup, where
    raising would cost the user every sensor rather than just the cached value.
    Unreadable *components* cost only the components -- the prices are the
    primary data and are kept.
    """
    if not isinstance(raw, Mapping) or raw.get("version") != CACHE_VERSION:
        return None
    try:
        prices = raw["prices"]
        scraped_at = datetime.fromisoformat(raw["scraped_at"])
        electricity = float(prices["electricity"])
        gas_kwh = float(prices["gas_kwh"])
        injection = float(prices["injection"])
    except (KeyError, TypeError, ValueError):
        return None
    if scraped_at.tzinfo is None:
        # A naive timestamp cannot be compared with Home Assistant's aware now.
        return None
    return CachedData(
        electricity=electricity,
        gas_kwh=gas_kwh,
        injection=injection,
        scraped_at=scraped_at,
        tariffs=_components(raw.get("tariffs")),
    )


def is_usable(cached: CachedData, now: datetime) -> bool:
    """Whether a cached price is still the tariff in force.

    True while ``now`` falls in the same calendar month the price was scraped
    in. Both instants are read in ``now``'s timezone first, so a record written
    just before midnight UTC is not judged against a different local month than
    the one the user is in.
    """
    scraped = cached.scraped_at.astimezone(now.tzinfo)
    return (scraped.year, scraped.month) == (now.year, now.month)
