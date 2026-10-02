from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

UNAVAILABLE = "无法读取"


@dataclass(slots=True)
class ProblemDetails:
    category: str
    title: str
    description: str
    preceding_actions: str = ""
    attempted_solutions: str = ""
    unresolved_issues: str = ""
    resolution_status: str = "稍后处理"


@dataclass(slots=True)
class Attachment:
    path: Path
    export_name: str
    included: bool = True
    processed_path: Path | None = None

    @property
    def export_source(self) -> Path:
        return self.processed_path or self.path


@dataclass(slots=True)
class SystemSnapshot:
    windows_version: str = UNAVAILABLE
    architecture: str = UNAVAILABLE
    cpu: str = UNAVAILABLE
    logical_cores: str = UNAVAILABLE
    memory_total: str = UNAVAILABLE
    memory_usage: str = UNAVAILABLE
    disks: str = UNAVAILABLE
    gpu: str = UNAVAILABLE
    network_interfaces: str = UNAVAILABLE
    gateway_reachable: str = UNAVAILABLE
    dns_status: str = UNAVAILABLE
    current_time: str = UNAVAILABLE
    boot_time: str = UNAVAILABLE

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class ReportBundle:
    problem: ProblemDetails
    snapshot: SystemSnapshot
    attachments: list[Attachment] = field(default_factory=list)
    diagnostics_markdown: str = ""

    def source_paths(self) -> list[str]:
        return [str(path) for item in self.attachments for path in (item.path, item.export_source)]

    def serializable(self) -> dict[str, Any]:
        return {
            "problem": asdict(self.problem),
            "snapshot": self.snapshot.as_dict(),
            "attachments": [item.export_name for item in self.attachments if item.included],
            "has_diagnostics": bool(self.diagnostics_markdown),
        }
