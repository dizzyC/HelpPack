from __future__ import annotations

import base64
import copy
import ctypes
import hashlib
import ipaddress
import json
import os
import platform
import re
import uuid
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from helppack.english import text as msg

from ..plan_resources import tr
from ..redaction import redact_text
from .models import (
    RepairSuggestion,
    RestartRequirement,
    RollbackCapability,
    SafetyLevel,
)
from .runner import CommandResult, CommandRunner

ALLOWED_STARTUP_KEYS = {
    r"Software\Microsoft\Windows\CurrentVersion\Run",
    r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
}
PROXY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
PROXY_VALUES = ("ProxyEnable", "ProxyServer", "AutoConfigURL")
ALLOWED_SERVICES = frozenset({"wuauserv", "BITS", "cryptsvc", "Spooler", "Audiosrv", "AudioEndpointBuilder", "bthserv"})
GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
OFFICIAL_DRIVER_HOSTS = frozenset({"www.dell.com", "support.lenovo.com", "support.hp.com", "www.intel.com", "www.nvidia.com", "www.amd.com"})
ADMIN_ACTIONS = frozenset({"renew_dhcp", "reset_dns_to_dhcp", "reset_winsock", "reset_tcp_ip", "service_start", "service_restart", "time_resync", "dism_restore_health", "sfc_scan", "scan_devices", "install_wua_driver", "install_inf_driver"})
HIGH_RISK_ACTIONS = frozenset({"reset_winsock", "reset_tcp_ip", "store_reset_data", "dism_restore_health", "sfc_scan", "install_wua_driver", "install_inf_driver"})


HIGH_RISK_ACTIONS = HIGH_RISK_ACTIONS | frozenset({"renew_dhcp", "reset_dns_to_dhcp", "reset_user_proxy", "service_restart"})

ADMIN_ACTIONS = ADMIN_ACTIONS | frozenset({"flush_dns_cache", "restore_dns_settings", "restore_service_state"})


class RepairError(RuntimeError):
    pass


class ConfirmationRequired(RepairError):
    pass


class InvalidRepairTarget(RepairError):
    pass


class RepairExecutionError(RepairError):
    pass


class RegistryBackend(Protocol):
    def read_value(self, key_path: str, value_name: str) -> tuple[bool, Any, int]: ...
    def set_value(self, key_path: str, value_name: str, value: Any, value_type: int) -> None: ...
    def delete_value(self, key_path: str, value_name: str) -> None: ...


class RepairHandler(Protocol):
    action_id: str

    def validate(self, target: dict[str, str]) -> None: ...
    def snapshot(self, target: dict[str, str]) -> dict[str, Any] | None: ...
    def execute(self, target: dict[str, str]) -> str: ...
    def verify(self, target: dict[str, str]) -> tuple[bool, str]: ...
    def rollback(self, snapshot: dict[str, Any]) -> str: ...


class WindowsRegistryBackend:
    def _key(self, key_path: str, access: int):
        if platform.system() != "Windows":
            raise NotImplementedError(msg('仅支持 Windows'))
        import winreg

        if key_path not in ALLOWED_STARTUP_KEYS | {PROXY_KEY}:
            raise InvalidRepairTarget(msg('注册表路径不在允许列表'))
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
    rollback_capability: RollbackCapability = RollbackCapability.FULL
    restart_requirement: RestartRequirement = RestartRequirement.NONE
    requires_network: bool = False
    side_effects: list[str] | None = None
    evidence_ids: list[str] | None = None
    estimated_seconds: int = 10
    requires_second_confirmation: bool = False
    confirmation_phrase: str = ""
    expires_at: str = ""


@dataclass(slots=True)
class RepairOutcome:
    executed: bool
    message: str
    backup_id: str | None = None
    recheck_completed: bool = False
    recheck_summary: str = ""
    verified: bool | None = None
    restart_required: bool = False
    action_id: str = ""


