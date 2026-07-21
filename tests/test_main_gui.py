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
        self.settings = QSettings("DayZTranslateToolTests", "DayZTranslateToolTests")
        self.settings.clear()
        self.settings.sync()
        self.window = DayzTranslateTool(settings=self.settings)
        self._ensure_dayz_table()

    def tearDown(self):
        self.window.close()
        self.settings.clear()

    def _ensure_dayz_table(self):
        if not (self.window.headers and self.window.table.rowCount() > 0 and self.window.table.columnCount() > 0):
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

    def test_dialog_switching_provider_saves_old_provider_fields(self):
        self.window.translation_provider = "deepl"
        self.window.translation_api_key = "original-deepl"
        self.window.save_translation_settings()

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("DeepL")
        dialog.api_key_input.setText("changed-deepl")

        dialog.provider_combo.setCurrentText("Microsoft")
        dialog.api_key_input.setText("ms-key")

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

        active_color = self.window.table.item(0, 2).background().color()
        match_color = self.window.table.item(1, 2).background().color()
        self.assertEqual(active_color, QColor("#ffc857"))
        self.assertEqual(match_color, QColor("#9adbe8"))
        self.assertNotEqual(active_color, match_color)

    def test_closing_search_dialog_clears_highlight_and_text(self):
        self.window.set_cell_text(0, 2, "Knife")
        dialog = SearchDialog(self.window)
        dialog.search_input.setText("Knife")

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
        self.window.run_translation_jobs = lambda jobs: captured_jobs.extend(jobs)

        self.window.translate_selected_cells()

        self.assertEqual(captured_jobs, [(0, 14, "Knife", "zh-CN")])

    def test_right_click_context_menu_selects_target_cell(self):
        self.window.table.clearSelection()
        self.window.set_cell_text(0, 4, "")
        center = self.window.table.visualItemRect(self.window.table.item(0, 4)).center()

        with patch.object(self.window, "show_context_menu") as show_menu:
            self.window.open_context_menu(center)
            show_menu.assert_called_once()
            self.assertEqual(show_menu.call_args.args[:3], ("cell", 0, 4))

        selected = [(item.row(), item.column()) for item in self.window.table.selectedItems()]
        self.assertEqual(selected, [(0, 4)])
        self.assertEqual(self.window.table.currentRow(), 0)
        self.assertEqual(self.window.table.currentColumn(), 4)

    def test_translate_selected_cells_falls_back_to_current_cell(self):
        captured_jobs = []
        self.window.source_header = "english"
        self.window.set_cell_text(0, 2, "Knife")
        self.window.table.clearSelection()
        self.window.table.setCurrentCell(0, 4)
        self.window.run_translation_jobs = lambda jobs: captured_jobs.extend(jobs)

        self.window.translate_selected_cells()

        self.assertEqual(captured_jobs, [(0, 4, "Knife", "de")])

    def test_finish_translation_shows_errors_when_all_jobs_fail(self):
        results = TranslationResults(translated=0, failed=2, errors=["network down", "timeout"])
        with patch.object(QMessageBox, "warning") as warning:
            self.window.finish_translation(results)
            warning.assert_called()
            self.assertIn("network down", warning.call_args.args[2])

    def test_translation_settings_dialog_saves_provider_and_parallel_batches(self):
        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("DeepL")
        dialog.parallel_batches_input.setValue(3)
        dialog.batch_size_input.setValue(40)
        dialog.api_key_input.setText("secret")

        dialog.apply_settings()

        self.assertEqual(self.window.translation_provider, "deepl")
        self.assertEqual(self.window.translation_parallel_batches, 3)
        self.assertEqual(self.window.translation_batch_size, 40)
        self.assertEqual(self.window.translation_api_key, "secret")
        self.assertFalse(hasattr(dialog, "language_combo"))
        self.assertGreaterEqual(dialog.width(), 620)

    def test_translation_settings_auto_save_when_fields_change(self):
        dialog = TranslationSettingsDialog(self.window)

        dialog.provider_combo.setCurrentText("OpenAI")
        dialog.model_input.setText("gpt-test")
        dialog.base_url_input.setText("https://example.test/v1")

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

            text = path.read_text(encoding="utf-8")
            self.assertIn('"Knife"', text)

    def test_wordbook_uses_default_path_for_auto_save(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "wordbook.csv"
            wordbook = WordbookWindow(self.window, wordbook_path=path)

            wordbook.set_cell_text(0, 1, "Knife")

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
        self.window.translation_batch_size = 12
        self.window.translation_parallel_batches = 3
        self.window.translation_api_key = "key"
        self.window.translation_region = "region"
        self.window.translation_model = "model-a"
        self.window.translation_base_url = "https://a.test/v1"
        self.window.translation_email = "me@example.com"
        self.window.save_translation_preset("OpenAI A")

        self.window.translation_provider = "google"
        self.window.translation_batch_size = 30
        self.window.translation_parallel_batches = 1
        self.window.translation_api_key = ""
        self.window.translation_region = ""
        self.window.translation_model = "model-b"
        self.window.translation_base_url = ""
        self.window.translation_email = ""

        self.window.load_translation_preset("OpenAI A")

        self.assertEqual(self.window.translation_provider, "openai")
        self.assertEqual(self.window.translation_batch_size, 12)
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

        dialog = TranslationSettingsDialog(self.window)
        dialog.provider_combo.setCurrentText("OpenAI")

        dialog.preset_combo.setCurrentText("PresetA")
        dialog.auto_load_preset("PresetA")
        self.assertEqual(dialog.api_key_input.text(), "key-a")
        self.assertEqual(dialog.model_input.text(), "model-a")
        self.assertEqual(dialog.base_url_input.text(), "https://a.test/v1")

        dialog.preset_combo.setCurrentText("PresetB")
        dialog.auto_load_preset("PresetB")
        self.assertEqual(dialog.api_key_input.text(), "key-b")
        self.assertEqual(dialog.model_input.text(), "model-b")
        self.assertEqual(dialog.base_url_input.text(), "https://b.test/v1")

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
        self.window.run_translation_jobs = lambda jobs: captured_jobs.extend(jobs)

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
        self.window.run_translation_jobs = lambda jobs: captured_jobs.extend(jobs)

        self.window.translate_empty_cells()

        job_positions = [(j[0], j[1]) for j in captured_jobs]
        self.assertNotIn((0, 3), job_positions)
        self.assertIn((1, 3), job_positions)

    def test_translate_all_cells_menu_action_exists(self):
        self.assertTrue(hasattr(self.window, "action_translate_all"))
        self.assertTrue(hasattr(self.window, "action_translate_empty"))


if __name__ == "__main__":
    unittest.main()
