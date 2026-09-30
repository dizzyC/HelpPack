from __future__ import annotations

import platform
import re
from typing import ClassVar

import psutil

from ..redaction import redact_text
from .engine import ScanContext
from .models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
    RepairSuggestion,
    RestartRequirement,
    RollbackCapability,
    SafetyLevel,
    Severity,
)


def _result(check_id: str, category: str, name: str, status: DiagnosticStatus, evidence: list[Evidence], explanation: str, recommendations: list[str], repairs: list[RepairSuggestion] | None = None, *, severity: Severity = Severity.INFO, confidence: str = "中") -> DiagnosticResult:
    repairs = repairs or []
    return DiagnosticResult(
        check_id, category, name, status, severity, evidence, explanation, confidence, recommendations,
        supports_rollback=any(item.rollback_capability != RollbackCapability.NONE for item in repairs),
        redacted_raw=redact_text("\n".join(f"{item.label}: {item.value}" for item in evidence)),
        repair_suggestions=repairs,
    )


def _command_failure(check_id: str, category: str, name: str, command) -> DiagnosticResult:
    if command.timed_out:
        text = "检查超时"
    elif command.permission_denied:
        text = "权限不足"
    elif command.unsupported:
        text = "系统不支持此接口"
    else:
        text = f"检查失败（退出码 {command.returncode}）"
    return _result(check_id, category, name, DiagnosticStatus.UNKNOWN, [Evidence("检查状态", text)], "无法获得可靠证据，因此没有执行或推荐自动修改。", ["可稍后重试并把状态加入求助包。"], confidence="高（失败状态）")


