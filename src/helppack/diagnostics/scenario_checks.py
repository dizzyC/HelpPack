"""Evidence-bearing scene checks shared by both editions."""
from __future__ import annotations

import json
import socket
from datetime import datetime

import psutil

from ..plan_resources import tr
from .models import (
    DiagnosticResult,
    DiagnosticStatus,
    Evidence,
    RepairSuggestion,
    RollbackCapability,
    SafetyLevel,
    Severity,
)


def result(check_id, category, title, abnormal, evidence, recommendations, actions=()):
    return DiagnosticResult(check_id, category, title, DiagnosticStatus.NOTICE if abnormal else DiagnosticStatus.NORMAL,
                            Severity.MEDIUM if abnormal else Severity.INFO, evidence, tr("performance_limit") if category == "系统卡顿" else tr("network_limits"),
                            "中", recommendations, repair_suggestions=list(actions))


class NetworkSceneCheck:
    check_id = "network.scene"
    categories = frozenset({"网络或Wi-Fi异常", "Microsoft Store 问题"})
    explicit_only = True

    def __init__(self, url="https://www.microsoft.com/", scope="all_sites", resolver=None, https=None):
        from .network_layers import probe_https, validate_target
        self.url, self.host = validate_target(url)
        if scope not in {"all_sites", "one_site", "wifi"}:
            raise ValueError(tr("unsupported"))
        self.scope, self.display_name = scope, tr("network_title")
        self.resolver = resolver or (lambda host: [r[4][0] for r in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)])
        self.https = https or probe_https

    def run(self, context):
        from .network_layers import investigate_network
        evidence, actions, recommendations = [], [], []
        report = investigate_network(self.url, "", context.cancel_event, lambda *_: context.ensure_not_cancelled(), context.runner,
                                     resolver=self.resolver, https=self.https)
        evidence.append(Evidence(tr("network_title"), report.markdown()))
        evidence.append(Evidence(tr("network_scope"), tr(self.scope)))
        evidence.append(Evidence(tr("system_time"), datetime.now().astimezone().isoformat()))
        dns, connections = {}, {}
        for host in dict.fromkeys([self.host, "www.microsoft.com", "www.bing.com"]):
            context.ensure_not_cancelled()
            try:
                dns[host] = bool(self.resolver(host))
            except OSError:
                dns[host] = False
            context.ensure_not_cancelled()
            connections[host] = self.https("https://" + host + "/", False)[0]
        refs = ["www.microsoft.com", "www.bing.com"]
        if not any(dns[h] for h in refs):
            recommendations.append(tr("dns_hint"))
            actions.append(RepairSuggestion("flush_dns_cache", tr("flush"), {}, SafetyLevel.L1, False,
                           tr("flush_impact"), "ipconfig.exe /flushdns", tr("never"), RollbackCapability.NONE,
                           evidence_ids=[self.check_id], estimated_seconds=30))
        if any(connections[h] for h in refs) and not connections[self.host]:
            recommendations.append(tr("target_only"))
        direct = self.https(self.url, True)[0]
        if direct != connections[self.host]:
            recommendations.append(tr("proxy_hint"))
        if dns[self.host] and not connections[self.host]:
            recommendations.append(tr("https_hint"))
        evidence.append(Evidence("DNS / HTTPS", json.dumps({"dns": dns, "https": connections}, sort_keys=True)))
        return [result(self.check_id, "网络或Wi-Fi异常", self.display_name,
                       not all(dns.values()) or not all(connections.values()), evidence, recommendations or [tr("network_limits")], actions)]


def sustained_pressure(samples):
    def high(key):
        values = [s.get(key) for s in samples]
        if any(v is None for v in values):
            return None
        return sum(v >= 90 for v in values) >= max(3, int(len(values) * 0.67))
    return {"cpu": high("cpu"), "memory": high("memory"), "disk": high("disk")}


