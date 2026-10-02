from __future__ import annotations

import re
from typing import ClassVar

from helppack.english import label as display_label
from helppack.english import text as msg

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
        text = msg('检查超时')
    elif command.permission_denied:
        text = msg('product.permission_denied')
    elif command.unsupported:
        text = msg('系统不支持此接口')
    else:
        text = msg('检查失败（退出码 {0}）', command.returncode)
    return _result(check_id, category, name, DiagnosticStatus.UNKNOWN, [Evidence(msg('检查状态'), text)], msg('无法获得可靠证据，因此没有执行或推荐自动修改。'), [msg('可稍后重试并把状态加入求助包。')], confidence=msg('高（失败状态）'))


class NetworkRepairEligibilityCheck:
    check_id = "network.repair_eligibility"
    display_name = msg('网络自动修复安全条件')
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
            evidence.append(f"{alias or msg('未命名接口')}：DHCP {msg('启用') if dhcp else msg('未启用')}；{msg('复杂/虚拟接口') if is_complex else msg('普通接口')}")
        return [_result(self.check_id, "网络或Wi-Fi异常", self.display_name, DiagnosticStatus.NOTICE,
            [Evidence(msg('活动接口'), redact_text("；".join(evidence)) if evidence else msg('没有可读取的活动接口'))],
            msg('网络栈损坏尚无可靠证据，因此不提供全局 Winsock/TCP/IP 重置。'), [msg('按实际症状选择单个接口；正常的自定义 DNS 无需重置。')], repairs,
            severity=Severity.LOW, confidence=msg('高（配置）；中（修复适用性）'))]


class MicrosoftStoreCheck:
    check_id = "store.health"
    display_name = msg('Microsoft Store 包与策略')
    categories = frozenset({"Microsoft Store 问题"})

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        from .store import FAMILY, read_store_state
        try:
            value = read_store_state(context.runner)
        except (RuntimeError, ValueError, TypeError):
            return [_result(self.check_id, "Microsoft Store 问题", self.display_name, DiagnosticStatus.UNKNOWN,
                [Evidence(msg('检查状态'), msg('未能可靠读取商店状态'))], msg('查询失败不代表商店被卸载。'),
                [msg('稍后重新检查，或在 Windows 设置中检查已安装应用。')])]
        exists, blocked = bool(value.get("Exists")), bool(value.get("PolicyDisabled"))
        repairs: list[RepairSuggestion] = []
        family = {"package_family": FAMILY}
        if not blocked and exists and value["WsresetAvailable"]:
            repairs.append(RepairSuggestion("store_cache_reset", msg('可选：清理商店缓存后手动重试'), {}, SafetyLevel.L1, False,
                msg('适用于商店已注册但加载异常；不会修复策略封锁、断网或缺失的安装文件。'), msg('运行 Windows 内置 wsreset.exe'), msg('缓存会重新生成。'),
                RollbackCapability.NONE, RestartRequirement.APP, evidence_ids=[self.check_id], estimated_seconds=120))
        if not blocked and exists and value["ManifestExists"]:
            repairs.append(RepairSuggestion("store_reregister", msg('高级：尝试恢复当前用户商店注册'), family, SafetyLevel.L2, False,
                msg('用于注册异常。未注册不代表已卸载；若系统没有可用安装包，操作将失败并保留错误信息。'),
                msg('优先使用已安装商店的 AppxManifest.xml；未注册时按系统支持的包系列接口尝试恢复'), msg('不提供自动回滚。'),
                RollbackCapability.NONE, RestartRequirement.APP, evidence_ids=[self.check_id], estimated_seconds=120))
        status = DiagnosticStatus.ABNORMAL if blocked else (DiagnosticStatus.NOTICE if not exists or value.get("Status") != "Ok" else DiagnosticStatus.NORMAL)
        recommendations = [
            msg('0x80131500/安全连接错误：优先查看“Internet TLS 设置”检查，按 Windows 支持范围勾选 TLS 1.2/1.3，而不是直接重置商店。'),
            msg('点击无反应/闪退：先在 Windows 设置 → 应用 → Microsoft Store → 高级选项中选择“修复”。'),
            msg('能打开但一直加载/网络报错：先查看 DNS、代理、HTTPS 和系统日期/时区，不要直接清空应用数据。'),
            msg('只有修复和缓存清理无效后，再到 Windows 设置手动选择“重置”；这会清除商店应用数据。'),
            msg('命令完成或包已注册不代表恢复正常；请实际打开商店并加载页面后再判断。'),
        ]
        if blocked:
            recommendations = [msg('检测到用户或电脑策略禁用 Store，请联系管理员；修复缓存或重置应用不能绕过该策略。')]
        elif not exists:
            recommendations.insert(0, msg('当前用户没有商店注册记录，不能断言整台电脑已卸载商店。应先由管理员只读检查其他用户的商店包是否存在，再在原用户的非管理员会话恢复注册；本次未确认机器级安装状态，因此不提供自动注册。'))
        return [_result(self.check_id, "Microsoft Store 问题", self.display_name, status,
            [Evidence(msg('当前用户注册'), msg('已注册') if exists else msg('未注册（机器级安装状态尚未确认）')), Evidence(msg('用户/电脑策略'), msg('已禁用') if blocked else msg('未发现 RemoveWindowsStore 禁用项')), Evidence(msg('包状态'), str(value.get("Status") or msg('不适用'))), Evidence(msg('自动验证边界'), msg('未验证商店能否实际启动或加载内容'))],
            msg('按注册、策略和实际症状选择下一步；正常注册不是启动成功的证据。'), recommendations, repairs,
            severity=Severity.HIGH if blocked else Severity.LOW, confidence=msg('高（注册和已检查策略）；未知（实际启动）'))]


