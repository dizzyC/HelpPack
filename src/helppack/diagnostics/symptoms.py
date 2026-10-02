from __future__ import annotations

from .checks import default_checks
from .engine import DiagnosticEngine
from .models import DiagnosticStatus

PRESETS = ("电脑突然变卡", "软件打开就退出", "只有某个网站打不开", "连上Wi-Fi却不能上网", "耳机连接成功但没有声音", "打印机无法打印", "蓝屏或异常重启")
RULES = (
    (("卡", "慢", "性能", "发热"), "系统卡顿"),
    (("软件", "程序", "闪退", "退出", "安装", "无响应"), "软件或浏览器异常"),
    (("网站", "网页", "网络", "wifi", "wi-fi", "上网", "dns"), "网络或Wi-Fi异常"),
    (("耳机", "声音", "音频", "扬声器"), "声音问题"),
    (("蓝牙",), "蓝牙问题"),
    (("打印",), "打印机问题"),
    (("蓝屏", "重启", "死机"), "蓝屏或异常重启"),
    (("商店", "store"), "Microsoft Store 问题"),
)


def route_symptom(text: str) -> list[str]:
    normalized = text.casefold().strip()
    if not normalized:
        raise ValueError("请先描述你遇到的症状")
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
