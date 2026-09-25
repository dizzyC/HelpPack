from pathlib import Path

from helppack.diagnostics.history import DiagnosticHistoryStore
from helppack.diagnostics.models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
    SafetyLevel,
    ScanSummary,
    Severity,
)


def test_history_survives_store_restart_and_is_redacted(tmp_path: Path) -> None:
    summary = ScanSummary(
        category="网络或Wi-Fi异常",
        started_at="start",
        finished_at="finish",
        cancelled=False,
        results=[
            DiagnosticResult(
                check_id="network",
                category="网络",
                display_name="网络",
                status=DiagnosticStatus.NOTICE,
                severity=Severity.LOW,
                evidence=[Evidence("证据", "192.168.50.8 user@example.com token=fake-secret")],
                explanation="test",
                confidence="中",
                recommendations=["test"],
                safety_level=SafetyLevel.L0,
            )
        ],
    )
    first_process = DiagnosticHistoryStore(tmp_path)
    path = first_process.save(summary)
    raw = path.read_text(encoding="utf-8")
    assert "192.168.50.8" not in raw
    assert "user@example.com" not in raw
    assert "fake-secret" not in raw

    restarted_process = DiagnosticHistoryStore(tmp_path)
    loaded = restarted_process.load_latest()
    assert loaded is not None
    assert loaded["category"] == "网络或Wi-Fi异常"
    assert loaded["results"][0]["evidence"][0]["value"] == "<IP_ADDRESS> <EMAIL> token=<REDACTED_SECRET>"


def test_corrupt_history_returns_none(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "latest_scan.json").write_text("not json", encoding="utf-8")
    assert DiagnosticHistoryStore(tmp_path).load_latest() is None
