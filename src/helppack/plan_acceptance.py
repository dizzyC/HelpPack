"""Explicit native acceptance: read-only checks, synthetic plans and exports only."""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton

from .diagnostics.checks import PerformanceCheck
from .diagnostics.engine import DiagnosticEngine
from .diagnostics.history import DiagnosticHistoryStore
from .diagnostics.models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
    RepairSuggestion,
    RollbackCapability,
    SafetyLevel,
    ScanSummary,
    Severity,
)
from .diagnostics.repair_plan import make_plan
from .diagnostics.scenario_checks import NetworkSceneCheck
from .edition import LANGUAGE
from .exporter import export_markdown, export_zip
from .models import ProblemDetails, ReportBundle, SystemSnapshot
from .plan_resources import tr
from .report import generate_markdown
from .ui.font import configure_local_font
from .ui.main_window import MainWindow
from .ui.repair_plan_panel import PlanReview


def run(directory):
    output = Path(directory).resolve() / uuid.uuid4().hex
    output.mkdir(parents=True, exist_ok=False)
    app = QApplication.instance() or QApplication([])
    configure_local_font(app)
    window = MainWindow()
    window.diagnostic_page.history = DiagnosticHistoryStore(output / "history")
    window.show()
    app.processEvents()
    result = {"edition": LANGUAGE, "frozen": bool(getattr(sys, "frozen", False)), "platform": app.platformName(),
              "real_system_repairs": "not performed", "native_external_clicks": "not verified"}
    try:
        # Only documented read-only probes run; no real data is written to reports or screenshots.
        with ThreadPoolExecutor(max_workers=1) as pool:
            for name, check, category in (("network", NetworkSceneCheck(), "网络或Wi-Fi异常"),
                                          ("performance", PerformanceCheck(), "系统卡顿")):
                future = pool.submit(DiagnosticEngine([check]).scan, category)
                ticks = 0
                while not future.done():
                    app.processEvents()
                    time.sleep(0.05)
                    ticks += 1
                scanned = future.result()
                result[name] = {"states": [r.status.value for r in scanned.results], "event_loop_ticks": ticks}
            from .diagnostics.software_analysis import analyze_software
            future = pool.submit(analyze_software, sys.executable, "闪退", threading.Event(), lambda *_: None)
            while not future.done():
                app.processEvents()
                time.sleep(0.05)
            software = future.result()
            result["software"] = {"finding_count": len(software.findings), "states": [f.state for f in software.findings]}
        now = datetime.now(UTC).isoformat()
        actions = [RepairSuggestion("flush_dns_cache", tr("flush"), {}, SafetyLevel.L1, False, tr("flush_impact"),
                                    "ipconfig.exe /flushdns", tr("never"), RollbackCapability.NONE),
                   RepairSuggestion("renew_dhcp", "DHCP", {"interface_alias": "Fictional Adapter"}, SafetyLevel.L3, True,
                                    "Synthetic network interruption", "ipconfig.exe /renew", tr("never"), RollbackCapability.NONE)]
        finding = DiagnosticResult("network.scene", "网络或Wi-Fi异常", tr("network_title"), DiagnosticStatus.NOTICE, Severity.LOW,
                                   [Evidence("Synthetic DNS evidence", "Fictional evidence only. " * 160 + "END_MARKER")],
                                   tr("network_limits"), "中", [tr("dns_hint")], repair_suggestions=actions)
        summary = ScanSummary("网络或Wi-Fi异常", now, now, False, [finding])
        window._go(6, tr("title"))
        window.diagnostic_page._scan_completed(summary)
        window.diagnostic_page.result_tree.setCurrentItem(window.diagnostic_page.result_tree.topLevelItem(0))
        for width, height in ((1100, 800), (760, 560)):
            window.resize(width, height)
            app.processEvents()
            assert window.grab().save(str(output / f"results_{width}.png"))
        review = PlanReview(make_plan(summary), window)
        assert len(review.selected()) == 1  # High-impact DHCP action starts unchecked.
        assert next(b for b in review.findChildren(QPushButton) if b.text() == tr("cancel")).isDefault()
        review.findChild(QCheckBox).setChecked(True)
        review.show()
        app.processEvents()
        review.grab().save(str(output / "plan_preview.png"))
        assert "Synthetic DNS evidence" in review.details.toPlainText()
        review.reject()  # Never accept a real plan during native acceptance.
        from PySide6.QtWidgets import QScrollArea
        for area in window.diagnostic_page.findChildren(QScrollArea):
            area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
        app.processEvents()
        window.grab().save(str(output / "results_bottom.png"))
        assert not window.diagnostic_page.plan_panel.is_running
        bundle = ReportBundle(ProblemDetails("其他问题", "Fictional issue Ω 中文", "Synthetic description"),
                              SystemSnapshot(windows_version="Fictional Windows"), diagnostics_markdown=tr("plan_report"))
        window.bundle = bundle
        report = generate_markdown(bundle)
        window.preview_edit.setPlainText(report)
        window._go(4, tr("plan_report"))
        app.processEvents()
        window.grab().save(str(output / "report_preview.png"))
        export_markdown(report, output / "report.md")
        archive_path = export_zip(report, bundle, output / "HelpPack_20261002_000000.zip")
        with zipfile.ZipFile(archive_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert str(output) not in json.dumps(manifest)
            assert archive.read("report.md").decode("utf-8") == report
            assert all(hashlib.sha256(archive.read(e["name"])).hexdigest() == e["sha256"] for e in manifest["files"])
        result.update(status="ok", native_visible=window.isVisible(), plan_preview="passed; cancelled without mutation",
                      unicode_and_zip="passed", long_evidence="END_MARKER" in window.diagnostic_page.result_detail.toPlainText())
    except Exception as exc:  # noqa: BLE001 - acceptance must report failures without mutating the system
        result.update(status="failed", error=type(exc).__name__ + ": " + str(exc))
    finally:
        (output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        window.close()
    return 0 if result.get("status") == "ok" else 1