class DriverUpdateCheck:
    check_id = "drivers.windows_update"
    display_name = msg('Windows Update 可用驱动')
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
            return [_command_failure(self.check_id, msg('设备'), self.display_name, command)]
        try:
            rows = command.json_value() or []
        except (ValueError, TypeError):
            rows = []
        rows = [rows] if isinstance(rows, dict) else rows
        repairs: list[RepairSuggestion] = []
        evidence: list[str] = []
        for row in rows[:12]:
            update_id, title = str(row.get("UpdateID", "")), str(row.get("Title", msg('驱动更新')))
            evidence.append(f"{title}；{row.get('DriverManufacturer') or msg('厂商未知')}；{row.get('DriverModel') or msg('型号未知')}")
            if re.fullmatch(r"[0-9a-fA-F-]{36}", update_id):
                repairs.append(RepairSuggestion(
                    "install_wua_driver", msg('安装驱动：{0}', title), {"update_id": update_id}, SafetyLevel.L3, True,
                    msg('驱动安装可能改变设备行为、要求重启，且不能保证自动回滚。'), msg('重新搜索相同 UpdateID，只安装这一项 Windows Update 驱动'), msg('仅能通过 Windows/设备管理器尽力回退。'),
                    RollbackCapability.BEST_EFFORT, RestartRequirement.SYSTEM if row.get("RebootRequired") else RestartRequirement.NONE,
                    True, [msg('设备可能短暂不可用'), msg('可能需要重启')], [self.check_id], 3600, True,
                ))
        return [_result(self.check_id, msg('设备'), self.display_name, DiagnosticStatus.NOTICE if rows else DiagnosticStatus.NORMAL,
            [Evidence(msg('适用且未安装的驱动'), redact_text("\n".join(evidence)) if evidence else msg('未发现'))],
            msg('这里只列出 Windows Update 判定为适用且未安装的驱动；不从第三方驱动站下载。'),
            [msg('每次只安装一个驱动，并在完成后重新检查设备状态。')] if rows else [msg('Windows Update 当前没有返回适用驱动。')], repairs,
            severity=Severity.LOW if rows else Severity.INFO, confidence=msg('高（Windows Update 适用性）'))]


class SystemRepairCheck:
    check_id = "system.repair_options"
    display_name = msg('系统组件与常见服务修复')
    categories = frozenset({"Windows更新问题", "声音问题", "蓝牙问题", "打印机问题"})
    SERVICE_LABELS: ClassVar[dict[str, str]] = {"wuauserv": "Windows Update", "BITS": "BITS", "cryptsvc": msg('加密服务'), "Spooler": msg('打印后台处理'), "Audiosrv": "Windows Audio", "AudioEndpointBuilder": msg('音频终结点'), "bthserv": msg('蓝牙支持')}

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        from .scenario_checks import SafeServiceCheck
        return SafeServiceCheck().run(context)


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
    display_name = msg('官方厂商驱动来源')
    categories = DriverUpdateCheck.categories

    def run(self, context: ScanContext) -> list[DiagnosticResult]:
        script = "Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model | ConvertTo-Json -Compress"
        command = context.runner.powershell_json(script, timeout=20)
        if command.returncode != 0:
            return [_command_failure(self.check_id, msg('设备'), self.display_name, command)]
        try:
            system = command.json_value() or {}
        except (ValueError, TypeError):
            system = {}
        manufacturer = str(system.get("Manufacturer", display_label("未知")))
        matched = next((name for name in ("dell", "lenovo", "hp") if name in manufacturer.lower()), "")
        sources = ([VENDOR_SUPPORT_URLS[matched]] if matched else []) + [VENDOR_SUPPORT_URLS[name] for name in ("intel", "nvidia", "amd")]
        labels = {"dell": "Dell", "lenovo": "Lenovo", "hp": "HP", "intel": "Intel", "nvidia": "NVIDIA", "amd": "AMD"}
        source_names = ([matched] if matched else []) + ["intel", "nvidia", "amd"]
        repairs = [RepairSuggestion(
            "open_vendor_support", msg('打开 {0} 官方驱动支持页', labels[name]), {"url": VENDOR_SUPPORT_URLS[name]}, SafetyLevel.L1, False,
            msg('会把官方 HTTPS 地址交给默认浏览器；不会自动提交序列号或运行安装器。'), msg('打开 {0}', VENDOR_SUPPORT_URLS[name]), msg('打开网页无需回滚。'),
            RollbackCapability.NONE, requires_network=True, evidence_ids=[self.check_id], estimated_seconds=10,
        ) for name in source_names]
        return [_result(self.check_id, msg('设备'), self.display_name, DiagnosticStatus.NORMAL,
            [Evidence(msg('整机厂商'), redact_text(manufacturer)), Evidence(msg('允许的官方来源'), "\n".join(sources))],
            msg('HelpPack 只允许官方 HTTPS 域名；首版不抓取页面、不静默运行厂商 EXE，也不传输序列号。'),
            [msg('Windows Update 没有合适驱动时，可从列表中的官方页面人工选择。')], repairs, confidence=msg('高（来源白名单）'))]
