from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from helppack.attachments import add_attachments
from helppack.collector import _gateway_status
from helppack.diagnostics.checks import _command_json_result
from helppack.diagnostics.models import (
    DiagnosticStatus,
    RollbackCapability,
    ScanSummary,
    Severity,
)
from helppack.diagnostics.reporting import generate_diagnostic_markdown
from helppack.diagnostics.runner import CommandResult, CommandRunner
from helppack.diagnostics.software_analysis import SCENARIOS
from helppack.diagnostics.symptoms import route_symptom
from helppack.english import LABELS, MESSAGES, format_time, label, text
from helppack.exporter import export_zip
from helppack.models import ProblemDetails, ReportBundle, SystemSnapshot
from helppack.report import generate_markdown
from helppack.ui.localized_widgets import ChoiceBox
from helppack.ui.main_window import MainWindow
from helppack.ui.repair_review import RepairReview

_application = None


def app():
    global _application
    _application = QApplication.instance() or QApplication([])
    return _application


def test_catalog_is_english_and_all_calls_resolve():
    assert len(MESSAGES) > 650
    for message in [*MESSAGES.values(), *LABELS.values()]:
        assert not re.search("[\u4e00-\u9fff]", message), message
    root = Path(__file__).resolve().parents[1] / "src/helppack"
    for path in root.rglob("*.py"):
        if path.name == "english.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "msg":
                assert isinstance(node.args[0], ast.Constant), path
                assert node.args[0].value in MESSAGES, (path, node.args[0].value)


def test_ui_fixed_copy_and_choice_values_are_separate():
    app()
    window = MainWindow()
    for widget in window.findChildren(QLabel) + window.findChildren(QPushButton):
        assert not re.search("[\u4e00-\u9fff]", widget.text()), widget.text()
    for box in window.findChildren(ChoiceBox):
        for index in range(box.count()):
            assert not re.search("[\u4e00-\u9fff]", box.itemText(index))
    assert window.category.currentText() == "软件无法启动或崩溃"
    window.resolution.setCurrentText("已解决")
    assert window.resolution.currentText() == "已解决"
    assert window.resolution.itemText(window.resolution.currentIndex()) == "Resolved"
    assert SCENARIOS == ("无法启动", "闪退", "无响应", "安装失败")
    assert DiagnosticStatus.NORMAL.value == "正常"
    assert RollbackCapability.FULL.value == "可完整回滚"
    window.close()


@pytest.mark.parametrize(("symptom", "category"), [
    ("My computer suddenly became slow", "系统卡顿"),
    ("An app closes as soon as it opens", "软件或浏览器异常"),
    ("Connected to Wi-Fi but no internet", "网络或Wi-Fi异常"),
    ("Headphones connected but no sound", "声音问题"),
    ("软件无法启动", "软件或浏览器异常"), ("网络出错", "网络或Wi-Fi异常"),
])
def test_bilingual_symptom_routing(symptom, category):
    assert category in route_symptom(symptom)


def test_unicode_input_names_and_manifest_remain_compatible(tmp_path):
    folder = tmp_path / "中文路径"
    folder.mkdir()
    screenshot = folder / "原图截图.png"
    screenshot.write_bytes(b"synthetic PNG fixture")
    problem = ProblemDetails(category="网络问题", title="中文问题 Ω", description="用户原话：不能上网")
    bundle = ReportBundle(problem, SystemSnapshot(), add_attachments([], [screenshot]))
    markdown = generate_markdown(bundle)
    assert "## Problem Summary" in markdown
    assert "Network problems" in markdown
    assert problem.description in markdown and problem.title in markdown
    assert screenshot.name in markdown
    assert "Unable to read" in markdown
    destination = export_zip(markdown, bundle, folder / "unicode.zip")
    with zipfile.ZipFile(destination) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert set(manifest) == {"app", "app_version", "generated_at", "attachments", "files"}
        assert manifest["app"] == "HelpPack"
        assert str(folder.resolve()) not in json.dumps(manifest, ensure_ascii=False)
        assert archive.read("report.md").decode("utf-8") == markdown
        assert f"attachments/{screenshot.name}" in archive.namelist()
        for item in manifest["files"]:
            assert hashlib.sha256(archive.read(item["name"])).hexdigest() == item["sha256"]


