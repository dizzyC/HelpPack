import hashlib
import json
import os
import time
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from helppack.diagnostics.history import DiagnosticHistoryStore
from helppack.diagnostics.investigation import Finding, Investigation
from helppack.diagnostics.models import ScanSummary
from helppack.exporter import export_zip
from helppack.models import Attachment, ProblemDetails, ReportBundle, SystemSnapshot
from helppack.ui.investigation_page import InvestigationPage
from helppack.ui.main_window import MainWindow
from helppack.ui.screenshot_editor import ScreenshotEditor

_application = None


def app():
    global _application
    _application = QApplication.instance() or QApplication([])
    return _application


def await_idle(page, timeout=10):
    deadline = time.monotonic() + timeout
    while page.thread is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    assert page.thread is None, "后台检查未在有界等待内完成"


def click(page, name):
    button = next(b for b in page.findChildren(QPushButton) if b.text() == name)
    button.click()
    app().processEvents()


def test_real_entry_route_task_history_compare_and_attach(tmp_path, monkeypatch):
    application = app()
    monkeypatch.setattr(QMessageBox, "information", lambda *a: QMessageBox.StandardButton.Ok)
    window = MainWindow()
    page = window.investigation_page
    page.history = DiagnosticHistoryStore(tmp_path / "history")
    click(window, 'Symptom Guide and Targeted Checks')
    assert window.stack.currentWidget() == page
    page.symptom.setText("只有某个网站打不开")
    assert 'Network' in page.plan.text()
    summary = ScanSummary("模拟症状", "2026-01-01", "2026-01-01", False, [])
    from helppack.ui import investigation_page as module
    monkeypatch.setattr(module, "diagnose_symptom", lambda *args: (summary, []))
    click(page, 'Run Symptom Checks')
    await_idle(page)
    assert "只有某个网站" in page.output.toPlainText()
    assert len(page.history.list_records()) == 1
    # Exercise a network task, rendering, persistence and comparable evidence.
    def network(*args):
        return Investigation("模拟网络", findings=[Finding("系统 DNS", "失败", "虚构错误")])
    monkeypatch.setattr(module, "investigate_network", network)
    click(page, 'Run Layered Network Checks')
    await_idle(page)
    monkeypatch.setattr(module, "investigate_network", lambda *args: Investigation("模拟网络", findings=[Finding("系统 DNS", "有结果", "虚构地址")]))
    click(page, 'Run Layered Network Checks')
    await_idle(page)
    page.refresh_history()
    page.records.item(0).setSelected(True)
    page.records.item(1).setSelected(True)
    page.compare_history()
    assert "Failed → Results found" in page.output.toPlainText() or "Results found → Failed" in page.output.toPlainText()
    page.records.setCurrentRow(0)
    page.disposition.setCurrentText("已解决")
    page.mark_history()
    assert "Resolved" in page.records.item(0).text()
    page.show_history()
    click(page, 'Add to Report')
    assert "Local Problem History" in window.diagnostics_markdown
    window.resize(780, 650)
    application.processEvents()
    window.close()


def test_storage_ui_confirmation_move_and_restart_recovery(tmp_path, monkeypatch):
    app()
    root = tmp_path / "selected"
    (root / "cache").mkdir(parents=True)
    source = root / "cache" / "fake.bin"
    source.write_bytes(b"synthetic cache")
    page = InvestigationPage(history=DiagnosticHistoryStore(tmp_path / "history"))
    page.directory.setText(str(root))
    page.start_storage()
    await_idle(page)
    assert page.files.count() == 1
    page.files.setCurrentRow(0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.No)
    page.move_cache()
    assert source.exists()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
    page.move_cache()
    await_idle(page)
    assert not source.exists() and page.receipts
    assert page.history.list_records()[0]["operations"][0]["confirmed"]
    page.receipts = []
    page.start_storage()
    await_idle(page)
    assert page.receipts
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page.restore_cache()
    await_idle(page)
    assert source.read_bytes() == b"synthetic cache"
    page.close()


def test_worker_cancel_failure_and_long_results_remain_responsive(tmp_path):
    app()
    page = InvestigationPage(history=DiagnosticHistoryStore(tmp_path))
    def waiting(cancel, progress):
        progress(10, "等待模拟查询")
        if cancel.wait(2):
            raise InterruptedError("Check cancelled")
        return "unexpected"
    page.run_task(waiting, "test")
    QTest.qWait(30)
    page.cancel_task()
    await_idle(page)
    assert 'cancelled' in page.status.text()
    long_text = "可完整复制的虚构证据" * 2000
    page.run_task(lambda c, p: long_text, "test")
    await_idle(page)
    assert long_text == page.output.toPlainText()
    assert page.output.isReadOnly()
    page.close()


