from __future__ import annotations

import hashlib
import json
import os
import platform
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from ..redaction import redact_text
from .models import RepairSuggestion, SafetyLevel

ALLOWED_STARTUP_KEYS = {
    r"Software\Microsoft\Windows\CurrentVersion\Run",
    r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
}
PROXY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
PROXY_VALUES = ("ProxyEnable", "ProxyServer", "AutoConfigURL")


class RepairError(RuntimeError):
    pass


class ConfirmationRequired(RepairError):
    pass


class InvalidRepairTarget(RepairError):
    pass


class RegistryBackend(Protocol):
    def read_value(self, key_path: str, value_name: str) -> tuple[bool, Any, int]: ...
    def set_value(self, key_path: str, value_name: str, value: Any, value_type: int) -> None: ...
    def delete_value(self, key_path: str, value_name: str) -> None: ...


class WindowsRegistryBackend:
    def _key(self, key_path: str, access: int):
        if platform.system() != "Windows":
            raise NotImplementedError("仅支持 Windows")
        import winreg

        allowed = ALLOWED_STARTUP_KEYS | {PROXY_KEY}
        if key_path not in allowed:
            raise InvalidRepairTarget("注册表路径不在允许列表")
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, access)

    def read_value(self, key_path: str, value_name: str) -> tuple[bool, Any, int]:
        import winreg

        try:
            with self._key(key_path, winreg.KEY_QUERY_VALUE) as key:
                value, value_type = winreg.QueryValueEx(key, value_name)
                return True, value, value_type
        except FileNotFoundError:
            return False, None, winreg.REG_NONE

    def set_value(self, key_path: str, value_name: str, value: Any, value_type: int) -> None:
        import winreg

        with self._key(key_path, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, value_name, 0, value_type, value)

    def delete_value(self, key_path: str, value_name: str) -> None:
        import winreg

        with self._key(key_path, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, value_name)
            except FileNotFoundError:
                pass


@dataclass(slots=True)
class PreparedRepair:
    confirmation_id: str
    action_id: str
    display_name: str
    target: dict[str, str]
    safety_level: SafetyLevel
    requires_admin: bool
    impact: str
    operation_preview: str
    rollback: str
    target_digest: str


@dataclass(slots=True)
class RepairOutcome:
    executed: bool
    message: str
    backup_id: str | None = None
    recheck_completed: bool = False
    recheck_summary: str = ""