class BackupStore:
    def __init__(self, root: str | Path | None = None) -> None:
        default_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HelpPack" / "backups"
        self.root = Path(root) if root is not None else default_root

    def save(self, payload: dict[str, Any], *, sensitive: bool = False) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        backup_id = f"{datetime.now(UTC).astimezone().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        path = self.root / f"{backup_id}.json"
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        if sensitive and platform.system() == "Windows":
            envelope: dict[str, Any] = {"format": "dpapi-v1", "payload": base64.b64encode(_dpapi(raw, protect=True)).decode("ascii")}
        else:
            envelope = {"format": "json-v1", "payload": payload}
        path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        return backup_id

    def load(self, backup_id: str) -> dict[str, Any]:
        if not backup_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in backup_id):
            raise InvalidRepairTarget(msg('备份编号无效'))
        path = (self.root / f"{backup_id}.json").resolve()
        if path.parent != self.root.resolve():
            raise InvalidRepairTarget(msg('备份路径越界'))
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if envelope.get("format") == "dpapi-v1":
            raw = _dpapi(base64.b64decode(envelope["payload"]), protect=False)
            return json.loads(raw.decode("utf-8"))
        if envelope.get("format") == "json-v1":
            return dict(envelope["payload"])
        return envelope  # v0.2 compatibility

    def list_ids(self, limit: int = 20) -> list[str]:
        if not self.root.is_dir():
            return []
        files = sorted(self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        return [item.stem for item in files[:limit] if all(char.isalnum() or char in "_-" for char in item.stem)]


class RegistryRepairHandler:
    def __init__(self, action_id: str, backend: RegistryBackend) -> None:
        self.action_id = action_id
        self.backend = backend

    def validate(self, target: dict[str, str]) -> None:
        if self.action_id == "disable_hkcu_startup":
            if set(target) != {"key_path", "value_name"} or target.get("key_path") not in ALLOWED_STARTUP_KEYS:
                raise InvalidRepairTarget(msg('启动项路径不受支持'))
            name = target.get("value_name", "")
            if not name or len(name) > 260 or any(char in name for char in "\r\n\x00\\/"):
                raise InvalidRepairTarget(msg('启动项名称无效'))
        elif target != {"key_path": PROXY_KEY}:
            raise InvalidRepairTarget(msg('代理对象不受支持'))

    def snapshot(self, target: dict[str, str]) -> dict[str, Any]:
        targets = [(target["key_path"], target["value_name"])] if self.action_id == "disable_hkcu_startup" else [(PROXY_KEY, name) for name in PROXY_VALUES]
        values = []
        for key_path, value_name in targets:
            exists, value, value_type = self.backend.read_value(key_path, value_name)
            values.append({"key_path": key_path, "value_name": value_name, "exists": exists, "value": value, "value_type": value_type})
        return {"values": values}

    def execute(self, target: dict[str, str]) -> str:
        if self.action_id == "disable_hkcu_startup":
            self.backend.delete_value(target["key_path"], target["value_name"])
            return msg('已禁用所选当前用户启动项。')
        import winreg

        self.backend.set_value(PROXY_KEY, "ProxyEnable", 0, winreg.REG_DWORD)
        self.backend.delete_value(PROXY_KEY, "ProxyServer")
        self.backend.delete_value(PROXY_KEY, "AutoConfigURL")
        return msg('已重置当前用户代理和 PAC。')

    def verify(self, target: dict[str, str]) -> tuple[bool, str]:
        if self.action_id == "disable_hkcu_startup":
            exists, _value, _kind = self.backend.read_value(target["key_path"], target["value_name"])
            return not exists, msg('启动项已不存在') if not exists else msg('启动项仍然存在')
        enabled_exists, enabled_value, _kind = self.backend.read_value(PROXY_KEY, "ProxyEnable")
        server_exists, _server, _kind = self.backend.read_value(PROXY_KEY, "ProxyServer")
        pac_exists, _pac, _kind = self.backend.read_value(PROXY_KEY, "AutoConfigURL")
        ok = (not enabled_exists or not bool(enabled_value)) and not server_exists and not pac_exists
        return ok, msg('当前用户代理已关闭') if ok else msg('代理配置仍然存在')

    def rollback(self, snapshot: dict[str, Any]) -> str:
        values = snapshot.get("values", [])
        if not isinstance(values, list) or not values:
            raise InvalidRepairTarget(msg('备份内容无效'))
        for item in values:
            if self.action_id == "disable_hkcu_startup":
                self.validate({"key_path": str(item["key_path"]), "value_name": str(item["value_name"])})
                if len(values) != 1:
                    raise InvalidRepairTarget(msg('启动项备份必须只有一个目标'))
            elif item["key_path"] != PROXY_KEY or item["value_name"] not in PROXY_VALUES:
                raise InvalidRepairTarget(msg('备份超出代理恢复范围'))
        for item in values:
            if item["exists"]:
                self.backend.set_value(str(item["key_path"]), str(item["value_name"]), item["value"], int(item["value_type"]))
            else:
                self.backend.delete_value(str(item["key_path"]), str(item["value_name"]))
        return msg('已按备份恢复原配置。')


class CommandRepairHandler:
    def __init__(self, action_id: str, runner: CommandRunner, validator: Callable[[dict[str, str]], None], command: Callable[[dict[str, str]], tuple[list[str], float]], verifier: Callable[[dict[str, str]], tuple[bool, str]] | None = None, snapshotter: Callable[[dict[str, str]], dict[str, Any] | None] | None = None, rollbacker: Callable[[dict[str, Any]], str] | None = None) -> None:
        self.action_id, self.runner, self._validator, self._command = action_id, runner, validator, command
        self._verifier, self._snapshotter, self._rollbacker = verifier, snapshotter, rollbacker

    def validate(self, target: dict[str, str]) -> None:
        self._validator(target)

    def snapshot(self, target: dict[str, str]) -> dict[str, Any] | None:
        return self._snapshotter(target) if self._snapshotter else None

    def execute(self, target: dict[str, str]) -> str:
        from .preflight import check_preconditions
        check_preconditions(self.action_id, target, self.runner)
        args, timeout = self._command(target)
        result = self.runner.run_repair(args, timeout=timeout)
        self.last_exit_code = result.returncode
        _ensure_command_success(result)
        if self.action_id == "install_wua_driver":
            value = result.json_value()
            self.restart_required = bool(value.get("RebootRequired")) if isinstance(value, dict) else True
        output = (result.stdout or result.stderr).strip()
        return redact_text(output[-4000:] if output else msg('系统命令已完成。'))

    def verify(self, target: dict[str, str]) -> tuple[bool | None, str]:
        return self._verifier(target) if self._verifier else (None, msg('命令已完成；尚不能确认原问题是否解决。'))

    def rollback(self, snapshot: dict[str, Any]) -> str:
        if self._rollbacker is None:
            raise InvalidRepairTarget(msg('此操作不支持自动回滚'))
        return self._rollbacker(snapshot)


class OfficialUrlHandler:
    action_id = "open_vendor_support"

    def validate(self, target: dict[str, str]) -> None:
        from urllib.parse import urlparse

        if set(target) != {"url"}:
            raise InvalidRepairTarget(msg('厂商支持目标无效'))
        parsed = urlparse(target["url"])
        if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_DRIVER_HOSTS or parsed.username or parsed.password:
            raise InvalidRepairTarget(msg('只允许打开白名单中的官方 HTTPS 驱动网站'))

    def snapshot(self, target: dict[str, str]) -> None:
        return None

    def execute(self, target: dict[str, str]) -> str:
        if not webbrowser.open(target["url"], new=2):
            raise RepairExecutionError(msg('系统没有接受打开浏览器的请求'))
        return msg('已在默认浏览器中打开官方驱动支持页面。')

    def verify(self, target: dict[str, str]) -> tuple[bool, str]:
        return True, msg('已把官方 HTTPS 地址交给默认浏览器')

    def rollback(self, snapshot: dict[str, Any]) -> str:
        raise InvalidRepairTarget(msg('打开网页无需回滚'))


class RepairCoordinator:
    def __init__(self, backend: RegistryBackend | None = None, backups: BackupStore | None = None, runner: CommandRunner | None = None, handlers: dict[str, RepairHandler] | None = None) -> None:
        self.backend = backend or WindowsRegistryBackend()
        self.backups = backups or BackupStore()
        self.runner = runner or CommandRunner()
        self.handlers = handlers or build_default_handlers(self.backend, self.runner)
        self.audit_log: list[str] = []
        self._prepared: dict[str, PreparedRepair] = {}
        if handlers is None:
            from .repair_actions import install_safe_handlers
            install_safe_handlers(self)

    def prepare(self, suggestion: RepairSuggestion) -> PreparedRepair:
        suggestion = copy.deepcopy(suggestion)
        if suggestion.action_id in ADMIN_ACTIONS:
            suggestion.requires_admin = True
        if suggestion.action_id in HIGH_RISK_ACTIONS:
            suggestion.safety_level = SafetyLevel.L3
            suggestion.requires_second_confirmation = True
        if suggestion.action_id == "store_reset_data":
            suggestion.confirmation_phrase = "重置"
        if suggestion.safety_level == SafetyLevel.L0:
            raise InvalidRepairTarget(msg('只读检查不是修复操作'))
        handler = self.handlers.get(suggestion.action_id)
        if handler is None:
            raise InvalidRepairTarget(msg('操作不在允许列表'))
        handler.validate(suggestion.target)
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
            target_digest=_target_digest(suggestion.action_id, suggestion.target),
            rollback_capability=suggestion.rollback_capability,
            restart_requirement=suggestion.restart_requirement,
            requires_network=suggestion.requires_network,
            side_effects=list(suggestion.side_effects),
            evidence_ids=list(suggestion.evidence_ids),
            estimated_seconds=max(1, min(suggestion.estimated_seconds, 7200)),
            requires_second_confirmation=suggestion.requires_second_confirmation or suggestion.safety_level == SafetyLevel.L3,
            confirmation_phrase=suggestion.confirmation_phrase,
            expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        )
        self._prepared[prepared.confirmation_id] = copy.deepcopy(prepared)
        return prepared

    def execute(self, prepared: PreparedRepair, *, user_confirmed: bool, second_confirmation: str | bool = False, recheck=None) -> RepairOutcome:
        current = self._prepared.pop(prepared.confirmation_id, None)
        if current is None or current != prepared or current.target_digest != _target_digest(prepared.action_id, prepared.target):
            raise ConfirmationRequired(msg('确认已失效或对象发生变化'))
        if datetime.now(UTC) > datetime.fromisoformat(current.expires_at):
            raise ConfirmationRequired(msg('确认已过期，请重新查看操作内容'))
        if not user_confirmed:
            self._log(msg('用户拒绝修复：{0}', prepared.display_name))
            return RepairOutcome(False, msg('用户已取消，没有执行任何修改。'), action_id=prepared.action_id)
        if current.requires_second_confirmation:
            expected = current.confirmation_phrase
            confirmed = second_confirmation is True if not expected else second_confirmation == expected
            if not confirmed:
                raise ConfirmationRequired(msg('高风险操作需要完成第二次确认'))
        if prepared.requires_admin and not is_admin():
            raise PermissionError(msg('此操作需要管理员权限'))

        handler = self.handlers[prepared.action_id]
        handler.validate(prepared.target)
        snapshot = handler.snapshot(prepared.target)
        if prepared.action_id == "disable_hkcu_startup" and not any(v["exists"] for v in snapshot["values"]):
            raise RepairExecutionError(tr("stale"))
        backup_id = None
        if snapshot is not None:
            payload = {"version": 2, "action_id": prepared.action_id, "target": prepared.target, "created_at": datetime.now().astimezone().isoformat(timespec="seconds"), "rollback_capability": prepared.rollback_capability.value, "snapshot": snapshot}
            backup_id = self.backups.save(payload, sensitive=True)
        self._record_operation(prepared.action_id, msg('执行中'), backup_id)
        try:
            message = handler.execute(prepared.target)
            if snapshot is not None:
                payload["post_snapshot"] = handler.snapshot(prepared.target)
                backup_id = self.backups.save(payload, sensitive=True)
        except Exception:
            self._record_operation(prepared.action_id, msg('执行未完整完成；需要复查'), backup_id)
            raise
        try:
            verified, verification = handler.verify(prepared.target)
        except Exception as exc:  # noqa: BLE001 - preserve evidence of completed mutation
            verified, verification = None, msg('操作已执行，复查不可用：{0}', type(exc).__name__)
        self._record_operation(prepared.action_id, msg('命令完成'), backup_id, verification)
        self._log(msg('已执行：{0}；验证：{1}', prepared.display_name, verification))
        recheck_completed, recheck_summary = True, verification
        if recheck is not None:
            try:
                recheck_summary = str(recheck())
            except Exception as exc:  # noqa: BLE001
                recheck_summary, recheck_completed = msg('复查失败：{0}', type(exc).__name__), False
        state = msg('目标状态复查通过；请确认原问题是否解决。') if verified is True else (msg('操作已完成，但复查未通过。') if verified is False else msg('操作已完成，原问题是否解决尚未验证。'))
        restart_required = prepared.restart_requirement == RestartRequirement.SYSTEM or bool(getattr(handler, "restart_required", False))
        return RepairOutcome(True, f"{message}\n{state}", backup_id, recheck_completed, redact_text(recheck_summary), verified, restart_required, prepared.action_id)

    def rollback(self, backup_id: str, *, user_confirmed: bool) -> RepairOutcome:
        if not user_confirmed:
            return RepairOutcome(False, msg('用户已取消，没有执行回滚。'))
        payload = self.backups.load(backup_id)
        handler = self.handlers.get(str(payload.get("action_id", "")))
        if handler is None:
            raise InvalidRepairTarget(msg('备份操作类型不受支持'))
        if payload.get("rollback_capability") == RollbackCapability.NONE.value:
            raise InvalidRepairTarget(msg('此操作没有自动回滚能力'))
        if "post_snapshot" not in payload:
            raise RepairExecutionError(tr("unavailable"))
        if payload["action_id"] in {"reset_dns_to_dhcp", "service_start"} and not is_admin():
            raise PermissionError(tr("permission"))
        from .repair_actions import state_signature
        target = payload.get("target", {})
        handler.validate(target)
        if state_signature(handler.snapshot(target)) != state_signature(payload["post_snapshot"]):
            raise RepairExecutionError(tr("conflict"))
        message = handler.rollback(dict(payload.get("snapshot", payload)))
        self._log(msg('已回滚备份：{0}', backup_id))
        return RepairOutcome(True, message, backup_id=backup_id, action_id=str(payload.get("action_id", "")))

    def _log(self, message: str) -> None:
        self.audit_log.append(redact_text(message))

    def _record_operation(self, action_id: str, state: str, backup_id: str | None, verification: str = "") -> None:
        root = self.backups.root.parent / "operation-history"
        root.mkdir(parents=True, exist_ok=True)
        data = {"time": datetime.now(UTC).isoformat(), "action_id": action_id,
                "state": state, "backup_id": backup_id, "verification": redact_text(verification)}
        with (root / "operations.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(data, ensure_ascii=False) + "\n")


def build_default_handlers(backend: RegistryBackend, runner: CommandRunner) -> dict[str, RepairHandler]:
    from .store import STORE_REGISTER
    handlers: dict[str, RepairHandler] = {
        "disable_hkcu_startup": RegistryRepairHandler("disable_hkcu_startup", backend),
        "reset_user_proxy": RegistryRepairHandler("reset_user_proxy", backend),
        "open_vendor_support": OfficialUrlHandler(),
    }

    def add(action_id: str, validator, command, verifier=None, snapshotter=None, rollbacker=None) -> None:
        handlers[action_id] = CommandRepairHandler(action_id, runner, validator, command, verifier, snapshotter, rollbacker)

    add("flush_dns_cache", _expect_empty, lambda _t: (["ipconfig.exe", "/flushdns"], 30), _verify_dns)
    add("renew_dhcp", _validate_interface, lambda t: (["ipconfig.exe", "/renew", t["interface_alias"]], 90), _verify_dns, lambda t: _snapshot_dns(runner, t))
    add("reset_dns_to_dhcp", _validate_interface_index, lambda t: (_powershell_args(f"Set-DnsClientServerAddress -InterfaceIndex {int(t['interface_index'])} -ResetServerAddresses -ErrorAction Stop"), 45), _verify_dns, lambda t: _snapshot_dns(runner, t), lambda snap: _restore_dns(runner, snap))
    add("reset_winsock", _expect_empty, lambda _t: (["netsh.exe", "winsock", "reset"], 60))
    add("reset_tcp_ip", _validate_safe_tcpip, lambda _t: (["netsh.exe", "int", "ip", "reset"], 90))
    add("store_cache_reset", _expect_empty, lambda _t: (["wsreset.exe"], 120), lambda t: _verify_store(t, runner))
    add("store_reregister", _expect_store_family, lambda _t: (_powershell_args(STORE_REGISTER), 120), lambda t: _verify_store(t, runner))
    add("store_reset_data", _expect_store_family, lambda _t: (_powershell_args("Get-AppxPackage -Name Microsoft.WindowsStore -ErrorAction Stop | Reset-AppxPackage -ErrorAction Stop"), 180), lambda t: _verify_store(t, runner))
    add("service_start", _validate_service, lambda t: (["sc.exe", "start", t["service_name"]], 60), lambda t: _verify_service(runner, t))
    add("service_restart", _validate_service, lambda t: (_powershell_args(f"Restart-Service -Name '{t['service_name']}' -ErrorAction Stop"), 90), lambda t: _verify_service(runner, t))
    add("time_resync", _expect_empty, lambda _t: (["w32tm.exe", "/resync"], 60))
    add("dism_restore_health", _expect_empty, lambda _t: (["dism.exe", "/Online", "/Cleanup-Image", "/RestoreHealth", "/NoRestart"], 7200))
    add("sfc_scan", _expect_empty, lambda _t: (["sfc.exe", "/scannow"], 7200))
    add("scan_devices", _expect_empty, lambda _t: (["pnputil.exe", "/scan-devices"], 120))
    add("install_wua_driver", _validate_update_id, lambda t: (_powershell_args(_wua_install_script(t["update_id"])), 3600))
    add("install_inf_driver", _validate_inf, lambda t: (["pnputil.exe", "/add-driver", t["inf_path"], "/install"], 900))
    return handlers


def _expect_empty(target: dict[str, str]) -> None:
    if target:
        raise InvalidRepairTarget(msg('此操作不接受目标参数'))


def _expect_store_family(target: dict[str, str]) -> None:
    if target != {"package_family": "Microsoft.WindowsStore_8wekyb3d8bbwe"}:
        raise InvalidRepairTarget(msg('只允许修复 Microsoft Store 当前用户包'))


def _validate_service(target: dict[str, str]) -> None:
    if set(target) != {"service_name"} or target["service_name"] not in ALLOWED_SERVICES:
        raise InvalidRepairTarget(msg('服务不在允许列表'))


def _validate_interface(target: dict[str, str]) -> None:
    value = target.get("interface_alias", "")
    if set(target) != {"interface_alias"} or not value or len(value) > 128 or any(ch in value for ch in "\r\n\x00*?/"):
        raise InvalidRepairTarget(msg('网络接口名称无效'))


def _validate_interface_index(target: dict[str, str]) -> None:
    if set(target) != {"interface_index"} or not target["interface_index"].isdigit() or not 1 <= int(target["interface_index"]) <= 65535:
        raise InvalidRepairTarget(msg('网络接口编号无效'))


def _validate_safe_tcpip(target: dict[str, str]) -> None:
    if target != {"dhcp_only": "true", "complex_adapters": "false"}:
        raise InvalidRepairTarget(msg('检测到静态地址、VPN、网桥或虚拟交换机，禁止自动重置 TCP/IP'))


def _validate_update_id(target: dict[str, str]) -> None:
    if set(target) != {"update_id"} or not GUID_RE.fullmatch(target["update_id"]):
        raise InvalidRepairTarget(msg('Windows Update 驱动编号无效'))


def _validate_inf(target: dict[str, str]) -> None:
    if set(target) != {"inf_path"}:
        raise InvalidRepairTarget(msg('驱动目标无效'))
    path = Path(target["inf_path"])
    if not path.is_absolute() or path.suffix.lower() != ".inf" or not path.is_file():
        raise InvalidRepairTarget(msg('必须选择存在的本地 INF 文件'))
    raise InvalidRepairTarget(msg('INF 安装尚未通过签名、硬件匹配与恢复验证，当前不可执行'))


def _powershell_args(script: str) -> list[str]:
    script = " ".join(script.splitlines())
    script = "$ErrorActionPreference='Stop';[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);" + script
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]


