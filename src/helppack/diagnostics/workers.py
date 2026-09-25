from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from .engine import DiagnosticEngine


class DiagnosticWorker(QObject):
    progress = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, category: str, engine: DiagnosticEngine | None = None) -> None:
        super().__init__()
        self.category = category
        self.engine = engine or DiagnosticEngine()
        self.cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            summary = self.engine.scan(
                self.category,
                cancel_event=self.cancel_event,
                progress=lambda percent, message: self.progress.emit(percent, message),
            )
            self.completed.emit(summary)
        except Exception as exc:  # noqa: BLE001 - worker boundary reports a user-safe failure
            self.failed.emit(f"诊断未能完成：{type(exc).__name__}")
        finally:
            self.finished.emit()

    @Slot()
    def cancel(self) -> None:
        self.cancel_event.set()
