from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
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


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""
