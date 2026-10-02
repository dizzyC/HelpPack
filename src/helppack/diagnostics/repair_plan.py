"""Evidence-scoped, expiring, single-use repair plans with serial scheduling."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from ..plan_resources import tr
from ..redaction import redact_text
from .models import DiagnosticStatus, RepairSuggestion, RollbackCapability, SafetyLevel
from .repair_actions import service_applicable, service_state, state_signature
from .repairs import ConfirmationRequired, RepairCoordinator, is_admin

ALLOWED = frozenset({"flush_dns_cache", "service_start", "service_restart", "disable_hkcu_startup",
                     "reset_user_proxy", "renew_dhcp", "reset_dns_to_dhcp", "quarantine_allowed_cache",
                     "restore_user_settings", "restore_dns_settings", "restore_service_state", "sfc_scan", "dism_restore_health"})
EXTRA = frozenset({"service_restart", "disable_hkcu_startup", "reset_user_proxy", "renew_dhcp",
                   "reset_dns_to_dhcp", "restore_dns_settings", "restore_service_state", "sfc_scan", "dism_restore_health"})


@dataclass
class PlanItem:
    item_id: str
    suggestion: RepairSuggestion
    check_id: str
    evidence: str
    dependencies: list[str] = field(default_factory=list)

    @property
    def extra(self):
        return self.suggestion.action_id in EXTRA or self.suggestion.requires_second_confirmation or self.suggestion.safety_level == SafetyLevel.L3


@dataclass
class RepairPlan:
    plan_id: str
    created_at: str
    expires_at: str
    items: list[PlanItem]
    manual_reasons: list[str] = field(default_factory=list)


def digest(plan):
    return hashlib.sha256(json.dumps(asdict(plan), sort_keys=True).encode()).hexdigest()


def make_plan(summary) -> RepairPlan:
    items, reasons, seen, conflicts = [], [], set(), {}
    if summary.cancelled:
        return new_plan([], [tr("unavailable")])
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(summary.finished_at)).total_seconds()
    except (ValueError, TypeError):
        return new_plan([], [tr("expired")])
    if not -60 <= age <= 300:
        return new_plan([], [tr("expired")])
    fault_evidence = any(r.status == DiagnosticStatus.ABNORMAL or
                         (r.check_id == "performance.resources" and r.status == DiagnosticStatus.NOTICE)
                         for r in summary.results)
    for result in summary.results:
        if result.status not in {DiagnosticStatus.NOTICE, DiagnosticStatus.ABNORMAL}:
            continue
        evidence = redact_text("\n".join(f"{e.label}: {e.value}" for e in result.evidence))
        for candidate in result.repair_suggestions:
            action = candidate.action_id
            if action == "quarantine_allowed_cache" and not fault_evidence:
                continue  # Ordinary cached data is not itself a diagnosed fault.
            # Configuration presence is not a failure; legacy broad suggestions are excluded.
            if action not in ALLOWED or (action in {"renew_dhcp", "reset_dns_to_dhcp"} and result.check_id == "network.repair_eligibility") or (action == "reset_user_proxy" and result.check_id == "network.proxy_hosts"):
                reasons.append(tr("unsupported"))
                continue
            if action in {"sfc_scan", "dism_restore_health"} and result.check_id != "system.proven_corruption":
                reasons.append(tr("unsupported"))
                continue
            if action == "service_restart" and result.check_id != "services.proven_unresponsive":
                reasons.append(tr("unsupported"))
                continue
            if not evidence:
                continue
            suggestion = copy.deepcopy(candidate)
            suggestion.evidence_ids = [result.check_id]
            key = (action, json.dumps(suggestion.target, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            resource = suggestion.target.get("service_name") or ("user_proxy" if action == "reset_user_proxy" else None)
            if resource in conflicts:
                raise ValueError(tr("conflict"))
            if resource:
                conflicts[resource] = action
            items.append(PlanItem(uuid.uuid4().hex, suggestion, result.check_id, evidence))
    # Audio endpoint service must run before the audio service. No invented service starts.
    endpoint = next((i for i in items if i.suggestion.target.get("service_name") == "AudioEndpointBuilder"), None)
    audio = next((i for i in items if i.suggestion.target.get("service_name") == "Audiosrv"), None)
    if audio and endpoint:
        audio.dependencies.append(endpoint.item_id)
    return new_plan(topological(items), list(dict.fromkeys(reasons)))


def new_plan(items, reasons=None):
    now = datetime.now(UTC)
    return RepairPlan(uuid.uuid4().hex, now.isoformat(), (now + timedelta(minutes=5)).isoformat(), items, reasons or [])


def topological(items):
    pending = {i.item_id: i for i in items}
    if len(pending) != len(items):
        raise ValueError(tr("conflict"))
    ordered = []
    while pending:
        ready = [i for i in pending.values() if all(dep in {o.item_id for o in ordered} for dep in i.dependencies)]
        if not ready:
            raise ValueError(tr("conflict"))
        for item in ready:
            ordered.append(item)
            del pending[item.item_id]
    return ordered


class PlanLock:
    mutex = threading.Lock()

    def __init__(self, root):
        self.root, self.stream = root, None

    def __enter__(self):
        if not self.mutex.acquire(blocking=False):
            raise RuntimeError(tr("busy"))
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / "plan.lock"
            if path.is_symlink() or path.is_junction() or self.root.is_symlink() or self.root.is_junction():
                raise RuntimeError(tr("conflict"))
            self.stream = path.open("a+b")
            self.stream.seek(0, 2)
            if self.stream.tell() == 0:
                self.stream.write(b"0")
            self.stream.flush()
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self
        except Exception:  # noqa: BLE001 - release both locks on every acquisition failure
            if self.stream:
                self.stream.close()
            self.mutex.release()
            raise RuntimeError(tr("busy")) from None

    def __exit__(self, *args):
        self.stream.close()  # OS releases the lock even after a process crash.
        self.mutex.release()


def read_action_state(coordinator, suggestion):
    action, target = suggestion.action_id, suggestion.target
    handler = coordinator.handlers[action]
    handler.validate(target)
    if action == "flush_dns_cache":
        from .repairs import _verify_dns
        ok, detail = _verify_dns(target)
        return {"applicable": not ok, "metrics": {"dns_ok": ok, "detail": detail}}
    if action.startswith("service_"):
        state = service_state(coordinator.runner, target["service_name"])
        return {"applicable": service_applicable(state, action), "metrics": state}
    if action == "quarantine_allowed_cache":
        state = handler.snapshot(target)
        return {"applicable": bool(state["files"]), "metrics": {"files": len(state["files"]), "exists": state["exists"]}}
    if action.startswith("restore_"):
        handler.validate(target)
        payload = coordinator.backups.load(target["backup_id"])
        current = coordinator.handlers[payload["action_id"]].snapshot(payload["target"])
        restored = state_signature(current) == state_signature(payload["snapshot"])
        return {"applicable": not restored, "metrics": {"restored": restored, "state": current}}
    from .preflight import check_preconditions
    check_preconditions(action, target, coordinator.runner)
    state = handler.snapshot(target)
    if action == "disable_hkcu_startup" and not any(v.get("exists") for v in state["values"]):
        return {"applicable": False, "metrics": {"entry_present": False}}
    if action == "reset_user_proxy" and handler.verify(target)[0]:
        return {"applicable": False, "metrics": {"proxy_reset": True}}
    return {"applicable": True, "metrics": state or {"state": "unknown"}}


class PlanExecutor:
    def __init__(self, coordinator=None, probe=None, broker=None, recheck=None):
        self.coordinator = coordinator or RepairCoordinator()
        self.probe = probe or (lambda action: read_action_state(self.coordinator, action))
        self.broker, self.recheck = broker, recheck
        self.authorizations, self.used = {}, set()
        self.cancel = threading.Event()

    def authorize(self, plan):
        topological(plan.items)
        for item in plan.items:
            if item.suggestion.action_id not in ALLOWED:
                raise ValueError(tr("unsupported"))
            prepared = self.coordinator.prepare(item.suggestion)
            item.suggestion.requires_admin = prepared.requires_admin
            item.suggestion.safety_level = prepared.safety_level
            item.suggestion.requires_second_confirmation = prepared.requires_second_confirmation
        self.authorizations[plan.plan_id] = digest(plan)

    def run(self, plan, selected, *, confirmed=False, extra_confirmed=(), progress=None):
        if not confirmed:
            raise ConfirmationRequired(tr("intro"))
        if plan.plan_id in self.used or self.authorizations.get(plan.plan_id) != digest(plan) or datetime.now(UTC) > datetime.fromisoformat(plan.expires_at):
            raise ConfirmationRequired(tr("expired"))
        selected = set(selected)
        known = {i.item_id for i in plan.items}
        if not selected <= known or any(i.extra and i.item_id in selected and i.item_id not in extra_confirmed for i in plan.items):
            raise ConfirmationRequired(tr("extra", "", ""))
        results = []
        with PlanLock(self.coordinator.backups.root.parent / "operations"):
            self.used.add(plan.plan_id)
            success = set()
            for index, item in enumerate(topological(plan.items), 1):
                if item.item_id not in selected:
                    continue
                row = {"item_id": item.item_id, "action_id": item.suggestion.action_id, "name": item.suggestion.display_name,
                       "status": "skipped", "before": {}, "after": {}, "message": "", "backup_id": None, "exit_code": None}
                if self.cancel.is_set() or not set(item.dependencies) <= success or datetime.now(UTC) > datetime.fromisoformat(plan.expires_at):
                    row["message"] = tr("skipped")
                    results.append(row)
                    continue
                if progress:
                    progress(index, len(plan.items), item.suggestion.display_name)
                try:
                    before = self.probe(item.suggestion)
                    row["before"] = before["metrics"]
                    if not before["applicable"]:
                        row["message"] = tr("stale")
                        results.append(row)
                        continue
                    prepared = self.coordinator.prepare(item.suggestion)
                    if prepared.requires_admin and not is_admin():
                        from .elevation import ElevationBroker
                        outcome = (self.broker or ElevationBroker()).execute(item.suggestion)
                    else:
                        outcome = self.coordinator.execute(prepared, user_confirmed=True,
                            second_confirmation=prepared.confirmation_phrase or bool(item.extra))
                    row["backup_id"] = outcome.backup_id if item.suggestion.rollback_capability != RollbackCapability.NONE else None
                    row["message"] = outcome.message
                    # Successful command is distinct from improved evidence.
                    try:
                        after = self.probe(item.suggestion)
                        row["after"] = after["metrics"]
                    except Exception:  # noqa: BLE001 - completed mutation must retain unknown recheck state
                        after = None
                    if outcome.restart_required:
                        row["status"] = "restart"
                    elif not outcome.executed:
                        row["status"] = "failed"
                    elif after is None or outcome.verified is None:
                        row["status"] = "unknown"
                    elif outcome.verified is True and state_signature(row["before"]) != state_signature(row["after"]):
                        row["status"] = "improved"
                    else:
                        row["status"] = "unchanged"
                    if self.recheck:
                        try:
                            row["recheck"] = self.recheck(item)
                            if not outcome.restart_required and outcome.executed:
                                if row["recheck"].get("healthy") is False:
                                    row["status"] = "unchanged"
                                elif row["recheck"].get("healthy") is None:
                                    row["status"] = "unknown"
                        except Exception as exc:  # noqa: BLE001 - preserve completed mutation and unknown scene outcome
                            row.update(status="unknown", recheck={"error": type(exc).__name__})
                    handler = self.coordinator.handlers.get(item.suggestion.action_id)
                    row["exit_code"] = getattr(handler, "last_exit_code", None)
                    if outcome.executed and outcome.verified is True:
                        success.add(item.item_id)
                except Exception as exc:  # noqa: BLE001 - retain independent actions and record uncertainty
                    row.update(status="failed", message=f"{type(exc).__name__}: {exc}\n" + tr("partial_failure"))
                    handler = self.coordinator.handlers.get(item.suggestion.action_id)
                    row["exit_code"] = getattr(handler, "last_exit_code", None)
                results.append(row)
            # No paths or unredacted snapshots enter the operation record/report.
            def redact_value(value):
                if isinstance(value, str):
                    return redact_text(value)
                if isinstance(value, dict):
                    return {k: redact_value(v) for k, v in value.items() if k not in {"destination", "backup_path", "request_path"}}
                if isinstance(value, list):
                    return [redact_value(v) for v in value]
                return value
            public = redact_value({"plan_id": plan.plan_id, "time": datetime.now(UTC).isoformat(), "results": results})
            self.coordinator.backups.root.parent.mkdir(parents=True, exist_ok=True)
            with (self.coordinator.backups.root.parent / "plans.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(public, ensure_ascii=False) + "\n")
            return public


def plan_markdown(record):
    rows = [tr("plan_report")]
    for item in record["results"]:
        rows += [f"### {item['name']}", tr(item["status"]), item["message"],
                 tr("before_after", json.dumps(item.get("before", {}), ensure_ascii=False), json.dumps(item.get("after", {}), ensure_ascii=False))]
        if item.get("recheck"):
            rows.append(tr("rechecked", json.dumps(item["recheck"], ensure_ascii=False)))
    return redact_text("\n\n".join(rows))


def related_recheck(item, category, url, scope):
    from .checks import default_checks
    from .engine import DiagnosticEngine
    from .scenario_checks import NetworkSceneCheck, SafeServiceCheck
    checks = [c for c in default_checks() if c.check_id == item.check_id]
    if item.check_id == "network.scene":
        checks = [NetworkSceneCheck(url, scope)]
    elif item.check_id == "services.safe_eligibility":
        checks = [SafeServiceCheck()]
    elif item.check_id == "recovery":
        return {"healthy": True, "limitation": tr("restore_confirm")}
    if not checks:
        return {"healthy": None, "limitation": tr("unavailable")}
    summary = DiagnosticEngine(checks).scan(category)
    healthy = True if summary.results and all(r.status == DiagnosticStatus.NORMAL for r in summary.results) else False if any(r.status in {DiagnosticStatus.ABNORMAL, DiagnosticStatus.NOTICE} for r in summary.results) else None
    return {"healthy": healthy, "evidence": [{"check": r.display_name, "evidence": [{"label": e.label, "value": e.value} for e in r.evidence]} for r in summary.results]}