@pytest.mark.parametrize("header", ["Active Routes:", "活动路由："])
def test_numeric_gateway_parser_is_language_independent(header):
    def run(args, **kwargs):
        output = header + "\n 0.0.0.0 0.0.0.0 192.0.2.1 192.0.2.2 25\n" if args[0] == "route" else ""
        return subprocess.CompletedProcess(args, 0, stdout=output)
    with patch("helppack.collector.subprocess.run", side_effect=run):
        assert _gateway_status() == "Reachable"


@pytest.mark.parametrize("raw", ["access is denied", "拒绝访问"])
def test_permission_detection_handles_both_languages(raw):
    completed = subprocess.CompletedProcess([], 1, b"", raw.encode("utf-8"))
    with patch("helppack.diagnostics.runner.subprocess.run", return_value=completed):
        result = CommandRunner().run(["fixed.exe"])
    assert result.permission_denied and result.stderr == raw


@pytest.mark.parametrize("raw", ["Status: Running", "状态：正在运行"])
def test_localized_human_output_is_not_guessed(raw):
    result = _command_json_result(CommandResult((), 0, raw, ""), "fixed.id", "综合检查", "Fixed Check", "Evidence", "Limitation")
    assert result.status == DiagnosticStatus.UNKNOWN
    assert "could not be read structurally" in result.explanation


def test_diagnostic_english_labels_preserve_original_logs():
    from helppack.diagnostics.models import DiagnosticResult, Evidence
    original = "原始日志：用户输入不翻译"
    result = DiagnosticResult("fixed.id", "综合检查", "Fixed Check", DiagnosticStatus.NOTICE,
                              Severity.LOW, [Evidence("Original Log", original)], "Explanation", "中", ["Recommended action"])
    markdown = generate_diagnostic_markdown(ScanSummary("综合检查", "start", "end", False, [result]))
    assert "Status: Notice" in markdown and "Confidence: Medium" in markdown
    assert original in markdown and "fixed.id" in markdown


def test_explicit_time_zone_and_opaque_template_values():
    assert format_time("2026-10-01T14:30:00+08:00") == "2026-10-01 14:30:00 UTC+08:00"
    assert text("- 问题标题：{0}", "正常 原始标题") == "- Title: 正常 原始标题"
    assert label("重置") == "RESET"


def test_repair_review_scrolls_and_defaults_to_no_changes():
    app()
    dialog = RepairReview("<p>Safety details " + "long evidence " * 2000 + "END_MARKER</p>")
    dialog.show()
    app().processEvents()
    assert "END_MARKER" in dialog.details.toPlainText()
    assert dialog.details.verticalScrollBar().maximum() > 0
    cancel = next(b for b in dialog.findChildren(QPushButton) if b.isDefault())
    assert cancel.text() == "Cancel — Make No Changes"
    cancel.click()
    assert dialog.result() == dialog.DialogCode.Rejected


def test_preview_action_remains_readable_at_minimum_window_size():
    app()
    window = MainWindow()
    window.resize(760, 560)
    window.show()
    window._go(4, "Preview")
    app().processEvents()
    button = next(b for b in window.findChildren(QPushButton) if b.text() == "Update Preview")
    assert button.isVisible()
    assert button.height() >= 40
    assert button.width() >= button.fontMetrics().horizontalAdvance(button.text())
    window.close()


def test_history_labels_are_english_without_changing_saved_values(tmp_path):
    from helppack.diagnostics.history import DiagnosticHistoryStore
    app()
    window = MainWindow()
    store = DiagnosticHistoryStore(tmp_path / "history")
    record_id = store.save_record({"kind": "扫描", "time": "2026-10-01T14:30:00+08:00",
                                   "status": "稍后处理", "report": "原始用户文字"})
    window.investigation_page.history = store
    window.investigation_page.refresh_history()
    caption = window.investigation_page.records.item(0).text()
    assert caption == "2026-10-01 14:30:00 UTC+08:00 · Check · Later"
    stored = store.load_record(record_id)
    assert stored["kind"] == "扫描" and stored["report"] == "原始用户文字"
    window.close()
