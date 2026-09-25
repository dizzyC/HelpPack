import subprocess

import pytest

from helppack.diagnostics.checks import _command_json_result
from helppack.diagnostics.models import DiagnosticStatus
from helppack.diagnostics.runner import CommandResult, CommandRunner


def test_command_arguments_reject_control_character_injection() -> None:
    with pytest.raises(ValueError, match="控制字符"):
        CommandRunner().run(["safe.exe", "value\r\nmalicious"])


def test_runner_never_uses_shell(monkeypatch) -> None:
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "{}", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    CommandRunner().run(["tool.exe", "literal & not-a-command"])
    assert captured["shell"] is False


def test_localized_human_output_is_not_guessed_as_structured_data() -> None:
    command = CommandResult(("powershell",), 0, "任务已准备就绪，但这是本地化文本", "")
    result = _command_json_result(command, "id", "分类", "名称", "证据", "限制")
    assert result.status == DiagnosticStatus.UNKNOWN
    assert "无法结构化" in result.explanation


def test_permission_unsupported_and_timeout_are_distinct() -> None:
    permission = _command_json_result(CommandResult(("x",), 1, "", "拒绝访问", permission_denied=True), "p", "c", "n", "l", "x")
    unsupported = _command_json_result(CommandResult(("x",), -1, "", "", unsupported=True), "u", "c", "n", "l", "x")
    timeout = _command_json_result(CommandResult(("x",), -1, "", "", timed_out=True), "t", "c", "n", "l", "x")
    assert permission.status == DiagnosticStatus.PERMISSION_DENIED
    assert unsupported.status == DiagnosticStatus.UNSUPPORTED
    assert timeout.status == DiagnosticStatus.UNKNOWN