def _ensure_command_success(result: CommandResult) -> None:
    if result.timed_out:
        raise RepairExecutionError(msg('操作超时；未强制结束系统修复进程，请稍后重新检查状态'))
    if result.permission_denied:
        raise PermissionError(msg('系统拒绝了操作权限'))
    if result.unsupported:
        raise RepairExecutionError(msg('当前 Windows 版本不支持此操作'))
    if result.returncode != 0:
        detail = redact_text((result.stderr or result.stdout).strip())[-1200:]
        raise RepairExecutionError(msg('系统操作失败（退出码 {0}）：{1}', result.returncode, detail or msg('没有返回详细信息')))


def _verify_dns(_target: dict[str, str]) -> tuple[bool, str]:
    import socket

    succeeded = 0
    for hostname in ("www.microsoft.com", "www.bing.com"):
        try:
            socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            succeeded += 1
        except OSError:
            pass
    return succeeded == 2, msg('DNS 复查：{0}/2 个测试域名解析成功', succeeded)


def _verify_store(_target: dict[str, str], runner: CommandRunner) -> tuple[bool | None, str]:
    result = runner.run(_powershell_args("if(Get-AppxPackage -Name Microsoft.WindowsStore){exit 0}else{exit 2}"), timeout=30)
    return (None, msg('Microsoft Store 包存在；请实际打开商店确认能否正常使用')) if result.returncode == 0 else (False, msg('无法确认 Microsoft Store 包存在'))


