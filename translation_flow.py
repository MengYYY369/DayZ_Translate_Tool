"""无界面的翻译编排层：界面（main.py）与命令行（cli.py）共用。

这个模块不 import QtWidgets、不碰 QTableWidget：只做「表格数据 → 翻译任务 → 结果」的纯计算。
唯一跟 Qt 沾边的是 load_app_settings() / save_sources() / config_dir()，它们只用到 QSettings
与 QStandardPaths —— 实测这两个不需要 QApplication 实例，QCoreApplication 的静态 setter 就够。
"""

from dataclasses import dataclass, field
from pathlib import Path

from dayz_csv import (
    build_column_translation_jobs,
    build_row_translation_jobs,
    copy_source_for_header,
    header_index,
    language_code_for_header,
    source_language_code_for_header,
)
from free_translators import FREE_SOURCE_SPECS
from translation_sources import RULE_ALL, RULE_EMPTY, RULE_SELECTION, SourceList
from translator_service import (
    DEFAULT_CHAR_BUDGET,
    RetryPolicy,
    TranslationJob,
    TranslationService,
)

ORGANIZATION_NAME = "DayZTranslateTool"
APPLICATION_NAME = "DayZTranslateTool"

MODE_ALL = "all"
MODE_EMPTY = "empty"
MODE_COLUMNS = "columns"
MODE_ROWS = "rows"
ALL_MODES = (MODE_EMPTY, MODE_ALL, MODE_COLUMNS, MODE_ROWS)

DEFAULT_TIMEOUT = 60.0

# AI 源的接口类型（原来写在 main.py:77，这里成为唯一出处，main.py 改成引用这里）
AI_TYPE_KEYS = ("openai", "claude", "codex")

# 源测试用的固定样本（跟界面上的「测试这个源」一模一样）
TEST_TEXT = "Knife"
TEST_LANGUAGES = ("chinese", "russian", "japanese", "german")
TEST_RETRY_POLICY = RetryPolicy(max_attempts=2, base_delay=1.0, max_delay=2.0)


@dataclass
class AppSettings:
    """界面那份配置读出来之后的样子。"""

    source_header: str = "english"
    sources: SourceList = field(default_factory=SourceList)
    char_budget: int = DEFAULT_CHAR_BUDGET
    timeout: float = DEFAULT_TIMEOUT
    ui_language: str = "en"


def _qsettings(settings=None):
    if settings is not None:
        return settings
    from PySide6.QtCore import QSettings
    return QSettings(ORGANIZATION_NAME, APPLICATION_NAME)


def load_app_settings(settings=None):
    """读界面那份配置（Windows 上是注册表 HKCU\\Software\\DayZTranslateTool\\DayZTranslateTool）。"""
    settings = _qsettings(settings)
    return AppSettings(
        source_header=str(settings.value("source_header", "english") or "english"),
        sources=SourceList.from_json(settings.value("translation_sources_json", "")),
        char_budget=int(settings.value("translation_char_budget", DEFAULT_CHAR_BUDGET)),
        timeout=float(settings.value("translation_timeout", DEFAULT_TIMEOUT)),
        ui_language=str(settings.value("ui_language", "en") or "en"),
    )


def save_sources(sources, settings=None):
    """只写 translation_sources_json 这一个键，别的键一个都不碰。"""
    settings = _qsettings(settings)
    settings.setValue("translation_sources_json", sources.to_json())
    settings.sync()


_CONFIG_DIR = None


def config_dir():
    """用户数据目录（wordbook.csv 就住这儿，`main.py` 的 `CONFIG_DIR` 也用它）。

    两件事很关键：
    1. **不能**先设 org/app 名再问 Qt，否则会多出 `DayZTranslateTool/DayZTranslateTool`
       一层，命令行就去读另一个文件了；
    2. 只算一次并缓存住 —— Qt 那个值会随 QApplication 建没建而变（建了之后
       applicationName 变成解释器名，路径上会多出 `/python` 一层），同一个进程里必须
       只用第一个算出来的值。

    注意：缓存只保证「本进程内不再变」，**不**保证「一定跟界面那个目录相同」。真正
    保证相同的是 `main.py` 也改成 `CONFIG_DIR = translation_flow.config_dir()`
    （Task 2 Step 3）—— 两边共用这一次计算。
    """
    global _CONFIG_DIR
    if _CONFIG_DIR is None:
        from PySide6.QtCore import QStandardPaths
        _CONFIG_DIR = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    return _CONFIG_DIR


