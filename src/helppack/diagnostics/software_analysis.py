from __future__ import annotations

from pathlib import Path

import psutil

from .investigation import Finding, Investigation, ps_literal, query, readable
from .runner import CommandRunner

SCENARIOS = ("无法启动", "闪退", "无响应", "安装失败")


def running_programs() -> list[tuple[str, str, int]]:
    found = []
    for process in psutil.process_iter(["pid", "name", "exe"]):
        try:
            path = process.info.get("exe")
            if path and path.casefold().endswith(".exe"):
                found.append((str(process.info["name"]), path, process.pid))
        except (psutil.Error, OSError):
            continue
    return sorted(found)[:250]


def analyze_software(raw_path: str, scenario: str, cancel, progress, runner=None) -> Investigation:
    path = Path(raw_path).absolute()
    if str(path).startswith("\\\\"):
        raise ValueError("请选择本机 EXE，不读取网络共享中的程序")
    if scenario not in SCENARIOS or path.suffix.lower() != ".exe" or not path.is_file() or path.is_symlink():
        raise ValueError("请选择存在的 EXE 和支持的故障场景")
    literal = ps_literal(str(path))
    name = ps_literal(path.name)
    runner = runner or CommandRunner()
    result = Investigation("软件专项诊断", f"{path.name}：{scenario}")
    def collect(percent, title, script):
        if cancel.is_set():
            raise InterruptedError("已取消专项检查")
        progress(percent, title)
        try:
            value = query(runner, script, 25)
            state = "部分无法验证" if isinstance(value, list) and any(isinstance(item, dict) and item.get("State") == "无法读取" for item in value) else "已读取"
            result.findings.append(Finding(title, state, readable(value)))
        except (OSError, ValueError, TimeoutError) as exc:
            result.findings.append(Finding(title, "权限不足" if isinstance(exc, PermissionError) else "无法验证", type(exc).__name__))
    collect(10, "版本与安装路径",
            f"$f=Get-Item -LiteralPath {literal};"
            "[pscustomobject]@{Path=$f.FullName;Version=$f.VersionInfo.FileVersion;Product=$f.VersionInfo.ProductName}|ConvertTo-Json -Compress")
    collect(20, "文件签名与发布者",
            f"$s=Get-AuthenticodeSignature -LiteralPath {literal};"
            "[pscustomobject]@{Signature=[string]$s.Status;Publisher=if($s.SignerCertificate){$s.SignerCertificate.Subject}else{'未知'}}|ConvertTo-Json -Compress")
    collect(30, "进程与无响应线索",
            f"@(Get-Process | Where-Object {{$_.Path -eq {literal}}} | Select-Object Id,Responding,CPU,WorkingSet64)|ConvertTo-Json -Compress")
    ids = "11707,11708" if scenario == "安装失败" else "1000,1001,1002,1026"
    collect(50, "相关应用事件（最近七天，有界匹配）",
            f"@(Get-WinEvent -FilterHashtable @{{LogName='Application';Id=@({ids});StartTime=(Get-Date).AddDays(-7)}} -MaxEvents 300 -ErrorAction SilentlyContinue |"
            f" Where-Object {{$_.Message -and $_.Message.IndexOf({name},[StringComparison]::OrdinalIgnoreCase) -ge 0}} |"
            " Select-Object -First 20 TimeCreated,Id,ProviderName,Message)|ConvertTo-Json -Depth 4 -Compress")
    collect(70, "常见运行库存在性（不是健康证明）",
            "$roots=@('HKLM:\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64','HKLM:\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x86',"
            "'HKLM:\\SOFTWARE\\Microsoft\\NET Framework Setup\\NDP\\v4\\Full');"
            "@($roots|ForEach-Object {$p=Get-ItemProperty -LiteralPath $_ -ErrorAction SilentlyContinue;"
            "[pscustomobject]@{Runtime=$_;Registered=[bool]$p;Version=[string]$p.Version;Release=[string]$p.Release}})|ConvertTo-Json -Compress")
    collect(85, "可读取的拦截记录",
            f"@(foreach($log in @('Microsoft-Windows-Windows Defender/Operational','Microsoft-Windows-AppLocker/EXE and DLL')) {{"
            " try {"
            f" $events=@(Get-WinEvent -FilterHashtable @{{LogName=$log;StartTime=(Get-Date).AddDays(-7)}} -MaxEvents 150 -ErrorAction Stop);"
            f" $matched=@($events|Where-Object {{$_.Message -and $_.Message.IndexOf({name},[StringComparison]::OrdinalIgnoreCase) -ge 0}} |"
            " Select-Object -First 10 TimeCreated,Id,ProviderName,Message);"
            " [pscustomobject]@{Log=$log;State='已读取';Events=$matched}"
            " } catch { if($_.FullyQualifiedErrorId -like '*NoMatchingEventsFound*') {"
            " [pscustomobject]@{Log=$log;State='无匹配事件';Events=@()}"
            " } else { [pscustomobject]@{Log=$log;State='无法读取';ErrorType=$_.Exception.GetType().Name;Events=@()} } }"
            " })|ConvertTo-Json -Depth 6 -Compress")
    result.recommendations = ["记录依据是文件元数据、当前进程和可读取日志；文件签名有效不证明程序可信或运行正常。",
                              "日志按文件名关联，可能涉及同名程序，需核对时间、路径与事件；没有日志不证明未被拦截。",
                              "运行库注册存在不等于文件完整或与程序架构匹配；未解析全部依赖、安装器私有日志或第三方安全软件，不能据此排除依赖/拦截问题。",
                              {"无法启动": "先核对报错、签名、架构与同一时间拦截记录，不自动绕过安全软件。", "闪退": "核对相同时间的崩溃模块与异常码，模块出现不等于它是根因。",
                               "无响应": "Responding/CPU 是瞬时线索；等待和收集复现步骤，不自动结束进程。", "安装失败": "核对安装事件与错误码、剩余空间、权限和待重启状态，不自动卸载或重新运行安装器。"}[scenario]]
    progress(100, "专项检查完成")
    return result
