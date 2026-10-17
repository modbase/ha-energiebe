"""The xlsx reader, against a real VREG workbook."""

import unittest

from loader import fixture, load

xlsx = load("xlsx")


class TestReadXlsx(unittest.TestCase):
    def setUp(self) -> None:
        self.sheets = xlsx.read_xlsx(fixture("nettarieven-2026.xlsx"))

    def test_sheet_names_in_workbook_order(self) -> None:
        names = list(self.sheets)
        self.assertEqual(names[0], "ELEK Overzicht laagspanning")
        self.assertIn("FW ELEK Afname", names)
        self.assertEqual(len(names), 18)

    def test_shared_strings_are_resolved(self) -> None:
        rows = self.sheets["ELEK Overzicht laagspanning"]
        labels = [row[1] for row in rows if len(row) > 1]
        self.assertIn("Totaal kWh-tarief", labels)
        self.assertIn("Digitale meter", labels)

    def test_numbers_come_back_as_written(self) -> None:
        rows = self.sheets["ELEK Overzicht laagspanning"]
        row = next(r for r in rows if len(r) > 2 and r[1] == "Totaal kWh-tarief")
        self.assertAlmostEqual(float(row[9]), 63.1937, places=4)

    def test_blank_rows_are_kept_as_empty_lists(self) -> None:
        # Row numbering is not preserved across readers, which is exactly why
        # parsers must match header text -- but a blank row must not shift the
        # columns of the rows around it either.
        rows = self.sheets["ELEK Overzicht laagspanning"]
        self.assertIn([], rows)

    def test_two_letter_columns(self) -> None:
        # The V-test sheet runs out to column AE; a reader that only handles
        # single letters silently drops the price column.
        self.assertEqual(xlsx._column("AE17"), 30)
        self.assertEqual(xlsx._column("A1"), 0)
        self.assertEqual(xlsx._column("Z9"), 25)

    def test_rubbish_input_raises(self) -> None:
        with self.assertRaises(xlsx.XlsxError):
            xlsx.read_xlsx(b"this is not a zip")


if __name__ == "__main__":
    unittest.main()