class NetworkRepairEligibilityCheck:
    check_id = "network.repair_eligibility"
    display_name = "网络自动修复安全条件"
    categories = frozenset({"网络或Wi-Fi异常"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "Get-NetIPConfiguration -ErrorAction Stop | Where-Object {$_.NetAdapter.Status -eq 'Up'} | "
            "ForEach-Object {[pscustomobject]@{Alias=$_.InterfaceAlias;Index=$_.InterfaceIndex;"
            "Dhcp=[string]$_.NetIPv4Interface.Dhcp;Description=$_.InterfaceDescription;"
            "Dns=@($_.DNSServer.ServerAddresses)}} | ConvertTo-Json -Depth 4 -Compress"
        )
        command = context.runner.powershell_json(script, timeout=25)
        if command.returncode != 0:
            return [_command_failure(self.check_id, "网络或Wi-Fi异常", self.display_name, command)]
        try:
            rows = command.json_value() or []
        except (ValueError, TypeError):
            rows = []
        rows = [rows] if isinstance(rows, dict) else rows
        repairs: list[RepairSuggestion] = []
        evidence: list[str] = []
        for row in rows:
            alias, description = str(row.get("Alias", "")), str(row.get("Description", ""))
            is_complex = any(word in f"{alias} {description}".lower() for word in ("vpn", "virtual", "hyper-v", "bridge", "tap", "tunnel"))
            dhcp = str(row.get("Dhcp", "")).lower() == "enabled"
            evidence.append(f"{alias or '未命名接口'}：DHCP {'启用' if dhcp else '未启用'}；{'复杂/虚拟接口' if is_complex else '普通接口'}")
            if dhcp and alias and str(row.get("Index", "")).isdigit():
                repairs.append(RepairSuggestion(
                    "renew_dhcp", f"续租 DHCP：{alias}", {"interface_alias": alias}, SafetyLevel.L2, True,
                    "该接口可能短暂断网。", f"只对接口“{alias}”执行 DHCP 续租", "续租本身不能可靠还原。",
                    RollbackCapability.BEST_EFFORT, side_effects=["短暂断网"], evidence_ids=[self.check_id], estimated_seconds=90,
                ))
                repairs.append(RepairSuggestion(
                    "reset_dns_to_dhcp", f"恢复 DHCP DNS：{alias}", {"interface_index": str(row["Index"])}, SafetyLevel.L2, True,
                    "会移除该接口手动配置的 DNS 服务器。", f"只重置接口“{alias}”的 DNS 为 DHCP 默认值", "使用 DPAPI 加密快照恢复原 DNS。",
                    RollbackCapability.FULL, side_effects=["域名解析可能短暂中断"], evidence_ids=[self.check_id], estimated_seconds=45,
                ))
        return [_result(self.check_id, "网络或Wi-Fi异常", self.display_name, DiagnosticStatus.NOTICE,
            [Evidence("活动接口", redact_text("；".join(evidence)) if evidence else "没有可读取的活动接口")],
            "网络栈损坏尚无可靠证据，因此不提供全局 Winsock/TCP/IP 重置。", ["按实际症状选择单个接口；正常的自定义 DNS 无需重置。"], repairs,
            severity=Severity.LOW, confidence="高（配置）；中（修复适用性）")]


class MicrosoftStoreCheck:
    check_id = "store.health"
    display_name = "Microsoft Store 包与策略"
    categories = frozenset({"Microsoft Store 问题"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        from .store import FAMILY, read_store_state
        try:
            value = read_store_state(context.runner)
        except (RuntimeError, ValueError, TypeError):
            return [_result(self.check_id, "Microsoft Store 问题", self.display_name, DiagnosticStatus.UNKNOWN,
                [Evidence("检查状态", "未能可靠读取商店状态")], "查询失败不代表商店被卸载。",
                ["稍后重新检查，或在 Windows 设置中检查已安装应用。"])]
        exists, blocked = bool(value.get("Exists")), bool(value.get("PolicyDisabled"))
        repairs: list[RepairSuggestion] = []
        family = {"package_family": FAMILY}
        if not blocked and exists and value["WsresetAvailable"]:
            repairs.append(RepairSuggestion("store_cache_reset", "可选：清理商店缓存后手动重试", {}, SafetyLevel.L1, False,
                "适用于商店已注册但加载异常；不会修复策略封锁、断网或缺失的安装文件。", "运行 Windows 内置 wsreset.exe", "缓存会重新生成。",
                RollbackCapability.NONE, RestartRequirement.APP, evidence_ids=[self.check_id], estimated_seconds=120))
        if not blocked and exists and value["ManifestExists"]:
            repairs.append(RepairSuggestion("store_reregister", "高级：尝试恢复当前用户商店注册", family, SafetyLevel.L2, False,
                "用于注册异常。未注册不代表已卸载；若系统没有可用安装包，操作将失败并保留错误信息。",
                "优先使用已安装商店的 AppxManifest.xml；未注册时按系统支持的包系列接口尝试恢复", "不提供自动回滚。",
                RollbackCapability.NONE, RestartRequirement.APP, evidence_ids=[self.check_id], estimated_seconds=120))
        status = DiagnosticStatus.ABNORMAL if blocked else (DiagnosticStatus.NOTICE if not exists or value.get("Status") != "Ok" else DiagnosticStatus.NORMAL)
        recommendations = [
            "0x80131500/安全连接错误：优先查看“Internet TLS 设置”检查，按 Windows 支持范围勾选 TLS 1.2/1.3，而不是直接重置商店。",
            "点击无反应/闪退：先在 Windows 设置 → 应用 → Microsoft Store → 高级选项中选择“修复”。",
            "能打开但一直加载/网络报错：先查看 DNS、代理、HTTPS 和系统日期/时区，不要直接清空应用数据。",
            "只有修复和缓存清理无效后，再到 Windows 设置手动选择“重置”；这会清除商店应用数据。",
            "命令完成或包已注册不代表恢复正常；请实际打开商店并加载页面后再判断。",
        ]
        if blocked:
            recommendations = ["检测到用户或电脑策略禁用 Store，请联系管理员；修复缓存或重置应用不能绕过该策略。"]
        elif not exists:
            recommendations.insert(0, "当前用户没有商店注册记录，不能断言整台电脑已卸载商店。应先由管理员只读检查其他用户的商店包是否存在，再在原用户的非管理员会话恢复注册；本次未确认机器级安装状态，因此不提供自动注册。")
        return [_result(self.check_id, "Microsoft Store 问题", self.display_name, status,
            [Evidence("当前用户注册", "已注册" if exists else "未注册（机器级安装状态尚未确认）"), Evidence("用户/电脑策略", "已禁用" if blocked else "未发现 RemoveWindowsStore 禁用项"), Evidence("包状态", str(value.get("Status") or "不适用")), Evidence("自动验证边界", "未验证商店能否实际启动或加载内容")],
            "按注册、策略和实际症状选择下一步；正常注册不是启动成功的证据。", recommendations, repairs,
            severity=Severity.HIGH if blocked else Severity.LOW, confidence="高（注册和已检查策略）；未知（实际启动）")]


class DriverUpdateCheck:
    check_id = "drivers.windows_update"
    display_name = "Windows Update 可用驱动"
    categories = frozenset({"驱动安装与更新"})
    explicit_only = True

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = (
            "$s=New-Object -ComObject Microsoft.Update.Session;$q=$s.CreateUpdateSearcher();"
            "$r=$q.Search(\"IsInstalled=0 and Type='Driver' and IsHidden=0\");$items=@();"
            "foreach($u in $r.Updates){$items+=[pscustomobject]@{Title=$u.Title;UpdateID=$u.Identity.UpdateID;"
            "DriverManufacturer=$u.DriverManufacturer;DriverModel=$u.DriverModel;RebootRequired=$u.RebootRequired}};"
            "$items|ConvertTo-Json -Depth 3 -Compress"
        )
        command = context.runner.powershell_json(script, timeout=120)
        if command.returncode != 0:
            return [_command_failure(self.check_id, "设备", self.display_name, command)]
        try:
            rows = command.json_value() or []
        except (ValueError, TypeError):
            rows = []
        rows = [rows] if isinstance(rows, dict) else rows
        repairs: list[RepairSuggestion] = []
        evidence: list[str] = []
        for row in rows[:12]:
            update_id, title = str(row.get("UpdateID", "")), str(row.get("Title", "驱动更新"))
            evidence.append(f"{title}；{row.get('DriverManufacturer') or '厂商未知'}；{row.get('DriverModel') or '型号未知'}")
            if re.fullmatch(r"[0-9a-fA-F-]{36}", update_id):
                repairs.append(RepairSuggestion(
                    "install_wua_driver", f"安装驱动：{title}", {"update_id": update_id}, SafetyLevel.L3, True,
                    "驱动安装可能改变设备行为、要求重启，且不能保证自动回滚。", "重新搜索相同 UpdateID，只安装这一项 Windows Update 驱动", "仅能通过 Windows/设备管理器尽力回退。",
                    RollbackCapability.BEST_EFFORT, RestartRequirement.SYSTEM if row.get("RebootRequired") else RestartRequirement.NONE,
                    True, ["设备可能短暂不可用", "可能需要重启"], [self.check_id], 3600, True,
                ))
        return [_result(self.check_id, "设备", self.display_name, DiagnosticStatus.NOTICE if rows else DiagnosticStatus.NORMAL,
            [Evidence("适用且未安装的驱动", redact_text("\n".join(evidence)) if evidence else "未发现")],
            "这里只列出 Windows Update 判定为适用且未安装的驱动；不从第三方驱动站下载。",
            ["每次只安装一个驱动，并在完成后重新检查设备状态。"] if rows else ["Windows Update 当前没有返回适用驱动。"], repairs,
            severity=Severity.LOW if rows else Severity.INFO, confidence="高（Windows Update 适用性）")]


class SystemRepairCheck:
    check_id = "system.repair_options"
    display_name = "系统组件与常见服务修复"
    categories = frozenset({"Windows更新问题", "声音问题", "蓝牙问题", "打印机问题"})
    SERVICE_LABELS: ClassVar[dict[str, str]] = {"wuauserv": "Windows Update", "BITS": "BITS", "cryptsvc": "加密服务", "Spooler": "打印后台处理", "Audiosrv": "Windows Audio", "AudioEndpointBuilder": "音频终结点", "bthserv": "蓝牙支持"}

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        if platform.system() != "Windows" or not hasattr(psutil, "win_service_get"):
            raise NotImplementedError
        repairs: list[RepairSuggestion] = []
        rows: list[str] = []
        for name, label in self.SERVICE_LABELS.items():
            selection = {"声音问题": {"Audiosrv", "AudioEndpointBuilder"}, "蓝牙问题": {"bthserv"},
                         "打印机问题": {"Spooler"}, "Windows更新问题": {"wuauserv", "BITS", "cryptsvc"}}
            if context.category in selection and name not in selection[context.category]:
                continue
            try:
                status = psutil.win_service_get(name).status()
            except psutil.Error:
                status = "无法读取"
            rows.append(f"{label}：{status}")
            if status == "stopped":
                repairs.append(RepairSuggestion("service_start", f"启动服务：{label}", {"service_name": name}, SafetyLevel.L2, True, "只启动该服务，不修改启动类型。", f"启动服务 {name}", "可人工再次停止。", RollbackCapability.BEST_EFFORT, RestartRequirement.SERVICE, evidence_ids=[self.check_id], estimated_seconds=60))
            elif status == "running" and context.category in selection:
                repairs.append(RepairSuggestion("service_restart", f"重新启动服务：{label}", {"service_name": name}, SafetyLevel.L2, True,
                    "会暂时中断该服务正在处理的任务，未保存的任务可能失败。", f"只重新启动 {name}，不改启动类型", "无法恢复被中断的任务。",
                    RollbackCapability.NONE, RestartRequirement.SERVICE, evidence_ids=[self.check_id], estimated_seconds=90))
        return [_result(self.check_id, "系统", self.display_name, DiagnosticStatus.NOTICE,
            [Evidence("相关服务", "；".join(rows))], "按需启动的服务停止可能正常；启动服务前请确认与当前故障相关。",
            ["尚无组件损坏证据，因此不自动推荐 DISM/SFC 修复。"], repairs, severity=Severity.LOW, confidence="中")]


VENDOR_SUPPORT_URLS = {
    "dell": "https://www.dell.com/support/home/",
    "lenovo": "https://support.lenovo.com/",
    "hp": "https://support.hp.com/drivers/",
    "intel": "https://www.intel.com/content/www/us/en/download-center/home.html",
    "nvidia": "https://www.nvidia.com/Download/index.aspx",
    "amd": "https://www.amd.com/en/support/download/drivers.html",
}


class VendorDriverSourceCheck:
    check_id = "drivers.vendor_sources"
    display_name = "官方厂商驱动来源"
    categories = DriverUpdateCheck.categories

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = "Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model | ConvertTo-Json -Compress"
        command = context.runner.powershell_json(script, timeout=20)
        if command.returncode != 0:
            return [_command_failure(self.check_id, "设备", self.display_name, command)]
        try:
            system = command.json_value() or {}
        except (ValueError, TypeError):
            system = {}
        manufacturer = str(system.get("Manufacturer", "未知"))
        matched = next((name for name in ("dell", "lenovo", "hp") if name in manufacturer.lower()), "")
        sources = ([VENDOR_SUPPORT_URLS[matched]] if matched else []) + [VENDOR_SUPPORT_URLS[name] for name in ("intel", "nvidia", "amd")]
        labels = {"dell": "Dell", "lenovo": "Lenovo", "hp": "HP", "intel": "Intel", "nvidia": "NVIDIA", "amd": "AMD"}
        source_names = ([matched] if matched else []) + ["intel", "nvidia", "amd"]
        repairs = [RepairSuggestion(
            "open_vendor_support", f"打开 {labels[name]} 官方驱动支持页", {"url": VENDOR_SUPPORT_URLS[name]}, SafetyLevel.L1, False,
            "会把官方 HTTPS 地址交给默认浏览器；不会自动提交序列号或运行安装器。", f"打开 {VENDOR_SUPPORT_URLS[name]}", "打开网页无需回滚。",
            RollbackCapability.NONE, requires_network=True, evidence_ids=[self.check_id], estimated_seconds=10,
        ) for name in source_names]
        return [_result(self.check_id, "设备", self.display_name, DiagnosticStatus.NORMAL,
            [Evidence("整机厂商", redact_text(manufacturer)), Evidence("允许的官方来源", "\n".join(sources))],
            "HelpPack 只允许官方 HTTPS 域名；首版不抓取页面、不静默运行厂商 EXE，也不传输序列号。",
            ["Windows Update 没有合适驱动时，可从列表中的官方页面人工选择。"], repairs, confidence="高（来源白名单）")]
