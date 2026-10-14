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
