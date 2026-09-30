from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    permission_denied: bool = False
    unsupported: bool = False

    def json_value(self) -> Any:
        if self.returncode != 0 or not self.stdout.strip():
            return None
        return json.loads(self.stdout.lstrip("\ufeff"))


class CommandRunner:
    """Runs fixed argument arrays. Shell strings and user-provided commands are rejected."""

    def run(self, args: list[str] | tuple[str, ...], *, timeout: float = 15) -> CommandResult:
        if not isinstance(args, (list, tuple)) or not args or not all(isinstance(item, str) and item for item in args):
            raise ValueError("命令必须是非空参数数组")
        if any("\x00" in item or "\r" in item or "\n" in item for item in args):
            raise ValueError("命令参数包含不允许的控制字符")
        safe_args = tuple(args)
        try:
            completed = subprocess.run(
                safe_args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(safe_args, -1, _text(exc.stdout), _text(exc.stderr), timed_out=True)
        except FileNotFoundError:
            return CommandResult(safe_args, -1, "", "命令不可用", unsupported=True)
        except PermissionError:
            return CommandResult(safe_args, -1, "", "权限不足", permission_denied=True)
        stderr = completed.stderr or ""
        denied = completed.returncode != 0 and any(
            marker in stderr.lower() for marker in ("access is denied", "permissiondenied", "0x80041003", "拒绝访问")
        )
        return CommandResult(safe_args, completed.returncode, completed.stdout or "", stderr, permission_denied=denied)

    def powershell_json(self, script: str, *, timeout: float = 20) -> CommandResult:
        if not isinstance(script, str) or not script or "\x00" in script:
            raise ValueError("PowerShell 脚本无效")
        utf8_script = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); " + script
        return self.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                utf8_script,
            ],
            timeout=timeout,
        )

    def run_repair(self, args: list[str], *, timeout: float) -> CommandResult:
        """Do not terminate a process modifying drivers or Windows components."""
        allowed = {"ipconfig.exe", "netsh.exe", "wsreset.exe", "sc.exe", "powershell.exe", "w32tm.exe", "dism.exe", "sfc.exe", "pnputil.exe"}
        name = args[0].lower()
        if name not in allowed or any(any(c in item for c in "\x00\r\n") for item in args):
            raise ValueError("修复命令不在允许列表")
        system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        executable = system32 / ("WindowsPowerShell/v1.0/powershell.exe" if name == "powershell.exe" else name)
        safe_args = [str(executable), *args[1:]]
        # communicate(timeout=...) with subprocess.run kills a child on timeout.
        # Repair commands must be allowed to finish their system transaction.
        try:
            process = subprocess.Popen(safe_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                stdout, stderr = process.communicate()
            return CommandResult(tuple(safe_args), process.returncode, _text(stdout), _text(stderr))
        except FileNotFoundError:
            return CommandResult(tuple(safe_args), -1, "", "命令不可用", unsupported=True)
        except PermissionError:
            return CommandResult(tuple(safe_args), -1, "", "权限不足", permission_denied=True)


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""
