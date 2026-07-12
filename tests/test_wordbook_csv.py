import tempfile
import unittest
from pathlib import Path

from wordbook_csv import WORDBOOK_HEADERS, load_wordbook_csv, wordbook_rows_for_save, write_wordbook_csv


class WordbookCsvTests(unittest.TestCase):
    def write_sample(self, text):
        tmp = tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", delete=False, suffix=".csv")
        tmp.write(text)
        tmp.close()
        return Path(tmp.name)

    def test_headers_do_not_include_language_or_trailing_empty_column(self):
        self.assertEqual(WORDBOOK_HEADERS[0], "original")
        self.assertNotIn("Language", WORDBOOK_HEADERS)
        self.assertNotIn("", WORDBOOK_HEADERS)

    def test_load_expands_missing_supported_columns_by_header_name(self):
        path = self.write_sample('"original","english","chinesesimp"\n"Knife","Knife","刀"\n')

        headers, rows = load_wordbook_csv(path)

        self.assertEqual(headers, WORDBOOK_HEADERS)
        self.assertEqual(rows[0][0], "Knife")
        self.assertEqual(rows[0][1], "Knife")
        self.assertEqual(rows[0][-1], "刀")
        self.assertEqual(rows[0][2], "")

    def test_load_rejects_unsupported_columns(self):
        path = self.write_sample('"original","english","unknown"\n"Knife","Knife","x"\n')

        with self.assertRaises(ValueError):
            load_wordbook_csv(path)

    def test_write_quotes_cells_and_does_not_add_dayz_trailing_comma(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "wordbook.csv"

            write_wordbook_csv(path, [["A \"sharp\" knife", "Knife"]])

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertTrue(lines[0].startswith('"original","english"'))
            self.assertTrue(lines[0].endswith('"chinesesimp"'))
            self.assertFalse(lines[0].endswith(","))
            self.assertIn('"A ""sharp"" knife"', lines[1])

    def test_rows_for_save_ignores_final_empty_row(self):
        rows = [
            ["Knife", "Knife"] + [""] * (len(WORDBOOK_HEADERS) - 2),
            [""] * len(WORDBOOK_HEADERS),
        ]

        self.assertEqual(wordbook_rows_for_save(rows), [rows[0]])


if __name__ == "__main__":
    unittest.main()
