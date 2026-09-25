from __future__ import annotations

import html

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..diagnostics.history import DiagnosticHistoryStore
from ..diagnostics.models import RepairSuggestion, SafetyLevel, ScanSummary
from ..diagnostics.repairs import RepairCoordinator, RepairError
from ..diagnostics.reporting import generate_diagnostic_markdown
from ..diagnostics.workers import DiagnosticWorker

DIAGNOSTIC_CATEGORIES = [
    "系统卡顿",
    "软件或浏览器异常",
    "网络或Wi-Fi异常",
    "声音问题",
    "蓝牙问题",
    "打印机问题",
    "Windows更新问题",
    "蓝屏或异常重启",
    "电池或磁盘健康",
    "综合检查",
]


class DiagnosticPage(QWidget):
    go_home = Signal()
    add_to_help_pack = Signal(str)
    phase_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.summary: ScanSummary | None = None
        self.thread: QThread | None = None
        self.worker: DiagnosticWorker | None = None
        self.coordinator = RepairCoordinator()
        self.history = DiagnosticHistoryStore()
        self.last_operation_message = ""
        self.rollback_ids: list[str] = self.coordinator.backups.list_ids()

        layout = QVBoxLayout(self)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._selection_page())
        self.pages.addWidget(self._scan_page())
        self.pages.addWidget(self._results_page())
        layout.addWidget(self.pages)

    @property
    def is_running(self) -> bool:
        return self.thread is not None and self.thread.isRunning()

    def show_start(self) -> None:
        self.pages.setCurrentIndex(0)
        self.phase_changed.emit("本机诊断 · 选择问题")
        latest = self.history.load_latest()
        if latest:
            self.history_label.setText(
                f"上次只读扫描：{latest.get('finished_at', '时间未知')} · {latest.get('category', '类型未知')}。历史结果已脱敏保存在本机。"
            )
        else:
            self.history_label.setText("尚无本机诊断历史。")

    def request_cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel_event.set()
            self.scan_status.setText("正在取消；当前检查结束后不会继续后续项目…")

    def _selection_page(self) -> QWidget:
        page = QWidget()
        body = QVBoxLayout(page)
        heading = QLabel("本机诊断")
        heading.setObjectName("pageTitle")
        body.addWidget(heading)
        description = QLabel("选择最接近的问题。默认扫描只运行 L0 只读检查，不会修改系统设置、结束进程或清理文件。")
        description.setObjectName("subtitle")
        description.setWordWrap(True)
        body.addWidget(description)
        notice = QFrame()
        notice.setObjectName("notice")
        notice_layout = QVBoxLayout(notice)
        notice_layout.addWidget(QLabel("安全边界"))
        safety = QLabel(
            "检查结论会展示证据和可信度。只有你选择一个具体修复、查看影响/权限/回滚方式并再次确认后，应用才可能执行该单项操作。综合检查不会运行 SFC、DISM、网络重置或深度磁盘检查。"
        )
        safety.setWordWrap(True)
        notice_layout.addWidget(safety)
        body.addWidget(notice)
        self.history_label = QLabel("尚无本机诊断历史。")
        self.history_label.setObjectName("subtitle")
        self.history_label.setWordWrap(True)
        body.addWidget(self.history_label)
        body.addWidget(QLabel("问题类型"))
        self.category = QComboBox()
        self.category.addItems(DIAGNOSTIC_CATEGORIES)
        self.category.setMinimumHeight(40)
        body.addWidget(self.category)
        body.addStretch()
        nav = QHBoxLayout()
        back = QPushButton("返回首页")
        back.clicked.connect(self.go_home)
        start = QPushButton("开始只读检查")
        start.setObjectName("primary")
        start.clicked.connect(self._start_scan)
        nav.addWidget(back)
        nav.addStretch()
        nav.addWidget(start)
        body.addLayout(nav)
        return page

    def _scan_page(self) -> QWidget:
        page = QWidget()
        body = QVBoxLayout(page)
        body.addStretch()
        heading = QLabel("正在执行只读检查")
        heading.setObjectName("pageTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(heading)
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 100)
        body.addWidget(self.scan_progress)
        self.scan_status = QLabel("准备开始…")
        self.scan_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_status.setWordWrap(True)
        body.addWidget(self.scan_status)
        detail = QLabel("某些事件日志或设备查询可能需要十几秒。无法获得精确进度时，进度表示已完成的检查项目比例。")
        detail.setObjectName("subtitle")
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        body.addWidget(detail)
        cancel = QPushButton("取消扫描")
        cancel.clicked.connect(self.request_cancel)
        body.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignCenter)
        body.addStretch(2)
        return page

    def _results_page(self) -> QWidget:
        page = QWidget()
        body = QVBoxLayout(page)
        heading = QLabel("查看证据与建议")
        heading.setObjectName("pageTitle")
        body.addWidget(heading)
        self.result_banner = QLabel()
        self.result_banner.setWordWrap(True)
        self.result_banner.setObjectName("statusBox")
        body.addWidget(self.result_banner)
        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderLabels(["检查项目 / 为什么这样判断", "状态", "严重程度", "可信度"])
        self.result_tree.setAlternatingRowColors(True)
        self.result_tree.setMinimumHeight(260)
        body.addWidget(self.result_tree, 2)
        body.addWidget(QLabel("可选的单项修复（没有建议时不会执行任何修改）"))
        self.repair_list = QListWidget()
        self.repair_list.setMaximumHeight(115)
        body.addWidget(self.repair_list)
        repair_row = QHBoxLayout()
        self.repair_button = QPushButton("查看并确认所选修复")
        self.repair_button.clicked.connect(self._confirm_selected_repair)
        self.rollback_button = QPushButton("回滚最近一次修改")
        self.rollback_button.clicked.connect(self._confirm_rollback)
        self.rollback_button.setEnabled(bool(self.rollback_ids))
        repair_row.addWidget(self.repair_button)
        repair_row.addWidget(self.rollback_button)
        repair_row.addStretch()
        body.addLayout(repair_row)
        nav = QHBoxLayout()
        again = QPushButton("重新选择")
        again.clicked.connect(self.show_start)
        package = QPushButton("将诊断结果加入求助包")
        package.setObjectName("primary")
        package.clicked.connect(self._attach_report)
        nav.addWidget(again)
        nav.addStretch()
        nav.addWidget(package)
        body.addLayout(nav)
        return page

    def _start_scan(self) -> None:
        if self.is_running:
            return
        self.pages.setCurrentIndex(1)
        self.phase_changed.emit("本机诊断 · 只读检查")
        self.scan_progress.setValue(0)
        self.scan_status.setText("准备开始…")
        self.thread = QThread(self)
        self.worker = DiagnosticWorker(self.category.currentText())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._scan_progress)
        self.worker.completed.connect(self._scan_completed)
        self.worker.failed.connect(self._scan_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    def _scan_progress(self, percent: int, message: str) -> None:
        self.scan_progress.setValue(percent)
        self.scan_status.setText(message)

    def _scan_completed(self, summary: ScanSummary) -> None:
        self.summary = summary
        try:
            self.history.save(summary)
        except OSError:
            pass
        self._populate_results()
        self.pages.setCurrentIndex(2)
        self.phase_changed.emit("本机诊断 · 查看证据")

    def _scan_failed(self, message: str) -> None:
        QMessageBox.warning(self, "诊断未完成", message)
        self.show_start()

    def _thread_finished(self) -> None:
        self.thread = None
        self.worker = None

    def _populate_results(self) -> None:
        self.result_tree.clear()
        self.repair_list.clear()
        if self.summary is None:
            return
        counts: dict[str, int] = {}
        for item in self.summary.results:
            counts[item.status.value] = counts.get(item.status.value, 0) + 1
            top = QTreeWidgetItem([item.display_name, item.status.value, item.severity.value, item.confidence])
            self.result_tree.addTopLevelItem(top)
            QTreeWidgetItem(top, [f"解释：{item.explanation}", "", "", ""])
            for evidence in item.evidence:
                QTreeWidgetItem(top, [f"证据 · {evidence.label}：{evidence.value}", "", "", ""])
            for recommendation in item.recommendations:
                QTreeWidgetItem(top, [f"建议：{recommendation}", "", "", ""])
            for repair in item.repair_suggestions:
                row = QListWidgetItem(f"[{repair.safety_level.value}] {repair.display_name}")
                row.setData(Qt.ItemDataRole.UserRole, repair)
                self.repair_list.addItem(row)
        state = "扫描已取消，以下结果不完整。" if self.summary.cancelled else "L0 只读扫描完成，没有修改系统。"
        count_text = "，".join(f"{key} {value} 项" for key, value in counts.items()) or "没有结果"
        message = f"{state} {count_text}"
        if self.last_operation_message:
            message = f"{self.last_operation_message}\n复查结果：{message}"
            self.last_operation_message = ""
        self.result_banner.setText(message)
        self.repair_button.setEnabled(self.repair_list.count() > 0)
        self.result_tree.resizeColumnToContents(1)
        self.result_tree.resizeColumnToContents(2)

    def _confirm_selected_repair(self) -> None:
        row = self.repair_list.currentItem()
        if row is None:
            QMessageBox.information(self, "请选择操作", "请先选择一个具体的修复建议。")
            return
        suggestion = row.data(Qt.ItemDataRole.UserRole)
        if not isinstance(suggestion, RepairSuggestion):
            return
        try:
            prepared = self.coordinator.prepare(suggestion)
        except RepairError as exc:
            QMessageBox.warning(self, "无法准备修复", str(exc))
            return
        warning = "此操作可能中断部分应用的联网。" if prepared.safety_level == SafetyLevel.L2 else "此操作仅影响明确列出的当前用户启动项。"
        detail = (
            f"<b>{html.escape(prepared.display_name)}</b><br><br>"
            f"安全等级：{prepared.safety_level.value}<br>"
            f"目标：{html.escape(str(prepared.target))}<br>"
            f"等价操作：{html.escape(prepared.operation_preview)}<br>"
            f"需要管理员权限：{'是' if prepared.requires_admin else '否'}<br>"
            f"可能影响：{html.escape(prepared.impact)}<br>"
            f"回滚方式：{html.escape(prepared.rollback)}<br><br>"
            f"<b>{html.escape(warning)}</b><br><br>是否只执行这一项操作？"
        )
        answer = QMessageBox.warning(
            self,
            "确认单项修复",
            detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.coordinator.execute(prepared, user_confirmed=False)
            return
        try:
            outcome = self.coordinator.execute(prepared, user_confirmed=True)
        except (RepairError, PermissionError, OSError) as exc:
            QMessageBox.warning(self, "修复未执行", f"没有完成修改：{exc}")
            return
        if outcome.backup_id:
            self.rollback_ids.append(outcome.backup_id)
            self.rollback_button.setEnabled(True)
        self.last_operation_message = outcome.message
        QMessageBox.information(self, "操作已执行", outcome.message + "\n现在将自动重新进行只读检查。")
        self._start_scan()

    def _confirm_rollback(self) -> None:
        if not self.rollback_ids:
            return
        backup_id = self.rollback_ids[-1]
        answer = QMessageBox.question(
            self,
            "确认回滚",
            f"将使用备份 {backup_id} 恢复最近一次由 HelpPack 修改的配置。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            outcome = self.coordinator.rollback(backup_id, user_confirmed=True)
        except (RepairError, OSError) as exc:
            QMessageBox.warning(self, "回滚失败", str(exc))
            return
        self.rollback_ids.pop()
        self.rollback_button.setEnabled(bool(self.rollback_ids))
        self.last_operation_message = outcome.message
        QMessageBox.information(self, "回滚完成", outcome.message + "\n现在将自动重新进行只读检查。")
        self._start_scan()

    def _attach_report(self) -> None:
        if self.summary is not None:
            self.add_to_help_pack.emit(generate_diagnostic_markdown(self.summary))
