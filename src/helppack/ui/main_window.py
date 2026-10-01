from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from helppack.english import text as msg

from ..attachments import AttachmentError, add_attachments
from ..exporter import export_markdown, export_zip, safe_timestamp
from ..models import Attachment, ProblemDetails, ReportBundle, SystemSnapshot
from ..report import DEFAULT_INCLUDED_FIELDS, SYSTEM_LABELS, generate_markdown
from ..workers import CollectionWorker
from .diagnostic_page import DiagnosticPage
from .investigation_page import InvestigationPage
from .localized_widgets import ChoiceBox
from .screenshot_editor import ScreenshotEditor

CATEGORIES = [
    "软件无法启动或崩溃",
    "游戏问题",
    "网络问题",
    "电脑卡顿",
    "蓝屏或异常重启",
    "其他问题",
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(msg('求助包 HelpPack'))
        self.resize(980, 720)
        self.setMinimumSize(760, 560)
        self.attachments: list[Attachment] = []
        self.snapshot = SystemSnapshot()
        self.bundle: ReportBundle | None = None
        self.diagnostics_markdown = ""
        self.collection_thread: QThread | None = None
        self.collection_worker: CollectionWorker | None = None
        self.screenshot_copies = tempfile.TemporaryDirectory(prefix="helppack_edited_")

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(self._build_header())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._home_page())
        self.stack.addWidget(self._problem_page())
        self.stack.addWidget(self._collection_page())
        self.stack.addWidget(self._privacy_page())
        self.stack.addWidget(self._preview_page())
        self.stack.addWidget(self._export_page())
        self.diagnostic_page = DiagnosticPage(self)
        self.diagnostic_page.go_home.connect(self._back_home)
        self.diagnostic_page.add_to_help_pack.connect(self._attach_diagnostics)
        self.diagnostic_page.phase_changed.connect(self.step_label.setText)
        self.stack.addWidget(self.diagnostic_page)
        self.investigation_page = InvestigationPage(self)
        self.investigation_page.go_home.connect(self._back_home)
        self.investigation_page.add_to_help_pack.connect(self._attach_diagnostics)
        self.stack.addWidget(self.investigation_page)
        for caption in self.findChildren(QLabel):
            caption.setWordWrap(True)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self._apply_style()

    def _build_header(self) -> QWidget:
        frame = QFrame()
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        brand = QLabel(msg('求助包  HelpPack'))
        brand.setObjectName("brand")
        row.addWidget(brand)
        row.addStretch()
        self.step_label = QLabel(msg('开始'))
        self.step_label.setObjectName("step")
        row.addWidget(self.step_label)
        return frame

    def _home_page(self) -> QWidget:
        page, body = self._scroll_page()
        body.addStretch()
        title = QLabel(msg('把电脑故障整理成一份清楚的求助报告'))
        title.setObjectName("hero")
        title.setWordWrap(True)
        body.addWidget(title)
        subtitle = QLabel(msg('回答几个简单问题，HelpPack 会在本机收集必要信息，并生成可检查、可编辑的诊断报告。'))
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        body.addWidget(subtitle)
        privacy = self._notice(msg('隐私优先'), msg('系统信息仅在本机处理。生成报告前，你可以检查并删除任何内容。'))
        body.addWidget(privacy)
        start = QPushButton(msg('创建求助包'))
        start.setObjectName("primary")
        start.setMinimumHeight(48)
        start.clicked.connect(lambda: self._go(1, msg('1 / 5  描述问题')))
        body.addWidget(start, alignment=Qt.AlignmentFlag.AlignLeft)
        diagnose = QPushButton(msg('本机诊断'))
        diagnose.setMinimumHeight(44)
        diagnose.clicked.connect(self._open_diagnostics)
        body.addWidget(diagnose, alignment=Qt.AlignmentFlag.AlignLeft)
        toolbox = QPushButton(msg('症状向导与专项排查'))
        toolbox.clicked.connect(lambda: self._go(7, msg('专项排查 · 症状与证据')))
        body.addWidget(toolbox, alignment=Qt.AlignmentFlag.AlignLeft)
        body.addStretch(2)
        return page

    def _problem_page(self) -> QWidget:
        page, body = self._scroll_page()
        body.addWidget(self._page_title(msg('描述问题'), msg('不必使用专业术语，按你看到的情况填写即可。')))
        form = QFormLayout()
        form.setSpacing(12)
        self.category = ChoiceBox()
        self.category.addItems(CATEGORIES)
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText(msg('例如：双击游戏后没有反应'))
        self.description_input = QPlainTextEdit()
        self.description_input.setPlaceholderText(msg('发生了什么？是否有报错？能否重复出现？'))
        self.description_input.setMinimumHeight(100)
        self.preceding_input = QPlainTextEdit()
        self.preceding_input.setPlaceholderText(msg('例如：更新了显卡驱动、安装了新软件'))
        self.preceding_input.setMinimumHeight(78)
        self.attempted_input = QPlainTextEdit()
        self.attempted_input.setPlaceholderText(msg('例如：重启电脑、重新安装软件'))
        self.attempted_input.setMinimumHeight(78)
        self.remaining_input = QPlainTextEdit()
        self.remaining_input.setPlaceholderText(msg('现在还有什么没有解决？可留空，但不会自动认定已解决。'))
        self.remaining_input.setMinimumHeight(65)
        self.resolution = ChoiceBox()
        self.resolution.addItems(["稍后处理", "未解决", "已解决"])
        form.addRow(msg('问题类型'), self.category)
        form.addRow(msg('问题标题 *'), self.title_input)
        form.addRow(msg('发生了什么 *'), self.description_input)
        form.addRow(msg('问题前做过什么'), self.preceding_input)
        form.addRow(msg('已经尝试过什么'), self.attempted_input)
        form.addRow(msg('仍未解决的问题'), self.remaining_input)
        form.addRow(msg('处理状态（自己标记）'), self.resolution)
        body.addLayout(form)

        attachment_header = QHBoxLayout()
        attachment_header.addWidget(QLabel(msg('截图（最多 5 张）')))
        attachment_header.addStretch()
        add_button = QPushButton(msg('添加截图'))
        add_button.clicked.connect(self._add_screenshots)
        remove_button = QPushButton(msg('移除选中'))
        remove_button.clicked.connect(self._remove_screenshot)
        edit_button = QPushButton(msg('裁剪 / 遮挡选中截图'))
        edit_button.clicked.connect(self._edit_screenshot)
        attachment_header.addWidget(add_button)
        attachment_header.addWidget(remove_button)
        attachment_header.addWidget(edit_button)
        body.addLayout(attachment_header)
        self.attachment_list = QListWidget()
        self.attachment_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.attachment_list.setMinimumHeight(90)
        body.addWidget(self.attachment_list)
        reminder = QLabel(msg('提醒：截图内容不会自动识别或脱敏，请在导出前自行检查。'))
        reminder.setObjectName("warningText")
        reminder.setWordWrap(True)
        body.addWidget(reminder)
        body.addLayout(self._nav(self._back_home, self._start_collection, msg('开始收集')))
        return page

    def _collection_page(self) -> QWidget:
        page = QWidget()
        body = QVBoxLayout(page)
        body.addStretch()
        body.addWidget(self._page_title(msg('正在收集必要信息'), msg('只读取与排查有关的系统状态，不会读取文档、密码、浏览历史或剪贴板。')))
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setMinimumHeight(22)
        body.addWidget(self.progress)
        self.progress_status = QLabel(msg('准备开始…'))
        self.progress_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(self.progress_status)
        body.addStretch(2)
        return page

    def _privacy_page(self) -> QWidget:
        page, body = self._scroll_page()
        body.addWidget(self._page_title(msg('检查隐私'), msg('HelpPack 已自动脱敏，但自动处理不能代替你的最终检查。')))
        body.addWidget(self._notice(msg('将自动隐藏'), msg('Windows 用户名、用户目录路径、IP 地址、MAC 地址、邮箱，以及常见 API Key、Token 和密码字段。')))
        body.addWidget(self._notice(msg('截图需要你检查'), msg('截图不会进行 OCR 脱敏。请确认截图中没有账号、聊天、订单、二维码或其他私人内容。'), warning=True))
        self.privacy_attachment_list = QListWidget()
        self.privacy_attachment_list.setMinimumHeight(130)
        body.addWidget(QLabel(msg('选择要保留的截图：')))
        body.addWidget(self.privacy_attachment_list)
        body.addWidget(QLabel(msg('取消勾选后，该截图不会进入 ZIP，也不会出现在报告附件列表中。')))
        body.addStretch()
        body.addLayout(self._nav(lambda: self._go(1, msg('1 / 5  描述问题')), self._prepare_preview, msg('生成预览')))
        return page

    def _preview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self._page_title(msg('预览并编辑'), msg('取消勾选不希望导出的系统信息；正文也可以直接修改。')))
        content = QHBoxLayout()
        field_panel = QFrame()
        field_panel.setObjectName("panel")
        fields_layout = QVBoxLayout(field_panel)
        fields_layout.addWidget(QLabel(msg('包含的系统信息')))
        field_scroll = QScrollArea()
        field_scroll.setWidgetResizable(True)
        field_options = QWidget()
        options_layout = QVBoxLayout(field_options)
        self.field_checks: dict[str, QCheckBox] = {}
        for key, label in SYSTEM_LABELS.items():
            check = QCheckBox(label)
            check.setChecked(key in DEFAULT_INCLUDED_FIELDS)
            self.field_checks[key] = check
            options_layout.addWidget(check)
        options_layout.addStretch()
        field_scroll.setWidget(field_options)
        fields_layout.addWidget(field_scroll, 1)
        field_panel.setMinimumWidth(260)
        field_panel.setMaximumWidth(300)
        refresh = QPushButton(msg('按选择更新预览'))
        refresh.setMinimumHeight(40)
        refresh.clicked.connect(self._refresh_preview)
        fields_layout.addWidget(refresh)
        content.addWidget(field_panel, 0)
        self.preview_edit = QPlainTextEdit()
        self.preview_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        content.addWidget(self.preview_edit, 1)
        layout.addLayout(content, 1)
        copy = QPushButton(msg('复制当前预览的简洁问题摘要'))
        copy.clicked.connect(self._copy_report_summary)
        layout.addWidget(copy)
        layout.addLayout(self._nav(lambda: self._go(3, msg('3 / 5  检查隐私')), self._show_export, msg('确认并导出')))
        return page

    def _export_page(self) -> QWidget:
        page, body = self._scroll_page()
        body.addWidget(self._page_title(msg('导出求助包'), msg('建议优先导出 ZIP：它包含报告、已确认的截图和校验清单。')))
        zip_button = QPushButton(msg('导出 ZIP 求助包'))
        zip_button.setObjectName("primary")
        zip_button.setMinimumHeight(48)
        zip_button.clicked.connect(self._export_zip)
        md_button = QPushButton(msg('仅导出 Markdown 报告'))
        md_button.setMinimumHeight(44)
        md_button.clicked.connect(self._export_markdown)
        body.addWidget(zip_button)
        body.addWidget(md_button)
        self.export_status = QLabel(msg('尚未导出'))
        self.export_status.setObjectName("statusBox")
        self.export_status.setWordWrap(True)
        body.addWidget(self.export_status)
        body.addStretch()
        restart = QPushButton(msg('创建另一份求助包'))
        restart.clicked.connect(self._reset)
        body.addWidget(restart, alignment=Qt.AlignmentFlag.AlignLeft)
        return page

    def _scroll_page(self) -> tuple[QScrollArea, QVBoxLayout]:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(14)
        area.setWidget(content)
        return area, layout

    def _page_title(self, title: str, subtitle: str) -> QWidget:
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 8)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        detail = QLabel(subtitle)
        detail.setObjectName("subtitle")
        detail.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(detail)
        return block

    def _notice(self, title: str, text: str, warning: bool = False) -> QFrame:
        frame = QFrame()
        frame.setObjectName("warning" if warning else "notice")
        layout = QVBoxLayout(frame)
        heading = QLabel(title)
        heading.setObjectName("noticeTitle")
        detail = QLabel(text)
        detail.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(detail)
        return frame

    def _nav(self, back_action, next_action, next_text: str) -> QHBoxLayout:
        row = QHBoxLayout()
        back = QPushButton(msg('返回'))
        back.clicked.connect(back_action)
        forward = QPushButton(next_text)
        forward.setObjectName("primary")
        forward.clicked.connect(next_action)
        row.addWidget(back)
        row.addStretch()
        row.addWidget(forward)
        return row

    def _go(self, index: int, label: str) -> None:
        self.stack.setCurrentIndex(index)
        self.step_label.setText(label)

    def _back_home(self) -> None:
        self._go(0, msg('开始'))

    def _open_diagnostics(self) -> None:
        self.diagnostic_page.show_start()
        self._go(6, msg('本机诊断 · 选择问题'))

    def _attach_diagnostics(self, markdown: str) -> None:
        self.diagnostics_markdown = "\n\n".join(filter(None, [self.diagnostics_markdown, markdown]))
        QMessageBox.information(self, msg('诊断结果已保留'), msg('只读诊断结果会加入接下来生成的求助包。请继续填写问题描述。'))
        self._go(1, msg('1 / 5  描述问题'))

    def _add_screenshots(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, msg('选择截图'), "", msg('图片 (*.png *.jpg *.jpeg)'))
        if not paths:
            return
        try:
            self.attachments = add_attachments(self.attachments, paths)
        except AttachmentError as exc:
            QMessageBox.warning(self, msg('无法添加截图'), str(exc))
            return
        self._sync_attachment_list()

    def _remove_screenshot(self) -> None:
        rows = sorted({index.row() for index in self.attachment_list.selectedIndexes()}, reverse=True)
        for row in rows:
            self.attachments.pop(row)
        self._sync_attachment_list()

    def _edit_screenshot(self) -> None:
        index = self.attachment_list.currentRow()
        if index < 0:
            QMessageBox.information(self, msg('选择截图'), msg('请先选择一张截图。'))
            return
        attachment = self.attachments[index]
        try:
            dialog = ScreenshotEditor(attachment.export_source, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            copy = Path(self.screenshot_copies.name) / f"screenshot_{uuid.uuid4().hex}.png"
            if not dialog.canvas.image.save(str(copy), "PNG"):
                raise ValueError(msg('无法保存处理后的副本'))
            attachment.processed_path = copy
            attachment.export_name = f"screenshot_processed_{index + 1}_{uuid.uuid4().hex[:8]}.png"
            self._sync_attachment_list()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, msg('截图编辑未完成'), str(exc))

    def _sync_attachment_list(self) -> None:
        self.attachment_list.clear()
        self.attachment_list.addItems([item.export_name for item in self.attachments])

    def _start_collection(self) -> None:
        title = self.title_input.text().strip()
        description = self.description_input.toPlainText().strip()
        if not title or not description:
            QMessageBox.information(self, msg('还需要一点信息'), msg('请填写问题标题和“发生了什么”。'))
            return
        self.problem = ProblemDetails(
            category=self.category.currentText(),
            title=title,
            description=description,
            preceding_actions=self.preceding_input.toPlainText().strip(),
            attempted_solutions=self.attempted_input.toPlainText().strip(),
            unresolved_issues=self.remaining_input.toPlainText().strip(),
            resolution_status=self.resolution.currentText(),
        )
        self._go(2, msg('2 / 5  收集信息'))
        self.progress.setValue(0)
        self.progress_status.setText(msg('准备开始…'))
        self.collection_thread = QThread(self)
        self.collection_worker = CollectionWorker()
        self.collection_worker.moveToThread(self.collection_thread)
        self.collection_thread.started.connect(self.collection_worker.run)
        self.collection_worker.progress.connect(self._collection_progress)
        self.collection_worker.completed.connect(self._collection_done)
        self.collection_worker.failed.connect(self._collection_failed)
        self.collection_worker.finished.connect(self.collection_thread.quit)
        self.collection_worker.finished.connect(self.collection_worker.deleteLater)
        self.collection_thread.finished.connect(self.collection_thread.deleteLater)
        self.collection_thread.finished.connect(self._collection_thread_finished)
        self.collection_thread.start()

    def _copy_report_summary(self):
        from ..redaction import redact_text
        from ..report import concise_summary
        text = redact_text(self.preview_edit.toPlainText(), extra_paths=[str(p) for a in self.attachments for p in (a.path, a.export_source)])
        QApplication.clipboard().setText(concise_summary(text))

    def _collection_thread_finished(self) -> None:
        self.collection_thread = None
        self.collection_worker = None

    def _collection_progress(self, percent: int, message: str) -> None:
        self.progress.setValue(percent)
        self.progress_status.setText(message)

    def _collection_done(self, snapshot: SystemSnapshot) -> None:
        self.snapshot = snapshot
        self.progress.setValue(100)
        self._populate_privacy_attachments()
        self._go(3, msg('3 / 5  检查隐私'))

    def _collection_failed(self, message: str) -> None:
        QMessageBox.warning(self, msg('收集未完成'), message)
        self._go(1, msg('1 / 5  描述问题'))

    def _populate_privacy_attachments(self) -> None:
        self.privacy_attachment_list.clear()
        for attachment in self.attachments:
            from PySide6.QtWidgets import QListWidgetItem

            item = QListWidgetItem(attachment.export_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if attachment.included else Qt.CheckState.Unchecked)
            self.privacy_attachment_list.addItem(item)

    def _prepare_preview(self) -> None:
        for index, attachment in enumerate(self.attachments):
            attachment.included = self.privacy_attachment_list.item(index).checkState() == Qt.CheckState.Checked
        self.bundle = ReportBundle(
            self.problem,
            self.snapshot,
            self.attachments,
            diagnostics_markdown=self.diagnostics_markdown,
        )
        self._refresh_preview()
        self._go(4, msg('4 / 5  预览'))

    def _refresh_preview(self) -> None:
        if self.bundle is None:
            return
        included = [key for key, check in self.field_checks.items() if check.isChecked()]
        self.preview_edit.setPlainText(generate_markdown(self.bundle, included))

    def _show_export(self) -> None:
        if not self.preview_edit.toPlainText().strip():
            QMessageBox.information(self, msg('报告为空'), msg('请保留或填写报告正文后再导出。'))
            return
        self._go(5, msg('5 / 5  导出'))

    def _export_markdown(self) -> None:
        default = f"HelpPack_{safe_timestamp()}.md"
        path, _ = QFileDialog.getSaveFileName(self, msg('导出 Markdown 报告'), default, "Markdown (*.md)")
        if not path:
            return
        try:
            from ..redaction import redact_text
            output = export_markdown(redact_text(self.preview_edit.toPlainText(), extra_paths=self.bundle.source_paths() if self.bundle else []), path)
        except OSError:
            QMessageBox.warning(self, msg('导出失败'), msg('无法写入所选位置，请选择其他文件夹后重试。'))
            return
        self.export_status.setText(msg('Markdown 报告已导出：\n{0}', output))

    def _export_zip(self) -> None:
        if self.bundle is None:
            return
        default = f"HelpPack_{safe_timestamp()}.zip"
        path, _ = QFileDialog.getSaveFileName(self, msg('导出 ZIP 求助包'), default, msg('ZIP 文件 (*.zip)'))
        if not path:
            return
        try:
            from ..redaction import redact_text
            output = export_zip(redact_text(self.preview_edit.toPlainText(), extra_paths=self.bundle.source_paths()), self.bundle, path)
        except (OSError, ValueError):
            QMessageBox.warning(self, msg('导出失败'), msg('无法创建求助包，请确认截图仍然存在并选择其他文件夹重试。'))
            return
        self.export_status.setText(msg('ZIP 求助包已导出：\n{0}\n\n发送前建议再检查一次报告和截图。', output))

    def _reset(self) -> None:
        self.attachments.clear()
        self.diagnostics_markdown = ""
        self._sync_attachment_list()
        for widget in (self.title_input,):
            widget.clear()
        for widget in (self.description_input, self.preceding_input, self.attempted_input, self.remaining_input, self.preview_edit):
            widget.clear()
        self.resolution.setCurrentText("稍后处理")
        self.export_status.setText(msg('尚未导出'))
        self._go(0, msg('开始'))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.investigation_page.monitor_thread is not None:
            self.investigation_page.stop_monitor()
            self.investigation_page.status.setText(msg('正在停止监测，请稍后再次关闭窗口。'))
            event.ignore()
            QTimer.singleShot(500, self.close)
            return
        if self.investigation_page.is_running:
            self.investigation_page.cancel_task()
            self.investigation_page.status.setText(msg('正在取消专项检查，请等待当前查询结束后再关闭。'))
            event.ignore()
            QTimer.singleShot(500, self.close)
            return
        if self.collection_thread is not None and self.collection_thread.isRunning():
            QMessageBox.information(self, msg('正在收集'), msg('请等待当前信息收集完成后再关闭。'))
            event.ignore()
            return
        if self.diagnostic_page.is_running:
            QMessageBox.information(self, msg('操作进行中'), msg('请等待修复完成，或取消只读诊断后再关闭。'))
            event.ignore()
            return
        self.investigation_page.stop_audio()
        self.screenshot_copies.cleanup()
        event.accept()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #F5F7FB; color: #1E293B; font-size: 14px; }
            QScrollArea { background: transparent; }
            QLabel#brand { font-size: 21px; font-weight: 700; color: #194C9B; }
            QLabel#step { color: #55708F; background: #E7EEF9; border-radius: 12px; padding: 6px 12px; }
            QLabel#hero { font-size: 30px; font-weight: 700; color: #102A43; }
            QLabel#pageTitle { font-size: 25px; font-weight: 700; color: #102A43; }
            QLabel#subtitle { font-size: 15px; color: #52667A; }
            QLabel#warningText { color: #8A4B08; }
            QLabel#noticeTitle { font-weight: 700; }
            QFrame#notice { background: #EAF3FF; border: 1px solid #BCD4F3; border-radius: 10px; }
            QFrame#warning { background: #FFF5DD; border: 1px solid #F0CF85; border-radius: 10px; }
            QFrame#panel { background: white; border: 1px solid #D7E0EA; border-radius: 10px; padding: 8px; }
            QLabel#statusBox { background: white; border: 1px solid #D7E0EA; border-radius: 8px; padding: 14px; }
            QLineEdit, QPlainTextEdit, QComboBox, QListWidget { background: white; border: 1px solid #C9D5E3; border-radius: 7px; padding: 7px; selection-background-color: #2F6FC4; }
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QListWidget:focus { border: 2px solid #2F6FC4; }
            QPushButton { background: white; border: 1px solid #B9C8D8; border-radius: 7px; padding: 8px 16px; }
            QPushButton:hover { background: #EDF3FA; }
            QPushButton#primary { background: #2467B7; color: white; border-color: #2467B7; font-weight: 600; }
            QPushButton#primary:hover { background: #19589F; }
            QProgressBar { border: 1px solid #C5D2E0; border-radius: 8px; background: white; text-align: center; }
            QProgressBar::chunk { background: #2F78C8; border-radius: 7px; }
            """
        )


def create_window() -> MainWindow:
    window = MainWindow()
    window.show()
    return window
