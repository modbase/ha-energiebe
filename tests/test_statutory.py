"""The bundled statutory levies."""

import unittest
from datetime import date

from loader import load

tariffs = load("tariffs")


class TestStatutory(unittest.TestCase):
    def components(self, **kwargs: object) -> dict:
        return {c.key: c for c in tariffs.statutory_components(**kwargs)}

    def test_both_levies_are_present(self) -> None:
        self.assertEqual(set(self.components()), {"excise", "energy_levy"})

    def test_card_figures_are_stored_as_published(self) -> None:
        published = {row["key"]: row for row in tariffs.STATUTORY_TABLE}
        self.assertEqual(published["excise"]["cents_per_kwh"], 5.0329)
        self.assertEqual(published["energy_levy"]["cents_per_kwh"], 0.2042)
        for row in published.values():
            self.assertIn(row["vat_basis"], {"incl", "excl"})
            self.assertTrue(row["source"])
            self.assertIsInstance(row["valid_from"], date)

    def test_an_inclusive_figure_is_divided_once(self) -> None:
        # Stored incl. VAT at 5.0329 c€/kWh; every value leaving this module is
        # excl. VAT, so 0.050329 / 1.06.
        excise = self.components()["excise"]
        self.assertAlmostEqual(excise.value, 0.047480189, places=9)
        self.assertAlmostEqual(excise.value * 1.06, 0.050329, places=9)

    def test_the_vat_basis_is_recorded_in_the_source(self) -> None:
        excise = self.components()["excise"]
        self.assertIn("incl", excise.source)
        self.assertIn("tariefkaart", excise.source.lower())

    def test_a_different_vat_rate_changes_the_normalisation(self) -> None:
        at_21 = self.components(vat_rate=0.21)["excise"]
        self.assertAlmostEqual(at_21.value, 0.050329 / 1.21, places=9)

    def test_switching_the_statutory_reading_is_a_one_line_change(self) -> None:
        # Open question 7: if the card's 5.0329 turns out to be the excl.-VAT
        # statutory rate, the table's vat_basis becomes "excl" and the value is
        # taken as-is. This pins what that would produce, so the two readings
        # cannot be confused later.
        as_excl = tariffs._normalise(
            cents_per_kwh=5.0329, vat_basis="excl", vat_rate=0.06
        )
        self.assertAlmostEqual(as_excl, 0.050329, places=9)
        self.assertAlmostEqual(as_excl * 1.06, 0.05334874, places=9)


if __name__ == "__main__":
    unittest.main()
