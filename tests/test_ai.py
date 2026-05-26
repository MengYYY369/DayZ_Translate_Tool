import subprocess
import unittest
from unittest.mock import MagicMock, patch

from dayz_translate_tool.ai import (
    AITranslator,
    BatchTranslationResult,
    GoogleTranslateTranslator,
    OpencodeCliTranslator,
    RateLimiter,
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

    def test_multi_target_translation_updates_each_target_column(self):
        table = StringTable(
            ["Language", "english", "german", "chinesesimp", ""],
            [
                ["STR_A", "Alpha", "", "", ""],
                ["STR_B", "", "", "", ""],
            ],
        )

        result = table.translate_rows_multi(
            row_indices=[0, 1],
            source_column="english",
            target_columns=["german", "chinesesimp"],
            translator=FakeTranslator(),
            autosave_every=10,
            max_workers=2,
        )

        self.assertEqual(BatchTranslationResult(translated=2, skipped=2, failed=[]), result)
        self.assertEqual("german:Alpha", table.get_cell(0, "german"))
        self.assertEqual("chinesesimp:Alpha", table.get_cell(0, "chinesesimp"))

    def test_rate_limiter_waits_between_translation_starts(self):
        sleeper = MagicMock()
        limiter = RateLimiter(interval_seconds=0.5, monotonic=lambda: 10.0, sleep=sleeper)

        limiter.wait()
        limiter.wait()

        sleeper.assert_called_once_with(0.5)

    def test_google_translator_parses_response(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'[[["Hallo","Hello",null,null,1]],null,"en"]'
        request = TranslationRequest(
            key="STR_A",
            source_language="english",
            source_text="Hello",
            target_language="german",
        )

        with patch("dayz_translate_tool.ai.urllib.request.urlopen", return_value=response):
            result = GoogleTranslateTranslator(timeout_seconds=10).translate(request)

        self.assertEqual("Hallo", result)

    def test_opencode_translator_uses_run_command_with_prompt_argument(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="译文\n", stderr="")
        request = TranslationRequest(
            key="STR_A",
            source_language="english",
            source_text="Hello",
            target_language="chinesesimp",
        )

        with patch("dayz_translate_tool.ai.subprocess.run", return_value=completed) as run:
            result = OpencodeCliTranslator("opencode", "--model test/model").translate(request)

        command = run.call_args.args[0]
        self.assertEqual("译文", result)
        self.assertEqual(["opencode", "run", "--model", "test/model"], command[:4])
        self.assertIn("源文本: Hello", command[-1])
        self.assertEqual("", run.call_args.kwargs["input"])


if __name__ == "__main__":
    unittest.main()
