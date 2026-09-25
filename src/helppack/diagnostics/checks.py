from __future__ import annotations

import os
import platform
import shutil
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import psutil

from ..redaction import redact_text
from .engine import ScanContext
from .models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
    RepairSuggestion,
    SafetyLevel,
    Severity,
)


def _result(
    check_id: str,
    category: str,
    name: str,
    status: DiagnosticStatus,
    evidence: list[Evidence],
    explanation: str,
    recommendations: list[str],
    *,
    severity: Severity = Severity.INFO,
    confidence: str = "中",
    repairs: list[RepairSuggestion] | None = None,
) -> DiagnosticResult:
    raw = "\n".join(f"{item.label}: {item.value}" for item in evidence)
    repairs = repairs or []
    return DiagnosticResult(
        check_id=check_id,
        category=category,
        display_name=name,
        status=status,
        severity=severity,
        evidence=evidence,
        explanation=explanation,
        confidence=confidence,
        recommendations=recommendations,
        supports_rollback=any(item.rollback for item in repairs),
        redacted_raw=redact_text(raw),
        repair_suggestions=repairs,
    )


class PerformanceCheck:
    check_id = "performance.resources"
    display_name = "资源占用与高占用进程（2 秒采样）"
    categories = frozenset({"系统卡顿"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        sample_seconds = 2.0
        net_before = psutil.net_io_counters()
        disk_before = psutil.disk_io_counters()
        processes: list[psutil.Process] = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                proc.cpu_percent(None)
                processes.append(proc)
            except (psutil.Error, OSError):
                continue
        psutil.cpu_percent(None)
        context.wait(sample_seconds)
        cpu = psutil.cpu_percent(None)
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        net_after = psutil.net_io_counters()
        disk_after = psutil.disk_io_counters()
        top: list[tuple[float, str, int, float]] = []
        for proc in processes:
            try:
                name = proc.name()
                if proc.pid == 0 or name.lower() == "system idle process":
                    continue
                top.append((proc.cpu_percent(None), name, proc.pid, proc.memory_info().rss / 1024**2))
            except (psutil.Error, OSError):
                continue
        top.sort(reverse=True)
        top_text = "；".join(f"{name} (PID {pid}) CPU {value:.1f}% / 内存 {rss:.0f} MB" for value, name, pid, rss in top[:8]) or "没有可读取的进程样本"
        sent = max(0, net_after.bytes_sent - net_before.bytes_sent)
        received = max(0, net_after.bytes_recv - net_before.bytes_recv)
        disk_read = max(0, (disk_after.read_bytes if disk_after else 0) - (disk_before.read_bytes if disk_before else 0))
        disk_write = max(0, (disk_after.write_bytes if disk_after else 0) - (disk_before.write_bytes if disk_before else 0))
        uptime_seconds = max(0, time.time() - psutil.boot_time())
        status = DiagnosticStatus.NOTICE if cpu >= 90 or memory.percent >= 90 else DiagnosticStatus.NORMAL
        severity = Severity.MEDIUM if status == DiagnosticStatus.NOTICE else Severity.INFO
        evidence = [
            Evidence("采样时长", f"{sample_seconds:.1f} 秒"),
            Evidence("CPU 平均占用", f"{cpu:.1f}%"),
            Evidence("内存占用", f"{memory.percent:.1f}%（可用 {memory.available / 1024**3:.1f} GB）"),
            Evidence("分页使用", f"{swap.percent:.1f}%"),
            Evidence("采样期网络流量", f"发送 {sent / 1024:.1f} KB，接收 {received / 1024:.1f} KB"),
            Evidence("采样期磁盘活动", f"读取 {disk_read / 1024:.1f} KB，写入 {disk_write / 1024:.1f} KB"),
            Evidence("系统运行时间", f"{uptime_seconds / 3600:.1f} 小时"),
            Evidence("高占用进程样本", top_text),
        ]
        return [_result(
            self.check_id, "系统卡顿", self.display_name, status, evidence,
            "这是短时间采样，只能反映扫描期间的状态；单个进程短暂升高不等于它就是故障原因。",
            ["问题出现时可再次扫描，对比多次结果。"], severity=severity, confidence="中（短时采样）"
        )]


class DiskAndTempCheck:
    check_id = "performance.storage"
    display_name = "磁盘空间与临时目录"
    categories = frozenset({"系统卡顿", "软件或浏览器异常", "Windows更新问题", "电池或磁盘健康"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        rows: list[str] = []
        low = False
        for part in psutil.disk_partitions(all=False):
            context.ensure_not_cancelled()
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (OSError, PermissionError):
                continue
            free_gb = usage.free / 1024**3
            free_percent = 100 - usage.percent
            rows.append(f"{part.device or part.mountpoint}：剩余 {free_gb:.1f} GB（{free_percent:.1f}%）")
            if os.environ.get("SystemDrive", "C:").upper() in part.mountpoint.upper() and (free_gb < 15 or free_percent < 10):
                low = True
        temp_evidence = []
        for value in {os.environ.get("TEMP", ""), os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Temp")}:
            if value:
                temp_evidence.append(_bounded_directory_size(Path(value), context))
        status = DiagnosticStatus.NOTICE if low else DiagnosticStatus.NORMAL
        return [_result(
            self.check_id, "系统卡顿", self.display_name, status,
            [Evidence("磁盘剩余空间", "\n".join(rows) or "没有可读取的分区"), Evidence("临时目录估算", "\n".join(temp_evidence) or "数据不可用")],
            "空间阈值用于提醒；空间偏低可能影响更新、缓存和分页，但不能单独证明是当前故障原因。",
            ["系统盘空间偏低时，优先使用 Windows“存储”设置检查可清理内容。"] if low else ["当前未发现明显的系统盘低空间提醒。"],
            severity=Severity.MEDIUM if low else Severity.INFO, confidence="高（容量）；中（临时目录估算）"
        )]


class StartupCheck:
    check_id = "startup.entries"
    display_name = "启动项、启动文件夹和自动服务"
    categories = frozenset({"系统卡顿"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        if platform.system() != "Windows":
            raise NotImplementedError
        entries, repairs = _registry_startup_entries()
        folders = _startup_folder_entries()
        services: list[str] = []
        try:
            for service in psutil.win_service_iter():
                context.ensure_not_cancelled()
                try:
                    info = service.as_dict()
                    binpath = str(info.get("binpath", "")).lower()
                    windows_root = os.environ.get("WINDIR", r"C:\Windows").lower()
                    if info.get("start_type") == "automatic" and binpath and windows_root not in binpath and "\\windows\\" not in binpath:
                        services.append(str(info.get("display_name") or info.get("name")))
                except (psutil.Error, OSError):
                    continue
        except (AttributeError, OSError):
            services = []
        evidence = [
            Evidence("注册表启动项", "；".join(entries) if entries else "未发现可读取的条目"),
            Evidence("启动文件夹", "；".join(folders) if folders else "未发现文件"),
            Evidence("自动启动服务", "；".join(services[:30]) if services else "未发现可读取的第三方条目"),
        ]
        return [_result(
            self.check_id, "系统卡顿", self.display_name, DiagnosticStatus.NORMAL, evidence,
            "发现启动项只说明它可能随登录或开机运行，不代表它有害或导致卡顿。",
            ["如需减少启动项，只选择你明确认识且不需要自动运行的用户启动项。"],
            confidence="高（枚举结果）；低（与故障的因果关系）", repairs=repairs
        )]


class ScheduledTaskCheck:
    check_id = "startup.scheduled_tasks"
    display_name = "登录或开机计划任务"
    categories = frozenset({"系统卡顿"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.Triggers.CimClass.CimClassName -match 'Logon|Boot' } | "
            "Select-Object -First 60 TaskName,TaskPath,State | ConvertTo-Json -Compress"
        )
        command = context.runner.powershell_json(script, timeout=15)
        return [_command_json_result(command, self.check_id, "系统卡顿", self.display_name, "计划任务", "计划任务存在不代表异常；部分系统任务不会在普通权限下完整显示。")]


class BrowserCheck:
    check_id = "software.browser"
    display_name = "常见浏览器状态"
    categories = frozenset({"软件或浏览器异常"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        names = {"chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox", "brave.exe": "Brave"}
        running: dict[str, int] = {name: 0 for name in names.values()}
        for proc in psutil.process_iter(["name"]):
            context.ensure_not_cancelled()
            try:
                key = (proc.info.get("name") or "").lower()
                if key in names:
                    running[names[key]] += 1
            except (psutil.Error, OSError):
                continue
        text = "；".join(f"{name}：{count} 个进程" for name, count in running.items())
        versions = _browser_versions()
        locks = _browser_lock_markers()
        return [_result(
            self.check_id, "软件或浏览器异常", self.display_name, DiagnosticStatus.NORMAL,
            [Evidence("已安装版本", "；".join(versions) if versions else "未从卸载注册表识别到常见浏览器"), Evidence("运行中的浏览器", text), Evidence("配置锁标记", "；".join(locks) if locks else "未发现已知锁标记")],
            "多进程是现代浏览器的正常设计；检测到进程或锁标记不能单独证明进程残留或配置损坏。",
            ["如浏览器无法退出，可在任务管理器中确认窗口已关闭后再检查残留进程。"], confidence="高（进程计数）；低（故障判断）"
        )]


class CrashEventCheck:
    check_id = "software.crash_events"
    display_name = "最近的应用崩溃与 WER 事件"
    categories = frozenset({"软件或浏览器异常"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "$since=(Get-Date).AddDays(-7); Get-WinEvent -FilterHashtable @{LogName='Application';StartTime=$since;Id=1000,1001} "
            "-MaxEvents 30 -ErrorAction Stop | Select-Object TimeCreated,Id,ProviderName,LevelDisplayName,Message | ConvertTo-Json -Depth 3 -Compress"
        )
        command = context.runner.powershell_json(script, timeout=20)
        result = _command_json_result(command, self.check_id, "软件或浏览器异常", self.display_name, "最近事件", "事件日志是排查证据；崩溃模块或单条事件不能单独证明根本原因。")
        result.evidence.append(Evidence("WER 记录元数据", _wer_metadata()))
        return [result]


class NetworkCheck:
    check_id = "network.connectivity"
    display_name = "网络配置、DNS 与 HTTPS"
    categories = frozenset({"网络或Wi-Fi异常", "软件或浏览器异常"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        interfaces: list[str] = []
        stats = psutil.net_if_stats()
        for name, addresses in psutil.net_if_addrs().items():
            context.ensure_not_cancelled()
            state = "已连接" if stats.get(name) and stats[name].isup else "未连接"
            values = [item.address for item in addresses if item.family in (socket.AF_INET, socket.AF_INET6)]
            interfaces.append(f"{name}：{state}，地址 {'、'.join(values) if values else '无'}")
        dns = "正常"
        https = "正常"
        try:
            socket.getaddrinfo("www.microsoft.com", 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            dns = f"失败（{type(exc).__name__}）"
        context.ensure_not_cancelled()
        try:
            request = urllib.request.Request("https://www.microsoft.com/", method="HEAD", headers={"User-Agent": "HelpPack/0.2"})
            with urllib.request.urlopen(request, timeout=6, context=ssl.create_default_context()) as response:
                https = f"成功（HTTP {response.status}）"
        except (OSError, TimeoutError, ValueError, ssl.SSLError, urllib.error.URLError) as exc:
            https = f"失败（{type(exc).__name__}）"
        status = DiagnosticStatus.NORMAL if dns == "正常" and https.startswith("成功") else DiagnosticStatus.NOTICE
        raw_interfaces = "\n".join(interfaces) or "没有网络接口数据"
        return [_result(
            self.check_id, "网络或Wi-Fi异常", self.display_name, status,
            [Evidence("网络接口", redact_text(raw_interfaces)), Evidence("DNS 解析", dns), Evidence("HTTPS 连接", https)],
            "DNS 和 HTTPS 分别测试，任一失败都只代表本次指定目标测试失败，不等同于整个互联网不可用。",
            ["结合适配器、代理、DNS 和系统时间结果继续排查。"], severity=Severity.MEDIUM if status == DiagnosticStatus.NOTICE else Severity.INFO,
            confidence="中（单次连接测试）"
        )]


class ProxyHostsCheck:
    check_id = "network.proxy_hosts"
    display_name = "当前用户代理、PAC 与 Hosts"
    categories = frozenset({"网络或Wi-Fi异常", "软件或浏览器异常"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        if platform.system() != "Windows":
            raise NotImplementedError
        proxy, repairs = _read_proxy()
        hosts_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
        redirects: list[str] = []
        try:
            for line in hosts_path.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.lstrip("\ufeff").strip()
                if stripped and not stripped.startswith("#"):
                    redirects.append(stripped)
        except PermissionError:
            return [_result(self.check_id, "网络或Wi-Fi异常", self.display_name, DiagnosticStatus.PERMISSION_DENIED, [Evidence("Hosts", "权限不足")], "无法读取 Hosts 文件。", ["可由管理员人工检查。"], confidence="高")]
        suspicious = [line for line in redirects if "localhost" not in line.lower()]
        status = DiagnosticStatus.NOTICE if proxy["enabled"] or proxy["pac"] or suspicious else DiagnosticStatus.NORMAL
        evidence = [
            Evidence("用户代理", proxy["display"]),
            Evidence("PAC", proxy["pac"] or "未配置"),
            Evidence("WinHTTP 默认代理", _winhttp_proxy()),
            Evidence("Hosts 非默认重定向", redact_text("\n".join(suspicious[:30])) if suspicious else "未发现"),
        ]
        return [_result(
            self.check_id, "网络或Wi-Fi异常", self.display_name, status, evidence,
            "代理、PAC 或 Hosts 自定义记录可能完全合法；这里只提示配置存在，不判定为恶意或故障。",
            ["确认这些配置是否由你、单位网络或可信软件设置。"], severity=Severity.LOW if status == DiagnosticStatus.NOTICE else Severity.INFO,
            confidence="高（配置存在性）；低（是否异常）", repairs=repairs
        )]


class DeviceServiceCheck:
    check_id = "devices.services"
    display_name = "音频、蓝牙与打印服务"
    categories = frozenset({"声音问题", "蓝牙问题", "打印机问题"})

    SERVICE_MAP: ClassVar[dict[str, str]] = {"Audiosrv": "Windows 音频", "AudioEndpointBuilder": "音频终结点", "bthserv": "蓝牙支持", "Spooler": "打印后台处理"}

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        if platform.system() != "Windows" or not hasattr(psutil, "win_service_get"):
            raise NotImplementedError
        rows: list[str] = []
        stopped: list[str] = []
        for service_name, display in self.SERVICE_MAP.items():
            try:
                info = psutil.win_service_get(service_name).as_dict()
                state = str(info.get("status", "unknown"))
                rows.append(f"{display}：{state}")
                if state != "running":
                    stopped.append(display)
            except psutil.NoSuchProcess:
                rows.append(f"{display}：系统未提供此服务")
            except psutil.AccessDenied:
                rows.append(f"{display}：权限不足")
        status = DiagnosticStatus.NOTICE if stopped else DiagnosticStatus.NORMAL
        return [_result(
            self.check_id, "设备", self.display_name, status, [Evidence("服务状态", "；".join(rows))],
            "服务未运行可能与设备不可用有关，但也可能是按需启动或该硬件不存在。",
            ["在对应 Windows 设置页确认设备存在、已启用且被选为输出或目标设备。"], confidence="中"
        )]


class PnpDeviceCheck:
    check_id = "devices.pnp"
    display_name = "PnP 设备状态"
    categories = frozenset({"声音问题", "蓝牙问题", "打印机问题"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "$classes='AudioEndpoint','MEDIA','Bluetooth','Printer'; Get-PnpDevice -ErrorAction Stop | "
            "Where-Object { $classes -contains $_.Class } | Select-Object -First 80 Class,FriendlyName,Status,Problem | ConvertTo-Json -Compress"
        )
        command = context.runner.powershell_json(script, timeout=20)
        return [_command_json_result(command, self.check_id, "设备", self.display_name, "设备", "设备状态或错误码是证据；驱动日期较旧本身不能证明驱动故障。")]


class UpdateCheck:
    check_id = "windows_update.basic"
    display_name = "Windows Update 基础状态"
    categories = frozenset({"Windows更新问题"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        services: list[str] = []
        if platform.system() == "Windows" and hasattr(psutil, "win_service_get"):
            for name in ("wuauserv", "BITS", "cryptsvc"):
                try:
                    info = psutil.win_service_get(name).as_dict()
                    services.append(f"{name}：{info.get('status', 'unknown')} / {info.get('start_type', 'unknown')}")
                except psutil.Error:
                    services.append(f"{name}：无法读取")
        pending = _pending_reboot()
        status = DiagnosticStatus.NOTICE if pending else DiagnosticStatus.NORMAL
        return [_result(
            self.check_id, "Windows更新问题", self.display_name, status,
            [Evidence("更新相关服务", "；".join(services) or "不支持"), Evidence("等待重启标记", "存在" if pending else "未发现已知标记")],
            "这里只检查基础服务和已知重启标记，不会安装更新，也没有运行 SFC 或 DISM。",
            ["如更新持续失败，可记录错误代码后使用 Windows Update 设置或官方支持渠道。"], confidence="中"
        )]


class NetworkConfigurationCheck:
    check_id = "network.configuration"
    display_name = "DHCP、默认网关、DNS 服务器与 Wi-Fi 适配器"
    categories = frozenset({"网络或Wi-Fi异常"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "Get-NetIPConfiguration -ErrorAction Stop | ForEach-Object { [pscustomobject]@{"
            "Alias=$_.InterfaceAlias;Status=$_.NetAdapter.Status;Dhcp=$_.NetIPv4Interface.Dhcp;"
            "IPv4=@($_.IPv4Address.IPAddress);IPv6=@($_.IPv6Address.IPAddress);"
            "Gateway=@($_.IPv4DefaultGateway.NextHop);DNS=@($_.DNSServer.ServerAddresses);"
            "GatewayReachable=if($_.IPv4DefaultGateway.NextHop){Test-Connection -ComputerName $_.IPv4DefaultGateway.NextHop -Count 1 -Quiet -ErrorAction SilentlyContinue}else{$null};"
            "Description=$_.InterfaceDescription} } | ConvertTo-Json -Depth 4 -Compress"
        )
        command = context.runner.powershell_json(script, timeout=20)
        result = _command_json_result(
            command, self.check_id, "网络或Wi-Fi异常", self.display_name, "结构化网络配置",
            "配置存在不等于异常；Wi-Fi 名称不写入报告，网关、DNS 和接口地址会自动脱敏。"
        )
        result.evidence.append(Evidence("系统时间", datetime.now().astimezone().isoformat(timespec="seconds")))
        return [result]


class PrinterCheck:
    check_id = "devices.printers"
    display_name = "打印机、默认打印机与队列"
    categories = frozenset({"打印机问题"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "$items=@(); Get-Printer -ErrorAction Stop | ForEach-Object { $count=0; "
            "try { $count=@(Get-PrintJob -PrinterName $_.Name -ErrorAction Stop).Count } catch {} ; "
            "$items += [pscustomobject]@{Name=$_.Name;DriverName=$_.DriverName;PortName=$_.PortName;"
            "PrinterStatus=$_.PrinterStatus;QueueCount=$count} }; $items | ConvertTo-Json -Compress"
        )
        command = context.runner.powershell_json(script, timeout=20)
        result = _command_json_result(command, self.check_id, "打印机问题", self.display_name, "已安装打印机", "队列数量是当前快照；不会自动取消任何打印任务。")
        result.evidence.append(Evidence("默认打印机", _default_printer()))
        return [result]


class UpdateHistoryCheck:
    check_id = "windows_update.history"
    display_name = "最近更新记录、失败代码与日志能力"
    categories = frozenset({"Windows更新问题"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "$since=(Get-Date).AddDays(-30); Get-WinEvent -FilterHashtable @{LogName='System';"
            "ProviderName='Microsoft-Windows-WindowsUpdateClient';StartTime=$since} -MaxEvents 40 -ErrorAction Stop | "
            "Select-Object TimeCreated,Id,LevelDisplayName,Message | ConvertTo-Json -Depth 3 -Compress"
        )
        command = context.runner.powershell_json(script, timeout=20)
        result = _command_json_result(command, self.check_id, "Windows更新问题", self.display_name, "更新事件", "事件记录可包含成功和失败；事件存在不等于当前更新仍失败。")
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        logs = []
        for name in ("Logs/CBS/CBS.log", "Logs/DISM/dism.log", "WindowsUpdate.log"):
            path = windir / name
            try:
                logs.append(f"{path.name}：{'可读' if path.is_file() and os.access(path, os.R_OK) else '不存在或不可读'}")
            except OSError:
                logs.append(f"{path.name}：无法检查")
        result.evidence.extend(
            [
                Evidence("日志读取能力", "；".join(logs)),
                Evidence("SFC 只读验证能力", "命令可用（未执行）" if shutil.which("sfc.exe") else "命令不可用"),
                Evidence("DISM 扫描能力", "命令可用（未执行）" if shutil.which("dism.exe") else "命令不可用"),
            ]
        )
        result.recommendations.append("发布前验证没有运行 sfc /verifyonly 或 DISM /ScanHealth，避免未经确认的长时间扫描。")
        return [result]


class ReliabilityCheck:
    check_id = "reliability.events"
    display_name = "蓝屏、异常关机与硬件错误事件"
    categories = frozenset({"蓝屏或异常重启"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "$since=(Get-Date).AddDays(-30); Get-WinEvent -FilterHashtable @{LogName='System';StartTime=$since;Id=41,1001,18,19,20,46} "
            "-MaxEvents 40 -ErrorAction Stop | Select-Object TimeCreated,Id,ProviderName,LevelDisplayName,Message | ConvertTo-Json -Depth 3 -Compress"
        )
        command = context.runner.powershell_json(script, timeout=20)
        result = _command_json_result(command, self.check_id, "蓝屏或异常重启", self.display_name, "最近事件", "Kernel-Power 41 只表示系统未正常关机，不等同于已经确认电源故障；事件或模块名也不能单独证明根因。")
        dump_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Minidump"
        try:
            dumps = sorted(dump_dir.glob("*.dmp"), key=lambda item: item.stat().st_mtime, reverse=True)
            dump_text = f"{len(dumps)} 个；最近：{datetime.fromtimestamp(dumps[0].stat().st_mtime, tz=UTC).astimezone().isoformat(timespec='seconds')}" if dumps else "未发现"
        except PermissionError:
            dump_text = "权限不足"
        result.evidence.append(Evidence("小型转储", dump_text))
        return [result]


class BatteryDiskHealthCheck:
    check_id = "health.battery_disk"
    display_name = "电池与磁盘健康摘要"
    categories = frozenset({"电池或磁盘健康"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        battery = psutil.sensors_battery()
        battery_text = "未检测到电池" if battery is None else f"电量 {battery.percent:.0f}% / {'接通电源' if battery.power_plugged else '使用电池'}"
        script = "Get-PhysicalDisk -ErrorAction Stop | Select-Object FriendlyName,MediaType,HealthStatus,OperationalStatus,Size | ConvertTo-Json -Compress"
        command = context.runner.powershell_json(script, timeout=15)
        disk_result = _command_json_result(command, self.check_id, "电池或磁盘健康", self.display_name, "磁盘", "SMART 或 HealthStatus 显示正常也不能保证磁盘绝对安全；USB、RAID 和部分厂商驱动可能不提供数据。")
        disk_result.evidence.insert(0, Evidence("电池", battery_text))
        disk_result.evidence.insert(1, Evidence("电池设计/满充容量与循环次数", "标准 psutil 接口不提供；厂商固件或更高权限接口可用性不确定"))
        disk_result.evidence.append(Evidence("温度", "当前 Windows 标准接口无法可靠覆盖本机硬件，第一版不支持"))
        disk_result.recommendations.append("如出现异响、读写错误或健康异常，优先备份重要数据。")
        return [disk_result]


def default_checks() -> list[Any]:
    return [
        PerformanceCheck(),
        DiskAndTempCheck(),
        StartupCheck(),
        ScheduledTaskCheck(),
        BrowserCheck(),
        CrashEventCheck(),
        NetworkCheck(),
        ProxyHostsCheck(),
        NetworkConfigurationCheck(),
        DeviceServiceCheck(),
        PnpDeviceCheck(),
        PrinterCheck(),
        UpdateCheck(),
        UpdateHistoryCheck(),
        ReliabilityCheck(),
        BatteryDiskHealthCheck(),
    ]


def _bounded_directory_size(path: Path, context: ScanContext, limit: int = 20_000) -> str:
    total = 0
    count = 0
    skipped = 0
    try:
        for root, dirs, files in os.walk(path, followlinks=False):
            context.ensure_not_cancelled()
            dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()]
            for name in files:
                if count >= limit:
                    return f"{path.name or path}: 至少 {count} 个文件 / {total / 1024**2:.1f} MB（达到统计上限）"
                try:
                    total += (Path(root) / name).stat().st_size
                    count += 1
                except (OSError, PermissionError):
                    skipped += 1
    except (OSError, PermissionError):
        return f"{path.name or path}: 权限不足或不可用"
    suffix = f"，跳过 {skipped} 项" if skipped else ""
    return f"{path.name or path}: {count} 个文件 / {total / 1024**2:.1f} MB{suffix}"


def _registry_startup_entries() -> tuple[list[str], list[RepairSuggestion]]:
    import winreg

    entries: list[str] = []
    repairs: list[RepairSuggestion] = []
    paths = [r"Software\Microsoft\Windows\CurrentVersion\Run", r"Software\Microsoft\Windows\CurrentVersion\RunOnce"]
    for hive, hive_name in ((winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
        for path in paths:
            try:
                with winreg.OpenKey(hive, path) as key:
                    for index in range(winreg.QueryInfoKey(key)[1]):
                        name, value, _kind = winreg.EnumValue(key, index)
                        entries.append(f"{hive_name}\\{Path(path).name}\\{name} → {Path(str(value).strip(chr(34))).name or '命令'}")
                        if hive_name == "HKCU":
                            repairs.append(RepairSuggestion(
                                action_id="disable_hkcu_startup",
                                display_name=f"禁用用户启动项：{name}",
                                target={"key_path": path, "value_name": name},
                                safety_level=SafetyLevel.L1,
                                requires_admin=False,
                                impact="该程序将不再随当前用户登录自动启动；不会删除程序文件。",
                                operation_preview=f"备份后删除 HKCU\\{path} 中名为 {name} 的值",
                                rollback="从 HelpPack 备份恢复原值及注册表类型。",
                            ))
            except OSError:
                continue
    return entries, repairs


def _browser_versions() -> list[str]:
    if platform.system() != "Windows":
        return []
    import winreg

    products = ("Google Chrome", "Microsoft Edge", "Mozilla Firefox", "Brave")
    found: list[str] = []
    uninstall = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, uninstall, 0, winreg.KEY_READ | view) as root:
                    for index in range(winreg.QueryInfoKey(root)[0]):
                        try:
                            with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                                name = str(winreg.QueryValueEx(key, "DisplayName")[0])
                                if not any(product.lower() in name.lower() for product in products):
                                    continue
                                try:
                                    version = str(winreg.QueryValueEx(key, "DisplayVersion")[0])
                                except OSError:
                                    version = "版本无法读取"
                                row = f"{name} {version}"
                                if row not in found:
                                    found.append(row)
                        except OSError:
                            continue
            except OSError:
                continue
    return found


def _browser_lock_markers() -> list[str]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roaming = Path(os.environ.get("APPDATA", ""))
    candidates = {
        "Chrome": [local / "Google/Chrome/User Data/SingletonLock"],
        "Edge": [local / "Microsoft/Edge/User Data/SingletonLock"],
        "Brave": [local / "BraveSoftware/Brave-Browser/User Data/SingletonLock"],
    }
    firefox_root = roaming / "Mozilla/Firefox/Profiles"
    try:
        candidates["Firefox"] = [path / "parent.lock" for path in firefox_root.iterdir() if path.is_dir()]
    except (OSError, PermissionError):
        candidates["Firefox"] = []
    rows = []
    for name, paths in candidates.items():
        count = sum(1 for path in paths if path.exists())
        if count:
            rows.append(f"{name}：发现 {count} 个锁标记")
    return rows


def _wer_metadata() -> str:
    roots = [
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft/Windows/WER/ReportArchive",
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft/Windows/WER/ReportQueue",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/WER/ReportArchive",
    ]
    count = 0
    latest = 0.0
    denied = 0
    for root in roots:
        try:
            for path in root.glob("*/*.wer"):
                if count >= 200:
                    break
                try:
                    latest = max(latest, path.stat().st_mtime)
                    count += 1
                except (OSError, PermissionError):
                    denied += 1
        except (OSError, PermissionError):
            denied += 1
    if count:
        suffix = "（达到统计上限）" if count >= 200 else ""
        return f"发现 {count} 条元数据{suffix}；最近时间 {datetime.fromtimestamp(latest, tz=UTC).astimezone().isoformat(timespec='seconds')}"
    return "权限不足" if denied else "未发现 WER 记录"


def _winhttp_proxy() -> str:
    if platform.system() != "Windows":
        return "当前系统不支持"
    try:
        import ctypes
        from ctypes import wintypes

        class ProxyInfo(ctypes.Structure):
            _fields_ = [("access_type", wintypes.DWORD), ("proxy", ctypes.c_void_p), ("bypass", ctypes.c_void_p)]

        info = ProxyInfo()
        winhttp = ctypes.WinDLL("winhttp.dll", use_last_error=True)
        function = winhttp.WinHttpGetDefaultProxyConfiguration
        function.argtypes = [ctypes.POINTER(ProxyInfo)]
        function.restype = wintypes.BOOL
        if not function(ctypes.byref(info)):
            error = ctypes.get_last_error()
            return f"无法读取（错误 {error}）"
        proxy = ctypes.wstring_at(info.proxy) if info.proxy else ""
        bypass = ctypes.wstring_at(info.bypass) if info.bypass else ""
        try:
            if info.proxy:
                ctypes.windll.kernel32.GlobalFree(info.proxy)
            if info.bypass:
                ctypes.windll.kernel32.GlobalFree(info.bypass)
        finally:
            pass
        access = {0: "系统默认", 1: "直连", 3: "指定代理", 4: "自动代理"}.get(info.access_type, f"类型 {info.access_type}")
        details = f"{access}；{proxy or '无代理服务器'}；绕过 {bypass or '无'}"
        return redact_text(details)
    except (AttributeError, OSError, ValueError):
        return "接口不可用"


def _default_printer() -> str:
    if platform.system() != "Windows":
        return "当前系统不支持"
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Windows") as key:
            value = str(winreg.QueryValueEx(key, "Device")[0])
            return redact_text(value.split(",", 1)[0] or "未设置")
    except OSError:
        return "未设置或无法读取"


def _startup_folder_entries() -> list[str]:
    folders = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs/StartUp",
    ]
    result: list[str] = []
    for folder in folders:
        try:
            result.extend(item.name for item in folder.iterdir() if item.is_file())
        except (OSError, PermissionError):
            continue
    return result


def _read_proxy() -> tuple[dict[str, Any], list[RepairSuggestion]]:
    import winreg

    path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    values: dict[str, Any] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            for name in ("ProxyEnable", "ProxyServer", "AutoConfigURL"):
                try:
                    values[name] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    pass
    except OSError:
        pass
    enabled = bool(values.get("ProxyEnable"))
    server = str(values.get("ProxyServer", ""))
    pac = str(values.get("AutoConfigURL", ""))
    repairs: list[RepairSuggestion] = []
    if enabled or pac:
        repairs.append(RepairSuggestion(
            action_id="reset_user_proxy",
            display_name="重置当前用户代理和 PAC",
            target={"key_path": path},
            safety_level=SafetyLevel.L2,
            requires_admin=False,
            impact="可能立即改变浏览器及部分应用的联网方式；单位网络或代理软件可能因此无法连接。",
            operation_preview="备份并更新 HKCU Internet Settings 的 ProxyEnable、ProxyServer 和 AutoConfigURL",
            rollback="从 HelpPack 备份恢复这三个值及其注册表类型。",
        ))
    return {"enabled": enabled, "display": f"{'启用' if enabled else '未启用'}；{redact_text(server) if server else '无服务器'}", "pac": redact_text(pac)}, repairs


def _pending_reboot() -> bool:
    if platform.system() != "Windows":
        return False
    import winreg

    paths = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
    ]
    for path in paths:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path):
                return True
        except OSError:
            continue
    return False


def _command_json_result(command, check_id: str, category: str, name: str, label: str, limitation: str) -> DiagnosticResult:
    if command.timed_out:
        return _result(check_id, category, name, DiagnosticStatus.UNKNOWN, [Evidence("检查状态", "超时")], "检查超时，数据不足，无法判断。", ["可稍后重试。"], confidence="高（超时状态）")
    if command.permission_denied:
        return _result(check_id, category, name, DiagnosticStatus.PERMISSION_DENIED, [Evidence("检查状态", "权限不足")], "当前权限不足，未读取到该数据。", ["如确有需要，可由管理员人工检查。"], confidence="高（权限状态）")
    if command.unsupported:
        return _result(check_id, category, name, DiagnosticStatus.UNSUPPORTED, [Evidence("检查状态", "命令或模块不可用")], "当前 Windows 版本或组件不支持此检查。", ["不需要为了此项检查安装未知工具。"], confidence="高（支持状态）")
    if command.returncode != 0:
        return _result(check_id, category, name, DiagnosticStatus.UNKNOWN, [Evidence("检查状态", f"失败（退出码 {command.returncode}）")], "检查失败，不等同于发现异常。", ["将此状态写入求助包，供技术人员继续判断。"], confidence="高（失败状态）")
    try:
        value = command.json_value()
    except (ValueError, TypeError):
        return _result(check_id, category, name, DiagnosticStatus.UNKNOWN, [Evidence("检查状态", "返回数据格式无法识别")], "系统返回了无法结构化读取的数据；不会解析本地化文本来猜测结果。", ["可稍后重试。"], confidence="高（格式状态）")
    if not value:
        return _result(check_id, category, name, DiagnosticStatus.NORMAL, [Evidence(label, "未发现相关记录")], limitation, ["当前没有发现相关证据。"], confidence="中")
    redacted = redact_text(str(value))
    return _result(check_id, category, name, DiagnosticStatus.NOTICE, [Evidence(label, redacted[:12000])], limitation, ["展开证据并结合发生时间判断相关性。"], severity=Severity.LOW, confidence="中")
