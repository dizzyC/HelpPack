"""Read-only Internet Options TLS diagnostics; never override security policy."""
from __future__ import annotations

import platform
import sys
from collections.abc import Callable

from .models import DiagnosticResult, DiagnosticStatus, Evidence, Severity

INTERNET_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
POLICY_KEY = r"Software\Policies\Microsoft\Windows\CurrentVersion\Internet Settings"
SCHANNEL_KEY = r"SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols"
TLS_BITS = {"TLS 1.2": 0x800, "TLS 1.3": 0x2000}


def read_dword(hive: str, path: str, name: str) -> int | None:
    import winreg

    root = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}[hive]
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
            value, kind = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None
    if kind != winreg.REG_DWORD or type(value) is not int:
        raise ValueError("TLS 注册表值不是 DWORD")
    return value


def supports_tls13() -> bool:
    version = sys.getwindowsversion()
    return version.major >= 10 and version.build >= (22000 if version.product_type == 1 else 20348)


class InternetTlsCheck:
    check_id = "network.internet_tls"
    display_name = "商店连接：Internet TLS 设置"
    categories = frozenset({"网络或Wi-Fi异常", "Microsoft Store 问题"})

    def __init__(self, reader: Callable | None = None, tls13: Callable | None = None):
        self.reader = reader or read_dword
        self.tls13 = tls13 or supports_tls13

    def run(self, context) -> list[DiagnosticResult]:
        if platform.system() != "Windows":
            return [self.result(DiagnosticStatus.UNSUPPORTED, [], ["此项仅支持 Windows。"])]
        try:
            supported = self.tls13()
            user_mask = self.reader("HKCU", INTERNET_KEY, "SecureProtocols")
            policies = [self.reader(hive, POLICY_KEY, "SecureProtocols") for hive in ("HKCU", "HKLM")]
            evidence = [Evidence("当前用户 Internet 协议设置", "未显式配置（使用系统默认，不能判定为关闭）" if user_mask is None else f"协议掩码 0x{user_mask:X}")]
            abnormal = False
            for label, bit in TLS_BITS.items():
                if label == "TLS 1.3" and not supported:
                    evidence.append(Evidence(label, "当前 Windows 不支持；不要强行添加注册表项"))
                    continue
                state = "系统默认，尚未确认实际协商" if user_mask is None else ("用户选项已勾选" if user_mask & bit else "用户选项未勾选")
                disabled = False
                for name in ("Enabled", "DisabledByDefault"):
                    value = self.reader("HKLM", SCHANNEL_KEY + "\\" + label + r"\Client", name)
                    if (name == "Enabled" and value == 0) or (name == "DisabledByDefault" and value == 1):
                        disabled = True
                if disabled:
                    state += "；Schannel 客户端有显式禁用配置"
                evidence.append(Evidence(label, state))
                abnormal |= disabled or (user_mask is not None and not user_mask & bit)
            managed = any(value is not None for value in policies)
            evidence.append(Evidence("协议管理策略", "存在用户/电脑策略；不自动覆盖" if managed else "未发现 SecureProtocols 策略值（不代表不存在其他管理限制）"))
            recommendations = [
                "商店出现 0x80131500、一直加载或安全连接错误时，应优先检查 TLS；这不是所有打不开问题的确定原因。",
                "控制面板 → Internet 选项 → 高级 → 安全：勾选“使用 TLS 1.2”" + ("和“使用 TLS 1.3”（如果界面提供）" if supported else "；当前 Windows 不支持 TLS 1.3，不强行开启") + "，应用后关闭并重新打开商店。",
                "不要为兼容而启用 SSL、TLS 1.0/1.1，不关闭证书校验，不修改企业策略。",
                "设置勾选或注册表正常不等于连接成功；需实际打开商店并加载页面，失败时继续排查代理、时间、DNS 和 HTTPS。",
            ]
            if managed:
                recommendations.insert(0, "检测到协议管理策略，请联系管理员，不绕过灰色或锁定的选项。")
            return [self.result(DiagnosticStatus.NOTICE if abnormal or managed else DiagnosticStatus.NORMAL, evidence, recommendations)]
        except (OSError, ValueError, AttributeError):
            return [self.result(DiagnosticStatus.UNKNOWN, [Evidence("检查状态", "无法可靠读取 TLS 配置")], ["请手动检查 Internet 选项；读取失败不代表 TLS 已关闭。"])]

    def result(self, status, evidence, recommendations):
        return DiagnosticResult(self.check_id, "网络或Wi-Fi异常", self.display_name, status, Severity.LOW,
                                evidence, "只读检查用户 Internet 选项、协议策略和 Schannel 显式禁用项；不修改系统安全配置，也不代替真实 TLS 握手或商店启动验证。",
                                "高（已读取配置）；未知（实际连接）", recommendations)
