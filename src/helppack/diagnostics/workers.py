from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from helppack.english import text as msg

from .elevation import ElevationBroker
from .engine import DiagnosticEngine
from .models import RepairSuggestion
from .repairs import RepairCoordinator


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
            self.failed.emit(msg('诊断未能完成：{0}', type(exc).__name__))
        finally:
            self.finished.emit()

    @Slot()
    def cancel(self) -> None:
        self.cancel_event.set()


class RepairWorker(QObject):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, suggestion: RepairSuggestion, second_confirmation: str | bool = False) -> None:
        super().__init__()
        self.suggestion = suggestion
        self.second_confirmation = second_confirmation

    @Slot()
    def run(self) -> None:
        try:
            from ..redaction import redact_text
            self.progress.emit(msg('正在创建操作快照并验证目标…'))
            coordinator = RepairCoordinator()
            prepared = coordinator.prepare(self.suggestion)
            if prepared.requires_second_confirmation:
                expected = prepared.confirmation_phrase
                if (self.second_confirmation != expected if expected else self.second_confirmation is not True):
                    raise ValueError(msg('缺少有效的第二次确认'))
            if self.suggestion.requires_admin:
                self.progress.emit(msg('请在 Windows 用户账户控制窗口中确认此单项操作…'))
                outcome = ElevationBroker().execute(self.suggestion)
            else:
                self.progress.emit(msg('正在执行所选修复；不会自动重启电脑…'))
                outcome = coordinator.execute(
                    prepared,
                    user_confirmed=True,
                    second_confirmation=self.second_confirmation,
                )
            self.completed.emit(outcome)
        except Exception as exc:  # noqa: BLE001 - worker boundary returns user-safe text
            self.failed.emit(redact_text(f"{type(exc).__name__}: {exc}"))
        finally:
            self.finished.emit()
