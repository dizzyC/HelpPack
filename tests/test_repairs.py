from pathlib import Path

import pytest

from helppack.diagnostics.models import RepairSuggestion, SafetyLevel
from helppack.diagnostics.repairs import (
    ALLOWED_STARTUP_KEYS,
    BackupStore,
    ConfirmationRequired,
    InvalidRepairTarget,
    RepairCoordinator,
)


class FakeRegistry:
    def __init__(self) -> None:
        self.values = {}
        self.mutations = []

    def read_value(self, key_path, value_name):
        key = (key_path, value_name)
        if key in self.values:
            value, value_type = self.values[key]
            return True, value, value_type
        return False, None, 0

    def set_value(self, key_path, value_name, value, value_type):
        self.mutations.append(("set", key_path, value_name))
        self.values[(key_path, value_name)] = (value, value_type)

    def delete_value(self, key_path, value_name):
        self.mutations.append(("delete", key_path, value_name))
        self.values.pop((key_path, value_name), None)


def startup_suggestion(name="KnownApp") -> RepairSuggestion:
    path = next(iter(ALLOWED_STARTUP_KEYS))
    return RepairSuggestion(
        action_id="disable_hkcu_startup",
        display_name=f"禁用 {name}",
        target={"key_path": path, "value_name": name},
        safety_level=SafetyLevel.L1,
        requires_admin=False,
        impact="不再自动启动",
        operation_preview="备份后删除单个值",
        rollback="恢复备份值",
    )


def test_repair_refusal_never_mutates_system(tmp_path: Path) -> None:
    backend = FakeRegistry()
    coordinator = RepairCoordinator(backend, BackupStore(tmp_path))
    prepared = coordinator.prepare(startup_suggestion())
    outcome = coordinator.execute(prepared, user_confirmed=False)
    assert outcome.executed is False
    assert backend.mutations == []
    assert list(tmp_path.iterdir()) == []


def test_confirmed_repair_saves_state_rechecks_and_rolls_back(tmp_path: Path) -> None:
    backend = FakeRegistry()
    suggestion = startup_suggestion()
    key = (suggestion.target["key_path"], suggestion.target["value_name"])
    backend.values[key] = (r"C:\Program Files\Known\app.exe", 1)
    coordinator = RepairCoordinator(backend, BackupStore(tmp_path))

    outcome = coordinator.execute(coordinator.prepare(suggestion), user_confirmed=True, recheck=lambda: "启动项已不存在")

    assert outcome.executed is True
    assert outcome.backup_id
    assert outcome.recheck_completed is True
    assert key not in backend.values
    assert (tmp_path / f"{outcome.backup_id}.json").exists()

    rollback = coordinator.rollback(outcome.backup_id, user_confirmed=True)
    assert rollback.executed is True
    assert backend.values[key] == (r"C:\Program Files\Known\app.exe", 1)


def test_stale_or_missing_confirmation_cannot_execute(tmp_path: Path) -> None:
    coordinator = RepairCoordinator(FakeRegistry(), BackupStore(tmp_path))
    prepared = coordinator.prepare(startup_suggestion())
    prepared.target["value_name"] = "Changed"
    with pytest.raises(ConfirmationRequired):
        coordinator.execute(prepared, user_confirmed=True)


def test_admin_required_action_is_blocked_without_admin(tmp_path: Path, monkeypatch) -> None:
    backend = FakeRegistry()
    suggestion = startup_suggestion()
    suggestion.requires_admin = True
    coordinator = RepairCoordinator(backend, BackupStore(tmp_path))
    monkeypatch.setattr("helppack.diagnostics.repairs.is_admin", lambda: False)
    with pytest.raises(PermissionError):
        coordinator.execute(coordinator.prepare(suggestion), user_confirmed=True)
    assert backend.mutations == []


def test_unknown_target_is_rejected_before_backup_or_mutation(tmp_path: Path) -> None:
    backend = FakeRegistry()
    coordinator = RepairCoordinator(backend, BackupStore(tmp_path))
    bad = startup_suggestion("bad/name")
    with pytest.raises(InvalidRepairTarget):
        coordinator.prepare(bad)
    assert backend.mutations == []
    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_audit_log_is_redacted(tmp_path: Path) -> None:
    backend = FakeRegistry()
    suggestion = startup_suggestion("UserApp")
    key = (suggestion.target["key_path"], suggestion.target["value_name"])
    backend.values[key] = ("token=secret-value", 1)
    coordinator = RepairCoordinator(backend, BackupStore(tmp_path))
    coordinator.execute(coordinator.prepare(suggestion), user_confirmed=True)
    assert "secret-value" not in "\n".join(coordinator.audit_log)
