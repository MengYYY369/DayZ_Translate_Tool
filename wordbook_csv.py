import csv
from pathlib import Path


WORDBOOK_HEADERS = [
    "original",
    "english",
    "czech",
    "german",
    "russian",
    "polish",
    "hungarian",
    "italian",
    "spanish",
    "french",
    "chinese",
    "japanese",
    "portuguese",
    "chinesesimp",
]


def load_wordbook_csv(path):
    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))

    if not rows:
        return list(WORDBOOK_HEADERS), []

    column_map = _build_header_map(rows[0])
    return list(WORDBOOK_HEADERS), [_expand_row(row, column_map) for row in rows[1:]]


def write_wordbook_csv(path, rows):
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        handle.write(_format_wordbook_row(WORDBOOK_HEADERS))
        for row in wordbook_rows_for_save(rows):
            handle.write(_format_wordbook_row(_normalize_row(row)))


def wordbook_rows_for_save(rows):
    normalized = [_normalize_row(row) for row in rows]
    while normalized and _is_empty_row(normalized[-1]):
        normalized.pop()
    return normalized


def _build_header_map(headers):
    fixed_indexes = {header: index for index, header in enumerate(WORDBOOK_HEADERS)}
    column_map = []
    for source_index, header in enumerate(headers):
        if header not in fixed_indexes:
            raise ValueError(f'Unsupported wordbook language column "{header}".')
        column_map.append((source_index, fixed_indexes[header]))
    return column_map


def _expand_row(row, column_map):
    expanded = [""] * len(WORDBOOK_HEADERS)
    for source_index, target_index in column_map:
        if source_index < len(row):
            expanded[target_index] = row[source_index]
    return expanded


def _normalize_row(row):
    normalized = list(row[: len(WORDBOOK_HEADERS)])
    if len(normalized) < len(WORDBOOK_HEADERS):
        normalized.extend([""] * (len(WORDBOOK_HEADERS) - len(normalized)))
    return normalized


def _is_empty_row(row):
    return not any((cell or "").strip() for cell in row)


def _format_wordbook_row(row):
    return ",".join(_quote_csv_cell(cell) for cell in _normalize_row(row)) + "\n"


def _quote_csv_cell(value):
    return '"' + str(value).replace('"', '""') + '"'
