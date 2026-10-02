from __future__ import annotations

import copy
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from helppack.diagnostics.engine import ScanContext
from helppack.diagnostics.models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
    RepairSuggestion,
    RollbackCapability,
    SafetyLevel,
    ScanSummary,
    Severity,
)
from helppack.diagnostics.repair_actions import (
    CacheHandler,
    service_applicable,
    service_state,
    state_signature,
)
from helppack.diagnostics.repair_plan import (
    PlanExecutor,
    PlanLock,
    make_plan,
    plan_markdown,
)
from helppack.diagnostics.repairs import (
    ConfirmationRequired,
    RepairCoordinator,
    RepairExecutionError,
)
from helppack.diagnostics.runner import CommandResult
from helppack.diagnostics.scenario_checks import (
    NetworkSceneCheck,
    crash_event_script,
    sustained_pressure,
)
from helppack.plan_resources import COPY, tr


@pytest.fixture(autouse=True)
def isolated_permissions(monkeypatch):
    # Fake handlers must never request real UAC, even when IDs require admin.
    monkeypatch.setattr("helppack.diagnostics.repair_plan.is_admin", lambda: True)
    monkeypatch.setattr("helppack.diagnostics.repairs.is_admin", lambda: True)


class MemoryBackups:
    def __init__(self, root):
        self.root, self.values = root, {}

    def save(self, payload, **_kwargs):
        key = uuid.uuid4().hex
        self.values[key] = copy.deepcopy(payload)
        return key

    def load(self, key):
        return copy.deepcopy(self.values[key])


class Handler:
    def __init__(self, action="flush_dns_cache", failure=None, verified=True):
        self.action_id, self.failure, self.verified = action, failure, verified
        self.value, self.calls, self.on_run = 0, 0, None
        self.last_exit_code = None

    def validate(self, target):
        if target:
            raise ValueError("unsupported parameters")

    def snapshot(self, target):
        return {"value": self.value}

    def execute(self, target):
        self.calls += 1
        if self.on_run:
            self.on_run()
        if self.failure:
            raise self.failure
        self.value = 1
        self.last_exit_code = 0
        return "synthetic action"

    def verify(self, target):
        return self.verified, "synthetic recheck"

    def rollback(self, snapshot):
        self.value = snapshot["value"]
        return "restored"


def suggestion(action="flush_dns_cache"):
    return RepairSuggestion(action, "Synthetic action", {}, SafetyLevel.L1, False, "Synthetic impact", "Fixed operation", "Restore snapshot", RollbackCapability.FULL)


def summary(actions, status=DiagnosticStatus.ABNORMAL, check_id="network.scene", evidence="synthetic DNS failure"):
    finding = DiagnosticResult(check_id, "网络或Wi-Fi异常", "Synthetic check", status, Severity.LOW,
        [Evidence("Synthetic", evidence)], "Not a cause", "中", [], repair_suggestions=actions)
    return ScanSummary("网络或Wi-Fi异常", "start", datetime.now(UTC).isoformat(), False, [finding])


def setup(tmp_path, handler=None, probe=None):
    handler = handler or Handler()
    coordinator = RepairCoordinator(backups=MemoryBackups(tmp_path / "backups"), handlers={handler.action_id: handler})
    executor = PlanExecutor(coordinator, probe=probe or (lambda _s: {"applicable": handler.value == 0, "metrics": {"value": handler.value}}))
    plan = make_plan(summary([suggestion(handler.action_id)]))
    executor.authorize(plan)
    return coordinator, executor, plan, handler


def execute(executor, plan, **kwargs):
    return executor.run(plan, {i.item_id for i in plan.items}, confirmed=True, **kwargs)


def test_normal_and_configuration_presence_never_generate_actions():
    assert not make_plan(summary([suggestion()], DiagnosticStatus.NORMAL)).items
    assert not make_plan(summary([suggestion("reset_user_proxy")], DiagnosticStatus.NOTICE, "network.proxy_hosts")).items
    assert not make_plan(summary([suggestion("reset_dns_to_dhcp")], DiagnosticStatus.NOTICE, "network.repair_eligibility")).items
    assert not make_plan(summary([suggestion("service_restart")], DiagnosticStatus.NOTICE, "services.safe_eligibility")).items
    assert not make_plan(summary([suggestion("install_wua_driver")])).items


