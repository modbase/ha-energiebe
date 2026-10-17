"""What the options flow stores when a field is not on the form."""

import unittest

from loader import load

options = load("options")


class TestMergeOptions(unittest.TestCase):
    def test_submitted_values_win(self) -> None:
        merged = options.merge_options(
            {"gos_ean": "541448820000000000", "vat_rate": 0.06},
            {"gos_ean": "", "vat_rate": 0.21},
        )
        self.assertEqual(merged["gos_ean"], "")
        self.assertEqual(merged["vat_rate"], 0.21)

    def test_a_field_absent_from_the_form_keeps_its_stored_value(self) -> None:
        # The VREG-backed dropdowns are dropped from the form when the files
        # cannot be fetched. Submitting it must not erase the all-in price
        # configuration: the price would go unavailable with nothing said.
        merged = options.merge_options(
            {
                "gos_ean": "541448820000000000",
                "network_operator": "Fluvius West",
                "meter_kind": "digital",
                "tariff_scheme": "single",
                "product": "Elektriciteit online",
            },
            {"gos_ean": "", "vat_rate": 0.06},
        )
        self.assertEqual(merged["network_operator"], "Fluvius West")
        self.assertEqual(merged["meter_kind"], "digital")
        self.assertEqual(merged["tariff_scheme"], "single")
        self.assertEqual(merged["product"], "Elektriciteit online")
        self.assertEqual(merged["gos_ean"], "")

    def test_clearing_the_operator_is_still_possible(self) -> None:
        # "Not set" submits an empty string, which is a real choice, not an
        # absent field -- it must switch the all-in sensor off.
        merged = options.merge_options(
            {"network_operator": "Fluvius West"}, {"network_operator": ""}
        )
        self.assertEqual(merged["network_operator"], "")

    def test_neither_input_is_mutated(self) -> None:
        current = {"gos_ean": "x"}
        submitted = {"vat_rate": 0.06}
        options.merge_options(current, submitted)
        self.assertEqual(current, {"gos_ean": "x"})
        self.assertEqual(submitted, {"vat_rate": 0.06})


if __name__ == "__main__":
    unittest.main()
