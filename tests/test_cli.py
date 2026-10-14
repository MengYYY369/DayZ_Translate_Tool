import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cli
from dayz_csv import DAYZ_HEADERS, load_dayz_csv

CSV_TEXT = (
    "Language,original,english,chinesesimp\n"
    "k1,Knife,Knife,\n"
    "k2,Gun,Gun,枪\n"
    "k3,,,\n"
)


def write_csv(text=CSV_TEXT):
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="")
    handle.write(text)
    handle.close()
    return Path(handle.name)


class CliTestCase(unittest.TestCase):
    def setUp(self):
        # 单测不读本机注册表里的真实配置（否则断言会随用户机器变），统一用默认值
        self._original_load_settings = cli.flow.load_app_settings
        cli.flow.load_app_settings = lambda *args, **kwargs: cli.flow.AppSettings()

    def tearDown(self):
        cli.flow.load_app_settings = self._original_load_settings

    def run_cli(self, *argv):
        """跑一次命令行，返回 (退出码, stdout 文本, stderr 文本)。"""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def run_json(self, *argv):
        code, out, _err = self.run_cli(*argv)
        return code, json.loads(out)


class InspectTests(CliTestCase):
    def test_counts_each_language_column(self):
        path = write_csv()
        code, payload = self.run_json("inspect", str(path), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["rows"], 3)
        columns = {item["header"]: item for item in payload["data"]["columns"]}
        self.assertEqual(columns["chinesesimp"]["translated"], 1)
        self.assertEqual(columns["chinesesimp"]["empty"], 2)
        self.assertEqual(columns["chinesesimp"]["language"], "zh-CN")

    def test_reports_rows_without_source_text(self):
        path = write_csv()
        _code, payload = self.run_json("inspect", str(path), "--json")
        self.assertEqual(payload["data"]["rows_missing_source"], [3])

    def test_text_output_is_readable(self):
        path = write_csv()
        code, out, _err = self.run_cli("inspect", str(path))
        self.assertEqual(code, 0)
        self.assertIn("chinesesimp", out)

    def test_missing_file_is_exit_2(self):
        code, _out, err = self.run_cli("inspect", "no-such-file.csv")
        self.assertEqual(code, 2)
        self.assertIn("error", err)


class ParseHelperTests(unittest.TestCase):
    def test_parse_rows_supports_ranges(self):
        self.assertEqual(cli.parse_rows("3,5-7"), [3, 5, 6, 7])

    def test_parse_rows_rejects_zero(self):
        with self.assertRaises(cli.CliError):
            cli.parse_rows("0")

    def test_resolve_columns_by_header_and_language_code(self):
        headers = ["Language", "original", "english", "chinesesimp"]
        self.assertEqual(cli.resolve_columns(headers, "chinesesimp"), [3])
        self.assertEqual(cli.resolve_columns(headers, "zh-CN"), [3])

    def test_resolve_columns_unknown(self):
        with self.assertRaises(cli.CliError):
            cli.resolve_columns(["Language", "english"], "nope")

    def test_resolve_columns_is_case_insensitive(self):
        headers = ["Language", "original", "english", "chinesesimp"]
        self.assertEqual(cli.resolve_columns(headers, "ZH-cn"), [3])

    def test_resolve_columns_ambiguous_language_code_lists_candidates(self):
        # 真实表头下 chinese(11) 与 chinesesimp(14) 都是 zh-CN，不能猜
        with self.assertRaises(cli.CliError) as caught:
            cli.resolve_columns(DAYZ_HEADERS, "zh-CN")
        message = str(caught.exception)
        self.assertIn("chinese", message)
        self.assertIn("chinesesimp", message)

    def test_resolve_columns_on_the_real_table(self):
        # load_dayz_csv 会把表头归一化成 16 列，chinesesimp 在下标 14
        self.assertEqual(cli.resolve_columns(DAYZ_HEADERS, "chinesesimp"), [14])
        self.assertEqual(cli.resolve_columns(DAYZ_HEADERS, "english"), [2])


class _FakeStore:
    """顶替翻译缓存：只碰给定的那个临时文件。"""

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        return {}

    def save(self, cache):
        pass

    def clear(self):
        Path(self.path).unlink(missing_ok=True)

    def is_writable(self):
        return True


class FakeConfig:
    def __init__(self, label="fake"):
        self.label = label
        self.provider = "fake"


