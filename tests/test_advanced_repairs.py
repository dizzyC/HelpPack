from pathlib import Path

import pytest

from helppack.diagnostics.models import (
    RepairSuggestion,
    RestartRequirement,
    RollbackCapability,
    SafetyLevel,
)
from helppack.diagnostics.repairs import (
    BackupStore,
    ConfirmationRequired,
    InvalidRepairTarget,
    RepairCoordinator,
)


def suggestion(action_id: str, target: dict[str, str], *, level: SafetyLevel = SafetyLevel.L2, admin: bool = False, phrase: str = "") -> RepairSuggestion:
    return RepairSuggestion(
        action_id, "虚构修复", target, level, admin, "虚构影响", "固定动作预览", "不可回滚",
        RollbackCapability.NONE, RestartRequirement.NONE, requires_second_confirmation=level == SafetyLevel.L3,
        confirmation_phrase=phrase,
    )


def test_action_registry_rejects_unknown_action_and_service(tmp_path: Path) -> None:
    coordinator = RepairCoordinator(backups=BackupStore(tmp_path))
    with pytest.raises(InvalidRepairTarget):
        coordinator.prepare(suggestion("run_arbitrary_command", {"command": "whoami"}))
    with pytest.raises(InvalidRepairTarget):
        coordinator.prepare(suggestion("service_start", {"service_name": "UntrustedService"}, admin=True))


def test_network_reset_requires_proven_safe_shape(tmp_path: Path) -> None:
    coordinator = RepairCoordinator(backups=BackupStore(tmp_path))
    with pytest.raises(InvalidRepairTarget):
        coordinator.prepare(suggestion("reset_tcp_ip", {"dhcp_only": "false", "complex_adapters": "false"}, level=SafetyLevel.L3, admin=True))
    prepared = coordinator.prepare(suggestion("reset_tcp_ip", {"dhcp_only": "true", "complex_adapters": "false"}, level=SafetyLevel.L3, admin=True))
    assert prepared.requires_second_confirmation is True


def test_high_risk_action_needs_second_confirmation(tmp_path: Path) -> None:
    coordinator = RepairCoordinator(backups=BackupStore(tmp_path))
    prepared = coordinator.prepare(suggestion("store_reset_data", {"package_family": "Microsoft.WindowsStore_8wekyb3d8bbwe"}, level=SafetyLevel.L3, phrase="重置"))
    with pytest.raises(ConfirmationRequired):
        coordinator.execute(prepared, user_confirmed=True, second_confirmation="错误")


def test_wua_update_id_and_inf_path_are_typed(tmp_path: Path) -> None:
    coordinator = RepairCoordinator(backups=BackupStore(tmp_path))
    with pytest.raises(InvalidRepairTarget):
        coordinator.prepare(suggestion("install_wua_driver", {"update_id": "'; Remove-Item C:\\*"}, level=SafetyLevel.L3, admin=True))
    with pytest.raises(InvalidRepairTarget):
        coordinator.prepare(suggestion("install_inf_driver", {"inf_path": str(tmp_path / "missing.inf")}, level=SafetyLevel.L3, admin=True))


def test_vendor_url_is_restricted_to_official_https_hosts(tmp_path: Path) -> None:
    coordinator = RepairCoordinator(backups=BackupStore(tmp_path))
    coordinator.prepare(suggestion("open_vendor_support", {"url": "https://support.lenovo.com/"}, level=SafetyLevel.L1))
    for url in ("http://support.lenovo.com/", "https://evil.example/driver", "https://user:pass@www.dell.com/support/"):
        with pytest.raises(InvalidRepairTarget):
            coordinator.prepare(suggestion("open_vendor_support", {"url": url}, level=SafetyLevel.L1))
