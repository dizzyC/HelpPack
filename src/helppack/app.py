from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from .ui.font import configure_local_font
from .ui.main_window import create_window


def _maybe_run_elevated_helper() -> int | None:
    if len(sys.argv) == 4 and sys.argv[1] == "--elevated-helper":
        from .diagnostics.elevation import run_elevated_helper

        return run_elevated_helper(sys.argv[2], sys.argv[3])
    return None


def main() -> int:
    helper_result = _maybe_run_elevated_helper()
    if helper_result is not None:
        return helper_result
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        from .validation import run_self_check
        return run_self_check(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--plan-self-check":
        from .plan_acceptance import run
        return run(sys.argv[2])
    app = QApplication(sys.argv)
    app.setApplicationName("HelpPack-English")
    app.setOrganizationName("HelpPack")
    configure_local_font(app)
    window = create_window()  # noqa: F841 - keep the top-level window alive through app.exec()
    smoke_exit = os.environ.get("HELPPACK_SMOKE_EXIT_MS", "")
    if smoke_exit.isdigit() and 0 < int(smoke_exit) <= 60_000:
        QTimer.singleShot(int(smoke_exit), app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
