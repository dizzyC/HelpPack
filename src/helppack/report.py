from __future__ import annotations

from collections.abc import Iterable

from helppack.english import text as msg

from .english import format_time, label
from .models import ReportBundle
from .redaction import redact_text

SYSTEM_LABELS = {
    "windows_version": msg('Windows 版本'),
    "architecture": msg('系统架构'),
    "cpu": "CPU",
    "logical_cores": msg('逻辑核心数'),
    "memory_total": msg('总内存'),
    "memory_usage": msg('当前内存使用率'),
    "disks": msg('磁盘分区'),
    "gpu": msg('显卡'),
    "network_interfaces": msg('网络接口状态'),
    "gateway_reachable": msg('默认网关可达性'),
    "dns_status": msg('DNS 解析'),
    "current_time": msg('当前时间'),
    "boot_time": msg('最近开机时间'),
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
        msg('# 求助包诊断报告'),
        "",
        msg('## 问题摘要'),
        msg('- 问题类型：{0}', label(problem.category)),
        msg('- 问题标题：{0}', problem.title or msg('未填写')),
        msg('- 处理状态（用户标记）：{0}', label(problem.resolution_status)),
        "",
        msg('## 用户描述'),
        problem.description or msg('未填写'),
        "",
        msg('### 问题出现前的操作'),
        problem.preceding_actions or msg('未填写'),
        "",
        msg('## 已尝试的操作'),
        problem.attempted_solutions or msg('未填写'),
        "",
        msg('## 仍未解决的问题'),
        problem.unresolved_issues or msg('尚未填写；诊断正常或指标改善不代表问题已经解决。'),
        "",
        msg('## 系统环境'),
        *_format_fields(snapshot, selected, environment_keys),
        "",
        msg('## 硬件和资源状态'),
        *_format_fields(snapshot, selected, resource_keys),
        "",
        msg('## 网络检测结果'),
        *_format_fields(snapshot, selected, network_keys),
        "",
        msg('## 附件列表'),
    ]
    included = [item.export_name for item in bundle.attachments if item.included]
    sections.extend([f"- {name}" for name in included] or [msg('无附件')])
    sections.extend(
        ["", bundle.diagnostics_markdown.strip()] if bundle.diagnostics_markdown.strip() else []
    )
    sections.extend(
        [
            "",
            msg('## 值得优先检查的方向'),
            msg('以下内容仅是排查方向，不是确定的故障结论：请先结合报错信息、问题发生时间和可复现步骤进行核对。'),
            "",
            msg('## 隐私处理说明'),
            msg('本报告已自动尝试隐藏用户名、用户目录、IP 地址、MAC 地址、邮箱地址及常见密钥或密码字段。'),
            msg('截图内容未进行 OCR 脱敏，导出前应由用户自行检查。自动脱敏可能无法覆盖所有敏感信息。'),
            "",
        ]
    )
    return redact_text("\n".join(sections), extra_paths=bundle.source_paths())


def _format_fields(snapshot: dict[str, str], selected: set[str], keys: tuple[str, ...]) -> list[str]:
    rows: list[str] = []
    for key in keys:
        if key not in selected:
            continue
        value = snapshot.get(key, "无法读取")
        if value == "无法读取" or key in {"dns_status", "gateway_reachable"}:
            value = label(value)
        if key in {"current_time", "boot_time"}:
            value = format_time(value)
        value = value.replace("\n", "<br>")
        rows.append(f"- {SYSTEM_LABELS[key]}: {value}")
    return rows or [msg('未包含此类信息')]


def concise_summary(report_text: str) -> str:
    """Summarize only the current preview, never reintroduce removed source data."""
    text = redact_text(report_text)
    sections = []
    current = []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            sections.append(current)
            current = []
        current.append(line)
    if current:
        sections.append(current)
    priority = ("Problem Summary", "Your Description", "Actions Already Tried", "Unresolved Issues", "Before and After", "Symptoms", "Evidence")
    selected = [s for s in sections if any(word in s[0] for word in priority)]
    if not selected:
        selected = sections
    body = "\n\n".join("\n".join(s).strip()[:450] for s in selected)[:2000]
    return msg('HelpPack 简洁问题摘要（检查线索不是确定原因）：\n') + body + msg('\n如需进一步排查，请结合完整报告；转发前检查隐私。')
