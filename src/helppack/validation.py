"""Explicit native-Qt self-check, usable by a frozen EXE without pytest.

The caller chooses an output folder. A unique child prevents overwriting files.
Only read-only system collection runs. Exports/screenshots use fictional data.
No repairs, audio playback, printing or elevation are triggered.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QRect, QTimer
from PySide6.QtGui import QColor, QImage, QTextCursor
from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton, QScrollArea

from .attachments import add_attachments
from .diagnostics.history import DiagnosticHistoryStore
from .diagnostics.models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
    ScanSummary,
    Severity,
)
from .english import text
from .models import SystemSnapshot
from .ui.font import configure_local_font
from .ui.main_window import MainWindow
from .ui.repair_review import RepairReview
from .ui.screenshot_editor import ScreenshotEditor


def run_self_check(directory: str) -> int:
    output = Path(directory).resolve() / (datetime.now(UTC).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)
    application = QApplication.instance() or QApplication([])
    application.setApplicationName("HelpPack-English")
    font = configure_local_font(application)
    window = MainWindow()
    history = DiagnosticHistoryStore(output / "history")
    window.diagnostic_page.history = history
    window.investigation_page.history = history
    window.show()
    start = time.monotonic()
    ticks = []
    result = {"frozen": bool(getattr(sys, "frozen", False)), "platform": application.platformName(),
              "font": font, "device_pixel_ratio": window.devicePixelRatioF(), "real_repairs": "not run", "audio_and_print": "not run",
              "file_picker": "bypassed for repeatable app-internal checks", "external_mouse_test": "not verified"}
    deadline = QTimer()
    deadline.setInterval(100)

    def click(caption):
        next(b for b in window.findChildren(QPushButton) if b.text() == caption).click()

    def capture(name):
        application.processEvents()
        if not window.grab().save(str(output / (name + ".png"))):
            raise RuntimeError("Cannot save synthetic render evidence")

    def finish():
        try:
            result["read_only_collection"] = "completed"
            result["readable_system_fields"] = sum(value != "无法读取" for value in window.snapshot.as_dict().values())
            # Never export the real snapshot. Everything after this point is fictional.
            window.snapshot = SystemSnapshot(windows_version="Fictional Windows 11", architecture="AMD64", cpu="Example CPU", logical_cores="8")
            image = QImage(120, 80, QImage.Format.Format_RGB32)
            image.fill(QColor("#3b82f6"))
            original = output / "原图截图.png"
            if not image.save(str(original)):
                raise RuntimeError("Cannot create fictional screenshot")
            editor = ScreenshotEditor(original, window)
            editor.canvas.apply_rect(QRect(0, 0, 20, 20), "遮挡")
            edited = output / "edited.png"
            editor.canvas.image.save(str(edited), "PNG")
            attachment = add_attachments([], [original])[0]
            attachment.processed_path = edited
            window.attachments = [attachment]
            window._sync_attachment_list()
            window._populate_privacy_attachments()
            for index in range(4):
                window._go(index, "Support Bundle · Self-Check")
                capture(f"page_{index}")
            window._prepare_preview()
            report = window.preview_edit.toPlainText()
            assert "# HelpPack Support Report" in report
            assert "中文问题 Ω" in report and "用户原话：不能上网" in report
            assert str(output) not in report and "Fictional Windows" in report
            capture("page_4")
            window._show_export()
            picker = QFileDialog.getSaveFileName
            try:
                QFileDialog.getSaveFileName = lambda *a, **k: (str(output / "report.md"), "")
                window._export_markdown()
                QFileDialog.getSaveFileName = lambda *a, **k: (str(output / "HelpPack_20261001_000000.zip"), "")
                window._export_zip()
            finally:
                QFileDialog.getSaveFileName = picker
            capture("page_5")
            with zipfile.ZipFile(output / "HelpPack_20261001_000000.zip") as archive:
                manifest = json.loads(archive.read("manifest.json"))
                assert set(manifest) == {"app", "app_version", "generated_at", "attachments", "files"}
                assert str(output) not in json.dumps(manifest, ensure_ascii=False)
                assert archive.read("report.md").decode("utf-8") == report
                assert archive.read("attachments/原图截图.png") == edited.read_bytes()
                for entry in manifest["files"]:
                    assert hashlib.sha256(archive.read(entry["name"])).hexdigest() == entry["sha256"]
            assert QImage(str(original)).pixelColor(0, 0) == QColor("#3b82f6")
            assert QImage(str(edited)).pixelColor(0, 0) == QColor("black")
            window._go(6, "Diagnostics · Self-Check")
            window.diagnostic_page.show_start()
            capture("diagnostics_selection")
            finding = DiagnosticResult("english.synthetic", "综合检查", "Fictional Long Finding", DiagnosticStatus.NOTICE, Severity.LOW,
                                       [Evidence("Fictional evidence", "Readable evidence. " * 300 + "END_MARKER")],
                                       "A clue, not a confirmed cause.", "中", ["Run a targeted check."])
            window.diagnostic_page._scan_completed(ScanSummary("综合检查", "2026-10-01T00:00:00+00:00", "2026-10-01T00:00:01+00:00", False, [finding]))
            window.diagnostic_page.result_tree.setCurrentItem(window.diagnostic_page.result_tree.topLevelItem(0))
            window.diagnostic_page.result_detail.moveCursor(QTextCursor.MoveOperation.End)
            capture("diagnostics_findings")
            window._go(7, "Targeted Checks · Self-Check")
            for index in range(window.investigation_page.tabs.count()):
                window.investigation_page.tabs.setCurrentIndex(index)
                capture(f"targeted_{index}")
                tab = window.investigation_page.tabs.widget(index)
                areas = ([tab] if isinstance(tab, QScrollArea) else []) + tab.findChildren(QScrollArea)
                for area in areas:
                    area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
                capture(f"targeted_{index}_bottom")
            window.investigation_page.show_report("## Fictional Long Evidence\n" + "This is synthetic evidence, not real system data.\n" * 200 + "END_MARKER")
            window.resize(760, 560)
            window.investigation_page.output.moveCursor(QTextCursor.MoveOperation.End)
            capture("narrow_long_end")
            result["narrow_window"] = [window.width(), window.height()]
            result["native_widget_visible"] = window.isVisible()
            result["long_text_end_retained"] = window.investigation_page.output.toPlainText().endswith("END_MARKER")
            review = RepairReview("<p>Safety review. " + "Long impact explanation. " * 1000 + "END_MARKER</p>", window)
            review.show()
            application.processEvents()
            review.details.moveCursor(QTextCursor.MoveOperation.End)
            review.grab().save(str(output / "repair_review.png"))
            assert review.details.verticalScrollBar().maximum() > 0
            review.reject()
            editor.show()
            application.processEvents()
            editor.grab().save(str(output / "screenshot_editor.png"))
            editor.reject()
            result.update(status="ok", zip_hashes="passed", unicode_export="passed", original_image_unchanged=True,
                          event_loop_ticks=len(ticks), elapsed_seconds=round(time.monotonic() - start, 2))
        except Exception as exc:  # noqa: BLE001 - self-check reports failures, never repairs
            result.update(status="failed", error=type(exc).__name__ + ": " + str(exc))
        finally:
            (output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            deadline.stop()
            window.close()
            application.exit(0 if result.get("status") == "ok" else 1)

    def poll():
        ticks.append(time.monotonic())
        (output / "stage.json").write_text(json.dumps({"page": window.stack.currentIndex(), "thread_exists": window.collection_thread is not None,
                                                      "progress": window.progress.value(), "ticks": len(ticks)}), encoding="utf-8")
        if window.stack.currentIndex() == 3 and window.collection_thread is None:
            finish()
        elif time.monotonic() - start > 90 and window.collection_thread is None:
            result.update(status="failed", error="Collection did not reach privacy review")
            (output / "results.json").write_text(json.dumps(result), encoding="utf-8")
            deadline.stop()
            window.close()
            application.exit(1)

    def begin():
        print("English self-check: starting native workflow", flush=True)
        click(text("创建求助包"))
        window.title_input.setText("中文问题 Ω")
        window.description_input.setPlainText("用户原话：不能上网")
        click(text("开始收集"))
        print("English self-check: read-only collection started", flush=True)
        deadline.start()

    deadline.timeout.connect(poll)
    QTimer.singleShot(200, begin)
    return application.exec()
