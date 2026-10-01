from __future__ import annotations

import html
from dataclasses import asdict

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from helppack.english import text as msg

from ..diagnostics.history import DiagnosticHistoryStore, compare_summaries
from ..diagnostics.models import (
    RepairSuggestion,
    SafetyLevel,
    ScanSummary,
)
from ..diagnostics.repairs import RepairCoordinator, RepairError
from ..diagnostics.reporting import generate_diagnostic_markdown
from ..diagnostics.workers import DiagnosticWorker, RepairWorker
from ..english import label
from .localized_widgets import ChoiceBox
from .repair_review import RepairReview

DIAGNOSTIC_CATEGORIES = [
    "系统卡顿",
    "软件或浏览器异常",
    "网络或Wi-Fi异常",
    "Microsoft Store 问题",
    "驱动安装与更新",
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
        self.repair_thread: QThread | None = None
        self.repair_worker: RepairWorker | None = None
        self.coordinator = RepairCoordinator()
        self.history = DiagnosticHistoryStore()
        self.last_operation_message = ""
        self.rollback_ids: list[str] = []
        for backup_id in reversed(self.coordinator.backups.list_ids()):
            try:
                if self.coordinator.backups.load(backup_id).get("action_id") in {"disable_hkcu_startup", "reset_user_proxy"}:
                    self.rollback_ids.append(backup_id)
            except (OSError, ValueError):
                continue
        self.operation_summaries: list[str] = []

        layout = QVBoxLayout(self)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._selection_page())
        self.pages.addWidget(self._scan_page())
        self.pages.addWidget(self._results_page())
        layout.addWidget(self.pages)

    @property
    def is_running(self) -> bool:
        return (self.thread is not None and self.thread.isRunning()) or (self.repair_thread is not None and self.repair_thread.isRunning())

    def show_start(self) -> None:
        self.pages.setCurrentIndex(0)
        self.phase_changed.emit(msg('本机诊断 · 选择问题'))
        latest = self.history.load_latest()
        if latest:
            self.history_label.setText(
                msg('上次只读扫描：{0} · {1}。历史结果已脱敏保存在本机。', latest.get('finished_at', msg('时间未知')), label(latest.get('category', msg('类型未知'))))
            )
        else:
            self.history_label.setText(msg('尚无本机诊断历史。'))

    def request_cancel(self) -> None:
        if self.repair_thread is not None and self.repair_thread.isRunning():
            self.scan_status.setText(msg('修复正在进行，当前操作不能安全中断；完成后会显示结果。'))
            return
        if self.worker is not None:
            self.worker.cancel_event.set()
            self.scan_status.setText(msg('正在取消；当前检查结束后不会继续后续项目…'))

    def _selection_page(self) -> QWidget:
        page = QWidget()
        body = QVBoxLayout(page)
        heading = QLabel(msg('本机诊断'))
        heading.setObjectName("pageTitle")
        body.addWidget(heading)
        description = QLabel(msg('选择最接近的问题。默认扫描只运行 L0 只读检查，不会修改系统设置、结束进程或清理文件。'))
        description.setObjectName("subtitle")
        description.setWordWrap(True)
        body.addWidget(description)
        notice = QFrame()
        notice.setObjectName("notice")
        notice_layout = QVBoxLayout(notice)
        notice_layout.addWidget(QLabel(msg('安全边界')))
        safety = QLabel(
            msg('检查结论会展示证据和可信度。修复必须逐项确认；高风险操作需要第二次确认。管理员操作只在该动作执行期间请求 UAC，应用永不自动重启电脑。')
        )
        safety.setWordWrap(True)
        notice_layout.addWidget(safety)
        validation = QLabel(msg('开发预览：新增系统修复尚待隔离 Windows 环境验收。驱动更新检查会联系 Windows Update。'))
        validation.setWordWrap(True)
        notice_layout.addWidget(validation)
        body.addWidget(notice)
        self.history_label = QLabel(msg('尚无本机诊断历史。'))
        self.history_label.setObjectName("subtitle")
        self.history_label.setWordWrap(True)
        body.addWidget(self.history_label)
        body.addWidget(QLabel(msg('问题类型')))
        self.category = ChoiceBox()
        self.category.addItems(DIAGNOSTIC_CATEGORIES)
        self.category.setMinimumHeight(40)
        body.addWidget(self.category)
        body.addStretch()
        nav = QHBoxLayout()
        back = QPushButton(msg('返回首页'))
        back.clicked.connect(self.go_home)
        start = QPushButton(msg('开始只读检查'))
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
        heading = QLabel(msg('正在执行只读检查'))
        self.scan_heading = heading
        heading.setObjectName("pageTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(heading)
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 100)
        body.addWidget(self.scan_progress)
        self.scan_status = QLabel(msg('准备开始…'))
        self.scan_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_status.setWordWrap(True)
        body.addWidget(self.scan_status)
        detail = QLabel(msg('某些事件日志或设备查询可能需要十几秒。无法获得精确进度时，进度表示已完成的检查项目比例。'))
        detail.setObjectName("subtitle")
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        body.addWidget(detail)
        cancel = QPushButton(msg('取消扫描'))
        cancel.clicked.connect(self.request_cancel)
        body.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignCenter)
        body.addStretch(2)
        return page

    def _results_page(self) -> QWidget:
        page = QWidget()
        body = QVBoxLayout(page)
        heading = QLabel(msg('查看证据与建议'))
        heading.setObjectName("pageTitle")
        body.addWidget(heading)
        self.result_banner = QLabel()
        self.result_banner.setWordWrap(True)
        self.result_banner.setObjectName("statusBox")
        body.addWidget(self.result_banner)
        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderLabels([msg('检查项目 / 为什么这样判断'), msg('状态'), msg('严重程度'), msg('可信度')])
        self.result_tree.setAlternatingRowColors(True)
        self.result_tree.setWordWrap(True)
        self.result_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            self.result_tree.header().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.result_tree.currentItemChanged.connect(self._show_result_detail)
        self.result_tree.setMinimumHeight(190)
        body.addWidget(self.result_tree, 2)
        detail_heading = QLabel(msg('所选项目完整内容（可滚动、选择和复制）'))
        body.addWidget(detail_heading)
        self.result_detail = QPlainTextEdit()
        self.result_detail.setReadOnly(True)
        self.result_detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.result_detail.setMinimumHeight(110)
        self.result_detail.setPlaceholderText(msg('选择上方检查项目或证据后，在这里查看完整文字。'))
        body.addWidget(self.result_detail, 1)
        body.addWidget(QLabel(msg('可选的单项修复（没有建议时不会执行任何修改）')))
        self.repair_list = QListWidget()
        self.repair_list.setMaximumHeight(90)
        body.addWidget(self.repair_list)
        repair_row = QHBoxLayout()
        self.repair_button = QPushButton(msg('查看并确认所选修复'))
        self.repair_button.clicked.connect(self._confirm_selected_repair)
        self.rollback_button = QPushButton(msg('回滚最近一次修改'))
        self.rollback_button.clicked.connect(self._confirm_rollback)
        self.rollback_button.setEnabled(bool(self.rollback_ids))
        repair_row.addWidget(self.repair_button)
        repair_row.addWidget(self.rollback_button)
        repair_row.addStretch()
        body.addLayout(repair_row)
        nav = QHBoxLayout()
        again = QPushButton(msg('重新选择'))
        again.clicked.connect(self.show_start)
        package = QPushButton(msg('将诊断结果加入求助包'))
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
        self.scan_heading.setText(msg('正在执行只读检查'))
        self.phase_changed.emit(msg('本机诊断 · 只读检查'))
        self.scan_progress.setValue(0)
        self.scan_status.setText(msg('准备开始…'))
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
        if getattr(self, "repair_before", None):
            changes = compare_summaries(self.repair_before, asdict(summary))
            self.operation_summaries.append(msg('修复前后变化（变化不证明因果）：\n') + "\n".join(changes))
            self.last_operation_message += "\n" + "\n".join(changes)
            try:
                if self.repair_history_id:
                    self.history.add_operation(self.repair_history_id, {"action": "修复后复检", "changes": changes, "finished_at": summary.finished_at})
            except (OSError, ValueError, TypeError):
                self.last_operation_message += msg('\n前后对比保存失败。')
            self.repair_before = None
        try:
            self.history.save(summary)
        except OSError:
            pass
        self._populate_results()
        self.pages.setCurrentIndex(2)
        self.phase_changed.emit(msg('本机诊断 · 查看证据'))

    def _scan_failed(self, message: str) -> None:
        QMessageBox.warning(self, msg('诊断未完成'), message)
        self.show_start()

    def _thread_finished(self) -> None:
        self.thread = None
        self.worker = None

    def _populate_results(self) -> None:
        self.result_tree.clear()
        self.result_detail.clear()
        self.repair_list.clear()
        if self.summary is None:
            return
        counts: dict[str, int] = {}
        for item in self.summary.results:
            counts[item.status.value] = counts.get(item.status.value, 0) + 1
            top = QTreeWidgetItem([item.display_name, label(item.status.value), label(item.severity.value), label(item.confidence)])
            self.result_tree.addTopLevelItem(top)
            detail_lines = [
                item.display_name,
                msg('状态：{0}', label(item.status.value)),
                msg('严重程度：{0}', label(item.severity.value)),
                msg('可信度：{0}', label(item.confidence)),
                "",
                msg('解释：{0}', item.explanation),
                "",
                msg('检测证据：'),
            ]
            explanation = msg('解释：{0}', item.explanation)
            self._add_detail_child(top, explanation)
            for evidence in item.evidence:
                evidence_text = msg('证据 · {0}：{1}', evidence.label, evidence.value)
                detail_lines.append(f"- {evidence.label}：{evidence.value}")
                self._add_detail_child(top, evidence_text)
            detail_lines.extend(["", msg('建议操作：')])
            for recommendation in item.recommendations:
                recommendation_text = msg('建议：{0}', recommendation)
                detail_lines.append(f"- {recommendation}")
                self._add_detail_child(top, recommendation_text)
            full_detail = "\n".join(detail_lines)
            top.setData(0, Qt.ItemDataRole.UserRole, full_detail)
            top.setToolTip(0, full_detail)
            for repair in item.repair_suggestions:
                if repair.safety_level == SafetyLevel.L1 and not repair.requires_admin:
                    group = msg('可安全修复')
                elif repair.safety_level == SafetyLevel.L3:
                    group = msg('高风险/需二次确认')
                else:
                    group = msg('需要确认') + (msg('与管理员权限') if repair.requires_admin else "")
                row = QListWidgetItem(f"{group} · [{repair.safety_level.value}] {repair.display_name}")
                row.setData(Qt.ItemDataRole.UserRole, repair)
                self.repair_list.addItem(row)
        state = msg('扫描已取消，以下结果不完整。') if self.summary.cancelled else msg('L0 只读扫描完成，没有修改系统。')
        count_text = ", ".join(msg('{0} {1} 项', label(key), value) for key, value in counts.items()) or msg('没有结果')
        message = f"{state} {count_text}"
        if self.last_operation_message:
            message = msg('{0}\n复查结果：{1}', self.last_operation_message, message)
            self.last_operation_message = ""
        self.result_banner.setText(message)
        self.repair_button.setEnabled(self.repair_list.count() > 0)
        if self.result_tree.topLevelItemCount():
            self.result_tree.setCurrentItem(self.result_tree.topLevelItem(0))

    def _add_detail_child(self, parent: QTreeWidgetItem, full_text: str) -> None:
        preview = " ".join(full_text.splitlines())
        if len(preview) > 180:
            preview = preview[:177] + "…"
        child = QTreeWidgetItem(parent, [preview, "", "", ""])
        child.setData(0, Qt.ItemDataRole.UserRole, full_text)
        child.setToolTip(0, full_text)

    def _show_result_detail(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        if current is None:
            self.result_detail.clear()
            return
        full_text = current.data(0, Qt.ItemDataRole.UserRole) or current.text(0)
        self.result_detail.setPlainText(str(full_text))

    def _confirm_selected_repair(self) -> None:
        row = self.repair_list.currentItem()
        if row is None:
            QMessageBox.information(self, msg('请选择操作'), msg('请先选择一个具体的修复建议。'))
            return
        suggestion = row.data(Qt.ItemDataRole.UserRole)
        if not isinstance(suggestion, RepairSuggestion):
            return
        try:
            prepared = self.coordinator.prepare(suggestion)
        except RepairError as exc:
            QMessageBox.warning(self, msg('无法准备修复'), str(exc))
            return
        side_effects = "；".join(prepared.side_effects or []) or msg('未列出额外副作用')
        warning = msg('高风险操作必须再次确认，且可能无法自动恢复。') if prepared.safety_level == SafetyLevel.L3 else msg('应用只会执行这里列出的这一项操作。')
        detail = (
            msg('<b>{0}</b><br><br>安全等级：{1}<br>目标：{2}<br>等价操作：{3}<br>需要管理员权限：{4}<br>需要联网：{5}<br>重启要求：{6}<br>预计耗时：约 {7} 秒<br>可能影响：{8}<br>副作用：{9}<br>回滚能力：{10}<br>回滚方式：{11}<br><br><b>{12}</b><br><br>是否只执行这一项操作？', html.escape(prepared.display_name), prepared.safety_level.value, html.escape(str(prepared.target)), html.escape(prepared.operation_preview), msg('是') if prepared.requires_admin else msg('否'), msg('是') if prepared.requires_network else msg('否'), label(prepared.restart_requirement.value), prepared.estimated_seconds, html.escape(prepared.impact), html.escape(side_effects), label(prepared.rollback_capability.value), html.escape(prepared.rollback), html.escape(warning))
        )
        review = RepairReview(detail, self)
        if review.exec() != review.DialogCode.Accepted:
            self.coordinator.execute(prepared, user_confirmed=False)
            return
        second_confirmation: str | bool = False
        if prepared.requires_second_confirmation:
            if prepared.confirmation_phrase:
                value, ok = QInputDialog.getText(self, msg('第二次确认'), msg('此操作不可可靠回滚。请输入“{0}”继续：', label(prepared.confirmation_phrase)))
                if not ok or value != label(prepared.confirmation_phrase):
                    self.coordinator.execute(prepared, user_confirmed=False)
                    return
                second_confirmation = prepared.confirmation_phrase
            else:
                second = QMessageBox.warning(
                    self, msg('第二次确认'),
                    msg('此操作可能改变网络、驱动或系统组件，并且无法保证自动恢复。HelpPack 不会自动重启电脑。确定继续吗？'),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if second != QMessageBox.StandardButton.Yes:
                    self.coordinator.execute(prepared, user_confirmed=False)
                    return
                second_confirmation = True
        # Consume the local preview confirmation. The worker creates a fresh, short-lived confirmation.
        self.coordinator.execute(prepared, user_confirmed=False)
        self._start_repair_worker(suggestion, second_confirmation)

    def _start_repair_worker(self, suggestion: RepairSuggestion, second_confirmation: str | bool) -> None:
        if self.repair_thread is not None and self.repair_thread.isRunning():
            return
        self.repair_before = asdict(self.summary) if self.summary else None
        self.repair_history_id = self.history.last_id
        self.repair_action_id = suggestion.action_id
        self.pages.setCurrentIndex(1)
        self.scan_heading.setText(msg('正在执行单项修复'))
        self.phase_changed.emit(msg('本机诊断 · 执行单项修复'))
        self.scan_progress.setRange(0, 0)
        self.scan_status.setText(msg('正在准备修复…'))
        self.repair_thread = QThread(self)
        self.repair_worker = RepairWorker(suggestion, second_confirmation)
        self.repair_worker.moveToThread(self.repair_thread)
        self.repair_thread.started.connect(self.repair_worker.run)
        self.repair_worker.progress.connect(self.scan_status.setText)
        self.repair_worker.completed.connect(self._repair_completed)
        self.repair_worker.failed.connect(self._repair_failed)
        self.repair_worker.finished.connect(self.repair_thread.quit)
        self.repair_worker.finished.connect(self.repair_worker.deleteLater)
        self.repair_thread.finished.connect(self.repair_thread.deleteLater)
        self.repair_thread.finished.connect(self._repair_thread_finished)
        self.repair_thread.start()

    def _repair_completed(self, outcome) -> None:
        if outcome.backup_id and outcome.action_id in {"disable_hkcu_startup", "reset_user_proxy"}:
            self.rollback_ids.append(outcome.backup_id)
            self.rollback_button.setEnabled(True)
        restart = msg('\n此操作需要你稍后自行重启电脑；HelpPack 不会自动重启。') if outcome.restart_required else ""
        self.last_operation_message = outcome.message + "\n" + outcome.recheck_summary + restart
        from ..redaction import redact_text
        self.operation_summaries.append(redact_text(f"{outcome.action_id}：{self.last_operation_message}"))
        if self.repair_history_id:
            try:
                self.history.add_operation(self.repair_history_id, {"action": outcome.action_id, "executed": outcome.executed, "verified": outcome.verified, "result": self.last_operation_message})
            except (OSError, ValueError, TypeError):
                self.last_operation_message += msg('\n操作记录保存失败，请手动保留结果。')
        QMessageBox.information(self, msg('操作已完成'), self.last_operation_message + msg('\n现在将重新进行只读检查。'))
        self.scan_progress.setRange(0, 100)
        self._recheck_after_repair = True

    def _repair_failed(self, message: str) -> None:
        self.repair_before = None
        if getattr(self, "repair_history_id", None):
            try:
                self.history.add_operation(self.repair_history_id, {"action": self.repair_action_id, "confirmed": True, "verified": False, "result": message})
            except (OSError, ValueError, TypeError):
                message += msg('\n失败记录未能保存。')
        self.scan_progress.setRange(0, 100)
        QMessageBox.warning(self, msg('修复未完成'), msg('没有确认修复成功：{0}', message))
        self.pages.setCurrentIndex(2)
        self.phase_changed.emit(msg('本机诊断 · 查看证据'))

    def _repair_thread_finished(self) -> None:
        self.repair_thread = None
        self.repair_worker = None
        if getattr(self, "_recheck_after_repair", False):
            self._recheck_after_repair = False
            self._start_scan()

    def _confirm_rollback(self) -> None:
        if not self.rollback_ids:
            return
        backup_id = self.rollback_ids[-1]
        answer = QMessageBox.question(
            self,
            msg('确认回滚'),
            msg('将使用备份 {0} 恢复最近一次由 HelpPack 修改的配置。是否继续？', backup_id),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            outcome = self.coordinator.rollback(backup_id, user_confirmed=True)
        except (RepairError, OSError) as exc:
            QMessageBox.warning(self, msg('回滚失败'), str(exc))
            return
        self.rollback_ids.pop()
        self.rollback_button.setEnabled(bool(self.rollback_ids))
        self.last_operation_message = outcome.message
        QMessageBox.information(self, msg('回滚完成'), outcome.message + msg('\n现在将自动重新进行只读检查。'))
        self._start_scan()

    def _attach_report(self) -> None:
        if self.summary is not None:
            report = generate_diagnostic_markdown(self.summary)
            if self.operation_summaries:
                report += msg('\n\n## 本次修复记录（已脱敏）\n\n') + "\n\n".join(self.operation_summaries)
            self.add_to_help_pack.emit(report)
