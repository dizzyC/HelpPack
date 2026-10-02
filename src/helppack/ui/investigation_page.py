from __future__ import annotations

import math
import struct
import threading
import time
from dataclasses import asdict
from datetime import datetime

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QObject,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QPainter
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..diagnostics.history import DiagnosticHistoryStore, compare_summaries
from ..diagnostics.investigation import Finding, Investigation
from ..diagnostics.monitoring import MonitorBuffer, ResourceSampler
from ..diagnostics.network_layers import investigate_network
from ..diagnostics.peripherals import inspect_peripherals
from ..diagnostics.reporting import generate_diagnostic_markdown
from ..diagnostics.software_analysis import (
    SCENARIOS,
    analyze_software,
    running_programs,
)
from ..diagnostics.storage_analysis import (
    SpaceScan,
    quarantine_one,
    recovery_receipts,
    restore_one,
    scan_directory,
)
from ..diagnostics.symptoms import PRESETS, diagnose_symptom, route_symptom
from ..diagnostics.timeline import collect_timeline
from ..redaction import redact_text


class TaskWorker(QObject):
    progress = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, function):
        super().__init__()
        self.function = function
        self.cancel = threading.Event()

    @Slot()
    def run(self):
        try:
            self.completed.emit(self.function(self.cancel, self.progress.emit))
        except Exception as exc:  # noqa: BLE001 - GUI worker boundary
            message = str(exc) if isinstance(exc, (ValueError, InterruptedError)) else f"检查未完成：{type(exc).__name__}（权限、接口或文件可能不可用）"
            self.failed.emit(redact_text(message))
        finally:
            self.finished.emit()


class MonitorWorker(QObject):
    sampled = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.cancel = threading.Event()

    @Slot()
    def run(self):
        start = time.monotonic()
        try:
            sampler = ResourceSampler()
            while not self.cancel.is_set() and time.monotonic() - start <= 7200:
                self.sampled.emit(sampler.sample(time.monotonic() - start))
                if self.cancel.wait(2):
                    break
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"监测停止：{type(exc).__name__}")
        finally:
            self.finished.emit()


