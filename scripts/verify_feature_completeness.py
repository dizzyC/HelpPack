"""Read-only live checks and an optional isolated desktop inspection window.

Artifacts stay under ignored dist/validation; no repair, sound or print is run.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import sys
import threading
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from helppack.diagnostics.history import DiagnosticHistoryStore
from helppack.diagnostics.investigation import query, rows
from helppack.diagnostics.monitoring import MonitorBuffer, ResourceSampler
from helppack.diagnostics.network_layers import investigate_network
from helppack.diagnostics.peripherals import inspect_peripherals
from helppack.diagnostics.reporting import generate_diagnostic_markdown
from helppack.diagnostics.runner import CommandRunner
from helppack.diagnostics.software_analysis import analyze_software
from helppack.diagnostics.storage_analysis import scan_directory
from helppack.diagnostics.symptoms import diagnose_symptom
from helppack.diagnostics.timeline import collect_timeline
from helppack.exporter import export_markdown, export_zip
from helppack.models import Attachment, ProblemDetails, ReportBundle, SystemSnapshot
from helppack.report import concise_summary, generate_markdown

ROOT = Path(__file__).resolve().parents[1]


def desktop():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from helppack.ui.font import configure_local_font
    from helppack.ui.main_window import MainWindow

    application = QApplication([])
    configure_local_font(application)
    window = MainWindow()
    window.setWindowTitle("HelpPack 功能完整性验收 · 虚构长文字")
    window.investigation_page.history = DiagnosticHistoryStore(ROOT / "dist" / "validation" / "desktop_history")
    window._go(7, "专项排查 · 真实窗口验收")
    window.investigation_page.show_report("## 虚构长文字验收\n\n" + "这是一段虚构的可滚动、可选择复制证据，不含真实诊断信息。\n" * 200 + "\n全文末尾验证标记：HELPPACK_END")
    window.show()
    output = ROOT / "dist" / "validation" / "desktop_completeness"
    output.mkdir(parents=True, exist_ok=True)
    def snapshots():
        # Application-internal render evidence, not an external desktop click test.
        window.grab().save(str(output / "wide.png"))
        window.resize(780, 650)
        window.investigation_page.output.moveCursor(__import__("PySide6.QtGui").QtGui.QTextCursor.MoveOperation.End)
        def small():
            window.grab().save(str(output / "narrow_end.png"))
            (output / "render.json").write_text(json.dumps({"native_widget_visible": window.isVisible(), "platform": application.platformName(), "text_length": len(window.investigation_page.output.toPlainText()), "end_marker_retained": "HELPPACK_END" in window.investigation_page.output.toPlainText(), "external_click_test": "not verified: helper window binding failed"}), encoding="utf-8")
        QTimer.singleShot(300, small)
    QTimer.singleShot(700, snapshots)
    return application.exec()


def live():
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication

    from helppack.ui.screenshot_editor import ScreenshotEditor

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    output = ROOT / "dist" / "validation" / ("completeness_" + datetime.now(UTC).astimezone().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6])
    output.mkdir(parents=True)
    store = DiagnosticHistoryStore(output / "history")
    cancel = threading.Event()
    runner = CommandRunner()
    reports, checks = [], []

    def progress(percent, label):
        print(f"[{percent:3}%] {label}", flush=True)

    def record(kind, result):
        report = result.markdown()
        reports.append(report)
        store.save_record({"kind": kind, "time": result.timestamp, "status": "稍后处理", "report": report})
        checks.append({"kind": kind, "read_only_executed": True, "states": [{"layer": f.layer, "state": f.state} for f in result.findings]})

    print("只读验证：不修复系统、不播放声音、不提交打印任务", flush=True)
    summary, _ = diagnose_symptom("电脑突然变卡", cancel, progress, runner)
    store.save(summary)
    reports.append(generate_diagnostic_markdown(summary))
    checks.append({"kind": "症状", "check_count": len(summary.results), "read_only_executed": True})
    # Compare with an already configured DNS, not a newly selected public DNS.
    dns = ""
    try:
        interfaces = rows(query(runner, "Get-DnsClientServerAddress -AddressFamily IPv4 | Select-Object ServerAddresses | ConvertTo-Json -Compress"))
        for interface in interfaces:
            addresses = interface.get("ServerAddresses") or []
            if isinstance(addresses, str):
                addresses = [addresses]
            for address in addresses:
                if not ipaddress.ip_address(address).is_loopback:
                    dns = address
                    break
            if dns:
                break
    except (OSError, ValueError, TimeoutError):
        pass
    record("网络", investigate_network("https://www.microsoft.com/", dns, cancel, progress, runner))
    record("软件", analyze_software(sys.executable, "无响应", cancel, progress, runner))
    scan = scan_directory(str(ROOT / "src"), cancel, progress, max_entries=5000, max_seconds=15)
    reports.append(scan.markdown())
    checks.append({"kind": "空间", "files": len(scan.files), "cancelled": scan.cancelled, "limited": scan.limited, "read_only_executed": True})
    for kind in ("声音", "蓝牙", "打印机"):
        record(kind, inspect_peripherals(kind, cancel, progress, runner))
    record("时间线", collect_timeline(cancel, progress, runner))
    sampler, buffer = ResourceSampler(), MonitorBuffer()
    for index in range(5):
        buffer.append(sampler.sample(index * 2))
        if index == 2:
            buffer.mark_incident()
        if index < 4:
            time.sleep(2)
    buffer.stop()
    reports.append(buffer.markdown())
    checks.append({"kind": "监测", "sample_count": len(buffer.samples), "stopped": buffer.stopped, "read_only_executed": True})
    image = QImage(120, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    image.setText("Private", "synthetic@example.com")
    original, processed = output / "synthetic_original.png", output / "synthetic_processed.png"
    assert image.save(str(original))
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    editor = ScreenshotEditor(original)
    editor.canvas.apply_rect(QRect(5, 5, 30, 20), "遮挡")
    editor.canvas.apply_rect(QRect(0, 0, 100, 60), "裁剪")
    assert editor.canvas.image.save(str(processed))
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash
    assert QImage(str(processed)).pixelColor(10, 10) == QColor("black")
    assert not QImage(str(processed)).textKeys()
    bundle = ReportBundle(ProblemDetails("其他问题", "本机只读验证", "功能完整性验收，不执行修复", attempted_solutions="只读采样", unresolved_issues="实际故障未复现、声音/实体打印未测试"), SystemSnapshot(), [Attachment(original, "synthetic_processed.png", processed_path=processed)], "\n\n".join(reports))
    report = generate_markdown(bundle)
    export_markdown(report, output / "report.md")
    archive_path = export_zip(report, bundle, output / "verification.zip")
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert str(output) not in json.dumps(manifest) and ":\\" not in json.dumps(manifest)
        assert archive.read("attachments/synthetic_processed.png") == processed.read_bytes()
        for entry in manifest["files"]:
            assert hashlib.sha256(archive.read(entry["name"])).hexdigest() == entry["sha256"]
    assert "仍未解决的问题" in concise_summary(report)
    records = store.list_records()
    assert records
    store.mark(records[0]["id"], "未解决")
    assert DiagnosticHistoryStore(store.root).load_record(records[0]["id"])["status"] == "未解决"
    result = {"checks": checks, "zip_content_hashes": "passed", "processed_copy_original_unchanged": True, "history_reloaded": True,
              "not_executed": ["真实系统修复", "声音试听", "实体测试打印", "两小时持续运行"], "output": str(output)}
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**result, "checks": [{**c, "states": c.get("states", [])[:6]} for c in checks]}, ensure_ascii=False, indent=2), flush=True)
    editor.reject()
    application.processEvents()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true", help="执行本机只读检查并验证本地报告/ZIP")
    group.add_argument("--desktop", action="store_true", help="打开独立验收窗口，不自动运行检查")
    args = parser.parse_args()
    raise SystemExit(desktop() if args.desktop else live())
