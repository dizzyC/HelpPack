from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..redaction import redact_text
from .models import ScanSummary


class DiagnosticHistoryStore:
    def __init__(self, root: str | Path | None = None) -> None:
        default = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HelpPack" / "history"
        self.root = Path(root) if root is not None else default
        self.last_id: str | None = None

    def save(self, summary: ScanSummary) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        redacted_value = _redact_value(asdict(summary))
        serialized = json.dumps(redacted_value, ensure_ascii=False, indent=2)
        path = self.root / "latest_scan.json"
        temporary = self.root / "latest_scan.json.tmp"
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(path)
        self.last_id = self.save_record({"kind": "扫描", "summary": redacted_value, "status": "稍后处理", "operations": []})
        return path

    def save_record(self, value: dict[str, Any]) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        record_id = uuid.uuid4().hex
        self._write_record(record_id, {**value, "id": record_id})
        self.last_id = record_id
        return record_id

    def _path(self, record_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", record_id):
            raise ValueError("历史编号无效")
        return self.root / f"record_{record_id}.json"

    def _write_record(self, record_id: str, value: dict) -> None:
        path = self._path(record_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(_redact_value(value), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def load_record(self, record_id: str) -> dict:
        value = json.loads(self._path(record_id).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("历史记录损坏")
        if value.get("id") != record_id:
            raise ValueError("历史记录编号不匹配")
        return value

    def list_records(self, limit: int = 100) -> list[dict]:
        if not self.root.exists():
            return []
        result = []
        paths = sorted(self.root.glob("record_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in paths[:limit]:
            try:
                result.append(self.load_record(path.stem[7:]))
            except (OSError, ValueError, TypeError):
                continue
        return result

    def mark(self, record_id: str, status: str) -> None:
        if status not in {"已解决", "未解决", "稍后处理"}:
            raise ValueError("处理状态无效")
        value = self.load_record(record_id)
        value["status"] = status
        self._write_record(record_id, value)

    def add_operation(self, record_id: str, operation: dict) -> None:
        value = self.load_record(record_id)
        value.setdefault("operations", []).append(operation)
        self._write_record(record_id, value)

    def load_latest(self) -> dict[str, Any] | None:
        path = self.root / "latest_scan.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None


def compare_summaries(before: dict, after: dict) -> list[str]:
    old = {r["check_id"]: r for r in before.get("results", [])}
    changes = []
    for current in after.get("results", []):
        previous = old.get(current["check_id"])
        if previous is None:
            continue
        name = current["display_name"]
        if previous.get("status") != current.get("status"):
            changes.append(f"{name}：{previous.get('status')} → {current.get('status')}")
        values = {e["label"]: e["value"] for e in previous.get("evidence", [])}
        for evidence in current.get("evidence", []):
            label = evidence["label"]
            if label in values and values[label] != evidence["value"]:
                changes.append(f"{name} / {label}：{values[label]} → {evidence['value']}")
    return [_redact_value(c) for c in changes] or ["可比较项目未发现变化；不代表故障已经解决。"]

def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_value(item) for key, item in value.items()}
    return value
