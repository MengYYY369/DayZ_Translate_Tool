import tempfile
import unittest
from pathlib import Path

from dayz_csv import (
    DAYZ_HEADERS,
    build_column_translation_jobs,
    build_row_translation_jobs,
    copy_source_for_header,
    dayz_rows_for_save,
    is_copy_only_column,
    language_code_for_header,
    load_dayz_csv,
    source_language_code_for_header,
    write_dayz_csv,
)


class DayzCsvTests(unittest.TestCase):
    def write_sample(self, text):
        tmp = tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", delete=False, suffix=".csv")
        tmp.write(text)
        tmp.close()
        return Path(tmp.name)

    def test_load_uses_fixed_dayz_headers(self):
        path = self.write_sample(
            '"Language","original","english","czech","german","russian","polish","hungarian","italian","spanish","french","chinese","japanese","portuguese","chinesesimp",\n'
            '"STR_A","Knife","Knife","","","","","","","","","","","","",\n'
        )

        headers, rows, warnings = load_dayz_csv(path)

        self.assertEqual(headers, DAYZ_HEADERS)
        self.assertEqual(rows, [["STR_A", "Knife", "Knife", "", "", "", "", "", "", "", "", "", "", "", "", ""]])
        self.assertEqual(warnings, [])

    def test_load_skips_unknown_columns_with_warning(self):
        path = self.write_sample(
            '"Language","original","english","unknown","chinesesimp",\n'
            '"STR_A","Knife","Knife","x","刀",\n'
        )

        headers, rows, warnings = load_dayz_csv(path)

        self.assertEqual(headers, DAYZ_HEADERS)
        self.assertEqual(rows[0][0], "STR_A")
        self.assertEqual(rows[0][1], "Knife")
        self.assertEqual(rows[0][2], "Knife")
        self.assertEqual(rows[0][14], "刀")
        self.assertTrue(any("unknown" in w for w in warnings))

    def test_load_rejects_header_with_no_known_dayz_columns(self):
        path = self.write_sample('"id","foo","bar",\n"1","a","b",\n')

        with self.assertRaises(ValueError):
            load_dayz_csv(path)

    def test_load_without_language_column_still_maps_known_languages(self):
        path = self.write_sample(
            '"original","english","chinesesimp",\n'
            '"Knife","Knife","刀",\n'
        )

        headers, rows, warnings = load_dayz_csv(path)

        self.assertEqual(headers, DAYZ_HEADERS)
        self.assertEqual(rows[0][0], "")
        self.assertEqual(rows[0][1], "Knife")
        self.assertEqual(rows[0][2], "Knife")
        self.assertEqual(rows[0][14], "刀")

    def test_load_full_header_returns_empty_warnings(self):
        path = self.write_sample(
            '"Language","original","english","czech","german","russian","polish","hungarian","italian","spanish","french","chinese","japanese","portuguese","chinesesimp",\n'
            '"STR_A","Knife","Knife","","","","","","","","","","","","",\n'
        )

        headers, rows, warnings = load_dayz_csv(path)

        self.assertEqual(headers, DAYZ_HEADERS)
        self.assertEqual(warnings, [])
        self.assertEqual(rows[0][0], "STR_A")

    def test_load_expands_partial_dayz_header(self):
        path = self.write_sample(
            '"Language","original","english","chinese","chinesesimp","portuguese",\n'
            '"STR_A","Knife","Knife","Chinese","Chinese Simple","Portuguese",\n'
        )

        headers, rows, warnings = load_dayz_csv(path)

        self.assertEqual(headers, DAYZ_HEADERS)
        self.assertEqual(rows[0][0], "STR_A")
        self.assertEqual(rows[0][1], "Knife")
        self.assertEqual(rows[0][2], "Knife")
        self.assertEqual(rows[0][11], "Chinese")
        self.assertEqual(rows[0][13], "Portuguese")
        self.assertEqual(rows[0][14], "Chinese Simple")
        self.assertEqual(rows[0][3], "")
        self.assertEqual(rows[0][-1], "")

    def test_write_quotes_every_cell(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "stringtable.csv"

            write_dayz_csv(path, DAYZ_HEADERS, [["STR_A", "Knife", "Knife", "", "", "", "", "", "", "", "", "", "", "", "", ""]])

            expected_header = '"Language","original","english","czech","german","russian","polish","hungarian","italian","spanish","french","chinese","japanese","portuguese","chinesesimp",\n'
            expected_row = '"STR_A","Knife","Knife","","","","","","","","","","","","",\n'
            self.assertEqual(path.read_text(encoding="utf-8"), expected_header + expected_row)

    def test_write_escapes_quotes_and_keeps_trailing_empty_unquoted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "stringtable.csv"

            write_dayz_csv(path, DAYZ_HEADERS, [['STR_A', 'A "sharp" knife', 'Knife', "", "", "", "", "", "", "", "", "", "", "", "", ""]])

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertTrue(lines[0].endswith('"chinesesimp",'))
            self.assertTrue(lines[1].endswith('"",'))
            self.assertIn('"A ""sharp"" knife"', lines[1])

    def test_rows_for_save_drops_empty_rows(self):
        filled = ["STR_A", "Knife", "Knife"] + [""] * (len(DAYZ_HEADERS) - 3)
        empty = [""] * len(DAYZ_HEADERS)

        self.assertEqual(dayz_rows_for_save([empty, filled, empty]), [filled])

    def test_write_skips_empty_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "stringtable.csv"
            filled = ["STR_A", "Knife", "Knife"] + [""] * (len(DAYZ_HEADERS) - 3)
            empty = [""] * len(DAYZ_HEADERS)

            write_dayz_csv(path, DAYZ_HEADERS, [empty, filled, empty])

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn('"STR_A"', lines[1])

    def test_language_code_for_dayz_headers(self):
        self.assertEqual(language_code_for_header("english"), "en")
        self.assertEqual(language_code_for_header("czech"), "cs")
        self.assertEqual(language_code_for_header("hungarian"), "hu")
        self.assertEqual(language_code_for_header("chinesesimp"), "zh-CN")
        self.assertEqual(language_code_for_header("portuguese"), "pt")
        self.assertEqual(source_language_code_for_header("unknown"), "auto")

    def test_row_jobs_skip_empty_source_and_selected_targets(self):
        rows = [
            ["STR_A", "Knife", "Knife", "", "", "", "", "", "", "", "", "", "", "", "", ""],
            ["STR_B", "Empty", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ]

        jobs = build_row_translation_jobs(DAYZ_HEADERS, rows, source_header="english", selected_rows={0, 1}, selected_columns={14})

        self.assertEqual(jobs, [(0, 14, "Knife", "zh-CN")])

    def test_row_jobs_skip_original_when_targets_are_not_selected(self):
        rows = [["STR_A", "Knife", "Knife", "", "", "", "", "", "", "", "", "", "", "", "", ""]]

        jobs = build_row_translation_jobs(DAYZ_HEADERS, rows, source_header="english", selected_rows={0})

        self.assertNotIn((0, 1, "Knife", "auto"), jobs)
        self.assertIn((0, 14, "Knife", "zh-CN"), jobs)

    def test_column_jobs_use_configured_source_column(self):
        rows = [
            ["STR_A", "Knife", "Knife", "", "", "", "", "", "", "", "", "", "", "", "", ""],
            ["STR_B", "Empty", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ]

        jobs = build_column_translation_jobs(DAYZ_HEADERS, rows, source_header="english", selected_columns={13, 14})

        self.assertEqual(jobs, [(0, 13, "Knife", "pt"), (0, 14, "Knife", "zh-CN")])

    def test_copy_column_sources(self):
        self.assertEqual(copy_source_for_header("original"), "english")
        self.assertEqual(copy_source_for_header("chinese"), "chinesesimp")
        self.assertIsNone(copy_source_for_header("english"))
        self.assertIsNone(copy_source_for_header("russian"))

    def test_is_copy_only_column(self):
        self.assertTrue(is_copy_only_column("original"))
        self.assertTrue(is_copy_only_column("chinese"))
        self.assertFalse(is_copy_only_column("chinesesimp"))
        self.assertFalse(is_copy_only_column("english"))

    def test_row_jobs_skip_chinese_copy_only_column(self):
        rows = [["STR_A", "Knife", "Knife", "", "", "", "", "", "", "", "", "", "", "", "", ""]]

        jobs = build_row_translation_jobs(DAYZ_HEADERS, rows, source_header="english", selected_rows={0})

        job_columns = {job[1] for job in jobs}
        # original (1) and chinese (11) are copy-only columns, must be excluded
        self.assertNotIn(1, job_columns)
        self.assertNotIn(11, job_columns)
        # chinesesimp (14) is a normal translation target
        self.assertIn(14, job_columns)


if __name__ == "__main__":
    unittest.main()
