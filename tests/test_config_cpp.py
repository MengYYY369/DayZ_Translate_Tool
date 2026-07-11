import tempfile
import unittest
from pathlib import Path

from dayz_csv import DAYZ_HEADERS
from config_cpp import (
    collect_config_cpp_files,
    extract_keys_from_paths,
    extract_stringtable_keys_from_text,
    merge_language_keys,
)


class ConfigCppTests(unittest.TestCase):
    def test_extract_dollar_and_hash_inside_quotes(self):
        text = 'displayName="$STR_My_CODM_Weapons_LMG_Chopper_RulesOfTheGame0";'
        self.assertEqual(
            extract_stringtable_keys_from_text(text),
            ["STR_My_CODM_Weapons_LMG_Chopper_RulesOfTheGame0"],
        )

    def test_extract_multiple_keys_in_one_string(self):
        text = 'text = "Hello $STR_A and #STR_B end";'
        self.assertEqual(extract_stringtable_keys_from_text(text), ["STR_A", "STR_B"])

    def test_ignores_keys_outside_quotes(self):
        text = 'displayName=$STR_OUT; value="#STR_IN";'
        self.assertEqual(extract_stringtable_keys_from_text(text), ["STR_IN"])

    def test_single_quoted_string(self):
        text = "name = '#STR_SINGLE';"
        self.assertEqual(extract_stringtable_keys_from_text(text), ["STR_SINGLE"])

    def test_dedupe_preserves_first_order(self):
        text = '"$STR_A"; "$STR_B"; "$STR_A";'
        self.assertEqual(extract_stringtable_keys_from_text(text), ["STR_A", "STR_B"])

    def test_merge_skips_existing_language_keys(self):
        existing = [["STR_A", "x"] + [""] * (len(DAYZ_HEADERS) - 2)]
        merged, added, skipped = merge_language_keys(existing, ["STR_A", "STR_B"])
        self.assertEqual(added, 1)
        self.assertEqual(skipped, 1)
        self.assertEqual(merged[0][0], "STR_A")
        self.assertEqual(merged[0][1], "x")
        self.assertEqual(merged[1][0], "STR_B")
        self.assertEqual(merged[1][1:], [""] * (len(DAYZ_HEADERS) - 1))
        self.assertEqual(len(merged[1]), len(DAYZ_HEADERS))

    def test_merge_ignores_blank_existing_language_for_set(self):
        existing = [["", ""] + [""] * (len(DAYZ_HEADERS) - 2)]
        merged, added, skipped = merge_language_keys(existing, ["STR_NEW"])
        self.assertEqual(added, 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(len(merged), 2)

    def test_collect_config_cpp_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "a" / "config.cpp").write_text('"$STR_A";', encoding="utf-8")
            (root / "b.cpp").write_text('"$STR_X";', encoding="utf-8")
            (root / "Config.CPP").write_text('"$STR_B";', encoding="utf-8")
            files = collect_config_cpp_files(root)
            names = {p.name.lower() for p in files}
            self.assertEqual(names, {"config.cpp"})
            keys, warnings = extract_keys_from_paths(files)
            self.assertEqual(set(keys), {"STR_A", "STR_B"})
            self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
