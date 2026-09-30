import json
from datetime import UTC, datetime, timedelta

import pytest

from helppack.diagnostics.elevation import (
    ElevationRequestStore,
    _sign,
    run_elevated_helper,
)
from helppack.diagnostics.models import RepairSuggestion, SafetyLevel
from helppack.diagnostics.preflight import check_preconditions
from helppack.diagnostics.repairs import (
    BackupStore,
    ConfirmationRequired,
    RepairCoordinator,
    RepairExecutionError,
)
from helppack.diagnostics.runner import CommandResult


def action(name="store_reset_data", target=None):
    return RepairSuggestion(name, "测试操作", target or {"package_family": "Microsoft.WindowsStore_8wekyb3d8bbwe"},
                            SafetyLevel.L1, False, "测试影响", "测试预览", "无")


def test_caller_cannot_lower_high_risk_policy(tmp_path):
    coordinator = RepairCoordinator(backups=BackupStore(tmp_path))
    prepared = coordinator.prepare(action())
    assert prepared.safety_level == SafetyLevel.L3
    assert prepared.confirmation_phrase == "重置"
    with pytest.raises(ConfirmationRequired):
        coordinator.execute(prepared, user_confirmed=True)


def test_caller_cannot_change_confirmation_metadata(tmp_path):
    coordinator = RepairCoordinator(backups=BackupStore(tmp_path))
    prepared = coordinator.prepare(action())
    prepared.requires_second_confirmation = False
    with pytest.raises(ConfirmationRequired):
        coordinator.execute(prepared, user_confirmed=True)


def test_helper_never_writes_result_outside_request_directory(tmp_path):
    store = ElevationRequestStore(tmp_path / "operations")
    request, secret, _ = store.create(action())
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["operation_id"] = "../escape"
    request.write_text(json.dumps(payload), encoding="utf-8")
    assert run_elevated_helper(str(request), secret, store) != 0
    assert not (tmp_path / "escape.result.json").exists()


def test_helper_rejects_replayed_request_before_execution(tmp_path):
    store = ElevationRequestStore(tmp_path)
    request, secret, result = store.create(action())
    assert run_elevated_helper(str(request), secret, store) != 0
    original = result.read_bytes()
    assert run_elevated_helper(str(request), secret, store) != 0
    assert result.read_bytes() == original


class ReadOnlyRunner:
    def __init__(self, payload):
        self.payload = payload

    def powershell_json(self, script, timeout=30):
        return CommandResult(("mock",), 0, json.dumps(self.payload), "")


def test_network_preflight_rejects_static_or_changed_adapter():
    rows = [{"Index": 4, "Alias": "Example", "Physical": True, "Dhcp": "Disabled"}]
    with pytest.raises(RepairExecutionError):
        check_preconditions("reset_dns_to_dhcp", {"interface_index": "4"}, ReadOnlyRunner(rows))


def test_network_preflight_rejects_disconnected_virtual_adapters():
    rows = [{"Index": 4, "Physical": True, "Dhcp": "Enabled"},
            {"Index": 9, "Physical": False, "Status": "Disconnected", "Dhcp": "Enabled"}]
    with pytest.raises(RepairExecutionError):
        check_preconditions("reset_tcp_ip", {}, ReadOnlyRunner(rows))


def test_disabled_service_is_not_reenabled():
    with pytest.raises(RepairExecutionError):
        check_preconditions("service_start", {"service_name": "BITS"}, ReadOnlyRunner({"StartMode": "Disabled"}))


def test_helper_expired_request_never_consumed(tmp_path):
    store = ElevationRequestStore(tmp_path)
    path, secret, _ = store.create(action())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("hmac")
    payload["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    payload["hmac"] = _sign(payload, secret)
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert run_elevated_helper(str(path), secret, store) != 0
    assert not path.with_suffix(".consumed").exists()
