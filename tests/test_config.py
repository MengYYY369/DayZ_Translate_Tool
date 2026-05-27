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

    def test_opencode_model_settings_round_trip(self):
        config = AppConfig(
            opencode_port=31319,
            opencode_model="opencode-go/deepseek-v4-flash",
            opencode_models=["opencode-go/deepseek-v4-flash"],
            timeout_seconds=240,
        )

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_config(config, path)
            loaded = load_config(path)

        self.assertEqual(31319, loaded.opencode_port)
        self.assertEqual("opencode-go/deepseek-v4-flash", loaded.opencode_model)
        self.assertEqual(["opencode-go/deepseek-v4-flash"], loaded.opencode_models)
        self.assertEqual(240, loaded.timeout_seconds)

    def test_default_glossary_languages_include_stringtable_languages(self):
        self.assertIn("english", DEFAULT_LANGUAGE_COLUMNS)
        self.assertIn("german", DEFAULT_LANGUAGE_COLUMNS)
        self.assertIn("chinesesimp", DEFAULT_LANGUAGE_COLUMNS)

    def test_scan_and_azure_settings_round_trip(self):
        config = AppConfig(
            ai_backend="azure",
            azure_key="secret",
            azure_endpoint="https://example.cognitiveservices.azure.com",
            azure_region="eastus",
            scan_key_prefixes="STR_, MyMod_",
        )

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_config(config, path)
            loaded = load_config(path)

        self.assertEqual("azure", loaded.ai_backend)
        self.assertEqual("secret", loaded.azure_key)
        self.assertEqual("https://example.cognitiveservices.azure.com", loaded.azure_endpoint)
        self.assertEqual("eastus", loaded.azure_region)
        self.assertEqual("STR_, MyMod_", loaded.scan_key_prefixes)


if __name__ == "__main__":
    unittest.main()
