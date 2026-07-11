import re
from pathlib import Path

from dayz_csv import DAYZ_HEADERS

_KEY_IN_STRING = re.compile(r"[$#]([A-Za-z_][A-Za-z0-9_]*)")


def read_text(path):
    path = Path(path)
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _quoted_string_contents(text):
    contents = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            quote = ch
            i += 1
            buf = []
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if c == quote:
                    i += 1
                    break
                buf.append(c)
                i += 1
            contents.append("".join(buf))
            continue
        i += 1
    return contents


def extract_stringtable_keys_from_text(text):
    seen = set()
    ordered = []
    for content in _quoted_string_contents(text or ""):
        for match in _KEY_IN_STRING.finditer(content):
            key = match.group(1).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(key)
    return ordered


def extract_stringtable_keys_from_file(path):
    return extract_stringtable_keys_from_text(read_text(path))


def collect_config_cpp_files(folder):
    root = Path(folder)
    files = [p for p in root.rglob("*") if p.is_file() and p.name.lower() == "config.cpp"]
    return sorted(files, key=lambda p: str(p).lower())


def extract_keys_from_paths(paths):
    seen = set()
    ordered = []
    warnings = []
    for path in sorted((Path(p) for p in paths), key=lambda p: str(p).lower()):
        try:
            keys = extract_stringtable_keys_from_file(path)
        except OSError as exc:
            warnings.append(f"{path}: {exc}")
            continue
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            ordered.append(key)
    return ordered, warnings


def merge_language_keys(existing_rows, keys):
    width = len(DAYZ_HEADERS)
    merged = [list(row[:width]) + [""] * max(0, width - len(row)) for row in existing_rows]
    existing_keys = set()
    for row in merged:
        key = (row[0] if row else "").strip()
        if key:
            existing_keys.add(key)

    added = 0
    skipped = 0
    for key in keys:
        key = (key or "").strip()
        if not key:
            continue
        if key in existing_keys:
            skipped += 1
            continue
        new_row = [key] + [""] * (width - 1)
        merged.append(new_row)
        existing_keys.add(key)
        added += 1
    return merged, added, skipped
