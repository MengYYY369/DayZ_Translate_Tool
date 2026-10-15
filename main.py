import re
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QLibraryInfo, QObject, QSettings, QSize, QThread, Qt, QItemSelectionModel, QTimer, QTranslator, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QStyledItemDelegate,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
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
    QScrollArea,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from config_cpp import collect_config_cpp_files, extract_keys_from_paths, merge_language_keys
from dayz_csv import (
    DAYZ_HEADERS,
    is_copy_only_column,
    language_code_for_header,
    load_dayz_csv,
    source_language_code_for_header,
    write_dayz_csv,
)
from translation_cache import TranslationCacheStore
import translation_flow
from translation_worker import TranslationWorker
from quality_check import RULE_GROUPS, QualityCheckConfig, all_rules, target_columns
from quality_check_worker import QualityCheckWorker
from translator_service import DEFAULT_CHAR_BUDGET, MAX_AUTO_CONCURRENCY, MAX_CHAR_BUDGET, MIN_CHAR_BUDGET, RetryPolicy, TranslationJob, TranslationService, validate_translator_config
from free_translators import FREE_SOURCE_SPECS
from translation_sources import (
    ALL_RULES,
    RULE_ALL,
    RULE_EMPTY,
    RULE_SELECTION,
    SourceEntry,
    SourceList,
)
from wordbook_csv import WORDBOOK_HEADERS, load_wordbook_csv, wordbook_rows_for_save, write_wordbook_csv
from table_history import TableHistory, snapshot_table, restore_table
from word_split import split_stuck_words


APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
DEFAULT_CSV_PATH = APP_DIR / "stringtable.csv"
# 单词本放在用户配置文件夹，避免打包后写入应用目录失败
CONFIG_DIR = translation_flow.config_dir() or APP_DIR
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_WORDBOOK_PATH = CONFIG_DIR / "wordbook.csv"
LANGUAGE_COLUMN_WIDTH = 150
DEFAULT_COLUMN_WIDTH = 90
SEARCH_MATCH_COLOR = QColor("#9adbe8")
SEARCH_ACTIVE_COLOR = QColor("#ffc857")
# 质检标记色：自动查出来的和右键手动标的都用这一种（用户决定不区分）
QC_PROBLEM_COLOR = QColor("#ffb3b3")
TABLE_GRIDLINE_COLOR = "#8c8c8c"
AI_TYPE_KEYS = translation_flow.AI_TYPE_KEYS
AI_TYPE_LABEL_KEYS = {
    "openai": "ai_type_openai",
    "claude": "ai_type_claude",
    "codex": "ai_type_codex",
}
# 测试按钮是「探活」：失败要立刻看到原因，不套用正式翻译那套 5 次重试的长退避
TEST_RETRY_POLICY = RetryPolicy(max_attempts=2, base_delay=1.0, max_delay=2.0)
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
        "close": "Close",
        "ok": "OK",
        "test_translation": "Test",
        "test_translation_success": "Test succeeded. Translations:\n{result}",
        "test_translation_partial": "Test finished, but some languages failed:\n{result}",
        "test_translation_no_result": "No translation came back from this source.",
        "test_translation_failed": "Test failed: {error}",
        "test_translation_running": "Testing... (click another source to switch)",
        "translation_engine": "Translation Engine",
        "delete": "Delete",
        "translation_sources": "Translation sources",
        "source_rules_all": "All cells",
        "source_rules_empty": "Empty cells",
        "source_rules_selection": "Right-click",
        "source_rules_none": "None",
        "source_kind_free": "Free",
        "source_kind_ai": "AI",
        "source_name": "Name",
        "source_type": "Interface",
        "source_builtin_text": "Concurrency {concurrency}, interval {interval}s (built in)",
        "source_concurrency": "Concurrency",
        "source_interval": "Interval (s)",
        "source_move_up": "Move up",
        "source_move_down": "Move down",
        "source_remove": "Remove source",
        "source_test": "Test this source",
        "source_edit": "Edit source",
        "edit_ai_source": "Edit AI source",
        "add_ai_source": "Add AI source",
        "source_name_required": "Please enter a name for this source.",
        "source_name_duplicate": "A source named \"{name}\" already exists. Add another one anyway?",
        "source_remove_confirm": "Remove \"{name}\"?",
        "no_source_for_action": "No translation source is enabled for \"{action}\". Enable at least one source in Settings.",
        "translation_fallback": "{previous} is unavailable — switched to {current}",
        "no_source_selected": "No source enabled",
        "action_all_cells": "translate all cells",
        "action_empty_cells": "translate empty cells",
        "action_selection": "translate selection",
        "ai_type_openai": "OpenAI compatible",
        "ai_type_claude": "Claude",
        "ai_type_codex": "Codex",
        "source_google": "Google",
        "source_microsoft": "Microsoft (free)",
        "source_tencent": "Tencent Interactive",
        "source_volcano": "Volcano",
        "source_lara": "Lara",
        "source_mymemory": "MyMemory",
        "source_deepl": "DeepL",
        "char_budget": "Max chars per batch",
        "char_budget_tooltip": "Source characters a single request may carry. Rows are never split across requests. Larger = fewer requests but a bigger loss if one fails.",
        "translation_cache": "Translation cache",
        "clear_translation_cache": "Clear cache",
        "retry_countdown": "Rate limited — retrying in {seconds}s (attempt {attempt}/{max_attempts})",
        "retry_failed_only": "Retry failed only",
        "failed_cells_count": "{count} cells failed.",
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
        "split_stuck_words": "Split Stuck Words",
        "split_stuck_words_done": "Split {count} cells.",
        "split_stuck_words_none": "No stuck words to split in the selected cells.",
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
        "check_errors": "Check for Errors",
        "translate_error_cells": "Translate Error Cells",
        "quality_check_settings": "Check Settings...",
        "quality_only": "Problems only",
        "mark_error": "Mark as error",
        "unmark_error": "Clear error mark",
        "mark_row_error": "Mark whole row as error",
        "unmark_row_error": "Clear error marks on this row",
        "quality_check_progress": "Checking... {done}/{total}",
        "quality_check_done": "Checked {cells} cells, found {count} problems.",
        "quality_check_clean": "Checked {cells} cells, no problems found.",
        "quality_check_cancelled": "Check cancelled",
        "quality_check_running": "A check is already running. Cancel it or wait for it to finish.",
        "quality_check_failed": "Check failed",
        "quality_check_no_csv": "Open a DayZ stringtable.csv before checking.",
        "quality_check_no_cells": "No error cells to translate.",
        "cancelling_check": "Cancelling check...",
        "similarity_threshold": "Similarity threshold",
        "qc_select_all": "All",
        "qc_select_none": "None",
        "qc_restore_defaults": "Restore defaults",
        "qc_group_format": "Format",
        "qc_group_language": "Language",
        "qc_group_similarity": "Similarity and consistency",
        "qc_group_model": "Model output",
        "qc_group_glossary": "Wordbook",
        "quality_rule_placeholder_missing": "Placeholder missing or changed",
        "quality_rule_placeholder_extra": "Extra placeholder",
        "quality_rule_placeholder_order": "Placeholder order changed",
        "quality_rule_line_breaks": "Line break or tab mismatch",
        "quality_rule_rich_tags": "Rich text tag lost",
        "quality_rule_color_markup": "Color markup lost",
        "quality_rule_numbers": "Numbers do not match",
        "quality_rule_brackets": "Brackets or quotes unpaired",
        "quality_rule_spaces": "Space at the edge or doubled",
        "quality_rule_invisible_chars": "Invisible characters",
        "quality_rule_csv_unsafe": "Would break the CSV",
        "quality_rule_empty_translation": "Empty translation",
        "quality_rule_script_missing": "Missing expected writing system",
        "quality_rule_script_unexpected": "Unexpected writing system",
        "quality_rule_copied_source": "Copied the source text",
        "quality_rule_punctuation": "Punctuation not localized",
        "quality_rule_fullwidth": "Full-width and half-width mixed",
        "quality_rule_row_similarity": "Too similar to another language in the same row",
        "quality_rule_column_duplicate": "Two columns are almost the same",
        "quality_rule_inconsistent_target": "Same source, different translation",
        "quality_rule_duplicate_target": "Same translation for different sources",
        "quality_rule_prompt_leak": "Model talk or prompt residue",
        "quality_rule_length_ratio": "Length looks wrong",
        "quality_rule_untranslated_sentence": "Whole sentence still in the source language",
        "quality_rule_garbage": "Garbled text or links",
        "quality_rule_parenthetical_notes": "Added a note in brackets",
        "quality_rule_glossary_missing": "Wordbook term missing",
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
        "close": "关闭",
        "ok": "确定",
        "test_translation": "测试",
        "test_translation_success": "测试成功。翻译结果：\n{result}",
        "test_translation_partial": "测试完成，但有语言没翻出来：\n{result}",
        "test_translation_no_result": "这个源没有返回任何译文。",
        "test_translation_failed": "测试失败：{error}",
        "test_translation_running": "正在测试…（点其它源可以切换）",
        "translation_engine": "翻译引擎",
        "delete": "删除",
        "translation_sources": "翻译源",
        "source_rules_all": "全表",
        "source_rules_empty": "空白",
        "source_rules_selection": "右键选中",
        "source_rules_none": "未启用",
        "source_kind_free": "免费",
        "source_kind_ai": "AI",
        "source_name": "名称",
        "source_type": "接口类型",
        "source_builtin_text": "并发 {concurrency}，间隔 {interval} 秒（内置，不可修改）",
        "source_concurrency": "并发数",
        "source_interval": "间隔（秒）",
        "source_move_up": "上移",
        "source_move_down": "下移",
        "source_remove": "删除源",
        "source_test": "测试这个源",
        "source_edit": "编辑这个源",
        "edit_ai_source": "编辑 AI 源",
        "add_ai_source": "添加 AI 源",
        "source_name_required": "请给这个翻译源起个名字。",
        "source_name_duplicate": "已经有一个叫「{name}」的翻译源了，还要继续添加吗？",
        "source_remove_confirm": "确定要删除「{name}」吗？",
        "no_source_for_action": "没有任何翻译源被勾选用于「{action}」。请到设置里至少勾选一个源。",
        "translation_fallback": "{previous} 连不上，已自动改用 {current}",
        "no_source_selected": "未启用任何源",
        "action_all_cells": "翻译全表",
        "action_empty_cells": "翻译空白单元格",
        "action_selection": "翻译选中的内容",
        "ai_type_openai": "OpenAI 兼容",
        "ai_type_claude": "Claude",
        "ai_type_codex": "Codex",
        "source_google": "Google",
        "source_microsoft": "微软翻译（免费）",
        "source_tencent": "腾讯交互翻译",
        "source_volcano": "火山翻译",
        "source_lara": "Lara 翻译",
        "source_mymemory": "MyMemory",
        "source_deepl": "DeepL",
        "char_budget": "每批最多字数",
        "char_budget_tooltip": "单次请求最多携带的源文字数。行不会被拆到两个请求里。越大请求越少，但单次失败的代价也越大。",
        "translation_cache": "翻译缓存",
        "clear_translation_cache": "清空缓存",
        "retry_countdown": "被限速，{seconds} 秒后重试（第 {attempt}/{max_attempts} 次）",
        "retry_failed_only": "只重跑失败项",
        "failed_cells_count": "有 {count} 个单元格翻译失败。",
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
        "split_stuck_words": "自动分词",
        "split_stuck_words_done": "已拆分 {count} 个单元格。",
        "split_stuck_words_none": "选中的单元格里没有需要拆分的词。",
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
        "check_errors": "检查错误",
        "translate_error_cells": "翻译错误文本",
        "quality_check_settings": "检查设置...",
        "quality_only": "只看问题格",
        "mark_error": "标记为错误",
        "unmark_error": "取消错误标记",
        "mark_row_error": "标记整行为错误",
        "unmark_row_error": "取消整行的错误标记",
        "quality_check_progress": "正在检查… {done}/{total}",
        "quality_check_done": "已检查 {cells} 个单元格，发现 {count} 处问题。",
        "quality_check_clean": "已检查 {cells} 个单元格，没有发现问题。",
        "quality_check_cancelled": "检查已取消",
        "quality_check_running": "检查正在进行中，请先取消或等待完成。",
        "quality_check_failed": "检查失败",
        "quality_check_no_csv": "请先打开 DayZ stringtable.csv。",
        "quality_check_no_cells": "没有被标记错误的单元格可以重译。",
        "cancelling_check": "正在取消检查...",
        "similarity_threshold": "相似率门槛",
        "qc_select_all": "全选",
        "qc_select_none": "全不选",
        "qc_restore_defaults": "恢复默认",
        "qc_group_format": "格式",
        "qc_group_language": "语言",
        "qc_group_similarity": "相似度与一致性",
        "qc_group_model": "模型输出",
        "qc_group_glossary": "术语表",
        "quality_rule_placeholder_missing": "占位符少了或变了",
        "quality_rule_placeholder_extra": "多出了占位符",
        "quality_rule_placeholder_order": "占位符顺序变了",
        "quality_rule_line_breaks": "换行或制表符对不上",
        "quality_rule_rich_tags": "富文本标签丢了",
        "quality_rule_color_markup": "颜色标记丢了",
        "quality_rule_numbers": "数字对不上",
        "quality_rule_brackets": "括号或引号不配对",
        "quality_rule_spaces": "首尾空格或连续空格",
        "quality_rule_invisible_chars": "有看不见的字符",
        "quality_rule_csv_unsafe": "会撑坏 CSV",
        "quality_rule_empty_translation": "译文是空的",
        "quality_rule_script_missing": "缺少应有的文字",
        "quality_rule_script_unexpected": "混进了别的文字",
        "quality_rule_copied_source": "照抄了原文",
        "quality_rule_punctuation": "标点没有本地化",
        "quality_rule_fullwidth": "全角半角混用",
        "quality_rule_row_similarity": "同一行不同语言太像",
        "quality_rule_column_duplicate": "两列内容几乎一样",
        "quality_rule_inconsistent_target": "同一句原文译得不一样",
        "quality_rule_duplicate_target": "同一句译文用在不同原文上",
        "quality_rule_prompt_leak": "模型废话或提示词残留",
        "quality_rule_length_ratio": "长度明显异常",
        "quality_rule_untranslated_sentence": "整句还是原文语言",
        "quality_rule_garbage": "乱码或链接残留",
        "quality_rule_parenthetical_notes": "括号里多了注释",
        "quality_rule_glossary_missing": "单词本里的词没出现",
    },
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

    def __init__(self, window: "DayzTranslateTool"):
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

        self.quality_only_checkbox = QCheckBox(window.tr("quality_only"), self)
        self.quality_only_checkbox.toggled.connect(self._schedule_refresh)

        self.next_button = QPushButton(window.tr("next"), self)
        self.next_button.setMaximumWidth(96)
        self.next_button.clicked.connect(self.next_match)

        self.previous_button = QPushButton("↑", self)
        self.previous_button.setFixedSize(32, 32)
        self.previous_button.clicked.connect(self.previous_match)

        options_layout = QHBoxLayout()
        options_layout.addWidget(self.match_whole_word_checkbox)
        options_layout.addWidget(self.match_case_checkbox)
        options_layout.addWidget(self.quality_only_checkbox)
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
        self.resize(400, 200)

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

    def refresh_later(self):
        """外部改了格子底色（标记/检查结果变化）时延后重刷，避免在信号回调里递归。"""
        self._schedule_refresh()

    def refresh_matches(self):
        self._clear_highlight()
        text = self.search_input.text()
        if self.quality_only_checkbox.isChecked():
            # 只看问题格：搜索框留空就列全部问题格，填了就在问题格里再按文字筛
            self.matches = sorted(self.window.quality_problem_cells())
            if text.strip():
                found = set(self.window.find_matches(
                    text,
                    whole_word=self.match_whole_word_checkbox.isChecked(),
                    match_case=self.match_case_checkbox.isChecked(),
                ))
                self.matches = [cell for cell in self.matches if cell in found]
        else:
            self.matches = self.window.find_matches(
                text,
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
            # 恢复该格本来的底色：问题格的错误标记色不能被搜索高亮清掉
            self.window.restore_cell_background(row_index, column_index)
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


class AiSourceDialog(QDialog):
    """「添加 / 编辑 AI 源」弹窗。"""

    def __init__(self, window, parent=None, entry=None):
        super().__init__(parent or window)
        self.window = window
        self.setWindowTitle(window.tr("edit_ai_source" if entry is not None else "add_ai_source"))
        self.name_input = QLineEdit(self)
        self.type_combo = QComboBox(self)
        for key in AI_TYPE_KEYS:
            self.type_combo.addItem(window.tr(AI_TYPE_LABEL_KEYS[key]), key)
        self.base_url_input = QLineEdit(self)
        self.api_key_input = QLineEdit(self)
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.model_input = QLineEdit(self)
        self.concurrency_input = QSpinBox(self)
        self.concurrency_input.setRange(1, MAX_AUTO_CONCURRENCY)
        self.interval_input = QDoubleSpinBox(self)
        self.interval_input.setRange(0.0, 60.0)
        self.interval_input.setSingleStep(0.1)

        if entry is not None:
            # 编辑已有源：把现在的值填进去
            self.name_input.setText(entry.name)
            type_index = self.type_combo.findData(entry.api_type)
            if type_index >= 0:
                self.type_combo.setCurrentIndex(type_index)
            self.base_url_input.setText(entry.base_url)
            self.api_key_input.setText(entry.api_key)
            self.model_input.setText(entry.model)
            self.concurrency_input.setValue(max(1, int(entry.concurrency or 1)))
            self.interval_input.setValue(float(entry.interval or 0.0))

        form = QFormLayout()
        form.addRow(QLabel(window.tr("source_name"), self), self.name_input)
        form.addRow(QLabel(window.tr("source_type"), self), self.type_combo)
        form.addRow(QLabel(window.tr("base_url"), self), self.base_url_input)
        form.addRow(QLabel(window.tr("api_key"), self), self.api_key_input)
        form.addRow(QLabel(window.tr("model"), self), self.model_input)
        form.addRow(QLabel(window.tr("source_concurrency"), self), self.concurrency_input)
        form.addRow(QLabel(window.tr("source_interval"), self), self.interval_input)

        save_button = QPushButton(window.tr("save"), self)
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton(window.tr("cancel"), self)
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        self.resize(440, 300)

    def values(self):
        return {
            "name": self.name_input.text().strip(),
            "api_type": self.type_combo.currentData(),
            "base_url": self.base_url_input.text().strip(),
            "api_key": self.api_key_input.text().strip(),
            "model": self.model_input.text().strip(),
            "concurrency": self.concurrency_input.value(),
            "interval": self.interval_input.value(),
        }


RULE_LABEL_KEYS = {
    RULE_ALL: "source_rules_all",
    RULE_EMPTY: "source_rules_empty",
    RULE_SELECTION: "source_rules_selection",
}


class RulesButton(QToolButton):
    """三个规则的多选下拉框：勾选项，收起时显示「全表 / 空白」这样的汇总。"""

    rules_changed = Signal(object)

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setPopupMode(QToolButton.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 固定宽度：各行规则下拉框宽度一致，后面的图标才能对齐
        longest = " / ".join(window.tr(RULE_LABEL_KEYS[rule]) for rule in ALL_RULES)
        self.setFixedWidth(self.fontMetrics().horizontalAdvance(longest) + 34)
        menu = QMenu(self)
        container = QWidget(menu)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(8, 4, 8, 4)
        container_layout.setSpacing(2)
        self.checkboxes = {}
        for rule in ALL_RULES:
            box = QCheckBox(window.tr(RULE_LABEL_KEYS[rule]), container)
            box.stateChanged.connect(self._on_toggled)
            container_layout.addWidget(box)
            self.checkboxes[rule] = box
        # 用 QWidgetAction 装勾选框：点勾选框不会关掉下拉，可以一次勾好几个
        action = QWidgetAction(menu)
        action.setDefaultWidget(container)
        menu.addAction(action)
        self.setMenu(menu)
        self.refresh_text()

    def rules(self):
        return [rule for rule in ALL_RULES if self.checkboxes[rule].isChecked()]

    def set_rules(self, rules):
        for rule, box in self.checkboxes.items():
            box.blockSignals(True)
            box.setChecked(rule in rules)
            box.blockSignals(False)
        self.refresh_text()

    def refresh_text(self):
        labels = [self.window.tr(RULE_LABEL_KEYS[rule]) for rule in self.rules()]
        self.setText(" / ".join(labels) if labels else self.window.tr("source_rules_none"))

    def _on_toggled(self, _state):
        self.refresh_text()
        self.rules_changed.emit(self.rules())


class SourceRowWidget(QWidget):
    """翻译源列表里的一行：上移/下移 + 名称 + 规则多选 + 测试 + 编辑 + 删除。"""

    ICON_SLOT_WIDTH = 26

    def __init__(self, dialog, entry, parent=None):
        super().__init__(parent)
        self.dialog = dialog
        self.entry = entry
        window = dialog.window

        self.move_up_button = self._icon_button(QStyle.StandardPixmap.SP_ArrowUp, window.tr("source_move_up"))
        self.move_up_button.clicked.connect(lambda: dialog.move_source(entry.source_id, -1))
        self.move_down_button = self._icon_button(QStyle.StandardPixmap.SP_ArrowDown, window.tr("source_move_down"))
        self.move_down_button.clicked.connect(lambda: dialog.move_source(entry.source_id, 1))
        self.name_label = QLabel(dialog.source_label(entry), self)
        self.name_label.setToolTip(dialog.source_tooltip(entry))
        self.rules_button = RulesButton(window, self)
        self.rules_button.set_rules(entry.rules)
        self.rules_button.rules_changed.connect(self._on_rules_changed)
        self.test_button = self._icon_button(QStyle.StandardPixmap.SP_MediaPlay, window.tr("source_test"),
                                            color=QColor("white"))
        self.test_button.clicked.connect(lambda: dialog.run_source_test(entry))

        self.edit_button = None
        if dialog.is_source_editable(entry):
            self.edit_button = self._icon_button(QStyle.StandardPixmap.SP_FileDialogInfoView, window.tr("source_edit"))
            self.edit_button.clicked.connect(lambda: dialog.edit_source(entry))

        self.remove_button = None
        if entry.is_ai:
            self.remove_button = self._icon_button(QStyle.StandardPixmap.SP_TrashIcon, window.tr("source_remove"))
            self.remove_button.clicked.connect(lambda: dialog.remove_source(entry))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        layout.addWidget(self.move_up_button)
        layout.addWidget(self.move_down_button)
        layout.addWidget(self.name_label, 1)
        layout.addWidget(self.rules_button)
        layout.addWidget(self.test_button)
        # 没有图标的位置用等宽占位，保证每行的图标列都对齐
        layout.addWidget(self.edit_button if self.edit_button is not None else self._icon_slot())
        layout.addWidget(self.remove_button if self.remove_button is not None else self._icon_slot())

    def _icon_button(self, pixmap, tooltip, color=None):
        button = QToolButton(self)
        icon = self.style().standardIcon(pixmap)
        if color is not None:
            icon = self._tinted_icon(icon, color)
        button.setIcon(icon)
        button.setIconSize(QSize(16, 16))
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedWidth(self.ICON_SLOT_WIDTH)
        return button

    @staticmethod
    def _tinted_icon(icon, color):
        """把标准图标涂成指定颜色（测试按钮用白色）。"""
        source = icon.pixmap(QSize(16, 16))
        tinted = QPixmap(source.size())
        tinted.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tinted)
        painter.drawPixmap(0, 0, source)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), color)
        painter.end()
        return QIcon(tinted)

    def _icon_slot(self):
        slot = QWidget(self)
        slot.setFixedWidth(self.ICON_SLOT_WIDTH)
        return slot

    def _on_rules_changed(self, rules):
        self.entry.rules = list(rules)