def _verify_service(runner: CommandRunner, target: dict[str, str]) -> tuple[bool, str]:
    result = runner.run(["sc.exe", "query", target["service_name"]], timeout=20)
    ok = result.returncode == 0 and "RUNNING" in result.stdout.upper()
    return ok, msg('服务正在运行') if ok else msg('服务仍未运行或状态无法读取')


def _snapshot_dns(runner: CommandRunner, target: dict[str, str]) -> dict[str, Any] | None:
    if "interface_index" not in target:
        alias = target["interface_alias"].replace("'", "''")
        result = runner.powershell_json(
            f"Get-NetIPConfiguration -InterfaceAlias '{alias}' | Select-Object InterfaceAlias,InterfaceIndex,IPv4Address,IPv4DefaultGateway,DNSServer | ConvertTo-Json -Depth 6 -Compress", timeout=30)
        _ensure_command_success(result)
        if not result.stdout.strip():
            raise RepairExecutionError(msg('无法备份接口状态，已取消续租'))
        return {"interface_alias": target["interface_alias"], "configuration": result.json_value()}
    index = int(target["interface_index"])
    script = (
        f"$a=Get-NetAdapter -InterfaceIndex {index} -ErrorAction Stop;$g='{{'+([guid]$a.InterfaceGuid).ToString()+'}}';"
        f"Get-DnsClientServerAddress -InterfaceIndex {index} -ErrorAction Stop | ForEach-Object {{"
        "$p=if($_.AddressFamily -eq 2){'Tcpip'}else{'Tcpip6'};"
        "$k='HKLM:\\SYSTEM\\CurrentControlSet\\Services\\'+$p+'\\Parameters\\Interfaces\\'+$g;"
        "$v=(Get-ItemProperty -LiteralPath $k -ErrorAction Stop).NameServer;"
        "[pscustomobject]@{InterfaceGuid=$g;AddressFamily=$_.AddressFamily;ServerAddresses=@($_.ServerAddresses);Automatic=[string]::IsNullOrWhiteSpace($v)}}|ConvertTo-Json -Depth 3 -Compress"
    )
    result = runner.run(_powershell_args(script), timeout=30)
    _ensure_command_success(result)
    try:
        rows = json.loads(result.stdout.lstrip("\ufeff"))
        if not isinstance(rows, list) or len(rows) != 2 or {r.get("AddressFamily") for r in rows} != {2, 23}:
            raise ValueError("Incomplete DNS family snapshot")
        for row in rows:
            if not isinstance(row.get("Automatic"), bool) or not GUID_RE.fullmatch(str(row.get("InterfaceGuid", "")).strip("{}")):
                raise ValueError("Incomplete DNS configuration snapshot")
            for address in row.get("ServerAddresses", []):
                if ipaddress.ip_address(address).version != (4 if row["AddressFamily"] == 2 else 6):
                    raise ValueError("Mismatched DNS address family")
        return {"interface_index": index, "dns": rows}
    except (ValueError, TypeError) as exc:
        raise RepairExecutionError(msg('无法保存原 DNS 配置，已取消修改')) from exc


