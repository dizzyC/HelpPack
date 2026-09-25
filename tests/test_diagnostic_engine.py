import threading

from helppack.diagnostics.engine import DiagnosticEngine, ScanCancelled
from helppack.diagnostics.models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
    SafetyLevel,
    Severity,
)


def result(check_id: str, status: DiagnosticStatus = DiagnosticStatus.NORMAL) -> DiagnosticResult:
    return DiagnosticResult(
        check_id=check_id,
        category="系统卡顿",
        display_name=check_id,
        status=status,
        severity=Severity.INFO,
        evidence=[Evidence("证据", "测试")],
        explanation="测试",
        confidence="高",
        recommendations=["无"],
        safety_level=SafetyLevel.L0,
    )


class FakeCheck:
    categories = frozenset({"系统卡顿"})

    def __init__(self, check_id: str, behavior="normal") -> None:
        self.check_id = check_id
        self.display_name = check_id
        self.behavior = behavior

    def run(self, context):
        if self.behavior == "crash":
            raise RuntimeError("boom")
        if self.behavior == "permission":
            raise PermissionError
        if self.behavior == "unsupported":
            raise NotImplementedError
        if self.behavior == "timeout":
            raise TimeoutError
        if self.behavior == "cancel":
            context.cancel_event.set()
            raise ScanCancelled
        return [result(self.check_id, DiagnosticStatus.ABNORMAL if self.behavior == "abnormal" else DiagnosticStatus.NORMAL)]


def test_engine_preserves_all_distinct_outcomes_and_continues_after_crash() -> None:
    checks = [
        FakeCheck("normal"),
        FakeCheck("abnormal", "abnormal"),
        FakeCheck("permission", "permission"),
        FakeCheck("unsupported", "unsupported"),
        FakeCheck("timeout", "timeout"),
        FakeCheck("crash", "crash"),
        FakeCheck("after_crash"),
    ]
    summary = DiagnosticEngine(checks=checks).scan("系统卡顿")
    statuses = {item.check_id: item.status for item in summary.results}
    assert statuses == {
        "normal": DiagnosticStatus.NORMAL,
        "abnormal": DiagnosticStatus.ABNORMAL,
        "permission": DiagnosticStatus.PERMISSION_DENIED,
        "unsupported": DiagnosticStatus.UNSUPPORTED,
        "timeout": DiagnosticStatus.UNKNOWN,
        "crash": DiagnosticStatus.UNKNOWN,
        "after_crash": DiagnosticStatus.NORMAL,
    }
    assert all(item.safety_level == SafetyLevel.L0 for item in summary.results)


def test_user_cancel_stops_following_checks() -> None:
    cancel = threading.Event()
    summary = DiagnosticEngine(checks=[FakeCheck("first", "cancel"), FakeCheck("never")]).scan(
        "系统卡顿", cancel_event=cancel
    )
    assert summary.cancelled is True
    assert summary.results == []


def test_pre_cancelled_scan_produces_no_changes_or_results() -> None:
    cancel = threading.Event()
    cancel.set()
    summary = DiagnosticEngine(checks=[FakeCheck("never")]).scan("系统卡顿", cancel_event=cancel)
    assert summary.cancelled is True
    assert not summary.results
