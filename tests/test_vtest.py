"""Parsing the VREG V-test levies."""

import unittest
from datetime import date

from loader import fixture, load

tariffs = load("tariffs")
xlsx = load("xlsx")

OCTOBER = date(2026, 10, 1)


class TestVtest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sheets = xlsx.read_xlsx(fixture("vtest-202610.xlsx"))

    def parse(self, **kwargs: object) -> dict:
        arguments = {
            "supplier": "Energie.be",
            "product": "Elektriciteit online",
            "month": OCTOBER,
        }
        arguments.update(kwargs)
        return tariffs.parse_vtest(self.sheets, **arguments)

    def test_green_certificate_and_cogeneration_levies(self) -> None:
        components = self.parse()
        # 1.103 and 0.364 c€/kWh excl. VAT -> EUR/kWh.
        self.assertAlmostEqual(components["gsc"].value, 0.01103, places=9)
        self.assertAlmostEqual(components["wkk"].value, 0.00364, places=9)

    def test_source_names_the_file_and_the_month(self) -> None:
        component = self.parse()["gsc"]
        self.assertIn("V-test", component.source)
        self.assertIn("2026-10", component.source)
        self.assertEqual(component.valid_from, OCTOBER)

    def test_both_levies_are_excl_vat_as_published(self) -> None:
        # VREG states "Alle prijzen zijn exclusief btw"; the card's 1.169 and
        # 0.386 c€/kWh are these values with VAT, which is the check that the
        # basis has not been mixed up.
        components = self.parse()
        self.assertAlmostEqual(components["gsc"].value * 1.06, 0.0116918, places=9)
        self.assertAlmostEqual(components["wkk"].value * 1.06, 0.0038584, places=9)

    def test_a_month_not_in_the_file_falls_back_to_the_newest(self) -> None:
        # In early November the October file is still the newest published.
        components = self.parse(month=date(2026, 11, 1))
        self.assertAlmostEqual(components["gsc"].value, 0.01103, places=9)
        self.assertIn("2026-10", components["gsc"].source)
        self.assertEqual(components["gsc"].valid_from, OCTOBER)

    def test_an_earlier_month_reads_that_month(self) -> None:
        components = self.parse(month=date(2026, 1, 1))
        self.assertIn("2026-01", components["gsc"].source)
        self.assertEqual(components["gsc"].valid_from, date(2026, 1, 1))

    def test_supplier_names_are_whitespace_normalised(self) -> None:
        # The cell holds 'Aspiravi Energy ' with a trailing space.
        suppliers = tariffs.vtest_suppliers(self.sheets)
        self.assertIn("Energie.be", suppliers)
        self.assertIn("Aspiravi Energy", suppliers)

    def test_products_are_listed_per_supplier(self) -> None:
        products = tariffs.vtest_products(self.sheets, supplier="Energie.be")
        self.assertIn("Elektriciteit online", products)
        self.assertIn("Elektriciteit dynamisch online", products)
        # Gas and business products must not be offered as an electricity choice.
        self.assertNotIn("Gas online", products)
        self.assertNotIn("Elektriciteit professioneel online", products)

    def test_business_segment_reads_its_own_rows(self) -> None:
        components = self.parse(
            segment="Onderneming", product="Elektriciteit professioneel online"
        )
        self.assertAlmostEqual(components["gsc"].value, 0.01103, places=9)

    def test_months_are_listed_newest_first(self) -> None:
        months = tariffs.vtest_months(self.sheets)
        self.assertEqual(months[0], OCTOBER)
        self.assertIn(date(2026, 1, 1), months)

    def test_unknown_supplier_is_refused(self) -> None:
        with self.assertRaises(tariffs.TariffError):
            self.parse(supplier="Nuon")

    def test_unknown_product_is_refused(self) -> None:
        with self.assertRaises(tariffs.TariffError):
            self.parse(product="Elektriciteit offline")

    def test_ambiguous_match_is_refused(self) -> None:
        # Two rows for one component means the filter no longer identifies a
        # single product; publishing either would be a guess.
        doubled = {
            name: [list(row) for row in rows] for name, rows in self.sheets.items()
        }
        rows = doubled["Var-dyn (excl. btw) (2026)"]
        row = next(
            r
            for r in rows[1:]
            if len(r) > 30
            and r[1] == "okt"
            and r[5] == "Energie.be"
            and r[6] == "Elektriciteit online"
            and r[8].startswith("Kosten groene stroom")
        )
        rows.append(list(row))
        with self.assertRaises(tariffs.TariffError):
            tariffs.parse_vtest(
                doubled,
                supplier="Energie.be",
                product="Elektriciteit online",
                month=OCTOBER,
            )

    def test_missing_sheet_is_refused(self) -> None:
        with self.assertRaises(tariffs.TariffError):
            tariffs.parse_vtest(
                {}, supplier="Energie.be", product="Elektriciteit online", month=OCTOBER
            )


if __name__ == "__main__":
    unittest.main()
