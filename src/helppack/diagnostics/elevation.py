from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..redaction import redact_text
from .models import (
    RepairSuggestion,
    RestartRequirement,
    RollbackCapability,
    SafetyLevel,
)
from .repairs import (
    ADMIN_ACTIONS,
    ConfirmationRequired,
    RepairCoordinator,
    RepairOutcome,
)


class ElevationError(RuntimeError):
    pass


class ElevationRequestStore:
    def __init__(self, root: str | Path | None = None) -> None:
        default_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HelpPack" / "operations"
        self.root = Path(root) if root is not None else default_root

    def create(self, suggestion: RepairSuggestion) -> tuple[Path, str, Path]:
        self.root.mkdir(parents=True, exist_ok=True)
        operation_id = uuid.uuid4().hex
        secret = os.urandom(32).hex()
        payload = {
            "version": 1,
            "operation_id": operation_id,
            "nonce": uuid.uuid4().hex,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            "suggestion": _suggestion_to_dict(suggestion),
        }
        payload["hmac"] = _sign(payload, secret)
        request_path = self.root / f"{operation_id}.request.json"
        result_path = self.root / f"{operation_id}.result.json"
        request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if os.name == "nt":
            from .windows_security import assert_current_user_owns
            assert_current_user_owns(request_path)
        return request_path, secret, result_path

    def validate_path(self, path: str | Path) -> Path:
        original = Path(path)
        if original.is_symlink() or original.is_junction():
            raise ElevationError("提权请求不能是链接")
        candidate = Path(path).resolve()
        root = self.root.resolve()
        if candidate.parent != root or not candidate.name.endswith(".request.json"):
            raise ElevationError("提权请求路径越界")
        if not re.fullmatch(r"[0-9a-f]{32}\.request\.json", candidate.name):
            raise ElevationError("提权请求编号格式无效")
        if os.name == "nt":
            from .windows_security import assert_current_user_owns
            assert_current_user_owns(candidate)
        return candidate


class ElevationBroker:
    def __init__(self, store: ElevationRequestStore | None = None) -> None:
        self.store = store or ElevationRequestStore()

    def execute(self, suggestion: RepairSuggestion, *, timeout: int | None = None) -> RepairOutcome:
        request_path, secret, result_path = self.store.create(suggestion)
        maximum = timeout or max(120, min(suggestion.estimated_seconds + 120, 7500))
        exit_code = _run_as_admin(request_path, secret, maximum)
        if exit_code == 1223:
            raise ElevationError("用户取消了 Windows 管理员权限确认")
        if not result_path.is_file():
            raise ElevationError(f"管理员辅助进程没有返回结果（退出码 {exit_code}）")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        signature = str(result.pop("hmac", ""))
        if not hmac.compare_digest(signature, _sign(result, secret)):
            raise ElevationError("辅助进程结果校验失败")
        if not result.get("ok"):
            raise ElevationError(str(result.get("error", "管理员操作失败")))
        return RepairOutcome(**result["outcome"])


def run_elevated_helper(request_path: str, secret: str, store: ElevationRequestStore | None = None) -> int:
    request_store = store or ElevationRequestStore()
    result_path: Path | None = None
    try:
        path = request_store.validate_path(request_path)
        # Derive output names from the validated filename, never untrusted JSON.
        operation_id = path.name.split(".", 1)[0]
        result_path = path.with_name(f"{operation_id}.result.json")
        if result_path.exists():
            return 2
        if path.stat().st_size > 65536:
            raise ElevationError("提权请求超过大小限制")
        payload = json.loads(path.read_text(encoding="utf-8"))
        signature = str(payload.pop("hmac", ""))
        if not hmac.compare_digest(signature, _sign(payload, secret)):
            raise ElevationError("提权请求摘要不匹配")
        if datetime.now(UTC) > datetime.fromisoformat(str(payload["expires_at"])):
            raise ConfirmationRequired("提权请求已过期")
        if path.stem.split(".", 1)[0] != payload.get("operation_id"):
            raise ElevationError("提权请求编号不匹配")
        if not re.fullmatch(r"[0-9a-f]{32}", str(payload.get("nonce", ""))):
            raise ElevationError("提权请求随机标识无效")
        # Exclusive creation atomically consumes the request before any mutation.
        with path.with_suffix(".consumed").open("x", encoding="utf-8") as marker:
            marker.write(datetime.now(UTC).isoformat())
        suggestion = _suggestion_from_dict(dict(payload["suggestion"]))
        if not suggestion.requires_admin or suggestion.action_id not in ADMIN_ACTIONS:
            raise ElevationError("当前用户操作不能通过管理员辅助进程执行")
        coordinator = RepairCoordinator()
        prepared = coordinator.prepare(suggestion)
        confirmation: str | bool = suggestion.confirmation_phrase or True
        outcome = coordinator.execute(prepared, user_confirmed=True, second_confirmation=confirmation)
        response = {"ok": True, "outcome": _outcome_to_dict(outcome)}
        response["hmac"] = _sign(response, secret)
        with result_path.open("x", encoding="utf-8") as result_file:
            json.dump(response, result_file, ensure_ascii=False)
        return 0
    except Exception as exc:  # noqa: BLE001 - helper boundary returns a user-safe error
        if result_path is None:
            return 2
        with result_path.open("x", encoding="utf-8") as result_file:
            response = {"ok": False, "error": redact_text(f"{type(exc).__name__}: {exc}")}
            response["hmac"] = _sign(response, secret)
            json.dump(response, result_file, ensure_ascii=False)
        return 1


