import tempfile
import unittest
from pathlib import Path

from translation_cache import TranslationCacheStore


class TranslationCacheStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_then_load_roundtrip(self):
        store = TranslationCacheStore(base_dir=self.tmp, fallback_dir=self.tmp)
        cache = {("openai", "english", "chinese", "gpt-4o", "Knife"): "刀"}

        store.save(cache)
        loaded = TranslationCacheStore(base_dir=self.tmp, fallback_dir=self.tmp).load()

        self.assertEqual(loaded, cache)
        # 键必须是元组，不能变成 list（否则命中不了）
        key = next(iter(loaded))
        self.assertIsInstance(key, tuple)

    def test_load_missing_file_returns_empty(self):
        store = TranslationCacheStore(base_dir=self.tmp, fallback_dir=self.tmp)

        self.assertEqual(store.load(), {})

    def test_load_corrupt_file_returns_empty(self):
        store = TranslationCacheStore(base_dir=self.tmp, fallback_dir=self.tmp)
        store.path.write_text("{not json", encoding="utf-8")

        self.assertEqual(store.load(), {})

    def test_save_is_atomic(self):
        store = TranslationCacheStore(base_dir=self.tmp, fallback_dir=self.tmp)

        store.save({("a", "b", "c", "d", "e"): "f"})

        self.assertEqual(list(self.tmp.glob("*.tmp")), [])
        self.assertTrue(store.path.exists())

    def test_falls_back_when_base_dir_unwritable(self):
        # 用一个同名「文件」占住路径，使 mkdir 失败
        blocked = self.tmp / "blocked"
        blocked.write_text("", encoding="utf-8")
        fallback = self.tmp / "fallback"

        store = TranslationCacheStore(base_dir=blocked / "sub", fallback_dir=fallback)

        self.assertEqual(store.path.parent, fallback)
        store.save({("a", "b", "c", "d", "e"): "f"})
        self.assertEqual(store.load(), {("a", "b", "c", "d", "e"): "f"})

    def test_clear_removes_file(self):
        store = TranslationCacheStore(base_dir=self.tmp, fallback_dir=self.tmp)
        store.save({("a", "b", "c", "d", "e"): "f"})

        store.clear()

        self.assertFalse(store.path.exists())
        self.assertEqual(store.load(), {})

    def test_is_writable_true_for_temp_dir(self):
        store = TranslationCacheStore(base_dir=self.tmp, fallback_dir=self.tmp)

        self.assertTrue(store.is_writable())

    def test_entries_with_wrong_shape_are_skipped(self):
        store = TranslationCacheStore(base_dir=self.tmp, fallback_dir=self.tmp)
        store.path.write_text(
            '{"version": 1, "entries": [["a", "b", "c", "d", "e"], ["only", "four"], "notalist"]}',
            encoding="utf-8",
        )

        self.assertEqual(store.load(), {})

    def test_version_mismatch_returns_empty(self):
        store = TranslationCacheStore(base_dir=self.tmp, fallback_dir=self.tmp)
        store.path.write_text(
            '{"version": 99, "entries": [["a", "b", "c", "d", "e", "f"]]}',
            encoding="utf-8",
        )

        self.assertEqual(store.load(), {})


if __name__ == "__main__":
    unittest.main()
