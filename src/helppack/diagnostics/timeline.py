from __future__ import annotations

from .investigation import Finding, Investigation, query, rows
from .runner import CommandRunner

SOURCES = (
    ("软件安装/崩溃", "Application", "11707,11708,1000,1001,1002,1026"),
    ("系统更新/异常重启", "System", "19,20,41,1001,6008"),
    ("驱动配置变更", "Microsoft-Windows-Kernel-PnP/Configuration", "400,410,411"),
)


def collect_timeline(cancel, progress, runner=None) -> Investigation:
    runner = runner or CommandRunner()
    result = Investigation("故障时间线（最近 30 天）")
    events = []
    for index, (source, log, ids) in enumerate(SOURCES):
        if cancel.is_set():
            raise InterruptedError("已取消")
        progress(index * 30, source)
        try:
            values = rows(query(runner, f"@(Get-WinEvent -FilterHashtable @{{LogName='{log}';Id=@({ids});StartTime=(Get-Date).AddDays(-30)}} -MaxEvents 150 -ErrorAction Stop |"
                                " Select-Object @{n='Time';e={$_.TimeCreated.ToString('o')}},Id,ProviderName,Message)|ConvertTo-Json -Depth 4 -Compress"))
            for item in values:
                item["Source"] = source
                events.append(item)
            result.findings.append(Finding(source, "已读取", f"{len(values)} 项，有界读取并非完整历史"))
        except (OSError, ValueError, TimeoutError) as exc:
            result.findings.append(Finding(source, "权限不足" if isinstance(exc, PermissionError) else "未获得记录/接口受限", type(exc).__name__))
    for event in sorted(events, key=lambda e: str(e.get("Time", "")), reverse=True)[:300]:
        result.findings.append(Finding(str(event.get("Time", "时间未知")), str(event.get("Source")),
                                       f"事件 {event.get('Id')} / {event.get('ProviderName')}：{str(event.get('Message', ''))[:1800]}"))
    result.recommendations = ["时间先后或相邻只是线索，不直接证明更新、驱动或软件安装导致故障。",
                              "日志缺失/轮转/访问受限会造成时间线不完整；驱动配置事件不是所有驱动安装的完整审计。Kernel-Power 仅说明异常关机，不证明电源损坏。"]
    progress(100, "时间线整理完成")
    return result
