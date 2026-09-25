from __future__ import annotations

import locale
import platform
import re
import socket
import subprocess
from collections.abc import Callable
from datetime import datetime
from typing import Any

import psutil

from .models import UNAVAILABLE, SystemSnapshot

ProgressCallback = Callable[[int, str], None]


def collect_system_info(progress: ProgressCallback | None = None) -> SystemSnapshot:
    """Collect a best-effort snapshot; every probe is isolated from failures."""
    callback = progress or (lambda _percent, _message: None)
    probes: list[tuple[str, Callable[[], Any]]] = [
        ("windows_version", _windows_version),
        ("architecture", lambda: platform.machine() or UNAVAILABLE),
        ("cpu", _cpu_name),
        ("logical_cores", lambda: str(psutil.cpu_count(logical=True) or UNAVAILABLE)),
        ("memory", _memory),
        ("disks", _disks),
        ("gpu", _gpu),
        ("network_interfaces", _network_interfaces),
        ("gateway", _gateway_status),
        ("dns_status", _dns_status),
        ("current_time", lambda: datetime.now().astimezone().isoformat(timespec="seconds")),
        ("boot_time", lambda: datetime.fromtimestamp(psutil.boot_time()).astimezone().isoformat(timespec="seconds")),
    ]
    labels = {
        "windows_version": "读取 Windows 版本",
        "architecture": "读取系统架构",
        "cpu": "读取处理器信息",
        "logical_cores": "读取处理器核心数",
        "memory": "读取内存状态",
        "disks": "读取磁盘空间",
        "gpu": "读取显卡信息",
        "network_interfaces": "检查网络接口",
        "gateway": "检测默认网关",
        "dns_status": "检测 DNS 解析",
        "current_time": "记录当前时间",
        "boot_time": "读取开机时间",
    }
    values: dict[str, Any] = {}
    total = len(probes)
    for index, (key, probe) in enumerate(probes, start=1):
        callback(int((index - 1) / total * 100), labels[key])
        values[key] = _safe_probe(probe)
    callback(100, "收集完成")

    memory = values.get("memory")
    gateway = values.get("gateway")
    return SystemSnapshot(
        windows_version=_string(values.get("windows_version")),
        architecture=_string(values.get("architecture")),
        cpu=_string(values.get("cpu")),
        logical_cores=_string(values.get("logical_cores")),
        memory_total=_string(memory[0]) if isinstance(memory, tuple) else UNAVAILABLE,
        memory_usage=_string(memory[1]) if isinstance(memory, tuple) else UNAVAILABLE,
        disks=_string(values.get("disks")),
        gpu=_string(values.get("gpu")),
        network_interfaces=_string(values.get("network_interfaces")),
        gateway_reachable=_string(gateway) if gateway else UNAVAILABLE,
        dns_status=_string(values.get("dns_status")),
        current_time=_string(values.get("current_time")),
        boot_time=_string(values.get("boot_time")),
    )


def _safe_probe(probe: Callable[[], Any]) -> Any:
    try:
        value = probe()
        return value if value not in (None, "") else UNAVAILABLE
    except Exception:  # noqa: BLE001 - each independent probe must fail closed
        return UNAVAILABLE


def _string(value: Any) -> str:
    return value if isinstance(value, str) and value else UNAVAILABLE


def _windows_version() -> str:
    if platform.system() != "Windows":
        return f"{platform.system()} {platform.release()} {platform.version()}"
    edition = platform.win32_edition()
    release = platform.release()
    version = platform.version()
    return " ".join(item for item in ("Windows", edition, release, version) if item)


def _cpu_name() -> str:
    name = _registry_cpu_name()
    if name:
        return name
    output = _run_powershell("(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)")
    return output or platform.processor().strip() or UNAVAILABLE


def _memory() -> tuple[str, str]:
    memory = psutil.virtual_memory()
    return (_format_bytes(memory.total), f"{memory.percent:.1f}%")


def _disks() -> str:
    rows: list[str] = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (OSError, PermissionError):
            continue
        rows.append(
            f"{partition.device or partition.mountpoint} 总计 {_format_bytes(usage.total)}，剩余 {_format_bytes(usage.free)}"
        )
    return "\n".join(rows) or UNAVAILABLE


def _gpu() -> str:
    registry_names = _registry_gpu_names()
    if registry_names:
        return "；".join(registry_names)
    output = _run_powershell(
        "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"
    )
    names = [line.strip() for line in output.splitlines() if line.strip()]
    return "；".join(dict.fromkeys(names)) or UNAVAILABLE


def _registry_cpu_name() -> str:
    if platform.system() != "Windows":
        return ""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ) as key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except (OSError, ImportError):
        return ""


def _registry_gpu_names() -> list[str]:
    if platform.system() != "Windows":
        return []
    names: list[str] = []
    try:
        import winreg

        class_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, class_path) as class_key:
            for index in range(winreg.QueryInfoKey(class_key)[0]):
                subkey_name = winreg.EnumKey(class_key, index)
                try:
                    with winreg.OpenKey(class_key, subkey_name) as adapter_key:
                        value = str(winreg.QueryValueEx(adapter_key, "DriverDesc")[0]).strip()
                except OSError:
                    continue
                if value and value not in names:
                    names.append(value)
    except (OSError, ImportError):
        return []
    return names


def _network_interfaces() -> str:
    stats = psutil.net_if_stats()
    rows: list[str] = []
    for name in sorted(stats):
        item = stats[name]
        state = "已连接" if item.isup else "未连接"
        speed = f"，速率 {item.speed} Mbps" if item.speed and item.speed > 0 else ""
        rows.append(f"{name}：{state}{speed}")
    return "\n".join(rows) or UNAVAILABLE


def _gateway_status() -> str:
    output = subprocess.run(
        ["route", "print", "-4"],
        capture_output=True,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
        timeout=8,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout
    match = re.search(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d{1,3}(?:\.\d{1,3}){3})", output, re.MULTILINE)
    if not match:
        return "未检测到默认网关"
    gateway = match.group(1)
    completed = subprocess.run(
        ["ping", "-n", "1", "-w", "1500", gateway],
        capture_output=True,
        timeout=4,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return "可达" if completed.returncode == 0 else "未响应"


def _dns_status() -> str:
    socket.getaddrinfo("www.microsoft.com", 443, type=socket.SOCK_STREAM)
    return "正常"


def _run_powershell(script: str) -> str:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=12,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"
