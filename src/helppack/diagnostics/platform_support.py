from __future__ import annotations

import platform
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlatformSupport:
    supported: bool
    label: str
    reason: str


def detect_windows_support(system: str | None = None, release: str | None = None) -> PlatformSupport:
    system = system if system is not None else platform.system()
    release = release if release is not None else platform.release()
    if system != "Windows":
        return PlatformSupport(False, f"{system} {release}".strip(), "本机诊断第一版仅支持 Windows。")
    normalized = release.strip().lower()
    if normalized.startswith("10"):
        return PlatformSupport(True, "Windows 10", "使用 Windows 10 兼容检查路径。")
    if normalized.startswith("11"):
        return PlatformSupport(True, "Windows 11", "使用 Windows 11 兼容检查路径。")
    return PlatformSupport(False, f"Windows {release}".strip(), "此 Windows 版本未纳入第一版验证范围。")
