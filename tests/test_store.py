import json
import threading

import pytest

from helppack.diagnostics.advanced_checks import MicrosoftStoreCheck
from helppack.diagnostics.engine import ScanContext
from helppack.diagnostics.models import DiagnosticStatus
from helppack.diagnostics.preflight import check_preconditions
from helppack.diagnostics.repairs import RepairExecutionError
from helppack.diagnostics.runner import CommandResult
from helppack.diagnostics.store import (
    STORE_PROBE,
    STORE_REGISTER,
    read_store_state,
)


class StoreRunner:
    def __init__(self, **changes):
        self.state = {"Exists": True, "Status": "Ok", "PolicyDisabled": False,
                      "CanRegisterByFamily": True, "CanReset": True,
                      "ManifestExists": True, "WsresetAvailable": True}
        self.state.update(changes)
        self.returncode = 0

    def powershell_json(self, script, *, timeout):
        assert "\n" not in script
        return CommandResult(("powershell.exe",), self.returncode, json.dumps(self.state), "")


def diagnose(runner):
    return MicrosoftStoreCheck().run(ScanContext(runner, threading.Event()))[0]


def test_query_failure_is_unknown_not_uninstalled():
    runner = StoreRunner()
    runner.returncode = 1
    result = diagnose(runner)
    assert result.status == DiagnosticStatus.UNKNOWN
    assert not result.repair_suggestions
    assert "不代表" in result.explanation


@pytest.mark.parametrize("invalid", [None, "false", 0])
def test_incomplete_or_wrong_boolean_probe_rejected(invalid):
    with pytest.raises(ValueError):
        read_store_state(StoreRunner(Exists=invalid))


def test_registered_does_not_claim_successful_startup():
    result = diagnose(StoreRunner())
    assert result.status == DiagnosticStatus.NORMAL
    assert "不是启动成功" in result.explanation
    assert "store_reset_data" not in {r.action_id for r in result.repair_suggestions}


def test_user_unregistered_not_machine_uninstalled(monkeypatch):
    monkeypatch.setattr("helppack.diagnostics.repairs.is_admin", lambda: False)
    runner = StoreRunner(Exists=False, ManifestExists=False)
    result = diagnose(runner)
    assert not result.repair_suggestions
    assert "机器级" in result.evidence[0].value
    for action in ("store_reregister", "store_cache_reset", "store_reset_data"):
        with pytest.raises(RepairExecutionError):
            check_preconditions(action, {}, runner)


def test_policy_disabled_has_no_repairs(monkeypatch):
    monkeypatch.setattr("helppack.diagnostics.repairs.is_admin", lambda: False)
    runner = StoreRunner(PolicyDisabled=True)
    assert not diagnose(runner).repair_suggestions
    with pytest.raises(RepairExecutionError):
        check_preconditions("store_reregister", {}, runner)
    assert "HKCU:" in STORE_PROBE and "HKLM:" in STORE_PROBE


def test_old_windows_manifest_repair_and_admin_refusal(monkeypatch):
    runner = StoreRunner(CanRegisterByFamily=False)
    monkeypatch.setattr("helppack.diagnostics.repairs.is_admin", lambda: False)
    check_preconditions("store_reregister", {}, runner)
    assert "-Register $manifest" in STORE_REGISTER
    assert "RegisterByFamilyName" not in STORE_REGISTER
    assert "Remove-AppxPackage" not in STORE_REGISTER
    assert "-AllUsers" not in STORE_REGISTER
    monkeypatch.setattr("helppack.diagnostics.repairs.is_admin", lambda: True)
    with pytest.raises(RepairExecutionError):
        check_preconditions("store_reregister", {}, runner)
