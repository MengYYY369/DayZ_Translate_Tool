import re
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QLibraryInfo, QObject, QSettings, QStandardPaths, QThread, Qt, QItemSelectionModel, QTimer, QTranslator
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QStyledItemDelegate,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from config_cpp import collect_config_cpp_files, extract_keys_from_paths, merge_language_keys
from dayz_csv import (
    DAYZ_HEADERS,
    build_column_translation_jobs,
    build_row_translation_jobs,
    copy_source_for_header,
    is_copy_only_column,
    language_code_for_header,
    load_dayz_csv,
    source_language_code_for_header,
    write_dayz_csv,
)
from translation_cache import TranslationCacheStore
from translation_worker import TranslationWorker
from translator_service import DEFAULT_CHAR_BUDGET, MAX_CHAR_BUDGET, MIN_CHAR_BUDGET, TranslationJob, TranslationService, TranslatorConfig, normalize_provider, validate_translator_config
from wordbook_csv import WORDBOOK_HEADERS, load_wordbook_csv, wordbook_rows_for_save, write_wordbook_csv
from table_history import TableHistory, snapshot_table, restore_table


APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
DEFAULT_CSV_PATH = APP_DIR / "stringtable.csv"
# 单词本放在用户配置文件夹，避免打包后写入应用目录失败
CONFIG_DIR = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) or APP_DIR
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_WORDBOOK_PATH = CONFIG_DIR / "wordbook.csv"
LANGUAGE_COLUMN_WIDTH = 150
DEFAULT_COLUMN_WIDTH = 90
SEARCH_MATCH_COLOR = QColor("#9adbe8")
SEARCH_ACTIVE_COLOR = QColor("#ffc857")
TABLE_GRIDLINE_COLOR = "#8c8c8c"
PROVIDER_LABELS = {
    "google": "Google",
    "mymemory": "MyMemory",
    "deepl": "DeepL",
    "microsoft": "Microsoft",
    "openai": "OpenAI",
    "claude": "Claude",
    "codex": "Codex",
}
LANGUAGE_LABELS = {
    "en": "English",
    "zh": "中文",
}
UI_TEXT = {
    "en": {
        "file": "File",
        "open": "Open",
        "save": "Save",
        "save_as": "Save As",
        "search": "Search",
        "settings": "Settings",
        "wordbook": "Wordbook",
        "source_language": "Source Language",
        "translation_settings": "Translation Settings...",
        "language_settings": "Interface Language...",
        "cancel": "Cancel",
        "ok": "OK",
        "test_translation": "Test",
        "test_translation_success": "Test succeeded. Translations:\n{result}",
        "test_translation_failed": "Test failed: {error}",
        "test_translation_running": "Testing...",
        "translation_engine": "Translation Engine",
        "preset": "Preset",
        "char_budget": "Max chars per batch",
        "parallel_batches": "Parallel Batches",
        "char_budget_tooltip": "Source characters a single request may carry. Rows are never split across requests. Larger = fewer requests but a bigger loss if one fails.",
        "parallel_batches_tooltip": "Number of batches processed concurrently. Larger = faster but may hit API rate limits.",
        "timeout": "Timeout (s)",
        "language": "Language",
        "api_key": "API Key",
        "region": "Region",
        "model": "Model",
        "base_url": "Base URL",
        "email": "Email",
        "next": "Next",
        "matches": "{count} matches",
        "match_whole_word": "Match whole word",
        "match_case": "Match case",
        "copy": "Copy",
        "paste": "Paste",
        "cut": "Cut",
        "delete_cell": "Delete Cell",
        "delete_selected_cells": "Delete Selected Cells",
        "delete_row": "Delete Row",
        "delete_column": "Delete Column",
        "reset_column_order": "Reset Column Order",
        "insert_row_above": "Insert Row Above",
        "insert_row_below": "Insert Row Below",
        "fill_row_with_cell": "Fill Row With This Cell",
        "translate_selected_cells": "Translate Selected Cells",
        "translate_selected_rows": "Translate Selected Rows",
        "translate_selected_columns": "Translate Selected Columns",
        "undo": "Undo",
        "redo": "Redo",
        "open_dayz_csv": "Open DayZ stringtable.csv",
        "save_dayz_csv": "Save DayZ stringtable.csv",
        "open_wordbook_csv": "Open wordbook.csv",
        "save_wordbook_csv": "Save wordbook.csv",
        "csv_files": "CSV files (*.csv)",
        "wordbook_files": "CSV files (*.csv)",
        "open_failed": "Open failed",
        "save_skipped": "Save skipped",
        "save_failed": "Save failed",
        "no_dayz_csv_loaded": "No DayZ CSV is loaded.",
        "loaded": "Loaded {path}",
        "saved": "Saved {path}",
        "load_csv_before_source": "Load a DayZ CSV before choosing the source language.",
        "source_column": "Source column:",
        "source_language_status": "Source language: {value}",
        "translation_engine_status": "Translation engine: {engine}",
        "translate_cells": "Translate cells",
        "translate_rows": "Translate rows",
        "translate_columns": "Translate columns",
        "source_column_missing": "Source language column \"{header}\" was not found.",
        "translate": "Translate",
        "no_translatable_cells": "No translatable cells were selected.",
        "translation_progress": "Translated {translated}, failed {failed}, cache hits {cache_hits}",
        "translate_failed": "Translate failed",
        "cancelling_translation": "Cancelling translation...",
        "translation_cancelled": "Translation cancelled",
        "translation_in_progress": "A translation is already running. Please cancel it or wait for it to finish.",
        "translation_running_close": "A translation is in progress. Cancel it and close?",
        "failed_count": "failed {count}",
        "unsaved_changes": "Unsaved changes",
        "save_changes_before_close": "Save changes to {path} before closing?",
        "import_config_cpp": "Import from config.cpp...",
        "import_config_cpp_folder": "Import config.cpp from Folder...",
        "translate_all_cells": "Translate All Cells",
        "translate_empty_cells": "Translate Empty Cells",
        "import_config_cpp_title": "Select config.cpp files",
        "import_config_folder_title": "Select folder containing config.cpp",
        "config_cpp_files": "config.cpp (config.cpp);;C++ files (*.cpp);;All files (*.*)",
        "import_requires_csv": "Open a DayZ stringtable.csv before importing config.cpp keys.",
        "import_no_files": "No config.cpp files were selected.",
        "import_no_new_keys": "No new keys to import. Skipped duplicates: {skipped}. Files: {files}.",
        "import_result": "Imported {added} keys, skipped {skipped} duplicates, files: {files}.",
        "import_failed": "Import failed",
    },
    "zh": {
        "file": "文件",
        "open": "打开",
        "save": "保存",
        "save_as": "另存为",
        "search": "搜索",
        "settings": "设置",
        "wordbook": "单词本",
        "source_language": "源语言",
        "translation_settings": "翻译设置...",
        "language_settings": "界面语言...",
        "cancel": "取消",
        "ok": "确定",
        "test_translation": "测试",
        "test_translation_success": "测试成功。翻译结果：\n{result}",
        "test_translation_failed": "测试失败：{error}",
        "test_translation_running": "正在测试...",
        "translation_engine": "翻译引擎",
        "preset": "预设",
        "char_budget": "每批最多字数",
        "parallel_batches": "并行批次",
        "char_budget_tooltip": "单次请求最多携带的源文字数。行不会被拆到两个请求里。越大请求越少，但单次失败的代价也越大。",
        "parallel_batches_tooltip": "同时进行的批次数（并发请求数）。越大翻译越快但可能触发 API 限流。",
        "timeout": "超时 (s)",
        "language": "语言",
        "api_key": "API Key",
        "region": "区域",
        "model": "模型",
        "base_url": "Base URL",
        "email": "Email",
        "next": "下一个",
        "matches": "{count} 个匹配",
        "match_whole_word": "全词匹配",
        "match_case": "匹配大小写",
        "copy": "复制",
        "paste": "粘贴",
        "cut": "剪切",
        "delete_cell": "删除单元格",
        "delete_selected_cells": "删除选中单元格",
        "delete_row": "删除行",
        "delete_column": "删除列",
        "reset_column_order": "重置列顺序",
        "insert_row_above": "在上方插入行",
        "insert_row_below": "在下方插入行",
        "fill_row_with_cell": "以该单元格填充整行",
        "translate_selected_cells": "翻译选中单元格",
        "translate_selected_rows": "翻译选中行",
        "translate_selected_columns": "翻译选中列",
        "undo": "撤销",
        "redo": "重做",
        "open_dayz_csv": "打开 DayZ stringtable.csv",
        "save_dayz_csv": "保存 DayZ stringtable.csv",
        "open_wordbook_csv": "打开 wordbook.csv",
        "save_wordbook_csv": "保存 wordbook.csv",
        "csv_files": "CSV 文件 (*.csv)",
        "wordbook_files": "CSV 文件 (*.csv)",
        "open_failed": "打开失败",
        "save_skipped": "跳过保存",
        "save_failed": "保存失败",
        "no_dayz_csv_loaded": "还没有加载 DayZ CSV。",
        "loaded": "已加载 {path}",
        "saved": "已保存 {path}",
        "load_csv_before_source": "选择源语言前，请先加载 DayZ CSV。",
        "source_column": "源语言列：",
        "source_language_status": "源语言：{value}",
        "translation_engine_status": "翻译引擎：{engine}",
        "translate_cells": "翻译单元格",
        "translate_rows": "翻译行",
        "translate_columns": "翻译列",
        "source_column_missing": "没有找到源语言列 \"{header}\"。",
        "translate": "翻译",
        "no_translatable_cells": "没有可翻译的选中单元格。",
        "translation_progress": "已翻译 {translated}，失败 {failed}，缓存命中 {cache_hits}",
        "translate_failed": "翻译失败",
        "cancelling_translation": "正在取消翻译...",
        "translation_cancelled": "翻译已取消",
        "translation_in_progress": "翻译正在进行中，请先取消或等待完成。",
        "translation_running_close": "翻译正在进行中，是否取消翻译并关闭？",
        "failed_count": "失败 {count}",
        "unsaved_changes": "未保存的更改",
        "save_changes_before_close": "关闭前要保存 {path} 的更改吗？",
        "import_config_cpp": "从 config.cpp 导入...",
        "import_config_cpp_folder": "从文件夹批量导入 config.cpp...",
        "translate_all_cells": "翻译全表",
        "translate_empty_cells": "翻译空白单元格",
        "import_config_cpp_title": "选择 config.cpp 文件",
        "import_config_folder_title": "选择包含 config.cpp 的文件夹",
        "config_cpp_files": "config.cpp (config.cpp);;C++ 文件 (*.cpp);;所有文件 (*.*)",
        "import_requires_csv": "请先打开 DayZ stringtable.csv，再导入 config.cpp 键。",
        "import_no_files": "没有选择 config.cpp 文件。",
        "import_no_new_keys": "没有可导入的新键。跳过重复 {skipped}，文件数 {files}。",
        "import_result": "新增 {added} 个键，跳过重复 {skipped}，文件数 {files}。",
        "import_failed": "导入失败",
    },
}
PROVIDER_FIELD_KEYS = {
    "google": set(),
    "mymemory": {"email"},
    "deepl": {"api_key"},
    "microsoft": {"api_key", "region"},
    "openai": {"api_key", "model", "base_url"},
    "claude": {"api_key", "model", "base_url"},
    "codex": {"api_key", "model", "base_url"},
}
PROVIDER_DEFAULTS = {
    "google": {},
    "mymemory": {"email": ""},
    "deepl": {"api_key": ""},
    "microsoft": {"api_key": "", "region": ""},
    "openai": {"api_key": "", "model": "gpt-3.5-turbo", "base_url": ""},
    "claude": {"api_key": "", "model": "claude-3-5-sonnet-20241022", "base_url": ""},
    "codex": {"api_key": "", "model": "gpt-4o-mini", "base_url": ""},
}


class _NoToolTipFilter(QObject):
    """拦截 viewport 的 ToolTip 事件，避免单元格文本被截断时弹出自动 tooltip 覆盖单元格。"""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ToolTip:
            return True
        return super().eventFilter(obj, event)


