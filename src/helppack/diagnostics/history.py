from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..redaction import redact_text
from .models import ScanSummary


class DiagnosticHistoryStore:
    def __init__(self, root: str | Path | None = None) -> None:
        default = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HelpPack" / "history"
        self.root = Path(root) if root is not None else default

    def save(self, summary: ScanSummary) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        redacted_value = _redact_value(asdict(summary))
        serialized = json.dumps(redacted_value, ensure_ascii=False, indent=2)
        path = self.root / "latest_scan.json"
        temporary = self.root / "latest_scan.json.tmp"
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(path)
        return path

    def load_latest(self) -> dict[str, Any] | None:
        path = self.root / "latest_scan.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_value(item) for key, item in value.items()}
    return value