def _sign(payload: dict[str, Any], secret: str) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        key = bytes.fromhex(secret)
    except ValueError as exc:
        raise ElevationError("提权能力令牌无效") from exc
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def _suggestion_to_dict(item: RepairSuggestion) -> dict[str, Any]:
    return {
        "action_id": item.action_id,
        "display_name": item.display_name,
        "target": item.target,
        "safety_level": item.safety_level.value,
        "requires_admin": item.requires_admin,
        "impact": item.impact,
        "operation_preview": item.operation_preview,
        "rollback": item.rollback,
        "rollback_capability": item.rollback_capability.value,
        "restart_requirement": item.restart_requirement.value,
        "requires_network": item.requires_network,
        "side_effects": item.side_effects,
        "evidence_ids": item.evidence_ids,
        "estimated_seconds": item.estimated_seconds,
        "requires_second_confirmation": item.requires_second_confirmation,
        "confirmation_phrase": item.confirmation_phrase,
    }


def _suggestion_from_dict(value: dict[str, Any]) -> RepairSuggestion:
    target = value.get("target")
    if not isinstance(target, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in target.items()):
        raise ElevationError("提权目标参数类型无效")
    return RepairSuggestion(
        action_id=str(value["action_id"]), display_name=str(value["display_name"]), target=target,
        safety_level=SafetyLevel(value["safety_level"]), requires_admin=bool(value["requires_admin"]),
        impact=str(value["impact"]), operation_preview=str(value["operation_preview"]), rollback=str(value["rollback"]),
        rollback_capability=RollbackCapability(value["rollback_capability"]), restart_requirement=RestartRequirement(value["restart_requirement"]),
        requires_network=bool(value.get("requires_network")), side_effects=[str(item) for item in value.get("side_effects", [])],
        evidence_ids=[str(item) for item in value.get("evidence_ids", [])], estimated_seconds=int(value.get("estimated_seconds", 10)),
        requires_second_confirmation=bool(value.get("requires_second_confirmation")), confirmation_phrase=str(value.get("confirmation_phrase", "")),
    )


def _outcome_to_dict(item: RepairOutcome) -> dict[str, Any]:
    return {name: getattr(item, name) for name in item.__dataclass_fields__}


def _run_as_admin(request_path: Path, secret: str, timeout: int) -> int:
    if os.name != "nt":
        raise ElevationError("管理员辅助模式仅支持 Windows")
    if getattr(sys, "frozen", False):
        executable = sys.executable
        arguments = ["--elevated-helper", str(request_path), secret]
    else:
        executable = sys.executable
        arguments = ["-m", "helppack", "--elevated-helper", str(request_path), secret]

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong), ("fMask", ctypes.c_ulong), ("hwnd", ctypes.c_void_p),
            ("lpVerb", ctypes.c_wchar_p), ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
            ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int), ("hInstApp", ctypes.c_void_p),
            ("lpIDList", ctypes.c_void_p), ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
            ("dwHotKey", ctypes.c_ulong), ("hIconOrMonitor", ctypes.c_void_p), ("hProcess", ctypes.c_void_p),
        ]

    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = subprocess.list2cmdline(arguments)
    info.nShow = 0
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = ctypes.c_int
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = ctypes.c_ulong
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == 1223:
            return code
        raise ElevationError(f"无法启动管理员辅助进程（Windows 错误 {code}）")
    wait_result = kernel.WaitForSingleObject(info.hProcess, int(timeout * 1000))
    if wait_result == 0x00000102:
        kernel.CloseHandle(info.hProcess)
        raise ElevationError("管理员操作等待超时；未强制终止系统修复进程")
    exit_code = ctypes.c_ulong()
    kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code))
    kernel.CloseHandle(info.hProcess)
    time.sleep(0.05)
    return int(exit_code.value)