def test_nonempty_cache_alone_is_not_a_fault_or_automatic_repair():
    assert not make_plan(summary([suggestion("quarantine_allowed_cache")], DiagnosticStatus.NOTICE, "cache.allowlisted")).items


def test_plan_dialog_high_impact_unchecked_and_cancel_default():
    from PySide6.QtWidgets import QApplication, QPushButton

    from helppack.ui.repair_plan_panel import PlanReview
    application = QApplication.instance() or QApplication([])
    review = PlanReview(make_plan(summary([suggestion(), suggestion("renew_dhcp")])))
    review.show()
    application.processEvents()
    assert len(review.selected()) == 1
    assert next(b for b in review.findChildren(QPushButton) if b.text() == tr("cancel")).isDefault()
    review.reject()


def test_mock_plan_gui_worker_history_and_report_flow(tmp_path):
    import time

    from PySide6.QtWidgets import QApplication

    from helppack.diagnostics.history import DiagnosticHistoryStore
    from helppack.ui.main_window import MainWindow
    application = QApplication.instance() or QApplication([])
    window = MainWindow()
    coordinator, executor, plan, handler = setup(tmp_path)
    page = window.diagnostic_page
    page.coordinator = coordinator
    page.history = DiagnosticHistoryStore(tmp_path / "history")
    page.summary = summary([suggestion()])
    panel = page.plan_panel
    panel.set_summary(page.summary)
    panel.executor = executor
    panel.launch(plan, {plan.items[0].item_id}, set())
    deadline = time.monotonic() + 5
    while panel.thread is not None and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.01)
    assert panel.thread is None and handler.calls == 1
    assert panel.record["results"][0]["status"] == "improved"
    assert page.operation_summaries and panel.output.toPlainText()
    assert list((tmp_path / "history").glob("*.json"))
    reports = []
    page.add_to_help_pack.disconnect(window._attach_diagnostics)
    page.add_to_help_pack.connect(reports.append)
    page._attach_report()
    assert page.operation_summaries[0] in reports[0]
    window.close()


def test_unconfirmed_plan_has_no_side_effects(tmp_path):
    _c, executor, plan, handler = setup(tmp_path)
    with pytest.raises(ConfirmationRequired):
        executor.run(plan, {plan.items[0].item_id})
    assert handler.calls == 0


def test_high_impact_action_requires_individual_extra_confirmation(tmp_path):
    _c, executor, plan, handler = setup(tmp_path, Handler("renew_dhcp"))
    with pytest.raises(ConfirmationRequired):
        execute(executor, plan)
    assert handler.calls == 0
    execute(executor, plan, extra_confirmed={plan.items[0].item_id})
    assert handler.calls == 1


@pytest.mark.parametrize("change", ["tamper", "expire", "unknown_selection"])
def test_stale_tampered_or_foreign_confirmation_is_rejected(tmp_path, change):
    _c, executor, plan, handler = setup(tmp_path)
    if change == "tamper":
        plan.items[0].suggestion.target["command"] = "malicious"
    elif change == "expire":
        plan.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with pytest.raises(ConfirmationRequired):
        executor.run(plan, {"foreign"} if change == "unknown_selection" else {plan.items[0].item_id}, confirmed=True)
    assert handler.calls == 0


def test_changed_applicability_skips_without_mutation(tmp_path):
    _c, executor, plan, handler = setup(tmp_path, probe=lambda _s: {"applicable": False, "metrics": {"state": "now normal"}})
    record = execute(executor, plan)
    assert record["results"][0]["status"] == "skipped" and handler.calls == 0