class BackupStore:
    def __init__(self, root: str | Path | None = None) -> None:
        default_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HelpPack" / "backups"
        self.root = Path(root) if root is not None else default_root

    def save(self, payload: dict[str, Any]) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        backup_id = f"{datetime.now(UTC).astimezone().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        path = self.root / f"{backup_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return backup_id

    def load(self, backup_id: str) -> dict[str, Any]:
        if not backup_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in backup_id):
            raise InvalidRepairTarget("备份编号无效")
        path = (self.root / f"{backup_id}.json").resolve()
        if path.parent != self.root.resolve():
            raise InvalidRepairTarget("备份路径越界")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_ids(self, limit: int = 20) -> list[str]:
        if not self.root.is_dir():
            return []
        files = sorted(self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        return [item.stem for item in files[:limit] if all(char.isalnum() or char in "_-" for char in item.stem)]


class RepairCoordinator:
    def __init__(self, backend: RegistryBackend | None = None, backups: BackupStore | None = None) -> None:
        self.backend = backend or WindowsRegistryBackend()
        self.backups = backups or BackupStore()
        self.audit_log: list[str] = []
        self._prepared: dict[str, PreparedRepair] = {}

    def prepare(self, suggestion: RepairSuggestion) -> PreparedRepair:
        self._validate_suggestion(suggestion)
        digest = _target_digest(suggestion.action_id, suggestion.target)
        prepared = PreparedRepair(
            confirmation_id=uuid.uuid4().hex,
            action_id=suggestion.action_id,
            display_name=suggestion.display_name,
            target=dict(suggestion.target),
            safety_level=suggestion.safety_level,
            requires_admin=suggestion.requires_admin,
            impact=suggestion.impact,
            operation_preview=suggestion.operation_preview,
            rollback=suggestion.rollback,
            target_digest=digest,
        )
        self._prepared[prepared.confirmation_id] = prepared
        return prepared

    def execute(self, prepared: PreparedRepair, *, user_confirmed: bool, recheck=None) -> RepairOutcome:
        current = self._prepared.pop(prepared.confirmation_id, None)
        if current is None or current.target_digest != _target_digest(prepared.action_id, prepared.target):
            raise ConfirmationRequired("确认已失效或对象发生变化")
        if not user_confirmed:
            self._log(f"用户拒绝修复：{prepared.display_name}")
            return RepairOutcome(False, "用户已取消，没有执行任何修改。")
        if prepared.requires_admin and not is_admin():
            raise PermissionError("此操作需要管理员权限")

        backup_payload = self._snapshot(prepared)
        backup_id = self.backups.save(backup_payload)
        if prepared.action_id == "disable_hkcu_startup":
            self.backend.delete_value(prepared.target["key_path"], prepared.target["value_name"])
        elif prepared.action_id == "reset_user_proxy":
            self._reset_proxy()
        else:
            raise InvalidRepairTarget("未知修复操作")
        self._log(f"已执行：{prepared.display_name}；备份：{backup_id}")

        recheck_completed = False
        recheck_summary = "未提供复查器"
        if recheck is not None:
            try:
                recheck_summary = str(recheck())
                recheck_completed = True
            except Exception as exc:  # noqa: BLE001 - recheck failure must not hide completed action
                recheck_summary = f"复查失败：{type(exc).__name__}"
        return RepairOutcome(
            True,
            "操作已执行；这不等于原问题已经解决，请查看复查结果。",
            backup_id=backup_id,
            recheck_completed=recheck_completed,
            recheck_summary=redact_text(recheck_summary),
        )

    def rollback(self, backup_id: str, *, user_confirmed: bool) -> RepairOutcome:
        if not user_confirmed:
            return RepairOutcome(False, "用户已取消，没有执行回滚。")
        payload = self.backups.load(backup_id)
        action_id = payload.get("action_id")
        values = payload.get("values", [])
        if action_id not in {"disable_hkcu_startup", "reset_user_proxy"}:
            raise InvalidRepairTarget("备份操作类型不受支持")
        for item in values:
            key_path = str(item["key_path"])
            value_name = str(item["value_name"])
            if item["exists"]:
                self.backend.set_value(key_path, value_name, item["value"], int(item["value_type"]))
            else:
                self.backend.delete_value(key_path, value_name)
        self._log(f"已回滚备份：{backup_id}")
        return RepairOutcome(True, "已按备份恢复原配置。", backup_id=backup_id)

    def _snapshot(self, prepared: PreparedRepair) -> dict[str, Any]:
        targets: list[tuple[str, str]]
        if prepared.action_id == "disable_hkcu_startup":
            targets = [(prepared.target["key_path"], prepared.target["value_name"])]
        else:
            targets = [(PROXY_KEY, name) for name in PROXY_VALUES]
        values = []
        for key_path, value_name in targets:
            exists, value, value_type = self.backend.read_value(key_path, value_name)
            values.append({"key_path": key_path, "value_name": value_name, "exists": exists, "value": value, "value_type": value_type})
        return {"version": 1, "action_id": prepared.action_id, "created_at": datetime.now().astimezone().isoformat(timespec="seconds"), "values": values}

    def _reset_proxy(self) -> None:
        import winreg

        self.backend.set_value(PROXY_KEY, "ProxyEnable", 0, winreg.REG_DWORD)
        self.backend.delete_value(PROXY_KEY, "ProxyServer")
        self.backend.delete_value(PROXY_KEY, "AutoConfigURL")

    def _validate_suggestion(self, suggestion: RepairSuggestion) -> None:
        if suggestion.safety_level not in {SafetyLevel.L1, SafetyLevel.L2}:
            raise InvalidRepairTarget("第一版只允许 L1 或 L2 修复")
        if suggestion.action_id == "disable_hkcu_startup":
            if suggestion.target.get("key_path") not in ALLOWED_STARTUP_KEYS:
                raise InvalidRepairTarget("启动项路径不受支持")
            name = suggestion.target.get("value_name", "")
            if not name or len(name) > 260 or any(char in name for char in "\r\n\x00\\/"):
                raise InvalidRepairTarget("启动项名称无效")
        elif suggestion.action_id == "reset_user_proxy":
            if suggestion.target != {"key_path": PROXY_KEY}:
                raise InvalidRepairTarget("代理对象不受支持")
        else:
            raise InvalidRepairTarget("操作不在允许列表")

    def _log(self, message: str) -> None:
        self.audit_log.append(redact_text(message))


def _target_digest(action_id: str, target: dict[str, str]) -> str:
    serialized = json.dumps({"action_id": action_id, "target": target}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def is_admin() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False
