# Batched Deep Translator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add AI-style translation to the DayZ CSV editor using `deep-translator` with batching, deduplication, caching, progress reporting, and cancellation.

**Architecture:** Keep translation scheduling outside the GUI. `translator_service.py` builds optimized batches and calls `translate_batch`; `translation_worker.py` runs those batches on a Qt worker thread and emits progress; `main.py` only creates jobs, starts the worker, shows progress, and writes results back to cells.

**Tech Stack:** Python 3.10, PySide6, deep-translator, unittest.

---

## File Structure

- Create `translator_service.py`: pure-Python translation job models, cache, grouping, batching, fakeable provider factory, and batch execution.
- Create `translation_worker.py`: Qt `QObject` worker that runs `translator_service.translate_jobs` in a `QThread` and emits progress/result/error signals.
- Modify `main.py`: replace synchronous per-cell translation with progress dialog + background worker wiring.
- Modify `tests/test_dayz_csv.py`: keep existing job-generation tests unchanged unless a column index needs a visible-header adjustment.
- Create `tests/test_translator_service.py`: unit tests for grouping, dedupe, cache, failure, and cancellation without network calls.
- Create `tests/test_translation_worker.py`: minimal Qt worker signal test with fake service callbacks, no network.
- Modify `tests/test_main_gui.py`: verify GUI uses worker start path and does not call real translator in tests.

---

### Task 1: Translation Service Models And Batch Planning

**Files:**
- Create: `translator_service.py`
- Create: `tests/test_translator_service.py`

- [ ] **Step 1: Write failing tests for batching and dedupe**

Create `tests/test_translator_service.py`:

```python
import unittest

from translator_service import TranslationJob, TranslationService, TranslatorConfig


class FakeBatchTranslator:
    def __init__(self):
        self.calls = []

    def translate_batch(self, texts):
        self.calls.append(list(texts))
        return [f"translated:{text}" for text in texts]


class TranslationServiceTests(unittest.TestCase):
    def test_batches_by_language_direction_and_dedupes_texts(self):
        fake = FakeBatchTranslator()
        created = []

        def factory(source, target):
            created.append((source, target))
            return fake

        service = TranslationService(provider_factory=factory, batch_size=2)
        config = TranslatorConfig(provider="google")
        jobs = [
            TranslationJob(0, 3, "Knife", "en", "de"),
            TranslationJob(1, 3, "Knife", "en", "de"),
            TranslationJob(2, 3, "Gun", "en", "de"),
        ]

        results = service.translate_jobs(jobs, config)

        self.assertEqual(created, [("en", "de")])
        self.assertEqual(fake.calls, [["Knife", "Gun"]])
        self.assertEqual(results.translated, 3)
        self.assertEqual(results.failed, 0)
        self.assertEqual(results.cell_results[(0, 3)], "translated:Knife")
        self.assertEqual(results.cell_results[(1, 3)], "translated:Knife")
        self.assertEqual(results.cell_results[(2, 3)], "translated:Gun")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
rtk py -3 -m unittest tests.test_translator_service -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'translator_service'`.

- [ ] **Step 3: Implement minimal models and batching**

Create `translator_service.py`:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TranslationJob:
    row: int
    column: int
    text: str
    source_code: str
    target_code: str


@dataclass(frozen=True)
class TranslatorConfig:
    provider: str = "google"


@dataclass
class TranslationResults:
    translated: int = 0
    skipped: int = 0
    failed: int = 0
    cache_hits: int = 0
    cell_results: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


