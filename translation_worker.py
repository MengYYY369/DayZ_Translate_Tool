from PySide6.QtCore import QObject, Signal, Slot


class TranslationWorker(QObject):
    progress = Signal(object)
    retrying = Signal(int, int, int)
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
            self.service.on_retry = self.retrying.emit
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
