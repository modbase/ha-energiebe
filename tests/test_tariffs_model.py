"""The component model: one VAT conversion, and it is here."""

import unittest
from datetime import date

from loader import load

tariffs = load("tariffs")


def component(key: str, value: float, year: int = 2026) -> object:
    return tariffs.Component(
        key=key, value=value, source=f"test {key}", valid_from=date(year, 1, 1)
    )


class TestTariffComponents(unittest.TestCase):
    def setUp(self) -> None:
        self.components = tariffs.TariffComponents(
            components=(component("network", 0.0631937), component("gsc", 0.01103)),
            vat_rate=0.06,
        )

    def test_total_excl_vat_is_the_plain_sum(self) -> None:
        self.assertAlmostEqual(self.components.total_excl_vat, 0.0742237, places=9)

    def test_total_incl_vat_applies_the_rate_once(self) -> None:
        self.assertAlmostEqual(self.components.total_incl_vat, 0.078677122, places=9)

    def test_all_in_price_includes_the_energy_component(self) -> None:
        # 0.1877 scraped, excl. VAT, plus these two components, all taxed once.
        self.assertAlmostEqual(
            self.components.all_in_price(0.1877), 0.277639122, places=9
        )

    def test_a_different_vat_rate_is_honoured(self) -> None:
        # The rate is statutory and has changed before: nothing may bake in 1.06.
        at_21 = tariffs.TariffComponents(
            components=self.components.components, vat_rate=0.21
        )
        self.assertAlmostEqual(at_21.total_incl_vat, 0.089810677, places=9)

    def test_zero_vat_leaves_the_sum_untouched(self) -> None:
        free = tariffs.TariffComponents(
            components=self.components.components, vat_rate=0.0
        )
        self.assertEqual(free.total_incl_vat, free.total_excl_vat)
        self.assertEqual(free.all_in_price(0.1877), free.total_excl_vat + 0.1877)

    def test_newest_valid_from_is_the_latest_component(self) -> None:
        mixed = tariffs.TariffComponents(
            components=(component("network", 0.063, 2026), component("gsc", 0.011, 2024))
        )
        self.assertEqual(mixed.newest_valid_from, date(2026, 1, 1))

    def test_attributes_name_every_component_and_its_provenance(self) -> None:
        attributes = self.components.as_attributes()
        self.assertAlmostEqual(attributes["network"], 0.0631937, places=9)
        self.assertEqual(attributes["network_source"], "test network")
        self.assertEqual(attributes["network_valid_from"], "2026-01-01")
        self.assertEqual(attributes["vat_rate"], 0.06)
        self.assertEqual(attributes["vat_basis"], "incl")

    def test_default_vat_rate_is_six_percent(self) -> None:
        self.assertEqual(tariffs.DEFAULT_VAT_RATE, 0.06)
        self.assertEqual(
            tariffs.TariffComponents(components=()).vat_rate, 0.06
        )


if __name__ == "__main__":
    unittest.main()
