import os
import unittest

import translation_flow as flow
from translation_sources import RULE_ALL, RULE_EMPTY, RULE_SELECTION, SourceEntry, SourceList

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HEADERS = ["Language", "original", "english", "chinesesimp"]
ROWS = [
    ["k1", "Knife", "Knife", ""],
    ["k2", "Gun", "Gun", "枪"],
    ["k3", "", "", ""],
]


class FakeSettings:
    """顶替 QSettings：只要 value() 够用。"""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.written = {}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.written[key] = value

    def sync(self):
        pass


COPY_HEADERS = ["Language", "original", "english", "chinesesimp"]
COPY_ROWS = [
    ["k1", "", "Knife", ""],        # original 空 → 填 Knife
    ["k2", "Gun(旧)", "Gun", "枪"],  # original 已有值 → 默认不动
    ["k3", "", "", ""],             # english 也空 → 不填
]


class FillCopyColumnsTests(unittest.TestCase):
    def test_fills_empty_copy_columns(self):
        filled, changed = flow.fill_copy_columns(COPY_HEADERS, COPY_ROWS)
        self.assertTrue(changed)
        self.assertEqual(filled[0][1], "Knife")      # original ← english
        self.assertEqual(filled[2][1], "")           # 源列是空的，不动

    def test_keeps_existing_without_overwrite(self):
        filled, _ = flow.fill_copy_columns(COPY_HEADERS, COPY_ROWS)
        self.assertEqual(filled[1][1], "Gun(旧)")

    def test_overwrite_replaces_existing(self):
        filled, _ = flow.fill_copy_columns(COPY_HEADERS, COPY_ROWS, overwrite=True)
        self.assertEqual(filled[1][1], "Gun")

    def test_chinese_column_copies_from_chinesesimp(self):
        headers = ["Language", "original", "english", "chinese", "chinesesimp"]
        rows = [["k1", "Knife", "Knife", "", "刀"]]
        filled, changed = flow.fill_copy_columns(headers, rows)
        self.assertTrue(changed)
        self.assertEqual(filled[0][3], "刀")          # chinese ← chinesesimp

    def test_row_indexes_limits_scope(self):
        rows = [["k1", "", "Knife", ""], ["k2", "", "Gun", ""]]
        filled, changed = flow.fill_copy_columns(COPY_HEADERS, rows, row_indexes=[0])
        self.assertTrue(changed)
        self.assertEqual(filled[0][1], "Knife")
        self.assertEqual(filled[1][1], "")            # 不在名单里 → 没填

    def test_input_rows_are_not_mutated(self):
        flow.fill_copy_columns(COPY_HEADERS, COPY_ROWS)
        self.assertEqual(COPY_ROWS[0][1], "")