class InvestigationPage(QWidget):
    go_home = Signal()
    add_to_help_pack = Signal(str)

    def __init__(self, parent=None, history=None):
        super().__init__(parent)
        self.history = history or DiagnosticHistoryStore()
        self.thread = None
        self.worker = None
        self.monitor_thread = None
        self.monitor_worker = None
        self.last_scan = None
        self.receipts = []
        self.report = ""
        self.audio_sink = None
        self.audio_timer = QTimer(self)
        self.audio_timer.setSingleShot(True)
        self.audio_timer.timeout.connect(self.stop_audio)
        layout = QVBoxLayout(self)
        title = QLabel("专项排查与问题记录")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.tabs = QTabWidget()
        for name, build in (("症状", self.symptom_tab), ("网络", self.network_tab), ("软件", self.software_tab),
                            ("空间", self.storage_tab), ("外设", self.peripheral_tab), ("历史", self.history_tab),
                            ("时间线", self.timeline_tab), ("监测", self.monitor_tab)):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(build())
            self.tabs.addTab(scroll, name)
        splitter.addWidget(self.tabs)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("检查结果、证据与下一步会显示在这里，可滚动选择复制。")
        splitter.addWidget(self.output)
        splitter.setSizes([330, 220])
        layout.addWidget(splitter, 1)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel("默认只读；网址/指定 DNS 检查会联网，声音与打印只由用户主动触发。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        nav = QHBoxLayout()
        for label, action in (("返回首页", self.go_home.emit), ("取消当前检查", self.cancel_task),
                              ("复制简洁摘要", self.copy_summary), ("加入求助报告", self.attach_report)):
            button = QPushButton(label)
            button.clicked.connect(action)
            nav.addWidget(button)
        layout.addLayout(nav)

    @property
    def is_running(self):
        return self.thread is not None and self.thread.isRunning()

    def page(self, explanation):
        page = QWidget()
        body = QVBoxLayout(page)
        label = QLabel(explanation)
        label.setWordWrap(True)
        body.addWidget(label)
        return page, body

    def button(self, body, text, function):
        button = QPushButton(text)
        button.clicked.connect(function)
        body.addWidget(button)
        return button

    def symptom_tab(self):
        page, body = self.page("本地关键词路由，不上传症状、不使用远程 AI；匹配检查不等于认定故障原因。")
        self.preset = QComboBox()
        self.preset.addItems(PRESETS)
        self.symptom = QLineEdit()
        self.symptom.setPlaceholderText("自行描述症状，留空则使用上面的预设")
        body.addWidget(self.preset)
        body.addWidget(self.symptom)
        self.plan = QLabel()
        self.plan.setWordWrap(True)
        body.addWidget(self.plan)
        self.symptom.textChanged.connect(self.preview_route)
        self.preset.currentTextChanged.connect(self.preview_route)
        self.button(body, "按症状开始只读诊断", self.start_symptom)
        self.preview_route()
        body.addStretch()
        return page

    def preview_route(self, *args):
        text = self.symptom.text().strip() or self.preset.currentText()
        self.plan.setText("将检查：" + "、".join(route_symptom(text)))

    def start_symptom(self):
        text = self.symptom.text().strip() or self.preset.currentText()
        def check(cancel, progress):
            summary, failed = diagnose_symptom(text, cancel, progress)
            guidance = "\n\n专项下一步：仅某个网站失败请在“网络”页填写实际网址；软件问题请在“软件”页选择对应 EXE 与场景；耳机问题请在“外设”页检查实际输出及静音/音量。向导不会假设尚未提供的目标。"
            return (summary, "## 症状向导\n\n" + redact_text(text) + "\n\n" + generate_diagnostic_markdown(summary) + "\n\n优先查看有证据的提醒：" + ("、".join(failed) or "没有检测到明确异常，不代表不存在故障") + guidance)
        self.run_task(check, "symptom")

    def network_tab(self):
        page, body = self.page("会向你输入的网站发送 HTTPS HEAD 请求，并向指定 DNS 发送该域名。不修改系统 DNS；不绕过证书、不跟随重定向。PAC 自动脚本不能完整模拟。")
        self.url = QLineEdit("https://www.microsoft.com/")
        self.dns = QLineEdit()
        self.dns.setPlaceholderText("可选 DNS 服务器 IP，由你决定；留空不发送指定 DNS 查询")
        form = QFormLayout()
        form.addRow("目标网址", self.url)
        form.addRow("指定 DNS", self.dns)
        body.addLayout(form)
        self.button(body, "开始网络分层检查", self.start_network)
        body.addStretch()
        return page

    def start_network(self):
        target, dns = self.url.text().strip(), self.dns.text().strip()
        self.run_task(lambda cancel, progress: investigate_network(target, dns, cancel, progress), "network")

    def software_tab(self):
        page, body = self.page("只读检查所选 EXE，不执行它。签名或依赖存在不证明程序健康；第三方拦截日志可能不可读取。")
        self.programs = QComboBox()
        self.exe = QLineEdit()
        self.scenario = QComboBox()
        self.scenario.addItems(SCENARIOS)
        body.addWidget(self.programs)
        self.programs.currentIndexChanged.connect(self.select_program)
        self.button(body, "刷新正在运行的程序", lambda: self.run_task(lambda c, p: running_programs(), "processes"))
        self.button(body, "选择 EXE", self.choose_exe)
        body.addWidget(self.exe)
        body.addWidget(self.scenario)
        self.button(body, "开始软件专项检查", self.start_software)
        body.addStretch()
        return page

    def select_program(self, index):
        path = self.programs.itemData(index)
        if path:
            self.exe.setText(path)

    def choose_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择待诊断程序（不会运行）", "", "程序 (*.exe)")
        if path:
            self.exe.setText(path)

    def start_software(self):
        path, scenario = self.exe.text().strip(), self.scenario.currentText()
        self.run_task(lambda c, p: analyze_software(path, scenario, c, p), "software")

    def storage_tab(self):
        page, body = self.page("只扫描主动选择的目录；跳过链接、无权访问与隔离区，最多 20 万项/120 秒。仅缓存候选可逐项移入同盘隔离区，原图/用户文件不自动删除。同盘移出不会释放该分区空间。")
        self.directory = QLineEdit()
        body.addWidget(self.directory)
        self.button(body, "选择目录", self.choose_directory)
        self.button(body, "扫描目录与分区空间", self.start_storage)
        self.files = QListWidget()
        body.addWidget(self.files)
        self.button(body, "预览并移出选中的一个缓存文件", self.move_cache)
        self.button(body, "恢复当前目录最近移出的文件（重扫后可恢复）", self.restore_cache)
        return page

    def choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, "选择空间分析范围")
        if path:
            self.directory.setText(path)

    def start_storage(self):
        path = self.directory.text().strip()
        self.run_task(lambda c, p: scan_directory(path, c, p), "storage")

    def move_cache(self):
        row = self.files.currentItem()
        if row is None or self.last_scan is None or self.is_running:
            return
        entry = row.data(Qt.ItemDataRole.UserRole)
        if not entry.category.startswith("缓存"):
            QMessageBox.information(self, "不自动清理", "这是应用文件或用户文件，不作为缓存移出。")
            return
        question = f"具体文件：{entry.path}\n大小：{entry.size} 字节\n分类：{entry.category}\n影响：缓存可能重建；运行中的程序可能受影响。不会永久删除，会移到同盘隔离区，不会释放该分区空间。\n是否只移出这一文件？"
        if QMessageBox.warning(self, "确认单项清理", question, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        scan = self.last_scan
        self.run_task(lambda c, p: quarantine_one(scan, entry, confirmed=True), "cleanup")

    def restore_cache(self):
        if not self.receipts or self.is_running:
            return
        if QMessageBox.question(self, "恢复缓存文件", "恢复本次最近移出的文件？不覆盖原位置的同名文件。", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        receipt = self.receipts[-1]
        self.run_task(lambda c, p: restore_one(receipt, confirmed=True), "restore")

    def peripheral_tab(self):
        page, body = self.page("默认只读；试听不会修改系统音量。测试打印需单独确认，可能消耗纸张/墨粉，队列成功不等于实体打印成功。")
        self.peripheral = QComboBox()
        self.peripheral.addItems(["声音", "蓝牙", "打印机"])
        body.addWidget(self.peripheral)
        self.button(body, "检查所选外设", self.start_peripheral)
        self.outputs = QComboBox()
        body.addWidget(self.outputs)
        self.button(body, "刷新输出设备（标记默认）", self.refresh_audio)
        self.button(body, "低音量试听两秒", self.play_test)
        self.printers = QComboBox()
        body.addWidget(self.printers)
        self.button(body, "刷新可用打印机", self.refresh_printers)
        self.button(body, "确认打印一页 HelpPack 测试页", self.test_print)
        body.addStretch()
        return page

    def start_peripheral(self):
        kind = self.peripheral.currentText()
        audio = None
        if kind == "声音":
            self.refresh_audio()
            audio = Finding("声音输出设备与默认设备", "已读取", "、".join(self.outputs.itemText(i) for i in range(self.outputs.count())) or "未检测到输出设备")
        def check(cancel, progress):
            result = inspect_peripherals(kind, cancel, progress)
            if audio:
                result.findings.insert(0, audio)
            return result
        self.run_task(check, "peripherals")

    def refresh_audio(self):
        self.audio_devices = QMediaDevices.audioOutputs()
        default = QMediaDevices.defaultAudioOutput()
        self.outputs.clear()
        for device in self.audio_devices:
            self.outputs.addItem(device.description() + ("（默认）" if device.id() == default.id() else ""))
        self.status.setText(f"读取到 {len(self.audio_devices)} 个输出设备；没有设备时不能试听。")

    def play_test(self):
        index = self.outputs.currentIndex()
        if index < 0 or not hasattr(self, "audio_devices"):
            QMessageBox.information(self, "请选择输出", "先刷新并选择一个输出设备。")
            return
        self.stop_audio()
        device = self.audio_devices[index]
        audio_format = QAudioFormat()
        audio_format.setSampleRate(48000)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(audio_format):
            self.status.setText("此输出不支持当前试听格式，未播放。")
            return
        pcm = b"".join(struct.pack("<h", int(1500 * math.sin(2 * math.pi * 440 * i / 48000))) for i in range(96000))
        self.audio_buffer = QBuffer(self)
        self.audio_buffer.setData(QByteArray(pcm))
        self.audio_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.audio_sink = QAudioSink(device, audio_format, self)
        self.audio_sink.setVolume(0.2)
        self.audio_sink.start(self.audio_buffer)
        self.status.setText("试听已发送到所选设备；请你确认是否听见。未调整系统静音或音量。")
        self.audio_timer.start(2500)

    def stop_audio(self):
        self.audio_timer.stop()
        if self.audio_sink:
            self.audio_sink.stop()
            self.audio_sink.deleteLater()
            self.audio_sink = None
        if hasattr(self, "audio_buffer"):
            self.audio_buffer.close()
            self.audio_buffer.deleteLater()
            del self.audio_buffer

    def refresh_printers(self):
        self.printers.clear()
        self.printers.addItems(QPrinterInfo.availablePrinterNames())

    def test_print(self):
        if self.is_running:
            self.status.setText("请先等待或取消当前检查，再单独确认测试打印。")
            return
        name = self.printers.currentText()
        if not name or name not in QPrinterInfo.availablePrinterNames():
            QMessageBox.information(self, "打印机不可用", "请刷新并选择系统中存在的打印机。")
            return
        if QMessageBox.warning(self, "单独确认测试打印", f"将向“{name}”提交一页测试页，会消耗纸张/墨粉或打开虚拟打印保存窗口。是否继续？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        def submit(cancel, progress):
            if cancel.is_set():
                raise InterruptedError("未提交，已取消")
            progress(20, "提交已确认的测试页；不强制终止打印驱动")
            printer = QPrinter()
            printer.setPrinterName(name)
            printer.setDocName("HelpPack 测试页")
            painter = QPainter()
            if not painter.begin(printer):
                raise ValueError("未能提交打印任务，请检查队列和权限")
            painter.drawText(100, 150, "HelpPack 测试页 · 请核对所选打印机")
            finished = painter.end()
            if not finished:
                raise ValueError("打印驱动未确认完成提交，请检查队列")
            return Investigation("测试打印记录", findings=[Finding("用户确认的打印机", "已提交（实体结果未验证）", name)], recommendations=["请核对队列和实体输出，提交不等于打印成功。提交后的队列任务不会因取消检查而自动撤销。"])
        self.run_task(submit, "test_print")

    def history_tab(self):
        page, body = self.page("历史保存在本机且自动脱敏；状态由你标记。选择两条同类诊断可比较，指标变化不证明修复因果。")
        self.records = QListWidget()
        self.records.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        body.addWidget(self.records)
        self.button(body, "刷新本地历史", self.refresh_history)
        self.button(body, "查看选中记录", self.show_history)
        self.button(body, "比较两条记录", self.compare_history)
        self.disposition = QComboBox()
        self.disposition.addItems(["已解决", "未解决", "稍后处理"])
        body.addWidget(self.disposition)
        self.button(body, "标记当前问题处理状态", self.mark_history)
        return page

    def refresh_history(self):
        current = self.records.currentItem()
        selected_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.records.clear()
        for record in self.history.list_records():
            summary = record.get("summary", {})
            timestamp = record.get("time") or summary.get("finished_at", "时间未知")
            row = QListWidgetItem(f"{timestamp} · {record.get('kind', '')} · {record.get('status', '稍后处理')}")
            row.setData(Qt.ItemDataRole.UserRole, record["id"])
            self.records.addItem(row)
            if record["id"] == selected_id:
                self.records.setCurrentItem(row)

    def show_history(self):
        row = self.records.currentItem()
        if row:
            try:
                import json
                value = self.history.load_record(row.data(Qt.ItemDataRole.UserRole))
                self.show_report("## 本地问题处理记录\n\n" + str(value.get("report", "")) + "\n\n```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```")
            except (OSError, ValueError, TypeError):
                self.status.setText("历史记录无法读取。")

    def mark_history(self):
        row = self.records.currentItem()
        if row:
            try:
                self.history.mark(row.data(Qt.ItemDataRole.UserRole), self.disposition.currentText())
                self.refresh_history()
            except (OSError, ValueError, TypeError):
                self.status.setText("处理状态保存失败。")

    def compare_history(self):
        selected = self.records.selectedItems()
        if len(selected) != 2:
            QMessageBox.information(self, "选择两条", "请用 Ctrl 选择两条同类诊断记录。")
            return
        try:
            values = [self.history.load_record(item.data(Qt.ItemDataRole.UserRole)) for item in selected]
            values.sort(key=lambda r: r.get("time", r.get("summary", {}).get("finished_at", "")))
            if not all("summary" in value for value in values) or values[0]["kind"] != values[1]["kind"]:
                raise ValueError("这两条不是结构化诊断记录")
            if values[0]["summary"].get("subject") != values[1]["summary"].get("subject"):
                raise ValueError("检查目标或场景不同，不能作为同一问题的前后对比")
            changes = compare_summaries(values[0]["summary"], values[1]["summary"])
            self.show_report("## 前后对比（时间变化不证明因果）\n\n" + "\n\n".join(changes))
        except (OSError, ValueError, TypeError) as exc:
            self.status.setText(redact_text(str(exc)))

    def timeline_tab(self):
        page, body = self.page("按时间整合可读取的安装、驱动配置、更新、崩溃和异常关机事件。最近 30 天、有界查询，不声称时间相邻就是原因。")
        self.button(body, "生成故障时间线", lambda: self.run_task(collect_timeline, "timeline"))
        body.addStretch()
        return page

    def monitor_tab(self):
        page, body = self.page("由你主动开启，每两秒采样资源计数，不采集私人内容。默认保留最近 10 分钟，最长两小时。故障标记保存前 60 秒和后 30 秒；提前停止保留不完整片段。退出后停止。")
        self.monitor_status = QLabel("监测未开启")
        self.monitor_status.setWordWrap(True)
        body.addWidget(self.monitor_status)
        self.button(body, "开启间歇性故障监测", self.start_monitor)
        self.button(body, "刚才出问题了", self.mark_incident)
        self.button(body, "停止监测并查看记录", self.stop_monitor)
        body.addStretch()
        return page

    def start_monitor(self):
        if self.monitor_thread is not None:
            return
        self.monitor_buffer = MonitorBuffer()
        self.monitor_error = ""
        self.monitor_thread = QThread(self)
        self.monitor_worker = MonitorWorker()
        self.monitor_worker.moveToThread(self.monitor_thread)
        self.monitor_thread.started.connect(self.monitor_worker.run)
        self.monitor_worker.sampled.connect(self.monitor_sample)
        self.monitor_worker.failed.connect(self.monitor_failed)
        self.monitor_worker.finished.connect(self.monitor_thread.quit, Qt.ConnectionType.DirectConnection)
        self.monitor_worker.finished.connect(self.monitor_worker.deleteLater)
        self.monitor_thread.finished.connect(self.monitor_finished)
        self.monitor_thread.start()
        self.monitor_status.setText("监测开启，2 秒一次，最长两小时")

    @Slot(object)
    def monitor_sample(self, sample):
        if self.monitor_buffer.append(sample):
            self.monitor_status.setText(f"监测中 {sample['elapsed']:.0f} 秒 · CPU {sample['cpu_percent']}% · 内存 {sample['memory_percent']}% · 缓存 {len(self.monitor_buffer.samples)} 项 · 最近采样耗时 {sample['sampler_ms']} ms（不是应用全部资源开销）")

    @Slot(str)
    def monitor_failed(self, text):
        self.monitor_error = text
        self.monitor_status.setText(text)

    def mark_incident(self):
        if not hasattr(self, "monitor_buffer") or self.monitor_buffer.stopped:
            self.monitor_status.setText("请先开启监测。")
            return
        try:
            self.monitor_buffer.mark_incident()
            self.status.setText("已保留故障前片段，接下来还会采集后 30 秒。")
        except ValueError as exc:
            self.status.setText(str(exc))

    def stop_monitor(self):
        if self.monitor_worker:
            self.monitor_worker.cancel.set()
            self.monitor_buffer.stop()

    @Slot()
    def monitor_finished(self):
        thread = self.monitor_thread
        if thread is not None and not thread.wait(100):
            QTimer.singleShot(10, self.monitor_finished)
            return
        if thread is not None:
            thread.deleteLater()
        self.monitor_thread = None
        self.monitor_worker = None
        self.monitor_buffer.stop()
        self.monitor_status.setText("监测已停止；应用不会在后台继续监测。")
        report = self.monitor_buffer.markdown()
        if self.monitor_error:
            report += "\n\n提前停止原因：" + redact_text(self.monitor_error)
            self.monitor_status.setText(self.monitor_error + "；已保留现有采样。")
        self.show_report(report)
        self.save_report("监测", report)

    def run_task(self, function, kind):
        if self.is_running:
            self.status.setText("请等待或取消当前检查。")
            return
        self.kind = kind
        self.thread = QThread(self)
        self.worker = TaskWorker(function)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.completed.connect(self.task_completed)
        self.worker.failed.connect(self.task_failed)
        self.worker.finished.connect(self.thread.quit, Qt.ConnectionType.DirectConnection)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.task_finished)
        self.progress.setRange(0, 0)
        self.status.setText("后台检查中，可取消；不会阻塞界面。")
        self.thread.start()

    @Slot(int, str)
    def on_progress(self, percent, text):
        self.progress.setRange(0, 100) if percent else self.progress.setRange(0, 0)
        self.progress.setValue(percent)
        self.status.setText(text)

    @Slot(str)
    def task_failed(self, text):
        self.status.setText(text)

    @Slot(object)
    def task_completed(self, result):
        if self.kind == "processes":
            self.programs.clear()
            for name, path, pid in result:
                self.programs.addItem(f"{name} · PID {pid}", path)
            self.status.setText(f"列出 {len(result)} 个可读取程序，路径仅用于你选择的检查。")
            return
        summary = None
        if self.kind == "symptom":
            summary, report = result
        elif isinstance(result, SpaceScan):
            self.last_scan = result
            self.receipts = recovery_receipts(result.root)
            self.files.clear()
            for entry in sorted(result.files, key=lambda e: e.size, reverse=True)[:500]:
                row = QListWidgetItem(f"{entry.path.relative_to(result.root)} · {entry.size / 2**20:.2f} MiB · {entry.category}")
                row.setData(Qt.ItemDataRole.UserRole, entry)
                self.files.addItem(row)
            report = result.markdown()
        elif self.kind == "cleanup":
            self.receipts.append(result)
            target = str(result.source.relative_to(result.root))
            report = f"## 单项清理记录\n\n用户确认的目录内目标：{target}\n\n已移入同盘隔离区，原位置的文件不再存在。重扫所选目录后也可恢复，不会覆盖同名文件；本次只移出一个文件，未永久删除，未释放该分区空间。"
        elif self.kind == "restore":
            restored = self.receipts.pop()
            report = "## 恢复记录\n\n本次所选缓存已恢复原位置，目录内目标：" + str(restored.source.relative_to(restored.root))
        else:
            report = result.markdown() if isinstance(result, Investigation) else str(result)
            if isinstance(result, Investigation):
                summary = {"finished_at": result.timestamp, "subject": result.title + "：" + result.symptom, "results": [
                    {"check_id": finding.layer, "display_name": finding.layer, "status": finding.state,
                     "evidence": [{"label": "检查证据", "value": finding.detail}]} for finding in result.findings
                ]}
        self.show_report(report)
        self.status.setText("检查完成，结果与验证边界见下方；可加入报告或复制摘要。")
        self.save_report(self.kind, report, summary)

    def save_report(self, kind, report, summary=None):
        try:
            value = {"kind": kind, "time": datetime.now().astimezone().isoformat(), "status": "稍后处理", "report": report, "operations": []}
            if summary:
                value["summary"] = summary if isinstance(summary, dict) else asdict(summary)
            if kind in {"cleanup", "restore", "test_print"}:
                value["operations"] = [{"action": kind, "confirmed": True, "result": report}]
            self.history.save_record(value)
        except OSError:
            self.status.setText("结果已显示，但本地历史保存失败；请手动保留。")

    def show_report(self, text):
        self.report = redact_text(text)
        self.output.setPlainText(self.report)

    @Slot()
    def task_finished(self):
        thread = self.thread
        if thread is not None and not thread.wait(100):
            QTimer.singleShot(10, self.task_finished)
            return
        if thread is not None:
            thread.deleteLater()
        self.thread = self.worker = None
        self.progress.setRange(0, 100)

    def cancel_task(self):
        if self.worker:
            self.worker.cancel.set()
            self.status.setText("正在取消，当前有界系统查询结束后停止。")

    def copy_summary(self):
        if self.report:
            from ..report import concise_summary
            QApplication.clipboard().setText(concise_summary(self.report))
            self.status.setText("脱敏后的简洁摘要已复制；粘贴发送前请再检查。")

    def attach_report(self):
        if self.report:
            self.add_to_help_pack.emit(self.report)
