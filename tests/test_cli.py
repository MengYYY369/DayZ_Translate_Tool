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
from translation_sources import RULE_ALL, RULE_EMPTY, RULE_SELECTION, SourceEntry, SourceList

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


class EditTests(CliTestCase):
    def test_set_cell_writes_after_write_flag(self):
        path = write_csv()
        code, payload = self.run_json("edit", "set-cell", str(path), "--row", "2",
                                      "--column", "chinesesimp", "--text", "枪炮", "--write", "--json")
        self.assertEqual(code, 0)
        self.assertIn("枪炮", path.read_text(encoding="utf-8"))
        self.assertEqual(payload["data"]["changes"][0]["row"], 2)

    def test_set_cell_without_write_only_previews(self):
        path = write_csv()
        _code, payload = self.run_json("edit", "set-cell", str(path), "--row", "2",
                                       "--column", "chinesesimp", "--text", "枪炮", "--json")
        self.assertNotIn("枪炮", path.read_text(encoding="utf-8"))
        self.assertIn("枪炮", Path(payload["data"]["preview"]).read_text(encoding="utf-8"))

    def test_set_cell_bad_row_is_exit_2(self):
        path = write_csv()
        code, _out, _err = self.run_cli("edit", "set-cell", str(path), "--row", "99",
                                        "--column", "chinesesimp", "--text", "x")
        self.assertEqual(code, 2)

    def test_replace_all_matches_in_column(self):
        path = write_csv()
        self.run_json("edit", "replace", str(path), "--column", "english",
                      "--find", "Gun", "--replace", "Rifle", "--write", "--json")
        headers, rows, _warnings = load_dayz_csv(path)
        english, original = headers.index("english"), headers.index("original")
        self.assertEqual(rows[1][english], "Rifle")
        self.assertEqual(rows[1][original], "Gun")       # 只动了 english 列

    def test_replace_regex(self):
        path = write_csv()
        _code, payload = self.run_json("edit", "replace", str(path), "--column", "english",
                                       "--find", "Kni.e", "--replace", "Blade", "--regex", "--json")
        self.assertEqual(payload["data"]["changes"][0]["before"], "Knife")

    def test_replace_ignore_case(self):
        path = write_csv()
        _code, payload = self.run_json("edit", "replace", str(path), "--column", "english",
                                       "--find", "gun", "--replace", "Rifle",
                                       "--ignore-case", "--json")
        self.assertEqual(len(payload["data"]["changes"]), 1)

    def test_replace_case_sensitive_by_default(self):
        path = write_csv()
        _code, payload = self.run_json("edit", "replace", str(path), "--column", "english",
                                       "--find", "gun", "--replace", "Rifle", "--json")
        self.assertEqual(payload["data"]["changes"], [])

    def test_replace_whole_word(self):
        path = write_csv("Language,original,english,chinesesimp\nk1,Gun,Gun,\nk2,Gunpowder,Gunpowder,\n")
        _code, payload = self.run_json("edit", "replace", str(path), "--column", "english",
                                       "--find", "Gun", "--replace", "Rifle",
                                       "--whole-word", "--json")
        self.assertEqual(len(payload["data"]["changes"]), 1)

    def test_add_row_appends_with_key(self):
        path = write_csv()
        _code, payload = self.run_json("edit", "add-row", str(path), "--key", "k9", "--write", "--json")
        self.assertEqual(payload["data"]["added_row"], 4)
        self.assertIn("k9", path.read_text(encoding="utf-8"))

    def test_add_row_after_position(self):
        path = write_csv()
        _code, payload = self.run_json("edit", "add-row", str(path), "--key", "k9",
                                       "--after", "1", "--json")
        self.assertEqual(payload["data"]["added_row"], 2)

    def test_delete_row_by_number(self):
        path = write_csv()
        _code, payload = self.run_json("edit", "delete-row", str(path), "--row", "2", "--write", "--json")
        self.assertEqual(payload["data"]["deleted"], ["k2"])
        self.assertNotIn("k2", path.read_text(encoding="utf-8"))

    def test_delete_row_by_key(self):
        path = write_csv()
        _code, payload = self.run_json("edit", "delete-row", str(path), "--key", "k2", "--json")
        self.assertEqual(payload["data"]["deleted"], ["k2"])

    def test_delete_unknown_key_is_exit_2(self):
        path = write_csv()
        code, _out, _err = self.run_cli("edit", "delete-row", str(path), "--key", "nope")
        self.assertEqual(code, 2)

    def test_set_cell_with_several_columns_is_exit_2(self):
        path = write_csv()
        code, _out, err = self.run_cli("edit", "set-cell", str(path), "--row", "2",
                                       "--column", "english,chinesesimp", "--text", "x")
        self.assertEqual(code, 2)
        self.assertIn("one column", err)

    def test_add_row_without_key_is_exit_2(self):
        path = write_csv()
        code, _out, err = self.run_cli("edit", "add-row", str(path), "--write")
        self.assertEqual(code, 2)
        self.assertIn("--key", err)
        _headers, rows, _warnings = load_dayz_csv(path)
        self.assertEqual(len(rows), 3)          # 盘上没多出一行来

    def test_delete_row_with_both_row_and_key_is_exit_2(self):
        path = write_csv()
        code, _out, err = self.run_cli("edit", "delete-row", str(path), "--row", "1", "--key", "k2")
        self.assertEqual(code, 2)
        self.assertIn("not both", err)