def rule_for_mode(mode):
    """翻译模式 → 源列表勾选规则。"""
    if mode == MODE_ALL:
        return RULE_ALL
    if mode == MODE_EMPTY:
        return RULE_EMPTY
    return RULE_SELECTION


def build_test_jobs(source_header):
    """「测试这个源」用的固定样本：一个单词 × 四种语言。

    跟源列同语言的样本要跳过 —— 有的接口（MyMemory）直接拒绝「翻成同一种语言」，
    一条失败就把整个好用的源误判成坏的。
    """
    source_code = source_language_code_for_header(source_header)
    jobs = []
    for column, language in enumerate(TEST_LANGUAGES):
        code = language_code_for_header(language)
        if code and code != source_code:
            jobs.append((0, column, TEST_TEXT, code))
    return jobs


# —— 复制列 ——

def fill_copy_columns(headers, rows, overwrite=False, row_indexes=None):
    """把 original←english、chinese←chinesesimp 这些复制列填上。

    返回 `(新行列表, 有没有改动)`；输入 rows 不会被改。
    """
    filled = [list(row) for row in rows]
    changed = False
    targets = range(len(filled)) if row_indexes is None else sorted(row_indexes)
    for column_index, header in enumerate(headers):
        source_header = copy_source_for_header(header)
        if not source_header:
            continue
        try:
            source_column = header_index(headers, source_header)
        except ValueError:
            continue
        for row_index in targets:
            if row_index < 0 or row_index >= len(filled):
                continue
            row = filled[row_index]
            source_text = _text_at(row, source_column)
            if not source_text:
                continue
            existing = _text_at(row, column_index)
            if existing and not overwrite:
                continue
            if existing == source_text:
                continue
            _set_at(row, column_index, source_text)
            changed = True
    return filled, changed


# —— 挑任务 ——

def collect_jobs(headers, rows, source_header, mode=MODE_EMPTY, columns=None,
                 row_indexes=None, only_empty=False):
    """按模式挑出翻译任务：`[(行下标, 列下标, 原文, 目标语言码), ...]`。

    - `MODE_EMPTY`：整张表，但只翻目标格还空着的（就是界面上的「翻译空白单元格」）
    - `MODE_ALL`：整张表，已有译文的也重翻
    - `MODE_COLUMNS`：只翻 `columns` 里的列
    - `MODE_ROWS`：只翻 `row_indexes` 里的行

    `row_indexes` / `columns` 在四种模式下都再收窄一次范围：`None` = 没给（全都要），
    给了个空集合 = 一个都不要（返回空任务表）；`only_empty=True` 可以在任何模式下再叠
    一层「只翻空格」。
    """
    if mode not in ALL_MODES:
        raise ValueError(f"Unknown mode: {mode}")
    # 界面上「一行都没选中」时会传一个空集合进来（不是 None）—— 那时不能抛错：原行为是
    # 照样填复制列，然后由 run_translation_jobs 弹一句「没有可翻译的选中单元格」。
    # 所以这里只把 None 当成「参数没给」。
    if mode == MODE_ROWS and row_indexes is None:
        raise ValueError("--rows is required when --mode rows")
    if mode == MODE_COLUMNS and columns is None:
        raise ValueError("--columns is required when --mode columns")
    selected_rows = sorted(set(row_indexes)) if row_indexes is not None else range(len(rows))
    selected_columns = set(columns) if columns is not None else None
    if mode == MODE_COLUMNS:
        jobs = build_column_translation_jobs(headers, rows, source_header, selected_columns)
        if row_indexes is not None:
            wanted = set(selected_rows)
            jobs = [job for job in jobs if job[0] in wanted]
    else:
        jobs = build_row_translation_jobs(headers, rows, source_header, selected_rows,
                                          selected_columns)
    if mode == MODE_EMPTY or only_empty:
        jobs = [job for job in jobs if not _text_at(rows[job[0]], job[1])]
    return jobs


# —— 源配置 ——

