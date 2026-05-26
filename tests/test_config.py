import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dayz_translate_tool.config import AppConfig, DEFAULT_LANGUAGE_COLUMNS, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_glossary_entries_round_trip(self):
        config = AppConfig(glossary_entries=[{"term": "rifle", "english": "rifle", "chinesesimp": "步枪", "note": "weapon"}])

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_config(config, path)
            loaded = load_config(path)

        self.assertEqual([{"term": "rifle", "english": "rifle", "chinesesimp": "步枪", "note": "weapon"}], loaded.glossary_entries)

    def test_default_glossary_languages_include_stringtable_languages(self):
        self.assertIn("english", DEFAULT_LANGUAGE_COLUMNS)
        self.assertIn("german", DEFAULT_LANGUAGE_COLUMNS)
        self.assertIn("chinesesimp", DEFAULT_LANGUAGE_COLUMNS)


if __name__ == "__main__":
    unittest.main()
