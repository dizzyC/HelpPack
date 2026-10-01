from __future__ import annotations

from helppack.english import text as msg

from .checks import default_checks
from .engine import DiagnosticEngine
from .models import DiagnosticStatus

PRESETS = ("My computer suddenly became slow", "An app closes as soon as it opens", "Only one website won't open", "Connected to Wi-Fi but no internet", "Headphones connected but no sound", "My printer won't print", "Blue screen or unexpected restart")
RULES = (
    (("卡", "慢", "性能", "发热", "slow", "lag", "performance", "hot"), "系统卡顿"),
    (("软件", "程序", "闪退", "退出", "安装", "无响应", "app", "software", "crash", "closes", "install", "not responding"), "软件或浏览器异常"),
    (("网站", "网页", "网络", "wifi", "wi-fi", "上网", "dns", "website", "internet", "network"), "网络或Wi-Fi异常"),
    (("耳机", "声音", "音频", "扬声器", "headphone", "sound", "audio", "speaker"), "声音问题"),
    (("蓝牙", "bluetooth"), "蓝牙问题"),
    (("打印", "print"), "打印机问题"),
    (("蓝屏", "重启", "死机", "blue screen", "restart", "bsod"), "蓝屏或异常重启"),
    (("商店", "store"), "Microsoft Store 问题"),
)


def route_symptom(text: str) -> list[str]:
    normalized = text.casefold().strip()
    if not normalized:
        raise ValueError(msg('请先描述你遇到的症状'))
    return list(dict.fromkeys(category for words, category in RULES if any(w in normalized for w in words))) or ["综合检查"]


def diagnose_symptom(text: str, cancel, progress, runner=None):
    categories = route_symptom(text)
    checks = [c for c in default_checks() if not getattr(c, "explicit_only", False) and (
        "综合检查" in categories or any(category in c.categories for category in categories))]
    summary = DiagnosticEngine(checks, runner).scan("综合检查", cancel_event=cancel, progress=progress)
    summary.category = "症状向导：" + "、".join(categories)
    # Symptom routing is lexical and local, never a claimed AI diagnosis.
    failed = [r.display_name for r in summary.results if r.status in {DiagnosticStatus.ABNORMAL, DiagnosticStatus.NOTICE}]
    return summary, failed
