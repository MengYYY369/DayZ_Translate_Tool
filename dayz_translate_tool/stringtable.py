import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable, Optional

from .ai import BatchTranslationResult, RateLimiter, TranslationRequest


class StringTable:
    def __init__(self, header: list[str], rows: list[list[str]], path: Optional[Path] = None, has_bom: bool = False):
        self.header = header
        self.rows = [self._normalize_row(row) for row in rows]
        self.path = path
        self.has_bom = has_bom

    @classmethod
    def load(cls, path: Path) -> "StringTable":
        data = path.read_bytes()
        has_bom = data.startswith(b"\xef\xbb\xbf")
        encoding = "utf-8-sig" if has_bom else "utf-8"
        with path.open("r", encoding=encoding, newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
        if not rows:
            raise ValueError("CSV 文件为空")
        header = rows[0]
        return cls(header, rows[1:], path=path, has_bom=has_bom)

    def save(self, path: Optional[Path] = None) -> None:
        target = path or self.path
        if target is None:
            raise ValueError("没有可保存的文件路径")
        encoding = "utf-8-sig" if self.has_bom else "utf-8"
        with target.open("w", encoding=encoding, newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
            writer.writerow(self.header)
            writer.writerows(self.rows)
        self.path = target

    def get_cell(self, row_index: int, column: str) -> str:
        return self.rows[row_index][self.column_index(column)]

    def set_cell(self, row_index: int, column: str, value: str) -> None:
        self.rows[row_index][self.column_index(column)] = value

    def column_index(self, column: str) -> int:
        try:
            return self.header.index(column)
        except ValueError as exc:
            raise KeyError(f"找不到列: {column}") from exc

    def language_columns(self) -> list[str]:
        return [column for column in self.header[1:] if column]

    def keys(self) -> set[str]:
        if not self.header:
            return set()
        return {row[0] for row in self.rows if row and row[0]}

    def add_key(self, key: str) -> bool:
        clean_key = key.strip()
        if not clean_key or clean_key in self.keys():
            return False
        row = [""] * len(self.header)
        row[0] = clean_key
        self.rows.append(row)
        return True

    def add_keys(self, keys: Iterable[str]) -> int:
        count = 0
        for key in keys:
            if self.add_key(key):
                count += 1
        return count

    def translate_rows(
        self,
        row_indices: Iterable[int],
        source_column: str,
        target_column: str,
        translator,
        autosave_every: int = 5,
        save_callback: Optional[Callable[["StringTable"], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> BatchTranslationResult:
        return self.translate_rows_multi(
            row_indices=row_indices,
            source_column=source_column,
            target_columns=[target_column],
            translator=translator,
            autosave_every=autosave_every,
            save_callback=save_callback,
            progress_callback=progress_callback,
            max_workers=1,
        )

    def translate_rows_multi(
        self,
        row_indices: Iterable[int],
        source_column: str,
        target_columns: Iterable[str],
        translator,
        autosave_every: int = 5,
        save_callback: Optional[Callable[["StringTable"], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        max_workers: int = 1,
        rate_limit_seconds: float = 0.0,
    ) -> BatchTranslationResult:
        translated = 0
        skipped = 0
        failed: list[tuple[int, str]] = []
        indices = list(row_indices)
        targets = [column for column in target_columns if column and column != source_column]
        jobs: list[tuple[int, str, TranslationRequest]] = []
        for row_index in indices:
            source_text = self.get_cell(row_index, source_column).strip()
            if not source_text:
                skipped += len(targets)
                continue
            for target_column in targets:
                request = TranslationRequest(
                    key=self.rows[row_index][0],
                    source_language=source_column,
                    source_text=source_text,
                    target_language=target_column,
                    current_target_text=self.get_cell(row_index, target_column).strip(),
                )
                jobs.append((row_index, target_column, request))
        completed = 0
        total = len(jobs)
        limiter = RateLimiter(rate_limit_seconds)

        def run_job(job: tuple[int, str, TranslationRequest]) -> tuple[int, str, str]:
            row_index, target_column, request = job
            limiter.wait()
            return row_index, target_column, translator.translate(request).strip()

        with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as executor:
            futures = {executor.submit(run_job, job): job for job in jobs}
            for future in as_completed(futures):
                row_index, target_column, _request = futures[future]
                try:
                    _row_index, _target_column, result = future.result()
                    if not result:
                        raise RuntimeError("AI 返回了空翻译")
                    self.set_cell(row_index, target_column, result)
                    translated += 1
                    if save_callback and autosave_every > 0 and translated % autosave_every == 0:
                        save_callback(self)
                except Exception as exc:
                    failed.append((row_index, str(exc)))
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)
        if not jobs and progress_callback:
            progress_callback(0, 0)
        if save_callback and translated > 0:
            save_callback(self)
        return BatchTranslationResult(translated=translated, skipped=skipped, failed=failed)

    def _normalize_row(self, row: list[str]) -> list[str]:
        normalized = list(row[: len(self.header)])
        if len(normalized) < len(self.header):
            normalized.extend([""] * (len(self.header) - len(normalized)))
        return normalized
