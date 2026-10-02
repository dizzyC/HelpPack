from __future__ import annotations

import os
import platform
import shutil
import socket
import ssl
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import psutil

from helppack.english import label as display_label
from helppack.english import text as msg

from ..plan_resources import tr
from ..redaction import redact_text
from .engine import ScanContext
from .models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
    RepairSuggestion,
    RollbackCapability,
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
    display_name = tr("performance_title")
    categories = frozenset({"系统卡顿"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        from .scenario_checks import continuous_performance
        return continuous_performance(context)


class DiskAndTempCheck:
    check_id = "performance.storage"
    display_name = msg('磁盘空间与临时目录')
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
            rows.append(msg('{0}：剩余 {1:.1f} GB（{2:.1f}%）', part.device or part.mountpoint, free_gb, free_percent))
            if os.environ.get("SystemDrive", "C:").upper() in part.mountpoint.upper() and (free_gb < 15 or free_percent < 10):
                low = True
        temp_evidence = []
        for value in {os.environ.get("TEMP", ""), os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Temp")}:
            if value:
                temp_evidence.append(_bounded_directory_size(Path(value), context))
        status = DiagnosticStatus.NOTICE if low else DiagnosticStatus.NORMAL
        return [_result(
            self.check_id, "系统卡顿", self.display_name, status,
            [Evidence(msg('磁盘剩余空间'), "\n".join(rows) or msg('没有可读取的分区')), Evidence(msg('临时目录估算'), "\n".join(temp_evidence) or msg('数据不可用'))],
            msg('空间阈值用于提醒；空间偏低可能影响更新、缓存和分页，但不能单独证明是当前故障原因。'),
            [msg('系统盘空间偏低时，优先使用 Windows“存储”设置检查可清理内容。')] if low else [msg('当前未发现明显的系统盘低空间提醒。')],
            severity=Severity.MEDIUM if low else Severity.INFO, confidence=msg('高（容量）；中（临时目录估算）')
        )]


class StartupCheck:
    check_id = "startup.entries"
    display_name = msg('启动项、启动文件夹和自动服务')
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
            Evidence(msg('注册表启动项'), "；".join(entries) if entries else msg('未发现可读取的条目')),
            Evidence(msg('启动文件夹'), "；".join(folders) if folders else msg('未发现文件')),
            Evidence(msg('自动启动服务'), "；".join(services[:30]) if services else msg('未发现可读取的第三方条目')),
        ]
        return [_result(
            self.check_id, "系统卡顿", self.display_name, DiagnosticStatus.NORMAL, evidence,
            msg('发现启动项只说明它可能随登录或开机运行，不代表它有害或导致卡顿。'),
            [msg('如需减少启动项，只选择你明确认识且不需要自动运行的用户启动项。')],
            confidence=msg('高（枚举结果）；低（与故障的因果关系）'), repairs=repairs
        )]


class ScheduledTaskCheck:
    check_id = "startup.scheduled_tasks"
    display_name = msg('登录或开机计划任务')
    categories = frozenset({"系统卡顿"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.Triggers.CimClass.CimClassName -match 'Logon|Boot' } | "
            "Select-Object -First 60 TaskName,TaskPath,State | ConvertTo-Json -Compress"
        )
        command = context.runner.powershell_json(script, timeout=15)
        return [_command_json_result(command, self.check_id, "系统卡顿", self.display_name, msg('计划任务'), msg('计划任务存在不代表异常；部分系统任务不会在普通权限下完整显示。'))]


class BrowserCheck:
    check_id = "software.browser"
    display_name = msg('常见浏览器状态')
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
        text = "；".join(msg('{0}：{1} 个进程', name, count) for name, count in running.items())
        versions = _browser_versions()
        locks = _browser_lock_markers()
        return [_result(
            self.check_id, "软件或浏览器异常", self.display_name, DiagnosticStatus.NORMAL,
            [Evidence(msg('已安装版本'), "；".join(versions) if versions else msg('未从卸载注册表识别到常见浏览器')), Evidence(msg('运行中的浏览器'), text), Evidence(msg('配置锁标记'), "；".join(locks) if locks else msg('未发现已知锁标记'))],
            msg('多进程是现代浏览器的正常设计；检测到进程或锁标记不能单独证明进程残留或配置损坏。'),
            [msg('如浏览器无法退出，可在任务管理器中确认窗口已关闭后再检查残留进程。')], confidence=msg('高（进程计数）；低（故障判断）')
        )]


class CrashEventCheck:
    check_id = "software.crash_events"
    display_name = msg('最近的应用崩溃与 WER 事件')
    categories = frozenset({"软件或浏览器异常"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "$since=(Get-Date).AddDays(-7); Get-WinEvent -FilterHashtable @{LogName='Application';StartTime=$since;Id=1000,1001} "
            "-MaxEvents 30 -ErrorAction Stop | Select-Object TimeCreated,Id,ProviderName,LevelDisplayName,Message | ConvertTo-Json -Depth 3 -Compress"
        )
        command = context.runner.powershell_json(script, timeout=20)
        result = _command_json_result(command, self.check_id, "软件或浏览器异常", self.display_name, msg('最近事件'), msg('事件日志是排查证据；崩溃模块或单条事件不能单独证明根本原因。'))
        result.evidence.append(Evidence(msg('WER 记录元数据'), _wer_metadata()))
        return [result]


class NetworkCheck:
    check_id = "network.connectivity"
    display_name = msg('网络配置、DNS 与 HTTPS')
    categories = frozenset({"网络或Wi-Fi异常", "软件或浏览器异常", "Microsoft Store 问题"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        interfaces: list[str] = []
        stats = psutil.net_if_stats()
        for name, addresses in psutil.net_if_addrs().items():
            context.ensure_not_cancelled()
            state = msg('已连接') if stats.get(name) and stats[name].isup else msg('未连接')
            values = [item.address for item in addresses if item.family in (socket.AF_INET, socket.AF_INET6)]
            interfaces.append(msg('{0}：{1}，地址 {2}', name, state, '、'.join(values) if values else msg('无')))
        dns = "正常"
        https = "正常"
        try:
            socket.getaddrinfo("www.microsoft.com", 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            dns = msg('失败（{0}）', type(exc).__name__)
        context.ensure_not_cancelled()
        try:
            request = urllib.request.Request("https://www.microsoft.com/", method="HEAD", headers={"User-Agent": "HelpPack/0.2"})
            with urllib.request.urlopen(request, timeout=6, context=ssl.create_default_context()) as response:
                https = msg('成功（HTTP {0}）', response.status)
        except (OSError, TimeoutError, ValueError, ssl.SSLError, urllib.error.URLError) as exc:
            https = msg('失败（{0}）', type(exc).__name__)
        status = DiagnosticStatus.NORMAL if dns == "正常" and https.startswith(msg('成功')) else DiagnosticStatus.NOTICE
        raw_interfaces = "\n".join(interfaces) or msg('没有网络接口数据')
        repairs: list[RepairSuggestion] = []
        if dns != "正常":
            repairs.append(RepairSuggestion(
                action_id="flush_dns_cache",
                display_name=msg('清除 DNS 客户端缓存'),
                target={},
                safety_level=SafetyLevel.L1,
                requires_admin=False,
                impact=msg('只清除本机缓存的域名解析结果，不会更改 DNS 服务器。'),
                operation_preview=msg('运行 Windows 内置 ipconfig /flushdns，并重新解析两个测试域名'),
                rollback=msg('无需回滚；后续解析会重新写入缓存。'),
                rollback_capability=RollbackCapability.NONE,
                evidence_ids=[self.check_id],
                estimated_seconds=20,
            ))
        return [_result(
            self.check_id, "网络或Wi-Fi异常", self.display_name, status,
            [Evidence(msg('网络接口'), redact_text(raw_interfaces)), Evidence(msg('DNS 解析'), display_label(dns)), Evidence(msg('HTTPS 连接'), display_label(https))],
            msg('DNS 和 HTTPS 分别测试，任一失败都只代表本次指定目标测试失败，不等同于整个互联网不可用。'),
            [msg('结合适配器、代理、DNS 和系统时间结果继续排查。')], severity=Severity.MEDIUM if status == DiagnosticStatus.NOTICE else Severity.INFO,
            confidence=msg('中（单次连接测试）'), repairs=repairs
        )]


class ProxyHostsCheck:
    check_id = "network.proxy_hosts"
    display_name = msg('当前用户代理、PAC 与 Hosts')
    categories = frozenset({"网络或Wi-Fi异常", "软件或浏览器异常", "Microsoft Store 问题"})

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
            return [_result(self.check_id, "网络或Wi-Fi异常", self.display_name, DiagnosticStatus.PERMISSION_DENIED, [Evidence("Hosts", display_label("权限不足"))], msg('无法读取 Hosts 文件。'), [msg('可由管理员人工检查。')], confidence="高")]
        suspicious = [line for line in redirects if "localhost" not in line.lower()]
        status = DiagnosticStatus.NOTICE if proxy["enabled"] or proxy["pac"] or suspicious else DiagnosticStatus.NORMAL
        evidence = [
            Evidence(msg('用户代理'), proxy["display"]),
            Evidence("PAC", proxy["pac"] or msg('未配置')),
            Evidence(msg('WinHTTP 默认代理'), _winhttp_proxy()),
            Evidence(msg('Hosts 非默认重定向'), redact_text("\n".join(suspicious[:30])) if suspicious else msg('未发现')),
        ]
        return [_result(
            self.check_id, "网络或Wi-Fi异常", self.display_name, status, evidence,
            msg('代理、PAC 或 Hosts 自定义记录可能完全合法；这里只提示配置存在，不判定为恶意或故障。'),
            [msg('确认这些配置是否由你、单位网络或可信软件设置。')], severity=Severity.LOW if status == DiagnosticStatus.NOTICE else Severity.INFO,
            confidence=msg('高（配置存在性）；低（是否异常）'), repairs=repairs
        )]


class DeviceServiceCheck:
    check_id = "devices.services"
    display_name = msg('音频、蓝牙与打印服务')
    categories = frozenset({"声音问题", "蓝牙问题", "打印机问题"})

    SERVICE_MAP: ClassVar[dict[str, str]] = {"Audiosrv": msg('Windows 音频'), "AudioEndpointBuilder": msg('音频终结点'), "bthserv": msg('蓝牙支持'), "Spooler": msg('打印后台处理')}

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
                rows.append(msg('{0}：系统未提供此服务', display))
            except psutil.AccessDenied:
                rows.append(msg('{0}：权限不足', display))
        status = DiagnosticStatus.NOTICE if stopped else DiagnosticStatus.NORMAL
        return [_result(
            self.check_id, msg('设备'), self.display_name, status, [Evidence(msg('服务状态'), "；".join(rows))],
            msg('服务未运行可能与设备不可用有关，但也可能是按需启动或该硬件不存在。'),
            [msg('在对应 Windows 设置页确认设备存在、已启用且被选为输出或目标设备。')], confidence="中"
        )]


class PnpDeviceCheck:
    check_id = "devices.pnp"
    display_name = msg('PnP 设备状态')
    categories = frozenset({"声音问题", "蓝牙问题", "打印机问题"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "$classes='AudioEndpoint','MEDIA','Bluetooth','Printer'; Get-PnpDevice -ErrorAction Stop | "
            "Where-Object { $classes -contains $_.Class } | Select-Object -First 80 Class,FriendlyName,Status,Problem | ConvertTo-Json -Compress"
        )
        command = context.runner.powershell_json(script, timeout=20)
        return [_command_json_result(command, self.check_id, msg('设备'), self.display_name, msg('设备'), msg('设备状态或错误码是证据；驱动日期较旧本身不能证明驱动故障。'))]


class UpdateCheck:
    check_id = "windows_update.basic"
    display_name = msg('Windows Update 基础状态')
    categories = frozenset({"Windows更新问题"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        services: list[str] = []
        if platform.system() == "Windows" and hasattr(psutil, "win_service_get"):
            for name in ("wuauserv", "BITS", "cryptsvc"):
                try:
                    info = psutil.win_service_get(name).as_dict()
                    services.append(f"{name}：{info.get('status', 'unknown')} / {info.get('start_type', 'unknown')}")
                except psutil.Error:
                    services.append(msg('{0}：无法读取', name))
        pending = _pending_reboot()
        status = DiagnosticStatus.NOTICE if pending else DiagnosticStatus.NORMAL
        return [_result(
            self.check_id, "Windows更新问题", self.display_name, status,
            [Evidence(msg('更新相关服务'), "；".join(services) or display_label("不支持")), Evidence(msg('等待重启标记'), msg('存在') if pending else msg('未发现已知标记'))],
            msg('这里只检查基础服务和已知重启标记，不会安装更新，也没有运行 SFC 或 DISM。'),
            [msg('如更新持续失败，可记录错误代码后使用 Windows Update 设置或官方支持渠道。')], confidence="中"
        )]


class NetworkConfigurationCheck:
    check_id = "network.configuration"
    display_name = msg('DHCP、默认网关、DNS 服务器与 Wi-Fi 适配器')
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
            command, self.check_id, "网络或Wi-Fi异常", self.display_name, msg('结构化网络配置'),
            msg('配置存在不等于异常；Wi-Fi 名称不写入报告，网关、DNS 和接口地址会自动脱敏。')
        )
        result.evidence.append(Evidence(msg('系统时间'), datetime.now().astimezone().isoformat(timespec="seconds")))
        return [result]


class PrinterCheck:
    check_id = "devices.printers"
    display_name = msg('打印机、默认打印机与队列')
    categories = frozenset({"打印机问题"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "$items=@(); Get-Printer -ErrorAction Stop | ForEach-Object { $count=0; "
            "try { $count=@(Get-PrintJob -PrinterName $_.Name -ErrorAction Stop).Count } catch {} ; "
            "$items += [pscustomobject]@{Name=$_.Name;DriverName=$_.DriverName;PortName=$_.PortName;"
            "PrinterStatus=$_.PrinterStatus;QueueCount=$count} }; $items | ConvertTo-Json -Compress"
        )
        command = context.runner.powershell_json(script, timeout=20)
        result = _command_json_result(command, self.check_id, "打印机问题", self.display_name, msg('已安装打印机'), msg('队列数量是当前快照；不会自动取消任何打印任务。'))
        result.evidence.append(Evidence(msg('默认打印机'), _default_printer()))
        return [result]


class UpdateHistoryCheck:
    check_id = "windows_update.history"
    display_name = msg('最近更新记录、失败代码与日志能力')
    categories = frozenset({"Windows更新问题"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "$since=(Get-Date).AddDays(-30); Get-WinEvent -FilterHashtable @{LogName='System';"
            "ProviderName='Microsoft-Windows-WindowsUpdateClient';StartTime=$since} -MaxEvents 40 -ErrorAction Stop | "
            "Select-Object TimeCreated,Id,LevelDisplayName,Message | ConvertTo-Json -Depth 3 -Compress"
        )
        command = context.runner.powershell_json(script, timeout=20)
        result = _command_json_result(command, self.check_id, "Windows更新问题", self.display_name, msg('更新事件'), msg('事件记录可包含成功和失败；事件存在不等于当前更新仍失败。'))
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        logs = []
        for name in ("Logs/CBS/CBS.log", "Logs/DISM/dism.log", "WindowsUpdate.log"):
            path = windir / name
            try:
                logs.append(f"{path.name}：{msg('可读') if path.is_file() and os.access(path, os.R_OK) else msg('不存在或不可读')}")
            except OSError:
                logs.append(msg('{0}：无法检查', path.name))
        result.evidence.extend(
            [
                Evidence(msg('日志读取能力'), "；".join(logs)),
                Evidence(msg('SFC 只读验证能力'), msg('命令可用（未执行）') if shutil.which("sfc.exe") else msg('命令不可用')),
                Evidence(msg('DISM 扫描能力'), msg('命令可用（未执行）') if shutil.which("dism.exe") else msg('命令不可用')),
            ]
        )
        result.recommendations.append(msg('发布前验证没有运行 sfc /verifyonly 或 DISM /ScanHealth，避免未经确认的长时间扫描。'))
        return [result]


class ReliabilityCheck:
    check_id = "reliability.events"
    display_name = msg('蓝屏、异常关机与硬件错误事件')
    categories = frozenset({"蓝屏或异常重启"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "$since=(Get-Date).AddDays(-30); Get-WinEvent -FilterHashtable @{LogName='System';StartTime=$since;Id=41,1001,18,19,20,46} "
            "-MaxEvents 40 -ErrorAction Stop | Select-Object TimeCreated,Id,ProviderName,LevelDisplayName,Message | ConvertTo-Json -Depth 3 -Compress"
        )
        command = context.runner.powershell_json(script, timeout=20)
        result = _command_json_result(command, self.check_id, "蓝屏或异常重启", self.display_name, msg('最近事件'), msg('Kernel-Power 41 只表示系统未正常关机，不等同于已经确认电源故障；事件或模块名也不能单独证明根因。'))
        dump_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Minidump"
        try:
            dumps = sorted(dump_dir.glob("*.dmp"), key=lambda item: item.stat().st_mtime, reverse=True)
            dump_text = msg('{0} 个；最近：{1}', len(dumps), datetime.fromtimestamp(dumps[0].stat().st_mtime, tz=UTC).astimezone().isoformat(timespec='seconds')) if dumps else msg('未发现')
        except PermissionError:
            dump_text = msg('product.permission_denied')
        result.evidence.append(Evidence(msg('小型转储'), dump_text))
        return [result]


class BatteryDiskHealthCheck:
    check_id = "health.battery_disk"
    display_name = msg('电池与磁盘健康摘要')
    categories = frozenset({"电池或磁盘健康"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        battery = psutil.sensors_battery()
        battery_text = msg('未检测到电池') if battery is None else msg('电量 {0:.0f}% / {1}', battery.percent, msg('接通电源') if battery.power_plugged else msg('使用电池'))
        script = "Get-PhysicalDisk -ErrorAction Stop | Select-Object FriendlyName,MediaType,HealthStatus,OperationalStatus,Size | ConvertTo-Json -Compress"
        command = context.runner.powershell_json(script, timeout=15)
        disk_result = _command_json_result(command, self.check_id, "电池或磁盘健康", self.display_name, msg('磁盘'), msg('SMART 或 HealthStatus 显示正常也不能保证磁盘绝对安全；USB、RAID 和部分厂商驱动可能不提供数据。'))
        disk_result.evidence.insert(0, Evidence(msg('电池'), battery_text))
        disk_result.evidence.insert(1, Evidence(msg('电池设计/满充容量与循环次数'), msg('标准 psutil 接口不提供；厂商固件或更高权限接口可用性不确定')))
        disk_result.evidence.append(Evidence(msg('温度'), msg('当前 Windows 标准接口无法可靠覆盖本机硬件，第一版不支持')))
        disk_result.recommendations.append(msg('如出现异响、读写错误或健康异常，优先备份重要数据。'))
        return [disk_result]


def default_checks() -> list[Any]:
    from .advanced_checks import (
        DriverUpdateCheck,
        MicrosoftStoreCheck,
        NetworkRepairEligibilityCheck,
        SystemRepairCheck,
        VendorDriverSourceCheck,
    )
    from .scenario_checks import CachePreviewCheck
    from .tls import InternetTlsCheck

    return [
        PerformanceCheck(),
        CachePreviewCheck(),
        DiskAndTempCheck(),
        StartupCheck(),
        ScheduledTaskCheck(),
        BrowserCheck(),
        CrashEventCheck(),
        NetworkCheck(),
        ProxyHostsCheck(),
        NetworkConfigurationCheck(),
        NetworkRepairEligibilityCheck(),
        InternetTlsCheck(),
        MicrosoftStoreCheck(),
        DeviceServiceCheck(),
        PnpDeviceCheck(),
        DriverUpdateCheck(),
        VendorDriverSourceCheck(),
        SystemRepairCheck(),
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
                    return msg('{0}: 至少 {1} 个文件 / {2:.1f} MB（达到统计上限）', path.name or path, count, total / 1024 ** 2)
                try:
                    total += (Path(root) / name).stat().st_size
                    count += 1
                except (OSError, PermissionError):
                    skipped += 1
    except (OSError, PermissionError):
        return msg('{0}: 权限不足或不可用', path.name or path)
    suffix = msg('，跳过 {0} 项', skipped) if skipped else ""
    return msg('{0}: {1} 个文件 / {2:.1f} MB{3}', path.name or path, count, total / 1024 ** 2, suffix)


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
                        entries.append(f"{hive_name}\\{Path(path).name}\\{name} → {Path(str(value).strip(chr(34))).name or msg('命令')}")
                        if hive_name == "HKCU":
                            repairs.append(RepairSuggestion(
                                action_id="disable_hkcu_startup",
                                display_name=msg('禁用用户启动项：{0}', name),
                                target={"key_path": path, "value_name": name},
                                safety_level=SafetyLevel.L1,
                                requires_admin=False,
                                impact=msg('该程序将不再随当前用户登录自动启动；不会删除程序文件。'),
                                operation_preview=msg('备份后删除 HKCU\\{0} 中名为 {1} 的值', path, name),
                                rollback=msg('从 HelpPack 备份恢复原值及注册表类型。'),
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
                                    version = msg('版本无法读取')
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
            rows.append(msg('{0}：发现 {1} 个锁标记', name, count))
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
        suffix = msg('（达到统计上限）') if count >= 200 else ""
        return msg('发现 {0} 条元数据{1}；最近时间 {2}', count, suffix, datetime.fromtimestamp(latest, tz=UTC).astimezone().isoformat(timespec='seconds'))
    return msg('product.permission_denied') if denied else msg('未发现 WER 记录')


def _winhttp_proxy() -> str:
    if platform.system() != "Windows":
        return msg('当前系统不支持')
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
            return msg('无法读取（错误 {0}）', error)
        proxy = ctypes.wstring_at(info.proxy) if info.proxy else ""
        bypass = ctypes.wstring_at(info.bypass) if info.bypass else ""
        try:
            if info.proxy:
                ctypes.windll.kernel32.GlobalFree(info.proxy)
            if info.bypass:
                ctypes.windll.kernel32.GlobalFree(info.bypass)
        finally:
            pass
        access = {0: msg('系统默认'), 1: msg('直连'), 3: msg('指定代理'), 4: msg('自动代理')}.get(info.access_type, msg('类型 {0}', info.access_type))
        details = msg('{0}；{1}；绕过 {2}', access, proxy or msg('无代理服务器'), bypass or msg('无'))
        return redact_text(details)
    except (AttributeError, OSError, ValueError):
        return msg('接口不可用')


def _default_printer() -> str:
    if platform.system() != "Windows":
        return msg('当前系统不支持')
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Windows") as key:
            value = str(winreg.QueryValueEx(key, "Device")[0])
            return redact_text(value.split(",", 1)[0] or msg('未设置'))
    except OSError:
        return msg('未设置或无法读取')


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
    return {"enabled": enabled, "display": f"{msg('启用') if enabled else msg('未启用')}；{redact_text(server) if server else msg('无服务器')}", "pac": redact_text(pac)}, repairs


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
        return _result(check_id, category, name, DiagnosticStatus.UNKNOWN, [Evidence(msg('检查状态'), msg('超时'))], msg('检查超时，数据不足，无法判断。'), [msg('可稍后重试。')], confidence=msg('高（超时状态）'))
    if command.permission_denied:
        return _result(check_id, category, name, DiagnosticStatus.PERMISSION_DENIED, [Evidence(msg('检查状态'), display_label("权限不足"))], msg('当前权限不足，未读取到该数据。'), [msg('如确有需要，可由管理员人工检查。')], confidence=msg('高（权限状态）'))
    if command.unsupported:
        return _result(check_id, category, name, DiagnosticStatus.UNSUPPORTED, [Evidence(msg('检查状态'), msg('命令或模块不可用'))], msg('当前 Windows 版本或组件不支持此检查。'), [msg('不需要为了此项检查安装未知工具。')], confidence=msg('高（支持状态）'))
    if command.returncode != 0:
        return _result(check_id, category, name, DiagnosticStatus.UNKNOWN, [Evidence(msg('检查状态'), msg('失败（退出码 {0}）', command.returncode))], msg('检查失败，不等同于发现异常。'), [msg('将此状态写入求助包，供技术人员继续判断。')], confidence=msg('高（失败状态）'))
    try:
        value = command.json_value()
    except (ValueError, TypeError):
        return _result(check_id, category, name, DiagnosticStatus.UNKNOWN, [Evidence(msg('检查状态'), msg('返回数据格式无法识别'))], msg('系统返回了无法结构化读取的数据；不会解析本地化文本来猜测结果。'), [msg('可稍后重试。')], confidence=msg('高（格式状态）'))
    if not value:
        return _result(check_id, category, name, DiagnosticStatus.NORMAL, [Evidence(label, msg('未发现相关记录'))], limitation, [msg('当前没有发现相关证据。')], confidence="中")
    redacted = redact_text(str(value))
    return _result(check_id, category, name, DiagnosticStatus.NOTICE, [Evidence(label, redacted[:12000])], limitation, [msg('展开证据并结合发生时间判断相关性。')], severity=Severity.LOW, confidence="中")