class TranslationService:
    def __init__(self, provider_factory=None, batch_size=30):
        self.provider_factory = provider_factory or self.create_provider
        self.batch_size = batch_size
        self.cache = {}

    def create_provider(self, source, target):
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source=source, target=target)

    def translate_jobs(self, jobs, config, progress_callback=None, should_cancel=None):
        results = TranslationResults()
        grouped = self._group_jobs(jobs)
        for (source, target), group_jobs in grouped.items():
            if should_cancel and should_cancel():
                break
            translator = self.provider_factory(source, target)
            unique_texts = self._unique_uncached_texts(config.provider, source, target, group_jobs, results)
            for batch in self._chunks(unique_texts):
                if should_cancel and should_cancel():
                    break
                try:
                    translated_texts = translator.translate_batch(batch)
                except Exception as exc:
                    results.failed += len(batch)
                    results.errors.append(str(exc))
                    continue
                for source_text, translated_text in zip(batch, translated_texts):
                    self.cache[(config.provider, source, target, source_text)] = translated_text
            for job in group_jobs:
                key = (config.provider, job.source_code, job.target_code, job.text)
                if key in self.cache:
                    results.cell_results[(job.row, job.column)] = self.cache[key]
                    results.translated += 1
            if progress_callback:
                progress_callback(results)
        return results

    def _group_jobs(self, jobs):
        grouped = {}
        for job in jobs:
            if not job.text:
                continue
            grouped.setdefault((job.source_code, job.target_code), []).append(job)
        return grouped

    def _unique_uncached_texts(self, provider, source, target, jobs, results):
        seen = set()
        texts = []
        for job in jobs:
            key = (provider, source, target, job.text)
            if key in self.cache:
                results.cache_hits += 1
                continue
            if job.text not in seen:
                seen.add(job.text)
                texts.append(job.text)
        return texts

    def _chunks(self, values):
        for index in range(0, len(values), self.batch_size):
            yield values[index:index + self.batch_size]
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
rtk py -3 -m unittest tests.test_translator_service -v
```

Expected: PASS.

---

### Task 2: Cache, Failure, And Cancellation Coverage

**Files:**
- Modify: `translator_service.py`
- Modify: `tests/test_translator_service.py`

- [ ] **Step 1: Add failing tests for cache, failures, and cancellation**

Append to `TranslationServiceTests`:

```python
    def test_cache_prevents_second_batch_call(self):
        fake = FakeBatchTranslator()
        service = TranslationService(provider_factory=lambda source, target: fake, batch_size=30)
        config = TranslatorConfig(provider="google")
        jobs = [TranslationJob(0, 3, "Knife", "en", "de")]

        first = service.translate_jobs(jobs, config)
        second = service.translate_jobs(jobs, config)

        self.assertEqual(fake.calls, [["Knife"]])
        self.assertEqual(first.cell_results[(0, 3)], "translated:Knife")
        self.assertEqual(second.cell_results[(0, 3)], "translated:Knife")
        self.assertEqual(second.cache_hits, 1)

    def test_batch_failure_records_error_and_continues_next_direction(self):
        class FailingTranslator:
            def translate_batch(self, texts):
                raise RuntimeError("network down")

        ok = FakeBatchTranslator()

        def factory(source, target):
            if target == "de":
                return FailingTranslator()
            return ok

        service = TranslationService(provider_factory=factory, batch_size=30)
        config = TranslatorConfig(provider="google")
        jobs = [
            TranslationJob(0, 3, "Knife", "en", "de"),
            TranslationJob(0, 4, "Knife", "en", "fr"),
        ]

        results = service.translate_jobs(jobs, config)

        self.assertEqual(results.failed, 1)
        self.assertEqual(results.cell_results[(0, 4)], "translated:Knife")
        self.assertTrue(results.errors)

    def test_cancel_stops_before_processing_later_groups(self):
        fake = FakeBatchTranslator()
        calls = 0

        def should_cancel():
            nonlocal calls
            calls += 1
            return calls > 1

        service = TranslationService(provider_factory=lambda source, target: fake, batch_size=30)
        config = TranslatorConfig(provider="google")
        jobs = [
            TranslationJob(0, 3, "Knife", "en", "de"),
            TranslationJob(0, 4, "Knife", "en", "fr"),
        ]

        results = service.translate_jobs(jobs, config, should_cancel=should_cancel)

        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(results.translated, 1)
```

- [ ] **Step 2: Run test to verify it fails or exposes gaps**

Run:

```powershell
rtk py -3 -m unittest tests.test_translator_service -v
```

Expected: at least one FAIL if Task 1 implementation does not count failed jobs per cell or cancellation correctly.

- [ ] **Step 3: Adjust service behavior**

Ensure failures count affected jobs, not only unique texts:

```python
except Exception as exc:
    failed_texts = set(batch)
    results.failed += sum(1 for job in group_jobs if job.text in failed_texts)
    results.errors.append(str(exc))
    continue