class TranslateTests(CliTestCase):
    def setUp(self):
        self.calls = []

        def fake_run(raw_jobs, configs, source_header, **kwargs):
            from translator_service import TranslationResults

            self.calls.append({"jobs": list(raw_jobs), "configs": configs, "source": source_header})
            results = TranslationResults()
            for row, column, text, _target in raw_jobs:
                if text == "Gun":
                    continue                      # 故意留一条失败
                results.cell_results[(row, column)] = f"[{text}]"
                results.translated += 1
            results.failed = len(raw_jobs) - len(results.cell_results)
            results.errors.append("boom")
            return results

        self._original = cli.flow.run_translation
        cli.flow.run_translation = fake_run
        self._original_configs = cli.flow.build_translation_configs
        cli.flow.build_translation_configs = lambda *a, **k: [FakeConfig()]
        # 本类有自己的 setUp（没调 super()），所以配置打桩也要自己来一遍
        self._original_load_settings = cli.flow.load_app_settings
        cli.flow.load_app_settings = lambda *args, **kwargs: cli.flow.AppSettings()
        # 别让单测去读写用户本机的真缓存
        self._cache_folder = tempfile.TemporaryDirectory()
        self._original_store = cli.make_cache_store
        cli.make_cache_store = lambda: _FakeStore(Path(self._cache_folder.name) / "cache.json")

    def tearDown(self):
        cli.flow.run_translation = self._original
        cli.flow.build_translation_configs = self._original_configs
        cli.flow.load_app_settings = self._original_load_settings
        cli.make_cache_store = self._original_store
        self._cache_folder.cleanup()

    def test_preview_is_written_without_write(self):
        path = write_csv()
        code, payload = self.run_json("translate", str(path), "--mode", "all", "--json")
        self.assertEqual(code, 1)                                   # 有一条翻失败了
        self.assertFalse(payload["ok"])                              # 信封里也不能写 ok
        preview = Path(payload["data"]["preview"])
        self.assertTrue(preview.exists())
        self.assertIn("[Knife]", preview.read_text(encoding="utf-8"))
        self.assertNotIn("[Knife]", path.read_text(encoding="utf-8"))  # 原文件没动
        self.assertEqual(payload["data"]["failed_cells"][0]["row"], 2)
        self.assertEqual(payload["data"]["failed_cells"][0]["header"], "czech")

    def test_write_backs_up_and_saves(self):
        path = write_csv()
        code, payload = self.run_json("translate", str(path), "--mode", "all", "--write", "--json")
        self.assertEqual(code, 1)
        self.assertTrue(payload["data"]["written"])
        self.assertTrue(Path(payload["data"]["backup"]).exists())
        self.assertIn("[Knife]", path.read_text(encoding="utf-8"))

    def test_custom_preview_path(self):
        path = write_csv()
        target = path.with_name("custom.csv")
        _code, payload = self.run_json("translate", str(path), "--preview", str(target), "--json")
        self.assertEqual(payload["data"]["preview"], str(target))

    def test_mode_all_ignores_existing_translation(self):
        path = write_csv()
        self.run_json("translate", str(path), "--mode", "all", "--json")
        # load_dayz_csv 把表头归一化成 16 列，chinesesimp 是下标 14
        self.assertIn((1, 14, "Gun", "zh-CN"), self.calls[0]["jobs"])

    def test_mode_empty_skips_existing_translation(self):
        path = write_csv()
        self.run_json("translate", str(path), "--json")
        jobs = self.calls[0]["jobs"]
        self.assertIn((0, 14, "Knife", "zh-CN"), jobs)        # 空格要翻
        self.assertNotIn((1, 14, "Gun", "zh-CN"), jobs)       # 已有译文不翻

    def test_from_column_override(self):
        path = write_csv()
        self.run_json("translate", str(path), "--from-column", "chinesesimp", "--json")
        self.assertEqual(self.calls[0]["source"], "chinesesimp")

    def test_unknown_from_column_is_exit_2(self):
        path = write_csv()
        code, _out, err = self.run_cli("translate", str(path), "--from-column", "klingon")
        self.assertEqual(code, 2)

    def test_no_source_configured_is_exit_2(self):
        path = write_csv()
        cli.flow.build_translation_configs = lambda *a, **k: []
        code, _out, err = self.run_cli("translate", str(path))
        self.assertEqual(code, 2)
        self.assertIn("source", err)

    def test_no_jobs_is_exit_0(self):
        path = write_csv("Language,original,english,chinesesimp\n")
        code, payload = self.run_json("translate", str(path), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["jobs"], 0)

    def test_rows_out_of_range_is_exit_2(self):
        path = write_csv()
        code, _out, err = self.run_cli("translate", str(path), "--rows", "99")
        self.assertEqual(code, 2)
        self.assertIn("row out of range", err)
        # 区间里只越界一半也要报错，不能静默只翻前面那几行
        code, _out, err = self.run_cli("translate", str(path), "--rows", "2-99")
        self.assertEqual(code, 2)
        self.assertIn("row out of range", err)

    def test_preview_must_not_point_at_the_source_file(self):
        path = write_csv()
        code, _out, err = self.run_cli("translate", str(path), "--preview", str(path))
        self.assertEqual(code, 2)
        self.assertIn("--preview", err)
        self.assertIn("Knife", path.read_text(encoding="utf-8"))    # 原文件一字未动
        # 换个写法指回同一个文件也得拦住
        same = path.parent / "." / path.name
        code, _out, _err = self.run_cli("translate", str(path), "--preview", str(same))
        self.assertEqual(code, 2)
        self.assertIn("Knife", path.read_text(encoding="utf-8"))
