import csv
from pathlib import Path


DAYZ_HEADERS = [
    "Language",
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
    "",
]

LANGUAGE_CODES = {
    "original": "auto",
    "english": "en",
    "czech": "cs",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
    "polish": "pl",
    "hungarian": "hu",
    "russian": "ru",
    "german": "de",
    "chinese": "zh-CN",
    "chinesesimp": "zh-CN",
    "japanese": "ja",
    "portuguese": "pt",
}


def load_dayz_csv(path):
    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))

    if not rows:
        raise ValueError("CSV file is empty.")

    column_map, warnings = _build_header_map(rows[0])

    return list(DAYZ_HEADERS), [_expand_row(row, column_map) for row in rows[1:]], warnings


def write_dayz_csv(path, headers, rows):
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        handle.write(_format_dayz_csv_row(DAYZ_HEADERS))
        for row in rows:
            handle.write(_format_dayz_csv_row(_normalize_row(row)))


def language_code_for_header(header):
    return LANGUAGE_CODES.get((header or "").strip().lower())


def source_language_code_for_header(header):
    return language_code_for_header(header) or "auto"


def header_index(headers, header):
    normalized = (header or "").strip().lower()
    for index, value in enumerate(headers):
        if (value or "").strip().lower() == normalized:
            return index
    raise ValueError(f'Source language column "{header}" was not found.')


def build_row_translation_jobs(headers, rows, source_header, selected_rows, selected_columns=None):
    source_index = header_index(headers, source_header)
    target_columns = _target_columns_for_rows(headers, source_index, selected_columns)
    jobs = []

    for row_index in sorted(selected_rows):
        if row_index < 0 or row_index >= len(rows):
            continue
        source_text = _cell_text(rows[row_index], source_index)
        if not source_text:
            continue
        for column_index in target_columns:
            target_code = language_code_for_header(headers[column_index])
            if target_code:
                jobs.append((row_index, column_index, source_text, target_code))

    return jobs


def build_column_translation_jobs(headers, rows, source_header, selected_columns):
    source_index = header_index(headers, source_header)
    target_columns = _target_columns_for_columns(headers, source_index, selected_columns)
    jobs = []

    for row_index, row in enumerate(rows):
        source_text = _cell_text(row, source_index)
        if not source_text:
            continue
        for column_index in target_columns:
            target_code = language_code_for_header(headers[column_index])
            if target_code:
                jobs.append((row_index, column_index, source_text, target_code))

    return jobs


def _target_columns_for_rows(headers, source_index, selected_columns):
    if selected_columns:
        candidates = sorted(selected_columns)
    else:
        candidates = range(len(headers))
    return [index for index in candidates if _is_translatable_target(headers, source_index, index)]


def _target_columns_for_columns(headers, source_index, selected_columns):
    return [index for index in sorted(selected_columns) if _is_translatable_target(headers, source_index, index)]


def _is_translatable_target(headers, source_index, index):
    if index < 0 or index >= len(headers):
        return False
    if index == source_index:
        return False
    if index == 0:
        return False
    if (headers[index] or "").strip().lower() == "original":
        return False
    return bool(language_code_for_header(headers[index]))


def _cell_text(row, index):
    if index < 0 or index >= len(row):
        return ""
    return (row[index] or "").strip()


def _normalize_row(row):
    normalized = list(row[: len(DAYZ_HEADERS)])
    if len(normalized) < len(DAYZ_HEADERS):
        normalized.extend([""] * (len(DAYZ_HEADERS) - len(normalized)))
    return normalized


def _build_header_map(headers):
    fixed_indexes = {header: index for index, header in enumerate(DAYZ_HEADERS)}
    column_map = []
    warnings = []
    known_count = 0

    for source_index, header in enumerate(headers or []):
        if header == "" and source_index == len(headers) - 1:
            # Trailing empty DayZ column is optional; alone it does not validate a file.
            column_map.append((source_index, len(DAYZ_HEADERS) - 1))
            continue
        if header in fixed_indexes:
            column_map.append((source_index, fixed_indexes[header]))
            known_count += 1
            continue
        warnings.append(f'Skipped unsupported DayZ language column "{header}".')

    if known_count == 0:
        raise ValueError("No supported DayZ stringtable columns were found.")

    return column_map, warnings


def _expand_row(row, column_map):
    expanded = [""] * len(DAYZ_HEADERS)
    for source_index, target_index in column_map:
        if source_index < len(row):
            expanded[target_index] = row[source_index]
    return expanded


def _format_dayz_csv_row(row):
    normalized = _normalize_row(row)
    cells = [_quote_csv_cell(cell) for cell in normalized[:-1]]
    cells.append("")
    return ",".join(cells) + "\n"


def _quote_csv_cell(value):
    return '"' + str(value).replace('"', '""') + '"'
