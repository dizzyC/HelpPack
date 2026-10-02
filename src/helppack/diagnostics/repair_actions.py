"""Narrow repair extensions and structured state reads. No arbitrary command input."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

import psutil

from ..plan_resources import tr


def state_signature(state):
    value = json.loads(json.dumps(state, sort_keys=True))
    if isinstance(value, dict):
        value.pop("destination", None)
        for row in value.get("dns", []) if isinstance(value.get("dns", []), list) else [value.get("dns")]:
            if isinstance(row, dict) and row.get("Automatic"):
                row["ServerAddresses"] = []  # DHCP lease changes are not manual-config conflicts.
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def service_state(runner, name):
    from .repairs import ALLOWED_SERVICES, RepairExecutionError
    if name not in ALLOWED_SERVICES:
        raise ValueError(tr("unsupported"))
    command = runner.powershell_json(
        "$ErrorActionPreference='Stop';"
        f"$s=Get-CimInstance Win32_Service -Filter \"Name='{name}'\";"
        f"$g=Get-Service -Name '{name}' -ErrorAction Stop;"
        "[pscustomobject]@{Name=$s.Name;State=$s.State;StartMode=$s.StartMode;"
        "Dependencies=@($g.ServicesDependedOn|ForEach-Object {[pscustomobject]@{Name=$_.Name;State=[string]$_.Status}});"
        "Dependents=@($g.DependentServices|ForEach-Object {[pscustomobject]@{Name=$_.Name;State=[string]$_.Status}})}|ConvertTo-Json -Depth 5 -Compress", timeout=20)
    if command.returncode or command.timed_out or command.permission_denied:
        raise RepairExecutionError(tr("unavailable"))
    state = command.json_value()
    if not isinstance(state, dict) or state.get("Name") != name or not state.get("State") or not state.get("StartMode"):
        raise RepairExecutionError(tr("unavailable"))
    if not isinstance(state.get("Dependencies"), list) or not isinstance(state.get("Dependents"), list):
        raise RepairExecutionError(tr("unavailable"))
    return state


def service_applicable(state, action):
    if state.get("StartMode") == "Disabled" or any(d.get("State") != "Running" for d in state.get("Dependencies", [])):
        return False
    if action == "service_start":
        return state.get("State") == "Stopped" and state.get("StartMode") == "Auto"
    return state.get("State") == "Running"  # Restart still requires specific evidence and extra confirmation.


class ServiceHandler:
    def __init__(self, action_id, runner):
        self.action_id, self.runner = action_id, runner

    def validate(self, target):
        from .repairs import _validate_service
        _validate_service(target)

    def snapshot(self, target):
        return service_state(self.runner, target["service_name"])

    def execute(self, target):
        from .repairs import (
            RepairExecutionError,
            _ensure_command_success,
            _powershell_args,
        )
        state = self.snapshot(target)
        if not service_applicable(state, self.action_id):
            raise RepairExecutionError(tr("stale"))
        verb = "Start-Service" if self.action_id == "service_start" else "Restart-Service"
        # Check applicability in the helper immediately before the exact mutation too.
        result = self.runner.run_repair(_powershell_args(
            f"{verb} -Name '{target['service_name']}' -ErrorAction Stop"), timeout=90)
        _ensure_command_success(result)
        self.last_exit_code = result.returncode
        return tr("automatic", target["service_name"])

    def verify(self, target):
        state = self.snapshot(target)
        return state["State"] == "Running", json.dumps(state, sort_keys=True)

    def rollback(self, snapshot):
        from .repairs import (
            RepairExecutionError,
            _ensure_command_success,
            _powershell_args,
        )
        if self.action_id != "service_start" or snapshot.get("State") != "Stopped":
            raise RepairExecutionError(tr("unsupported"))
        self.validate({"service_name": snapshot["Name"]})
        current = service_state(self.runner, snapshot["Name"])
        if any(d.get("State") == "Running" for d in current["Dependents"]):
            raise RepairExecutionError(tr("conflict"))
        _ensure_command_success(self.runner.run_repair(_powershell_args(
            f"Stop-Service -Name '{snapshot['Name']}' -ErrorAction Stop"), timeout=60))
        if self.snapshot({"service_name": snapshot["Name"]})["State"] != "Stopped":
            raise RepairExecutionError(tr("unavailable"))
        return tr("best")


def cache_roots():
    local = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    roaming = Path(os.environ.get("APPDATA", Path.home()))
    return {"helppack": (local / "HelpPack" / "cache", ()), "vscode": (roaming / "Code" / "Cache", ("code.exe",))}


class CacheHandler:
    action_id = "quarantine_allowed_cache"

    def __init__(self, roots=None, processes=None):
        self.roots = roots if roots is not None else cache_roots()
        self.processes = processes or (lambda: [p.info.get("name", "") for p in psutil.process_iter(["name"])])
        self.destinations = {}

    def validate(self, target):
        if set(target) != {"cache_id"} or target["cache_id"] not in self.roots:
            raise ValueError(tr("unsupported"))

    def _root(self, target):
        from .storage_analysis import linked
        self.validate(target)
        root, names = self.roots[target["cache_id"]]
        if any(str(name).lower() in {n.lower() for n in names} for name in self.processes()):
            raise PermissionError(tr("cache_closed"))
        for part in [root, *root.parents]:
            if part.exists() and linked(part):
                raise ValueError(tr("cache_closed"))
        return root

    def snapshot(self, target):
        from .storage_analysis import linked
        root = self._root(target)
        destination = self.destinations.setdefault(str(root), root.parent / ".helppack-cache-recovery" / uuid.uuid4().hex)
        files = {}
        total = 0
        if root.exists():
            if not root.is_dir():
                raise ValueError(tr("cache_closed"))
            stack = [root]
            entries, total = 0, 0
            while stack:
                for path in stack.pop().iterdir():
                    entries += 1
                    if entries > 5000 or linked(path):
                        raise ValueError(tr("cache_closed"))
                    if path.is_dir():
                        stack.append(path)
                    elif path.is_file():
                        total += path.stat().st_size
                        if total > 512 * 1024**2:
                            raise ValueError(tr("unsupported"))
                        digest = hashlib.sha256()
                        with path.open("rb") as stream:
                            for block in iter(lambda: stream.read(1024 * 1024), b""):
                                digest.update(block)
                        files[str(path.relative_to(root))] = digest.hexdigest()
        return {"cache_id": target["cache_id"], "root": str(root), "exists": root.exists(), "files": files, "total_bytes": total, "destination": str(destination)}

    def execute(self, target):
        before = self.snapshot(target)
        if not before["files"]:
            raise ValueError(tr("stale"))
        root, destination = Path(before["root"]), Path(before["destination"])
        from .storage_analysis import linked
        if destination.parent.exists() and linked(destination.parent):
            raise ValueError(tr("cache_closed"))
        destination.parent.mkdir(exist_ok=True)
        self._root(target)  # Refresh process/path checks after scanning.
        root.rename(destination)  # Recovery copy on the same volume; no permanent deletion.
        return tr("cache_done")

    def verify(self, target):
        state = self.snapshot(target)
        return not state["exists"], tr("cache_done")

    def rollback(self, snapshot):
        from .storage_analysis import linked
        target = {"cache_id": snapshot["cache_id"]}
        root = self._root(target)
        destination = Path(snapshot["destination"])
        expected = root.parent / ".helppack-cache-recovery"
        if root.exists() or destination.parent != expected or linked(expected) or linked(destination) or not destination.is_dir():
            raise ValueError(tr("conflict"))
        # Verify all recovery bytes before restoring; reject foreign or edited backups.
        probe = CacheHandler({target["cache_id"]: (destination, ())}, processes=list)
        if probe.snapshot(target)["files"] != snapshot["files"]:
            raise ValueError(tr("conflict"))
        destination.rename(root)
        return tr("cache_restored")


class RestoreHandler:
    def __init__(self, coordinator, kind="user"):
        self.coordinator, self.kind = coordinator, kind
        self.action_id = {"dns": "restore_dns_settings", "service": "restore_service_state", "user": "restore_user_settings"}[kind]

    def validate(self, target):
        if set(target) != {"backup_id"}:
            raise ValueError(tr("unsupported"))
        payload = self.coordinator.backups.load(target["backup_id"])
        allowed = {"reset_dns_to_dhcp"} if self.kind == "dns" else {"service_start"} if self.kind == "service" else {"disable_hkcu_startup", "reset_user_proxy", "quarantine_allowed_cache"}
        if payload.get("action_id") not in allowed or "post_snapshot" not in payload:
            raise ValueError(tr("unsupported"))

    def snapshot(self, target):
        self.validate(target)

    def execute(self, target):
        self.validate(target)
        return self.coordinator.rollback(target["backup_id"], user_confirmed=True).message

    def verify(self, target):
        payload = self.coordinator.backups.load(target["backup_id"])
        current = self.coordinator.handlers[payload["action_id"]].snapshot(payload["target"])
        return state_signature(current) == state_signature(payload["snapshot"]), tr("full")

    def rollback(self, snapshot):
        raise ValueError(tr("unsupported"))


def install_safe_handlers(coordinator):
    handlers = coordinator.handlers
    handlers["service_start"] = ServiceHandler("service_start", coordinator.runner)
    handlers["service_restart"] = ServiceHandler("service_restart", coordinator.runner)
    handlers["quarantine_allowed_cache"] = CacheHandler()
    handlers["restore_user_settings"] = RestoreHandler(coordinator)
    handlers["restore_dns_settings"] = RestoreHandler(coordinator, kind="dns")
    handlers["restore_service_state"] = RestoreHandler(coordinator, kind="service")
