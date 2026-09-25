from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, Qt, QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
)

from helppack.diagnostics import DiagnosticEngine
from helppack.diagnostics.models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
    SafetyLevel,
    Severity,
)
from helppack.diagnostics.workers import DiagnosticWorker
from helppack.ui.font import configure_local_font
from helppack.ui.main_window import MainWindow


class SlowCheck:
    check_id = "ui.slow"
    display_name = "后台响应测试"
    categories = frozenset({"测试"})

    def run(self, context):
        for _ in range(8):
            context.wait(0.05)
        return [
            DiagnosticResult(
                check_id=self.check_id,
                category="测试",
                display_name=self.display_name,
                status=DiagnosticStatus.NORMAL,
                severity=Severity.INFO,
                evidence=[Evidence("结果", "完成")],
                explanation="测试",
                confidence="高",
                recommendations=["无"],
                safety_level=SafetyLevel.L0,
            )
        ]


def button(window: MainWindow, text: str) -> QPushButton:
    return next(item for item in window.findChildren(QPushButton) if item.text() == text)


def verify_background_responsiveness(app: QApplication) -> tuple[int, bool]:
    engine = DiagnosticEngine(checks=[SlowCheck()])
    worker = DiagnosticWorker("测试", engine=engine)
    thread = QThread()
    worker.moveToThread(thread)
    loop = QEventLoop()
    ticks = {"count": 0}
    summaries = []
    timer = QTimer()
    timer.setInterval(25)
    timer.timeout.connect(lambda: ticks.update(count=ticks["count"] + 1))
    worker.completed.connect(summaries.append)
    worker.finished.connect(thread.quit)
    thread.finished.connect(loop.quit)
    thread.started.connect(worker.run)
    timer.start()
    thread.start()
    loop.exec()
    timer.stop()
    thread.wait()
    app.processEvents()
    return ticks["count"], bool(summaries and not summaries[0].cancelled)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    selected_font = configure_local_font(app)
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    app.processEvents()
    if window.size().width() != 1200 or window.size().height() != 800:
        raise AssertionError("窗口缩放失败")
    if not window.findChildren(QScrollArea):
        raise AssertionError("未发现滚动区域")

    output = Path("dist") / "validation"
    output.mkdir(parents=True, exist_ok=True)
    home_image = output / "ui_home.png"
    window.grab().save(str(home_image), "PNG")

    QTest.mouseClick(button(window, "创建求助包"), Qt.MouseButton.LeftButton)
    app.processEvents()
    if window.stack.currentIndex() != 1:
        raise AssertionError("创建求助包页面切换失败")
    QTest.mouseClick(button(window, "返回"), Qt.MouseButton.LeftButton)
    app.processEvents()
    QTest.mouseClick(button(window, "本机诊断"), Qt.MouseButton.LeftButton)
    app.processEvents()
    if window.stack.currentIndex() != 6:
        raise AssertionError("本机诊断页面切换失败")
    diagnostic_image = output / "ui_diagnostic.png"
    window.grab().save(str(diagnostic_image), "PNG")

    window._go(1, "1 / 5  描述问题")
    messages = []
    with patch.object(QMessageBox, "information", side_effect=lambda _parent, title, text: messages.append((title, text))):
        window._start_collection()
    if not messages or "请填写" not in messages[0][1]:
        raise AssertionError("表单错误信息不清晰")

    labels = [item.text() for item in window.findChildren(QLabel)]
    buttons = [item.text() for item in window.findChildren(QPushButton)]
    if any("�" in value for value in labels + buttons):
        raise AssertionError("界面存在乱码替换字符")

    ticks, completed = verify_background_responsiveness(app)
    if ticks < 5 or not completed:
        raise AssertionError("后台扫描期间界面事件循环未保持响应")

    cancel_engine = DiagnosticEngine(checks=[SlowCheck(), SlowCheck()])
    cancel = threading.Event()
    cancel_timer = threading.Timer(0.08, cancel.set)
    cancel_timer.start()
    cancel_summary = cancel_engine.scan("测试", cancel_event=cancel)
    cancel_timer.join()
    if not cancel_summary.cancelled:
        raise AssertionError("取消状态未生效")

    window.close()
    app.processEvents()
    result = {
        "status": "ok",
        "window_resize": "1200x800",
        "page_switching": True,
        "scroll_areas": len(window.findChildren(QScrollArea)),
        "chinese_replacement_characters": 0,
        "selected_font": selected_font,
        "background_event_ticks": ticks,
        "cancelled_scan": True,
        "user_friendly_validation_message": True,
        "screenshots": [str(home_image.resolve()), str(diagnostic_image.resolve())],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