class CollectJobsTests(unittest.TestCase):
    def test_empty_mode_only_takes_empty_targets(self):
        jobs = flow.collect_jobs(HEADERS, ROWS, "english", mode=flow.MODE_EMPTY)
        self.assertEqual(jobs, [(0, 3, "Knife", "zh-CN")])

    def test_all_mode_takes_every_target(self):
        jobs = flow.collect_jobs(HEADERS, ROWS, "english", mode=flow.MODE_ALL)
        self.assertEqual(sorted(jobs), [(0, 3, "Knife", "zh-CN"), (1, 3, "Gun", "zh-CN")])

    def test_columns_mode_needs_columns(self):
        with self.assertRaises(ValueError):
            flow.collect_jobs(HEADERS, ROWS, "english", mode=flow.MODE_COLUMNS)

    def test_rows_mode_needs_rows(self):
        with self.assertRaises(ValueError):
            flow.collect_jobs(HEADERS, ROWS, "english", mode=flow.MODE_ROWS)

    def test_only_empty_filters_all_mode(self):
        jobs = flow.collect_jobs(HEADERS, ROWS, "english", mode=flow.MODE_ALL, only_empty=True)
        self.assertEqual(jobs, [(0, 3, "Knife", "zh-CN")])

    def test_row_indexes_narrow_every_mode(self):
        jobs = flow.collect_jobs(HEADERS, ROWS, "english", mode=flow.MODE_ALL, row_indexes=[0])
        self.assertEqual(jobs, [(0, 3, "Knife", "zh-CN")])

    def test_columns_narrow_every_mode(self):
        # HEADERS 里只有一个可翻译列（下标 3），收窄没收窄看起来一样，所以这条单独换一份
        # 有两个目标列的样本（czech 下标 3 + chinesesimp 下标 4），不然测试是假绿的。
        headers = ["Language", "original", "english", "czech", "chinesesimp"]
        rows = [["k1", "Knife", "Knife", "", ""]]
        for mode in (flow.MODE_ALL, flow.MODE_EMPTY):
            jobs = flow.collect_jobs(headers, rows, "english", mode=mode, columns=[3])
            self.assertEqual(jobs, [(0, 3, "Knife", "cs")], mode)

    def test_columns_mode_takes_the_whole_column(self):
        jobs = flow.collect_jobs(HEADERS, ROWS, "english", mode=flow.MODE_COLUMNS, columns=[3])
        self.assertEqual(sorted(jobs), [(0, 3, "Knife", "zh-CN"), (1, 3, "Gun", "zh-CN")])

    def test_columns_mode_with_rows_narrows_to_those_rows(self):
        jobs = flow.collect_jobs(HEADERS, ROWS, "english", mode=flow.MODE_COLUMNS,
                                 columns=[3], row_indexes=[1])
        self.assertEqual(jobs, [(1, 3, "Gun", "zh-CN")])

    def test_rows_mode_takes_the_whole_row(self):
        jobs = flow.collect_jobs(HEADERS, ROWS, "english", mode=flow.MODE_ROWS, row_indexes=[0])
        self.assertEqual(jobs, [(0, 3, "Knife", "zh-CN")])

    def test_source_row_without_text_is_skipped(self):
        jobs = flow.collect_jobs(HEADERS, ROWS, "english", mode=flow.MODE_ALL)
        self.assertFalse([job for job in jobs if job[0] == 2])      # 第三行没有原文

    def test_empty_selection_means_no_jobs(self):
        # 界面上「一行都没选中」时会传空集合进来（不是 None），这时不能抛错：原行为是
        # 照样填复制列，然后由 run_translation_jobs 弹「没有可翻译的选中单元格」。
        self.assertEqual(flow.collect_jobs(HEADERS, ROWS, "english",
                                          mode=flow.MODE_ROWS, row_indexes=set()), [])
        self.assertEqual(flow.collect_jobs(HEADERS, ROWS, "english",
                                          mode=flow.MODE_COLUMNS, columns=set()), [])

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            flow.collect_jobs(HEADERS, ROWS, "english", mode="nope")


class SourceConfigTests(unittest.TestCase):
    def test_free_source_uses_builtin_concurrency(self):
        entry = SourceEntry(source_id="google", kind="free", rules=[RULE_ALL])
        config = flow.build_source_config(entry)
        self.assertEqual(config.provider, "google")
        self.assertEqual(config.parallel_batches, 2)

    def test_ai_source_uses_entry_settings(self):
        entry = SourceEntry(source_id="ai:1", kind="ai", name="MyAI", api_type="openai",
                            rules=[RULE_ALL], api_key="k", model="m", base_url="u",
                            concurrency=3, interval=0.5)
        config = flow.build_source_config(entry)
        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.label, "MyAI")
        self.assertEqual(config.parallel_batches, 3)
        self.assertEqual(config.min_interval, 0.5)
        self.assertEqual(config.api_key, "k")

    def test_build_translation_configs_follows_rule_and_order(self):
        sources = SourceList([
            SourceEntry(source_id="google", kind="free", rules=[RULE_ALL, RULE_EMPTY]),
            SourceEntry(source_id="lara", kind="free", rules=[RULE_SELECTION]),
            SourceEntry(source_id="ai:1", kind="ai", name="A", api_type="openai", rules=[RULE_ALL]),
        ])
        labels = [c.provider for c in flow.build_translation_configs(sources, RULE_ALL)]
        self.assertEqual(labels, ["google", "openai"])

    def test_build_translation_configs_source_id_filter(self):
        sources = SourceList([
            SourceEntry(source_id="google", kind="free", rules=[RULE_ALL]),
            SourceEntry(source_id="lara", kind="free", rules=[RULE_ALL]),
        ])
        configs = flow.build_translation_configs(sources, RULE_ALL, source_id="lara")
        self.assertEqual([c.provider for c in configs], ["lara"])

    def test_build_translation_configs_unknown_source_id(self):
        sources = SourceList([SourceEntry(source_id="google", kind="free", rules=[RULE_ALL])])
        with self.assertRaises(ValueError):
            flow.build_translation_configs(sources, RULE_ALL, source_id="nope")

    def test_glossary_is_passed_through(self):
        entry = SourceEntry(source_id="ai:1", kind="ai", name="A", api_type="openai", rules=[RULE_ALL])
        glossary = [{"original": "Knife", "chinesesimp": "刀"}]
        config = flow.build_source_config(entry, glossary=glossary, glossary_source_key="english")
        self.assertEqual(config.glossary, glossary)
        self.assertEqual(config.glossary_source_key, "english")


