import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dayz_translate_tool.scanner import scan_translation_keys


class ScannerTests(unittest.TestCase):
    def test_scan_file_extracts_dollar_and_hash_keys_without_duplicates(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.cpp"
            path.write_text(
                'displayName="$STR_Test_A";\n'
                'descriptionShort="#STR_Test_B";\n'
                'again="$STR_Test_A";\n'
                'plain="not a key";\n',
                encoding="utf-8",
            )

            keys = scan_translation_keys(path)

        self.assertEqual(["STR_Test_A", "STR_Test_B"], keys)

    def test_scan_directory_ignores_unreadable_or_binary_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts" / "item.c").write_text('$STR_Item_Name "#STR_Item_Desc"', encoding="utf-8")
            (root / "image.bin").write_bytes(b"\x00\x01\x02$STR_Not_Text\xff")

            keys = scan_translation_keys(root)

        self.assertEqual(["STR_Item_Name", "STR_Item_Desc"], keys)


if __name__ == "__main__":
    unittest.main()
