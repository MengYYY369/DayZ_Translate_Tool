import re
from pathlib import Path


KEY_PATTERN = re.compile(r"[$#]([A-Za-z][A-Za-z0-9_.:-]*)")
TEXT_SUFFIXES = {
    ".c",
    ".cpp",
    ".layout",
}


def scan_translation_keys(path: Path, key_prefixes=None) -> list[str]:
    root = Path(path)
    files = [root] if root.is_file() else _iter_text_files(root)
    prefixes = _normalize_key_prefixes(key_prefixes)
    found: list[str] = []
    seen: set[str] = set()
    for file_path in files:
        for key in _scan_file(file_path, prefixes):
            if key not in seen:
                seen.add(key)
                found.append(key)
    return found


def _iter_text_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES)


def _normalize_key_prefixes(key_prefixes) -> list[str]:
    if not key_prefixes:
        return []
    if isinstance(key_prefixes, str):
        return [item for item in re.split(r"[,;\s]+", key_prefixes.strip()) if item]
    return [str(item).strip() for item in key_prefixes if str(item).strip()]


def _scan_file(path: Path, key_prefixes: list[str]) -> list[str]:
    if path.suffix.lower() not in TEXT_SUFFIXES:
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
    keys = KEY_PATTERN.findall(text)
    if not key_prefixes:
        return keys
    return [key for key in keys if any(key.startswith(prefix) for prefix in key_prefixes)]