@pytest.mark.parametrize("error", [PermissionError("permission denied"), TimeoutError("synthetic timeout"), RuntimeError("synthetic failure")])
def test_execution_failure_timeout_and_permissions_recorded(tmp_path, error):
    _c, executor, plan, handler = setup(tmp_path, Handler(failure=error))
    assert execute(executor, plan)["results"][0]["status"] == "failed"
    assert handler.calls == 1


def test_recheck_improvement_history_and_replay_protection(tmp_path):
    _c, executor, plan, _h = setup(tmp_path)
    record = execute(executor, plan)
    row = record["results"][0]
    assert row["status"] == "improved" and row["before"] != row["after"] and row["exit_code"] == 0
    assert json.loads((tmp_path / "plans.jsonl").read_text())["plan_id"] == plan.plan_id
    with pytest.raises(ConfirmationRequired):
        execute(executor, plan)


@pytest.mark.parametrize(("verified", "status"), [(False, "unchanged"), (None, "unknown")])
def test_success_does_not_mean_problem_resolved(tmp_path, verified, status):
    _c, executor, plan, _h = setup(tmp_path, Handler(verified=verified))
    assert execute(executor, plan)["results"][0]["status"] == status


def test_no_new_action_after_cancel(tmp_path):
    handler = Handler()
    second = Handler("quarantine_allowed_cache")
    coordinator = RepairCoordinator(backups=MemoryBackups(tmp_path / "backups"), handlers={h.action_id: h for h in (handler, second)})
    executor = PlanExecutor(coordinator, probe=lambda s: {"applicable": True, "metrics": coordinator.handlers[s.action_id].snapshot({})})
    plan = make_plan(summary([suggestion(), suggestion(second.action_id)]))
    executor.authorize(plan)
    handler.on_run = executor.cancel.set
    record = execute(executor, plan)
    assert handler.calls == 1 and second.calls == 0
    assert record["results"][1]["status"] == "skipped"


def test_failed_dependency_skips_child_but_independent_continues(tmp_path):
    handlers = [Handler(failure=RuntimeError("failure")), Handler("quarantine_allowed_cache"), Handler("restore_user_settings")]
    coordinator = RepairCoordinator(backups=MemoryBackups(tmp_path / "backups"), handlers={h.action_id: h for h in handlers})
    executor = PlanExecutor(coordinator, probe=lambda _s: {"applicable": True, "metrics": {"state": "synthetic"}})
    plan = make_plan(summary([suggestion(h.action_id) for h in handlers]))
    plan.items[1].dependencies = [plan.items[0].item_id]
    executor.authorize(plan)
    execute(executor, plan)
    assert [h.calls for h in handlers] == [1, 0, 1]


def test_plan_lock_conflict_dedup_and_cycle(tmp_path):
    _c, executor, plan, _h = setup(tmp_path)
    with PlanLock(tmp_path / "operations"), pytest.raises(RuntimeError):
        execute(executor, plan)
    assert len(make_plan(summary([suggestion(), suggestion()])).items) == 1
    plan.items[0].dependencies = [plan.items[0].item_id]
    with pytest.raises(ValueError):
        executor.authorize(plan)


def test_backup_conflict_refuses_overwrite(tmp_path):
    coordinator, executor, plan, handler = setup(tmp_path)
    record = execute(executor, plan)
    backup_id = record["results"][0]["backup_id"]
    handler.value = 2  # A third party changed the state.
    with pytest.raises(RepairExecutionError):
        coordinator.rollback(backup_id, user_confirmed=True)
    assert handler.value == 2
    handler.value = 1
    assert coordinator.rollback(backup_id, user_confirmed=True).executed
    assert handler.value == 0


def test_report_and_history_redact_metrics_and_log(tmp_path):
    _c, executor, plan, _h = setup(tmp_path, probe=lambda _s: {"applicable": True, "metrics": {"address": "192.0.2.10", "email": "synthetic@example.com", "secret": "token=synthetic-test-secret", "destination": "Synthetic private recovery path"}})
    record = execute(executor, plan)
    text = plan_markdown(record) + (tmp_path / "plans.jsonl").read_text()
    assert "192.0.2.10" not in text and "synthetic@example.com" not in text and "synthetic-test-secret" not in text
    assert "Synthetic private recovery path" not in text and "destination" not in text


