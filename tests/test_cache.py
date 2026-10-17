"""Carrying the last good price across a restart."""

import json
import unittest
from datetime import date, datetime, timedelta, timezone

from loader import load

cache = load("cache")
tariffs = load("tariffs")

BRUSSELS = timezone(timedelta(hours=1))


def components() -> object:
    return tariffs.TariffComponents(
        components=(
            tariffs.Component(
                key="network",
                value=0.0631937,
                source="VREG distributienettarieven 2026, Fluvius West, Digitale meter",
                valid_from=date(2026, 1, 1),
                valid_until=date(2026, 12, 31),
            ),
            tariffs.Component(
                key="gsc",
                value=0.01103,
                source="VREG V-test 2026-10 (excl. btw)",
                valid_from=date(2026, 10, 1),
            ),
        ),
        vat_rate=0.06,
    )


def record(**kwargs: object) -> object:
    arguments = {
        "electricity": 0.1877,
        "gas_kwh": 0.076,
        "injection": 0.0397,
        "scraped_at": datetime(2026, 10, 17, 20, 30, tzinfo=BRUSSELS),
        "tariffs": components(),
    }
    arguments.update(kwargs)
    return cache.CachedData(**arguments)


class TestRoundTrip(unittest.TestCase):
    def test_a_record_survives_json(self) -> None:
        restored = cache.from_json(json.loads(json.dumps(cache.to_json(record()))))
        self.assertEqual(restored, record())

    def test_the_components_come_back_whole(self) -> None:
        restored = cache.from_json(cache.to_json(record()))
        network = next(c for c in restored.tariffs.components if c.key == "network")
        self.assertAlmostEqual(network.value, 0.0631937, places=9)
        self.assertEqual(network.valid_from, date(2026, 1, 1))
        self.assertEqual(network.valid_until, date(2026, 12, 31))
        self.assertIn("Fluvius West", network.source)
        self.assertEqual(restored.tariffs.vat_rate, 0.06)
        self.assertAlmostEqual(
            restored.tariffs.all_in_price(restored.electricity), 0.277639122, places=9
        )

    def test_a_record_without_components_round_trips(self) -> None:
        restored = cache.from_json(cache.to_json(record(tariffs=None)))
        self.assertIsNone(restored.tariffs)
        self.assertAlmostEqual(restored.electricity, 0.1877, places=9)


class TestUsable(unittest.TestCase):
    def test_usable_within_the_month_it_was_scraped_in(self) -> None:
        self.assertTrue(
            cache.is_usable(record(), datetime(2026, 10, 31, 23, 0, tzinfo=BRUSSELS))
        )

    def test_not_usable_once_the_month_turns(self) -> None:
        # The variable tariff is re-indexed monthly, so on the 1st the cached
        # figure is last month's price: wrong, not merely old.
        self.assertFalse(
            cache.is_usable(record(), datetime(2026, 11, 1, 0, 30, tzinfo=BRUSSELS))
        )

    def test_not_usable_a_year_later_in_the_same_month(self) -> None:
        self.assertFalse(
            cache.is_usable(record(), datetime(2027, 10, 17, 20, 30, tzinfo=BRUSSELS))
        )

    def test_the_comparison_is_made_in_one_timezone(self) -> None:
        # Stored as UTC, but local time is already November: a naive comparison
        # of the stored month against the local month would disagree.
        stored_utc = record(scraped_at=datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc))
        self.assertTrue(
            cache.is_usable(stored_utc, datetime(2026, 11, 1, 6, 0, tzinfo=BRUSSELS))
        )


class TestRejectsRubbish(unittest.TestCase):
    def test_nothing_stored(self) -> None:
        self.assertIsNone(cache.from_json(None))

    def test_not_a_mapping(self) -> None:
        self.assertIsNone(cache.from_json("nope"))

    def test_a_newer_version_is_ignored_rather_than_misread(self) -> None:
        raw = cache.to_json(record())
        raw["version"] = cache.CACHE_VERSION + 1
        self.assertIsNone(cache.from_json(raw))

    def test_missing_fields(self) -> None:
        raw = cache.to_json(record())
        del raw["prices"]
        self.assertIsNone(cache.from_json(raw))

    def test_a_price_that_is_not_a_number(self) -> None:
        raw = cache.to_json(record())
        raw["prices"]["electricity"] = "cheap"
        self.assertIsNone(cache.from_json(raw))

    def test_an_unparseable_timestamp(self) -> None:
        raw = cache.to_json(record())
        raw["scraped_at"] = "last Tuesday"
        self.assertIsNone(cache.from_json(raw))

    def test_a_timestamp_without_a_timezone(self) -> None:
        # Comparing a naive timestamp against an aware one raises; refuse it.
        raw = cache.to_json(record())
        raw["scraped_at"] = "2026-10-17T20:30:00"
        self.assertIsNone(cache.from_json(raw))

    def test_broken_components_drop_only_the_components(self) -> None:
        # The prices are the primary data; unreadable components must not cost
        # us the cached price as well.
        raw = cache.to_json(record())
        raw["tariffs"]["components"][0]["valid_from"] = "whenever"
        restored = cache.from_json(raw)
        self.assertIsNotNone(restored)
        self.assertIsNone(restored.tariffs)
        self.assertAlmostEqual(restored.electricity, 0.1877, places=9)


if __name__ == "__main__":
    unittest.main()
