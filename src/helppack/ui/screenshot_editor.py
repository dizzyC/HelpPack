from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ImageCanvas(QWidget):
    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        # Render pixels into a fresh image: do not export source text/EXIF metadata.
        self.image = QImage(image.size(), QImage.Format.Format_ARGB32)
        self.image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.image)
        painter.drawImage(0, 0, image)
        painter.end()
        self.mode = "遮挡"
        self.selection = QRect()
        self.undo_images: list[QImage] = []
        self.setMinimumSize(400, 260)

    def target_rect(self):
        size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect((self.width() - size.width()) // 2, (self.height() - size.height()) // 2, size.width(), size.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#e2e8f0"))
        target = self.target_rect()
        painter.drawImage(target, self.image)
        painter.setPen(QPen(QColor("#2563eb"), 2))
        painter.drawRect(self.selection)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.anchor = event.position().toPoint()
            self.selection = QRect(self.anchor, self.anchor)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and hasattr(self, "anchor"):
            self.selection = QRect(self.anchor, event.position().toPoint()).normalized().intersected(self.target_rect())
            self.update()

    def image_rect(self):
        target = self.target_rect()
        if target.width() <= 0 or target.height() <= 0 or self.selection.isEmpty():
            return QRect()
        rect = self.selection.intersected(target)
        return QRect(round((rect.x() - target.x()) * self.image.width() / target.width()),
                     round((rect.y() - target.y()) * self.image.height() / target.height()),
                     round(rect.width() * self.image.width() / target.width()),
                     round(rect.height() * self.image.height() / target.height())).intersected(self.image.rect())

    def apply_rect(self, rect: QRect, mode: str):
        if rect.isEmpty() or not self.image.rect().contains(rect):
            raise ValueError("请在图片内拖动选择有效区域")
        if mode not in {"遮挡", "裁剪"}:
            raise ValueError("编辑类型无效")
        self.undo_images.append(self.image.copy())
        self.undo_images = self.undo_images[-5:]
        if mode == "裁剪":
            self.image = self.image.copy(rect)
        else:
            painter = QPainter(self.image)
            painter.fillRect(rect, Qt.GlobalColor.black)
            painter.end()
        self.selection = QRect()
        self.update()

    def undo(self):
        if self.undo_images:
            self.image = self.undo_images.pop()
            self.selection = QRect()
            self.update()


class ScreenshotEditor(QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        reader = QImageReader(str(path))
        size = reader.size()
        if size.width() <= 0 or size.height() <= 0 or size.width() * size.height() > 20000000:
            raise ValueError("图片无法读取或超过 2000 万像素编辑上限")
        image = reader.read().convertToFormat(QImage.Format.Format_ARGB32)
        if image.isNull():
            raise ValueError("图片格式或内容无效")
        self.setWindowTitle("截图裁剪与手动遮挡 · 原图不改变")
        self.resize(850, 650)
        layout = QVBoxLayout(self)
        hint = QLabel("在图中拖动选择区域，再点击应用。遮挡使用不透明黑色；请检查所有敏感区域，导出只用处理后的 PNG 副本。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.canvas = ImageCanvas(image)
        layout.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["遮挡", "裁剪"])
        row.addWidget(self.mode)
        apply = QPushButton("应用选区")
        apply.clicked.connect(self.apply)
        undo = QPushButton("撤销")
        undo.clicked.connect(self.canvas.undo)
        save = QPushButton("使用处理后的副本")
        save.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        for button in (apply, undo, save, cancel):
            row.addWidget(button)
        layout.addLayout(row)
        self.message = QLabel()
        layout.addWidget(self.message)

    def apply(self):
        try:
            self.canvas.apply_rect(self.canvas.image_rect(), self.mode.currentText())
            self.message.setText("已应用；原图未修改。")
        except ValueError as exc:
            self.message.setText(str(exc))
