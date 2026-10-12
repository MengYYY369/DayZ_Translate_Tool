import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox, QTableWidgetSelectionRange, QTableWidgetItem

from dayz_csv import DAYZ_HEADERS
from main import DayzTranslateTool, LanguageSettingsDialog, SearchDialog, TranslationSettingsDialog, WordbookWindow
from translator_service import TranslationResults


app = QApplication.instance() or QApplication([])


class MainGuiTests(unittest.TestCase):
    def setUp(self):
        self._settings_file = tempfile.NamedTemporaryFile(suffix=".ini", delete=False)
        self._settings_file.close()
        self.settings = QSettings(self._settings_file.name, QSettings.Format.IniFormat)
        self.settings.clear()
        self.settings.sync()
        self.window = DayzTranslateTool(settings=self.settings)
        self._ensure_dayz_table()

    def tearDown(self):
        self.window.close()
        self.settings.clear()
        os.unlink(self._settings_file.name)

    def _ensure_dayz_table(self):
        # Always reset to a deterministic sample table so tests do not depend
        # on the presence of a real stringtable.csv in the working directory.
        self.window.headers = list(DAYZ_HEADERS)
        sample = [
            ["STR_A", "OrigA", "EngA"] + [""] * (len(DAYZ_HEADERS) - 3),
            ["STR_B", "OrigB", "EngB"] + [""] * (len(DAYZ_HEADERS) - 3),
        ]
        self.window.apply_table_rows(sample, dirty=False)
        if self.window.current_path is None:
            self.window.current_path = Path("stringtable.csv")
            self.window.update_current_file_label()

    def test_import_config_requires_loaded_csv(self):
        self.window.headers = []
        self.window.table.setRowCount(0)
        with patch.object(QMessageBox, "warning") as warning:
            self.window.import_from_config_cpp_files()
            warning.assert_called()

    def test_import_config_paths_appends_new_keys_and_sets_dirty(self):
        self.window.apply_table_rows([["STR_EXIST"] + [""] * (len(DAYZ_HEADERS) - 1)], dirty=False)
        before = self.window.table.rowCount()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.cpp"
            path.write_text(
                'displayName="$STR_EXIST";\ndescription="$STR_NEW_FROM_CPP";\n',
                encoding="utf-8",
            )
            self.window._import_config_cpp_paths([path])

        self.assertEqual(self.window.table.rowCount(), before + 1)
        last = self.window.table.item(self.window.table.rowCount() - 1, 0).text()
        self.assertEqual(last, "STR_NEW_FROM_CPP")
        self.assertTrue(self.window.is_dirty)

    def test_window_is_large_and_columns_fit(self):
        self.assertGreaterEqual(self.window.width(), 1600)
        total_width = sum(self.window.table.columnWidth(index) for index in range(self.window.table.columnCount()))
        self.assertLessEqual(total_width, self.window.width())
        self.assertEqual(self.window.table.columnCount(), 15)
        self.assertEqual(self.window.table.horizontalHeaderItem(14).text(), "chinesesimp")

    def test_table_uses_clip_text_delegate_and_tooltip_filter(self):
        """表格使用 _ClipTextDelegate 截断文本不加省略号，并安装 tooltip 拦截过滤器。"""
        from main import _ClipTextDelegate, _NoToolTipFilter

        self.assertIsInstance(self.window.table.itemDelegate(), _ClipTextDelegate)
        self.assertIsInstance(self.window._no_tooltip_filter, _NoToolTipFilter)

    def test_clip_delegate_sets_elide_none_in_style_option(self):
        """_ClipTextDelegate 的 initStyleOption 应设 textElideMode=ElideNone（不加省略号）。"""
        from main import _ClipTextDelegate
        from PySide6.QtWidgets import QStyleOptionViewItem
        from PySide6.QtCore import Qt

        delegate = self.window.table.itemDelegate()
        option = QStyleOptionViewItem()
        delegate.initStyleOption(option, self.window.table.model().index(0, 0))
        self.assertEqual(option.textElideMode, Qt.TextElideMode.ElideNone)

    def test_no_tooltip_filter_intercepts_tooltip_event(self):
        """_NoToolTipFilter 对 ToolTip 事件返回 True（拦截），对其他事件返回 False。"""
        from PySide6.QtCore import QEvent, QPoint
        from PySide6.QtGui import QHelpEvent

        viewport = self.window.table.viewport()
        tooltip_ev = QHelpEvent(QEvent.Type.ToolTip, QPoint(0, 0), viewport.mapToGlobal(QPoint(0, 0)))
        self.assertTrue(self.window._no_tooltip_filter.eventFilter(viewport, tooltip_ev))

        non_tooltip = QHelpEvent(QEvent.Type.Shortcut, QPoint(0, 0), viewport.mapToGlobal(QPoint(0, 0)))
        self.assertFalse(self.window._no_tooltip_filter.eventFilter(viewport, non_tooltip))

    def test_table_rows_restore_hidden_trailing_empty_column(self):
        rows = self.window.table_rows()

        self.assertEqual(len(rows[0]), 16)
        self.assertEqual(rows[0][-1], "")

    def test_search_action_uses_ctrl_f(self):
        self.assertEqual(self.window.search_action.shortcut().toString(), QKeySequence(QKeySequence.Find).toString())

    def test_default_translation_provider_is_google(self):
        self.assertEqual(self.window.translation_provider, "google")
        self.assertEqual(self.window.translation_parallel_batches, 1)

    def test_provider_settings_are_isolated_between_providers(self):
        self.window.translation_provider = "deepl"
        self.window.translation_api_key = "deepl-key"
        self.window.save_translation_settings()

        self.window.translation_provider = "microsoft"
        self.window.translation_api_key = "ms-key"
        self.window.translation_region = "eastus"
        self.window.save_translation_settings()

        self.window.translation_provider = "deepl"
        self.assertEqual(self.window.translation_api_key, "deepl-key")

        self.window.translation_provider = "microsoft"
        self.assertEqual(self.window.translation_api_key, "ms-key")
        self.assertEqual(self.window.translation_region, "eastus")

    def test_dialog_switching_provider_loads_correct_per_provider_settings(self):
        self.window.translation_provider = "deepl"
        self.window.translation_api_key = "deepl-key"
        self.window.save_translation_settings()

        self.window.translation_provider = "microsoft"
        self.window.translation_api_key = "ms-key"
        self.window.save_translation_settings()

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("DeepL")
        self.assertEqual(dialog.api_key_input.text(), "deepl-key")

        dialog.provider_combo.setCurrentText("Microsoft")
        self.assertEqual(dialog.api_key_input.text(), "ms-key")

    def test_dialog_switching_provider_caches_old_provider_fields(self):
        """切换 provider 时对话框字段缓存到内存，不立即写入 window。"""
        self.window.translation_provider = "deepl"
        self.window.translation_api_key = "original-deepl"
        self.window.save_translation_settings()

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("DeepL")
        dialog.api_key_input.setText("changed-deepl")

        # 切换到 Microsoft 前，window 状态不应被修改
        dialog.provider_combo.setCurrentText("Microsoft")
        dialog.api_key_input.setText("ms-key")

        # window 的 provider_settings 在点击"保存"前不应被修改
        self.assertEqual(self.window.get_provider_setting("deepl", "api_key"), "original-deepl")
        # 对话框缓存中保存了修改后的值
        self.assertEqual(dialog._dialog_field_cache["deepl"]["api_key"], "changed-deepl")
        self.assertEqual(dialog._dialog_field_cache["microsoft"]["api_key"], "ms-key")

        # 点击"保存"后写入 window
        dialog.apply_settings()
        self.assertEqual(self.window.get_provider_setting("deepl", "api_key"), "changed-deepl")
        self.assertEqual(self.window.get_provider_setting("microsoft", "api_key"), "ms-key")

    def test_body_context_menu_hides_translation_for_language_column_only(self):
        actions = self.window.context_action_labels(context="cell", row=0, column=0)

        self.assertNotIn("Translate Selected Cells", actions)
        self.assertNotIn("Translate Selected Rows", actions)
        self.assertNotIn("Translate Selected Columns", actions)

    def test_body_context_menu_only_shows_cell_translation(self):
        actions = self.window.context_action_labels(context="cell", row=0, column=2)

        self.assertIn("Translate Selected Cells", actions)
        self.assertNotIn("Translate Selected Rows", actions)
        self.assertNotIn("Translate Selected Columns", actions)

    def test_header_context_menus_show_translation(self):
        row_actions = self.window.context_action_labels(context="row_header", row=0, column=-1)
        column_actions = self.window.context_action_labels(context="column_header", row=-1, column=2)

        self.assertIn("Translate Selected Rows", row_actions)
        self.assertIn("Translate Selected Columns", column_actions)

    def test_context_menus_show_delete_actions(self):
        cell_actions = self.window.context_action_labels(context="cell", row=0, column=2)
        row_actions = self.window.context_action_labels(context="row_header", row=0, column=-1)
        column_actions = self.window.context_action_labels(context="column_header", row=-1, column=2)

        self.assertIn("Delete Cell", cell_actions)
        self.assertIn("Delete Row", row_actions)
        self.assertIn("Delete Column", column_actions)

    def test_search_dialog_has_next_and_smaller_previous_button(self):
        dialog = SearchDialog(self.window)

        self.assertEqual(dialog.next_button.text(), "Next")
        self.assertEqual(dialog.previous_button.text(), "\u2191")
        self.assertEqual(dialog.previous_button.maximumWidth(), dialog.previous_button.maximumHeight())
        self.assertLess(dialog.previous_button.maximumWidth(), dialog.next_button.maximumWidth())

    def test_search_highlight_uses_distinct_readable_colors(self):
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(1, 2, "Knife")
        dialog = SearchDialog(self.window)

        dialog.search_input.setText("Knife")
        dialog.refresh_matches()

        active_color = self.window.table.item(0, 2).background().color()
        match_color = self.window.table.item(1, 2).background().color()
        self.assertEqual(active_color, QColor("#ffc857"))
        self.assertEqual(match_color, QColor("#9adbe8"))
        self.assertNotEqual(active_color, match_color)

    def test_closing_search_dialog_clears_highlight_and_text(self):
        self.window.set_cell_text(0, 2, "Knife")
        dialog = SearchDialog(self.window)
        dialog.search_input.setText("Knife")
        dialog.refresh_matches()

        dialog.close()

        self.assertEqual(self.window.table.item(0, 2).background().color(), QColor())
        self.assertEqual(dialog.search_input.text(), "")

    def test_run_translation_jobs_starts_worker_instead_of_sync_translate(self):
        started = []

        class FakeSignal:
            def __init__(self):
                self.callbacks = []

            def connect(self, callback):
                self.callbacks.append(callback)

        class FakeWorker:
            def __init__(self):
                self.progress = FakeSignal()
                self.finished = FakeSignal()
                self.failed = FakeSignal()

            def moveToThread(self, thread):
                pass

            def run(self):
                started.append(True)

            def cancel(self):
                pass

        self.window.create_translation_worker = lambda jobs: FakeWorker()
        self.window.start_translation_worker([(0, 2, "Knife", "de")], run_immediately=True)

        self.assertTrue(started)
        self.assertTrue(hasattr(self.window, "translation_progress_bar"))
        self.assertTrue(hasattr(self.window, "translation_cancel_button"))

    def test_translate_selected_empty_target_cell_uses_source_language_cell(self):
        captured_jobs = []
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(0, 14, "")
        self.window.table.clearSelection()
        self.window.table.item(0, 14).setSelected(True)
        self.window.run_translation_jobs = lambda jobs, **kwargs: captured_jobs.extend(jobs)

        self.window.translate_selected_cells()

        self.assertEqual(captured_jobs, [(0, 14, "Knife", "zh-CN")])

    def test_right_click_context_menu_selects_target_cell(self):
        self.window.table.clearSelection()
        self.window.set_cell_text(0, 4, "")
        # customContextMenuRequested 传递 viewport 坐标，visualItemRect 也是 viewport 坐标
        center = self.window.table.visualItemRect(self.window.table.item(0, 4)).center()

        with patch.object(self.window, "show_context_menu") as show_menu:
            self.window.open_context_menu(center)
            show_menu.assert_called_once()
            self.assertEqual(show_menu.call_args.args[:3], ("cell", 0, 4))

        selected = [(item.row(), item.column()) for item in self.window.table.selectedItems()]
        self.assertEqual(selected, [(0, 4)])
        self.assertEqual(self.window.table.currentRow(), 0)
        self.assertEqual(self.window.table.currentColumn(), 4)

    def test_right_click_near_cell_right_edge_selects_correct_cell(self):
        """右键点击单元格右边缘时，不应偏移到右边一列。"""
        self.window.table.clearSelection()
        rect = self.window.table.visualItemRect(self.window.table.item(0, 2))
        with patch.object(self.window, "show_context_menu") as show_menu:
            self.window.open_context_menu(rect.center())
            self.assertEqual(show_menu.call_args.args[:3], ("cell", 0, 2))
        self.assertEqual(self.window.table.currentColumn(), 2)

    def test_translate_selected_cells_falls_back_to_current_cell(self):
        captured_jobs = []
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.table.clearSelection()
        self.window.table.setCurrentCell(0, 4)
        self.window.run_translation_jobs = lambda jobs, **kwargs: captured_jobs.extend(jobs)

        self.window.translate_selected_cells()

        self.assertEqual(captured_jobs, [(0, 4, "Knife", "de")])

    def test_finish_translation_shows_errors_when_all_jobs_fail(self):
        results = TranslationResults(translated=0, failed=2, errors=["network down", "timeout"])
        with patch.object(QMessageBox, "warning") as warning:
            self.window.finish_translation(results)
            warning.assert_called()
            self.assertIn("network down", warning.call_args.args[2])

    def test_update_translation_progress_label_shows_failed_count(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()
        results = TranslationResults(translated=2, failed=1, cache_hits=0)
        results.cell_results = {(0, 2): "x"}
        self.window.show_translation_progress(5)
        self.window.update_translation_progress(results)
        self.assertIn("失败 1", self.window.translation_progress_label.text())

    def test_update_translation_progress_label_no_failed_suffix_when_zero_failed(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()
        results = TranslationResults(translated=2, failed=0, cache_hits=0)
        results.cell_results = {(0, 2): "x"}
        self.window.show_translation_progress(5)
        self.window.update_translation_progress(results)
        self.assertNotIn("失败", self.window.translation_progress_label.text())

    def test_finish_translation_cancelled_does_not_fill_progress_bar(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()
        results = TranslationResults(translated=1, failed=0, cache_hits=0)
        results.cancelled = True
        results.cell_results = {}
        self.window.show_translation_progress(5)
        self.window.translation_progress_bar.setValue(2)
        self.window.finish_translation(results)
        self.assertNotEqual(self.window.translation_progress_bar.value(), 5)
        self.assertIn("翻译已取消", self.window.statusBar().currentMessage())

    def test_translation_settings_dialog_saves_provider_and_parallel_batches(self):
        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("DeepL")
        dialog.parallel_batches_input.setValue(3)
        dialog.char_budget_input.setValue(2400)
        dialog.api_key_input.setText("secret")

        dialog.apply_settings()

        self.assertEqual(self.window.translation_provider, "deepl")
        self.assertEqual(self.window.translation_parallel_batches, 3)
        self.assertEqual(self.window.translation_char_budget, 2400)
        self.assertEqual(self.window.translation_api_key, "secret")
        self.assertFalse(hasattr(dialog, "language_combo"))
        self.assertGreaterEqual(dialog.width(), 620)

    def test_translation_settings_batch_and_parallel_have_tooltips(self):
        dialog = TranslationSettingsDialog(self.window)
        self.assertTrue(dialog.char_budget_input.toolTip())
        self.assertTrue(dialog.parallel_batches_input.toolTip())

    def test_translation_settings_auto_save_when_fields_change(self):
        """字段变化不立即写入 window，只有点击"保存"才持久化。"""
        dialog = TranslationSettingsDialog(self.window)

        dialog.provider_combo.setCurrentText("OpenAI")
        dialog.model_input.setText("gpt-test")
        dialog.base_url_input.setText("https://example.test/v1")

        # 编辑期间 window 状态不应被修改
        self.assertNotEqual(self.window.translation_provider, "openai")
        # 对话框字段已更新
        self.assertEqual(dialog.model_input.text(), "gpt-test")
        self.assertEqual(dialog.base_url_input.text(), "https://example.test/v1")

        # 点击"保存"后写入 window
        dialog.apply_settings()
        self.assertEqual(self.window.translation_provider, "openai")
        self.assertEqual(self.window.translation_model, "gpt-test")
        self.assertEqual(self.window.translation_base_url, "https://example.test/v1")

    def test_translation_settings_dialog_shows_fields_for_selected_provider(self):
        dialog = TranslationSettingsDialog(self.window)

        dialog.provider_combo.setCurrentText("Google")
        self.assertFalse(dialog.is_field_visible("api_key"))
        self.assertFalse(dialog.is_field_visible("region"))
        self.assertFalse(dialog.is_field_visible("model"))
        self.assertFalse(dialog.is_field_visible("email"))
        self.assertFalse(dialog.is_field_visible("base_url"))

        dialog.provider_combo.setCurrentText("Microsoft")
        self.assertTrue(dialog.is_field_visible("api_key"))
        self.assertTrue(dialog.is_field_visible("region"))
        self.assertFalse(dialog.is_field_visible("model"))
        self.assertFalse(dialog.is_field_visible("email"))
        self.assertFalse(dialog.is_field_visible("base_url"))

        dialog.provider_combo.setCurrentText("OpenAI")
        self.assertTrue(dialog.is_field_visible("api_key"))
        self.assertFalse(dialog.is_field_visible("region"))
        self.assertTrue(dialog.is_field_visible("model"))
        self.assertFalse(dialog.is_field_visible("email"))
        self.assertTrue(dialog.is_field_visible("base_url"))

    def test_translation_settings_presets_only_visible_for_openai(self):
        dialog = TranslationSettingsDialog(self.window)

        dialog.provider_combo.setCurrentText("Google")
        self.assertFalse(dialog.is_field_visible("preset"))

        dialog.provider_combo.setCurrentText("OpenAI")
        self.assertTrue(dialog.is_field_visible("preset"))

    def test_legacy_chatgpt_provider_is_shown_as_openai(self):
        self.settings.setValue("translation_provider", "chatgpt")
        window = DayzTranslateTool(settings=self.settings)
        dialog = TranslationSettingsDialog(window)

        self.assertEqual(window.translation_provider, "openai")
        self.assertEqual(dialog.provider_combo.currentText(), "OpenAI")
        window.close()

    def test_progress_update_writes_successful_cells_immediately(self):
        self.window.set_cell_text(0, 14, "")
        results = TranslationResults(translated=1, cell_results={(0, 14): "Translated Knife"})

        self.window.update_translation_progress(results)

        self.assertEqual(self.window.table.item(0, 14).text(), "Translated Knife")

    def test_language_setting_switches_main_menu_to_chinese(self):
        dialog = LanguageSettingsDialog(self.window)
        dialog.language_combo.setCurrentText("中文")

        dialog.apply_settings()

        self.assertEqual(self.window.ui_language, "zh")
        self.assertEqual(self.window.menu_file.title(), "文件")
        self.assertEqual(self.window.menu_search.title(), "搜索")
        self.assertEqual(self.window.action_translation_settings.text(), "翻译设置...")
        self.assertEqual(self.window.action_language_settings.text(), "界面语言...")

    def test_chinese_ui_translates_search_dialog_and_context_actions(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()
        dialog = SearchDialog(self.window)

        self.assertEqual(dialog.windowTitle(), "搜索")
        self.assertEqual(dialog.next_button.text(), "下一个")
        self.assertEqual(dialog.count_label.text(), "0 个匹配")
        self.assertEqual(self.window.context_action_labels(context="cell", row=0, column=2)[0], "复制")

    def test_delete_cell_clears_current_cell_text(self):
        self.window.set_cell_text(0, 2, "Knife")
        self.window.table.setCurrentCell(0, 2)
        self.window.set_dirty(False)

        self.window.delete_cell_text()

        self.assertEqual(self.window.table.item(0, 2).text(), "")
        self.assertTrue(self.window.is_dirty)

    def test_context_menu_includes_delete_selected_cells_when_multi_selected(self):
        table = self.window.table
        table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 1, 4), True)

        actions = self.window.context_action_names(context="cell", row=0, column=2)

        self.assertIn("delete_cell", actions)
        self.assertIn("delete_selected_cells", actions)

    def test_context_menu_omits_delete_selected_cells_for_single_cell(self):
        table = self.window.table
        table.clearSelection()
        table.setCurrentCell(0, 2)
        item = table.item(0, 2)
        if item is not None:
            item.setSelected(True)

        actions = self.window.context_action_names(context="cell", row=0, column=2)

        self.assertIn("delete_cell", actions)
        self.assertNotIn("delete_selected_cells", actions)

    def test_delete_selected_cells_clears_all_selected_cells(self):
        table = self.window.table
        self.window.set_cell_text(0, 2, "A")
        self.window.set_cell_text(0, 3, "B")
        self.window.set_cell_text(1, 2, "C")
        self.window.set_cell_text(1, 3, "D")
        self.window.set_cell_text(0, 5, "Keep")
        table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 1, 3), True)
        self.window.set_dirty(False)

        self.window.delete_selected_cells()

        self.assertEqual(table.item(0, 2).text(), "")
        self.assertEqual(table.item(0, 3).text(), "")
        self.assertEqual(table.item(1, 2).text(), "")
        self.assertEqual(table.item(1, 3).text(), "")
        self.assertEqual(table.item(0, 5).text(), "Keep")
        self.assertTrue(self.window.is_dirty)

    def test_delete_selected_cells_clears_empty_items_in_range(self):
        table = self.window.table
        self.window.set_cell_text(0, 2, "A")
        table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 1, 2), True)
        self.window.set_dirty(False)

        self.window.delete_selected_cells()

        self.assertEqual(self.window.table.item(0, 2).text(), "")
        self.assertEqual(self.window.table.item(1, 2).text(), "")
        self.assertTrue(self.window.is_dirty)

    def test_delete_selected_cells_chinese_label(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()
        self.window.table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 1, 3), True)

        labels = self.window.context_action_labels(context="cell", row=0, column=2)

        self.assertIn("删除选中单元格", labels)

    def test_fill_row_with_cell_fills_empty_cells_after_first_column(self):
        table = self.window.table
        self.window.set_cell_text(0, 0, "STR_KEY")
        self.window.set_cell_text(0, 1, "")
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(0, 3, "")
        self.window.set_cell_text(0, 4, "Existing")
        table.setCurrentCell(0, 2)
        self.window.set_dirty(False)

        self.window.fill_row_with_cell()

        self.assertEqual(table.item(0, 0).text(), "STR_KEY")
        self.assertEqual(table.item(0, 1).text(), "Knife")
        self.assertEqual(table.item(0, 2).text(), "Knife")
        self.assertEqual(table.item(0, 3).text(), "Knife")
        self.assertEqual(table.item(0, 4).text(), "Existing")
        self.assertTrue(self.window.is_dirty)

    def test_fill_row_with_cell_skips_first_column_even_when_target_empty(self):
        table = self.window.table
        self.window.set_cell_text(0, 0, "")
        self.window.set_cell_text(0, 1, "")
        self.window.set_cell_text(0, 2, "Knife")
        table.setCurrentCell(0, 2)
        self.window.set_dirty(False)

        self.window.fill_row_with_cell()

        self.assertEqual(table.item(0, 0).text(), "")
        self.assertEqual(table.item(0, 1).text(), "Knife")

    def test_fill_row_with_cell_does_nothing_when_source_empty(self):
        table = self.window.table
        self.window.set_cell_text(0, 1, "")
        self.window.set_cell_text(0, 2, "")
        table.setCurrentCell(0, 2)
        self.window.set_dirty(False)

        self.window.fill_row_with_cell()

        self.assertEqual(table.item(0, 1).text(), "")
        self.assertFalse(self.window.is_dirty)

    def test_fill_row_with_cell_appears_in_cell_context_menu(self):
        actions = self.window.context_action_names(context="cell", row=0, column=2)

        self.assertIn("fill_row_with_cell", actions)

    def test_fill_row_with_cell_has_chinese_label(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()

        labels = self.window.context_action_labels(context="cell", row=0, column=2)

        self.assertIn("以该单元格填充整行", labels)

    def test_delete_row_removes_current_row_without_leaving_empty_row(self):
        self.window.table.setRowCount(2)
        self.window.set_cell_text(0, 1, "First")
        self.window.set_cell_text(1, 1, "Second")
        self.window.table.selectRow(0)
        self.window.set_dirty(False)

        self.window.delete_rows()

        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertEqual(self.window.table.item(0, 1).text(), "Second")
        self.assertTrue(self.window.is_dirty)

    def test_insert_row_above_inserts_blank_row_before_current(self):
        self.window.table.setRowCount(2)
        self.window.set_cell_text(0, 1, "First")
        self.window.set_cell_text(1, 1, "Second")
        self.window.table.setCurrentCell(1, 1)
        self.window.set_dirty(False)

        self.window.insert_row_above()

        self.assertEqual(self.window.table.rowCount(), 3)
        self.assertEqual(self.window.table.item(0, 1).text(), "First")
        self.assertEqual(self.window.table.item(1, 1).text(), "")
        self.assertEqual(self.window.table.item(2, 1).text(), "Second")
        self.assertTrue(self.window.is_dirty)

    def test_insert_row_below_inserts_blank_row_after_current(self):
        self.window.table.setRowCount(2)
        self.window.set_cell_text(0, 1, "First")
        self.window.set_cell_text(1, 1, "Second")
        self.window.table.setCurrentCell(0, 1)
        self.window.set_dirty(False)

        self.window.insert_row_below()

        self.assertEqual(self.window.table.rowCount(), 3)
        self.assertEqual(self.window.table.item(0, 1).text(), "First")
        self.assertEqual(self.window.table.item(1, 1).text(), "")
        self.assertEqual(self.window.table.item(2, 1).text(), "Second")
        self.assertTrue(self.window.is_dirty)

    def test_insert_row_above_at_first_row_pushes_existing_down(self):
        self.window.table.setRowCount(1)
        self.window.set_cell_text(0, 1, "Only")
        self.window.table.setCurrentCell(0, 1)
        self.window.set_dirty(False)

        self.window.insert_row_above()

        self.assertEqual(self.window.table.rowCount(), 2)
        self.assertEqual(self.window.table.item(0, 1).text(), "")
        self.assertEqual(self.window.table.item(1, 1).text(), "Only")

    def test_insert_row_actions_appear_only_in_row_header_context(self):
        row_actions = self.window.context_action_names(context="row_header", row=0, column=-1)
        cell_actions = self.window.context_action_names(context="cell", row=0, column=2)

        self.assertIn("insert_row_above", row_actions)
        self.assertIn("insert_row_below", row_actions)
        self.assertNotIn("insert_row_above", cell_actions)
        self.assertNotIn("insert_row_below", cell_actions)

    def test_insert_row_actions_omitted_from_column_header_context(self):
        column_actions = self.window.context_action_names(context="column_header", row=-1, column=2)

        self.assertNotIn("insert_row_above", column_actions)
        self.assertNotIn("insert_row_below", column_actions)

    def test_insert_row_actions_have_chinese_labels(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()

        row_labels = self.window.context_action_labels(context="row_header", row=0, column=-1)

        self.assertIn("在上方插入行", row_labels)
        self.assertIn("在下方插入行", row_labels)

    def test_column_header_context_has_reset_column_order(self):
        column_actions = self.window.context_action_names(context="column_header", row=-1, column=2)

        self.assertIn("reset_column_order", column_actions)

    def test_reset_column_order_has_chinese_label(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()

        column_labels = self.window.context_action_labels(context="column_header", row=-1, column=2)

        self.assertIn("重置列顺序", column_labels)

    def test_main_table_columns_are_movable(self):
        self.assertTrue(self.window.table.horizontalHeader().sectionsMovable())

    def test_wordbook_table_columns_are_movable(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")
            self.assertTrue(wordbook.table.horizontalHeader().sectionsMovable())

    def test_reset_column_order_restores_original_visual_order(self):
        self.window.table.setRowCount(1)
        self.window.set_cell_text(0, 0, "A")
        self.window.set_cell_text(0, 1, "B")
        self.window.set_cell_text(0, 2, "C")
        self.window.table.horizontalHeader().moveSection(0, 2)

        self.assertNotEqual(self.window.table.horizontalHeader().logicalIndex(0), 0)

        self.window.reset_column_order()

        column_count = self.window.table.columnCount()
        for visual_index in range(column_count):
            self.assertEqual(self.window.table.horizontalHeader().logicalIndex(visual_index), visual_index)

    def test_drag_reorder_does_not_change_save_order(self):
        self.window.table.setRowCount(1)
        self.window.set_cell_text(0, 0, "A")
        self.window.set_cell_text(0, 1, "B")
        self.window.set_cell_text(0, 2, "C")
        self.window.table.horizontalHeader().moveSection(0, 2)

        rows = self.window.table_rows()

        self.assertEqual(rows[0][:3], ["A", "B", "C"])

    def test_qt_translators_installed_for_chinese(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()

        self.assertTrue(len(self.window.qt_translators) > 0)

    def test_qt_translators_removed_for_english(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()
        self.window.ui_language = "en"
        self.window.apply_ui_language()

        self.assertEqual(len(self.window.qt_translators), 0)

    def test_delete_column_clears_current_column_including_first_row(self):
        self.window.table.setRowCount(3)
        self.window.set_cell_text(0, 2, "Header value")
        self.window.set_cell_text(1, 2, "Middle")
        self.window.set_cell_text(2, 2, "Bottom")
        self.window.table.setCurrentCell(1, 2)
        self.window.set_dirty(False)

        self.window.delete_column_cells()

        self.assertEqual(self.window.table.item(0, 2).text(), "")
        self.assertEqual(self.window.table.item(1, 2).text(), "")
        self.assertEqual(self.window.table.item(2, 2).text(), "")
        self.assertTrue(self.window.is_dirty)

    def test_delete_column_uses_selected_header_column_over_stale_current_cell(self):
        self.window.table.setRowCount(2)
        self.window.set_cell_text(0, 1, "Keep first row")
        self.window.set_cell_text(1, 1, "Keep this")
        self.window.set_cell_text(0, 2, "Column first row")
        self.window.set_cell_text(1, 2, "Clear this")
        self.window.table.setCurrentCell(1, 1)
        self.window.table.selectColumn(2)

        self.window.delete_column_cells()

        self.assertEqual(self.window.table.item(1, 1).text(), "Keep this")
        self.assertEqual(self.window.table.item(0, 2).text(), "")
        self.assertEqual(self.window.table.item(1, 2).text(), "")

    def test_wordbook_window_starts_with_one_empty_row_and_no_language_column(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")

            self.assertGreaterEqual(wordbook.width(), 1500)
            self.assertEqual(wordbook.table.rowCount(), 1)
            self.assertEqual(wordbook.table.columnCount(), 14)
            self.assertEqual(wordbook.table.horizontalHeaderItem(0).text(), "original")
            self.assertEqual(wordbook.table.horizontalHeaderItem(13).text(), "chinesesimp")

    def test_wordbook_copy_paste_cut_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")
            wordbook.set_cell_text(0, 1, "Knife")
            wordbook.table.setRangeSelected(QTableWidgetSelectionRange(0, 1, 0, 1), True)

            wordbook.copy_selection()

            self.assertEqual(QApplication.clipboard().text(), "Knife")

            wordbook.table.setCurrentCell(1, 1)
            wordbook.paste_selection()

            self.assertEqual(wordbook.table.item(1, 1).text(), "Knife")

            wordbook.table.setRangeSelected(QTableWidgetSelectionRange(1, 1, 1, 1), True)
            wordbook.cut_selection()

            self.assertEqual(wordbook.table.item(1, 1).text(), "")
            self.assertEqual(QApplication.clipboard().text(), "Knife")

    def test_wordbook_context_menu_has_copy_paste_cut_actions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")

            shortcuts = {action.shortcut().toString() for action in wordbook.actions() if not action.shortcut().isEmpty()}
            self.assertIn(QKeySequence(QKeySequence.Copy).toString(), shortcuts)
            self.assertIn(QKeySequence(QKeySequence.Paste).toString(), shortcuts)
            self.assertIn(QKeySequence(QKeySequence.Cut).toString(), shortcuts)

    def test_wordbook_paste_expands_table_when_rows_exceed_current(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")
            QApplication.clipboard().setText("A\tB\nC\tD")
            wordbook.table.setCurrentCell(0, 1)

            wordbook.paste_selection()

            self.assertEqual(wordbook.table.item(0, 1).text(), "A")
            self.assertEqual(wordbook.table.item(0, 2).text(), "B")
            self.assertEqual(wordbook.table.item(1, 1).text(), "C")
            self.assertEqual(wordbook.table.item(1, 2).text(), "D")

    def test_wordbook_gridline_color_is_set(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")

            self.assertIn("gridline-color", wordbook.table.styleSheet())

    def test_main_table_gridline_color_is_set(self):
        self.assertIn("gridline-color", self.window.table.styleSheet())

    def test_wordbook_window_appends_row_when_last_row_is_filled(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")

            wordbook.set_cell_text(0, 1, "Knife")

            self.assertEqual(wordbook.table.rowCount(), 2)
            self.assertEqual(wordbook.table.item(1, 1).text(), "")

    def test_wordbook_rows_skip_trailing_empty_row(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")
            wordbook.set_cell_text(0, 1, "Knife")
            wordbook.set_cell_text(0, 13, "刀")

            rows = wordbook.rows_for_save()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][1], "Knife")
            self.assertEqual(rows[0][13], "刀")

    def test_main_window_opens_wordbook_window(self):
        self.window.open_wordbook_window()

        self.assertIsNotNone(self.window.wordbook_window)
        self.assertTrue(self.window.wordbook_window.isVisible())

    def test_translation_worker_receives_open_wordbook_glossary(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.window.wordbook_window = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")
            self.window.wordbook_window.set_cell_text(0, 1, "Knife")
            self.window.wordbook_window.set_cell_text(0, 3, "Messer")

            worker = self.window.create_translation_worker([])

            self.assertEqual(worker.config.glossary, [{"english": "Knife", "german": "Messer"}])

    def test_wordbook_auto_saves_after_edit_when_path_exists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "wordbook.csv"
            wordbook = WordbookWindow(self.window)
            wordbook.write_current_file(path)

            wordbook.set_cell_text(0, 1, "Knife")
            # auto_save 防抖，手动触发以模拟定时器到期后的写盘。
            wordbook.auto_save()

            text = path.read_text(encoding="utf-8")
            self.assertIn('"Knife"', text)

    def test_wordbook_uses_default_path_for_auto_save(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "wordbook.csv"
            wordbook = WordbookWindow(self.window, wordbook_path=path)

            wordbook.set_cell_text(0, 1, "Knife")
            # auto_save 防抖，手动触发以模拟定时器到期后的写盘。
            wordbook.auto_save()

            self.assertEqual(wordbook.current_path, path)
            self.assertTrue(path.exists())

    def test_wordbook_loads_default_path_on_open(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "wordbook.csv"
            path.write_text('"original","english","czech","german","russian","polish","hungarian","italian","spanish","french","chinese","japanese","portuguese","chinesesimp"\n"","Knife","","Messer","","","","","","","","","",""\n', encoding="utf-8")

            wordbook = WordbookWindow(self.window, wordbook_path=path)

            self.assertEqual(wordbook.table.item(0, 1).text(), "Knife")
            self.assertEqual(wordbook.table.item(0, 3).text(), "Messer")

    def test_main_status_bar_shows_current_file_path(self):
        self.assertIn(str(self.window.current_path), self.window.current_file_label.text())

    def test_main_status_bar_marks_unsaved_after_edit(self):
        self.window.set_dirty(False)

        self.window.set_cell_text(0, 2, "Changed")

        self.assertTrue(self.window.is_dirty)
        self.assertTrue(self.window.current_file_label.text().endswith("*"))

    def test_main_status_bar_clears_unsaved_after_save(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "stringtable.csv"
            self.window.set_cell_text(0, 2, "Changed")

            saved = self.window.write_current_file(path)

            self.assertTrue(saved)
            self.assertFalse(self.window.is_dirty)
            self.assertFalse(self.window.current_file_label.text().endswith("*"))

    def test_wordbook_status_bar_shows_current_file_path_after_save(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "wordbook.csv"
            wordbook = WordbookWindow(self.window)

            wordbook.write_current_file(path)

            self.assertIn(str(path), wordbook.current_file_label.text())

    def test_wordbook_status_bar_keeps_unsaved_marker_when_auto_save_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "wordbook.csv"
            wordbook = WordbookWindow(self.window, wordbook_path=path)

            with patch("main.write_wordbook_csv", side_effect=OSError("blocked")):
                wordbook.set_cell_text(0, 1, "Knife")

            self.assertTrue(wordbook.is_dirty)
            self.assertTrue(wordbook.current_file_label.text().endswith("*"))

    def test_translation_settings_preset_roundtrip(self):
        self.window.save_translation_preset("TestPreset")
        names = self.window.translation_preset_names()
        self.assertIn("TestPreset", names)

    def test_translation_settings_loads_full_preset(self):
        self.window.translation_provider = "openai"
        self.window.translation_char_budget = 12
        self.window.translation_parallel_batches = 3
        self.window.translation_api_key = "key"
        self.window.translation_region = "region"
        self.window.translation_model = "model-a"
        self.window.translation_base_url = "https://a.test/v1"
        self.window.translation_email = "me@example.com"
        self.window.save_translation_preset("OpenAI A")

        self.window.translation_provider = "google"
        self.window.translation_char_budget = 30
        self.window.translation_parallel_batches = 1
        self.window.translation_api_key = ""
        self.window.translation_region = ""
        self.window.translation_model = "model-b"
        self.window.translation_base_url = ""
        self.window.translation_email = ""

        self.window.load_translation_preset("OpenAI A")

        self.assertEqual(self.window.translation_provider, "openai")
        self.assertEqual(self.window.translation_char_budget, 12)
        self.assertEqual(self.window.translation_parallel_batches, 3)
        self.assertEqual(self.window.translation_api_key, "key")
        self.assertEqual(self.window.translation_region, "region")
        self.assertEqual(self.window.translation_model, "model-a")
        self.assertEqual(self.window.translation_base_url, "https://a.test/v1")
        self.assertEqual(self.window.translation_email, "me@example.com")

    def test_translation_settings_deletes_preset(self):
        self.window.save_translation_preset("DeleteMe")

        self.window.delete_translation_preset("DeleteMe")

        self.assertNotIn("DeleteMe", self.window.translation_preset_names())

    def test_preset_combo_switch_auto_loads_values(self):
        self.window.translation_provider = "openai"
        self.window.translation_api_key = "key-a"
        self.window.translation_model = "model-a"
        self.window.translation_base_url = "https://a.test/v1"
        self.window.save_translation_preset("PresetA")

        self.window.translation_api_key = "key-b"
        self.window.translation_model = "model-b"
        self.window.translation_base_url = "https://b.test/v1"
        self.window.save_translation_preset("PresetB")

        # Loading an older preset must overwrite the live provider fields.
        self.window.load_translation_preset("PresetA")
        self.assertEqual(self.window.translation_api_key, "key-a")
        self.assertEqual(self.window.translation_model, "model-a")
        self.assertEqual(self.window.translation_base_url, "https://a.test/v1")

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("OpenAI")

        dialog.auto_load_preset("PresetA")
        self.assertEqual(dialog.api_key_input.text(), "key-a")
        self.assertEqual(dialog.model_input.text(), "model-a")
        self.assertEqual(dialog.base_url_input.text(), "https://a.test/v1")

        dialog.auto_load_preset("PresetB")
        self.assertEqual(dialog.api_key_input.text(), "key-b")
        self.assertEqual(dialog.model_input.text(), "model-b")
        self.assertEqual(dialog.base_url_input.text(), "https://b.test/v1")

    def test_load_translation_preset_overwrites_with_empty_fields(self):
        self.window.translation_provider = "openai"
        self.window.translation_api_key = "keep-me"
        self.window.translation_model = "model-keep"
        self.window.translation_base_url = "https://keep.test/v1"
        self.window.save_translation_preset("FullPreset")

        self.window.translation_api_key = ""
        self.window.translation_model = ""
        self.window.translation_base_url = ""
        self.window.save_translation_preset("EmptyPreset")

        self.window.translation_api_key = "stale"
        self.window.translation_model = "stale-model"
        self.window.translation_base_url = "https://stale.test/v1"
        self.window.load_translation_preset("EmptyPreset")

        self.assertEqual(self.window.translation_api_key, "")
        self.assertEqual(self.window.translation_model, "")
        self.assertEqual(self.window.translation_base_url, "")

    def test_preset_combo_shows_star_when_field_value_changes(self):
        self.window.translation_provider = "openai"
        self.window.translation_api_key = "original-key"
        self.window.translation_model = "original-model"
        self.window.translation_base_url = "https://original.test/v1"
        self.window.save_translation_preset("StarPreset")

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("OpenAI")
        dialog.preset_combo.setCurrentText("StarPreset")
        dialog.auto_load_preset("StarPreset")

        self.assertEqual(dialog.dirty_indicator_label.text(), "")

        dialog.api_key_input.setText("changed-key")

        self.assertTrue(dialog.is_preset_dirty())
        self.assertEqual(dialog.dirty_indicator_label.text(), "*")

    def test_preset_combo_clears_star_after_saving_preset(self):
        self.window.translation_provider = "openai"
        self.window.translation_api_key = "save-key"
        self.window.translation_model = "save-model"
        self.window.translation_base_url = "https://save.test/v1"
        self.window.save_translation_preset("SavePreset")

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("OpenAI")
        dialog.preset_combo.setCurrentText("SavePreset")
        dialog.auto_load_preset("SavePreset")

        dialog.api_key_input.setText("changed-key")
        self.assertTrue(dialog.is_preset_dirty())
        self.assertEqual(dialog.dirty_indicator_label.text(), "*")

        dialog.preset_name_input.setText("SavePreset")
        dialog.save_preset()

        self.assertEqual(dialog.dirty_indicator_label.text(), "")

    def test_preset_load_button_is_removed(self):
        dialog = TranslationSettingsDialog(self.window)
        self.assertFalse(hasattr(dialog, "load_preset_button"))

    def test_loading_preset_does_not_modify_provider_settings(self):
        """加载预设只更新对话框字段，不修改 window 的 provider_settings。"""
        self.window.translation_provider = "openai"
        self.window.translation_api_key = "live-key"
        self.window.translation_model = "live-model"
        self.window.translation_base_url = "https://live.test/v1"
        self.window.save_translation_settings()
        self.window.save_translation_preset("PresetA")

        # 修改 live 值
        self.window.translation_api_key = "modified-key"
        self.window.save_translation_settings()

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("OpenAI")
        dialog.preset_combo.setCurrentText("PresetA")
        dialog.auto_load_preset("PresetA")

        # 对话框显示预设值
        self.assertEqual(dialog.api_key_input.text(), "live-key")
        self.assertEqual(dialog.model_input.text(), "live-model")
        # window 的 provider_settings 不应被预设覆盖
        self.assertEqual(self.window.translation_api_key, "modified-key")

    def test_switching_presets_does_not_overwrite_each_other(self):
        """切换预设不相互覆盖 provider_settings。"""
        self.window.translation_provider = "openai"
        self.window.translation_api_key = "key-a"
        self.window.translation_model = "model-a"
        self.window.save_translation_settings()
        self.window.save_translation_preset("PresetA")

        self.window.translation_api_key = "key-b"
        self.window.translation_model = "model-b"
        self.window.save_translation_settings()
        self.window.save_translation_preset("PresetB")

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("OpenAI")

        # 加载 PresetA
        dialog.preset_combo.setCurrentText("PresetA")
        dialog.auto_load_preset("PresetA")
        self.assertEqual(dialog.api_key_input.text(), "key-a")

        # 加载 PresetB
        dialog.preset_combo.setCurrentText("PresetB")
        dialog.auto_load_preset("PresetB")
        self.assertEqual(dialog.api_key_input.text(), "key-b")

        # 再切回 PresetA，应仍显示 key-a
        dialog.preset_combo.setCurrentText("PresetA")
        dialog.auto_load_preset("PresetA")
        self.assertEqual(dialog.api_key_input.text(), "key-a")

        # window 的 provider_settings 在点击"保存"前不应被修改
        self.assertEqual(self.window.translation_api_key, "key-b")

    def test_cancel_dialog_does_not_persist_edits(self):
        """点击取消不持久化对话框中的编辑。"""
        self.window.translation_provider = "openai"
        self.window.translation_api_key = "original"
        self.window.save_translation_settings()

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("OpenAI")
        dialog.api_key_input.setText("edited")
        dialog.reject()

        self.assertEqual(self.window.translation_api_key, "original")

    def test_cancel_translation_calls_worker_cancel(self):
        """取消翻译按钮调用 worker.cancel()。"""
        from unittest.mock import MagicMock
        worker = MagicMock()
        self.window.translation_worker = worker
        self.window.translation_cancel_button.setEnabled(True)

        self.window.cancel_translation()

        worker.cancel.assert_called_once()
        self.assertFalse(self.window.translation_cancel_button.isEnabled())

    def test_open_csv_remember_last_directory(self):
        import csv
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "subfolder", "test.csv")
            os.makedirs(os.path.dirname(csv_path))
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["key", "original", "english"])
                writer.writerow(["STR_TEST", "Hello", "Hello"])

            self.window.open_csv_from_path(csv_path)
            self.assertEqual(self.window.last_file_directory, os.path.join(tmpdir, "subfolder"))

    def test_save_csv_remember_last_directory(self):
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = os.path.join(tmpdir, "savefolder", "output.csv")
            os.makedirs(os.path.dirname(save_path))
            self.window.save_csv_to_path(save_path)
            self.assertEqual(self.window.last_file_directory, os.path.join(tmpdir, "savefolder"))

    def test_last_file_directory_defaults_to_empty(self):
        self.assertEqual(self.window.last_file_directory, "")

    def test_right_click_preserves_multi_selection(self):
        table = self.window.table
        table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 1, table.columnCount() - 1), True)

        center = table.visualItemRect(table.item(0, 0)).center()
        with patch.object(self.window, "show_context_menu"):
            self.window.open_context_menu(center)

        selected_ranges = table.selectedRanges()
        self.assertGreater(len(selected_ranges), 0)
        total_selected_rows = sum(r.bottomRow() - r.topRow() + 1 for r in selected_ranges)
        self.assertGreater(total_selected_rows, 1)

    def test_right_click_on_unselected_cell_clears_selection(self):
        table = self.window.table
        table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 0, table.columnCount() - 1), True)

        self.window.set_cell_text(1, 0, "Unselected")
        center = table.visualItemRect(table.item(1, 0)).center()
        with patch.object(self.window, "show_context_menu"):
            self.window.open_context_menu(center)

        selected_range = table.selectedRanges()[0]
        self.assertEqual(selected_range.topRow(), 1)
        self.assertEqual(selected_range.bottomRow(), 1)

    def test_right_click_preserves_selection_on_empty_cell(self):
        table = self.window.table
        self.window.set_cell_text(0, 4, "")
        self.window.set_cell_text(1, 4, "")
        table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 1, table.columnCount() - 1), True)

        center = table.visualItemRect(table.item(0, 0)).center()
        with patch.object(self.window, "show_context_menu"):
            self.window.open_context_menu(center)

        selected_ranges = table.selectedRanges()
        self.assertGreater(len(selected_ranges), 0)
        total_selected_rows = sum(r.bottomRow() - r.topRow() + 1 for r in selected_ranges)
        self.assertGreater(total_selected_rows, 1)

    def test_translate_all_cells_creates_jobs_for_all_translatable_cells(self):
        captured_jobs = []
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(1, 2, "Rifle")
        self.window.run_translation_jobs = lambda jobs, **kwargs: captured_jobs.extend(jobs)

        self.window.translate_all_cells()

        self.assertGreater(len(captured_jobs), 0)
        job_positions = [(j[0], j[1]) for j in captured_jobs]
        self.assertIn((0, 3), job_positions)
        self.assertIn((1, 3), job_positions)

    def test_translate_empty_cells_only_translates_blank_targets(self):
        captured_jobs = []
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(1, 2, "Rifle")
        self.window.set_cell_text(0, 3, "Messer")
        self.window.run_translation_jobs = lambda jobs, **kwargs: captured_jobs.extend(jobs)

        self.window.translate_empty_cells()

        job_positions = [(j[0], j[1]) for j in captured_jobs]
        self.assertNotIn((0, 3), job_positions)
        self.assertIn((1, 3), job_positions)

    def test_translate_all_cells_menu_action_exists(self):
        self.assertTrue(hasattr(self.window, "action_translate_all"))
        self.assertTrue(hasattr(self.window, "action_translate_empty"))

    def test_is_translatable_column_excludes_copy_only_columns(self):
        # original (1) and chinese (11) are copy-only, not translatable
        self.assertFalse(self.window.is_translatable_column(1))
        self.assertFalse(self.window.is_translatable_column(11))
        # chinesesimp (14) and german (3) are normal translatable columns
        self.assertTrue(self.window.is_translatable_column(14))
        self.assertTrue(self.window.is_translatable_column(3))

    def test_translate_empty_cells_copies_english_to_original(self):
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(0, 1, "")
        self.window.run_translation_jobs = lambda jobs, **kwargs: None

        self.window.translate_empty_cells()

        self.assertEqual(self.window.table.item(0, 1).text(), "Knife")

    def test_translate_empty_cells_copies_chinesesimp_to_chinese(self):
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(0, 14, "\u5200")
        self.window.run_translation_jobs = lambda jobs, **kwargs: None

        self.window.translate_empty_cells()

        self.assertEqual(self.window.table.item(0, 11).text(), "\u5200")

    def test_translate_empty_cells_skips_copy_columns_in_ai_jobs(self):
        captured_jobs = []
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.run_translation_jobs = lambda jobs, **kwargs: captured_jobs.extend(jobs)

        self.window.translate_empty_cells()

        job_columns = {j[1] for j in captured_jobs}
        self.assertNotIn(1, job_columns)
        self.assertNotIn(11, job_columns)

    def test_translate_all_cells_overwrites_copy_columns(self):
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(0, 1, "OldValue")
        self.window.run_translation_jobs = lambda jobs, **kwargs: None

        self.window.translate_all_cells()

        self.assertEqual(self.window.table.item(0, 1).text(), "Knife")

    def test_translate_selected_rows_copies_english_to_original(self):
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "EngNew")
        self.window.set_cell_text(0, 1, "OldOrig")
        self.window.table.clearSelection()
        self.window.table.selectRow(0)
        self.window.run_translation_jobs = lambda jobs, **kwargs: None

        self.window.translate_selected_rows()

        self.assertEqual(self.window.table.item(0, 1).text(), "EngNew")

    def test_translate_selected_cells_copies_copy_columns_for_row(self):
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(0, 14, "\u5200")
        self.window.set_cell_text(0, 1, "")
        self.window.table.clearSelection()
        self.window.table.item(0, 3).setSelected(True)
        self.window.run_translation_jobs = lambda jobs, **kwargs: None

        self.window.translate_selected_cells()

        self.assertEqual(self.window.table.item(0, 1).text(), "Knife")
        self.assertEqual(self.window.table.item(0, 11).text(), "\u5200")

    def test_second_translation_starts_after_first_finishes(self):
        # 回归：第一次翻译结束后 thread.finished 的 deleteLater 会销毁 C++ 对象，
        # 若窗口未清空旧引用，第二次翻译调用 isRunning() 会访问已销毁对象。
        from translation_worker import TranslationWorker

        class FakeService:
            def translate_jobs(self, jobs, config, progress_callback=None, should_cancel=None):
                results = TranslationResults(translated=len(jobs))
                for job in jobs:
                    results.cell_results[(job.row, job.column)] = job.text
                return results

        self.window.create_translation_worker = lambda jobs: TranslationWorker(FakeService(), jobs, None)

        self.window.start_translation_worker([(0, 4, "Knife", "de")])
        first_thread = self.window.translation_thread
        self.assertIsNotNone(first_thread)
        first_thread.wait(5000)
        # 等待线程清理槽执行完毕（translation_thread 引用被置空）
        deadline = 50
        while self.window.translation_thread is not None and deadline > 0:
            app.processEvents()
            deadline -= 1

        self.assertIsNone(self.window.translation_thread)
        self.assertFalse(self.window._is_translation_running())

        # 第二次翻译同步执行，验证不再访问已销毁的线程对象
        self.window.start_translation_worker([(1, 4, "Axe", "de")], run_immediately=True)

        self.assertEqual(self.window.table.item(0, 4).text(), "Knife")
        self.assertEqual(self.window.table.item(1, 4).text(), "Axe")

    def test_translation_worker_uses_shared_cache(self):
        worker = self.window.create_translation_worker([])
        self.assertIs(worker.service.cache, self.window.translation_cache)

    def test_translate_empty_cells_does_not_overwrite_copy_columns(self):
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(0, 1, "ExistingOriginal")
        self.window.run_translation_jobs = lambda jobs, **kwargs: None

        self.window.translate_empty_cells()

        self.assertEqual(self.window.table.item(0, 1).text(), "ExistingOriginal")

    def test_original_filled_from_translated_english_when_source_is_chinesesimp(self):
        # 源语言为 chinesesimp 时 english 本身是翻译目标，
        # original 必须在翻译写入完成后从新的 english 回填
        from translation_worker import TranslationWorker

        class FakeService:
            def translate_jobs(self, jobs, config, progress_callback=None, should_cancel=None):
                results = TranslationResults(translated=len(jobs))
                for job in jobs:
                    results.cell_results[(job.row, job.column)] = f"EN:{job.text}"
                return results

        self.window.source_header = "chinesesimp"
        self.window.set_cell_text(0, 14, "Dao")
        self.window.set_cell_text(0, 2, "")
        self.window.set_cell_text(0, 1, "")
        self.window.create_translation_worker = lambda jobs: TranslationWorker(FakeService(), jobs, None)

        self.window.start_translation_worker([(0, 2, "Dao", "en"), (0, 3, "Dao", "de")], run_immediately=True)

        self.assertEqual(self.window.table.item(0, 2).text(), "EN:Dao")
        self.assertEqual(self.window.table.item(0, 3).text(), "EN:Dao")
        self.assertEqual(self.window.table.item(0, 1).text(), "EN:Dao")
        self.assertEqual(self.window.table.item(0, 11).text(), "Dao")

    def test_finish_translation_post_fill_does_not_overwrite_existing_copy_columns(self):
        # "翻译空白单元格"语义（copy_overwrite=False）：回填复制列不覆盖已有内容
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(0, 1, "Custom")
        self.window._translation_job_rows = {0}
        self.window._translation_copy_overwrite = False

        self.window.finish_translation(TranslationResults())

        self.assertEqual(self.window.table.item(0, 1).text(), "Custom")

    def test_search_match_whole_word(self):
        self.window.apply_table_rows(
            [["STR_A"] + [""] * (len(DAYZ_HEADERS) - 1)] * 4, dirty=False
        )
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(1, 2, "Sharp Knife")
        self.window.set_cell_text(2, 2, "knife")
        self.window.set_cell_text(3, 2, "Knifeman")

        exact = self.window.find_matches("Knife", whole_word=True, match_case=False)
        self.assertEqual(set(exact), {(0, 2), (1, 2), (2, 2)})

        exact_case = self.window.find_matches("Knife", whole_word=True, match_case=True)
        self.assertEqual(set(exact_case), {(0, 2), (1, 2)})

    def test_search_match_case(self):
        self.window.set_cell_text(0, 2, "Knife")
        self.window.set_cell_text(1, 2, "knife")

        case_sensitive = self.window.find_matches("Knife", whole_word=False, match_case=True)
        self.assertEqual(set(case_sensitive), {(0, 2)})

        case_insensitive = self.window.find_matches("Knife", whole_word=False, match_case=False)
        self.assertEqual(set(case_insensitive), {(0, 2), (1, 2)})

    def test_search_dialog_has_whole_word_and_match_case_checkboxes(self):
        dialog = SearchDialog(self.window)
        self.assertTrue(hasattr(dialog, "match_whole_word_checkbox"))
        self.assertTrue(hasattr(dialog, "match_case_checkbox"))
        self.assertFalse(dialog.match_whole_word_checkbox.isChecked())
        self.assertFalse(dialog.match_case_checkbox.isChecked())

    def test_sort_jobs_by_row_column_orders_single_row_multi_column(self):
        # 1 row, 3 columns → 仍按 (row, column) 排序，便于批次切分与进度展示
        jobs = [(0, 7, "a", "es"), (0, 3, "a", "de"), (0, 5, "a", "ru")]
        ordered = self.window._sort_jobs_by_row_column(jobs)
        self.assertEqual(ordered, sorted(jobs, key=lambda j: (j[0], j[1])))

    def test_sort_jobs_by_row_column_orders_multi_row_single_column(self):
        # 3 rows, 1 column → 按 (row, column) 排序
        jobs = [(2, 3, "c", "de"), (0, 3, "a", "de"), (1, 3, "b", "de")]
        ordered = self.window._sort_jobs_by_row_column(jobs)
        self.assertEqual(ordered, sorted(jobs, key=lambda j: (j[0], j[1])))

    # --- Undo/Redo tests for main table ---

    def test_main_table_undo_restores_previous_cell_value(self):
        self.window.set_cell_text(0, 2, "Modified")
        self.assertEqual(self.window.table.item(0, 2).text(), "Modified")

        self.window.undo()

        self.assertEqual(self.window.table.item(0, 2).text(), "EngA")

    def test_main_table_redo_restores_undone_value(self):
        self.window.set_cell_text(0, 2, "Modified")
        self.window.undo()

        self.window.redo()

        self.assertEqual(self.window.table.item(0, 2).text(), "Modified")

    def test_main_table_undo_after_delete_rows(self):
        self.window.table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 0, 0), True)
        self.window.table.setCurrentCell(0, 0)
        self.assertEqual(self.window.table.rowCount(), 2)

        self.window.delete_rows()
        self.assertEqual(self.window.table.rowCount(), 1)

        self.window.undo()

        self.assertEqual(self.window.table.rowCount(), 2)
        self.assertEqual(self.window.table.item(0, 0).text(), "STR_A")

    def test_main_table_undo_after_insert_row(self):
        self.window.table.setCurrentCell(0, 0)
        self.assertEqual(self.window.table.rowCount(), 2)

        self.window.insert_row_below()
        self.assertEqual(self.window.table.rowCount(), 3)

        self.window.undo()

        self.assertEqual(self.window.table.rowCount(), 2)

    def test_main_table_undo_cut_is_single_step(self):
        self.window.table.setCurrentCell(0, 2)
        self.window.table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 1, 2), True)
        self.window.cut_selection()
        self.assertEqual(self.window.table.item(0, 2).text(), "")
        self.assertEqual(self.window.table.item(1, 2).text(), "")

        self.window.undo()

        self.assertEqual(self.window.table.item(0, 2).text(), "EngA")
        self.assertEqual(self.window.table.item(1, 2).text(), "EngB")

    def test_main_table_undo_paste_is_single_step(self):
        QApplication.clipboard().setText("Pasted1\nPasted2")
        self.window.table.setCurrentCell(0, 2)
        self.window.paste_selection()
        self.assertEqual(self.window.table.item(0, 2).text(), "Pasted1")
        self.assertEqual(self.window.table.item(1, 2).text(), "Pasted2")

        self.window.undo()

        self.assertEqual(self.window.table.item(0, 2).text(), "EngA")
        self.assertEqual(self.window.table.item(1, 2).text(), "EngB")

    def test_main_table_undo_delete_selected_cells_is_single_step(self):
        self.window.table.setCurrentCell(0, 2)
        self.window.table.setRangeSelected(QTableWidgetSelectionRange(0, 2, 1, 2), True)
        self.window.delete_selected_cells()
        self.assertEqual(self.window.table.item(0, 2).text(), "")
        self.assertEqual(self.window.table.item(1, 2).text(), "")

        self.window.undo()

        self.assertEqual(self.window.table.item(0, 2).text(), "EngA")
        self.assertEqual(self.window.table.item(1, 2).text(), "EngB")

    def test_main_table_has_undo_redo_shortcuts(self):
        shortcuts = set()
        for action in self.window.actions():
            for sc in action.shortcuts():
                shortcuts.add(sc.toString())
        self.assertIn(QKeySequence(QKeySequence.Undo).toString(), shortcuts)
        self.assertIn("Ctrl+Shift+Z", shortcuts)

    # --- Undo/Redo tests for wordbook ---

    def test_wordbook_undo_restores_previous_cell_value(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")
            wordbook.set_cell_text(0, 1, "Knife")
            self.assertEqual(wordbook.table.item(0, 1).text(), "Knife")

            wordbook.undo()

            self.assertEqual(wordbook.table.item(0, 1).text(), "")
            wordbook.close()

    def test_wordbook_redo_restores_undone_value(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")
            wordbook.set_cell_text(0, 1, "Knife")
            wordbook.undo()

            wordbook.redo()

            self.assertEqual(wordbook.table.item(0, 1).text(), "Knife")
            wordbook.close()

    def test_wordbook_undo_cut_is_single_step(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")
            wordbook.set_cell_text(0, 1, "Knife")
            wordbook.set_cell_text(0, 2, "Messer")
            wordbook.table.setCurrentCell(0, 1)
            wordbook.table.setRangeSelected(QTableWidgetSelectionRange(0, 1, 0, 2), True)
            wordbook.cut_selection()
            self.assertEqual(wordbook.table.item(0, 1).text(), "")
            self.assertEqual(wordbook.table.item(0, 2).text(), "")

            wordbook.undo()

            self.assertEqual(wordbook.table.item(0, 1).text(), "Knife")
            self.assertEqual(wordbook.table.item(0, 2).text(), "Messer")
            wordbook.close()

    def test_wordbook_undo_paste_is_single_step(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")
            QApplication.clipboard().setText("A\tB")
            wordbook.table.setCurrentCell(0, 1)
            wordbook.paste_selection()
            self.assertEqual(wordbook.table.item(0, 1).text(), "A")
            self.assertEqual(wordbook.table.item(0, 2).text(), "B")

            wordbook.undo()

            self.assertEqual(wordbook.table.item(0, 1).text(), "")
            self.assertEqual(wordbook.table.item(0, 2).text(), "")
            wordbook.close()

    def test_wordbook_has_undo_redo_shortcuts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wordbook = WordbookWindow(self.window, wordbook_path=Path(tmp_dir) / "wordbook.csv")
            shortcuts = set()
            for action in wordbook.actions():
                for sc in action.shortcuts():
                    shortcuts.add(sc.toString())
            self.assertIn(QKeySequence(QKeySequence.Undo).toString(), shortcuts)
            self.assertIn("Ctrl+Shift+Z", shortcuts)
            wordbook.close()

    def test_wordbook_default_path_uses_config_directory(self):
        from main import DEFAULT_WORDBOOK_PATH, APP_DIR
        self.assertNotEqual(DEFAULT_WORDBOOK_PATH.parent, APP_DIR)


if __name__ == "__main__":
    unittest.main()