def _restore_dns(runner: CommandRunner, snapshot: dict[str, Any]) -> str:
    index = int(snapshot["interface_index"])
    rows = snapshot.get("dns", [])
    if isinstance(rows, dict):
        rows = [rows]
    if {row.get("AddressFamily") for row in rows} != {2, 23} or len(rows) != 2:
        raise InvalidRepairTarget(tr("unavailable"))
    for row in rows:
        guid = str(row.get("InterfaceGuid", "")).strip("{}")
        if not GUID_RE.fullmatch(guid) or not isinstance(row.get("Automatic"), bool):
            raise InvalidRepairTarget(tr("unavailable"))
        for address in row.get("ServerAddresses", []):
            parsed = ipaddress.ip_address(address)
            if parsed.version != (4 if row["AddressFamily"] == 2 else 6):
                raise InvalidRepairTarget(tr("unavailable"))
    for row in rows:
        family = int(row.get("AddressFamily", 0))
        servers = [str(ipaddress.ip_address(item)) for item in row.get("ServerAddresses", [])]
        if family not in {2, 23}:
            continue
        guid = str(row.get("InterfaceGuid", "")).strip("{}")
        if not GUID_RE.fullmatch(guid):
            raise InvalidRepairTarget(msg('备份缺少有效网卡标识'))
        family_name = "IPv4" if family == 2 else "IPv6"
        prefix = f"$a=Get-NetAdapter -InterfaceIndex {index} -ErrorAction Stop;if(([guid]$a.InterfaceGuid).ToString() -ne '{guid}'){{throw 'Network adapter changed'}};"
        prefix += f"Get-DnsClientServerAddress -InterfaceIndex {index} -AddressFamily {family_name} -ErrorAction Stop | "
        if servers and not row.get("Automatic", False):
            quoted = ",".join("'" + item.replace("'", "''") + "'" for item in servers)
            script = prefix + f"Set-DnsClientServerAddress -ServerAddresses @({quoted}) -ErrorAction Stop"
        else:
            script = prefix + "Set-DnsClientServerAddress -ResetServerAddresses -ErrorAction Stop"
        _ensure_command_success(runner.run_repair(_powershell_args(script), timeout=45))
    return msg('已按加密备份恢复原 DNS 服务器配置。')