def test_software_peripheral_timeline_real_buttons_use_worker(tmp_path, monkeypatch):
    app()
    page = InvestigationPage(history=DiagnosticHistoryStore(tmp_path))
    from helppack.ui import investigation_page as module
    monkeypatch.setattr(module, "analyze_software", lambda *a: Investigation("模拟软件结果"))
    monkeypatch.setattr(module, "inspect_peripherals", lambda *a: Investigation("模拟外设结果"))
    monkeypatch.setattr(module, "collect_timeline", lambda *a: Investigation("模拟时间线结果"))
    for button, title in (("Run Software Checks", "模拟软件结果"), ("Check Selected Device Type", "模拟外设结果"), ("Build Troubleshooting Timeline", "模拟时间线结果")):
        # Bluetooth avoids opening/playing any audio device during this test.
        page.peripheral.setCurrentText("蓝牙")
        click(page, button)
        await_idle(page)
        assert title in page.report
    assert len(page.history.list_records()) == 3
    page.close()


def test_test_print_requires_separate_confirmation_without_printing(tmp_path, monkeypatch):
    app()
    page = InvestigationPage(history=DiagnosticHistoryStore(tmp_path))
    from helppack.ui import investigation_page as module
    monkeypatch.setattr(module.QPrinterInfo, "availablePrinterNames", lambda: ["虚构打印机"])
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: QMessageBox.StandardButton.No)
    def forbidden(*args):
        raise AssertionError("用户拒绝时不允许创建打印任务")
    monkeypatch.setattr(module, "QPrinter", forbidden)
    page.refresh_printers()
    page.test_print()
    page.close()


def test_monitor_actual_resource_sampling_mark_stop_and_persist(tmp_path):
    app()
    page = InvestigationPage(history=DiagnosticHistoryStore(tmp_path))
    page.start_monitor()
    deadline = time.monotonic() + 5
    while not page.monitor_buffer.samples and time.monotonic() < deadline:
        QTest.qWait(10)
    assert page.monitor_buffer.samples
    page.mark_incident()
    page.stop_monitor()
    deadline = time.monotonic() + 5
    while page.monitor_thread is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    assert page.monitor_thread is None
    assert 'Monitoring stopped' in page.monitor_status.text()
    assert "incidents" in page.report
    assert not page.monitor_buffer.incidents[0]["complete"]
    assert page.history.list_records()[0]["kind"] == 'Monitoring'
    page.close()


def test_screenshot_mask_crop_undo_zip_uses_clean_copy(tmp_path):
    app()
    original = tmp_path / "original.png"
    image = QImage(100, 80, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    image.setText("Private", "secret@example.com")
    assert image.save(str(original))
    original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    editor = ScreenshotEditor(original)
    editor.canvas.apply_rect(QRect(10, 10, 20, 20), "遮挡")
    assert editor.canvas.image.pixelColor(15, 15) == QColor("black")
    editor.canvas.apply_rect(QRect(0, 0, 50, 40), "裁剪")
    assert editor.canvas.image.width() == 50
    editor.canvas.undo()
    assert editor.canvas.image.width() == 100
    processed = tmp_path / "processed.png"
    assert editor.canvas.image.save(str(processed))
    assert not QImage(str(processed)).textKeys()
    bundle = ReportBundle(ProblemDetails("其他问题", "虚构", "合成测试"), SystemSnapshot(),
                          [Attachment(original, "screenshot_01.png", processed_path=processed)])
    output = export_zip("合成示例报告", bundle, tmp_path / "test.zip")
    with zipfile.ZipFile(output) as archive:
        assert archive.read("attachments/screenshot_01.png") == processed.read_bytes()
        manifest = json.loads(archive.read("manifest.json"))
        for entry in manifest["files"]:
            assert hashlib.sha256(archive.read(entry["name"])).hexdigest() == entry["sha256"]
        assert str(tmp_path) not in json.dumps(manifest)
    assert hashlib.sha256(original.read_bytes()).hexdigest() == original_hash
    editor.reject()


def test_summary_uses_edited_preview_and_unresolved_fields():
    app()
    window = MainWindow()
    window.preview_edit.setPlainText("## 问题摘要\n虚构问题\n## 仍未解决的问题\n仍然闪退，联系 test@example.com\n## 已尝试的操作\n已重启")
    window._copy_report_summary()
    copied = app().clipboard().text()
    assert "仍然闪退" in copied and "已重启" in copied
    assert "test@example.com" not in copied
    window.close()


def test_audio_test_uses_only_selected_sink_not_system_volume(tmp_path, monkeypatch):
    app()
    page = InvestigationPage(history=DiagnosticHistoryStore(tmp_path))
    from helppack.ui import investigation_page as module
    class Device:
        def isFormatSupported(self, audio_format):
            return True
    class Sink:
        def __init__(self, device, audio_format, parent):
            self.device = device
        def setVolume(self, volume):
            self.volume = volume
        def start(self, buffer):
            self.bytes = buffer.size()
        def stop(self):
            self.stopped = True
        def deleteLater(self):
            pass
    monkeypatch.setattr(module, "QAudioSink", Sink)
    page.audio_devices = [Device()]
    page.outputs.addItem("虚构输出")
    page.play_test()
    assert page.audio_sink.bytes == 192000
    assert page.audio_sink.volume == 0.2
    assert page.audio_sink.device is page.audio_devices[0]
    page.stop_audio()
    page.close()
