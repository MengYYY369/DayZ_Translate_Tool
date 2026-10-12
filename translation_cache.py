"""翻译缓存的磁盘持久化：软件目录旁一个 JSON 文件，写不进去就回退到用户数据目录。"""
import json
import os
import sys
from pathlib import Path

FILENAME = "translation_cache.json"
FORMAT_VERSION = 1


class TranslationCacheStore:
    def __init__(self, base_dir=None, fallback_dir=None):
        self.base_dir = Path(base_dir) if base_dir else self._default_base_dir()
        self.fallback_dir = Path(fallback_dir) if fallback_dir else self._default_fallback_dir()
        self.path = self._resolve_path()

    @staticmethod
    def _default_base_dir():
        # 打包后 sys.executable 是 exe；开发时 __file__ 是仓库根
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent
        return Path(__file__).resolve().parent

    @staticmethod
    def _default_fallback_dir():
        if sys.platform == "win32":
            root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            if root:
                return Path(root) / "DayZ_Translate_Tool"
        return Path.home() / ".local" / "share" / "DayZ_Translate_Tool"

    def _resolve_path(self):
        for directory in (self.base_dir, self.fallback_dir):
            try:
                directory.mkdir(parents=True, exist_ok=True)
                probe = directory / f".{FILENAME}.probe"
                probe.write_text("", encoding="utf-8")
                probe.unlink()
                return directory / FILENAME
            except OSError:
                continue
        return self.fallback_dir / FILENAME

    def is_writable(self):
        return self.path.parent.exists() and os.access(self.path.parent, os.W_OK)

    def load(self):
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        if not isinstance(payload, dict) or payload.get("version") != FORMAT_VERSION:
            return {}
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return {}
        cache = {}
        for row in entries:
            if not isinstance(row, list) or len(row) != 6:
                continue
            key = tuple(str(part) for part in row[:5])
            value = row[5]
            if isinstance(value, str):
                cache[key] = value
        return cache

    def save(self, cache):
        entries = [list(key) + [value] for key, value in cache.items()]
        payload = {"version": FORMAT_VERSION, "entries": entries}
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass

    def clear(self):
        try:
            self.path.unlink()
        except OSError:
            pass
