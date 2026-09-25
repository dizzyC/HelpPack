import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea

from helppack.attachments import add_attachments
from helppack.models import ProblemDetails, SystemSnapshot
from helppack.ui.main_window import MainWindow


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_help_package_flow_switches_pages_and_edits_preview(tmp_path: Path) -> None:
    _application = app()
    window = MainWindow()
    window.show()
    _application.processEvents()
    assert window.stack.count() == 7
    assert window.stack.currentIndex() == 0
    assert window.findChildren(QScrollArea)

    window._go(1, "1 / 5  描述问题")
    window.title_input.setText("虚构测试故障")
    window.description_input.setPlainText("这是虚构描述")
    window.attempted_input.setPlainText("已经虚构地重启")
    image = tmp_path / "fake.png"
    image.write_bytes(b"test png")
    window.attachments = add_attachments([], [image])
    window._sync_attachment_list()
    assert window.attachment_list.count() == 1
    window.attachment_list.item(0).setSelected(True)
    window._remove_screenshot()
    assert window.attachment_list.count() == 0

    window.problem = ProblemDetails("其他问题", "虚构测试故障", "这是虚构描述", attempted_solutions="已经虚构地重启")
    window.snapshot = SystemSnapshot(cpu="Example CPU", logical_cores="8")
    window._populate_privacy_attachments()
    window._prepare_preview()
    assert window.stack.currentIndex() == 4
    assert "虚构测试故障" in window.preview_edit.toPlainText()
    window.field_checks["cpu"].setChecked(False)
    window._refresh_preview()
    assert "Example CPU" not in window.preview_edit.toPlainText()
    window.preview_edit.appendPlainText("用户可编辑内容")
    assert "用户可编辑内容" in window.preview_edit.toPlainText()
    window.close()


def test_diagnostic_cancel_control_sets_thread_safe_event() -> None:
    application = app()
    window = MainWindow()
    window._open_diagnostics()

    class FakeWorker:
        def __init__(self):
            import threading

            self.cancel_event = threading.Event()

    worker = FakeWorker()
    window.diagnostic_page.worker = worker
    window.diagnostic_page.request_cancel()
    application.processEvents()
    assert worker.cancel_event.is_set()
    assert "正在取消" in window.diagnostic_page.scan_status.text()
    window.diagnostic_page.worker = None
    window.close()


def test_visible_chinese_strings_have_no_replacement_character() -> None:
    app()
    window = MainWindow()
    texts = [label.text() for label in window.findChildren(__import__("PySide6.QtWidgets").QtWidgets.QLabel)]
    texts += [button.text() for button in window.findChildren(__import__("PySide6.QtWidgets").QtWidgets.QPushButton)]
    assert texts
    assert all("�" not in text for text in texts)
    window.close()
