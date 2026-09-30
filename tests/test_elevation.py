import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from helppack.diagnostics.elevation import (
    ElevationRequestStore,
    _sign,
    run_elevated_helper,
)
from helppack.diagnostics.models import (
    RepairSuggestion,
    RollbackCapability,
    SafetyLevel,
)


def elevated_suggestion() -> RepairSuggestion:
    return RepairSuggestion(
        "service_start", "启动虚构测试服务", {"service_name": "BITS"}, SafetyLevel.L2, True,
        "测试影响", "启动固定服务", "尽力恢复", RollbackCapability.BEST_EFFORT,
    )


def test_elevation_request_contains_no_arbitrary_command(tmp_path: Path) -> None:
    store = ElevationRequestStore(tmp_path)
    request, _secret, _result = store.create(elevated_suggestion())
    payload = json.loads(request.read_text(encoding="utf-8"))
    text = json.dumps(payload)
    assert '"command"' not in text
    assert payload["suggestion"]["action_id"] == "service_start"
    assert payload["suggestion"]["target"] == {"service_name": "BITS"}


def test_tampered_elevation_request_is_rejected(tmp_path: Path) -> None:
    store = ElevationRequestStore(tmp_path)
    request, secret, result = store.create(elevated_suggestion())
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["suggestion"]["target"]["service_name"] = "UntrustedService"
    request.write_text(json.dumps(payload), encoding="utf-8")
    assert run_elevated_helper(str(request), secret, store) != 0
    assert json.loads(result.read_text(encoding="utf-8"))["ok"] is False


def test_expired_elevation_request_is_rejected(tmp_path: Path) -> None:
    store = ElevationRequestStore(tmp_path)
    request, secret, result = store.create(elevated_suggestion())
    payload = json.loads(request.read_text(encoding="utf-8"))
    payload["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    payload["hmac"] = _sign({key: value for key, value in payload.items() if key != "hmac"}, secret)
    request.write_text(json.dumps(payload), encoding="utf-8")
    assert run_elevated_helper(str(request), secret, store) != 0
    assert "过期" in json.loads(result.read_text(encoding="utf-8"))["error"]