class ApiKeyDialog(QDialog):
    """内置源里只有 DeepL 要密钥，点它的笔弹这个。"""

    def __init__(self, window, parent=None, api_key=""):
        super().__init__(parent or window)
        self.window = window
        self.setWindowTitle(window.tr("source_deepl"))
        self.api_key_input = QLineEdit(api_key, self)
        self.api_key_input.setEchoMode(QLineEdit.Password)
        form = QFormLayout()
        form.addRow(QLabel(window.tr("api_key"), self), self.api_key_input)
        save_button = QPushButton(window.tr("save"), self)
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton(window.tr("cancel"), self)
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        self.resize(420, 120)

    def value(self):
        return self.api_key_input.text().strip()


class TranslationSettingsDialog(QDialog):
    ai_dialog_class = AiSourceDialog
    key_dialog_class = ApiKeyDialog

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.form_rows = {}
        self.source_rows = {}
        self.setWindowTitle(window.tr("translation_settings").rstrip("."))
        # 对话框编辑的是副本；点「保存」才写回 window（取消不留痕）
        self.sources = window.translation_sources.clone()

        self.char_budget_input = QSpinBox(self)
        self.char_budget_input.setRange(MIN_CHAR_BUDGET, MAX_CHAR_BUDGET)
        self.char_budget_input.setSingleStep(100)
        self.char_budget_input.setValue(window.translation_char_budget)

        self.timeout_input = QSpinBox(self)
        self.timeout_input.setRange(5, 300)
        self.timeout_input.setSingleStep(5)
        self.timeout_input.setValue(int(window.translation_timeout))

        self.clear_cache_button = QPushButton(window.tr("clear_translation_cache"), self)
        self.clear_cache_button.clicked.connect(self.clear_translation_cache)

        form = QFormLayout()
        self.add_form_row(form, "char_budget", window.tr("char_budget"), self.char_budget_input, window.tr("char_budget_tooltip"))
        self.add_form_row(form, "timeout", window.tr("timeout"), self.timeout_input)
        self.add_form_row(form, "clear_cache", window.tr("translation_cache"), self.clear_cache_button)

        self.source_rows_layout = QVBoxLayout()
        self.source_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.source_rows_layout.setSpacing(2)
        self.add_ai_source_button = QPushButton("+ " + window.tr("add_ai_source"), self)
        self.add_ai_source_button.clicked.connect(self.add_ai_source)

        source_box = QGroupBox(window.tr("translation_sources"), self)
        source_box_layout = QVBoxLayout(source_box)
        source_box_layout.addLayout(self.source_rows_layout)
        source_box_layout.addWidget(self.add_ai_source_button, 0, Qt.AlignLeft)

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
        layout.addWidget(source_box)
        layout.addStretch(1)
        layout.addLayout(buttons)

        self.refresh_source_rows()
        self.resize(760, 560)

    # —— 通用字段 ——

    def add_form_row(self, form, key, label_text, widget, tooltip=None):
        label = QLabel(label_text, self)
        if tooltip:
            label.setToolTip(tooltip)
            widget.setToolTip(tooltip)
        form.addRow(label, widget)
        self.form_rows[key] = (label, widget)

    def is_field_visible(self, key):
        if key not in self.form_rows:
            return False                  # 预设行已删，"preset" 这种键查不到
        label, widget = self.form_rows[key]
        return not label.isHidden() and not widget.isHidden()

    # —— 翻译源列表 ——

    def source_label(self, entry):
        return self.window.source_label(entry)

    def source_tooltip(self, entry):
        """免费源显示内置的并发/间隔；AI 源显示接口类型与模型。"""
        if entry.is_ai:
            parts = [self.window.tr("source_kind_ai"), entry.api_type, entry.model]
            return " · ".join(part for part in parts if part)
        spec = FREE_SOURCE_SPECS.get(entry.source_id, {})
        return " · ".join([
            self.window.tr("source_kind_free"),
            self.window.tr(
                "source_builtin_text",
                concurrency=spec.get("concurrency", 1),
                interval=spec.get("interval", 0.0),
            ),
        ])

    def is_source_editable(self, entry):
        """AI 源都能改；免费源里只有要密钥的（DeepL）有可改的东西。"""
        return entry.is_ai or bool(FREE_SOURCE_SPECS.get(entry.source_id, {}).get("needs_key"))

    def refresh_source_rows(self):
        while self.source_rows_layout.count():
            item = self.source_rows_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.source_rows = {}
        last_index = len(self.sources.entries) - 1
        for index, entry in enumerate(self.sources.entries):
            row = SourceRowWidget(self, entry, self)
            row.move_up_button.setEnabled(index > 0)
            row.move_down_button.setEnabled(index < last_index)
            self.source_rows[entry.source_id] = row
            self.source_rows_layout.addWidget(row)

    def move_source(self, source_id, delta):
        if delta < 0:
            self.sources.move_up(source_id)
        else:
            self.sources.move_down(source_id)
        self.refresh_source_rows()

    def remove_source(self, entry):
        if not entry.is_ai:
            return                      # 内置源不给删，只能取消勾选
        answer = QMessageBox.question(
            self, self.window.tr("source_remove"),
            self.window.tr("source_remove_confirm", name=self.source_label(entry)),
        )
        if answer != QMessageBox.Yes:
            return
        self.sources.remove(entry.source_id)
        self.refresh_source_rows()

    def add_ai_source(self):
        dialog = self.ai_dialog_class(self.window, self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        if not values.get("name"):
            QMessageBox.warning(self, self.window.tr("add_ai_source"), self.window.tr("source_name_required"))
            return
        if self.sources.has_name(values["name"]):
            answer = QMessageBox.question(
                self, self.window.tr("add_ai_source"),
                self.window.tr("source_name_duplicate", name=values["name"]),
            )
            if answer != QMessageBox.Yes:
                return
        # 新加的 AI 源默认只勾「右键选中」。勾上「翻译全表」= 授权一次可能产生
        # 费用的批量调用，必须由用户自己动手勾。
        entry = SourceEntry(
            kind="ai",
            name=values["name"],
            api_type=values.get("api_type") or "openai",
            rules=[RULE_SELECTION],
            api_key=values.get("api_key", ""),
            base_url=values.get("base_url", ""),
            model=values.get("model", ""),
            concurrency=int(values.get("concurrency") or 1),
            interval=float(values.get("interval") or 0.0),
        )
        self.sources.add_ai(entry)
        self.refresh_source_rows()

    def edit_source(self, entry):
        if entry.is_ai:
            dialog = self.ai_dialog_class(self.window, self, entry)
            if dialog.exec() != QDialog.Accepted:
                return
            values = dialog.values()
            if not values.get("name"):
                QMessageBox.warning(self, self.window.tr("edit_ai_source"), self.window.tr("source_name_required"))
                return
            if values["name"] != entry.name and self.sources.has_name(values["name"]):
                answer = QMessageBox.question(
                    self, self.window.tr("edit_ai_source"),
                    self.window.tr("source_name_duplicate", name=values["name"]),
                )
                if answer != QMessageBox.Yes:
                    return
            entry.name = values["name"]
            entry.api_type = values.get("api_type") or "openai"
            entry.base_url = values.get("base_url", "")
            entry.api_key = values.get("api_key", "")
            entry.model = values.get("model", "")
            entry.concurrency = int(values.get("concurrency") or 1)
            entry.interval = float(values.get("interval") or 0.0)
            self.refresh_source_rows()
            return
        dialog = self.key_dialog_class(self.window, self, entry.api_key)
        if dialog.exec() == QDialog.Accepted:
            entry.api_key = dialog.value()

    # —— 每个源单独测试 ——

    def _build_test_config(self, entry):
        return self.window.build_source_config(
            entry, self.char_budget_input.value(), float(self.timeout_input.value())
        )

    def run_source_test(self, entry):
        try:
            config = self._build_test_config(entry)
            validate_translator_config(config)
        except ValueError as exc:
            QMessageBox.warning(self, self.window.tr("test_translation"), str(exc))
            return
        # 上一个测试可能还卡在网络上：直接放弃它（结果不再弹窗），这次测试照跑不误。
        self._cancel_test_thread()
        service = self._build_test_service()
        # 线程挂在主窗口下：对话框先关掉时线程不会跟着被销毁（QThread 运行时被销毁会崩）。
        self._test_thread = QThread(self.window)
        self._test_worker = TranslationWorker(service=service, jobs=self._current_test_jobs(), configs=[config])
        self._test_worker.moveToThread(self._test_thread)
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.failed.connect(self._on_test_failed)
        self._test_worker.finished.connect(self._test_thread.quit)
        self._test_worker.failed.connect(self._test_thread.quit)
        self._test_thread.finished.connect(self._test_worker.deleteLater)
        self._test_thread.finished.connect(self._test_thread.deleteLater)
        self._test_thread.start()
        self._set_test_running(entry.source_id)

    def _build_test_service(self):
        """测试用的翻译服务：探活只试两次，失败立刻报，不等重试退避。"""
        service = TranslationService()
        service.retry_policy = TEST_RETRY_POLICY
        return service

    def _set_test_running(self, source_id):
        """只改提示，不禁用按钮：正在跑的源可能卡在网络上，不能让它挡住别的源。"""
        for row_source_id, row in self.source_rows.items():
            key = "test_translation_running" if row_source_id == source_id else "source_test"
            row.test_button.setToolTip(self.window.tr(key))

    def _cancel_test_thread(self):
        """放弃正在跑的测试：断开结果回调、置取消位（请求返回后线程自然退出）。"""
        worker = getattr(self, "_test_worker", None)
        thread = getattr(self, "_test_thread", None)
        self._test_worker = None
        self._test_thread = None
        if worker is None or thread is None:
            return
        for signal, slot in ((worker.finished, self._on_test_finished), (worker.failed, self._on_test_failed)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        try:
            worker.cancel()
            if not thread.isRunning():
                return
            thread.quit()
            # 线程可能还卡在网络请求里：它真正结束前不能丢掉引用，
            # 否则 worker 会在另一个线程正在执行时被销毁（QThread 在运行中被析构会崩）。
            self.window._test_threads.append((worker, thread))
            thread.finished.connect(lambda w=worker, t=thread: self._release_test_thread(w, t))
        except RuntimeError:
            # 线程已经结束、对象已被 deleteLater 销毁：没什么可取消的。
            # （点完一个源的测试再点另一个时就会走到这里，不接住会让按钮像卡死一样没反应。）
            return

    def _release_test_thread(self, worker, thread):
        self.window._test_threads = [pair for pair in self.window._test_threads if pair[0] is not worker]

    def done(self, result):
        # 关窗/确定时不阻塞等待：线程挂在主窗口下、引用也留着，它自己会结束。
        self._cancel_test_thread()
        super().done(result)

    def _on_test_finished(self, results):
        self._reset_test_button()
        lines = []
        succeeded = 0
        # 按 job 的 (row, column) 查找结果，而非用 zip 按位置配对：
        # 某语言失败时 cell_results 会缺少该条目，zip 会让剩余语言错位显示。
        for job in self._current_test_jobs():
            text = results.cell_results.get((job.row, job.column))
            if text is None:
                lines.append(f"{job.target_code}: (failed)")
            else:
                succeeded += 1
                lines.append(f"{job.target_code}: {text}")
        result_text = "\n".join(lines)
        if succeeded == 0:
            # 一条都没翻出来：不能报「测试成功」，要把失败原因显示出来
            reason = "\n".join(results.errors[:3]) or self.window.tr("test_translation_no_result")
            QMessageBox.critical(
                self,
                self.window.tr("test_translation"),
                self.window.tr("test_translation_failed", error=reason),
            )
            return
        if succeeded < len(self._current_test_jobs()):
            QMessageBox.warning(
                self,
                self.window.tr("test_translation"),
                self.window.tr("test_translation_partial", result=result_text),
            )
            return
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
        # 测试已经结束（信号就是从它发出来的），引用可以丢掉：线程马上会被
        # deleteLater 销毁，留着引用下次点测试就会摸到已删除的对象。
        self._test_thread = None
        self._test_worker = None
        for row in self.source_rows.values():
            row.test_button.setEnabled(True)
            row.test_button.setToolTip(self.window.tr("source_test"))

    def _current_test_jobs(self):
        test_word = "Knife"
        # 和正式翻译一样先把表头名转成接口认识的语言代码（english->en、chinese->zh-CN）：
        # 免费源拿 "chinese" 当语言码会直接 400。
        target_languages = ["chinese", "russian", "japanese", "german"]
        return [
            TranslationJob(
                row=0,
                column=index,
                text=test_word,
                source_code=source_language_code_for_header(self.window.source_header),
                target_code=language_code_for_header(lang),
            )
            for index, lang in enumerate(target_languages)
        ]

    # —— 保存 ——

    def apply_settings(self, close_dialog=True):
        self.window.translation_sources = self.sources.clone()
        self.window.translation_char_budget = self.char_budget_input.value()
        self.window.translation_timeout = float(self.timeout_input.value())
        self.window.save_translation_settings()
        if close_dialog:
            self.accept()

    def clear_translation_cache(self):
        self.window.clear_translation_cache()


class QualityCheckSettingsDialog(QDialog):
    """检查设置：逐条勾选检查项 + 相似率门槛。"""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle(window.tr("quality_check_settings").rstrip("."))

        self.similarity_input = QDoubleSpinBox(self)
        self.similarity_input.setRange(0.5, 1.0)
        self.similarity_input.setSingleStep(0.01)
        self.similarity_input.setDecimals(2)
        self.similarity_input.setValue(window.quality_config.similarity)

        form = QFormLayout()
        form.addRow(QLabel(window.tr("similarity_threshold"), self), self.similarity_input)

        self.checkboxes = {}
        groups_layout = QVBoxLayout()
        for group_key, rules in RULE_GROUPS:
            group_box = QGroupBox(window.tr(group_key), self)
            group_layout = QVBoxLayout(group_box)
            select_all_button = QPushButton(window.tr("qc_select_all"), group_box)
            select_all_button.clicked.connect(lambda _checked=False, rules=rules: self.set_group(rules, True))
            select_none_button = QPushButton(window.tr("qc_select_none"), group_box)
            select_none_button.clicked.connect(lambda _checked=False, rules=rules: self.set_group(rules, False))
            button_row = QHBoxLayout()
            button_row.addWidget(select_all_button)
            button_row.addWidget(select_none_button)
            button_row.addStretch(1)
            group_layout.addLayout(button_row)
            for rule in rules:
                checkbox = QCheckBox(window.tr(f"quality_rule_{rule}"), group_box)
                checkbox.setChecked(window.quality_config.is_enabled(rule))
                group_layout.addWidget(checkbox)
                self.checkboxes[rule] = checkbox
            groups_layout.addWidget(group_box)

        container = QWidget(self)
        container.setLayout(groups_layout)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)

        restore_button = QPushButton(window.tr("qc_restore_defaults"), self)
        restore_button.clicked.connect(self.restore_defaults)
        save_button = QPushButton(window.tr("save"), self)
        save_button.clicked.connect(self.apply_settings)
        cancel_button = QPushButton(window.tr("cancel"), self)
        cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(restore_button)
        buttons.addStretch(1)
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(scroll, 1)
        layout.addLayout(buttons)
        self.resize(520, 620)

    def set_group(self, rules, checked):
        for rule in rules:
            self.checkboxes[rule].setChecked(checked)

    def restore_defaults(self):
        defaults = QualityCheckConfig()
        for rule, checkbox in self.checkboxes.items():
            checkbox.setChecked(defaults.is_enabled(rule))
        self.similarity_input.setValue(defaults.similarity)

    def values(self):
        return QualityCheckConfig(
            enabled=[rule for rule, checkbox in self.checkboxes.items() if checkbox.isChecked()],
            similarity=self.similarity_input.value(),
        )

    def apply_settings(self):
        self.window.save_quality_config(self.values())
        self.accept()


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
        self.translation_sources = SourceList.from_json(
            self.settings.value("translation_sources_json", "")
        )
        self.translation_char_budget = int(
            self.settings.value("translation_char_budget", DEFAULT_CHAR_BUDGET)
        )
        self.translation_auto_concurrency = True      # 并发调节固定为自动（设置界面已去掉这个开关）
        self.translation_timeout = float(self.settings.value("translation_timeout", 60.0))
        self._translation_rule = RULE_SELECTION
        self._migrate_translation_settings()
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
        # 被放弃的测试线程（用户又点了别的源/关掉了设置窗）：等它真结束再放手
        self._test_threads = []
        # 跨次翻译共享的缓存：相同 (引擎, 模型, 源/目标语言, 文本) 的结果只翻译一次。
        # 落盘在软件目录旁，重开软件仍能复用；写不进去则回退到用户数据目录。
        self.translation_cache_store = TranslationCacheStore()
        self.translation_cache = self.translation_cache_store.load()
        self._translation_written_cells = set()
        self._translation_job_rows = set()
        self._translation_job_cells = set()
        self._translation_failed_cells = set()
        self._translation_copy_overwrite = True
        # 质检：自动查出来的问题格 + 右键手动标的格子，只存在内存里，不写进 csv
        self.quality_config = QualityCheckConfig.from_json(self.settings.value("quality_check_config", ""))
        self.quality_issues = {}
        self.manual_issue_cells = set()
        self._quality_painted = set()
        self._quality_check_cancelled = False
        self.quality_check_thread = None
        self.quality_check_worker = None
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

        self.menu_file.addSeparator()
        self.action_check_errors = QAction("Check for Errors", self)
        self.action_check_errors.triggered.connect(self.check_errors)
        self.menu_file.addAction(self.action_check_errors)
        self.action_translate_errors = QAction("Translate Error Cells", self)
        self.action_translate_errors.triggered.connect(self.translate_error_cells)
        self.menu_file.addAction(self.action_translate_errors)

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
        self.action_quality_check_settings = QAction("Check Settings...", self)
        self.action_quality_check_settings.triggered.connect(self.open_quality_check_settings)
        self.menu_settings.addAction(self.action_quality_check_settings)
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
        self.action_check_errors.setText(texts["check_errors"])
        self.action_translate_errors.setText(texts["translate_error_cells"])
        self.menu_search.setTitle(texts["search"])
        self.search_action.setText(texts["search"])
        self.menu_settings.setTitle(texts["settings"])
        self.action_source_language.setText(texts["source_language"])
        self.action_translation_settings.setText(texts["translation_settings"])
        self.action_quality_check_settings.setText(texts["quality_check_settings"])
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
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(1000)
        self._retry_timer.timeout.connect(self._tick_retry_countdown)
        self._retry_seconds_left = 0
        self._retry_attempt = 0
        self._retry_max_attempts = 0
        self.statusBar().addPermanentWidget(self.translation_progress_label)
        self.statusBar().addPermanentWidget(self.translation_progress_bar)
        self.statusBar().addPermanentWidget(self.translation_cancel_button)
        self.statusBar().addPermanentWidget(self.current_file_label, 1)
        self.hide_translation_progress()

    def hide_translation_progress(self):
        self._stop_retry_countdown()
        self.translation_progress_label.hide()
        self.translation_progress_bar.hide()
        self.translation_cancel_button.hide()

    def show_translation_progress(self, total):
        self._stop_retry_countdown()
        self.translation_progress_label.setText(f"0/{total}")
        self.translation_progress_bar.setRange(0, total)
        self.translation_progress_bar.setValue(0)
        self.translation_progress_label.show()
        self.translation_progress_bar.show()
        self.translation_cancel_button.show()
        self._translation_written_cells = set()

    def on_translation_retrying(self, attempt, max_attempts, wait_seconds):
        self._retry_seconds_left = max(0, int(round(wait_seconds)))
        self._retry_attempt = attempt
        self._retry_max_attempts = max_attempts
        self._render_retry_label()
        self._retry_timer.start()

    def on_translation_fallback(self, previous_label, next_label):
        """主备降级：状态栏显示一行小字（决定 20）。"""
        self.statusBar().showMessage(
            self.tr("translation_fallback", previous=previous_label, current=next_label),
            8000,
        )

    def _tick_retry_countdown(self):
        self._retry_seconds_left -= 1
        if self._retry_seconds_left <= 0:
            self._retry_timer.stop()
            self._retry_seconds_left = 0
        self._render_retry_label()

    def _render_retry_label(self):
        self.translation_progress_label.setText(
            self.tr("retry_countdown",
                    seconds=self._retry_seconds_left,
                    attempt=self._retry_attempt,
                    max_attempts=self._retry_max_attempts)
        )

    def _stop_retry_countdown(self):
        self._retry_timer.stop()
        self._retry_seconds_left = 0

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
        self.reset_quality_marks()
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
        # 手动改过的格子：原来的错误标记已经过期，直接去掉（不然标记会一直挂着）
        cell_key = (item.row(), item.column())
        if cell_key in self.quality_issues or cell_key in self.manual_issue_cells:
            self.quality_issues.pop(cell_key, None)
            self.manual_issue_cells.discard(cell_key)
            self.paint_quality_cells()
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
        # 重建单元格会抹掉所有底色，撤销后要把问题格重新刷上
        self._quality_painted = set()
        self.paint_quality_cells()

    def redo(self):
        snapshot = self.history.redo()
        if snapshot is None:
            return
        self.history.suppress(True)
        restore_table(self.table, snapshot, block_signal_widget=self.table)
        self.history.suppress(False)
        self.set_dirty(True)
        self._quality_painted = set()
        self.paint_quality_cells()

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

    def open_quality_check_settings(self):
        dialog = QualityCheckSettingsDialog(self)
        dialog.exec()

    def save_quality_config(self, config):
        self.quality_config = config
        self.settings.setValue("quality_check_config", config.to_json())
        self.settings.sync()

    def open_wordbook_window(self):
        if self.wordbook_window is None:
            self.wordbook_window = WordbookWindow(self)
        self.wordbook_window.show()
        self.wordbook_window.raise_()
        self.wordbook_window.activateWindow()

    def source_label(self, entry):
        if entry.is_ai:
            return entry.name or entry.api_type or "AI"
        return self.tr(FREE_SOURCE_SPECS.get(entry.source_id, {}).get("label_key", entry.source_id))

    def translation_source_summary(self):
        labels = [self.source_label(entry) for entry in self.translation_sources.entries if entry.rules]
        return " → ".join(labels) if labels else self.tr("no_source_selected")

    def build_source_config(self, entry, char_budget=None, timeout=None):
        return translation_flow.build_source_config(
            entry,
            char_budget=self.translation_char_budget if char_budget is None else char_budget,
            timeout=self.translation_timeout if timeout is None else timeout,
            label=self.source_label(entry),
            glossary=self.wordbook_glossary(),
            glossary_source_key=self.source_header,
        )

    def build_translation_configs(self, rule):
        return [
            self.build_source_config(entry)
            for entry in self.translation_sources.candidates(rule)
        ]

    def _migrate_translation_settings(self):
        """首次运行：清掉旧的 provider_settings 密钥，写入新的源列表。"""
        if str(self.settings.value("translation_sources_json", "") or "").strip():
            return
        self.settings.remove("provider_settings")
        self.settings.remove("translation_provider")
        self.settings.remove("translation_parallel_batches")     # 决定 24：这个设置项整个删掉
        self.settings.remove("translation_auto_concurrency")      # 自动并发开关也没了，固定自动
        self.settings.remove("translation_presets")              # 决定 26：预设整个删掉（连同里面的密钥）
        self.settings.remove("translation_preset_names_list")
        self.settings.setValue("translation_sources_json", self.translation_sources.to_json())
        self.settings.sync()

    def save_translation_settings(self):
        self.settings.setValue("translation_sources_json", self.translation_sources.to_json())
        self.settings.setValue("translation_char_budget", self.translation_char_budget)
        self.settings.setValue("translation_timeout", self.translation_timeout)
        self.settings.sync()
        self.statusBar().showMessage(
            self.tr("translation_engine_status", engine=self.translation_source_summary()),
            5000,
        )

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
            "split_stuck_words": self.split_selected_words,
            "delete_row": self.delete_rows,
            "delete_column": self.delete_column_cells,
            "reset_column_order": self.reset_column_order,
            "insert_row_above": self.insert_row_above,
            "insert_row_below": self.insert_row_below,
            "fill_row_with_cell": self.fill_row_with_cell,
            "translate_selected_cells": self.translate_selected_cells,
            "translate_selected_rows": self.translate_selected_rows,
            "translate_selected_columns": self.translate_selected_columns,
            "mark_error": lambda: self.mark_context_as_errors(context, row, column),
            "unmark_error": lambda: self.unmark_context_errors(context, row, column),
            "mark_row_error": lambda: self.mark_context_as_errors(context, row, column),
            "unmark_row_error": lambda: self.unmark_context_errors(context, row, column),
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
        mark_actions = self.context_mark_action_names(context, row, column)
        if mark_actions:
            actions.append("-")
            actions.extend(mark_actions)
        if translate_actions:
            actions.append("-")
            actions.extend(translate_actions)
        # 右键落在具体行或列上就说明有选中内容，源语言列的格子可以就地拆词
        if row >= 0 or column >= 0:
            actions.append("-")
            actions.append("split_stuck_words")
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

    def is_quality_target_column(self, column):
        """质检和「翻译错误文本」的目标列：语言列，且不是源语言列。"""
        if not self.is_translatable_column(column):
            return False
        try:
            return column != self.headers.index(self.source_header)
        except ValueError:
            return True

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

    def split_selected_words(self):
        try:
            source_column = self.headers.index(self.source_header)
        except ValueError:
            QMessageBox.warning(self, self.tr("split_stuck_words"), self.tr("source_column_missing", header=self.source_header))
            return
        changed = 0
        self.table.blockSignals(True)
        for item in self.selected_cell_items():
            if item.column() != source_column:
                continue
            text = item.text()
            split_text = split_stuck_words(text)
            if split_text == text:
                continue
            self.set_cell_text(item.row(), item.column(), split_text)
            changed += 1
        self.table.blockSignals(False)
        if not changed:
            self.statusBar().showMessage(self.tr("split_stuck_words_none"), 8000)
            return
        self._record_history()
        self.set_dirty(True)
        self.statusBar().showMessage(self.tr("split_stuck_words_done", count=changed), 8000)

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
        self.run_translation_jobs(jobs, rule=RULE_SELECTION)

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
            jobs = translation_flow.collect_jobs(
                self.headers, self.table_rows(), self.source_header,
                mode=translation_flow.MODE_ROWS, row_indexes=rows)
        except Exception as exc:
            QMessageBox.warning(self, self.tr("translate_rows"), str(exc))
            return
        # 复制列（original<-english, chinese<-chinesesimp）在翻译前填充，不受翻译成败影响
        self._fill_copy_columns(self.table_rows(), overwrite=True, row_indexes=rows)
        self.run_translation_jobs(jobs, rule=RULE_SELECTION)

    def translate_selected_columns(self):
        rows, columns = self.selected_rows_and_columns()
        if not columns:
            current_column = self.table.currentColumn()
            columns = {current_column} if current_column >= 0 else set()
        try:
            jobs = translation_flow.collect_jobs(
                self.headers, self.table_rows(), self.source_header,
                mode=translation_flow.MODE_COLUMNS, columns=columns)
        except Exception as exc:
            QMessageBox.warning(self, self.tr("translate_columns"), str(exc))
            return
        # 复制列（original<-english, chinese<-chinesesimp）在翻译前填充，不受翻译成败影响
        self._fill_copy_columns(self.table_rows(), overwrite=True)
        self.run_translation_jobs(jobs, rule=RULE_SELECTION)

    def translate_all_cells(self):
        if self.source_header not in self.headers:
            QMessageBox.warning(self, self.tr("translate_cells"), self.tr("source_column_missing", header=self.source_header))
            return
        rows = self.table_rows()
        # 复制列（original<-english, chinese<-chinesesimp）直接填充，不走 AI 翻译
        self._fill_copy_columns(rows, overwrite=True)
        # 任务从「填复制列之前」的快照里挑：源列本身是复制列时不会凭空多出任务
        jobs = translation_flow.collect_jobs(
            self.headers, rows, self.source_header, mode=translation_flow.MODE_ALL)
        self.run_translation_jobs(jobs, rule=RULE_ALL)

    def translate_empty_cells(self):
        if self.source_header not in self.headers:
            QMessageBox.warning(self, self.tr("translate_cells"), self.tr("source_column_missing", header=self.source_header))
            return
        rows = self.table_rows()
        # 复制列（original<-english, chinese<-chinesesimp）仅填充空白单元格
        self._fill_copy_columns(rows, overwrite=False)
        # 重新读取已更新的行数据，使后续空白判断反映复制结果
        rows = self.table_rows()
        jobs = translation_flow.collect_jobs(
            self.headers, rows, self.source_header, mode=translation_flow.MODE_EMPTY)
        self.run_translation_jobs(jobs, copy_overwrite=False, rule=RULE_EMPTY)

    def _fill_copy_columns(self, rows, overwrite=False, row_indexes=None):
        """填充复制列：original<-english, chinese<-chinesesimp。

        overwrite=True 时覆盖已有内容（用于"翻译全表"），
        overwrite=False 时仅填充空白单元格（用于"翻译空白单元格"）。
        row_indexes 指定只处理的行（用于选中单元格/行/列翻译），None 表示全部行。
        """
        filled, changed = translation_flow.fill_copy_columns(
            self.headers, rows, overwrite=overwrite, row_indexes=row_indexes)
        if not changed:
            return
        # 批量写入时屏蔽 itemChanged，避免每个单元格都推一条历史快照
        # （否则翻译前的状态会被挤出撤销栈，且 undo 需要按 N 次）。
        self.table.blockSignals(True)
        try:
            for row_index, row in enumerate(filled):
                original = rows[row_index]
                for column_index, value in enumerate(row):
                    if column_index < len(original) and value == original[column_index]:
                        continue
                    self.set_cell_text(row_index, column_index, value)
        finally:
            self.table.blockSignals(False)
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

    def run_translation_jobs(self, jobs, copy_overwrite=True, rule=RULE_SELECTION):
        jobs = self._sort_jobs_by_row_column(jobs)
        self.start_translation_worker(jobs, copy_overwrite=copy_overwrite, rule=rule)

    def _sort_jobs_by_row_column(self, jobs):
        """按 (行, 列) 排序翻译任务，使相邻单元格聚拢，便于批次切分与进度展示。"""
        if not jobs:
            return jobs
        return sorted(jobs, key=lambda j: (j[0], j[1]))

    def start_translation_worker(self, raw_jobs, run_immediately=False, copy_overwrite=True, rule=RULE_SELECTION):
        jobs = [
            TranslationJob(row, column, text, source_language_code_for_header(self.source_header), target)
            for row, column, text, target in raw_jobs
        ]
        # 记录本次任务涉及的行与复制列覆盖策略，翻译完成后据此回填 original/chinese 复制列
        self._translation_job_rows = {row for row, column, text, target in raw_jobs}
        self._translation_job_cells = {(row, column) for row, column, text, target in raw_jobs}
        self._translation_copy_overwrite = copy_overwrite
        if not jobs:
            QMessageBox.information(self, self.tr("translate"), self.tr("no_translatable_cells"))
            return

        # 防止翻译进行中重复启动新任务：先取消并等待旧线程结束，避免 QThread 被覆盖导致泄漏。
        if self._is_translation_running():
            QMessageBox.warning(self, self.tr("translate"), self.tr("translation_in_progress"))
            return

        configs = self.build_translation_configs(rule)
        if not configs:
            QMessageBox.warning(
                self,
                self.tr("translate"),
                self.tr("no_source_for_action", action=self.tr(f"action_{'all_cells' if rule == RULE_ALL else 'empty_cells' if rule == RULE_EMPTY else 'selection'}")),
            )
            return

        self._translation_rule = rule
        self.show_translation_progress(len(jobs))

        self.translation_worker = self.create_translation_worker(jobs, configs)
        self.translation_worker.progress.connect(self.update_translation_progress)
        self.translation_worker.retrying.connect(self.on_translation_retrying)
        self.translation_worker.fallback.connect(self.on_translation_fallback)
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

    def _ensure_test_threads_stopped(self, wait_ms=500):
        """退出前收尾被放弃的测试线程，理由同 _ensure_translation_stopped。"""
        for worker, thread in list(self._test_threads):
            try:
                worker.cancel()
                if thread.isRunning():
                    thread.quit()
                    thread.wait(wait_ms)
            except RuntimeError:
                # 线程已经结束并被销毁：跳过，别让它挡住窗口关闭。
                continue
        self._test_threads = []

    def create_translation_worker(self, jobs, configs):
        # 注入共享缓存：多次翻译运行复用相同内容的翻译结果
        return TranslationWorker(
            service=TranslationService(cache=self.translation_cache),
            jobs=jobs,
            configs=configs,
        )

    def clear_translation_cache(self):
        self.translation_cache = {}
        self.translation_cache_store.clear()
        self.statusBar().showMessage(self.tr("clear_translation_cache"), 3000)

    def wordbook_glossary(self):
        if self.wordbook_window is None:
            return []
        return translation_flow.build_glossary(self.wordbook_window.glossary_rows())

    def update_translation_progress(self, results):
        self._stop_retry_countdown()
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
        self._stop_retry_countdown()
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
        # 重译成功的格子自动取消错误标记，失败的保留（用户决定）
        if results.cell_results and (self.quality_issues or self.manual_issue_cells):
            done_cells = self.quality_problem_cells() & set(results.cell_results)
            if done_cells:
                for cell_key in done_cells:
                    self.quality_issues.pop(cell_key, None)
                    self.manual_issue_cells.discard(cell_key)
                self.paint_quality_cells()
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
        self._translation_failed_cells = {
            key for key in self._translation_job_cells if key not in results.cell_results
        }
        if not results.cancelled and results.failed and results.errors and results.translated == 0:
            QMessageBox.warning(self, self.tr("translate_failed"), "\n".join(results.errors[:3]))
        elif not results.cancelled and self._translation_failed_cells:
            box = QMessageBox(self)
            box.setWindowTitle(self.tr("translate"))
            box.setText(self.tr("failed_cells_count", count=len(self._translation_failed_cells)))
            retry_button = box.addButton(self.tr("retry_failed_only"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(self.tr("close"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is retry_button:
                self.retry_failed_cells()

    def retry_failed_cells(self):
        cells = sorted(self._translation_failed_cells)
        if not cells:
            return
        rows = self.table_rows()
        source_column = self.headers.index(self.source_header)
        jobs = []
        for row_index, column_index in cells:
            row = rows[row_index]
            source_text = row[source_column].strip() if source_column < len(row) else ""
            if not source_text:
                continue
            target_code = language_code_for_header(self.headers[column_index])
            if not target_code:
                continue
            jobs.append((row_index, column_index, source_text, target_code))
        self.run_translation_jobs(jobs, copy_overwrite=False, rule=self._translation_rule)

    # —— 翻译质检 ——

    def quality_problem_cells(self):
        """所有被标记为错误的格子：自动查出来的 + 右键手动标的。"""
        return set(self.quality_issues) | self.manual_issue_cells

    def cell_has_quality_problem(self, row_index, column_index):
        cell_key = (row_index, column_index)
        return cell_key in self.quality_issues or cell_key in self.manual_issue_cells

    def restore_cell_background(self, row_index, column_index):
        """恢复单元格本来的底色：问题格用错误色，其余用默认底色。"""
        item = self.table.item(row_index, column_index)
        if item is None:
            return
        item.setBackground(QC_PROBLEM_COLOR if self.cell_has_quality_problem(row_index, column_index) else QColor())

    def paint_quality_cells(self):
        """把问题格刷成错误色，同时把不再有问题的格子恢复底色。"""
        problems = self.quality_problem_cells()
        self.table.blockSignals(True)
        try:
            for cell_key in self._quality_painted - problems:
                self.restore_cell_background(*cell_key)
            for cell_key in problems:
                item = self.table.item(*cell_key)
                if item is not None:
                    item.setBackground(QC_PROBLEM_COLOR)
            self._quality_painted = set(problems)
        finally:
            self.table.blockSignals(False)
        self.refresh_search_highlight()

    def refresh_search_highlight(self):
        """搜索窗口开着时重刷高亮，让问题格的标记色及时生效。"""
        if self.search_dialog is not None and self.search_dialog.isVisible():
            self.search_dialog.refresh_later()

    def reset_quality_marks(self):
        """换表/导入新数据时清空标记（标记不写盘，不跨表保留）。"""
        self.quality_issues = {}
        self.manual_issue_cells = set()
        self._quality_painted = set()
        self.refresh_search_highlight()

    def mark_cells_as_errors(self, cells):
        added = False
        for cell_key in cells:
            if cell_key not in self.manual_issue_cells:
                self.manual_issue_cells.add(cell_key)
                added = True
        if added:
            self.paint_quality_cells()

    def unmark_cells(self, cells):
        removed = False
        for cell_key in cells:
            if cell_key in self.manual_issue_cells:
                self.manual_issue_cells.discard(cell_key)
                removed = True
            if cell_key in self.quality_issues:
                del self.quality_issues[cell_key]
                removed = True
        if removed:
            self.paint_quality_cells()

    def context_mark_targets(self, context, row, column):
        """右键要标记的格子：单元格是选中的格子，行头是该行所有可翻译格。"""
        if context == "row_header":
            if row < 0:
                return []
            return [(row, index) for index in range(self.table.columnCount()) if self.is_quality_target_column(index)]
        if context == "cell":
            items = self.selected_cell_items()
            if not items and row >= 0 and column >= 0:
                return [(row, column)] if self.is_quality_target_column(column) else []
            return [(item.row(), item.column()) for item in items if self.is_quality_target_column(item.column())]
        return []

    def context_mark_action_names(self, context, row, column):
        """右键里的「标记为错误 / 取消错误标记」：没格子可操作时不出菜单项。"""
        targets = self.context_mark_targets(context, row, column)
        if not targets:
            return []
        marked = all(self.cell_has_quality_problem(*cell_key) for cell_key in targets)
        if context == "row_header":
            return ["unmark_row_error"] if marked else ["mark_row_error"]
        return ["unmark_error"] if marked else ["mark_error"]

    def mark_context_as_errors(self, context, row, column):
        self.mark_cells_as_errors(self.context_mark_targets(context, row, column))

    def unmark_context_errors(self, context, row, column):
        self.unmark_cells(self.context_mark_targets(context, row, column))

    def check_errors(self):
        self.start_quality_check()

    def start_quality_check(self, run_immediately=False):
        if self._is_translation_running() or self._is_quality_check_running():
            QMessageBox.warning(self, self.tr("check_errors"), self.tr("quality_check_running"))
            return
        if not self.headers:
            QMessageBox.warning(self, self.tr("check_errors"), self.tr("quality_check_no_csv"))
            return

        self._quality_check_cancelled = False
        self.quality_check_worker = QualityCheckWorker(
            self.visible_headers(),
            self.table_rows(),
            self.source_header,
            config=self.quality_config,
            glossary=self.wordbook_glossary(),
        )
        self.quality_check_worker.progress.connect(self.update_quality_progress)
        self.quality_check_worker.finished.connect(self.finish_quality_check)
        self.quality_check_worker.failed.connect(self.fail_quality_check)

        self.show_translation_progress(len(all_rules()))
        if run_immediately:
            self.quality_check_worker.run()
            return

        self.quality_check_thread = QThread(self)
        self.quality_check_worker.moveToThread(self.quality_check_thread)
        self.quality_check_thread.started.connect(self.quality_check_worker.run)
        self.quality_check_worker.finished.connect(self.quality_check_thread.quit)
        self.quality_check_worker.failed.connect(self.quality_check_thread.quit)
        # 线程结束后释放并清空引用，理由同翻译线程（旧引用调 isRunning() 会抛 RuntimeError）。
        self.quality_check_thread.finished.connect(self.quality_check_worker.deleteLater)
        self.quality_check_thread.finished.connect(self.quality_check_thread.deleteLater)
        self.quality_check_thread.finished.connect(self._clear_quality_check_thread)
        self.quality_check_thread.start()

    def update_quality_progress(self, done, total):
        done = min(done, total)
        self.translation_progress_bar.setRange(0, total)
        self.translation_progress_bar.setValue(done)
        self.translation_progress_label.setText(self.tr("quality_check_progress", done=done, total=total))

    def quality_check_cell_count(self):
        """本次检查覆盖的格子数：有原文的行 × 要检查的语言列。"""
        columns = target_columns(self.visible_headers(), self.source_header)
        try:
            source_column = self.headers.index(self.source_header)
        except ValueError:
            return 0
        rows = self.table_rows()
        return sum(1 for row in rows if source_column < len(row) and row[source_column].strip()) * len(columns)

    def finish_quality_check(self, issues):
        self.hide_translation_progress()
        self.translation_cancel_button.setEnabled(True)
        # 每点一次检查就是重算：上一轮的自动标记全部作废，手动标记保留
        self.quality_issues = dict(issues)
        self.paint_quality_cells()
        if self._quality_check_cancelled:
            self.statusBar().showMessage(self.tr("quality_check_cancelled"), 5000)
            return
        cells = self.quality_check_cell_count()
        if self.quality_issues:
            self.statusBar().showMessage(self.tr("quality_check_done", cells=cells, count=len(self.quality_issues)), 8000)
        else:
            self.statusBar().showMessage(self.tr("quality_check_clean", cells=cells), 8000)

    def fail_quality_check(self, message):
        self.hide_translation_progress()
        self.translation_cancel_button.setEnabled(True)
        QMessageBox.critical(self, self.tr("quality_check_failed"), message)

    def _clear_quality_check_thread(self):
        self.quality_check_worker = None
        self.quality_check_thread = None

    def _is_quality_check_running(self):
        return self.quality_check_thread is not None and self.quality_check_thread.isRunning()

    def _ensure_quality_check_stopped(self):
        """关窗时收尾检查线程，理由同 _ensure_translation_stopped。"""
        if self.quality_check_worker is not None:
            self.quality_check_worker.cancel()
        thread = self.quality_check_thread
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(3000)
        self.quality_check_worker = None
        self.quality_check_thread = None

    def translate_error_cells(self):
        cells = sorted(self.quality_problem_cells())
        if not cells:
            QMessageBox.information(self, self.tr("translate_error_cells"), self.tr("quality_check_no_cells"))
            return
        try:
            source_column = self.headers.index(self.source_header)
        except ValueError:
            QMessageBox.warning(self, self.tr("translate_error_cells"), self.tr("source_column_missing", header=self.source_header))
            return
        rows = self.table_rows()
        jobs = []
        for row_index, column_index in cells:
            if row_index >= len(rows) or not self.is_quality_target_column(column_index):
                continue
            row = rows[row_index]
            source_text = row[source_column].strip() if source_column < len(row) else ""
            target_code = language_code_for_header(self.headers[column_index])
            if source_text and target_code:
                jobs.append((row_index, column_index, source_text, target_code))
        if not jobs:
            QMessageBox.information(self, self.tr("translate_error_cells"), self.tr("quality_check_no_cells"))
            return
        self.run_translation_jobs(jobs, copy_overwrite=False, rule=RULE_SELECTION)

    def fail_translation(self, message):
        self._stop_retry_countdown()
        self.hide_translation_progress()
        self.translation_cancel_button.setEnabled(True)
        self.translation_cache_store.save(self.translation_cache)
        QMessageBox.critical(self, self.tr("translate_failed"), message)

    def cancel_translation(self):
        # 同一个取消按钮兼管翻译和检查（两者不会同时跑）
        if self.quality_check_worker is not None:
            self.quality_check_worker.cancel()
            self._quality_check_cancelled = True
            self.statusBar().showMessage(self.tr("cancelling_check"), 3000)
            self.translation_cancel_button.setEnabled(False)
            return
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
        self._ensure_quality_check_stopped()
        self._ensure_test_threads_stopped()
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
                # 恢复该格本来的底色：问题格的错误标记色不能被清掉
                self.restore_cell_background(row_index, column_index)


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("DayZTranslateTool")
    app.setApplicationName("DayZTranslateTool")
    window = DayzTranslateTool()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
