"""Parsing the VREG distribution network tariffs."""

import unittest
from datetime import date

from loader import fixture, load

tariffs = load("tariffs")
xlsx = load("xlsx")


class TestNetworkTariffs(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sheets = xlsx.read_xlsx(fixture("nettarieven-2026.xlsx"))

    def parse(self, **kwargs: object) -> object:
        return tariffs.parse_network_tariffs(self.sheets, **kwargs)

    def test_fluvius_west_digital_single(self) -> None:
        component = self.parse(operator="Fluvius West")
        # 63.1937 EUR/MWh excl. VAT -> EUR/kWh.
        self.assertAlmostEqual(component.value, 0.0631937, places=9)
        self.assertEqual(component.key, "network")
        self.assertIn("Fluvius West", component.source)

    def test_validity_comes_from_the_sheet_not_the_clock(self) -> None:
        component = self.parse(operator="Fluvius West")
        self.assertEqual(component.valid_from, date(2026, 1, 1))
        self.assertEqual(component.valid_until, date(2026, 12, 31))

    def test_vat_conversion_matches_vregs_own_inclusive_block(self) -> None:
        # The file ships both bases. We read the exclusive one, so the inclusive
        # one is an independent oracle for our single conversion.
        component = self.parse(operator="Fluvius West")
        priced = tariffs.TariffComponents(components=(component,), vat_rate=0.06)
        self.assertAlmostEqual(priced.total_incl_vat * 1000, 66.9853, delta=1e-4)

    def test_every_operator_resolves(self) -> None:
        operators = tariffs.network_operators(self.sheets)
        self.assertEqual(len(operators), 8)
        self.assertIn("Fluvius West", operators)
        for operator in operators:
            self.assertGreater(self.parse(operator=operator).value, 0.0)

    def test_operator_names_are_whitespace_normalised(self) -> None:
        # The cells hold 'Fluvius\nAntwerpen' and 'Fluvius \nHalle-Vilvoorde'.
        operators = tariffs.network_operators(self.sheets)
        self.assertIn("Fluvius Antwerpen", operators)
        self.assertIn("Fluvius Halle-Vilvoorde", operators)
        self.assertAlmostEqual(
            self.parse(operator="Fluvius Antwerpen").value, 0.0505027, places=9
        )

    def test_night_only_reads_the_exclusief_nacht_row(self) -> None:
        component = self.parse(operator="Fluvius West", scheme="night_only")
        self.assertAlmostEqual(component.value, 0.056536, places=9)

    def test_dual_schemes_use_the_same_volume_tariff(self) -> None:
        # The distribution tariff for a digital meter does not split day/night.
        day = self.parse(operator="Fluvius West", scheme="dual_day")
        night = self.parse(operator="Fluvius West", scheme="dual_night")
        self.assertEqual(day.value, night.value)
        self.assertAlmostEqual(day.value, 0.0631937, places=9)

    def test_analogue_meter_reads_its_own_block(self) -> None:
        component = self.parse(operator="Fluvius West", meter_kind="classic")
        self.assertAlmostEqual(component.value, 0.0971801, places=9)
        self.assertIn("Analoge meter", component.source)

    def test_unknown_operator_is_refused_loudly(self) -> None:
        with self.assertRaises(tariffs.TariffError):
            self.parse(operator="Sibelga")

    def test_implausible_value_is_refused(self) -> None:
        # A reshaped sheet could put Maximumtarief (327.6 EUR/MWh) where the
        # real tariff was. Five times the plausible price must not be published.
        broken = {
            name: [list(row) for row in rows] for name, rows in self.sheets.items()
        }
        rows = broken["ELEK Overzicht laagspanning"]
        row = next(r for r in rows if len(r) > 9 and r[1] == "Totaal kWh-tarief")
        row[9] = "327.6168"
        with self.assertRaises(tariffs.TariffError):
            tariffs.parse_network_tariffs(broken, operator="Fluvius West")

    def test_unparseable_value_is_refused(self) -> None:
        broken = {
            name: [list(row) for row in rows] for name, rows in self.sheets.items()
        }
        rows = broken["ELEK Overzicht laagspanning"]
        row = next(r for r in rows if len(r) > 9 and r[1] == "Totaal kWh-tarief")
        row[9] = "n.v.t."
        with self.assertRaises(tariffs.TariffError):
            tariffs.parse_network_tariffs(broken, operator="Fluvius West")

    def test_missing_sheet_is_refused(self) -> None:
        with self.assertRaises(tariffs.TariffError):
            tariffs.parse_network_tariffs({}, operator="Fluvius West")


if __name__ == "__main__":
    unittest.main()
