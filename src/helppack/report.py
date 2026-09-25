from __future__ import annotations

from collections.abc import Iterable

from .models import ReportBundle
from .redaction import redact_text

SYSTEM_LABELS = {
    "windows_version": "Windows 版本",
    "architecture": "系统架构",
    "cpu": "CPU",
    "logical_cores": "逻辑核心数",
    "memory_total": "总内存",
    "memory_usage": "当前内存使用率",
    "disks": "磁盘分区",
    "gpu": "显卡",
    "network_interfaces": "网络接口状态",
    "gateway_reachable": "默认网关可达性",
    "dns_status": "DNS 解析",
    "current_time": "当前时间",
    "boot_time": "最近开机时间",
}

DEFAULT_INCLUDED_FIELDS = tuple(SYSTEM_LABELS)


def generate_markdown(bundle: ReportBundle, included_fields: Iterable[str] | None = None) -> str:
    selected = set(included_fields if included_fields is not None else DEFAULT_INCLUDED_FIELDS)
    problem = bundle.problem
    snapshot = bundle.snapshot.as_dict()

    environment_keys = ("windows_version", "architecture", "current_time", "boot_time")
    resource_keys = ("cpu", "logical_cores", "memory_total", "memory_usage", "disks", "gpu")
    network_keys = ("network_interfaces", "gateway_reachable", "dns_status")

    sections = [
        "# 求助包诊断报告",
        "",
        "## 问题摘要",
        f"- 问题类型：{problem.category}",
        f"- 问题标题：{problem.title or '未填写'}",
        "",
        "## 用户描述",
        problem.description or "未填写",
        "",
        "### 问题出现前的操作",
        problem.preceding_actions or "未填写",
        "",
        "## 已尝试的操作",
        problem.attempted_solutions or "未填写",
        "",
        "## 系统环境",
        *_format_fields(snapshot, selected, environment_keys),
        "",
        "## 硬件和资源状态",
        *_format_fields(snapshot, selected, resource_keys),
        "",
        "## 网络检测结果",
        *_format_fields(snapshot, selected, network_keys),
        "",
        "## 附件列表",
    ]
    included = [item.export_name for item in bundle.attachments if item.included]
    sections.extend([f"- {name}" for name in included] or ["无附件"])
    sections.extend(
        ["", bundle.diagnostics_markdown.strip()] if bundle.diagnostics_markdown.strip() else []
    )
    sections.extend(
        [
            "",
            "## 值得优先检查的方向",
            "以下内容仅是排查方向，不是确定的故障结论：请先结合报错信息、问题发生时间和可复现步骤进行核对。",
            "",
            "## 隐私处理说明",
            "本报告已自动尝试隐藏用户名、用户目录、IP 地址、MAC 地址、邮箱地址及常见密钥或密码字段。",
            "截图内容未进行 OCR 脱敏，导出前应由用户自行检查。自动脱敏可能无法覆盖所有敏感信息。",
            "",
        ]
    )
    return redact_text("\n".join(sections), extra_paths=bundle.source_paths())


def _format_fields(snapshot: dict[str, str], selected: set[str], keys: tuple[str, ...]) -> list[str]:
    rows: list[str] = []
    for key in keys:
        if key not in selected:
            continue
        value = snapshot.get(key, "无法读取").replace("\n", "<br>")
        rows.append(f"- {SYSTEM_LABELS[key]}：{value}")
    return rows or ["未包含此类信息"]
