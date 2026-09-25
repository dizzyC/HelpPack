from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


def configure_local_font(app: QApplication) -> str:
    """Load an installed Windows CJK font without bundling or downloading fonts."""
    fonts_root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for filename in ("msyh.ttc", "Deng.ttf", "simhei.ttf", "simsun.ttc"):
        path = fonts_root / filename
        if not path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
            return families[0]
    return app.font().family()
