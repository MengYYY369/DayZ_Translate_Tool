"""翻译质量检查：纯本地规则，不联网、不写盘。

检查只负责找出「可疑的格子」，不修改表格内容，也不写回 csv。
每条规则都有独立的键名，界面上的设置窗口按这些键逐条开关。
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import defaultdict
from itertools import combinations
from typing import NamedTuple

from dayz_csv import is_copy_only_column, language_code_for_header

# —— 规则清单 ——
# 键名同时用作界面文案的翻译键后缀（quality_rule_<键名>）。

RULE_GROUPS = (
    ("qc_group_format", (
        "placeholder_missing",
        "placeholder_extra",
        "placeholder_order",
        "line_breaks",
        "rich_tags",
        "color_markup",
        "numbers",
        "brackets",
        "spaces",
        "invisible_chars",
        "csv_unsafe",
        "empty_translation",
    )),
    ("qc_group_language", (
        "script_missing",
        "script_unexpected",
        "copied_source",
        "punctuation",
        "fullwidth",
    )),
    ("qc_group_similarity", (
        "row_similarity",
        "column_duplicate",
        "inconsistent_target",
        "duplicate_target",
    )),
    ("qc_group_model", (
        "prompt_leak",
        "length_ratio",
        "untranslated_sentence",
        "garbage",
        "parenthetical_notes",
    )),
    ("qc_group_glossary", (
        "glossary_missing",
    )),
)

DEFAULT_SIMILARITY = 0.85
# 空译文更像「没翻完」而不是「翻错了」，默认不勾。
DEFAULT_DISABLED_RULES = frozenset({"empty_translation"})

MIN_SIMILARITY_LENGTH = 8
MIN_SIMILARITY_LETTERS = 4
MIN_SCRIPT_LETTERS = 6
MIN_COLUMN_PAIRS = 5
COLUMN_DUPLICATE_RATIO = 0.8
MIN_REPEAT_SOURCE_LENGTH = 4
MIN_REPEAT_TARGET_LENGTH = 12
LONG_TRANSLATION_FLOOR = 40
LONG_TRANSLATION_FACTOR = 5
SHORT_SOURCE_LENGTH = 20
SHORT_TRANSLATION_LIMIT = 2

# 列头名 → 该语言必须出现的字符集
SCRIPT_PATTERNS = {
    "cyrillic": re.compile(r"[\u0400-\u04ff\u0500-\u052f]"),
    "han": re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"),
    "kana": re.compile(r"[\u3040-\u30ff]"),
    "hangul": re.compile(r"[\u1100-\u11ff\uac00-\ud7af]"),
    "greek": re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]"),
    "arabic": re.compile(r"[\u0600-\u06ff\u0750-\u077f]"),
    "hebrew": re.compile(r"[\u0590-\u05ff]"),
    "thai": re.compile(r"[\u0e00-\u0e7f]"),
}

REQUIRED_SCRIPTS = {
    "russian": ("cyrillic",),
    "chinese": ("han",),
    "chinesesimp": ("han",),
    "japanese": ("kana", "han"),
    "korean": ("hangul",),
    "greek": ("greek",),
    "arabic": ("arabic",),
    "hebrew": ("hebrew",),
    "thai": ("thai",),
}

# 拉丁字母列里出现这些文字就很可疑；反过来中日韩列里出现拉丁字母是正常的。
FOREIGN_SCRIPTS = ("han", "kana", "hangul", "cyrillic")
CJK_HEADERS = frozenset({"chinese", "chinesesimp", "japanese"})

# 同一语族的语言本来就长得很像（西/葡/意/法、捷/波/俄），互相像不算「偷懒照抄」。
LANGUAGE_FAMILIES = {
    "czech": "slavic",
    "polish": "slavic",
    "russian": "slavic",
    "spanish": "romance",
    "portuguese": "romance",
    "italian": "romance",
    "french": "romance",
}

PLACEHOLDER_RE = re.compile(r"%(\d+)")
NUMBER_RE = re.compile(r"\d+")
TAG_RE = re.compile(r"</?\s*([A-Za-z][A-Za-z0-9]*)[^<>]*>")
COLOR_RE = re.compile(r"#\([^)]*\)")
INVISIBLE_RE = re.compile(r"[\u00a0\u200b-\u200f\u2028\u2029\u202f\u2060\u3000\ufeff]")
REAL_CONTROL_RE = re.compile(r"[\n\r\t]")
HTML_ENTITY_RE = re.compile(r"&(?:[a-zA-Z]{2,10}|#\d{2,6});")
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27bf\u2b00-\u2bff\ufe0f]")
REPLACEMENT_RE = re.compile(r"[\ufffd\u25a1]")
LATIN_RUN_RE = re.compile(r"(?:[A-Za-z][A-Za-z'\-]{2,}\s+){2,}[A-Za-z][A-Za-z'\-]{2,}")
PAREN_NOTE_RE = re.compile(r"[（(]([^（()）]{6,})[)）]")
CJK_HALF_PUNCT_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff][,.](?![0-9])")
FULLWIDTH_PUNCT_RE = re.compile(r"[\uff0c\u3002\uff01\uff1f\uff1a\uff1b\uff08\uff09\u201c\u201d]")

# 只留高信号的模型痕迹：太宽会把正常英文句子误判成废话。
PROMPT_LEAK_PATTERNS = (
    "```",
    "here is the translation",
    "here's the translation",
    "here is your translation",
    "sure, here",
    "as an ai",
    "as a language model",
    "i'm sorry, but",
    "抱歉",
    "无法翻译",
    "翻译如下",
    "以下是翻译",
    "译文：",
    "译文:",
    "翻译：",
    "翻译:",
)


def all_rules():
    """按界面顺序返回全部规则键。"""
    return tuple(rule for _group, rules in RULE_GROUPS for rule in rules)


def default_enabled_rules():
    return tuple(rule for rule in all_rules() if rule not in DEFAULT_DISABLED_RULES)


def clamp_similarity(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SIMILARITY
    return min(max(number, 0.5), 1.0)


class QualityCheckConfig:
    """检查项开关 + 相似率门槛。"""

    def __init__(self, enabled=None, similarity=DEFAULT_SIMILARITY):
        self.enabled = set(default_enabled_rules() if enabled is None else enabled)
        self.similarity = clamp_similarity(similarity)

    def is_enabled(self, rule):
        return rule in self.enabled

    def to_json(self):
        return {"rules": sorted(self.enabled), "similarity": self.similarity}

    @classmethod
    def from_json(cls, raw):
        if not isinstance(raw, dict):
            return cls()
        rules = raw.get("rules")
        enabled = set(rules) if isinstance(rules, list) else None
        return cls(enabled=enabled, similarity=raw.get("similarity", DEFAULT_SIMILARITY))


class _Cell(NamedTuple):
    row: int
    column: int
    header: str
    source: str
    text: str


def source_header_index(headers, source_header):
    wanted = (source_header or "").strip().lower()
    for index, header in enumerate(headers):
        if (header or "").strip().lower() == wanted:
            return index
    return -1


def target_columns(headers, source_header):
    """需要检查的列：语言列去掉源语言列。

    original / chinese 是照抄列，没有自己的语言码，天然被排除。
    """
    source_index = source_header_index(headers, source_header)
    columns = []
    for index, header in enumerate(headers):
        if index == 0 or index == source_index:
            continue
        if not header or is_copy_only_column(header):
            continue
        if not language_code_for_header(header):
            continue
        columns.append(index)
    return columns


def check_table(headers, rows, source_header, config=None, glossary=None, progress=None, should_cancel=None):
    """检查整张表，返回 {(行, 列): (规则键, ...)}，只包含有问题的格子。

    progress(已查完的规则数, 规则总数) 每查完一条规则回调一次；
    should_cancel() 返回 True 时提前收工，已查出的结果照常返回。
    """
    config = config or QualityCheckConfig()
    glossary = list(glossary or [])
    if progress is None:
        progress = _no_progress
    if should_cancel is None:
        should_cancel = _never_cancel

    source_index = source_header_index(headers, source_header)
    columns = target_columns(headers, source_header)
    cells = []
    for row_index, row in enumerate(rows):
        source = _raw_at(row, source_index).strip()
        for column_index in columns:
            cells.append(_Cell(row_index, column_index, headers[column_index], source, _raw_at(row, column_index)))

    findings = {}

    def flag(cell, rule):
        key = (cell.row, cell.column)
        bucket = findings.get(key)
        if bucket is None:
            findings[key] = [rule]
        elif rule not in bucket:
            bucket.append(rule)

    total = len(FINDERS)
    for index, (rule, finder) in enumerate(FINDERS, start=1):
        if config.is_enabled(rule):
            for cell in finder(cells, config, glossary):
                flag(cell, rule)
        progress(index, total)
        if should_cancel():
            break

    return {key: tuple(rules) for key, rules in findings.items()}


def _no_progress(_done, _total):
    return None


def _never_cancel():
    return False


def _raw_at(row, index):
    if index < 0 or index >= len(row):
        return ""
    return row[index] or ""


def _normalized(text):
    return " ".join(text.split()).casefold()


def _letter_count(text):
    return sum(1 for char in text if char.isalpha())


def _similarity(left, right):
    return difflib.SequenceMatcher(None, _normalized(left), _normalized(right)).ratio()


def _skeleton(text):
    """去掉重音符号后的样子：用来区分「只是带不带重音」和真正的不同译法。"""
    decomposed = unicodedata.normalize("NFKD", _normalized(text))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _plain(text):
    """再去掉空格和标点：只比字母数字。"""
    return "".join(char for char in _skeleton(text) if char.isalnum())


def _comparable(left, right):
    if len(left.strip()) < MIN_SIMILARITY_LENGTH or len(right.strip()) < MIN_SIMILARITY_LENGTH:
        return False
    return _letter_count(left) >= MIN_SIMILARITY_LETTERS and _letter_count(right) >= MIN_SIMILARITY_LETTERS


def _same_language_pair(left_header, right_header):
    """chinese 与 chinesesimp 是同一个语言码，内容一样不算问题。"""
    left_code = language_code_for_header(left_header)
    right_code = language_code_for_header(right_header)
    return bool(left_code) and left_code == right_code


def _same_family_pair(left_header, right_header):
    left = LANGUAGE_FAMILIES.get((left_header or "").lower())
    right = LANGUAGE_FAMILIES.get((right_header or "").lower())
    return bool(left) and left == right


def _placeholders(text):
    return PLACEHOLDER_RE.findall(text)


def _is_passthrough(cell):
    """译文就是原文（可能只差大小写、重音、空格）：专有名词照抄，用户认为这是正常的。"""
    return bool(_plain(cell.text)) and _plain(cell.text) == _plain(cell.source)


def _by_row(cells):
    grouped = defaultdict(list)
    for cell in cells:
        grouped[cell.row].append(cell)
    return grouped


def _by_column(cells):
    grouped = defaultdict(list)
    for cell in cells:
        grouped[cell.column].append(cell)
    return grouped


# —— 格式类 ——


def _find_placeholder_missing(cells, config, glossary):
    for cell in cells:
        if cell.text and set(_placeholders(cell.source)) - set(_placeholders(cell.text)):
            yield cell


def _find_placeholder_extra(cells, config, glossary):
    for cell in cells:
        if cell.text and set(_placeholders(cell.text)) - set(_placeholders(cell.source)):
            yield cell


def _find_placeholder_order(cells, config, glossary):
    for cell in cells:
        if not cell.text:
            continue
        source_parts = _placeholders(cell.source)
        text_parts = _placeholders(cell.text)
        if source_parts != text_parts and sorted(source_parts) == sorted(text_parts):
            yield cell


def _find_line_breaks(cells, config, glossary):
    for cell in cells:
        if not cell.text:
            continue
        if cell.source.count("\\n") != cell.text.count("\\n") or cell.source.count("\\t") != cell.text.count("\\t"):
            yield cell


def _find_rich_tags(cells, config, glossary):
    for cell in cells:
        if not cell.text:
            continue
        source_tags = sorted(tag.lower() for tag in TAG_RE.findall(cell.source))
        text_tags = sorted(tag.lower() for tag in TAG_RE.findall(cell.text))
        if source_tags != text_tags:
            yield cell


def _find_color_markup(cells, config, glossary):
    for cell in cells:
        if cell.text and len(COLOR_RE.findall(cell.source)) != len(COLOR_RE.findall(cell.text)):
            yield cell


def _find_numbers(cells, config, glossary):
    for cell in cells:
        if not cell.text:
            continue
        source_numbers = sorted(NUMBER_RE.findall(PLACEHOLDER_RE.sub("", cell.source)))
        text_numbers = sorted(NUMBER_RE.findall(PLACEHOLDER_RE.sub("", cell.text)))
        if source_numbers != text_numbers:
            yield cell


def _find_brackets(cells, config, glossary):
    for cell in cells:
        if not cell.text:
            continue
        text = cell.text
        if (text.count("(") != text.count(")") or text.count("[") != text.count("]")
                or text.count("{") != text.count("}") or text.count("（") != text.count("）")):
            yield cell
            continue
        for opening in ("(", "[", "{"):
            if cell.source.count(opening) and not text.count(opening):
                yield cell
                break


def _find_spaces(cells, config, glossary):
    for cell in cells:
        if not cell.text:
            continue
        if cell.text != cell.text.strip():
            yield cell
        elif "  " in cell.text.strip() and "  " not in cell.source.strip():
            yield cell


def _find_invisible_chars(cells, config, glossary):
    for cell in cells:
        if cell.text and INVISIBLE_RE.search(cell.text):
            yield cell


def _find_csv_unsafe(cells, config, glossary):
    for cell in cells:
        if cell.text and REAL_CONTROL_RE.search(cell.text):
            yield cell


def _find_empty_translation(cells, config, glossary):
    for cell in cells:
        if cell.source.strip() and not cell.text.strip():
            yield cell


# —— 语言类 ——


def _find_script_missing(cells, config, glossary):
    for cell in cells:
        if not cell.text:
            continue
        # 专有名词原样照抄不算「字符集不对」
        if _is_passthrough(cell):
            continue
        required = REQUIRED_SCRIPTS.get(cell.header.lower())
        if not required or _letter_count(cell.text) < MIN_SCRIPT_LETTERS:
            continue
        if not any(SCRIPT_PATTERNS[name].search(cell.text) for name in required):
            yield cell


def _find_script_unexpected(cells, config, glossary):
    for cell in cells:
        header = cell.header.lower()
        if header in REQUIRED_SCRIPTS or not cell.text:
            continue
        if _letter_count(cell.text) < MIN_SCRIPT_LETTERS:
            continue
        if any(SCRIPT_PATTERNS[name].search(cell.text) for name in FOREIGN_SCRIPTS):
            yield cell


def _find_copied_source(cells, config, glossary):
    for cell in cells:
        source = cell.source.strip()
        if len(source) < MIN_SIMILARITY_LENGTH or " " not in source:
            continue
        if cell.text.strip().casefold() == source.casefold():
            yield cell


def _find_punctuation(cells, config, glossary):
    for cell in cells:
        if not cell.text or cell.header.lower() not in CJK_HEADERS:
            continue
        if CJK_HALF_PUNCT_RE.search(cell.text):
            yield cell


def _find_fullwidth(cells, config, glossary):
    for cell in cells:
        header = cell.header.lower()
        if not cell.text or header in REQUIRED_SCRIPTS:
            continue
        if FULLWIDTH_PUNCT_RE.search(cell.text):
            yield cell


# —— 相似度与一致性 ——


def _find_row_similarity(cells, config, glossary):
    """同一行两种语言的译文几乎一模一样。

    光看相似率会把西语/葡语/意语、捷克语/波兰语这类真正译对了的近亲语言误判，
    所以额外要求「去掉重音后完全一样」：这正好是模型偷懒照抄的情形。
    单个词的专有名词（Hurrikan / Gramofon 这种各国写法本来就一样）不判，只查整句；
    同一语族之间（西/葡、捷/波）本来就像，也不判。
    """
    for row_cells in _by_row(cells).values():
        for left, right in combinations(row_cells, 2):
            if _same_language_pair(left.header, right.header) or _same_family_pair(left.header, right.header):
                continue
            if _is_passthrough(left) or _is_passthrough(right):
                continue
            if " " not in left.text.strip() or " " not in right.text.strip():
                continue
            if not _comparable(left.text, right.text):
                continue
            if _skeleton(left.text) != _skeleton(right.text):
                continue
            if _similarity(left.text, right.text) >= config.similarity:
                yield left
                yield right


def _find_column_duplicate(cells, config, glossary):
    by_column = _by_column(cells)
    for left_column, right_column in combinations(sorted(by_column), 2):
        left_cells = {cell.row: cell for cell in by_column[left_column]}
        right_cells = {cell.row: cell for cell in by_column[right_column]}
        left_header = by_column[left_column][0].header
        right_header = by_column[right_column][0].header
        if _same_language_pair(left_header, right_header):
            continue
        compared = 0
        same = []
        for row_index, left in left_cells.items():
            right = right_cells.get(row_index)
            if right is None or not _comparable(left.text, right.text):
                continue
            if _is_passthrough(left) or _is_passthrough(right):
                continue
            compared += 1
            if _normalized(left.text) == _normalized(right.text):
                same.append((left, right))
        if compared >= MIN_COLUMN_PAIRS and len(same) / compared >= COLUMN_DUPLICATE_RATIO:
            for left, right in same:
                yield left
                yield right


def _find_inconsistent_target(cells, config, glossary):
    groups = defaultdict(list)
    for cell in cells:
        source = _normalized(cell.source)
        if len(source) < MIN_REPEAT_SOURCE_LENGTH or not cell.text.strip():
            continue
        groups[(cell.column, source)].append(cell)
    for group in groups.values():
        if len(group) < 2:
            continue
        counts = defaultdict(int)
        for cell in group:
            counts[_normalized(cell.text)] += 1
        if len(counts) < 2:
            continue
        best = max(counts.values())
        winners = {value for value, count in counts.items() if count == best}
        for cell in group:
            if len(winners) > 1 or _normalized(cell.text) not in winners:
                yield cell


def _find_duplicate_target(cells, config, glossary):
    groups = defaultdict(list)
    for cell in cells:
        text = _normalized(cell.text)
        if len(text) < MIN_REPEAT_TARGET_LENGTH:
            continue
        groups[text].append(cell)
    for group in groups.values():
        if len(group) < 2:
            continue
        sources = sorted({_normalized(cell.source) for cell in group})
        if len(sources) < 2 or _max_pair_ratio(sources) >= 0.5:
            continue
        for cell in group:
            yield cell


def _max_pair_ratio(values):
    best = 0.0
    for left, right in combinations(values, 2):
        best = max(best, difflib.SequenceMatcher(None, left, right).ratio())
    return best


# —— 模型输出类 ——


def _find_prompt_leak(cells, config, glossary):
    for cell in cells:
        text = cell.text.strip()
        if not text:
            continue
        lowered = text.casefold()
        if any(pattern in lowered for pattern in PROMPT_LEAK_PATTERNS):
            yield cell
            continue
        if text[:1] in ("{", "[") and '"' in text:
            yield cell


def _find_length_ratio(cells, config, glossary):
    for cell in cells:
        source = cell.source.strip()
        text = cell.text.strip()
        if not source or not text:
            continue
        if len(text) > max(LONG_TRANSLATION_FLOOR, LONG_TRANSLATION_FACTOR * len(source)):
            yield cell
        elif len(source) >= SHORT_SOURCE_LENGTH and len(text) <= SHORT_TRANSLATION_LIMIT:
            yield cell


def _find_untranslated_sentence(cells, config, glossary):
    for cell in cells:
        if not cell.text or cell.header.lower() not in REQUIRED_SCRIPTS:
            continue
        if LATIN_RUN_RE.search(cell.text):
            yield cell


def _find_garbage(cells, config, glossary):
    for cell in cells:
        text = cell.text
        if not text:
            continue
        if REPLACEMENT_RE.search(text) or URL_RE.search(text) or HTML_ENTITY_RE.search(text) or EMOJI_RE.search(text):
            yield cell


def _find_parenthetical_notes(cells, config, glossary):
    for cell in cells:
        if not cell.text or "(" in cell.source or "（" in cell.source:
            continue
        if PAREN_NOTE_RE.search(cell.text):
            yield cell


# —— 术语表 ——


def _find_glossary_missing(cells, config, glossary):
    if not glossary:
        return
    for cell in cells:
        if not cell.text:
            continue
        header = cell.header.lower()
        lowered = cell.text.casefold()
        source_lowered = cell.source.casefold()
        for entry in glossary:
            source_term = (entry.get("english") or "").strip()
            expected = (entry.get(header) or "").strip()
            if not source_term or not expected:
                continue
            if source_term.casefold() not in source_lowered:
                continue
            if expected.casefold() not in lowered:
                yield cell
                break


FINDERS = (
    ("placeholder_missing", _find_placeholder_missing),
    ("placeholder_extra", _find_placeholder_extra),
    ("placeholder_order", _find_placeholder_order),
    ("line_breaks", _find_line_breaks),
    ("rich_tags", _find_rich_tags),
    ("color_markup", _find_color_markup),
    ("numbers", _find_numbers),
    ("brackets", _find_brackets),
    ("spaces", _find_spaces),
    ("invisible_chars", _find_invisible_chars),
    ("csv_unsafe", _find_csv_unsafe),
    ("empty_translation", _find_empty_translation),
    ("script_missing", _find_script_missing),
    ("script_unexpected", _find_script_unexpected),
    ("copied_source", _find_copied_source),
    ("punctuation", _find_punctuation),
    ("fullwidth", _find_fullwidth),
    ("row_similarity", _find_row_similarity),
    ("column_duplicate", _find_column_duplicate),
    ("inconsistent_target", _find_inconsistent_target),
    ("duplicate_target", _find_duplicate_target),
    ("prompt_leak", _find_prompt_leak),
    ("length_ratio", _find_length_ratio),
    ("untranslated_sentence", _find_untranslated_sentence),
    ("garbage", _find_garbage),
    ("parenthetical_notes", _find_parenthetical_notes),
    ("glossary_missing", _find_glossary_missing),
)
