from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..diagnostics.models import RepairSuggestion, RollbackCapability, SafetyLevel
from ..diagnostics.repair_plan import (
    PlanExecutor,
    PlanItem,
    make_plan,
    new_plan,
    plan_markdown,
)
from ..plan_resources import tr
from ..redaction import redact_text


class PlanReview(QDialog):
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle(tr("title"))
        self.resize(850, 650)
        self.setMinimumSize(500, 420)
        layout = QVBoxLayout(self)
        intro = QLabel(tr("intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.items = QTreeWidget()
        self.items.setHeaderHidden(True)
        for item in plan.items:
            row = QTreeWidgetItem([item.suggestion.display_name + (" · " + tr("extra_badge") if item.extra else "")])
            row.setData(0, Qt.ItemDataRole.UserRole, item)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(0, Qt.CheckState.Unchecked if item.extra else Qt.CheckState.Checked)
            self.items.addTopLevelItem(row)
        layout.addWidget(self.items)
        toggle = QCheckBox(tr("details"))
        layout.addWidget(toggle)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(180)
        self.details.hide()
        toggle.toggled.connect(self.details.setVisible)
        layout.addWidget(self.details)
        self.items.currentItemChanged.connect(self.show_item)
        if plan.items:
            self.items.setCurrentItem(self.items.topLevelItem(0))
        explanation = QLabel((tr("manual") if plan.items else tr("none")) + "\n" + "\n".join(plan.manual_reasons))
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        manual_buttons(layout)
        nav = QHBoxLayout()
        cancel = QPushButton(tr("cancel"))
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        run = QPushButton(tr("execute"))
        run.setEnabled(bool(plan.items))
        run.clicked.connect(self.accept)
        nav.addWidget(cancel)
        nav.addWidget(run)
        layout.addLayout(nav)

    def show_item(self, current, _previous=None):
        if current is None:
            return
        item = current.data(0, Qt.ItemDataRole.UserRole)
        s = item.suggestion
        recovery = "full" if s.rollback_capability == RollbackCapability.FULL else "best" if s.rollback_capability == RollbackCapability.BEST_EFFORT else "never"
        self.details.setPlainText(redact_text(tr("item", s.display_name, s.target, item.evidence, s.impact,
                                               tr("yes") if s.requires_admin else tr("no"), tr("yes") if item.extra else tr("no"), tr(recovery), s.operation_preview)
            + "\n" + tr("metadata", s.estimated_seconds, tr("yes") if s.requires_network else tr("no"), tr("restart_" + s.restart_requirement.name.lower()), s.side_effects or s.impact)))

    def selected(self):
        return {self.items.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole).item_id
                for i in range(self.items.topLevelItemCount()) if self.items.topLevelItem(i).checkState(0) == Qt.CheckState.Checked}


class PlanWorker(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, executor, plan, selected, extra):
        super().__init__()
        self.executor, self.plan, self.selected, self.extra = executor, plan, selected, extra

    @Slot()
    def run(self):
        try:
            self.completed.emit(self.executor.run(self.plan, self.selected, confirmed=True, extra_confirmed=self.extra,
                progress=lambda *args: self.progress.emit(*args)))
        except Exception as exc:  # noqa: BLE001 - GUI worker boundary returns safe failure text
            self.failed.emit(redact_text(f"{type(exc).__name__}: {exc}"))
        finally:
            self.finished.emit()


class RepairPlanPanel(QWidget):
    report_ready = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, page):
        super().__init__(page)
        self.page, self.summary, self.record = page, None, None
        self.thread = self.worker = self.executor = None
        layout = QVBoxLayout(self)
        self.status = QLabel(tr("none"))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.review_button = QPushButton(tr("review"))
        self.review_button.clicked.connect(self.review)
        row.addWidget(self.review_button)
        self.cancel_button = QPushButton(tr("cancel"))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        self.restore_button = QPushButton(tr("restore"))
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self.restore)
        row.addWidget(self.restore_button)
        layout.addLayout(row)
        self.previous_button = QPushButton(tr("previous_restore"))
        self.previous_button.clicked.connect(self.restore_previous)
        layout.addWidget(self.previous_button)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(120)
        self.output.hide()
        layout.addWidget(self.output)

    @property
    def is_running(self):
        return self.thread is not None and self.thread.isRunning()

    def set_summary(self, summary):
        self.summary = summary
        plan = make_plan(summary)
        self.review_button.setEnabled(True)
        self.status.setText(tr("title") + f" · {len(plan.items)}" if plan.items else tr("none"))

    def review(self):
        if self.summary is None or self.is_running or self.page.is_running:
            return
        self.start_review(make_plan(self.summary))

    def start_review(self, plan):
        from ..diagnostics.repair_plan import related_recheck
        category = self.summary.category if self.summary else "综合检查"
        url, scope = self.page.network_target.text(), self.page.network_scope.currentData()
        self.executor = PlanExecutor(coordinator=self.page.coordinator,
            recheck=lambda item: related_recheck(item, category, url, scope))
        try:
            self.executor.authorize(plan)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, tr("title"), redact_text(str(exc)))
            return
        review = PlanReview(plan, self)
        if review.exec() != QDialog.DialogCode.Accepted:
            return
        selected, extra = review.selected(), set()
        for item in plan.items:
            if item.item_id in selected and item.extra:
                answer = QMessageBox.warning(self, tr("title"), tr("extra", item.suggestion.display_name, item.suggestion.impact),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    selected.remove(item.item_id)
                else:
                    extra.add(item.item_id)
        if not selected:
            return
        self.launch(plan, selected, extra)

    def launch(self, plan, selected, extra):
        if self.is_running:
            return
        self.thread = QThread(self)
        self.worker = PlanWorker(self.executor, plan, selected, extra)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(lambda current, total, name: self.status.setText(tr("running", current, total, name)))
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(self.status.setText)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.review_button.setEnabled(False)
        self.restore_button.setEnabled(False)
        self.previous_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.busy_changed.emit(True)
        self.thread.start()

    def cancel(self):
        if self.executor:
            self.executor.cancel.set()
            self.status.setText(tr("cancel") + " · " + tr("intro"))

    def completed(self, record):
        self.record = record
        report = plan_markdown(record)
        self.output.setPlainText(report)
        self.output.show()
        self.page.operation_summaries.append(report)
        try:
            self.page.history.save_record({"kind": "repair_plan", "time": record["time"], "status": "稍后处理", "report": report, "operations": record["results"]})
        except (OSError, ValueError):
            self.status.setText(tr("unavailable"))
        self.restore_button.setEnabled(any(r.get("backup_id") for r in record["results"]))
        self.status.setText(tr("recovery_list", sum(bool(r.get("backup_id")) for r in record["results"])))
        # Never claim resolution; preserve this result before a later full scan.

    def finished(self):
        self.thread = self.worker = None
        self.cancel_button.setEnabled(False)
        self.previous_button.setEnabled(True)
        self.review_button.setEnabled(self.summary is not None)
        self.busy_changed.emit(False)

    def restore(self):
        if self.is_running or self.page.is_running or not self.record:
            return
        if QMessageBox.question(self, tr("restore"), tr("restore_confirm"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        items = []
        for row in reversed(self.record["results"]):
            backup_id = row.get("backup_id")
            if not backup_id:
                continue
            try:
                payload = self.page.coordinator.backups.load(backup_id)
            except (OSError, ValueError):
                continue
            action = payload.get("action_id")
            if action == "reset_dns_to_dhcp":
                restore_id, admin = "restore_dns_settings", True
            elif action == "service_start":
                restore_id, admin = "restore_service_state", True
            elif action in {"reset_user_proxy", "disable_hkcu_startup", "quarantine_allowed_cache"}:
                restore_id, admin = "restore_user_settings", False
            else:
                continue
            suggestion = RepairSuggestion(restore_id, tr("restore") + " · " + row["name"], {"backup_id": backup_id}, SafetyLevel.L2,
                admin, tr("restore_confirm"), tr("restore"), tr("never"), RollbackCapability.NONE)
            items.append(PlanItem(backup_id, suggestion, "recovery", tr("restore_confirm")))
        if items:
            self.start_review(new_plan(items))
        else:
            QMessageBox.information(self, tr("restore"), tr("unsupported"))

    def restore_previous(self):
        if self.is_running or self.page.is_running:
            return
        rows = []
        for backup_id in self.page.coordinator.backups.list_ids():
            try:
                payload = self.page.coordinator.backups.load(backup_id)
            except (OSError, ValueError):
                continue
            if "post_snapshot" in payload and payload.get("action_id") in {
                    "reset_dns_to_dhcp", "reset_user_proxy", "disable_hkcu_startup", "quarantine_allowed_cache", "service_start"}:
                rows.append({"backup_id": backup_id, "name": payload["action_id"]})
        if not rows:
            QMessageBox.information(self, tr("restore"), tr("unsupported"))
            return
        previous = self.record
        self.record = {"results": rows}
        try:
            self.restore()
        finally:
            self.record = previous


def manual_buttons(layout):
    for key, uri in (("network_settings", "ms-settings:network-status"), ("software_help", "ms-settings:appsfeatures"),
                     ("printer_settings", "ms-settings:printers")):
        button = QPushButton(tr(key))
        button.clicked.connect(lambda _checked=False, url=uri: QDesktopServices.openUrl(QUrl(url)))
        layout.addWidget(button)
