import re
from pathlib import Path


KEY_PATTERN = re.compile(r"[$#]([A-Za-z][A-Za-z0-9_.:-]*)")
TEXT_SUFFIXES = {
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".json",
    ".xml",
    ".txt",
    ".layout",
    ".config",
    ".cfg",
    ".csv",
}


def scan_translation_keys(path: Path) -> list[str]:
    root = Path(path)
    files = [root] if root.is_file() else _iter_text_files(root)
    found: list[str] = []
    seen: set[str] = set()
    for file_path in files:
        for key in _scan_file(file_path):
            if key not in seen:
                seen.add(key)
                found.append(key)
    return found


def _iter_text_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES]


def _scan_file(path: Path) -> list[str]:
    if path.suffix.lower() and path.suffix.lower() not in TEXT_SUFFIXES:
        return []
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if b"\x00" in data:
        return []
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1251")
        except UnicodeDecodeError:
            return []
    return KEY_PATTERN.findall(text)
