from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path

EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
MAC_RE = re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])")
IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6_CANDIDATE_RE = re.compile(
    r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?:%[\w.-]+)?(?![0-9a-f:])"
)
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
SECRET_FIELD_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|refresh[_-]?token|token|password|passwd|pwd|secret)\b"
    r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;\"']+)"
)
COMMON_KEY_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})(?![A-Za-z0-9])"
)


def redact_text(
    text: str,
    *,
    username: str | None = None,
    home_path: str | Path | None = None,
    extra_paths: list[str | Path] | None = None,
) -> str:
    """Replace common personal identifiers and secrets with explicit placeholders."""
    if not text:
        return text

    username = username if username is not None else os.environ.get("USERNAME", "")
    home = str(home_path if home_path is not None else Path.home())
    result = text

    paths = [home, *(str(p) for p in (extra_paths or []))]
    for value in sorted({p for p in paths if p}, key=len, reverse=True):
        variants = {value, value.replace("\\", "/"), value.replace("/", "\\")}
        for variant in variants:
            result = re.sub(re.escape(variant), "<USER_PATH>", result, flags=re.IGNORECASE)

    result = BEARER_RE.sub("Bearer <REDACTED_SECRET>", result)
    result = SECRET_FIELD_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}<REDACTED_SECRET>", result)
    result = COMMON_KEY_RE.sub("<REDACTED_SECRET>", result)
    result = EMAIL_RE.sub("<EMAIL>", result)
    result = MAC_RE.sub("<MAC_ADDRESS>", result)
    result = IPV4_RE.sub(_redact_valid_ipv4, result)
    result = IPV6_CANDIDATE_RE.sub(_redact_valid_ipv6, result)

    if username:
        # Windows embeds account names in task names, paths and identifiers such as
        # ``VendorUpdate_Alice``. A word-boundary check misses those values because
        # underscores are word characters, so replace the known local username
        # wherever it occurs.
        result = re.sub(re.escape(username), "<USERNAME>", result, flags=re.IGNORECASE)
    return result


def _redact_valid_ipv4(match: re.Match[str]) -> str:
    try:
        ipaddress.IPv4Address(match.group(0))
    except ipaddress.AddressValueError:
        return match.group(0)
    return "<IP_ADDRESS>"


def _redact_valid_ipv6(match: re.Match[str]) -> str:
    candidate = match.group(0)
    address = candidate.split("%", 1)[0]
    try:
        ipaddress.IPv6Address(address)
    except ipaddress.AddressValueError:
        return candidate
    return "<IP_ADDRESS>"
