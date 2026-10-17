"""Assembling the components, end to end, from the real fixtures."""

import unittest
from datetime import date

from loader import fixture, load

tariffs = load("tariffs")
xlsx = load("xlsx")

OCTOBER = date(2026, 10, 1)
SCRAPED_ENERGY = 0.1877  # what the website published on 2026-10-17, excl. VAT


class TestBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.network_sheets = xlsx.read_xlsx(fixture("nettarieven-2026.xlsx"))
        cls.vtest_sheets = xlsx.read_xlsx(fixture("vtest-202610.xlsx"))

    def components(self, **kwargs: object) -> object:
        return tariffs.build(
            network=tariffs.parse_network_tariffs(
                self.network_sheets, operator="Fluvius West"
            ),
            vtest=tariffs.parse_vtest(
                self.vtest_sheets,
                supplier="Energie.be",
                product="Elektriciteit online",
                month=OCTOBER,
            ),
            **kwargs,
        )

    def test_every_required_component_is_present(self) -> None:
        self.assertEqual(self.components().keys(), tariffs.REQUIRED_KEYS)

    def test_components_total(self) -> None:
        components = self.components()
        self.assertAlmostEqual(components.total_excl_vat, 0.127270304, places=9)
        self.assertAlmostEqual(components.total_incl_vat, 0.134906522, places=9)

    def test_all_in_price_for_october_2026(self) -> None:
        # 0.1877 energy + network 63.1937 EUR/MWh + GSC 1.103 + WKK 0.364 c€/kWh
        # + the two statutory levies, VAT applied once.
        self.assertAlmostEqual(
            self.components().all_in_price(SCRAPED_ENERGY), 0.333868522, places=9
        )

    def test_it_reproduces_the_hand_written_helper_to_within_rounding(self) -> None:
        # The template helper this replaces used five constants rounded to four
        # decimals and was missing VAT on the energy term. Corrected, it gives
        # 0.333933; the parsed components give 0.333869. The 6e-5 gap is the
        # rounding in those constants, and is the regression check that we are
        # computing the same quantity.
        price = self.components().all_in_price(SCRAPED_ENERGY)
        self.assertAlmostEqual(price, 0.333933, delta=1e-4)

    def test_a_day_of_consumption_costs_what_the_invoice_would_say(self) -> None:
        price = self.components().all_in_price(SCRAPED_ENERGY)
        self.assertEqual(round(price * 3.689, 2), 1.23)

    def test_a_missing_component_is_refused(self) -> None:
        # A missing component does not make the price smaller, it makes it wrong.
        with self.assertRaises(tariffs.TariffError):
            tariffs.build(
                network=tariffs.parse_network_tariffs(
                    self.network_sheets, operator="Fluvius West"
                ),
                vtest={},
            )

    def test_a_different_vat_rate_flows_through(self) -> None:
        components = self.components(vat_rate=0.21)
        self.assertAlmostEqual(
            components.all_in_price(SCRAPED_ENERGY),
            (SCRAPED_ENERGY + components.total_excl_vat) * 1.21,
            places=9,
        )

    def test_fresh_components_are_not_stale(self) -> None:
        self.assertEqual(
            tariffs.stale_reasons(self.components(), today=date(2026, 10, 17)), ()
        )

    def test_an_old_vtest_month_is_stale(self) -> None:
        reasons = tariffs.stale_reasons(self.components(), today=date(2027, 1, 15))
        self.assertTrue(any("V-test" in reason for reason in reasons))

    def test_last_years_network_tariff_is_stale(self) -> None:
        reasons = tariffs.stale_reasons(self.components(), today=date(2027, 3, 1))
        self.assertTrue(any("nettarief" in reason.lower() for reason in reasons))

    def test_an_old_statutory_table_is_stale(self) -> None:
        reasons = tariffs.stale_reasons(self.components(), today=date(2028, 6, 1))
        self.assertTrue(any("heffing" in reason.lower() for reason in reasons))


if __name__ == "__main__":
    unittest.main()
