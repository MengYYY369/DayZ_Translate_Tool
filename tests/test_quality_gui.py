import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox

from dayz_csv import DAYZ_HEADERS
from main import QC_PROBLEM_COLOR, UI_TEXT, DayzTranslateTool, QualityCheckSettingsDialog, SearchDialog
from quality_check import RULE_GROUPS, QualityCheckConfig, all_rules


app = QApplication.instance() or QApplication([])

CZECH_COLUMN = DAYZ_HEADERS.index("czech")
GERMAN_COLUMN = DAYZ_HEADERS.index("german")


def make_row(key, source, **values):
    row = [key, f"Orig{key}", source] + [""] * (len(DAYZ_HEADERS) - 3)
    for header, text in values.items():
        row[DAYZ_HEADERS.index(header)] = text
    return row


# 捷克语和德语两格内容一样，用来触发「同一行太像」这条规则
SIMILAR_ROW = make_row("STR_A", "EngA", czech="Hello there friend", german="Hello there friend")
PLAIN_ROW = make_row("STR_B", "EngB")


class QualityGuiTests(unittest.TestCase):
    def setUp(self):
        self._settings_file = tempfile.NamedTemporaryFile(suffix=".ini", delete=False)
        self._settings_file.close()
        self.settings = QSettings(self._settings_file.name, QSettings.Format.IniFormat)
        self.settings.clear()
        self.settings.sync()
        self.window = DayzTranslateTool(settings=self.settings)
        self.window.headers = list(DAYZ_HEADERS)
        self.set_rows([SIMILAR_ROW, PLAIN_ROW])

    def tearDown(self):
        self.window.close()
        self.settings.clear()
        os.unlink(self._settings_file.name)

    def set_rows(self, rows):
        self.window.apply_table_rows([list(row) for row in rows], dirty=False)
        if self.window.current_path is None:
            self.window.current_path = Path("stringtable.csv")
            self.window.update_current_file_label()

    def cell_color(self, row, column):
        return self.window.table.item(row, column).background().color().name()

    def test_check_errors_marks_problem_cells(self):
        self.window.start_quality_check(run_immediately=True)
        self.assertEqual(self.window.quality_issues, {(0, CZECH_COLUMN): ("row_similarity",), (0, GERMAN_COLUMN): ("row_similarity",)})
        self.assertEqual(self.cell_color(0, CZECH_COLUMN), QC_PROBLEM_COLOR.name())
        self.assertEqual(self.cell_color(0, GERMAN_COLUMN), QC_PROBLEM_COLOR.name())
        self.assertEqual(self.cell_color(1, CZECH_COLUMN), QColor().name())

    def test_check_errors_menu_action_delegates(self):
        with patch.object(self.window, "start_quality_check") as start:
            self.window.check_errors()
        start.assert_called_once_with()

    def test_check_errors_clears_previous_automatic_marks(self):
        self.window.quality_issues = {(1, CZECH_COLUMN): ("row_similarity",)}
        self.window.manual_issue_cells = {(1, GERMAN_COLUMN)}
        self.window.start_quality_check(run_immediately=True)
        self.assertEqual(set(self.window.quality_issues), {(0, CZECH_COLUMN), (0, GERMAN_COLUMN)})
        # 手动标记不受重算影响
        self.assertEqual(self.window.manual_issue_cells, {(1, GERMAN_COLUMN)})

    def test_check_errors_without_table_warns(self):
        self.window.headers = []
        self.window.table.setRowCount(0)
        with patch.object(QMessageBox, "warning") as warning:
            self.window.check_errors()
            warning.assert_called()
        self.assertIsNone(self.window.quality_check_worker)

    def test_check_errors_while_translating_warns(self):
        with patch.object(self.window, "_is_translation_running", return_value=True), patch.object(QMessageBox, "warning") as warning:
            self.window.check_errors()
            warning.assert_called()
        self.assertIsNone(self.window.quality_check_worker)

    def test_manual_mark_and_unmark_repaints_cell(self):
        self.window.mark_cells_as_errors([(1, CZECH_COLUMN)])
        self.assertEqual(self.window.manual_issue_cells, {(1, CZECH_COLUMN)})
        self.assertEqual(self.cell_color(1, CZECH_COLUMN), QC_PROBLEM_COLOR.name())
        self.window.unmark_cells([(1, CZECH_COLUMN)])
        self.assertEqual(self.window.manual_issue_cells, set())
        self.assertEqual(self.cell_color(1, CZECH_COLUMN), QColor().name())

    def test_unmark_also_drops_automatic_issue(self):
        self.window.quality_issues = {(0, CZECH_COLUMN): ("row_similarity",)}
        self.window.paint_quality_cells()
        self.window.unmark_cells([(0, CZECH_COLUMN)])
        self.assertNotIn((0, CZECH_COLUMN), self.window.quality_issues)
        self.assertEqual(self.cell_color(0, CZECH_COLUMN), QColor().name())

    def test_editing_marked_cell_removes_mark(self):
        self.window.mark_cells_as_errors([(1, CZECH_COLUMN)])
        self.window.set_cell_text(1, CZECH_COLUMN, "changed text")
        self.assertEqual(self.window.manual_issue_cells, set())
        self.assertEqual(self.cell_color(1, CZECH_COLUMN), QColor().name())

    def test_painting_marks_does_not_dirty_table_or_add_history(self):
        self.window.set_dirty(False)
        self.window.mark_cells_as_errors([(1, CZECH_COLUMN)])
        self.assertFalse(self.window.is_dirty)
        self.assertFalse(self.window.history.can_undo())

    def test_context_menu_offers_mark_then_unmark(self):
        self.assertIn("mark_error", self.window.context_action_names("cell", 1, CZECH_COLUMN))
        self.assertNotIn("unmark_error", self.window.context_action_names("cell", 1, CZECH_COLUMN))
        self.window.mark_cells_as_errors([(1, CZECH_COLUMN)])
        self.assertIn("unmark_error", self.window.context_action_names("cell", 1, CZECH_COLUMN))
        self.assertNotIn("mark_error", self.window.context_action_names("cell", 1, CZECH_COLUMN))

    def test_context_menu_has_no_mark_action_for_source_column(self):
        self.assertNotIn("mark_error", self.window.context_action_names("cell", 1, 2))
        self.assertNotIn("mark_error", self.window.context_action_names("cell", 1, DAYZ_HEADERS.index("chinese")))

    def test_row_header_marks_every_translatable_column(self):
        self.assertIn("mark_row_error", self.window.context_action_names("row_header", 1, -1))
        self.window.mark_context_as_errors("row_header", 1, -1)
        expected = {(1, column) for column in (3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14)}
        self.assertEqual(self.window.manual_issue_cells, expected)
        self.assertIn("unmark_row_error", self.window.context_action_names("row_header", 1, -1))
        self.window.unmark_context_errors("row_header", 1, -1)
        self.assertEqual(self.window.manual_issue_cells, set())

    def test_context_menu_labels_are_translated(self):
        self.window.ui_language = "zh"
        self.window.apply_ui_language()
        labels = self.window.context_action_labels("cell", 1, CZECH_COLUMN)
        self.assertIn("标记为错误", labels)
        self.assertEqual(labels[0], "复制")

    def test_reloading_table_clears_marks(self):
        self.window.mark_cells_as_errors([(1, CZECH_COLUMN)])
        self.window.quality_issues = {(0, CZECH_COLUMN): ("row_similarity",)}
        self.set_rows([make_row("STR_C", "EngC")])
        self.assertEqual(self.window.quality_problem_cells(), set())
        self.assertEqual(self.cell_color(0, CZECH_COLUMN), QColor().name())

    def test_undo_repaints_marks(self):
        self.window.mark_cells_as_errors([(1, CZECH_COLUMN)])
        self.window.set_cell_text(0, CZECH_COLUMN, "some other text")
        self.assertEqual(self.cell_color(1, CZECH_COLUMN), QC_PROBLEM_COLOR.name())
        self.window.undo()
        self.assertEqual(self.cell_color(1, CZECH_COLUMN), QC_PROBLEM_COLOR.name())

    def test_translate_error_cells_builds_jobs_for_marked_cells(self):
        self.window.mark_cells_as_errors([(1, CZECH_COLUMN), (1, 2), (1, DAYZ_HEADERS.index("chinese"))])
        with patch.object(self.window, "run_translation_jobs") as run_jobs:
            self.window.translate_error_cells()
        run_jobs.assert_called_once()
        jobs = run_jobs.call_args.args[0]
        kwargs = run_jobs.call_args.kwargs
        self.assertEqual(jobs, [(1, CZECH_COLUMN, "EngB", "cs")])
        self.assertFalse(kwargs["copy_overwrite"])

    def test_translate_error_cells_without_marks_informs(self):
        with patch.object(QMessageBox, "information") as information, patch.object(self.window, "run_translation_jobs") as run_jobs:
            self.window.translate_error_cells()
        information.assert_called()
        run_jobs.assert_not_called()

    def test_search_dialog_quality_only_lists_problem_cells(self):
        self.window.quality_issues = {(0, CZECH_COLUMN): ("row_similarity",)}
        self.window.manual_issue_cells = {(1, CZECH_COLUMN)}
        self.window.paint_quality_cells()
        dialog = SearchDialog(self.window)
        dialog.quality_only_checkbox.setChecked(True)
        dialog.refresh_matches()
        self.assertEqual(dialog.matches, [(0, CZECH_COLUMN), (1, CZECH_COLUMN)])
        self.assertEqual(dialog.count_label.text(), self.window.tr("matches", count=2))
        dialog.close()

    def test_search_dialog_quality_only_with_text_intersects(self):
        self.set_rows([SIMILAR_ROW, make_row("STR_B", "Good morning world", czech="Good morning world")])
        self.window.manual_issue_cells = {(1, CZECH_COLUMN)}
        dialog = SearchDialog(self.window)
        dialog.quality_only_checkbox.setChecked(True)
        dialog.search_input.setText("Good morning")
        dialog.refresh_matches()
        self.assertEqual(dialog.matches, [(1, CZECH_COLUMN)])
        dialog.close()

    def test_search_highlight_restores_problem_color(self):
        self.window.manual_issue_cells = {(1, CZECH_COLUMN)}
        self.window.paint_quality_cells()
        dialog = SearchDialog(self.window)
        dialog.search_input.setText("EngB")
        dialog.refresh_matches()
        dialog.close()
        self.assertEqual(self.cell_color(1, CZECH_COLUMN), QC_PROBLEM_COLOR.name())

    def test_cancel_button_cancels_quality_check(self):
        worker = MagicMock()
        self.window.quality_check_worker = worker
        self.window.cancel_translation()
        worker.cancel.assert_called_once()
        self.assertTrue(self.window._quality_check_cancelled)
        self.assertFalse(self.window.translation_cancel_button.isEnabled())

    def test_settings_dialog_saves_choices(self):
        dialog = QualityCheckSettingsDialog(self.window)
        dialog.similarity_input.setValue(0.7)
        dialog.checkboxes["numbers"].setChecked(False)
        dialog.apply_settings()
        self.assertAlmostEqual(self.window.quality_config.similarity, 0.7)
        self.assertFalse(self.window.quality_config.is_enabled("numbers"))
        stored = QualityCheckConfig.from_json(self.settings.value("quality_check_config", ""))
        self.assertAlmostEqual(stored.similarity, 0.7)
        self.assertFalse(stored.is_enabled("numbers"))

    def test_settings_dialog_opens_with_saved_choices(self):
        self.window.save_quality_config(QualityCheckConfig(enabled=["numbers"], similarity=0.6))
        dialog = QualityCheckSettingsDialog(self.window)
        self.assertAlmostEqual(dialog.similarity_input.value(), 0.6)
        self.assertTrue(dialog.checkboxes["numbers"].isChecked())
        self.assertFalse(dialog.checkboxes["line_breaks"].isChecked())

    def test_settings_dialog_restore_defaults(self):
        dialog = QualityCheckSettingsDialog(self.window)
        dialog.similarity_input.setValue(0.5)
        dialog.checkboxes["numbers"].setChecked(False)
        dialog.restore_defaults()
        self.assertAlmostEqual(dialog.similarity_input.value(), QualityCheckConfig().similarity)
        self.assertTrue(dialog.checkboxes["numbers"].isChecked())
        self.assertFalse(dialog.checkboxes["empty_translation"].isChecked())

    def test_settings_dialog_group_buttons_toggle_all_rules(self):
        dialog = QualityCheckSettingsDialog(self.window)
        format_rules = RULE_GROUPS[0][1]
        dialog.checkboxes["numbers"].setChecked(False)
        dialog.set_group(format_rules, True)
        self.assertTrue(all(dialog.checkboxes[rule].isChecked() for rule in format_rules))
        dialog.set_group(format_rules, False)
        self.assertFalse(any(dialog.checkboxes[rule].isChecked() for rule in format_rules))

    def test_source_column_is_never_a_quality_target(self):
        self.assertFalse(self.window.is_quality_target_column(2))
        self.assertTrue(self.window.is_quality_target_column(CZECH_COLUMN))
        self.assertFalse(self.window.is_quality_target_column(1))
        self.assertFalse(self.window.is_quality_target_column(DAYZ_HEADERS.index("chinese")))

    def test_every_rule_and_group_has_ui_text(self):
        keys = [group_key for group_key, _rules in RULE_GROUPS]
        keys += [f"quality_rule_{rule}" for rule in all_rules()]
        for language in ("en", "zh"):
            for key in keys:
                self.assertIn(key, UI_TEXT[language], key)
                self.assertTrue(UI_TEXT[language][key], key)


if __name__ == "__main__":
    unittest.main()
