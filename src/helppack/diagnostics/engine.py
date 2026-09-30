from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Protocol

from .models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
    SafetyLevel,
    ScanSummary,
    Severity,
)
from .runner import CommandRunner


class ScanCancelled(RuntimeError):
    pass


class DiagnosticCheck(Protocol):
    check_id: str
    display_name: str
    categories: frozenset[str]

    def run(self, context: ScanContext) -> list[DiagnosticResult]: ...


class ScanContext:
    def __init__(self, runner: CommandRunner, cancel_event: threading.Event, category: str = "综合检查") -> None:
        self.runner = runner
        self.cancel_event = cancel_event
        self.category = category

    def ensure_not_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise ScanCancelled("用户已取消扫描")

    def wait(self, seconds: float) -> None:
        if self.cancel_event.wait(seconds):
            raise ScanCancelled("用户已取消扫描")


class DiagnosticEngine:
    def __init__(self, checks: Iterable[DiagnosticCheck] | None = None, runner: CommandRunner | None = None) -> None:
        if checks is None:
            from .checks import default_checks

            checks = default_checks()
        self.checks = list(checks)
        self.runner = runner or CommandRunner()

    def scan(
        self,
        category: str,
        *,
        cancel_event: threading.Event | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> ScanSummary:
        started = datetime.now().astimezone()
        cancel = cancel_event or threading.Event()
        callback = progress or (lambda _percent, _message: None)
        selected = [check for check in self.checks if (category == "综合检查" and not getattr(check, "explicit_only", False)) or category in check.categories]
        context = ScanContext(self.runner, cancel, category)
        results: list[DiagnosticResult] = []
        cancelled = False
        for index, check in enumerate(selected):
            try:
                context.ensure_not_cancelled()
                callback(int(index / max(len(selected), 1) * 100), check.display_name)
                results.extend(check.run(context))
            except ScanCancelled:
                cancelled = True
                break
            except PermissionError:
                results.append(_failure_result(check, DiagnosticStatus.PERMISSION_DENIED, "当前权限不足，未能完成此项检查。"))
            except TimeoutError:
                results.append(_failure_result(check, DiagnosticStatus.UNKNOWN, "检查超时，无法判断当前状态。"))
            except (NotImplementedError, OSError) as exc:
                results.append(_failure_result(check, DiagnosticStatus.UNSUPPORTED, f"当前系统不支持此项检查：{type(exc).__name__}"))
            except Exception as exc:  # noqa: BLE001 - a broken checker must not abort other checks
                results.append(_failure_result(check, DiagnosticStatus.UNKNOWN, f"检查失败，但其他项目将继续：{type(exc).__name__}"))
        callback(100, "扫描已取消" if cancelled else "只读扫描完成")
        finished = datetime.now().astimezone()
        return ScanSummary(
            category=category,
            started_at=started.isoformat(timespec="seconds"),
            finished_at=finished.isoformat(timespec="seconds"),
            cancelled=cancelled,
            results=results,
        )


def _failure_result(check: DiagnosticCheck, status: DiagnosticStatus, explanation: str) -> DiagnosticResult:
    return DiagnosticResult(
        check_id=check.check_id,
        category=next(iter(check.categories), "综合检查"),
        display_name=check.display_name,
        status=status,
        severity=Severity.INFO,
        evidence=[Evidence("检查状态", explanation)],
        explanation=explanation,
        confidence="高（仅针对检查是否完成）",
        recommendations=["可稍后重试，或将该状态连同求助包交给技术人员。"],
        safety_level=SafetyLevel.L0,
        redacted_raw=explanation,
    )