def build_source_config(entry, char_budget=None, timeout=None, label=None, glossary=None,
                        glossary_source_key=""):
    """一条源 → 一份 TranslatorConfig。字段取值与界面上的 build_source_config 完全一致。"""
    from translator_service import TranslatorConfig

    if label is None:
        label = entry.name or entry.source_id
    budget = DEFAULT_CHAR_BUDGET if char_budget is None else int(char_budget)
    limit = DEFAULT_TIMEOUT if timeout is None else float(timeout)
    glossary = list(glossary or [])
    glossary_source_key = (glossary_source_key or "").strip().lower()
    if entry.is_ai:
        return TranslatorConfig(
            provider=entry.api_type or "openai",
            label=label,
            char_budget=budget,
            parallel_batches=max(1, int(entry.concurrency or 1)),
            min_interval=max(0.0, float(entry.interval or 0.0)),
            api_key=entry.api_key,
            model=entry.model,
            base_url=entry.base_url,
            timeout=limit,
            glossary=glossary,
            glossary_source_key=glossary_source_key,
        )
    spec = FREE_SOURCE_SPECS.get(entry.source_id, {})
    return TranslatorConfig(
        provider=entry.source_id,
        label=label,
        char_budget=budget,
        parallel_batches=max(1, int(spec.get("concurrency", 1) or 1)),
        min_interval=max(0.0, float(spec.get("interval", 0.0) or 0.0)),
        api_key=entry.api_key,
        timeout=limit,
        glossary=glossary,
        glossary_source_key=glossary_source_key,
    )


def build_translation_configs(sources, rule, char_budget=None, timeout=None, glossary=None,
                              glossary_source_key="", source_id=None, label_for=None):
    """按勾选规则挑源 → 一串 config。`source_id` 非空时只留这一条（本次命令临时覆盖）。"""
    entries = sources.candidates(rule)
    if source_id:
        known = sources.find(source_id)
        if known is None:
            raise ValueError(f"Unknown source id: {source_id}")
        entries = [entry for entry in entries if entry.source_id == source_id]
    return [
        build_source_config(
            entry, char_budget=char_budget, timeout=timeout,
            label=(label_for(entry) if label_for else None),
            glossary=glossary, glossary_source_key=glossary_source_key,
        )
        for entry in entries
    ]


# —— 跑翻译 ——

def build_service(cache=None, retry_policy=None):
    service = TranslationService(cache=cache if cache is not None else {})
    if retry_policy is not None:
        service.retry_policy = retry_policy
    return service


def run_translation(raw_jobs, configs, source_header, cache=None, progress_callback=None,
                    should_cancel=None, on_fallback=None, retry_policy=None):
    """把 `collect_jobs()` 的输出交给 TranslationService（主备降级在 service 里）。"""
    jobs = [
        TranslationJob(row, column, text, source_language_code_for_header(source_header), target)
        for row, column, text, target in raw_jobs
    ]
    service = build_service(cache=cache, retry_policy=retry_policy)
    return service.translate_jobs_with_fallback(
        jobs, configs, progress_callback=progress_callback,
        should_cancel=should_cancel, on_fallback=on_fallback,
    )


def apply_results(headers, rows, results):
    """把 `results.cell_results` 写回行数据；越界的格子丢掉。"""
    updated = [list(row) for row in rows]
    for (row_index, column_index), text in results.cell_results.items():
        if row_index < 0 or row_index >= len(updated):
            continue
        _set_at(updated[row_index], column_index, text)
    return updated


def failed_cells(raw_jobs, results):
    """没拿到译文的格子，保持输入顺序。"""
    return [(row, column) for row, column, _text, _target in raw_jobs
            if (row, column) not in results.cell_results]


# —— 术语表 ——

def build_glossary(wordbook_rows):
    """词表行 → 术语表；至少两列有值才算一条（跟界面上的 wordbook_glossary 一致）。"""
    from wordbook_csv import WORDBOOK_HEADERS

    glossary = []
    for row in wordbook_rows:
        item = {}
        for column_index, value in enumerate(row):
            value = (value or "").strip()
            if value and column_index < len(WORDBOOK_HEADERS):
                item[WORDBOOK_HEADERS[column_index]] = value
        if len(item) >= 2:
            glossary.append(item)
    return glossary


# —— 小工具 ——

def _text_at(row, column_index):
    if column_index < 0 or column_index >= len(row):
        return ""
    return (row[column_index] or "").strip()


def _set_at(row, column_index, text):
    if column_index < 0:
        return
    while len(row) <= column_index:
        row.append("")
    row[column_index] = text