def _wua_install_script(update_id: str) -> str:
    return (
        "$session=New-Object -ComObject Microsoft.Update.Session;"
        "$searcher=$session.CreateUpdateSearcher();"
        "$r=$searcher.Search(\"UpdateID='" + update_id + "' and IsInstalled=0\");"
        "if($r.Updates.Count -ne 1){throw 'Driver update is missing or not unique'};"
        "$u=$r.Updates.Item(0);if($u.Type -ne 2){throw 'Target is not a driver update'};"
        "$hardware=[string]$u.DriverHardwareID;if([string]::IsNullOrWhiteSpace($hardware)){throw 'Hardware matching information is missing'};"
        "$devices=@(Get-CimInstance Win32_PnPEntity -ErrorAction Stop | Where-Object {"
        "@($_.HardwareID)+@($_.CompatibleID) -contains $hardware});"
        "if($devices.Count -ne 1){throw 'Cannot uniquely match a device; installation cancelled'};"
        "$old=@(Get-CimInstance Win32_PnPSignedDriver -ErrorAction Stop | Where-Object {$_.DeviceID -eq $devices[0].DeviceID});"
        "$versions=[regex]::Matches($u.Title,'(?<![0-9.])[0-9]+(?:[.][0-9]+){1,3}(?![0-9.])');"
        "if($versions.Count -ne 1 -or $old.Count -ne 1){throw 'Cannot reliably compare versions; use Windows Update Settings'};"
        "if([version]$versions[0].Value -le [version]$old[0].DriverVersion){throw 'Downgrades and duplicate installations are prohibited'};"
        "if(-not $u.EulaAccepted){throw 'Review and accept the license terms in Windows Update first'};"
        "if(-not $old[0].IsSigned -or $old[0].InfName -notmatch '^oem[0-9]+[.]inf$'){throw 'Cannot safely export the current driver; use Device Manager'};"
        "$backup=Join-Path $env:LOCALAPPDATA ('HelpPack\\driver-backups\\'+[guid]::NewGuid().ToString('N'));"
        "$null=New-Item -ItemType Directory -Path $backup -ErrorAction Stop;"
        "$tool=Join-Path $env:SystemRoot 'System32\\pnputil.exe';"
        "$null=& $tool /export-driver $old[0].InfName $backup;"
        "if($LASTEXITCODE -ne 0){throw 'Current driver export failed; installation cancelled'};"
        "$c=New-Object -ComObject Microsoft.Update.UpdateColl;$null=$c.Add($u);"
        "$d=$session.CreateUpdateDownloader();$d.Updates=$c;$dr=$d.Download();"
        "if($dr.ResultCode -ne 2){throw 'Driver download did not fully succeed'};"
        "$i=$session.CreateUpdateInstaller();$i.Updates=$c;$ir=$i.Install();"
        "if($ir.ResultCode -ne 2 -or $ir.GetUpdateResult(0).ResultCode -ne 2){throw 'Driver installation did not fully succeed'};"
        "[pscustomobject]@{Result=$ir.ResultCode;RebootRequired=$ir.RebootRequired}|ConvertTo-Json -Compress"
    )


def _target_digest(action_id: str, target: dict[str, str]) -> str:
    serialized = json.dumps({"action_id": action_id, "target": target}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def is_admin() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    if platform.system() != "Windows":
        return data
    buffer = ctypes.create_string_buffer(data)
    in_blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DataBlob()
    if protect:
        ok = ctypes.windll.crypt32.CryptProtectData(ctypes.byref(in_blob), "HelpPack backup", None, None, None, 0, ctypes.byref(out_blob))
    else:
        ok = ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob))
    if not ok:
        raise OSError(msg('Windows DPAPI 操作失败'))
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)
