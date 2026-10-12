import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from translation_worker import TranslationWorker
from translator_service import TranslationJob, TranslationResults, TranslatorConfig

app = QApplication.instance() or QApplication([])


class FakeService:
    def __init__(self):
        self.on_retry = None
        self.configs_seen = None
        self.fallback_seen = None

    def translate_jobs_with_fallback(self, jobs, configs, progress_callback=None,
                                     should_cancel=None, on_fallback=None):
        self.configs_seen = list(configs)
        if progress_callback:
            progress_callback(TranslationResults(translated=1))
        if on_fallback:
            on_fallback("微软翻译", "Google")
        return TranslationResults(
            translated=len(jobs),
            cell_results={(job.row, job.column): "done" for job in jobs},
        )


class TranslationWorkerTests(unittest.TestCase):
    def test_worker_emits_progress_fallback_and_finished(self):
        service = FakeService()
        worker = TranslationWorker(
            service=service,
            jobs=[TranslationJob(0, 3, "Knife", "en", "de")],
            configs=[TranslatorConfig(provider="microsoft", label="微软翻译"),
                     TranslatorConfig(provider="google", label="Google")],
        )
        progress, finished, fallback = [], [], []
        worker.progress.connect(progress.append)
        worker.finished.connect(finished.append)
        worker.fallback.connect(lambda a, b: fallback.append((a, b)))

        worker.run()

        self.assertEqual(progress[0].translated, 1)
        self.assertEqual(finished[0].cell_results[(0, 3)], "done")
        self.assertEqual(fallback, [("微软翻译", "Google")])
        self.assertEqual([c.provider for c in service.configs_seen], ["microsoft", "google"])

    def test_worker_reports_failure_when_no_source_is_configured(self):
        class EmptyService(FakeService):
            def translate_jobs_with_fallback(self, jobs, configs, **kwargs):
                raise ValueError("No translation source is available for this action.")

        worker = TranslationWorker(
            service=EmptyService(),
            jobs=[TranslationJob(0, 3, "Knife", "en", "de")],
            configs=[],
        )
        failed = []
        worker.failed.connect(failed.append)
        worker.run()
        self.assertIn("No translation source", failed[0])
