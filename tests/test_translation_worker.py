import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from translation_worker import TranslationWorker
from translator_service import TranslationJob, TranslationResults, TranslatorConfig


app = QApplication.instance() or QApplication([])


class FakeService:
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


if __name__ == "__main__":
    unittest.main()
