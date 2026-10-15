"""把质量检查放到后台线程跑，避免大表检查时界面卡住。

骨架与 translation_worker.TranslationWorker 保持一致：
progress 报告进度、finished 交回结果、failed 交回错误、cancel 请求中断。
"""

from PySide6.QtCore import QObject, Signal, Slot

from quality_check import QualityCheckConfig, check_table


class QualityCheckWorker(QObject):
    progress = Signal(int, int)   # (已查完的规则数, 规则总数)
    finished = Signal(object)     # {(行, 列): (规则键, ...)}
    failed = Signal(str)

    def __init__(self, headers, rows, source_header, config=None, glossary=None):
        super().__init__()
        # headers/rows 必须是主线程取好的快照，后台线程只读不写。
        self.headers = list(headers)
        self.rows = rows
        self.source_header = source_header
        self.config = config or QualityCheckConfig()
        self.glossary = list(glossary or [])
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    @Slot()
    def run(self):
        try:
            issues = check_table(
                self.headers,
                self.rows,
                self.source_header,
                config=self.config,
                glossary=self.glossary,
                progress=lambda done, total: self.progress.emit(done, total),
                should_cancel=lambda: self.cancelled,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(issues)
