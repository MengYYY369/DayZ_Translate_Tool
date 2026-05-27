import sys
import types
import unittest


def install_fake_ttkbootstrap() -> None:
    fake_ttk = types.ModuleType("ttkbootstrap")
    fake_ttk.Window = object
    constants = types.ModuleType("ttkbootstrap.constants")
    for name in ["BOTH", "DISABLED", "END", "LEFT", "NORMAL", "RIGHT", "X", "Y"]:
        setattr(constants, name, name.lower())
    sys.modules.setdefault("ttkbootstrap", fake_ttk)
    sys.modules.setdefault("ttkbootstrap.constants", constants)


install_fake_ttkbootstrap()

from dayz_translate_tool.ai import AzureTranslator, BingFreeTranslator, YandexFreeTranslator
from dayz_translate_tool.app import CHECKED_TEXT, DayZTranslateApp, UNCHECKED_TEXT, format_select_all_heading, format_translation_task_summary, shell_page_keys, shell_page_title


class ValueVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class AppUiTests(unittest.TestCase):
    def test_translation_task_summary_includes_rows_targets_and_total_items(self):
        summary = format_translation_task_summary(12, ["german", "chinesesimp"])

        self.assertEqual("选中 12 行 · 目标 2 列 · 预计 24 项", summary)

    def test_translation_task_summary_handles_empty_selection(self):
        summary = format_translation_task_summary(0, [])

        self.assertEqual("选中 0 行 · 目标 0 列 · 预计 0 项", summary)

    def test_select_all_heading_reflects_visible_row_state(self):
        self.assertEqual(UNCHECKED_TEXT, format_select_all_heading([], {0, 1}))
        self.assertEqual(UNCHECKED_TEXT, format_select_all_heading([0, 1], set()))
        self.assertEqual(UNCHECKED_TEXT, format_select_all_heading([0, 1], {0}))
        self.assertEqual(CHECKED_TEXT, format_select_all_heading([0, 1], {0, 1, 2}))

    def test_shell_pages_match_winui_navigation_order(self):
        self.assertEqual(("translate", "settings", "glossary"), shell_page_keys())
        self.assertEqual("Translate", shell_page_title("translate"))

    def test_create_translator_supports_new_backends(self):
        cases = [
            ("azure", AzureTranslator),
            ("bing_free", BingFreeTranslator),
            ("yandex_free", YandexFreeTranslator),
        ]
        for backend, expected_type in cases:
            app = DayZTranslateApp.__new__(DayZTranslateApp)
            app.backend_var = ValueVar(backend)
            app.timeout_var = ValueVar(30)
            app.azure_key_var = ValueVar("secret")
            app.azure_endpoint_var = ValueVar("https://example.cognitiveservices.azure.com")
            app.azure_region_var = ValueVar("eastus")

            translator = app._create_translator()

            self.assertIsInstance(translator, expected_type)


if __name__ == "__main__":
    unittest.main()
