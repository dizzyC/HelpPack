"""Scrollable, resizable safety review for long English repair descriptions."""
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ..english import text


class RepairReview(QDialog):
    def __init__(self, details: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(text("repair.review"))
        self.resize(740, 560)
        self.setMinimumSize(480, 360)
        layout = QVBoxLayout(self)
        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(False)
        self.details.setHtml(details)
        layout.addWidget(self.details, 1)
        row = QHBoxLayout()
        cancel = QPushButton(text("repair.cancel"))
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        run = QPushButton(text("repair.run"))
        run.setAutoDefault(False)
        run.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addStretch()
        row.addWidget(run)
        layout.addLayout(row)