CONFIG_CPP = """
class CfgVehicles
{
    class MyCar
    {
        displayName = "$STR_MyCar_Name";
        descriptionShort = "$STR_MyCar_Desc";
        attachments[] = {"$STR_MyCar_Wheel"};
    };
};
"""


class KeysTests(CliTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.cpp = Path(self.folder.name) / "config.cpp"
        self.cpp.write_text(CONFIG_CPP, encoding="utf-8")

    def tearDown(self):
        self.folder.cleanup()

    def test_adds_missing_keys(self):
        # 提取器只认引号里带 $ / # 前缀的键（config_cpp.py:6）
        path = write_csv()
        code, payload = self.run_json("keys", str(path), "--from", str(self.cpp), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["added"], 3)
        self.assertEqual(payload["data"]["keys_found"], 3)

    def test_write_saves_back(self):
        path = write_csv()
        self.run_json("keys", str(path), "--from", str(self.cpp), "--write", "--json")
        self.assertIn("STR_MyCar_Name", path.read_text(encoding="utf-8"))

    def test_skipped_counts_existing(self):
        path = write_csv("Language,original,english,chinesesimp\n"
                         "STR_MyCar_Name,Car,Car,\n")
        _code, payload = self.run_json("keys", str(path), "--from", str(self.cpp), "--json")
        self.assertEqual(payload["data"]["added"], 2)
        self.assertEqual(payload["data"]["skipped"], 1)

    def test_folder_input(self):
        path = write_csv()
        code, payload = self.run_json("keys", str(path), "--from", self.folder.name, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["added"], 3)

    def test_missing_path_is_exit_2(self):
        path = write_csv()
        code, _out, _err = self.run_cli("keys", str(path), "--from", "no-such-path")
        self.assertEqual(code, 2)


WORDBOOK_TEXT = "original,english,chinesesimp\nKnife,Knife,刀\n"


class WordbookTests(CliTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.wordbook = Path(self.folder.name) / "wordbook.csv"
        self.wordbook.write_text(WORDBOOK_TEXT, encoding="utf-8")

    def tearDown(self):
        self.folder.cleanup()

    def test_list(self):
        code, payload = self.run_json("wordbook", "list", "--wordbook", str(self.wordbook), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["count"], 1)

    def test_list_missing_file_is_empty(self):
        missing = Path(self.folder.name) / "nope.csv"
        code, payload = self.run_json("wordbook", "list", "--wordbook", str(missing), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["count"], 0)

    def test_set_updates_existing_row(self):
        code, payload = self.run_json("wordbook", "set", "--wordbook", str(self.wordbook),
                                      "--original", "Knife", "--language", "chinesesimp",
                                      "--text", "匕首", "--json")
        self.assertEqual(code, 0)
        self.assertIn("匕首", self.wordbook.read_text(encoding="utf-8"))
        self.assertEqual(payload["data"]["created"], False)

    def test_set_creates_new_row(self):
        code, payload = self.run_json("wordbook", "set", "--wordbook", str(self.wordbook),
                                      "--original", "Gun", "--language", "chinesesimp",
                                      "--text", "枪", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["created"], True)
        self.assertIn("Gun", self.wordbook.read_text(encoding="utf-8"))

    def test_set_unknown_language_is_exit_2(self):
        code, _out, _err = self.run_cli("wordbook", "set", "--wordbook", str(self.wordbook),
                                        "--original", "Knife", "--language", "klingon", "--text", "x")
        self.assertEqual(code, 2)

    def test_remove(self):
        _code, payload = self.run_json("wordbook", "remove", "--wordbook", str(self.wordbook),
                                       "--original", "Knife", "--json")
        self.assertEqual(payload["data"]["removed"], 1)
        self.assertNotIn("Knife", self.wordbook.read_text(encoding="utf-8"))

    def test_remove_unknown_is_exit_2(self):
        code, _out, _err = self.run_cli("wordbook", "remove", "--wordbook", str(self.wordbook),
                                        "--original", "Nope")
        self.assertEqual(code, 2)

    def test_import_merges(self):
        extra = Path(self.folder.name) / "extra.csv"
        extra.write_text("original,english,chinesesimp\nGun,Gun,枪\n", encoding="utf-8")
        _code, payload = self.run_json("wordbook", "import", str(extra),
                                       "--wordbook", str(self.wordbook), "--json")
        self.assertEqual(payload["data"]["imported"], 1)
        self.assertIn("Gun", self.wordbook.read_text(encoding="utf-8"))

    def test_export(self):
        target = Path(self.folder.name) / "export.csv"
        _code, payload = self.run_json("wordbook", "export", str(target),
                                       "--wordbook", str(self.wordbook), "--json")
        self.assertEqual(payload["data"]["exported"], 1)
        self.assertTrue(target.exists())

    def test_export_creates_the_parent_folder(self):
        target = Path(self.folder.name) / "nope" / "deep" / "export.csv"
        _code, payload = self.run_json("wordbook", "export", str(target),
                                       "--wordbook", str(self.wordbook), "--json")
        self.assertEqual(payload["data"]["exported"], 1)
        self.assertTrue(target.exists())


class FakeSourceSettings:
    """顶替 QSettings：只记 sources 一个键。"""

    def __init__(self, sources=None):
        self.sources = sources or SourceList()
        self.values = {}

    def value(self, key, default=None):
        if key == "translation_sources_json":
            return self.sources.to_json()
        return default

    def setValue(self, key, value):
        self.values[key] = value
        if key == "translation_sources_json":
            self.sources = SourceList.from_json(value)

    def sync(self):
        pass


def _settings_from(fake):
    settings = cli.flow.AppSettings()
    settings.sources = fake.sources
    return settings


class SourcesTests(CliTestCase):
    def setUp(self):
        self.settings = FakeSourceSettings(SourceList([
            SourceEntry(source_id="google", kind="free", rules=[RULE_ALL]),
            SourceEntry(source_id="lara", kind="free", rules=[RULE_SELECTION]),
        ]))
        self._original = cli.flow.load_app_settings
        self._original_save = cli.flow.save_sources
        cli.flow.load_app_settings = lambda settings=None: _settings_from(self.settings)
        cli.flow.save_sources = lambda sources, settings=None: self.settings.setValue(
            "translation_sources_json", sources.to_json())

    def tearDown(self):
        cli.flow.load_app_settings = self._original
        cli.flow.save_sources = self._original_save

    def test_list(self):
        code, payload = self.run_json("sources", "list", "--json")
        self.assertEqual(code, 0)
        self.assertEqual([item["id"] for item in payload["data"]["sources"]], ["google", "lara"])

    def test_add_ai_gets_selection_rule_by_default(self):
        code, payload = self.run_json("sources", "add-ai", "--name", "MyAI",
                                      "--type", "openai", "--key", "k", "--json")
        self.assertEqual(code, 0)
        entry = self.settings.sources.find(payload["data"]["id"])
        self.assertEqual(entry.rules, [RULE_SELECTION])
        self.assertEqual(entry.api_key, "k")

    def test_add_ai_with_rules(self):
        _code, payload = self.run_json("sources", "add-ai", "--name", "MyAI", "--type", "openai",
                                       "--rules", "all,empty", "--json")
        entry = self.settings.sources.find(payload["data"]["id"])
        self.assertEqual(entry.rules, [RULE_ALL, RULE_EMPTY])

    def test_add_ai_bad_type_is_exit_2(self):
        code, _out, _err = self.run_cli("sources", "add-ai", "--name", "X", "--type", "nope")
        self.assertEqual(code, 2)

    def test_remove(self):
        code, payload = self.run_json("sources", "remove", "lara", "--json")
        self.assertEqual(code, 0)
        self.assertIsNone(self.settings.sources.find("lara"))

    def test_remove_reports_restart_required(self):
        # --json 模式下看不到 RESTART_HINT 那段文字，得靠这个字段让 AI 知道要提醒用户重开界面
        _code, payload = self.run_json("sources", "remove", "lara", "--json")
        self.assertTrue(payload["data"]["restart_required"])

    def test_remove_unknown_is_exit_2(self):
        code, _out, _err = self.run_cli("sources", "remove", "nope")
        self.assertEqual(code, 2)

    def test_move_up(self):
        self.run_json("sources", "move", "lara", "--up", "--json")
        self.assertEqual([e.source_id for e in self.settings.sources.entries], ["lara", "google"])

    def test_move_down(self):
        self.run_json("sources", "move", "google", "--down", "--json")
        self.assertEqual([e.source_id for e in self.settings.sources.entries], ["lara", "google"])

    def test_move_both_flags_is_exit_2(self):
        code, _out, _err = self.run_cli("sources", "move", "google", "--up", "--down")
        self.assertEqual(code, 2)

    def test_set_rule_replaces_rules(self):
        self.run_json("sources", "set-rule", "google", "--rules", "empty", "--json")
        self.assertEqual(self.settings.sources.find("google").rules, [RULE_EMPTY])

    def test_set_rule_unknown_rule_is_exit_2(self):
        code, _out, _err = self.run_cli("sources", "set-rule", "google", "--rules", "nope")
        self.assertEqual(code, 2)

    def test_set_key(self):
        self.run_json("sources", "set-key", "lara", "--key", "secret", "--json")
        self.assertEqual(self.settings.sources.find("lara").api_key, "secret")

    def test_test_command_uses_the_entry(self):
        calls = []

        def fake_run(raw_jobs, configs, source_header, **kwargs):
            from translator_service import TranslationResults

            calls.append((list(raw_jobs), configs, source_header))
            results = TranslationResults()
            results.cell_results[(0, 0)] = "刀"
            results.translated = 1
            return results

        original = cli.flow.run_translation
        cli.flow.run_translation = fake_run
        try:
            code, payload = self.run_json("sources", "test", "--source", "google", "--json")
        finally:
            cli.flow.run_translation = original
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["results"][0]["id"], "google")
        self.assertEqual(payload["data"]["results"][0]["translated"], 1)
        self.assertEqual(len(calls[0][0]), 4)          # 四种语言


class CacheTests(CliTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "translation_cache.json"
        self.path.write_text(json.dumps({"version": 1, "entries": {}}), encoding="utf-8")
        self._original = cli.make_cache_store
        cli.make_cache_store = lambda: _FakeStore(self.path)

    def tearDown(self):
        cli.make_cache_store = self._original
        self.folder.cleanup()

    def test_stats_reports_the_path(self):
        code, payload = self.run_json("cache", "stats", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["path"], str(self.path))
        self.assertEqual(payload["data"]["entries"], 0)

    def test_clear_removes_the_file(self):
        code, payload = self.run_json("cache", "clear", "--json")
        self.assertEqual(code, 0)
        self.assertFalse(self.path.exists())
        self.assertTrue(payload["data"]["cleared"])

    def test_clear_that_does_not_delete_is_exit_2(self):
        class StubbornStore(_FakeStore):
            def clear(self):
                pass                      # 删不掉，模拟 TranslationCacheStore 吞掉 OSError 的行为

        cli.make_cache_store = lambda: StubbornStore(self.path)
        code, _out, err = self.run_cli("cache", "clear")
        self.assertEqual(code, 2)
        self.assertIn("could not delete", err)
