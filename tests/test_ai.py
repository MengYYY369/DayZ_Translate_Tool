import unittest

from dayz_translate_tool.ai import (
    AITranslator,
    BatchTranslationResult,
    TranslationRequest,
    build_translation_prompt,
)
from dayz_translate_tool.stringtable import StringTable


class FakeTranslator(AITranslator):
    def __init__(self):
        self.requests = []

    def translate(self, request: TranslationRequest) -> str:
        self.requests.append(request)
        return f"{request.target_language}:{request.source_text}"


class AITests(unittest.TestCase):
    def test_prompt_for_existing_translation_requests_optimization(self):
        request = TranslationRequest(
            key="STR_Test",
            source_language="english",
            source_text="Death Gun Belt",
            target_language="chinesesimp",
            current_target_text="死枪腰带",
        )

        prompt = build_translation_prompt(request)

        self.assertIn("优化当前翻译", prompt)
        self.assertIn("Death Gun Belt", prompt)
        self.assertIn("死枪腰带", prompt)

    def test_batch_translation_updates_only_target_column_and_autosaves_every_n_rows(self):
        table = StringTable(
            ["Language", "english", "chinesesimp", ""],
            [
                ["STR_A", "Alpha", "", ""],
                ["STR_B", "", "", ""],
                ["STR_C", "Charlie", "旧译文", ""],
                ["STR_D", "Delta", "", ""],
            ],
        )
        saves = []

        result = table.translate_rows(
            row_indices=[0, 1, 2, 3],
            source_column="english",
            target_column="chinesesimp",
            translator=FakeTranslator(),
            autosave_every=2,
            save_callback=lambda current_table: saves.append(current_table.get_cell(0, "chinesesimp")),
        )

        self.assertEqual(BatchTranslationResult(translated=3, skipped=1, failed=[]), result)
        self.assertEqual("chinesesimp:Alpha", table.get_cell(0, "chinesesimp"))
        self.assertEqual("", table.get_cell(1, "chinesesimp"))
        self.assertEqual("chinesesimp:Charlie", table.get_cell(2, "chinesesimp"))
        self.assertEqual("chinesesimp:Delta", table.get_cell(3, "chinesesimp"))
        self.assertEqual(2, len(saves))


if __name__ == "__main__":
    unittest.main()
