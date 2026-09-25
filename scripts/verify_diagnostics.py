from __future__ import annotations

import ipaddress
import json
import os
import platform
import re
from pathlib import Path

from helppack.diagnostics import DiagnosticEngine
from helppack.diagnostics.repairs import ALLOWED_STARTUP_KEYS, PROXY_KEY, PROXY_VALUES
from helppack.diagnostics.reporting import generate_diagnostic_markdown


def registry_snapshot() -> dict[str, object]:
    if platform.system() != "Windows":
        return {"supported": False}
    import winreg

    snapshot: dict[str, object] = {"supported": True, "keys": {}}
    targets = [(path, None) for path in sorted(ALLOWED_STARTUP_KEYS)] + [(PROXY_KEY, PROXY_VALUES)]
    for key_path, names in targets:
        values = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_QUERY_VALUE) as key:
                if names is None:
                    names = tuple(winreg.EnumValue(key, index)[0] for index in range(winreg.QueryInfoKey(key)[1]))
                for name in names:
                    try:
                        value, value_type = winreg.QueryValueEx(key, name)
                        values[name] = {"value": value, "type": value_type}
                    except OSError:
                        values[name] = {"missing": True}
        except OSError:
            values["<key>"] = {"missing": True}
        snapshot["keys"][key_path] = values
    return snapshot


def main() -> int:
    before = registry_snapshot()
    progress_log = []
    summary = DiagnosticEngine().scan(
        "综合检查",
        progress=lambda percent, message: progress_log.append({"percent": percent, "message": message}),
    )
    after = registry_snapshot()
    if before != after:
        raise AssertionError("L0 扫描前后启动项或代理配置发生变化")

    report_text = generate_diagnostic_markdown(summary)
    sensitive_literals = [os.environ.get("USERNAME", ""), str(Path.home())]
    if any(value and value.casefold() in report_text.casefold() for value in sensitive_literals):
        raise AssertionError("诊断报告包含用户名或用户目录")
    ipv4_candidates = re.findall(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", report_text)
    valid_ipv4_leaks = []
    for candidate in ipv4_candidates:
        try:
            ipaddress.IPv4Address(candidate)
            valid_ipv4_leaks.append(candidate)
        except ipaddress.AddressValueError:
            continue
    leak_patterns = [
        r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])",
        r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])",
    ]
    if valid_ipv4_leaks or any(re.search(pattern, report_text) for pattern in leak_patterns):
        raise AssertionError("诊断报告包含未脱敏的 IP、MAC 或邮箱")

    output = Path("dist") / "validation" / "diagnostic_scan.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report_text, encoding="utf-8", newline="\n")
    statuses: dict[str, int] = {}
    for item in summary.results:
        statuses[item.status.value] = statuses.get(item.status.value, 0) + 1
    result = {
        "status": "ok",
        "category": summary.category,
        "cancelled": summary.cancelled,
        "checks": len(summary.results),
        "statuses": statuses,
        "registry_snapshot_unchanged": True,
        "repair_actions_executed": 0,
        "privacy_scan_passed": True,
        "report": str(output.resolve()),
        "progress_events": len(progress_log),
        "check_ids": [item.check_id for item in summary.results],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
