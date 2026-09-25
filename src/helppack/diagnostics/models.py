from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class DiagnosticStatus(StrEnum):
    NORMAL = "正常"
    NOTICE = "提醒"
    ABNORMAL = "异常"
    UNKNOWN = "未知"
    UNSUPPORTED = "不支持"
    PERMISSION_DENIED = "权限不足"


class Severity(StrEnum):
    INFO = "信息"
    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"


class SafetyLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


@dataclass(slots=True)
class Evidence:
    label: str
    value: str


@dataclass(slots=True)
class RepairSuggestion:
    action_id: str
    display_name: str
    target: dict[str, str]
    safety_level: SafetyLevel
    requires_admin: bool
    impact: str
    operation_preview: str
    rollback: str


@dataclass(slots=True)
class DiagnosticResult:
    check_id: str
    category: str
    display_name: str
    status: DiagnosticStatus
    severity: Severity
    evidence: list[Evidence]
    explanation: str
    confidence: str
    recommendations: list[str]
    safety_level: SafetyLevel = SafetyLevel.L0
    requires_admin: bool = False
    supports_rollback: bool = False
    checked_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
    redacted_raw: str = ""
    repair_suggestions: list[RepairSuggestion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScanSummary:
    category: str
    started_at: str
    finished_at: str
    cancelled: bool
    results: list[DiagnosticResult]
