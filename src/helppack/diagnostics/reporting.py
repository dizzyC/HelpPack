from __future__ import annotations

from ..redaction import redact_text
from .models import ScanSummary


def generate_diagnostic_markdown(summary: ScanSummary) -> str:
    lines = [
        "## 本机只读诊断结果",
        f"- 问题类型：{summary.category}",
        f"- 扫描开始：{summary.started_at}",
        f"- 扫描结束：{summary.finished_at}",
        f"- 扫描状态：{'用户已取消，结果不完整' if summary.cancelled else '已完成'}",
        "- 安全说明：本次扫描只执行 L0 只读检查，没有修改系统。",
        "",
    ]
    for item in summary.results:
        lines.extend(
            [
                f"### {item.display_name}",
                f"- 检查 ID：{item.check_id}",
                f"- 状态：{item.status.value}",
                f"- 严重程度：{item.severity.value}",
                f"- 判断可信度：{item.confidence}",
                f"- 安全等级：{item.safety_level.value}",
                f"- 检测时间：{item.checked_at}",
                "- 检测证据：",
            ]
        )
        lines.extend(f"  - {evidence.label}：{evidence.value.replace(chr(10), '<br>')}" for evidence in item.evidence)
        lines.append(f"- 通俗解释：{item.explanation}")
        lines.append("- 建议操作：")
        lines.extend(f"  - {value}" for value in item.recommendations)
        lines.append("")
    lines.extend(
        [
            "> 诊断结果是基于当前证据的排查线索，不是确定的故障原因。检查失败、权限不足、不支持和未发现异常已分别记录。",
            "",
        ]
    )
    return redact_text("\n".join(lines))
