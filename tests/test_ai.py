import subprocess
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from dayz_translate_tool.ai import (
    AITranslator,
    AzureTranslator,
    BatchTranslationResult,
    BingFreeTranslator,
    GoogleTranslateTranslator,
    MultiTranslationRequest,
    OpencodeCliTranslator,
    RateLimiter,
    TranslationRequest,
    YandexFreeTranslator,
    build_multi_translation_prompt,
    build_translation_prompt,
    parse_multi_translation_response,
    list_opencode_models,
    parse_opencode_models_output,
)
from dayz_translate_tool.stringtable import StringTable


class FakeTranslator(AITranslator):
    def __init__(self):
        self.requests = []
        self.multi_requests = []

    def translate(self, request: TranslationRequest) -> str:
        self.requests.append(request)
        return f"{request.target_language}:{request.source_text}"

    def translate_many(self, request: MultiTranslationRequest) -> dict[str, str]:
        self.multi_requests.append(request)
        return {target.target_language: f"{target.target_language}:{request.source_text}" for target in request.targets}


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

    def test_multi_target_translation_calls_translator_once_per_row(self):
        translator = FakeTranslator()
        table = StringTable(
            ["Language", "english", "german", "chinesesimp", ""],
            [["STR_A", "Alpha", "", "", ""]],
        )

        result = table.translate_rows_multi(
            row_indices=[0],
            source_column="english",
            target_columns=["german", "chinesesimp"],
            translator=translator,
            autosave_every=10,
            max_workers=1,
        )

        self.assertEqual(BatchTranslationResult(translated=2, skipped=0, failed=[]), result)
        self.assertEqual(1, len(translator.multi_requests))
        self.assertEqual([], translator.requests)

    def test_multi_target_translation_can_be_cancelled_before_requests_start(self):
        translator = FakeTranslator()
        table = StringTable(
            ["Language", "english", "german", "chinesesimp", ""],
            [["STR_A", "Alpha", "", "", ""]],
        )

        result = table.translate_rows_multi(
            row_indices=[0],
            source_column="english",
            target_columns=["german", "chinesesimp"],
            translator=translator,
            cancel_callback=lambda: True,
        )

        self.assertEqual(BatchTranslationResult(translated=0, skipped=0, failed=[], canceled=True), result)
        self.assertEqual([], translator.multi_requests)

    def test_multi_translation_prompt_requests_json_for_selected_targets(self):
        request = MultiTranslationRequest(
            key="STR_A",
            source_language="english",
            source_text="Alpha",
            targets=[
                TranslationRequest("STR_A", "english", "Alpha", "german"),
                TranslationRequest("STR_A", "english", "Alpha", "chinesesimp", "旧译文"),
            ],
        )

        prompt = build_multi_translation_prompt(request)

        self.assertIn('{"german":"...", "chinesesimp":"..."}', prompt)
        self.assertIn("目标语言列: german, chinesesimp", prompt)
        self.assertIn("chinesesimp=旧译文", prompt)

    def test_parse_multi_translation_response_accepts_json_object(self):
        result = parse_multi_translation_response('```json\n{"german":"Alpha DE","chinesesimp":"阿尔法"}\n```', ["german", "chinesesimp"])

        self.assertEqual({"german": "Alpha DE", "chinesesimp": "阿尔法"}, result)

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

    def test_azure_translator_sends_official_request_and_parses_response(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'[{"translations":[{"text":"Hallo"}]}]'
        request = TranslationRequest(
            key="STR_A",
            source_language="english",
            source_text="Hello",
            target_language="german",
        )

        with patch("dayz_translate_tool.ai.urllib.request.urlopen", return_value=response) as urlopen:
            result = AzureTranslator(
                key="secret",
                endpoint="https://example.cognitiveservices.azure.com",
                region="eastus",
                timeout_seconds=10,
            ).translate(request)

        http_request = urlopen.call_args.args[0]
        body = http_request.data.decode("utf-8")
        self.assertEqual("Hallo", result)
        self.assertIn("/translator/text/v3.0/translate", http_request.full_url)
        self.assertIn("to=de", http_request.full_url)
        self.assertIn('"Text": "Hello"', body)
        self.assertEqual("secret", http_request.headers["Ocp-apim-subscription-key"])
        self.assertEqual("eastus", http_request.headers["Ocp-apim-subscription-region"])

    def test_azure_translator_reports_http_errors(self):
        request = TranslationRequest("STR_A", "english", "Hello", "german")
        error = urllib.error.HTTPError(
            url="https://example.test",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=MagicMock(read=MagicMock(return_value=b"bad key")),
        )

        with patch("dayz_translate_tool.ai.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as context:
                AzureTranslator("bad-key", timeout_seconds=10).translate(request)

        self.assertIn("Azure 翻译请求失败: HTTP 401 bad key", str(context.exception))

    def test_bing_free_translator_parses_response(self):
        auth_response = MagicMock()
        auth_response.__enter__.return_value.read.return_value = b"test-token"
        translate_response = MagicMock()
        translate_response.__enter__.return_value.read.return_value = b'[{"translations":[{"text":"Hallo"}]}]'
        request = TranslationRequest("STR_A", "english", "Hello", "german")

        with patch("dayz_translate_tool.ai.urllib.request.urlopen", side_effect=[auth_response, translate_response]) as urlopen:
            result = BingFreeTranslator(timeout_seconds=10).translate(request)

        auth_request = urlopen.call_args_list[0].args[0]
        translate_request = urlopen.call_args_list[1].args[0]
        self.assertEqual("Hallo", result)
        self.assertEqual("https://edge.microsoft.com/translate/auth", auth_request.full_url)
        self.assertEqual("Bearer test-token", translate_request.headers["Authorization"])

    def test_bing_free_translator_reports_unofficial_source_failures(self):
        request = TranslationRequest("STR_A", "english", "Hello", "german")
        auth_response = MagicMock()
        auth_response.__enter__.return_value.read.return_value = b"test-token"
        error = urllib.error.HTTPError(
            url="https://example.test",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=MagicMock(read=MagicMock(return_value=b"limited")),
        )

        with patch("dayz_translate_tool.ai.urllib.request.urlopen", side_effect=[auth_response, error]):
            with self.assertRaises(RuntimeError) as context:
                BingFreeTranslator(timeout_seconds=10).translate(request)

        self.assertIn("Bing 免费翻译请求失败", str(context.exception))
        self.assertIn("非官方免费源可能失效或被限流", str(context.exception))

    def test_yandex_free_translator_parses_response(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"code":200,"text":["Hallo"]}'
        request = TranslationRequest("STR_A", "english", "Hello", "german")

        with patch("dayz_translate_tool.ai.urllib.request.urlopen", return_value=response) as urlopen:
            result = YandexFreeTranslator(timeout_seconds=10).translate(request)

        http_request = urlopen.call_args.args[0]
        body = http_request.data.decode("utf-8")
        self.assertEqual("Hallo", result)
        self.assertIn("srv=android", http_request.full_url)
        self.assertIn("sid=", http_request.full_url)
        self.assertIn("text=Hello", body)
        self.assertIn("lang=en-de", body)

    def test_yandex_free_translator_reports_unofficial_source_failures(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"code":403,"message":"blocked"}'
        request = TranslationRequest("STR_A", "english", "Hello", "german")

        with patch("dayz_translate_tool.ai.urllib.request.urlopen", return_value=response):
            with self.assertRaises(RuntimeError) as context:
                YandexFreeTranslator(timeout_seconds=10).translate(request)

        self.assertIn("Yandex 免费翻译请求失败", str(context.exception))
        self.assertIn("非官方免费源可能失效或被限流", str(context.exception))

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
        self.assertIn("--print-logs", command)
        self.assertIn("--pure", command)
        self.assertIn("源文本: Hello", command[-1])
        self.assertEqual("", run.call_args.kwargs["input"])

    def test_opencode_translator_does_not_duplicate_stability_flags(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="译文\n", stderr="")
        request = TranslationRequest(
            key="STR_A",
            source_language="english",
            source_text="Hello",
            target_language="chinesesimp",
        )

        with patch("dayz_translate_tool.ai.subprocess.run", return_value=completed) as run:
            OpencodeCliTranslator("opencode", "--print-logs --pure").translate(request)

        command = run.call_args.args[0]
        self.assertEqual(1, command.count("--print-logs"))
        self.assertEqual(1, command.count("--pure"))

    def test_opencode_translator_uses_configured_process_timeout(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="译文\n", stderr="")
        request = TranslationRequest(
            key="STR_A",
            source_language="english",
            source_text="Hello",
            target_language="chinesesimp",
        )

        with patch("dayz_translate_tool.ai.subprocess.run", return_value=completed) as run:
            OpencodeCliTranslator("opencode", timeout_seconds=240).translate(request)

        self.assertEqual(240, run.call_args.kwargs["timeout"])

    def test_opencode_translator_reports_free_model_rate_limit_on_timeout(self):
        request = TranslationRequest(
            key="STR_A",
            source_language="english",
            source_text="Hello",
            target_language="chinesesimp",
        )
        error = subprocess.TimeoutExpired(
            cmd=["opencode", "run"],
            timeout=240,
            stderr='"type":"FreeUsageLimitError","message":"Rate limit exceeded","retry-after":"43222"',
        )

        with patch("dayz_translate_tool.ai.subprocess.run", side_effect=error):
            with self.assertRaises(RuntimeError) as context:
                OpencodeCliTranslator("opencode", timeout_seconds=240).translate(request)

        message = str(context.exception)
        self.assertIn("Opencode 在 240 秒内没有返回", message)
        self.assertIn("free 模型额度已触发限流", message)
        self.assertIn("12.0 小时", message)

    def test_opencode_translator_uses_local_port_and_selected_model_without_attach(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="译文\n", stderr="")
        request = TranslationRequest(
            key="STR_A",
            source_language="english",
            source_text="Hello",
            target_language="chinesesimp",
        )

        with patch("dayz_translate_tool.ai.subprocess.run", return_value=completed) as run:
            OpencodeCliTranslator(
                "opencode",
                port=31319,
                model="opencode-go/deepseek-v4-flash",
            ).translate(request)

        command = run.call_args.args[0]
        self.assertEqual("run", command[1])
        self.assertNotIn("--attach", command)
        self.assertIn("--port", command)
        self.assertIn("31319", command)
        self.assertIn("--model", command)
        self.assertIn("opencode-go/deepseek-v4-flash", command)

    def test_opencode_multi_target_translation_uses_single_target_prompts(self):
        responses = [
            subprocess.CompletedProcess(args=[], returncode=0, stdout="DE\n", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="RU\n", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="PL\n", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="ES\n", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="FR\n", stderr=""),
        ]
        request = MultiTranslationRequest(
            key="STR_A",
            source_language="chinesesimp",
            source_text="测试",
            targets=[
                TranslationRequest("STR_A", "chinesesimp", "测试", "german"),
                TranslationRequest("STR_A", "chinesesimp", "测试", "russian"),
                TranslationRequest("STR_A", "chinesesimp", "测试", "polish"),
                TranslationRequest("STR_A", "chinesesimp", "测试", "spanish"),
                TranslationRequest("STR_A", "chinesesimp", "测试", "french"),
            ],
        )

        with patch("dayz_translate_tool.ai.subprocess.run", side_effect=responses) as run:
            result = OpencodeCliTranslator("opencode").translate_many(request)

        self.assertEqual({"german": "DE", "russian": "RU", "polish": "PL", "spanish": "ES", "french": "FR"}, result)
        self.assertEqual(5, run.call_count)
        prompts = [call.args[0][-1] for call in run.call_args_list]
        self.assertIn("目标语言列: german", prompts[0])
        self.assertIn("目标语言列: russian", prompts[1])
        self.assertNotIn("目标语言列: german, russian", prompts[0])

    def test_opencode_translator_hides_console_window_when_supported(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="译文\n", stderr="")
        request = TranslationRequest(
            key="STR_A",
            source_language="english",
            source_text="Hello",
            target_language="chinesesimp",
        )

        with patch("dayz_translate_tool.ai.subprocess.run", return_value=completed) as run:
            OpencodeCliTranslator("opencode").translate(request)

        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            self.assertEqual(subprocess.CREATE_NO_WINDOW, run.call_args.kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)

    def test_opencode_translator_reports_model_not_found_cleanly(self):
        stderr = '\x1b[91mError:\x1b[0m{"name":"UnknownError","data":{"message":"Model not found: gpt-5.5"}}'
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)
        request = TranslationRequest(
            key="STR_A",
            source_language="english",
            source_text="Hello",
            target_language="chinesesimp",
        )

        with patch("dayz_translate_tool.ai.subprocess.run", return_value=completed):
            with self.assertRaises(RuntimeError) as context:
                OpencodeCliTranslator("opencode").translate(request)

        message = str(context.exception)
        self.assertIn("Model not found: gpt-5.5", message)
        self.assertIn("Run 参数", message)
        self.assertNotIn("\x1b", message)

    def test_parse_opencode_models_output_extracts_provider_model_names(self):
        output = """
        opencode-go/deepseek-v4-flash  DeepSeek V4 Flash
        anthropic/claude-sonnet-4.5
        https://example.test/not-a-model
        """

        models = parse_opencode_models_output(output)

        self.assertEqual(["anthropic/claude-sonnet-4.5", "opencode-go/deepseek-v4-flash"], models)

    def test_list_opencode_models_runs_cli_models_command(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="opencode-go/deepseek-v4-flash\n", stderr="")

        with patch("dayz_translate_tool.ai.subprocess.run", return_value=completed) as run:
            models = list_opencode_models("opencode", refresh=True)

        self.assertEqual(["opencode-go/deepseek-v4-flash"], models)
        self.assertEqual(["opencode", "models", "--refresh"], run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