class _ClipTextDelegate(QStyledItemDelegate):
    """截断超长文本但不显示省略号：initStyleOption 设 ElideMode=None（不加省略号），
    paint 时 setClipRect 限制绘制区域，超出单元格的文本被裁剪掉。"""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideNone

    def paint(self, painter, option, index):
        painter.save()
        painter.setClipRect(option.rect)
        super().paint(painter, option, index)
        painter.restore()


class SearchDialog(QDialog):
    SEARCH_DEBOUNCE_MS = 200

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle(window.tr("search"))
        self.setModal(False)
        self.matches = []
        self.current_match = -1
        self._highlighted_cells = set()

        self.search_input = QLineEdit(self)
        self.search_input.textChanged.connect(self._schedule_refresh)
        self.count_label = QLabel(window.tr("matches", count=0), self)

        self.match_whole_word_checkbox = QCheckBox(window.tr("match_whole_word"), self)
        self.match_whole_word_checkbox.toggled.connect(self._schedule_refresh)
        self.match_case_checkbox = QCheckBox(window.tr("match_case"), self)
        self.match_case_checkbox.toggled.connect(self._schedule_refresh)

        self.next_button = QPushButton(window.tr("next"), self)
        self.next_button.setMaximumWidth(96)
        self.next_button.clicked.connect(self.next_match)

        self.previous_button = QPushButton("↑", self)
        self.previous_button.setFixedSize(32, 32)
        self.previous_button.clicked.connect(self.previous_match)

        options_layout = QHBoxLayout()
        options_layout.addWidget(self.match_whole_word_checkbox)
        options_layout.addWidget(self.match_case_checkbox)
        options_layout.addStretch(1)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.next_button)
        button_layout.addWidget(self.previous_button)
        button_layout.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search_input)
        layout.addLayout(options_layout)
        layout.addWidget(self.count_label)
        layout.addLayout(button_layout)
        self.resize(360, 160)

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self.refresh_matches)

    def show_and_focus(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _schedule_refresh(self):
        self._debounce_timer.start(self.SEARCH_DEBOUNCE_MS)

    def refresh_matches(self):
        self._clear_highlight()
        self.matches = self.window.find_matches(
            self.search_input.text(),
            whole_word=self.match_whole_word_checkbox.isChecked(),
            match_case=self.match_case_checkbox.isChecked(),
        )
        for row_index, column_index in self.matches:
            item = self.window.table.item(row_index, column_index)
            if item:
                item.setBackground(SEARCH_MATCH_COLOR)
                self._highlighted_cells.add((row_index, column_index))
        self.current_match = -1
        self.count_label.setText(self.window.tr("matches", count=len(self.matches)))
        if self.matches:
            self.next_match()

    def _clear_highlight(self):
        for row_index, column_index in self._highlighted_cells:
            item = self.window.table.item(row_index, column_index)
            if item:
                item.setBackground(QColor())
        self._highlighted_cells.clear()

    def next_match(self):
        if not self.matches:
            return
        self.restore_current_match_color()
        self.current_match = (self.current_match + 1) % len(self.matches)
        self.window.focus_match(*self.matches[self.current_match])
        self.apply_current_match_color()

    def previous_match(self):
        if not self.matches:
            return
        self.restore_current_match_color()
        self.current_match = (self.current_match - 1) % len(self.matches)
        self.window.focus_match(*self.matches[self.current_match])
        self.apply_current_match_color()

    def restore_current_match_color(self):
        if self.current_match < 0 or self.current_match >= len(self.matches):
            return
        row_index, column_index = self.matches[self.current_match]
        item = self.window.table.item(row_index, column_index)
        if item:
            item.setBackground(SEARCH_MATCH_COLOR)

    def apply_current_match_color(self):
        if self.current_match < 0 or self.current_match >= len(self.matches):
            return
        row_index, column_index = self.matches[self.current_match]
        item = self.window.table.item(row_index, column_index)
        if item:
            item.setBackground(SEARCH_ACTIVE_COLOR)

    def closeEvent(self, event):
        self._debounce_timer.stop()
        self._clear_highlight()
        self.search_input.clear()
        self.matches = []
        self.current_match = -1
        self.count_label.setText(self.window.tr("matches", count=0))
        super().closeEvent(event)


class TranslationSettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.form_rows = {}
        self._loading_preset = False
        self.setWindowTitle(window.tr("translation_settings").rstrip("."))
        # 对话框维护自己的字段缓存，编辑期间不修改 window 的 provider_settings，
        # 只有点击"保存"按钮才通过 apply_settings 持久化。
        self._dialog_field_cache = {}
        for provider, keys in PROVIDER_FIELD_KEYS.items():
            self._dialog_field_cache[provider] = {
                key: window.get_provider_setting(provider, key, "") for key in keys
            }

        self.provider_combo = QComboBox(self)
        self.provider_combo.addItems(PROVIDER_LABELS.values())
        self.provider_combo.setCurrentText(PROVIDER_LABELS.get(window.translation_provider, "Google"))
        self._current_dialog_provider = window.translation_provider

        self.preset_combo = QComboBox(self)
        self.refresh_presets()
        self.preset_name_input = QLineEdit(self)
        self.dirty_indicator_label = QLabel("", self)
        self.dirty_indicator_label.setFixedWidth(16)
        self.save_preset_button = QPushButton(window.tr("save"), self)
        self.save_preset_button.clicked.connect(self.save_preset)
        self.delete_preset_button = QPushButton(window.tr("delete"), self)
        self.delete_preset_button.clicked.connect(self.delete_preset)

        self.char_budget_input = QSpinBox(self)
        self.char_budget_input.setRange(MIN_CHAR_BUDGET, MAX_CHAR_BUDGET)
        self.char_budget_input.setSingleStep(100)
        self.char_budget_input.setValue(window.translation_char_budget)

        self.parallel_batches_input = QSpinBox(self)
        self.parallel_batches_input.setRange(1, 5)
        self.parallel_batches_input.setValue(window.translation_parallel_batches)

        self.timeout_input = QSpinBox(self)
        self.timeout_input.setRange(5, 300)
        self.timeout_input.setSingleStep(5)
        self.timeout_input.setValue(int(window.translation_timeout))

        self.api_key_input = QLineEdit(self)
        self.api_key_input.setText(window.translation_api_key)

        self.region_input = QLineEdit(self)
        self.region_input.setText(window.translation_region)

        self.model_input = QLineEdit(self)
        self.model_input.setText(window.translation_model)

        self.base_url_input = QLineEdit(self)
        self.base_url_input.setText(window.translation_base_url)

        self.email_input = QLineEdit(self)
        self.email_input.setText(window.translation_email)

        form = QFormLayout()
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addWidget(self.dirty_indicator_label)
        preset_layout.addWidget(self.preset_name_input)
        preset_layout.addWidget(self.save_preset_button)
        preset_layout.addWidget(self.delete_preset_button)
        preset_label = QLabel(window.tr("preset"), self)
        form.addRow(preset_label, preset_layout)
        self.form_rows["preset"] = (preset_label, self._layout_widgets(preset_layout))
        self.add_form_row(form, "provider", window.tr("translation_engine"), self.provider_combo)
        self.add_form_row(form, "char_budget", window.tr("char_budget"), self.char_budget_input, window.tr("char_budget_tooltip"))
        self.add_form_row(form, "parallel_batches", window.tr("parallel_batches"), self.parallel_batches_input, window.tr("parallel_batches_tooltip"))
        self.add_form_row(form, "timeout", window.tr("timeout"), self.timeout_input)
        self.add_form_row(form, "api_key", window.tr("api_key"), self.api_key_input)
        self.add_form_row(form, "region", window.tr("region"), self.region_input)
        self.add_form_row(form, "model", window.tr("model"), self.model_input)
        self.add_form_row(form, "base_url", window.tr("base_url"), self.base_url_input)
        self.add_form_row(form, "email", window.tr("email"), self.email_input)
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self.connect_auto_save_signals()
        self.update_visible_fields()
        self.preset_combo.currentTextChanged.connect(self.auto_load_preset)

        save_button = QPushButton(window.tr("save"), self)
        save_button.clicked.connect(self.apply_settings)
        self.test_button = QPushButton(window.tr("test_translation"), self)
        self.test_button.clicked.connect(self.run_translation_test)
        cancel_button = QPushButton(window.tr("cancel"), self)
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.test_button)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        self.resize(660, 300)

    def _layout_widgets(self, layout):
        widgets = []
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget:
                widgets.append(widget)
        return widgets

    def add_form_row(self, form, key, label_text, widget, tooltip=None):
        label = QLabel(label_text, self)
        if tooltip:
            label.setToolTip(tooltip)
            widget.setToolTip(tooltip)
        form.addRow(label, widget)
        self.form_rows[key] = (label, widget)

    def update_visible_fields(self):
        provider_label = self.provider_combo.currentText()
        provider = next(key for key, label in PROVIDER_LABELS.items() if label == provider_label)
        visible_fields = PROVIDER_FIELD_KEYS.get(provider, set())
        preset_visible = provider in ("openai", "claude", "codex")
        preset_label, preset_widgets = self.form_rows["preset"]
        preset_label.setVisible(preset_visible)
        for widget in preset_widgets:
            widget.setVisible(preset_visible)
        for key in ("api_key", "region", "model", "base_url", "email"):
            label, widget = self.form_rows[key]
            visible = key in visible_fields
            label.setVisible(visible)
            widget.setVisible(visible)

    def is_field_visible(self, key):
        label, widget = self.form_rows[key]
        if isinstance(widget, list):
            return not label.isHidden() and all(not item.isHidden() for item in widget)
        return not label.isHidden() and not widget.isHidden()

    def connect_auto_save_signals(self):
        self.char_budget_input.valueChanged.connect(self._on_field_changed)
        self.parallel_batches_input.valueChanged.connect(self._on_field_changed)
        self.timeout_input.valueChanged.connect(self._on_field_changed)
        self.api_key_input.textChanged.connect(self._on_field_changed)
        self.region_input.textChanged.connect(self._on_field_changed)
        self.model_input.textChanged.connect(self._on_field_changed)
        self.base_url_input.textChanged.connect(self._on_field_changed)
        self.email_input.textChanged.connect(self._on_field_changed)

    def _on_provider_changed(self, label):
        if self._loading_preset:
            return
        old_provider = self._current_dialog_provider
        self._save_dialog_fields_to_cache(old_provider)
        new_provider = next(key for key, lbl in PROVIDER_LABELS.items() if lbl == label)
        self._block_field_signals(True)
        for key in PROVIDER_FIELD_KEYS.get(new_provider, set()):
            value = self._dialog_field_cache.get(new_provider, {}).get(key, "")
            self._set_field_value(key, value)
        self._block_field_signals(False)
        self._current_dialog_provider = new_provider
        self.update_visible_fields()
        self.refresh_preset_dirty_indicator()

    def _save_dialog_fields_to_cache(self, provider):
        for key in PROVIDER_FIELD_KEYS.get(provider, set()):
            self._dialog_field_cache.setdefault(provider, {})[key] = self._get_field_value(key)

    def _get_field_value(self, key):
        field_map = {
            "api_key": self.api_key_input,
            "region": self.region_input,
            "model": self.model_input,
            "base_url": self.base_url_input,
            "email": self.email_input,
        }
        widget = field_map.get(key)
        if widget is not None:
            return widget.text().strip()
        return ""

    def _set_field_value(self, key, value):
        field_map = {
            "api_key": self.api_key_input,
            "region": self.region_input,
            "model": self.model_input,
            "base_url": self.base_url_input,
            "email": self.email_input,
        }
        widget = field_map.get(key)
        if widget is not None:
            widget.setText(value or "")

    def _block_field_signals(self, block):
        self.api_key_input.blockSignals(block)
        self.region_input.blockSignals(block)
        self.model_input.blockSignals(block)
        self.base_url_input.blockSignals(block)
        self.email_input.blockSignals(block)

    def _on_field_changed(self, value=None):
        if self._loading_preset:
            return
        # 把当前 provider 的字段保存到对话框缓存，不写入 window
        self._save_dialog_fields_to_cache(self._current_dialog_provider)
        self.refresh_preset_dirty_indicator()

    def apply_settings(self, close_dialog=True):
        provider_label = self.provider_combo.currentText()
        provider = next(key for key, label in PROVIDER_LABELS.items() if label == provider_label)
        self.window.translation_provider = provider
        self.window.translation_char_budget = self.char_budget_input.value()
        self.window.translation_parallel_batches = self.parallel_batches_input.value()
        self.window.translation_timeout = float(self.timeout_input.value())
        # 保存当前 provider 的对话框字段到 window
        self._save_dialog_fields_to_cache(provider)
        # 把缓存中所有 provider 的字段写入 window（包括切换过的 provider）
        for prov, fields in self._dialog_field_cache.items():
            for key, value in fields.items():
                self.window.set_provider_setting(prov, key, value)
        self.window.save_translation_settings()
        if close_dialog:
            self.accept()

    def _build_test_config(self):
        provider_label = self.provider_combo.currentText()
        provider = next(key for key, label in PROVIDER_LABELS.items() if label == provider_label)
        return TranslatorConfig(
            provider=provider,
            # 测试连接只验证密钥/模型可用，不需要分批，给一个大预算一次问完
            char_budget=MAX_CHAR_BUDGET,
            parallel_batches=self.parallel_batches_input.value(),
            timeout=float(self.timeout_input.value()),
            api_key=self._get_field_value("api_key"),
            region=self._get_field_value("region"),
            model=self._get_field_value("model"),
            base_url=self._get_field_value("base_url"),
            email=self._get_field_value("email"),
        )

    def run_translation_test(self):
        config = self._build_test_config()
        try:
            validate_translator_config(config)
        except ValueError as exc:
            QMessageBox.warning(self, self.window.tr("test_translation"), str(exc))
            return
        # 重复点击测试按钮时，先等待旧测试线程结束，避免 QThread 被覆盖导致泄漏或崩溃。
        self._wait_for_test_thread()
        self.test_button.setEnabled(False)
        self.test_button.setText(self.window.tr("test_translation_running"))
        test_word = "Knife"
        target_languages = ["chinese", "russian", "japanese", "german"]
        jobs = [
            TranslationJob(row=0, column=index, text=test_word, source_code="english", target_code=lang)
            for index, lang in enumerate(target_languages)
        ]
        service = TranslationService()
        self._test_thread = QThread(self)
        self._test_worker = TranslationWorker(service=service, jobs=jobs, config=config)
        self._test_worker.moveToThread(self._test_thread)
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.failed.connect(self._on_test_failed)
        self._test_worker.finished.connect(self._test_thread.quit)
        self._test_worker.failed.connect(self._test_thread.quit)
        # 线程结束后释放 worker 和 thread，避免内存泄漏与重复回调。
        self._test_thread.finished.connect(self._test_worker.deleteLater)
        self._test_thread.finished.connect(self._test_thread.deleteLater)
        # 线程结束后清空引用，避免第二次测试时 isRunning() 抛 RuntimeError。
        self._test_thread.finished.connect(self._clear_test_thread)
        self._test_thread.start()

    def _clear_test_thread(self):
        self._test_worker = None
        self._test_thread = None

    def _wait_for_test_thread(self):
        thread = getattr(self, "_test_thread", None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(3000)

    def _on_test_finished(self, results):
        self._reset_test_button()
        lines = []
        # 按 job 的 (row, column) 查找结果，而非用 zip 按位置配对：
        # 某语言失败时 cell_results 会缺少该条目，zip 会让剩余语言错位显示。
        for job in self._current_test_jobs():
            text = results.cell_results.get((job.row, job.column))
            if text is None:
                text = "(failed)"
            lines.append(f"{job.target_code}: {text}")
        result_text = "\n".join(lines)
        QMessageBox.information(
            self,
            self.window.tr("test_translation"),
            self.window.tr("test_translation_success", result=result_text),
        )

    def _on_test_failed(self, error):
        self._reset_test_button()
        QMessageBox.critical(
            self,
            self.window.tr("test_translation"),
            self.window.tr("test_translation_failed", error=error),
        )

    def _reset_test_button(self):
        self.test_button.setEnabled(True)
        self.test_button.setText(self.window.tr("test_translation"))

    def _current_test_jobs(self):
        test_word = "Knife"
        target_languages = ["chinese", "russian", "japanese", "german"]
        return [
            TranslationJob(row=0, column=index, text=test_word, source_code="english", target_code=lang)
            for index, lang in enumerate(target_languages)
        ]

    def refresh_presets(self):
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(self.window.translation_preset_names())
        self.preset_combo.blockSignals(False)

    def save_preset(self):
        name = (self.preset_name_input.text() or "").strip()
        if not name:
            return
        # 保存当前 provider 字段到缓存
        provider_label = self.provider_combo.currentText()
        provider = next(key for key, label in PROVIDER_LABELS.items() if label == provider_label)
        self._save_dialog_fields_to_cache(provider)
        # 从对话框当前值保存预设，不修改 window 状态
        values = self.current_field_values()
        self.window.settings.beginGroup(f"translation_presets/{name}")
        for key, value in values.items():
            self.window.settings.setValue(key, value)
        self.window.settings.endGroup()
        names = self.window.translation_preset_names()
        if name not in names:
            names.append(name)
            self.window.settings.setValue("translation_preset_names_list", names)
        self.window.settings.sync()
        self.refresh_presets()
        self.preset_combo.setCurrentText(name)
        self._loaded_preset_values = self.current_field_values()
        self.refresh_preset_dirty_indicator()

    def delete_preset(self):
        name = (self.preset_combo.currentText() or "").rstrip("*").strip()
        self.window.delete_translation_preset(name)
        self.refresh_presets()
        self.refresh_preset_dirty_indicator()

    def auto_load_preset(self, name):
        name = (name or "").rstrip("*").strip()
        if not name:
            return
        self._loading_preset = True
        values = self._read_preset_values(name)
        self._apply_preset_values_to_dialog(values)
        self._loading_preset = False
        provider = normalize_provider(values.get("provider") or "google")
        self._current_dialog_provider = provider
        self.update_visible_fields()
        self._loaded_preset_values = self.current_field_values()
        self.refresh_preset_dirty_indicator()

    def _read_preset_values(self, name):
        preset_keys = ["provider", "char_budget", "parallel_batches", "timeout", "api_key", "region", "model", "base_url", "email", "batch_size"]
        prefix = f"translation_presets/{name}/"
        values = {key: self.window.settings.value(prefix + key, "") for key in preset_keys}
        return values

    def _apply_preset_values_to_dialog(self, values):
        provider = normalize_provider(values.get("provider") or "google")
        self.provider_combo.setCurrentText(PROVIDER_LABELS.get(provider, "Google"))
        # 旧键 batch_size 存的是「行数」（默认 30），新键 char_budget 是「字数」。
        # 旧值 30 落在新区间里，直接拿来用就会被当成「每批 30 个字」—— 一律换成默认值。
        char_budget = values.get("char_budget")
        if char_budget is None or str(char_budget) == "":
            legacy = values.get("batch_size")
            if legacy is not None and str(legacy) != "":
                char_budget = DEFAULT_CHAR_BUDGET
        if char_budget is not None and str(char_budget) != "":
            self.char_budget_input.setValue(int(char_budget))
        parallel_batches = values.get("parallel_batches")
        if parallel_batches is not None and str(parallel_batches) != "":
            self.parallel_batches_input.setValue(int(parallel_batches))
        timeout = values.get("timeout")
        if timeout is not None and str(timeout) != "":
            self.timeout_input.setValue(int(timeout))
        self._block_field_signals(True)
        for key in PROVIDER_FIELD_KEYS.get(provider, set()):
            value = values.get(key, "")
            self._set_field_value(key, str(value) if value is not None else "")
        self._block_field_signals(False)
        # 更新对话框字段缓存，使切换 provider 时能恢复预设值
        for key in PROVIDER_FIELD_KEYS.get(provider, set()):
            self._dialog_field_cache.setdefault(provider, {})[key] = str(values.get(key, "")) if values.get(key) is not None else ""

    def current_field_values(self):
        provider_label = self.provider_combo.currentText()
        provider = next(key for key, label in PROVIDER_LABELS.items() if label == provider_label)
        return {
            "provider": provider,
            "char_budget": self.char_budget_input.value(),
            "parallel_batches": self.parallel_batches_input.value(),
            "timeout": self.timeout_input.value(),
            "api_key": self.api_key_input.text().strip(),
            "region": self.region_input.text().strip(),
            "model": self.model_input.text().strip(),
            "base_url": self.base_url_input.text().strip(),
            "email": self.email_input.text().strip(),
        }

    def preset_saved_values(self):
        return getattr(self, '_loaded_preset_values', None)

    def is_preset_dirty(self):
        saved = self.preset_saved_values()
        if saved is None:
            return False
        current = self.current_field_values()
        for key, value in current.items():
            saved_value = saved.get(key, "")
            if str(value) != str(saved_value):
                return True
        return False

    def refresh_preset_dirty_indicator(self):
        if self.preset_saved_values() is None:
            self.dirty_indicator_label.setText("")
            return
        if self.is_preset_dirty():
            self.dirty_indicator_label.setText("*")
        else:
            self.dirty_indicator_label.setText("")


class LanguageSettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle(window.tr("language_settings").rstrip("."))

        self.language_combo = QComboBox(self)
        self.language_combo.addItems(LANGUAGE_LABELS.values())
        self.language_combo.setCurrentText(LANGUAGE_LABELS.get(window.ui_language, "English"))

        form = QFormLayout()
        form.addRow(QLabel(window.tr("language"), self), self.language_combo)

        save_button = QPushButton(window.tr("save"), self)
        save_button.clicked.connect(self.apply_settings)
        cancel_button = QPushButton(window.tr("cancel"), self)
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        self.resize(320, 120)

    def apply_settings(self):
        language_label = self.language_combo.currentText()
        self.window.ui_language = next(key for key, label in LANGUAGE_LABELS.items() if label == language_label)
        self.window.save_ui_language()
        self.window.apply_ui_language()
        self.accept()


class WordbookWindow(QMainWindow):
    def __init__(self, parent, wordbook_path=DEFAULT_WORDBOOK_PATH):
        super().__init__(parent)
        self.parent_window = parent
        self.current_path = Path(wordbook_path)
        self.loading = False
        self.is_dirty = False
        self.current_file_label = QLabel("", self)
        self.history = TableHistory()
        # 自动保存防抖：连续按键合并为一次写盘，避免每次按键都全量写 CSV。
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(1000)
        self._auto_save_timer.timeout.connect(self.auto_save)
        self.table = QTableWidget(self)
        self.table.setColumnCount(len(WORDBOOK_HEADERS))
        self.table.setHorizontalHeaderLabels(WORDBOOK_HEADERS)
        self.table.itemChanged.connect(self.handle_item_changed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_context_menu)
        self.table.setStyleSheet(f"QTableWidget {{ gridline-color: {TABLE_GRIDLINE_COLOR}; }}")
        self.table.horizontalHeader().setSectionsMovable(True)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setWordWrap(False)
        self.setCentralWidget(self.table)
        self._no_tooltip_filter = _NoToolTipFilter(self)
        self.table.viewport().installEventFilter(self._no_tooltip_filter)
        self.table.setItemDelegate(_ClipTextDelegate(self.table))
        self.resize(1500, 620)
        self.setWindowTitle(parent.tr("wordbook"))
        self.create_menus()
        self.create_edit_actions()
        self.statusBar().addPermanentWidget(self.current_file_label, 1)
        self.update_current_file_label()
        if self.current_path.exists():
            self.load_file(self.current_path)
        else:
            self.set_rows([])

    def create_menus(self):
        file_menu = self.menuBar().addMenu(self.parent_window.tr("file"))

        open_action = QAction(self.parent_window.tr("open"), self)
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)

        save_action = QAction(self.parent_window.tr("save"), self)
        save_action.triggered.connect(self.save_file)
        file_menu.addAction(save_action)

        save_as_action = QAction(self.parent_window.tr("save_as"), self)
        save_as_action.triggered.connect(self.save_file_as)
        file_menu.addAction(save_as_action)

    def create_edit_actions(self):
        copy_action = QAction(self)
        copy_action.setShortcut(QKeySequence.Copy)
        copy_action.triggered.connect(self.copy_selection)
        self.addAction(copy_action)

        paste_action = QAction(self)
        paste_action.setShortcut(QKeySequence.Paste)
        paste_action.triggered.connect(self.paste_selection)
        self.addAction(paste_action)

        cut_action = QAction(self)
        cut_action.setShortcut(QKeySequence.Cut)
        cut_action.triggered.connect(self.cut_selection)
        self.addAction(cut_action)

        undo_action = QAction(self)
        undo_action.setShortcut(QKeySequence.Undo)
        undo_action.triggered.connect(self.undo)
        self.addAction(undo_action)

        redo_action = QAction(self)
        redo_action.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Shift+Z")])
        redo_action.triggered.connect(self.redo)
        self.addAction(redo_action)

    def open_context_menu(self, position):
        # customContextMenuRequested 传递的是 viewport 坐标，rowAt/columnAt 直接使用。
        row = self.table.rowAt(position.y())
        # columnAt 返回 visual 索引，列拖拽重排后必须转为 logical 索引才能正确访问数据。
        visual_column = self.table.columnAt(position.x())
        column = self.table.horizontalHeader().logicalIndex(visual_column) if visual_column >= 0 else -1
        if row >= 0 and column >= 0:
            item = self.table.item(row, column)
            if item is None:
                # 创建空 item 仅用于选中，屏蔽信号避免触发 dirty 标记和历史快照。
                self.table.blockSignals(True)
                item = QTableWidgetItem("")
                self.table.setItem(row, column, item)
                self.table.blockSignals(False)
            if not self.is_cell_in_selection(row, column):
                self.table.clearSelection()
                item.setSelected(True)
            self.table.setCurrentCell(row, column, QItemSelectionModel.NoUpdate)
        menu = QMenu(self)
        menu.addAction(self.parent_window.tr("copy"), self.copy_selection)
        menu.addAction(self.parent_window.tr("paste"), self.paste_selection)
        menu.addAction(self.parent_window.tr("cut"), self.cut_selection)
        if row >= 0 and column >= 0:
            menu.addAction(self.parent_window.tr("fill_row_with_cell"), self.fill_row_with_cell)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _record_history(self):
        if not self.loading:
            self.history.record(snapshot_table(self.table))

    def undo(self):
        snapshot = self.history.undo()
        if snapshot is None:
            return
        self.history.suppress(True)
        restore_table(self.table, snapshot, block_signal_widget=self.table)
        self.history.suppress(False)
        self.ensure_trailing_empty_row()
        self.set_dirty(True)
        self.auto_save()

    def redo(self):
        snapshot = self.history.redo()
        if snapshot is None:
            return
        self.history.suppress(True)
        restore_table(self.table, snapshot, block_signal_widget=self.table)
        self.history.suppress(False)
        self.ensure_trailing_empty_row()
        self.set_dirty(True)
        self.auto_save()

    def is_cell_in_selection(self, row, column):
        for selected_range in self.table.selectedRanges():
            if selected_range.topRow() <= row <= selected_range.bottomRow() and \
               selected_range.leftColumn() <= column <= selected_range.rightColumn():
                return True
        return False

    def copy_selection(self):
        text = self.selection_as_text()
        if text:
            QApplication.clipboard().setText(text)

    def cut_selection(self):
        self.copy_selection()
        items = self.table.selectedItems()
        if not items:
            return
        self.table.blockSignals(True)
        for item in items:
            item.setText("")
        self.table.blockSignals(False)
        self._record_history()
        self.ensure_trailing_empty_row()
        self.set_dirty(True)
        self.auto_save()

    def fill_row_with_cell(self):
        row = self.table.currentRow()
        column = self.table.currentColumn()
        if row < 0 or column < 0:
            return
        item = self.table.item(row, column)
        if item is None:
            return
        text = item.text()
        if not text:
            return
        self.table.blockSignals(True)
        for column_index in range(1, self.table.columnCount()):
            if column_index == column:
                continue
            target_item = self.table.item(row, column_index)
            if target_item is None or not target_item.text():
                self.set_cell_text(row, column_index, text)
        self.table.blockSignals(False)
        self._record_history()
        self.ensure_trailing_empty_row()
        self.set_dirty(True)
        self.auto_save()

    def paste_selection(self):
        text = QApplication.clipboard().text()
        if not text:
            return
        start_row = self.table.currentRow()
        start_column = self.table.currentColumn()
        if start_row < 0 or start_column < 0:
            start_row = 0
            start_column = 0

        lines = text.splitlines()
        if start_row + len(lines) > self.table.rowCount():
            self.table.setRowCount(start_row + len(lines))

        self.table.blockSignals(True)
        for row_offset, line in enumerate(lines):
            values = line.split("\t")
            for column_offset, value in enumerate(values):
                row_index = start_row + row_offset
                column_index = start_column + column_offset
                if column_index >= self.table.columnCount():
                    continue
                self.set_cell_text(row_index, column_index, value)
        self.table.blockSignals(False)
        self._record_history()
        self.ensure_trailing_empty_row()
        self.set_dirty(True)
        self.auto_save()

    def selection_as_text(self):
        ranges = self.table.selectedRanges()
        if not ranges:
            return ""
        selected_range = ranges[0]
        lines = []
        for row_index in range(selected_range.topRow(), selected_range.bottomRow() + 1):
            values = []
            for column_index in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
                item = self.table.item(row_index, column_index)
                values.append(item.text() if item else "")
            lines.append("\t".join(values))
        return "\n".join(lines)

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, self.parent_window.tr("open_wordbook_csv"), "", self.parent_window.tr("wordbook_files"))
        if path:
            self.load_file(Path(path))

    def load_file(self, path):
        try:
            headers, rows = load_wordbook_csv(path)
        except Exception as exc:
            QMessageBox.critical(self, self.parent_window.tr("open_failed"), str(exc))
            return
        self.current_path = Path(path)
        self.set_rows(rows)
        self.set_dirty(False)

    def save_file(self):
        if not self.current_path:
            return self.save_file_as()
        return self.write_current_file(self.current_path)

    def save_file_as(self):
        path, _ = QFileDialog.getSaveFileName(self, self.parent_window.tr("save_wordbook_csv"), str(self.current_path or Path("wordbook.csv")), self.parent_window.tr("wordbook_files"))
        if path:
            return self.write_current_file(Path(path))
        return False

    def write_current_file(self, path, show_errors=True):
        try:
            write_wordbook_csv(path, self.rows_for_save())
        except Exception as exc:
            if show_errors:
                QMessageBox.critical(self, self.parent_window.tr("save_failed"), str(exc))
            return False
        self.current_path = Path(path)
        self.set_dirty(False)
        self.update_current_file_label()
        return True

    def update_current_file_label(self):
        text = str(self.current_path) if self.current_path else ""
        if self.is_dirty and text:
            text = f"{text}*"
        self.current_file_label.setText(text)

    def set_dirty(self, dirty=True):
        self.is_dirty = dirty
        self.update_current_file_label()

    def set_rows(self, rows):
        self.loading = True
        self.table.blockSignals(True)
        self.table.setRowCount(max(1, len(rows)))
        for row_index in range(self.table.rowCount()):
            row = rows[row_index] if row_index < len(rows) else []
            for column_index in range(len(WORDBOOK_HEADERS)):
                value = row[column_index] if column_index < len(row) else ""
                self.table.setItem(row_index, column_index, QTableWidgetItem(value))
        self.table.blockSignals(False)
        self.ensure_trailing_empty_row()
        self.loading = False
        self.history.clear()
        self.history.record(snapshot_table(self.table))

    def rows_for_save(self):
        return wordbook_rows_for_save(self.table_rows())

    def table_rows(self):
        rows = []
        for row_index in range(self.table.rowCount()):
            row = []
            for column_index in range(self.table.columnCount()):
                item = self.table.item(row_index, column_index)
                row.append(item.text() if item else "")
            rows.append(row)
        return rows

    def glossary_rows(self):
        return self.rows_for_save()

    def set_cell_text(self, row_index, column_index, text):
        item = self.table.item(row_index, column_index)
        if item is None:
            item = QTableWidgetItem("")
            self.table.setItem(row_index, column_index, item)
        item.setText(text)

    def ensure_trailing_empty_row(self):
        if self.table.rowCount() == 0:
            self.table.setRowCount(1)
            self._fill_row_items(0)
            return
        self._fill_row_items(self.table.rowCount() - 1)
        if not self._is_empty_table_row(self.table.rowCount() - 1):
            self.table.blockSignals(True)
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            self._fill_row_items(row_index)
            self.table.blockSignals(False)

    def _fill_row_items(self, row_index):
        for column_index in range(self.table.columnCount()):
            if self.table.item(row_index, column_index) is None:
                self.table.setItem(row_index, column_index, QTableWidgetItem(""))

    def _is_empty_table_row(self, row_index):
        for column_index in range(self.table.columnCount()):
            item = self.table.item(row_index, column_index)
            if item and item.text().strip():
                return False
        return True

    def handle_item_changed(self, item):
        if self.loading:
            return
        self._record_history()
        self.ensure_trailing_empty_row()
        self.set_dirty(True)
        # 自动保存防抖：连续按键合并为一次写盘，避免每次按键都全量写 CSV。
        self._auto_save_timer.start()

    def auto_save(self):
        # 取消挂起的防抖，避免手动保存（undo/redo/批量操作）后又重复写盘。
        self._auto_save_timer.stop()
        self.write_current_file(self.current_path, show_errors=False)

    def confirm_unsaved_close(self):
        if not self.is_dirty:
            return True
        path = str(self.current_path) if self.current_path else "wordbook.csv"
        result = QMessageBox.warning(
            self,
            self.parent_window.tr("unsaved_changes"),
            self.parent_window.tr("save_changes_before_close", path=path),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Save:
            return self.save_file()
        return result == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        if self.isVisible() and not self.confirm_unsaved_close():
            event.ignore()
            return
        # 关闭前 flush 挂起的自动保存，确保最近编辑已写盘。
        if self._auto_save_timer.isActive():
            self._auto_save_timer.stop()
            self.auto_save()
        super().closeEvent(event)


class DayzTranslateTool(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.headers = []
        self.current_path = None
        self.loading = False
        self.is_dirty = False
        self.settings = settings if settings is not None else QSettings("DayZTranslateTool", "DayZTranslateTool")
        self.last_file_directory = self.settings.value("last_file_directory", "")
        self.source_header = self.settings.value("source_header", "english")
        self.translation_provider = normalize_provider(self.settings.value("translation_provider", "google"))
        self.translation_char_budget = int(
            self.settings.value("translation_char_budget", DEFAULT_CHAR_BUDGET)
        )
        self.translation_auto_concurrency = str(
            self.settings.value("translation_auto_concurrency", "true")
        ).lower() in ("true", "1", "yes")
        self.translation_parallel_batches = int(self.settings.value("translation_parallel_batches", 1))
        self.translation_timeout = float(self.settings.value("translation_timeout", 60.0))
        self.provider_settings = self._load_provider_settings()
        self.ui_language = self.settings.value("ui_language", "en")
        self.qt_translators = []
        self.history = TableHistory()
        self.table = QTableWidget(self)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.itemChanged.connect(self.handle_item_changed)
        self.table.customContextMenuRequested.connect(self.open_context_menu)
        self.table.setStyleSheet(f"QTableWidget {{ gridline-color: {TABLE_GRIDLINE_COLOR}; }}")
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.open_column_header_context_menu)
        self.table.horizontalHeader().setSectionsMovable(True)
        self.table.verticalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.verticalHeader().customContextMenuRequested.connect(self.open_row_header_context_menu)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setWordWrap(False)
        self.setCentralWidget(self.table)
        self._no_tooltip_filter = _NoToolTipFilter(self)
        self.table.viewport().installEventFilter(self._no_tooltip_filter)
        self.table.setItemDelegate(_ClipTextDelegate(self.table))
        self.resize(1600, 900)
        self.setWindowTitle("DayZ Translate Tool")
        self.search_dialog = None
        self.wordbook_window = None
        self.progress_dialog = None
        self.translation_progress_label = QLabel("", self)
        self.translation_progress_bar = QProgressBar(self)
        self.translation_cancel_button = QPushButton("Cancel", self)
        self.current_file_label = QLabel("", self)
        self.translation_thread = None
        self.translation_worker = None
        # 跨次翻译共享的缓存：相同 (引擎, 模型, 源/目标语言, 文本) 的结果只翻译一次。
        # 落盘在软件目录旁，重开软件仍能复用；写不进去则回退到用户数据目录。
        self.translation_cache_store = TranslationCacheStore()
        self.translation_cache = self.translation_cache_store.load()
        self._translation_written_cells = set()
        self._translation_job_rows = set()
        self._translation_copy_overwrite = True
        self.create_menus()
        self.create_edit_actions()
        self.create_translation_status_widgets()
        self.apply_ui_language()

        if DEFAULT_CSV_PATH.exists():
            self.load_file(DEFAULT_CSV_PATH)

    def tr(self, key, **kwargs):
        text = UI_TEXT.get(self.ui_language, UI_TEXT["en"]).get(key, UI_TEXT["en"].get(key, key))
        return text.format(**kwargs) if kwargs else text

    def create_menus(self):
        self.menu_file = self.menuBar().addMenu("File")

        self.action_open = QAction("Open", self)
        self.action_open.setShortcut(QKeySequence.Open)
        self.action_open.triggered.connect(self.open_file)
        self.menu_file.addAction(self.action_open)

        self.action_save = QAction("Save", self)
        self.action_save.setShortcut(QKeySequence.Save)
        self.action_save.triggered.connect(self.save_file)
        self.menu_file.addAction(self.action_save)

        self.action_save_as = QAction("Save As", self)
        self.action_save_as.triggered.connect(self.save_file_as)
        self.menu_file.addAction(self.action_save_as)

        self.menu_file.addSeparator()
        self.action_import_config_cpp = QAction("Import from config.cpp...", self)
        self.action_import_config_cpp.triggered.connect(self.import_from_config_cpp_files)
        self.menu_file.addAction(self.action_import_config_cpp)
        self.action_import_config_folder = QAction("Import config.cpp from Folder...", self)
        self.action_import_config_folder.triggered.connect(self.import_config_cpp_from_folder)
        self.menu_file.addAction(self.action_import_config_folder)

        self.menu_file.addSeparator()
        self.action_translate_all = QAction("Translate All Cells", self)
        self.action_translate_all.triggered.connect(self.translate_all_cells)
        self.menu_file.addAction(self.action_translate_all)
        self.action_translate_empty = QAction("Translate Empty Cells", self)
        self.action_translate_empty.triggered.connect(self.translate_empty_cells)
        self.menu_file.addAction(self.action_translate_empty)

        self.menu_search = self.menuBar().addMenu("Search")
        self.search_action = QAction("Search", self)
        self.search_action.setShortcut(QKeySequence.Find)
        self.search_action.triggered.connect(self.open_search_dialog)
        self.menu_search.addAction(self.search_action)

        self.menu_settings = self.menuBar().addMenu("Settings")
        self.action_source_language = QAction("Source Language", self)
        self.action_source_language.triggered.connect(self.choose_source_language)
        self.menu_settings.addAction(self.action_source_language)
        self.action_translation_settings = QAction("Translation Settings...", self)
        self.action_translation_settings.triggered.connect(self.open_translation_settings)
        self.menu_settings.addAction(self.action_translation_settings)
        self.action_language_settings = QAction("Interface Language...", self)
        self.action_language_settings.triggered.connect(self.open_language_settings)
        self.menu_settings.addAction(self.action_language_settings)

        self.menu_wordbook = self.menuBar().addMenu("Wordbook")
        self.action_open_wordbook = QAction("Wordbook", self)
        self.action_open_wordbook.triggered.connect(self.open_wordbook_window)
        self.menu_wordbook.addAction(self.action_open_wordbook)

    def create_edit_actions(self):
        copy_action = QAction(self)
        copy_action.setShortcut(QKeySequence.Copy)
        copy_action.triggered.connect(self.copy_selection)
        self.addAction(copy_action)

        paste_action = QAction(self)
        paste_action.setShortcut(QKeySequence.Paste)
        paste_action.triggered.connect(self.paste_selection)
        self.addAction(paste_action)

        cut_action = QAction(self)
        cut_action.setShortcut(QKeySequence.Cut)
        cut_action.triggered.connect(self.cut_selection)
        self.addAction(cut_action)

        undo_action = QAction(self)
        undo_action.setShortcut(QKeySequence.Undo)
        undo_action.triggered.connect(self.undo)
        self.addAction(undo_action)

        redo_action = QAction(self)
        redo_action.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Shift+Z")])
        redo_action.triggered.connect(self.redo)
        self.addAction(redo_action)

    def apply_ui_language(self):
        self._apply_qt_translators()
        texts = UI_TEXT.get(self.ui_language, UI_TEXT["en"])
        self.menu_file.setTitle(texts["file"])
        self.action_open.setText(texts["open"])
        self.action_save.setText(texts["save"])
        self.action_save_as.setText(texts["save_as"])
        self.action_import_config_cpp.setText(texts["import_config_cpp"])
        self.action_import_config_folder.setText(texts["import_config_cpp_folder"])
        self.action_translate_all.setText(texts["translate_all_cells"])
        self.action_translate_empty.setText(texts["translate_empty_cells"])
        self.menu_search.setTitle(texts["search"])
        self.search_action.setText(texts["search"])
        self.menu_settings.setTitle(texts["settings"])
        self.action_source_language.setText(texts["source_language"])
        self.action_translation_settings.setText(texts["translation_settings"])
        self.action_language_settings.setText(texts["language_settings"])
        self.menu_wordbook.setTitle(texts["wordbook"])
        self.action_open_wordbook.setText(texts["wordbook"])
        self.translation_cancel_button.setText(texts["cancel"])

    def _apply_qt_translators(self):
        app = QApplication.instance()
        for translator in self.qt_translators:
            app.removeTranslator(translator)
        self.qt_translators = []
        if self.ui_language != "zh":
            return
        locale_map = {"zh": "zh_CN"}
        qt_locale = locale_map.get(self.ui_language, self.ui_language)
        translations_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        for prefix in ("qt", "qtbase"):
            translator = QTranslator(self)
            if translator.load(f"{prefix}_{qt_locale}", translations_dir):
                app.installTranslator(translator)
                self.qt_translators.append(translator)

    def create_translation_status_widgets(self):
        self.translation_progress_bar.setRange(0, 1)
        self.translation_progress_bar.setValue(0)
        self.translation_progress_bar.setFixedWidth(260)
        self.translation_cancel_button.setFixedWidth(80)
        self.translation_cancel_button.clicked.connect(self.cancel_translation)
        self.statusBar().addPermanentWidget(self.translation_progress_label)
        self.statusBar().addPermanentWidget(self.translation_progress_bar)
        self.statusBar().addPermanentWidget(self.translation_cancel_button)
        self.statusBar().addPermanentWidget(self.current_file_label, 1)
        self.hide_translation_progress()

    def hide_translation_progress(self):
        self.translation_progress_label.hide()
        self.translation_progress_bar.hide()
        self.translation_cancel_button.hide()

    def show_translation_progress(self, total):
        self.translation_progress_label.setText(f"0/{total}")
        self.translation_progress_bar.setRange(0, total)
        self.translation_progress_bar.setValue(0)
        self.translation_progress_label.show()
        self.translation_progress_bar.show()
        self.translation_cancel_button.show()
        self._translation_written_cells = set()

    def open_file(self):
        start_dir = self.last_file_directory or str(DEFAULT_CSV_PATH)
        path, _ = QFileDialog.getOpenFileName(self, self.tr("open_dayz_csv"), start_dir, self.tr("csv_files"))
        if path:
            self.open_csv_from_path(path)

    def open_csv_from_path(self, path):
        self.load_file(Path(path))
        self.last_file_directory = str(Path(path).parent)
        self.settings.setValue("last_file_directory", self.last_file_directory)

    def load_file(self, path):
        # 翻译进行中加载新文件会让 worker 用旧的行/列索引写入新表格，造成数据损坏。
        if self._is_translation_running():
            QMessageBox.warning(self, self.tr("translate"), self.tr("translation_in_progress"))
            return
        try:
            headers, rows, warnings = load_dayz_csv(path)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("open_failed"), str(exc))
            return

        self.headers = headers
        self.current_path = Path(path)
        self.apply_table_rows(rows, dirty=False)
        message = self.tr("loaded", path=self.current_path)
        if warnings:
            message = f"{message} | " + "; ".join(warnings)
        self.statusBar().showMessage(message, 8000)

    def apply_table_rows(self, rows, dirty=True):
        self.loading = True
        self.table.blockSignals(True)
        self.table.clear()
        visible_headers = self.visible_headers()
        self.table.setColumnCount(len(visible_headers))
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(visible_headers)

        for row_index, row in enumerate(rows):
            for column_index in range(len(visible_headers)):
                value = row[column_index] if column_index < len(row) else ""
                self.table.setItem(row_index, column_index, QTableWidgetItem(value))

        self.table.blockSignals(False)
        self.loading = False
        self.apply_column_widths()
        self.set_dirty(bool(dirty))
        self.history.clear()
        self.history.record(snapshot_table(self.table))

    def import_from_config_cpp_files(self):
        if not self.headers:
            QMessageBox.warning(self, self.tr("import_failed"), self.tr("import_requires_csv"))
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr("import_config_cpp_title"),
            "",
            self.tr("config_cpp_files"),
        )
        if not paths:
            return
        self._import_config_cpp_paths(paths)

    def import_config_cpp_from_folder(self):
        if not self.headers:
            QMessageBox.warning(self, self.tr("import_failed"), self.tr("import_requires_csv"))
            return
        folder = QFileDialog.getExistingDirectory(self, self.tr("import_config_folder_title"), "")
        if not folder:
            return
        paths = collect_config_cpp_files(folder)
        if not paths:
            QMessageBox.information(self, self.tr("import_failed"), self.tr("import_no_files"))
            return
        self._import_config_cpp_paths(paths)

    def _import_config_cpp_paths(self, paths):
        if not self.headers:
            QMessageBox.warning(self, self.tr("import_failed"), self.tr("import_requires_csv"))
            return
        try:
            keys, file_warnings = extract_keys_from_paths(paths)
            existing = self.table_rows()
            merged, added, skipped = merge_language_keys(existing, keys)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("import_failed"), str(exc))
            return

        files_count = len(list(paths))
        if added == 0:
            msg = self.tr("import_no_new_keys", skipped=skipped, files=files_count)
            if file_warnings:
                msg = msg + "\n" + "\n".join(file_warnings)
            QMessageBox.information(self, self.tr("import_config_cpp"), msg)
            return

        self.apply_table_rows(merged, dirty=True)
        msg = self.tr("import_result", added=added, skipped=skipped, files=files_count)
        if file_warnings:
            msg = f"{msg} | " + "; ".join(file_warnings)
        self.statusBar().showMessage(msg, 8000)

    def apply_column_widths(self):
        for column_index in range(self.table.columnCount()):
            width = LANGUAGE_COLUMN_WIDTH if column_index == 0 else DEFAULT_COLUMN_WIDTH
            self.table.setColumnWidth(column_index, width)

    def visible_headers(self):
        if self.headers and self.headers[-1] == "":
            return self.headers[:-1]
        return self.headers

    def save_file(self):
        if not self.current_path:
            return self.save_file_as()
        return self.write_current_file(self.current_path)

    def save_file_as(self):
        start_dir = self.last_file_directory or str(self.current_path or DEFAULT_CSV_PATH)
        path, _ = QFileDialog.getSaveFileName(self, self.tr("save_dayz_csv"), start_dir, self.tr("csv_files"))
        if path:
            return self.save_csv_to_path(path)
        return False

    def save_csv_to_path(self, path):
        result = self.write_current_file(Path(path))
        if result:
            self.last_file_directory = str(Path(path).parent)
            self.settings.setValue("last_file_directory", self.last_file_directory)
        return result

    def write_current_file(self, path):
        if not self.headers:
            QMessageBox.warning(self, self.tr("save_skipped"), self.tr("no_dayz_csv_loaded"))
            return False
        rows = self.table_rows()
        try:
            write_dayz_csv(path, self.headers, rows)
        except Exception as exc:
            QMessageBox.critical(self, self.tr("save_failed"), str(exc))
            return False
        self.current_path = Path(path)
        self.set_dirty(False)
        self.statusBar().showMessage(self.tr("saved", path=self.current_path), 5000)
        return True

    def update_current_file_label(self):
        text = str(self.current_path) if self.current_path else ""
        if self.is_dirty and text:
            text = f"{text}*"
        self.current_file_label.setText(text)

    def set_dirty(self, dirty=True):
        self.is_dirty = dirty
        self.update_current_file_label()

    def handle_item_changed(self, item):
        if self.loading:
            return
        self._record_history()
        self.set_dirty(True)

    def _record_history(self):
        if not self.loading:
            self.history.record(snapshot_table(self.table))

    def undo(self):
        snapshot = self.history.undo()
        if snapshot is None:
            return
        self.history.suppress(True)
        restore_table(self.table, snapshot, block_signal_widget=self.table)
        self.history.suppress(False)
        self.set_dirty(True)

    def redo(self):
        snapshot = self.history.redo()
        if snapshot is None:
            return
        self.history.suppress(True)
        restore_table(self.table, snapshot, block_signal_widget=self.table)
        self.history.suppress(False)
        self.set_dirty(True)

    def table_rows(self):
        rows = []
        for row_index in range(self.table.rowCount()):
            row = []
            for column_index in range(len(self.visible_headers())):
                item = self.table.item(row_index, column_index)
                row.append(item.text() if item else "")
            if len(row) < len(self.headers):
                row.extend([""] * (len(self.headers) - len(row)))
            rows.append(row)
        return rows

    def choose_source_language(self):
        if not self.headers:
            QMessageBox.warning(self, self.tr("settings"), self.tr("load_csv_before_source"))
            return
        usable_headers = [header for header in self.headers if header and header != "Language"]
        current_index = max(0, usable_headers.index(self.source_header)) if self.source_header in usable_headers else 0
        value, ok = QInputDialog.getItem(self, self.tr("source_language"), self.tr("source_column"), usable_headers, current_index, False)
        if ok and value:
            self.source_header = value
            self.settings.setValue("source_header", value)
            self.statusBar().showMessage(self.tr("source_language_status", value=value), 5000)

    def open_translation_settings(self):
        dialog = TranslationSettingsDialog(self)
        dialog.exec()

    def open_language_settings(self):
        dialog = LanguageSettingsDialog(self)
        dialog.exec()

    def open_wordbook_window(self):
        if self.wordbook_window is None:
            self.wordbook_window = WordbookWindow(self)
        self.wordbook_window.show()
        self.wordbook_window.raise_()
        self.wordbook_window.activateWindow()

    def _load_provider_settings(self):
        result = {}
        for provider, defaults in PROVIDER_DEFAULTS.items():
            self.settings.beginGroup(f"provider_settings/{provider}")
            values = {}
            for key, default_value in defaults.items():
                stored = self.settings.value(key, None)
                values[key] = stored if stored is not None else default_value
            self.settings.endGroup()
            result[provider] = values
        return result

    def _save_provider_settings(self):
        for provider, values in self.provider_settings.items():
            self.settings.beginGroup(f"provider_settings/{provider}")
            for key, value in values.items():
                self.settings.setValue(key, value)
            self.settings.endGroup()
        self.settings.sync()

    def get_provider_setting(self, provider, key, default=""):
        return self.provider_settings.get(provider, {}).get(key, default)

    def set_provider_setting(self, provider, key, value):
        if provider not in self.provider_settings:
            self.provider_settings[provider] = {}
        self.provider_settings[provider][key] = value

    @property
    def translation_api_key(self):
        return self.get_provider_setting(self.translation_provider, "api_key", "")

    @translation_api_key.setter
    def translation_api_key(self, value):
        self.set_provider_setting(self.translation_provider, "api_key", value)

    @property
    def translation_region(self):
        return self.get_provider_setting(self.translation_provider, "region", "")

    @translation_region.setter
    def translation_region(self, value):
        self.set_provider_setting(self.translation_provider, "region", value)

    @property
    def translation_model(self):
        return self.get_provider_setting(self.translation_provider, "model", "gpt-3.5-turbo")

    @translation_model.setter
    def translation_model(self, value):
        self.set_provider_setting(self.translation_provider, "model", value)

    @property
    def translation_base_url(self):
        return self.get_provider_setting(self.translation_provider, "base_url", "")

    @translation_base_url.setter
    def translation_base_url(self, value):
        self.set_provider_setting(self.translation_provider, "base_url", value)

    @property
    def translation_email(self):
        return self.get_provider_setting(self.translation_provider, "email", "")

    @translation_email.setter
    def translation_email(self, value):
        self.set_provider_setting(self.translation_provider, "email", value)

    def save_translation_settings(self):
        self.settings.setValue("translation_provider", self.translation_provider)
        self.settings.setValue("translation_char_budget", self.translation_char_budget)
        self.settings.setValue("translation_auto_concurrency", self.translation_auto_concurrency)
        self.settings.setValue("translation_parallel_batches", self.translation_parallel_batches)
        self.settings.setValue("translation_timeout", self.translation_timeout)
        self._save_provider_settings()
        self.statusBar().showMessage(
            self.tr("translation_engine_status", engine=PROVIDER_LABELS.get(self.translation_provider, self.translation_provider)),
            5000,
        )

    def current_translation_settings_dict(self):
        return {
            "provider": self.translation_provider,
            "char_budget": self.translation_char_budget,
            "auto_concurrency": self.translation_auto_concurrency,
            "parallel_batches": self.translation_parallel_batches,
            "timeout": self.translation_timeout,
            "api_key": self.translation_api_key,
            "region": self.translation_region,
            "model": self.translation_model,
            "base_url": self.translation_base_url,
            "email": self.translation_email,
        }

    def apply_translation_settings_dict(self, values):
        # Apply explicit preset/settings values. Do not use `or` for strings:
        # empty strings and missing-vs-stale values must not keep the previous
        # provider field (that caused flaky preset switches).
        provider = values.get("provider")
        if provider:
            self.translation_provider = normalize_provider(provider)
        # 旧键 batch_size 存的是「行数」（默认 30），新键 char_budget 是「字数」。
        # 旧值 30 落在新区间里，直接拿来用就会被当成「每批 30 个字」—— 一律换成默认值。
        char_budget = values.get("char_budget")
        if char_budget is None or char_budget == "":
            legacy = values.get("batch_size")
            if legacy is not None and legacy != "":
                char_budget = DEFAULT_CHAR_BUDGET
        if char_budget is not None and char_budget != "":
            self.translation_char_budget = int(char_budget)
        auto_concurrency = values.get("auto_concurrency")
        if auto_concurrency is not None and auto_concurrency != "":
            self.translation_auto_concurrency = bool(auto_concurrency)
        parallel_batches = values.get("parallel_batches")
        if parallel_batches is not None and parallel_batches != "":
            self.translation_parallel_batches = int(parallel_batches)
        timeout = values.get("timeout")
        if timeout is not None and timeout != "":
            self.translation_timeout = float(timeout)
        if "api_key" in values:
            self.translation_api_key = "" if values.get("api_key") is None else str(values.get("api_key"))
        if "region" in values:
            self.translation_region = "" if values.get("region") is None else str(values.get("region"))
        if "model" in values:
            self.translation_model = "" if values.get("model") is None else str(values.get("model"))
        if "base_url" in values:
            self.translation_base_url = "" if values.get("base_url") is None else str(values.get("base_url"))
        if "email" in values:
            self.translation_email = "" if values.get("email") is None else str(values.get("email"))
        self.save_translation_settings()

    def translation_preset_names(self):
        names = self.settings.value("translation_preset_names_list", [])
        if isinstance(names, str):
            names = [names]
        return sorted(names)

    def save_translation_preset(self, name):
        name = (name or "").strip()
        if not name:
            return
        prefix = f"translation_presets/{name}/"
        for key, value in self.current_translation_settings_dict().items():
            self.settings.setValue(prefix + key, value)
        self.settings.sync()
        names = self.translation_preset_names()
        if name not in names:
            names.append(name)
        self.settings.setValue("translation_preset_names_list", names)
        self.settings.sync()

    def load_translation_preset(self, name):
        name = (name or "").strip()
        if not name:
            return
        preset_keys = ["provider", "char_budget", "parallel_batches", "timeout", "api_key", "region", "model", "base_url", "email", "batch_size"]
        prefix = f"translation_presets/{name}/"
        # Always include keys so apply overwrites previous provider fields.
        values = {key: self.settings.value(prefix + key, "") for key in preset_keys}
        self.apply_translation_settings_dict(values)

    def delete_translation_preset(self, name):
        name = (name or "").strip()
        if not name:
            return
        self.settings.remove(f"translation_presets/{name}")
        names = self.translation_preset_names()
        if name in names:
            names.remove(name)
        self.settings.setValue("translation_preset_names_list", names)

    def save_ui_language(self):
        self.settings.setValue("ui_language", self.ui_language)

    def is_cell_in_selection(self, row, column):
        for selected_range in self.table.selectedRanges():
            if selected_range.topRow() <= row <= selected_range.bottomRow() and \
               selected_range.leftColumn() <= column <= selected_range.rightColumn():
                return True
        return False

    def has_multi_cell_selection(self):
        ranges = self.table.selectedRanges()
        if len(ranges) > 1:
            return True
        for selected_range in ranges:
            rows = selected_range.bottomRow() - selected_range.topRow() + 1
            columns = selected_range.rightColumn() - selected_range.leftColumn() + 1
            if rows * columns > 1:
                return True
        return False

    def open_context_menu(self, position):
        # customContextMenuRequested 传递的是 viewport 坐标，rowAt/columnAt 直接使用。
        row = self.table.rowAt(position.y())
        # columnAt 返回 visual 索引，列拖拽重排后必须转为 logical 索引才能正确访问数据。
        visual_column = self.table.columnAt(position.x())
        column = self.table.horizontalHeader().logicalIndex(visual_column) if visual_column >= 0 else -1
        if row >= 0 and column >= 0:
            item = self.table.item(row, column)
            if item is None:
                # 创建空 item 仅用于选中，屏蔽信号避免触发 dirty 标记和历史快照。
                self.table.blockSignals(True)
                item = QTableWidgetItem("")
                self.table.setItem(row, column, item)
                self.table.blockSignals(False)
            if not self.is_cell_in_selection(row, column):
                self.table.clearSelection()
                item.setSelected(True)
            self.table.setCurrentCell(row, column, QItemSelectionModel.NoUpdate)
        self.show_context_menu("cell", row, column, self.table.viewport().mapToGlobal(position))

    def open_row_header_context_menu(self, position):
        row = self.table.verticalHeader().logicalIndexAt(position)
        if row >= 0:
            self.table.selectRow(row)
        self.show_context_menu("row_header", row, -1, self.table.verticalHeader().mapToGlobal(position))

    def open_column_header_context_menu(self, position):
        column = self.table.horizontalHeader().logicalIndexAt(position)
        if column >= 0:
            self.table.selectColumn(column)
        self.show_context_menu("column_header", -1, column, self.table.horizontalHeader().mapToGlobal(position))

    def show_context_menu(self, context, row, column, global_position):
        menu = QMenu(self)
        action_map = {
            "copy": self.copy_selection,
            "paste": self.paste_selection,
            "cut": self.cut_selection,
            "delete_cell": self.delete_cell_text,
            "delete_selected_cells": self.delete_selected_cells,
            "delete_row": self.delete_rows,
            "delete_column": self.delete_column_cells,
            "reset_column_order": self.reset_column_order,
            "insert_row_above": self.insert_row_above,
            "insert_row_below": self.insert_row_below,
            "fill_row_with_cell": self.fill_row_with_cell,
            "translate_selected_cells": self.translate_selected_cells,
            "translate_selected_rows": self.translate_selected_rows,
            "translate_selected_columns": self.translate_selected_columns,
        }
        for name in self.context_action_names(context, row, column):
            if name == "-":
                menu.addSeparator()
            else:
                menu.addAction(self.tr(name), action_map[name])
        menu.exec(global_position)

    def context_action_labels(self, context, row, column):
        return [name if name == "-" else self.tr(name) for name in self.context_action_names(context, row, column)]

    def context_action_names(self, context, row, column):
        actions = ["copy", "paste", "cut"]
        if context == "row_header" and row >= 0:
            actions.extend(["insert_row_above", "insert_row_below", "-", "delete_row"])
        elif context == "column_header" and column >= 0:
            actions.extend(["reset_column_order", "-", "delete_column"])
        elif context == "cell" and row >= 0 and column >= 0:
            actions.append("delete_cell")
            if self.has_multi_cell_selection():
                actions.append("delete_selected_cells")
            actions.append("fill_row_with_cell")
        translate_actions = []
        if context == "row_header" and row >= 0:
            translate_actions = ["translate_selected_rows"]
        elif context == "column_header" and self.is_translatable_column(column):
            translate_actions = ["translate_selected_columns"]
        elif context == "cell":
            rows, columns = self.selection_or_current(row, column)
            if any(self.is_translatable_column(index) for index in columns):
                translate_actions = ["translate_selected_cells"]
            elif rows and any(index > 0 for index in columns):
                translate_actions = []
        if translate_actions:
            actions.append("-")
            actions.extend(translate_actions)
        return actions

    def selection_or_current(self, row, column):
        rows, columns = self.selected_rows_and_columns()
        if row >= 0:
            rows.add(row)
        if column >= 0:
            columns.add(column)
        return rows, columns

    def is_translatable_column(self, column):
        if column <= 0 or column >= len(self.visible_headers()):
            return False
        if is_copy_only_column(self.headers[column]):
            return False
        return bool(language_code_for_header(self.headers[column]))

    def copy_selection(self):
        text = self.selection_as_text()
        if text:
            QApplication.clipboard().setText(text)

    def cut_selection(self):
        self.copy_selection()
        items = self.table.selectedItems()
        if not items:
            return
        self.table.blockSignals(True)
        for item in items:
            item.setText("")
        self.table.blockSignals(False)
        self._record_history()
        self.set_dirty(True)

    def delete_cell_text(self):
        row = self.table.currentRow()
        column = self.table.currentColumn()
        if row < 0 or column < 0:
            return
        self.set_cell_text(row, column, "")

    def fill_row_with_cell(self):
        row = self.table.currentRow()
        column = self.table.currentColumn()
        if row < 0 or column < 0:
            return
        item = self.table.item(row, column)
        if item is None:
            return
        text = item.text()
        if not text:
            return
        self.table.blockSignals(True)
        for column_index in range(1, self.table.columnCount()):
            if column_index == column:
                continue
            target_item = self.table.item(row, column_index)
            if target_item is None or not target_item.text():
                self.set_cell_text(row, column_index, text)
        self.table.blockSignals(False)
        self._record_history()
        self.set_dirty(True)

    def delete_selected_cells(self):
        ranges = self.table.selectedRanges()
        if not ranges:
            return
        self.table.blockSignals(True)
        for selected_range in ranges:
            for row_index in range(selected_range.topRow(), selected_range.bottomRow() + 1):
                for column_index in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
                    self.set_cell_text(row_index, column_index, "")
        self.table.blockSignals(False)
        self._record_history()
        self.set_dirty(True)

    def delete_rows(self):
        rows, columns = self.selected_rows_and_columns()
        current_row = self.table.currentRow()
        if not rows and current_row >= 0:
            rows = {current_row}
        if not rows:
            return
        for row_index in sorted(rows, reverse=True):
            if 0 <= row_index < self.table.rowCount():
                self.table.removeRow(row_index)
        self._record_history()
        self.set_dirty(True)

    def insert_row_above(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.blockSignals(True)
        self.table.insertRow(row)
        self._fill_new_row(row)
        self.table.blockSignals(False)
        self._record_history()
        self.set_dirty(True)

    def insert_row_below(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.blockSignals(True)
        self.table.insertRow(row + 1)
        self._fill_new_row(row + 1)
        self.table.blockSignals(False)
        self._record_history()
        self.set_dirty(True)

    def _fill_new_row(self, row):
        for column_index in range(self.table.columnCount()):
            if self.table.item(row, column_index) is None:
                self.table.setItem(row, column_index, QTableWidgetItem(""))

    def reset_column_order(self):
        header = self.table.horizontalHeader()
        for visual_index in range(header.count()):
            for search_visual in range(visual_index, header.count()):
                if header.logicalIndex(search_visual) == visual_index:
                    if search_visual != visual_index:
                        header.moveSection(search_visual, visual_index)
                    break

    def delete_column_cells(self):
        column = self.table.currentColumn()
        if column < 0:
            columns = self.selected_columns()
            if not columns:
                return
            column = min(columns)
        if column < 0 or column >= self.table.columnCount():
            return
        self.table.blockSignals(True)
        for row_index in range(self.table.rowCount()):
            self.set_cell_text(row_index, column, "")
        self.table.blockSignals(False)
        self._record_history()
        self.set_dirty(True)

    def paste_selection(self):
        text = QApplication.clipboard().text()
        if not text:
            return
        start_row = self.table.currentRow()
        start_column = self.table.currentColumn()
        if start_row < 0 or start_column < 0:
            start_row = 0
            start_column = 0

        lines = text.splitlines()
        if start_row + len(lines) > self.table.rowCount():
            self.table.setRowCount(start_row + len(lines))

        self.table.blockSignals(True)
        for row_offset, line in enumerate(lines):
            values = line.split("\t")
            for column_offset, value in enumerate(values):
                row_index = start_row + row_offset
                column_index = start_column + column_offset
                if column_index >= self.table.columnCount():
                    continue
                self.set_cell_text(row_index, column_index, value)
        self.table.blockSignals(False)
        self._record_history()
        self.set_dirty(True)

    def selection_as_text(self):
        ranges = self.table.selectedRanges()
        if not ranges:
            return ""
        selected_range = ranges[0]
        lines = []
        for row_index in range(selected_range.topRow(), selected_range.bottomRow() + 1):
            values = []
            for column_index in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
                item = self.table.item(row_index, column_index)
                values.append(item.text() if item else "")
            lines.append("\t".join(values))
        return "\n".join(lines)

    def translate_selected_cells(self):
        jobs = []
        rows = self.table_rows()
        try:
            source_column = self.headers.index(self.source_header)
        except ValueError:
            QMessageBox.warning(self, self.tr("translate_cells"), self.tr("source_column_missing", header=self.source_header))
            return
        for item in self.selected_cell_items():
            if not self.is_translatable_column(item.column()):
                continue
            target_code = language_code_for_header(self.headers[item.column()])
            source_text = rows[item.row()][source_column].strip()
            if source_text and target_code:
                jobs.append((item.row(), item.column(), source_text, target_code))
        # 复制列（original<-english, chinese<-chinesesimp）在翻译前填充，不受翻译成败影响
        self._fill_copy_columns(rows, overwrite=True, row_indexes={item.row() for item in self.selected_cell_items()})
        self.run_translation_jobs(jobs)

    def selected_cell_items(self):
        items = list(self.table.selectedItems())
        if items:
            return items
        row = self.table.currentRow()
        column = self.table.currentColumn()
        if row < 0 or column < 0:
            return []
        item = self.table.item(row, column)
        # 不创建空 item（会触发 itemChanged → 标记 dirty + 推历史快照）。
        # 空单元格没有源文本，翻译无意义，直接跳过即可。
        return [item] if item is not None else []

    def translate_selected_rows(self):
        rows, columns = self.selected_rows_and_columns()
        if not rows:
            current_row = self.table.currentRow()
            rows = {current_row} if current_row >= 0 else set()
        try:
            jobs = build_row_translation_jobs(self.headers, self.table_rows(), self.source_header, rows)
        except Exception as exc:
            QMessageBox.warning(self, self.tr("translate_rows"), str(exc))
            return
        # 复制列（original<-english, chinese<-chinesesimp）在翻译前填充，不受翻译成败影响
        self._fill_copy_columns(self.table_rows(), overwrite=True, row_indexes=rows)
        self.run_translation_jobs(jobs)

    def translate_selected_columns(self):
        rows, columns = self.selected_rows_and_columns()
        if not columns:
            current_column = self.table.currentColumn()
            columns = {current_column} if current_column >= 0 else set()
        try:
            jobs = build_column_translation_jobs(self.headers, self.table_rows(), self.source_header, columns)
        except Exception as exc:
            QMessageBox.warning(self, self.tr("translate_columns"), str(exc))
            return
        # 复制列（original<-english, chinese<-chinesesimp）在翻译前填充，不受翻译成败影响
        self._fill_copy_columns(self.table_rows(), overwrite=True)
        self.run_translation_jobs(jobs)

    def translate_all_cells(self):
        try:
            source_column = self.headers.index(self.source_header)
        except ValueError:
            QMessageBox.warning(self, self.tr("translate_cells"), self.tr("source_column_missing", header=self.source_header))
            return
        rows = self.table_rows()
        # 复制列（original<-english, chinese<-chinesesimp）直接填充，不走 AI 翻译
        self._fill_copy_columns(rows, overwrite=True)
        jobs = []
        for row_index, row in enumerate(rows):
            source_text = row[source_column].strip() if source_column < len(row) else ""
            if not source_text:
                continue
            for col_index in range(len(self.headers)):
                if col_index == source_column or not self.is_translatable_column(col_index):
                    continue
                target_code = language_code_for_header(self.headers[col_index])
                if target_code:
                    jobs.append((row_index, col_index, source_text, target_code))
        self.run_translation_jobs(jobs)

    def translate_empty_cells(self):
        try:
            source_column = self.headers.index(self.source_header)
        except ValueError:
            QMessageBox.warning(self, self.tr("translate_cells"), self.tr("source_column_missing", header=self.source_header))
            return
        rows = self.table_rows()
        # 复制列（original<-english, chinese<-chinesesimp）仅填充空白单元格
        self._fill_copy_columns(rows, overwrite=False)
        # 重新读取已更新的行数据，使后续空白判断反映复制结果
        rows = self.table_rows()
        jobs = []
        for row_index, row in enumerate(rows):
            source_text = row[source_column].strip() if source_column < len(row) else ""
            if not source_text:
                continue
            for col_index in range(len(self.headers)):
                if col_index == source_column or not self.is_translatable_column(col_index):
                    continue
                target_code = language_code_for_header(self.headers[col_index])
                if not target_code:
                    continue
                target_text = row[col_index].strip() if col_index < len(row) else ""
                if not target_text:
                    jobs.append((row_index, col_index, source_text, target_code))
        self.run_translation_jobs(jobs, copy_overwrite=False)

    def _fill_copy_columns(self, rows, overwrite=False, row_indexes=None):
        """填充复制列：original<-english, chinese<-chinesesimp。

        overwrite=True 时覆盖已有内容（用于"翻译全表"），
        overwrite=False 时仅填充空白单元格（用于"翻译空白单元格"）。
        row_indexes 指定只处理的行（用于选中单元格/行/列翻译），None 表示全部行。
        """
        changed = False
        target_rows = range(len(rows)) if row_indexes is None else sorted(row_indexes)
        # 批量写入时屏蔽 itemChanged，避免每个单元格都推一条历史快照
        # （否则翻译前的状态会被挤出撤销栈，且 undo 需要按 N 次）。
        self.table.blockSignals(True)
        try:
            for col_index, header in enumerate(self.headers):
                source_header = copy_source_for_header(header)
                if not source_header:
                    continue
                try:
                    source_col = self.headers.index(source_header)
                except ValueError:
                    continue
                for row_index in target_rows:
                    if row_index < 0 or row_index >= len(rows):
                        continue
                    row = rows[row_index]
                    source_text = row[source_col].strip() if source_col < len(row) else ""
                    if not source_text:
                        continue
                    existing = row[col_index].strip() if col_index < len(row) else ""
                    if existing and not overwrite:
                        continue
                    if existing == source_text and overwrite:
                        continue
                    self.set_cell_text(row_index, col_index, source_text)
                    changed = True
        finally:
            self.table.blockSignals(False)
        if changed:
            self._record_history()
            self.set_dirty(True)

    def selected_rows_and_columns(self):
        rows = set()
        columns = set()
        for item in self.table.selectedItems():
            rows.add(item.row())
            columns.add(item.column())
        for selected_range in self.table.selectedRanges():
            for row_index in range(selected_range.topRow(), selected_range.bottomRow() + 1):
                rows.add(row_index)
            for column_index in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
                columns.add(column_index)
        return rows, columns

    def selected_columns(self):
        columns = set()
        for selected_range in self.table.selectedRanges():
            for column_index in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
                columns.add(column_index)
        return columns

    def run_translation_jobs(self, jobs, copy_overwrite=True):
        jobs = self._sort_jobs_by_row_column(jobs)
        self.start_translation_worker(jobs, copy_overwrite=copy_overwrite)

    def _sort_jobs_by_row_column(self, jobs):
        """按 (行, 列) 排序翻译任务，使相邻单元格聚拢，便于批次切分与进度展示。"""
        if not jobs:
            return jobs
        return sorted(jobs, key=lambda j: (j[0], j[1]))

    def start_translation_worker(self, raw_jobs, run_immediately=False, copy_overwrite=True):
        jobs = [
            TranslationJob(row, column, text, source_language_code_for_header(self.source_header), target)
            for row, column, text, target in raw_jobs
        ]
        # 记录本次任务涉及的行与复制列覆盖策略，翻译完成后据此回填 original/chinese 复制列
        self._translation_job_rows = {row for row, column, text, target in raw_jobs}
        self._translation_copy_overwrite = copy_overwrite
        if not jobs:
            QMessageBox.information(self, self.tr("translate"), self.tr("no_translatable_cells"))
            return

        # 防止翻译进行中重复启动新任务：先取消并等待旧线程结束，避免 QThread 被覆盖导致泄漏。
        if self._is_translation_running():
            QMessageBox.warning(self, self.tr("translate"), self.tr("translation_in_progress"))
            return

        self.show_translation_progress(len(jobs))

        self.translation_worker = self.create_translation_worker(jobs)
        self.translation_worker.progress.connect(self.update_translation_progress)
        self.translation_worker.finished.connect(self.finish_translation)
        self.translation_worker.failed.connect(self.fail_translation)

        if run_immediately:
            self.translation_worker.run()
            return

        self.translation_thread = QThread(self)
        self.translation_worker.moveToThread(self.translation_thread)
        self.translation_thread.started.connect(self.translation_worker.run)
        self.translation_worker.finished.connect(self.translation_thread.quit)
        self.translation_worker.failed.connect(self.translation_thread.quit)
        # 线程结束后释放 worker 和 thread，避免内存泄漏与重复回调。
        self.translation_thread.finished.connect(self.translation_worker.deleteLater)
        self.translation_thread.finished.connect(self.translation_thread.deleteLater)
        # 线程结束后清空引用：C++ 对象被 deleteLater 销毁后，旧引用调用
        # isRunning() 会抛 RuntimeError，导致第二次翻译静默无反应。
        self.translation_thread.finished.connect(self._clear_translation_thread)
        self.translation_thread.start()

    def _clear_translation_thread(self):
        # 线程已结束，缓存不会再被写；这里再存一次，兼顾窗口关闭等 finish/fail 未走到的路径。
        self.translation_cache_store.save(self.translation_cache)
        self.translation_worker = None
        self.translation_thread = None

    def _is_translation_running(self):
        return self.translation_thread is not None and self.translation_thread.isRunning()

    def _ensure_translation_stopped(self):
        """取消正在进行的翻译并阻塞等待线程真正结束，防止 QThread 在运行时被析构导致崩溃。"""
        if self.translation_worker is not None:
            self.translation_worker.cancel()
        thread = self.translation_thread
        if thread is not None and thread.isRunning():
            # quit() 让事件循环退出；翻译内部应在批次间检查 should_cancel 并尽快返回。
            thread.quit()
            thread.wait(3000)
        self.translation_worker = None
        self.translation_thread = None

    def create_translation_worker(self, jobs):
        return TranslationWorker(
            # 注入共享缓存：多次翻译运行复用相同内容的翻译结果
            service=TranslationService(cache=self.translation_cache),
            jobs=jobs,
            config=TranslatorConfig(
                provider=self.translation_provider,
                char_budget=self.translation_char_budget,
                auto_concurrency=self.translation_auto_concurrency,
                parallel_batches=self.translation_parallel_batches,
                timeout=self.translation_timeout,
                api_key=self.translation_api_key,
                region=self.translation_region,
                model=self.translation_model,
                base_url=self.translation_base_url,
                email=self.translation_email,
                glossary=self.wordbook_glossary(),
            ),
        )

    def wordbook_glossary(self):
        if self.wordbook_window is None:
            return []
        glossary = []
        for row in self.wordbook_window.glossary_rows():
            item = {}
            for column_index, value in enumerate(row):
                value = (value or "").strip()
                if value:
                    item[WORDBOOK_HEADERS[column_index]] = value
            if len(item) >= 2:
                glossary.append(item)
        return glossary

    def update_translation_progress(self, results):
        # 哪批翻译完就写入哪批，跳过已写入的单元格避免重复操作
        wrote = False
        for (row, column), text in results.cell_results.items():
            cell_key = (row, column)
            if cell_key in self._translation_written_cells:
                continue
            if not wrote:
                # 批量写入时屏蔽 itemChanged，避免每个单元格都推一条历史快照
                # （否则翻译前的状态会被挤出撤销栈，且 undo 需要按 N 次）。
                self.table.blockSignals(True)
                wrote = True
            self.set_cell_text(row, column, text)
            self._translation_written_cells.add(cell_key)
        if wrote:
            self.table.blockSignals(False)
            self._record_history()
            self.set_dirty(True)
        completed = results.translated + results.failed + results.skipped
        total = self.translation_progress_bar.maximum()
        self.translation_progress_bar.setValue(min(completed, total))
        label_text = f"{min(completed, total)}/{total}"
        if results.failed > 0:
            label_text += f" ({self.tr('failed_count', count=results.failed)})"
        self.translation_progress_label.setText(label_text)
        self.statusBar().showMessage(
            self.tr("translation_progress", translated=results.translated, failed=results.failed, cache_hits=results.cache_hits),
            1000,
        )

    def finish_translation(self, results):
        wrote = False
        for (row, column), text in results.cell_results.items():
            cell_key = (row, column)
            if cell_key in self._translation_written_cells:
                continue
            if not wrote:
                self.table.blockSignals(True)
                wrote = True
            self.set_cell_text(row, column, text)
            self._translation_written_cells.add(cell_key)
        if wrote:
            self.table.blockSignals(False)
            self._record_history()
            self.set_dirty(True)
        # 按翻译后的最终状态回填复制列：源语言为 chinesesimp 时 english 本身是翻译目标，
        # 只有翻译写入完成后才能复制到 original（chinese<-chinesesimp 同理兜底）。
        if self._translation_job_rows:
            self._fill_copy_columns(
                self.table_rows(),
                overwrite=self._translation_copy_overwrite,
                row_indexes=self._translation_job_rows,
            )
        if results.cancelled:
            current_value = self.translation_progress_bar.value()
            self.translation_progress_label.setText(f"{current_value}/{self.translation_progress_bar.maximum()}")
            self.statusBar().showMessage(self.tr("translation_cancelled"), 5000)
        else:
            total = self.translation_progress_bar.maximum()
            self.translation_progress_bar.setValue(total)
            label_text = f"{total}/{total}"
            if results.failed > 0:
                label_text += f" ({self.tr('failed_count', count=results.failed)})"
            self.translation_progress_label.setText(label_text)
            self.statusBar().showMessage(
                self.tr("translation_progress", translated=results.translated, failed=results.failed, cache_hits=results.cache_hits),
                5000,
            )
        self.hide_translation_progress()
        self.translation_cancel_button.setEnabled(True)
        # 取消也要存：已翻好的部分不该白花。
        self.translation_cache_store.save(self.translation_cache)
        if not results.cancelled and results.failed and results.errors and results.translated == 0:
            QMessageBox.warning(self, self.tr("translate_failed"), "\n".join(results.errors[:3]))

    def fail_translation(self, message):
        self.hide_translation_progress()
        self.translation_cancel_button.setEnabled(True)
        self.translation_cache_store.save(self.translation_cache)
        QMessageBox.critical(self, self.tr("translate_failed"), message)

    def cancel_translation(self):
        if self.translation_worker:
            self.translation_worker.cancel()
        self.statusBar().showMessage(self.tr("cancelling_translation"), 3000)
        self.translation_cancel_button.setEnabled(False)

    def confirm_unsaved_close(self):
        if not self.is_dirty:
            return True
        path = str(self.current_path) if self.current_path else "stringtable.csv"
        result = QMessageBox.warning(
            self,
            self.tr("unsaved_changes"),
            self.tr("save_changes_before_close", path=path),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Save:
            return self.save_file()
        return result == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        # 翻译进行中关闭窗口会让 QThread 在运行状态下被析构，触发段错误。
        # 先询问用户是否取消翻译后关闭。
        if self._is_translation_running():
            result = QMessageBox.warning(
                self,
                self.tr("translate"),
                self.tr("translation_running_close"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if result != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._ensure_translation_stopped()
        if self.isVisible() and not self.confirm_unsaved_close():
            event.ignore()
            return
        if self.wordbook_window and self.wordbook_window.isVisible() and not self.wordbook_window.confirm_unsaved_close():
            event.ignore()
            return
        super().closeEvent(event)

    def set_cell_text(self, row_index, column_index, text):
        item = self.table.item(row_index, column_index)
        if item is None:
            item = QTableWidgetItem("")
            self.table.setItem(row_index, column_index, item)
        item.setText(text)

    def open_search_dialog(self):
        if self.search_dialog is None:
            self.search_dialog = SearchDialog(self)
        self.search_dialog.show_and_focus()

    def find_matches(self, query, whole_word=False, match_case=False):
        query = (query or "").strip()
        if not query:
            return []
        flags = 0 if match_case else re.IGNORECASE
        if whole_word:
            pattern = re.compile(r"\b" + re.escape(query) + r"\b", flags)
        else:
            pattern = re.compile(re.escape(query), flags)
        column_count = self.table.columnCount()
        matches = []
        # 直接遍历底层数据而非 table.item()，避免大量 QTableWidgetItem 访问开销
        for row_index, row in enumerate(self.table_rows()):
            for column_index in range(column_count):
                cell_text = row[column_index] if column_index < len(row) else ""
                if cell_text and pattern.search(cell_text):
                    matches.append((row_index, column_index))
        return matches

    def focus_match(self, row_index, column_index):
        self.table.setCurrentCell(row_index, column_index)
        self.table.scrollToItem(self.table.item(row_index, column_index))

    def clear_search_highlight(self):
        for row_index in range(self.table.rowCount()):
            for column_index in range(self.table.columnCount()):
                item = self.table.item(row_index, column_index)
                if item:
                    item.setBackground(QColor())


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("DayZTranslateTool")
    app.setApplicationName("DayZTranslateTool")
    window = DayzTranslateTool()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