def continuous_performance(context, count=6):
    samples = []
    psutil.cpu_percent(None)
    processes = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            p.cpu_percent(None)
            processes.append(p)
        except psutil.Error:
            continue
    last_disk = psutil.disk_io_counters()
    for _ in range(count):
        context.wait(1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_io_counters()
        busy = getattr(disk, "busy_time", None)
        before_busy = getattr(last_disk, "busy_time", None)
        samples.append({"cpu": psutil.cpu_percent(None), "memory": memory.percent,
                        "available_gib": round(memory.available / 2**30, 2),
                        "disk": min(100, max(0, (busy - before_busy) / 10)) if busy is not None and before_busy is not None else None,
                        "disk_read_mib": round(max(0, disk.read_bytes - last_disk.read_bytes) / 2**20, 2) if disk and last_disk else None,
                        "disk_write_mib": round(max(0, disk.write_bytes - last_disk.write_bytes) / 2**20, 2) if disk and last_disk else None})
        last_disk = disk
    top = []
    for p in processes:
        try:
            if p.pid and p.name().lower() != "system idle process":
                top.append({"pid": p.pid, "name": p.name(), "cpu_average": p.cpu_percent(None), "rss_mib": round(p.memory_info().rss / 2**20)})
        except psutil.Error:
            continue
    top.sort(key=lambda p: p["cpu_average"], reverse=True)
    pressure = sustained_pressure(samples)
    return [result("performance.resources", "系统卡顿", tr("performance_title"), any(v is True for v in pressure.values()),
                   [Evidence(tr("performance_title"), json.dumps(samples)), Evidence(tr("processes"), json.dumps(top[:8])),
                    Evidence(tr("performance_title"), tr("sustained", count, pressure["cpu"], pressure["memory"], pressure["disk"]))], [tr("performance_limit")])]


class SafeServiceCheck:
    check_id = "services.safe_eligibility"
    display_name = tr("service_title")
    categories = frozenset({"声音问题", "蓝牙问题", "打印机问题", "Windows更新问题"})

    def run(self, context):
        from .repair_actions import service_state
        selected = {"声音问题": ("AudioEndpointBuilder", "Audiosrv"), "蓝牙问题": ("bthserv",),
                    "打印机问题": ("Spooler",), "Windows更新问题": ("wuauserv", "BITS", "cryptsvc")}
        names = selected.get(context.category, ())  # Never start generic services during a general scan.
        evidence, actions = [], []
        unreadable = False
        for name in names:
            context.ensure_not_cancelled()
            try:
                state = service_state(context.runner, name)
                evidence.append(Evidence(name, json.dumps(state)))
                if state["StartMode"] == "Auto" and state["State"] == "Stopped":
                    actions.append(RepairSuggestion("service_start", tr("automatic", name), {"service_name": name}, SafetyLevel.L2, True,
                                   tr("service_impact"), f"Start-Service -Name '{name}'", tr("best"), RollbackCapability.BEST_EFFORT,
                                   evidence_ids=[self.check_id], estimated_seconds=90))
            except (OSError, ValueError, RuntimeError):
                unreadable = True
                evidence.append(Evidence(name, tr("unavailable")))
        finding = result(self.check_id, context.category, self.display_name, bool(actions), evidence, [tr("service_impact")], actions)
        if not actions and (unreadable or not names):
            finding.status = DiagnosticStatus.UNKNOWN
        return [finding]


class CachePreviewCheck:
    check_id = "cache.allowlisted"
    display_name = tr("cache_title")
    categories = frozenset({"系统卡顿", "软件或浏览器异常"})

    def run(self, context):
        from .repair_actions import CacheHandler
        handler = CacheHandler()
        evidence, actions = [], []
        unreadable = False
        for cache_id in handler.roots:
            context.ensure_not_cancelled()
            try:
                state = handler.snapshot({"cache_id": cache_id})
                if not state["files"]:
                    continue
                evidence.append(Evidence(cache_id, f"{state['root']} · {len(state['files'])} files · {state['total_bytes']} bytes"))
                actions.append(RepairSuggestion("quarantine_allowed_cache", tr("cache_action", cache_id), {"cache_id": cache_id}, SafetyLevel.L1, False,
                               tr("cache_impact"), state["root"], tr("full"), RollbackCapability.FULL, evidence_ids=[self.check_id], estimated_seconds=120))
            except (OSError, ValueError, RuntimeError):
                unreadable = True
                evidence.append(Evidence(cache_id, tr("cache_closed")))
        finding = result(self.check_id, context.category, self.display_name, bool(actions), evidence, [tr("cache_impact")], actions)
        if unreadable and not actions:
            finding.status = DiagnosticStatus.UNKNOWN
        return [finding]


def crash_event_script(path, name):
    # Inputs are already quoted by ps_literal. Named EventData is language independent.
    return (
        "@(Get-WinEvent -FilterHashtable @{LogName='Application';Id=@(1000,1001,1002,1026);StartTime=(Get-Date).AddDays(-7)} "
        "-MaxEvents 300 -ErrorAction SilentlyContinue | ForEach-Object {"
        "$e=$_;$xml=[xml]$e.ToXml();$d=@{};foreach($n in $xml.Event.EventData.Data){if($n.Name){$d[[string]$n.Name]=[string]$n.'#text'}};"
        f"$byPath=$d.AppPath -and [string]::Equals($d.AppPath,{path},[StringComparison]::OrdinalIgnoreCase);"
        f"$byName=(!$d.AppPath) -and [string]::Equals($d.AppName,{name},[StringComparison]::OrdinalIgnoreCase);"
        "if($byPath -or $byName){[pscustomobject]@{Time=$e.TimeCreated.ToString('o');Id=$e.Id;"
        "MatchKind=if($byPath){'ExactPath'}else{'FilenameOnly'};AppName=$d.AppName;AppPath=$d.AppPath;"
        "AppVersion=$d.AppVersion;ExceptionCode=$d.ExceptionCode;ModuleName=$d.ModuleName;ModulePath=$d.ModulePath;Message=$e.Message}}"
        "}|Select-Object -First 20)|ConvertTo-Json -Depth 4 -Compress"
    )