class TestJobTests(unittest.TestCase):
    def test_sample_covers_four_languages_from_english(self):
        jobs = flow.build_test_jobs("english")
        self.assertEqual([job[3] for job in jobs], ["zh-CN", "ru", "ja", "de"])
        self.assertEqual([job[2] for job in jobs], [flow.TEST_TEXT] * 4)

    def test_sample_skips_the_source_language(self):
        # 源列是 chinesesimp（zh-CN）时不能拿 chinese（也是 zh-CN）当样本：
        # MyMemory 会直接拒「翻成同一种语言」，一失败就把整个好用的源判死
        jobs = flow.build_test_jobs("chinesesimp")
        self.assertNotIn("zh-CN", [job[3] for job in jobs])
        self.assertEqual([job[3] for job in jobs], ["ru", "ja", "de"])


class GlossaryTests(unittest.TestCase):
    def test_rows_need_two_columns(self):
        # 词表列序是 WORDBOOK_HEADERS：第 3 列（下标 2）是 czech，不是 chinesesimp
        rows = [["Knife", "", "刀"], ["Gun", "Gun", ""], ["", "", ""]]
        glossary = flow.build_glossary(rows)
        self.assertEqual(glossary, [{"original": "Knife", "czech": "刀"},
                                    {"original": "Gun", "english": "Gun"}])


class AppSettingsTests(unittest.TestCase):
    def test_reads_known_keys(self):
        sources = SourceList([SourceEntry(source_id="google", kind="free", rules=[RULE_ALL])])
        settings = FakeSettings({
            "source_header": "chinesesimp",
            "translation_sources_json": sources.to_json(),
            "translation_char_budget": 800,
            "translation_timeout": 30,
            "ui_language": "zh-CN",
        })
        loaded = flow.load_app_settings(settings)
        self.assertEqual(loaded.source_header, "chinesesimp")
        self.assertEqual(loaded.char_budget, 800)
        self.assertEqual(loaded.timeout, 30.0)
        self.assertEqual([e.source_id for e in loaded.sources.entries], ["google"])

    def test_defaults_when_settings_are_empty(self):
        loaded = flow.load_app_settings(FakeSettings())
        self.assertEqual(loaded.source_header, "english")
        self.assertEqual(loaded.char_budget, flow.DEFAULT_CHAR_BUDGET)
        self.assertEqual(loaded.timeout, 60.0)

    def test_save_sources_writes_one_key(self):
        settings = FakeSettings()
        sources = SourceList([SourceEntry(source_id="google", kind="free", rules=[RULE_ALL])])
        flow.save_sources(sources, settings)
        self.assertIn("translation_sources_json", settings.written)

    def test_config_dir_does_not_add_an_app_layer(self):
        # 早先的写法是先设 org/app 名再问 Qt，结果多出 DayZTranslateTool/DayZTranslateTool
        # 一层，命令行会去读界面永远不看的那份词表。这里钉住：路径里不许出现应用名。
        self.assertNotIn("DayZTranslateTool", str(flow.config_dir()))

        # 「跟界面是同一个目录」这条不在 Task 1 验 —— main.py 这时还没改用 flow 的目录，
        # 两边是各算各的，而 Qt 那个值会随「有没有建过 QApplication」而变，本文件在整套
        # 测试里又是最后才跑，一跑就是红的。等 Task 2 Step 3 把 main.py 接过来之后，
        # 那条断言（test_config_dir_is_the_same_folder_the_gui_uses）才加得进来。

    def test_config_dir_is_the_same_folder_the_gui_uses(self):
        # 两边算出不同目录的话，命令行会去读界面永远不看的那份词表。
        import main
        self.assertEqual(flow.config_dir() / "wordbook.csv", main.DEFAULT_WORDBOOK_PATH)


class ApplyResultsTests(unittest.TestCase):
    def test_writes_cells_back(self):
        from translator_service import TranslationResults

        results = TranslationResults(cell_results={(0, 3): "刀", (9, 9): "越界"})
        rows = flow.apply_results(HEADERS, ROWS, results)
        self.assertEqual(rows[0][3], "刀")
        self.assertEqual(len(rows), 3)                 # 越界的格子直接丢掉

    def test_failed_cells_keeps_input_order(self):
        from translator_service import TranslationResults

        jobs = [(0, 3, "Knife", "zh-CN"), (1, 3, "Gun", "zh-CN")]
        results = TranslationResults(cell_results={(1, 3): "枪"})
        self.assertEqual(flow.failed_cells(jobs, results), [(0, 3)])