def test_cache_allowlist_closed_process_recovery_and_conflict(tmp_path):
    root = tmp_path / "Cache"
    root.mkdir()
    (root / "synthetic.bin").write_bytes(b"synthetic cache")
    handler = CacheHandler({"vscode": (root, ("code.exe",))}, processes=list)
    target = {"cache_id": "vscode"}
    before = handler.snapshot(target)
    handler.execute(target)
    assert not root.exists() and handler.verify(target)[0]
    root.mkdir()  # A running app recreated its cache; do not overwrite it.
    with pytest.raises(ValueError):
        handler.rollback(before)
    root.rmdir()  # Only our empty synthetic test folder.
    handler.rollback(before)
    assert (root / "synthetic.bin").read_bytes() == b"synthetic cache"
    with pytest.raises(ValueError):
        handler.validate({"cache_id": "browser_profile", "path": "arbitrary"})
    handler.processes = lambda: ["Code.EXE"]
    with pytest.raises(PermissionError):
        handler.execute(target)


@pytest.mark.parametrize("target", [{"service_name": "Spooler';whoami"}, {"cache_id": "../Cookies"}, {"interface_index": "4;whoami"}])
def test_backend_parameter_injection_blocked(tmp_path, target):
    action = "service_start" if "service_name" in target else "quarantine_allowed_cache" if "cache_id" in target else "reset_dns_to_dhcp"
    c = RepairCoordinator(backups=MemoryBackups(tmp_path / "backups"))
    s = suggestion(action)
    s.target = target
    with pytest.raises((ValueError, RuntimeError)):
        c.prepare(s)


def test_automatic_service_and_dependencies_not_generic_stopped_services():
    state = {"State": "Stopped", "StartMode": "Auto", "Dependencies": [{"State": "Running"}]}
    assert service_applicable(state, "service_start")
    for key, value in (("StartMode", "Manual"), ("StartMode", "Disabled"), ("State", "Running"), ("Dependencies", [{"State": "Stopped"}])):
        assert not service_applicable({**state, key: value}, "service_start")


def test_dhcp_lease_change_not_manual_dns_conflict():
    a = {"dns": [{"Automatic": True, "ServerAddresses": ["192.0.2.1"]}]}
    b = {"dns": [{"Automatic": True, "ServerAddresses": ["192.0.2.2"]}]}
    assert state_signature(a) == state_signature(b)
    b["dns"][0]["Automatic"] = False
    assert state_signature(a) != state_signature(b)


def test_transient_peak_is_not_sustained_pressure():
    normal = {"cpu": 20, "memory": 40, "disk": None}
    assert sustained_pressure([{**normal, "cpu": 99}, normal, normal, normal, normal, normal])["cpu"] is False
    assert sustained_pressure([{**normal, "cpu": 99}] * 6)["cpu"] is True
    assert sustained_pressure([normal] * 6)["disk"] is None


def test_structured_crash_fields_and_exact_path_not_localized_message():
    script = crash_event_script("'C:\\Synthetic\\app.exe'", "'app.exe'")
    assert "ToXml" in script and "ExceptionCode" in script and "ModuleName" in script and "ExactPath" in script
    assert "Start-Process" not in script


def test_network_single_target_failure_not_global_reset():
    class Runner:
        def powershell_json(self, *args, **kwargs):
            return CommandResult((), 0, "[]", "")
    resolver = lambda host: ["192.0.2.1"]
    https = lambda url, _direct: ("target.invalid" not in url, "synthetic evidence")
    check = NetworkSceneCheck("https://target.invalid", "one_site", resolver, https)
    result = check.run(ScanContext(Runner(), threading.Event(), "网络或Wi-Fi异常"))[0]
    assert not result.repair_suggestions and tr("target_only") in result.recommendations


