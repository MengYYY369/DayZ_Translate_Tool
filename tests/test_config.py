import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dayz_translate_tool.config import AppConfig, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_glossary_entries_round_trip(self):
        config = AppConfig(glossary_entries=[{"source": "rifle", "target": "步枪", "note": "weapon"}])

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_config(config, path)
            loaded = load_config(path)

        self.assertEqual([{"source": "rifle", "target": "步枪", "note": "weapon"}], loaded.glossary_entries)


if __name__ == "__main__":
    unittest.main()
