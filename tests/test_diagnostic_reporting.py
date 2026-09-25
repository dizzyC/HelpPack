from helppack.diagnostics.models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
    SafetyLevel,
    ScanSummary,
    Severity,
)
from helppack.diagnostics.reporting import generate_diagnostic_markdown
from helppack.models import ProblemDetails, ReportBundle, SystemSnapshot
from helppack.report import generate_markdown


def test_diagnostic_report_is_redacted_and_can_be_embedded() -> None:
    summary = ScanSummary(
        category="网络或Wi-Fi异常",
        started_at="2026-09-25T10:00:00+08:00",
        finished_at="2026-09-25T10:00:02+08:00",
        cancelled=False,
        results=[
            DiagnosticResult(
                check_id="network.test",
                category="网络或Wi-Fi异常",
                display_name="网络测试",
                status=DiagnosticStatus.NOTICE,
                severity=Severity.LOW,
                evidence=[Evidence("原始证据", "IP 192.168.1.8 email test@example.com token=secret-token")],
                explanation="只是线索",
                confidence="中",
                recommendations=["继续检查"],
                safety_level=SafetyLevel.L0,
            )
        ],
    )
    diagnostic = generate_diagnostic_markdown(summary)
    assert "<IP_ADDRESS>" in diagnostic
    assert "<EMAIL>" in diagnostic
    assert "<REDACTED_SECRET>" in diagnostic
    assert "192.168.1.8" not in diagnostic
    bundle = ReportBundle(
        ProblemDetails("网络问题", "无法联网", "网页打不开"),
        SystemSnapshot(),
        diagnostics_markdown=diagnostic,
    )
    report = generate_markdown(bundle)
    assert "## 本机只读诊断结果" in report
    assert "本次扫描只执行 L0 只读检查" in report


def test_cancelled_report_is_explicit() -> None:
    summary = ScanSummary("综合检查", "start", "end", True, [])
    assert "用户已取消，结果不完整" in generate_diagnostic_markdown(summary)
