from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from .collector import collect_system_info
from .english import text


class CollectionWorker(QObject):
    progress = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    @Slot()
    def run(self) -> None:
        try:
            snapshot = collect_system_info(lambda percent, message: self.progress.emit(percent, message))
            self.completed.emit(snapshot)
        except Exception:  # noqa: BLE001 - worker boundary reports a user-safe failure
            self.failed.emit(text("系统信息收集未能完成。你仍可返回并重试。"))
        finally:
            self.finished.emit()
