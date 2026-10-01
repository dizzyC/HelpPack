"""English presentation of fixed choices with compatible persisted values."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox

from ..english import label


class ChoiceBox(QComboBox):
    COMPATIBILITY_ROLE = Qt.ItemDataRole.UserRole + 1

    def addItem(self, text, userData=None):
        super().addItem(label(text), userData)
        self.setItemData(self.count() - 1, text, self.COMPATIBILITY_ROLE)

    def addItems(self, texts):
        for value in texts:
            self.addItem(value)

    def currentText(self):
        value = self.currentData(self.COMPATIBILITY_ROLE)
        return value if value is not None else super().currentText()

    def setCurrentText(self, text):
        index = self.findData(text, self.COMPATIBILITY_ROLE)
        if index >= 0:
            self.setCurrentIndex(index)
        else:
            super().setCurrentText(text)
