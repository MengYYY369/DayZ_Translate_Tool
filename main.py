import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QThread, Qt, QItemSelectionModel
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
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
    language_code_for_header,
    load_dayz_csv,
    source_language_code_for_header,
    write_dayz_csv,
)
from translation_worker import TranslationWorker
from translator_service import TranslationJob, TranslationService, TranslatorConfig, normalize_provider
from wordbook_csv import WORDBOOK_HEADERS, load_wordbook_csv, wordbook_rows_for_save, write_wordbook_csv


DEFAULT_CSV_PATH = Path(__file__).with_name("stringtable.csv")
DEFAULT_WORDBOOK_PATH = Path(__file__).with_name("wordbook.csv")
LANGUAGE_COLUMN_WIDTH = 150
DEFAULT_COLUMN_WIDTH = 90
SEARCH_MATCH_COLOR = QColor("#9adbe8")
SEARCH_ACTIVE_COLOR = QColor("#ffc857")
PROVIDER_LABELS = {
    "google": "Google",
    "mymemory": "MyMemory",
    "deepl": "DeepL",
    "microsoft": "Microsoft",
    "openai": "OpenAI",
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
        "translation_engine": "Translation Engine",
        "preset": "Preset",
        "batch_size": "Batch Size",
        "parallel_batches": "Parallel Batches",
        "language": "Language",
        "api_key": "API Key",
        "region": "Region",
        "model": "Model",
        "base_url": "Base URL",
        "email": "Email",
        "next": "Next",
        "matches": "{count} matches",
        "copy": "Copy",
        "paste": "Paste",
        "cut": "Cut",
        "delete_cell": "Delete Cell",
        "delete_selected_cells": "Delete Selected Cells",
        "delete_row": "Delete Row",
        "delete_column": "Delete Column",
        "translate_selected_cells": "Translate Selected Cells",
        "translate_selected_rows": "Translate Selected Rows",
        "translate_selected_columns": "Translate Selected Columns",
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
        "translation_engine": "翻译引擎",
        "preset": "预设",
        "batch_size": "批量大小",
        "parallel_batches": "并行批次数",
        "language": "语言",
        "api_key": "API Key",
        "region": "区域",
        "model": "模型",
        "base_url": "Base URL",
        "email": "Email",
        "next": "下一个",
        "matches": "{count} 个匹配",
        "copy": "复制",
        "paste": "粘贴",
        "cut": "剪切",
        "delete_cell": "删除单元格",
        "delete_selected_cells": "删除选中单元格",
        "delete_row": "删除行",
        "delete_column": "删除列",
        "translate_selected_cells": "翻译选中单元格",
        "translate_selected_rows": "翻译选中行",
        "translate_selected_columns": "翻译选中列",
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
}
PROVIDER_DEFAULTS = {
    "google": {},
    "mymemory": {"email": ""},
    "deepl": {"api_key": ""},
    "microsoft": {"api_key": "", "region": ""},
    "openai": {"api_key": "", "model": "gpt-3.5-turbo", "base_url": ""},
}


class SearchDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle(window.tr("search"))
        self.setModal(False)
        self.matches = []
        self.current_match = -1

        self.search_input = QLineEdit(self)
        self.search_input.textChanged.connect(self.refresh_matches)
        self.count_label = QLabel(window.tr("matches", count=0), self)

        self.next_button = QPushButton(window.tr("next"), self)
        self.next_button.setMaximumWidth(96)
        self.next_button.clicked.connect(self.next_match)

        self.previous_button = QPushButton("↑", self)
        self.previous_button.setFixedSize(32, 32)
        self.previous_button.clicked.connect(self.previous_match)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.next_button)
        button_layout.addWidget(self.previous_button)
        button_layout.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search_input)
        layout.addWidget(self.count_label)
        layout.addLayout(button_layout)
        self.resize(360, 120)

    def show_and_focus(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.search_input.setFocus()
        self.search_input.selectAll()

    def refresh_matches(self):
        self.window.clear_search_highlight()
        self.matches = self.window.find_matches(self.search_input.text())
        for row_index, column_index in self.matches:
            item = self.window.table.item(row_index, column_index)
            if item:
                item.setBackground(SEARCH_MATCH_COLOR)
        self.current_match = -1
        self.count_label.setText(self.window.tr("matches", count=len(self.matches)))
        if self.matches:
            self.next_match()

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
        self.window.clear_search_highlight()
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
        self.delete_preset_button = QPushButton("Delete", self)
        self.delete_preset_button.clicked.connect(self.delete_preset)

        self.batch_size_input = QSpinBox(self)
        self.batch_size_input.setRange(1, 200)
        self.batch_size_input.setValue(window.translation_batch_size)

        self.parallel_batches_input = QSpinBox(self)
        self.parallel_batches_input.setRange(1, 5)
        self.parallel_batches_input.setValue(window.translation_parallel_batches)

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
        self.add_form_row(form, "batch_size", window.tr("batch_size"), self.batch_size_input)
        self.add_form_row(form, "parallel_batches", window.tr("parallel_batches"), self.parallel_batches_input)
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
        cancel_button = QPushButton(window.tr("cancel"), self)
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
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

    def add_form_row(self, form, key, label_text, widget):
        label = QLabel(label_text, self)
        form.addRow(label, widget)
        self.form_rows[key] = (label, widget)

    def update_visible_fields(self):
        provider_label = self.provider_combo.currentText()
        provider = next(key for key, label in PROVIDER_LABELS.items() if label == provider_label)
        visible_fields = PROVIDER_FIELD_KEYS.get(provider, set())
        preset_visible = provider == "openai"
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
        self.batch_size_input.valueChanged.connect(self._on_field_changed)
        self.parallel_batches_input.valueChanged.connect(self._on_field_changed)
        self.api_key_input.textChanged.connect(self._on_field_changed)
        self.region_input.textChanged.connect(self._on_field_changed)
        self.model_input.textChanged.connect(self._on_field_changed)
        self.base_url_input.textChanged.connect(self._on_field_changed)
        self.email_input.textChanged.connect(self._on_field_changed)

    def _on_provider_changed(self, label):
        if self._loading_preset:
            return
        old_provider = self._current_dialog_provider
        self._save_dialog_fields_for_provider(old_provider)
        new_provider = next(key for key, lbl in PROVIDER_LABELS.items() if lbl == label)
        self._block_field_signals(True)
        for key in PROVIDER_FIELD_KEYS.get(new_provider, set()):
            value = self.window.get_provider_setting(new_provider, key, "")
            self._set_field_value(key, value)
        self._block_field_signals(False)
        self._current_dialog_provider = new_provider
        self.update_visible_fields()
        self.apply_settings(close_dialog=False)
        self.refresh_preset_dirty_indicator()

    def _save_dialog_fields_for_provider(self, provider):
        for key in PROVIDER_FIELD_KEYS.get(provider, set()):
            self.window.set_provider_setting(provider, key, self._get_field_value(key))

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
        self.apply_settings(close_dialog=False)
        self.refresh_preset_dirty_indicator()

    def apply_settings(self, close_dialog=True):
        provider_label = self.provider_combo.currentText()
        provider = next(key for key, label in PROVIDER_LABELS.items() if label == provider_label)
        self.window.translation_provider = provider
        self.window.translation_batch_size = self.batch_size_input.value()
        self.window.translation_parallel_batches = self.parallel_batches_input.value()
        for key in PROVIDER_FIELD_KEYS.get(provider, set()):
            self.window.set_provider_setting(provider, key, self._get_field_value(key))
        self.window.save_translation_settings()
        if close_dialog:
            self.accept()

    def refresh_presets(self):
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(self.window.translation_preset_names())
        self.preset_combo.blockSignals(False)

    def save_preset(self):
        self.apply_settings(close_dialog=False)
        self.window.save_translation_preset(self.preset_name_input.text())
        self.refresh_presets()
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
        self.window.load_translation_preset(name)
        self.provider_combo.setCurrentText(PROVIDER_LABELS.get(self.window.translation_provider, "Google"))
        self.batch_size_input.setValue(self.window.translation_batch_size)
        self.parallel_batches_input.setValue(self.window.translation_parallel_batches)
        self.api_key_input.setText(self.window.translation_api_key)
        self.region_input.setText(self.window.translation_region)
        self.model_input.setText(self.window.translation_model)
        self.base_url_input.setText(self.window.translation_base_url)
        self.email_input.setText(self.window.translation_email)
        self._loading_preset = False
        self._current_dialog_provider = self.window.translation_provider
        self.update_visible_fields()
        self._loaded_preset_values = self.current_field_values()
        self.refresh_preset_dirty_indicator()

    def current_field_values(self):
        return {
            "provider": self.window.translation_provider,
            "batch_size": self.batch_size_input.value(),
            "parallel_batches": self.parallel_batches_input.value(),
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
        self.table = QTableWidget(self)
        self.table.setColumnCount(len(WORDBOOK_HEADERS))
        self.table.setHorizontalHeaderLabels(WORDBOOK_HEADERS)
        self.table.itemChanged.connect(self.handle_item_changed)
        self.setCentralWidget(self.table)
        self.resize(1500, 620)
        self.setWindowTitle(parent.tr("wordbook"))
        self.create_menus()
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
        self.ensure_trailing_empty_row()
        self.set_dirty(True)
        self.auto_save()

    def auto_save(self):
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
        self.translation_batch_size = int(self.settings.value("translation_batch_size", 30))
        self.translation_parallel_batches = int(self.settings.value("translation_parallel_batches", 1))
        self.provider_settings = self._load_provider_settings()
        self.ui_language = self.settings.value("ui_language", "en")
        self.table = QTableWidget(self)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.itemChanged.connect(self.handle_item_changed)
        self.table.customContextMenuRequested.connect(self.open_context_menu)
        self.table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.open_column_header_context_menu)
        self.table.verticalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.verticalHeader().customContextMenuRequested.connect(self.open_row_header_context_menu)
        self.setCentralWidget(self.table)
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
        self.create_menus()
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

    def apply_ui_language(self):
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
        self.settings.setValue("translation_batch_size", self.translation_batch_size)
        self.settings.setValue("translation_parallel_batches", self.translation_parallel_batches)
        self._save_provider_settings()
        self.statusBar().showMessage(
            self.tr("translation_engine_status", engine=PROVIDER_LABELS.get(self.translation_provider, self.translation_provider)),
            5000,
        )

    def current_translation_settings_dict(self):
        return {
            "provider": self.translation_provider,
            "batch_size": self.translation_batch_size,
            "parallel_batches": self.translation_parallel_batches,
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
        batch_size = values.get("batch_size")
        if batch_size is not None and batch_size != "":
            self.translation_batch_size = int(batch_size)
        parallel_batches = values.get("parallel_batches")
        if parallel_batches is not None and parallel_batches != "":
            self.translation_parallel_batches = int(parallel_batches)
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
        self.settings.beginGroup(f"translation_presets/{name}")
        for key, value in self.current_translation_settings_dict().items():
            self.settings.setValue(key, value)
        self.settings.endGroup()
        names = self.translation_preset_names()
        if name not in names:
            names.append(name)
        self.settings.setValue("translation_preset_names_list", names)
        self.settings.sync()

    def load_translation_preset(self, name):
        name = (name or "").strip()
        if not name:
            return
        preset_keys = ["provider", "batch_size", "parallel_batches", "api_key", "region", "model", "base_url", "email"]
        self.settings.beginGroup(f"translation_presets/{name}")
        # Always include keys so apply overwrites previous provider fields.
        values = {key: self.settings.value(key, "") for key in preset_keys}
        self.settings.endGroup()
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
        row = self.table.rowAt(position.y())
        column = self.table.columnAt(position.x())
        if row >= 0 and column >= 0:
            item = self.table.item(row, column)
            if item is None:
                item = QTableWidgetItem("")
                self.table.setItem(row, column, item)
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
            actions.append("delete_row")
        elif context == "column_header" and column >= 0:
            actions.append("delete_column")
        elif context == "cell" and row >= 0 and column >= 0:
            actions.append("delete_cell")
            if self.has_multi_cell_selection():
                actions.append("delete_selected_cells")
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
        return bool(language_code_for_header(self.headers[column]))

    def copy_selection(self):
        text = self.selection_as_text()
        if text:
            QApplication.clipboard().setText(text)

    def cut_selection(self):
        self.copy_selection()
        for item in self.table.selectedItems():
            item.setText("")

    def delete_cell_text(self):
        row = self.table.currentRow()
        column = self.table.currentColumn()
        if row < 0 or column < 0:
            return
        self.set_cell_text(row, column, "")

    def delete_selected_cells(self):
        ranges = self.table.selectedRanges()
        if not ranges:
            return
        for selected_range in ranges:
            for row_index in range(selected_range.topRow(), selected_range.bottomRow() + 1):
                for column_index in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
                    self.set_cell_text(row_index, column_index, "")

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
        self.set_dirty(True)

    def delete_column_cells(self):
        column = self.table.currentColumn()
        if column < 0:
            columns = self.selected_columns()
            if not columns:
                return
            column = min(columns)
        if column < 0 or column >= self.table.columnCount():
            return
        for row_index in range(self.table.rowCount()):
            self.set_cell_text(row_index, column, "")

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

        for row_offset, line in enumerate(lines):
            values = line.split("\t")
            for column_offset, value in enumerate(values):
                row_index = start_row + row_offset
                column_index = start_column + column_offset
                if column_index >= self.table.columnCount():
                    continue
                self.set_cell_text(row_index, column_index, value)

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
        if item is None:
            item = QTableWidgetItem("")
            self.table.setItem(row, column, item)
        return [item]

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
        self.run_translation_jobs(jobs)

    def translate_all_cells(self):
        try:
            source_column = self.headers.index(self.source_header)
        except ValueError:
            QMessageBox.warning(self, self.tr("translate_cells"), self.tr("source_column_missing", header=self.source_header))
            return
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
        self.run_translation_jobs(jobs)

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

    def run_translation_jobs(self, jobs):
        self.start_translation_worker(jobs)

    def start_translation_worker(self, raw_jobs, run_immediately=False):
        jobs = [
            TranslationJob(row, column, text, source_language_code_for_header(self.source_header), target)
            for row, column, text, target in raw_jobs
        ]
        if not jobs:
            QMessageBox.information(self, self.tr("translate"), self.tr("no_translatable_cells"))
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
        self.translation_thread.start()

    def create_translation_worker(self, jobs):
        return TranslationWorker(
            service=TranslationService(batch_size=self.translation_batch_size),
            jobs=jobs,
            config=TranslatorConfig(
                provider=self.translation_provider,
                batch_size=self.translation_batch_size,
                parallel_batches=self.translation_parallel_batches,
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
        for (row, column), text in results.cell_results.items():
            self.set_cell_text(row, column, text)
        completed = results.translated + results.failed + results.skipped
        total = self.translation_progress_bar.maximum()
        self.translation_progress_bar.setValue(min(completed, total))
        self.translation_progress_label.setText(f"{min(completed, total)}/{total}")
        self.statusBar().showMessage(
            self.tr("translation_progress", translated=results.translated, failed=results.failed, cache_hits=results.cache_hits),
            1000,
        )

    def finish_translation(self, results):
        for (row, column), text in results.cell_results.items():
            self.set_cell_text(row, column, text)
        total = self.translation_progress_bar.maximum()
        self.translation_progress_bar.setValue(total)
        self.translation_progress_label.setText(f"{total}/{total}")
        self.statusBar().showMessage(
            self.tr("translation_progress", translated=results.translated, failed=results.failed, cache_hits=results.cache_hits),
            5000,
        )
        self.hide_translation_progress()
        if results.failed and results.errors and results.translated == 0:
            QMessageBox.warning(self, self.tr("translate_failed"), "\n".join(results.errors[:3]))

    def fail_translation(self, message):
        self.hide_translation_progress()
        QMessageBox.critical(self, self.tr("translate_failed"), message)

    def cancel_translation(self):
        if self.translation_worker:
            self.translation_worker.cancel()
        self.statusBar().showMessage(self.tr("cancelling_translation"), 3000)

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

    def find_matches(self, query):
        query = (query or "").strip().lower()
        if not query:
            return []
        matches = []
        for row_index in range(self.table.rowCount()):
            for column_index in range(self.table.columnCount()):
                item = self.table.item(row_index, column_index)
                if item and query in item.text().lower():
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
    window = DayzTranslateTool()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
