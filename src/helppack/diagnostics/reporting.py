from __future__ import annotations

from helppack.english import text as msg

from ..english import format_time, label
from ..redaction import redact_text
from .models import ScanSummary


def generate_diagnostic_markdown(summary: ScanSummary) -> str:
    lines = [
        msg('## 本机只读诊断结果'),
        msg('- 问题类型：{0}', label(summary.category)),
        msg('- 扫描开始：{0}', format_time(summary.started_at)),
        msg('- 扫描结束：{0}', format_time(summary.finished_at)),
        msg('- 扫描状态：{0}', msg('用户已取消，结果不完整') if summary.cancelled else label('已完成')),
        msg('- 安全说明：本次扫描只执行 L0 只读检查，没有修改系统。'),
        "",
    ]
    for item in summary.results:
        lines.extend(
            [
                f"### {item.display_name}",
                msg('- 检查 ID：{0}', item.check_id),
                msg('- 状态：{0}', label(item.status.value)),
                msg('- 严重程度：{0}', label(item.severity.value)),
                msg('- 判断可信度：{0}', label(item.confidence)),
                msg('- 安全等级：{0}', item.safety_level.value),
                msg('- 检测时间：{0}', format_time(item.checked_at)),
                msg('- 检测证据：'),
            ]
        )
        lines.extend(f"  - {evidence.label}: {evidence.value.replace(chr(10), '<br>')}" for evidence in item.evidence)
        lines.append(msg('- 通俗解释：{0}', item.explanation))
        lines.append(msg('- 建议操作：'))
        lines.extend(f"  - {value}" for value in item.recommendations)
        lines.append("")
    lines.extend(
        [
            msg('> 诊断结果是基于当前证据的排查线索，不是确定的故障原因。检查失败、权限不足、不支持和未发现异常已分别记录。'),
            "",
        ]
    )
    return redact_text("\n".join(lines))