def test_bilingual_resources_have_identical_keys():
    assert all(len(pair) == 2 and all(pair) for pair in COPY.values())


def test_service_structured_interface_rejects_missing_or_denied_state():
    class Runner:
        def powershell_json(self, *args, **kwargs):
            return CommandResult((), 0, '{}', '')
    with pytest.raises(RepairExecutionError):
        service_state(Runner(), "Spooler")


def test_scene_recheck_can_reject_metric_improvement(tmp_path):
    _c, executor, plan, _handler = setup(tmp_path)
    executor.recheck = lambda _item: {"healthy": False, "evidence": "Synthetic persistent failure"}
    assert execute(executor, plan)["results"][0]["status"] == "unchanged"


def test_scene_recheck_error_is_unknown(tmp_path):
    _c, executor, plan, _handler = setup(tmp_path)
    def unavailable(_item):
        raise OSError("Synthetic unreadable state")
    executor.recheck = unavailable
    assert execute(executor, plan)["results"][0]["status"] == "unknown"


def test_old_diagnostics_do_not_generate_a_fresh_plan():
    old = summary([suggestion()])
    old.finished_at = (datetime.now(UTC) - timedelta(minutes=6)).isoformat()
    assert not make_plan(old).items


def test_restore_dns_validates_all_families_before_mutation():
    from helppack.diagnostics.repairs import InvalidRepairTarget, _restore_dns
    class NoMutation:
        def run_repair(self, *args, **kwargs):
            pytest.fail("Malformed backup must not mutate DNS")
    with pytest.raises(InvalidRepairTarget):
        _restore_dns(NoMutation(), {"interface_index": 3, "dns": [{"AddressFamily": 2}]})


def test_unreadable_service_is_unknown_not_healthy():
    from helppack.diagnostics.scenario_checks import SafeServiceCheck
    class Unreadable:
        def powershell_json(self, *args, **kwargs):
            return CommandResult((), 1, "", "Synthetic denied")
    finding = SafeServiceCheck().run(ScanContext(Unreadable(), threading.Event(), "声音问题"))[0]
    assert finding.status == DiagnosticStatus.UNKNOWN and not finding.repair_suggestions


def test_elevation_refusal_isolated_and_no_execution(tmp_path, monkeypatch):
    from helppack.diagnostics.repairs import RepairOutcome
    class DeniedBroker:
        def execute(self, _suggestion):
            return RepairOutcome(False, "Synthetic UAC denial")
    _c, executor, plan, handler = setup(tmp_path, Handler("service_start"))
    monkeypatch.setattr("helppack.diagnostics.repair_plan.is_admin", lambda: False)
    executor.broker = DeniedBroker()
    row = execute(executor, plan)["results"][0]
    assert row["status"] == "failed" and handler.calls == 0


def test_timeout_wait_does_not_kill_component_writer(monkeypatch):
    import subprocess

    from helppack.diagnostics.runner import CommandRunner
    class Process:
        returncode = 0
        calls = 0
        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("synthetic", timeout)
            return b"completed", b""
        def kill(self):
            pytest.fail("Must not kill a component writer")
    process = Process()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    result = CommandRunner().run_repair(["sfc.exe", "/scannow"], timeout=1)
    assert result.timed_out and process.calls == 2


def test_builtin_commands_ignore_path_and_systemroot_spoofing(monkeypatch):
    import os
    import subprocess

    from helppack.diagnostics.runner import CommandRunner
    if os.name != "nt":
        pytest.skip("Native Windows system-directory lookup")
    captured = []
    monkeypatch.setenv("SystemRoot", "D:/SyntheticSpoof")
    def run(args, **kwargs):
        captured.append(args)
        return subprocess.CompletedProcess(args, 0, b"{}", b"")
    monkeypatch.setattr(subprocess, "run", run)
    CommandRunner().powershell_json("'{}'")
    assert "SyntheticSpoof" not in captured[0][0]
    assert captured[0][0].lower().endswith(r"system32\windowspowershell\v1.0\powershell.exe")
