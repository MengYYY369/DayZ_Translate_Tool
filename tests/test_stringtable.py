import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dayz_translate_tool.stringtable import StringTable


class StringTableTests(unittest.TestCase):
    def test_load_sample_preserves_header_shape_and_rows(self):
        table = StringTable.load(Path("stringtable.csv"))

        self.assertEqual(16, len(table.header))
        self.assertEqual("Language", table.header[0])
        self.assertEqual("", table.header[-1])
        self.assertEqual(22, len(table.rows))

    def test_save_round_trip_preserves_utf8_without_bom_and_empty_tail_column(self):
        table = StringTable.load(Path("stringtable.csv"))
        table.set_cell(0, "chinesesimp", "测试翻译")

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "stringtable.csv"
            table.save(output)
            data = output.read_bytes()

            self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
            reloaded = StringTable.load(output)
            self.assertEqual("", reloaded.header[-1])
            self.assertEqual("测试翻译", reloaded.get_cell(0, "chinesesimp"))
            with output.open("r", encoding="utf-8", newline="") as handle:
                header = next(csv.reader(handle))
            self.assertEqual(table.header, header)

    def test_save_quotes_every_cell_for_dayz_stringtable_format(self):
        table = StringTable(["Language", "english", ""], [["STR_Test", "Hello", ""]])

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "stringtable.csv"
            table.save(output)

            text = output.read_text(encoding="utf-8")

        self.assertIn('"Language","english",""', text)
        self.assertIn('"STR_Test","Hello",""', text)

    def test_add_key_skips_existing_and_fills_all_columns(self):
        table = StringTable(["Language", "original", "chinesesimp", ""], [])

        self.assertTrue(table.add_key("STR_Test_A"))
        self.assertFalse(table.add_key("STR_Test_A"))
        self.assertEqual(1, len(table.rows))
        self.assertEqual(["STR_Test_A", "", "", ""], table.rows[0])

    def test_language_columns_excludes_key_and_empty_tail_columns(self):
        table = StringTable(["Language", "original", "english", "chinesesimp", ""], [])

        self.assertEqual(["original", "english", "chinesesimp"], table.language_columns())


if __name__ == "__main__":
    unittest.main()