```

Keep the current cancellation check before each group and before each batch.

- [ ] **Step 4: Run service tests**

Run:

```powershell
rtk py -3 -m unittest tests.test_translator_service -v
```

Expected: PASS.

---

### Task 3: Qt Translation Worker

**Files:**
- Create: `translation_worker.py`
- Create: `tests/test_translation_worker.py`

- [ ] **Step 1: Write failing worker test**

Create `tests/test_translation_worker.py`:

```python
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from translation_worker import TranslationWorker
from translator_service import TranslationJob, TranslationResults, TranslatorConfig


app = QApplication.instance() or QApplication([])


class FakeService:
    def __init__(self):
        self.cancelled = False

    def translate_jobs(self, jobs, config, progress_callback=None, should_cancel=None):
        if progress_callback:
            progress_callback(TranslationResults(translated=1))
        return TranslationResults(translated=len(jobs), cell_results={(job.row, job.column): "done" for job in jobs})


class TranslationWorkerTests(unittest.TestCase):
    def test_worker_emits_progress_and_finished(self):
        service = FakeService()
        worker = TranslationWorker(
            service=service,
            jobs=[TranslationJob(0, 3, "Knife", "en", "de")],
            config=TranslatorConfig(provider="google"),
        )
        progress = []
        finished = []
        worker.progress.connect(progress.append)
        worker.finished.connect(finished.append)

        worker.run()

        self.assertEqual(progress[0].translated, 1)
        self.assertEqual(finished[0].cell_results[(0, 3)], "done")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
rtk py -3 -m unittest tests.test_translation_worker -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'translation_worker'`.

- [ ] **Step 3: Implement worker**

Create `translation_worker.py`:

```python
from PySide6.QtCore import QObject, Signal, Slot


class TranslationWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, service, jobs, config):
        super().__init__()
        self.service = service
        self.jobs = jobs
        self.config = config
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    @Slot()
    def run(self):
        try:
            results = self.service.translate_jobs(
                self.jobs,
                self.config,
                progress_callback=self.progress.emit,
                should_cancel=lambda: self.cancelled,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(results)
```

- [ ] **Step 4: Run worker tests**

Run:

```powershell
rtk py -3 -m unittest tests.test_translation_worker -v
```

Expected: PASS.

---

### Task 4: Progress Dialog And GUI Wiring

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main_gui.py`

- [ ] **Step 1: Add failing GUI tests for worker start path**

Append to `tests/test_main_gui.py`:

```python
    def test_run_translation_jobs_starts_worker_instead_of_sync_translate(self):
        started = []

        class FakeWorker:
            def __init__(self):
                self.progress = FakeSignal()
                self.finished = FakeSignal()
                self.failed = FakeSignal()

            def run(self):
                started.append(True)

            def cancel(self):
                pass

        class FakeSignal:
            def __init__(self):
                self.callbacks = []

            def connect(self, callback):
                self.callbacks.append(callback)

        self.window.create_translation_worker = lambda jobs: FakeWorker()
        self.window.start_translation_worker([(0, 2, "Knife", "de")])

        self.assertTrue(started)
```

- [ ] **Step 2: Run GUI test to verify it fails**

Run:

```powershell
rtk py -3 -m unittest tests.test_main_gui -v
```

Expected: FAIL because `create_translation_worker` / `start_translation_worker` do not exist.

- [ ] **Step 3: Implement progress dialog and worker start methods**

In `main.py`, add imports:

```python
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QProgressDialog
from translator_service import TranslationJob, TranslationService, TranslatorConfig
from translation_worker import TranslationWorker
```

Add methods to `DayzTranslateTool`:

```python
    def start_translation_worker(self, raw_jobs):
        jobs = [
            TranslationJob(row, column, text, source_language_code_for_header(self.source_header), target)
            for row, column, text, target in raw_jobs
        ]
        if not jobs:
            QMessageBox.information(self, "Translate", "No translatable cells were selected.")
            return

        self.progress_dialog = QProgressDialog("Translating...", "Cancel", 0, len(jobs), self)
        self.progress_dialog.setWindowTitle("Translate")
        self.progress_dialog.setWindowModality(Qt.WindowModal)

        self.translation_thread = QThread(self)
        self.translation_worker = self.create_translation_worker(jobs)
        self.translation_worker.moveToThread(self.translation_thread)
        self.translation_thread.started.connect(self.translation_worker.run)
        self.translation_worker.progress.connect(self.update_translation_progress)
        self.translation_worker.finished.connect(self.finish_translation)
        self.translation_worker.failed.connect(self.fail_translation)
        self.progress_dialog.canceled.connect(self.translation_worker.cancel)
        self.translation_worker.finished.connect(self.translation_thread.quit)
        self.translation_worker.failed.connect(self.translation_thread.quit)
        self.translation_thread.start()

    def create_translation_worker(self, jobs):
        return TranslationWorker(
            service=TranslationService(batch_size=30),
            jobs=jobs,
            config=TranslatorConfig(provider="google"),
        )

    def update_translation_progress(self, results):
        self.progress_dialog.setValue(results.translated + results.failed + results.skipped)
        self.progress_dialog.setLabelText(
            f"Translated {results.translated}, failed {results.failed}, cache hits {results.cache_hits}"
        )

    def finish_translation(self, results):
        for (row, column), text in results.cell_results.items():
            self.set_cell_text(row, column, text)
        self.progress_dialog.setValue(self.progress_dialog.maximum())
        self.statusBar().showMessage(
            f"Translated {results.translated}, failed {results.failed}, cache hits {results.cache_hits}",
            5000,
        )

    def fail_translation(self, message):
        QMessageBox.critical(self, "Translate failed", message)
```

- [ ] **Step 4: Route existing translation actions into worker path**

Replace the body of `run_translation_jobs` with:

```python
    def run_translation_jobs(self, jobs):
        self.start_translation_worker(jobs)
```

- [ ] **Step 5: Run GUI tests**

Run:

```powershell
rtk py -3 -m unittest tests.test_main_gui -v
```

Expected: PASS.

---

### Task 5: Provider Setting And Requirements Check

**Files:**
- Modify: `main.py`
- Modify: `requirements.txt`
- Modify: `tests/test_main_gui.py`

- [ ] **Step 1: Add provider config tests**

Append to `tests/test_main_gui.py`:

```python
    def test_default_translation_provider_is_google(self):
        self.assertEqual(self.window.translation_provider, "google")
```

- [ ] **Step 2: Run GUI tests to verify fail**

Run:

```powershell
rtk py -3 -m unittest tests.test_main_gui -v
```

Expected: FAIL because `translation_provider` does not exist.

- [ ] **Step 3: Add provider state**

In `DayzTranslateTool.__init__`, add:

```python
self.translation_provider = self.settings.value("translation_provider", "google")
```

In `create_translation_worker`, pass:

```python
config=TranslatorConfig(provider=self.translation_provider)
```

Ensure `requirements.txt` contains:

```text
PySide6
deep-translator
```

- [ ] **Step 4: Run tests**

Run:

```powershell
rtk py -3 -m unittest discover -s tests
```

Expected: PASS.

---

### Task 6: Final Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run unit tests**

Run:

```powershell
rtk py -3 -m unittest discover -s tests
```

Expected:

```text
OK
```

- [ ] **Step 2: Run syntax check**

Run:

```powershell
rtk py -3 -m py_compile dayz_csv.py main.py translator_service.py translation_worker.py
```

Expected: exit code 0, no output.

- [ ] **Step 3: Verify dependency import**

Run:

```powershell
rtk py -3 -c "from deep_translator import GoogleTranslator; print(hasattr(GoogleTranslator(source='en', target='de'), 'translate_batch'))"
```

Expected:

```text
True
```

- [ ] **Step 4: Verify CodeGraph status**

Run:

```powershell
rtk codegraph status
```

Expected: if still `Not initialized`, report that index update cannot be performed until the user approves `codegraph init -i`.
