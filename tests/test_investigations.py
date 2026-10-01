import json
import socket
import struct
import threading
from types import SimpleNamespace

import pytest

from helppack.diagnostics.history import DiagnosticHistoryStore, compare_summaries
from helppack.diagnostics.investigation import Finding, Investigation, ps_literal, query
from helppack.diagnostics.monitoring import MonitorBuffer, ResourceSampler
from helppack.diagnostics.network_layers import (
    investigate_network,
    parse_dns,
    validate_target,
)
from helppack.diagnostics.peripherals import inspect_peripherals
from helppack.diagnostics.runner import CommandResult
from helppack.diagnostics.software_analysis import SCENARIOS, analyze_software
from helppack.diagnostics.storage_analysis import (
    FileEntry,
    MoveReceipt,
    assert_local_path,
    quarantine_one,
    recovery_receipts,
    restore_one,
    scan_directory,
)
from helppack.diagnostics.symptoms import PRESETS, route_symptom
from helppack.diagnostics.timeline import collect_timeline


class Runner:
    def __init__(self, values=None, failure=False):
        self.values = iter(values or [])
        self.failure = failure
        self.scripts = []

    def powershell_json(self, script, *, timeout):
        self.scripts.append(script)
        return CommandResult(("powershell.exe",), -1 if self.failure else 0,
                             json.dumps(next(self.values, [])), "", permission_denied=self.failure)

    def run(self, args, *, timeout):
        assert isinstance(args, list)
        return CommandResult(tuple(args), 1, "", "")


def event():
    return threading.Event()


def progress(*args):
    pass


@pytest.mark.parametrize("preset", PRESETS)
def test_symptoms_have_specific_routes(preset):
    assert route_symptom(preset) != ["综合检查"]


def test_local_symptom_multi_route_and_unknown():
    assert len(route_symptom("Wi-Fi不能上网，软件也闪退")) == 2
    assert route_symptom("不明症状") == ["综合检查"]
    with pytest.raises(ValueError):
        route_symptom(" ")


@pytest.mark.parametrize("value", ["http://example.com", "https://u:p@example.com", "https://example.com/?token=x", "https://example.com:444", "https://example.com/#x", "https://bad;cmd.com", "https://[::1]"])
def test_network_target_rejects_unsafe_input(value):
    with pytest.raises(ValueError):
        validate_target(value)


def test_dns_valid_response_and_invalid_packets():
    ident = 17
    question = b"\x07example\x03com\0" + struct.pack("!HH", 1, 1)
    packet = struct.pack("!6H", ident, 0x8180, 1, 1, 0, 0) + question
    packet += b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 30, 4) + socket.inet_aton("192.0.2.7")
    assert parse_dns(packet, ident) == ["192.0.2.7"]
    for bad, requested in ((packet[:-1], ident), (packet, 999), (b"", ident)):
        with pytest.raises(ValueError):
            parse_dns(bad, requested)


def test_network_layers_keep_failures_separate(monkeypatch):
    from helppack.diagnostics import network_layers as module

    monkeypatch.setattr(module.psutil, "net_if_stats", lambda: {"虚构网卡": SimpleNamespace(isup=True)})
    def failure(host):
        raise socket.gaierror()
    result = investigate_network("example.com", "192.0.2.53", event(), progress, runner=Runner(),
                                 resolver=failure, dns_query=lambda h, s: ["192.0.2.2"],
                                 https=lambda url, direct: (not direct, "模拟 HTTPS 响应"))
    assert {f.layer for f in result.findings} >= {"适配器", "网关", "系统 DNS", "指定 DNS", "代理", "直连 HTTPS", "目标服务"}
    assert any("系统 DNS 失败" in r for r in result.recommendations)
    assert any("代理/绕过" in r for r in result.recommendations)
    assert "192.0.2.2" not in result.markdown()
    stopped = event()
    stopped.set()
    with pytest.raises(InterruptedError):
        investigate_network("example.com", "", stopped, progress, runner=Runner())


def test_history_persistence_status_operation_and_comparison(tmp_path):
    store = DiagnosticHistoryStore(tmp_path)
    before = {"results": [{"check_id": "cpu", "display_name": "CPU", "status": "notice", "evidence": [{"label": "使用率", "value": "99%"}]}]}
    record = store.save_record({"kind": "测试", "summary": before, "report": "test@example.com", "operations": []})
    store.mark(record, "未解决")
    store.add_operation(record, {"action": "模拟确认", "result": "192.0.2.1"})
    reload = DiagnosticHistoryStore(tmp_path).load_record(record)
    assert reload["status"] == "未解决"
    assert "test@example.com" not in json.dumps(reload)
    assert "192.0.2.1" not in json.dumps(reload)
    after = json.loads(json.dumps(before))
    after["results"][0]["evidence"][0]["value"] = "10%"
    assert "99% → 10%" in " ".join(compare_summaries(before, after))
    assert "不代表" in compare_summaries(before, before)[0]
    with pytest.raises(ValueError):
        store.load_record("../../outside")
    (tmp_path / ("record_" + "a" * 32 + ".json")).write_text("[]", encoding="utf-8")
    assert len(store.list_records()) == 1


def synthetic_folder(tmp_path):
    root = tmp_path / "chosen"
    (root / "cache").mkdir(parents=True)
    (root / "cache" / "data.bin").write_bytes(b"x" * 20)
    (root / "cache" / "app.exe").write_bytes(b"x" * 5)
    (root / "document.txt").write_bytes(b"x" * 10)
    return root


def test_storage_scan_ranking_categories_cancel_and_limit(tmp_path):
    root = synthetic_folder(tmp_path)
    result = scan_directory(str(root), event(), progress)
    assert result.ranking[0] == ("cache", 25)
    assert len(result.files) == 3
    assert next(f for f in result.files if f.path.suffix == ".exe").category == "应用文件"
    assert next(f for f in result.files if f.path.suffix == ".txt").category == "用户文件/未知"
    limited = scan_directory(str(root), event(), progress, max_entries=1)
    assert limited.limited
    stopped = event()
    stopped.set()
    assert scan_directory(str(root), stopped, progress).cancelled
    with pytest.raises(ValueError):
        scan_directory("", event(), progress)


def test_cache_move_restart_restore_does_not_delete_original_data(tmp_path):
    root = synthetic_folder(tmp_path)
    scan = scan_directory(str(root), event(), progress)
    entry = next(f for f in scan.files if f.category.startswith("缓存"))
    with pytest.raises(PermissionError):
        quarantine_one(scan, entry, confirmed=False)
    receipt = quarantine_one(scan, entry, confirmed=True)
    assert not entry.path.exists() and receipt.destination.read_bytes() == b"x" * 20
    restarted = recovery_receipts(root)
    assert len(restarted) == 1
    assert len(scan_directory(str(root), event(), progress).files) == 2
    restore_one(restarted[0], confirmed=True)
    assert entry.path.read_bytes() == b"x" * 20
    assert not recovery_receipts(root)


def test_storage_rejects_changes_overwrite_and_path_forgery(tmp_path):
    root = synthetic_folder(tmp_path)
    scan = scan_directory(str(root), event(), progress)
    entry = next(f for f in scan.files if f.category.startswith("缓存"))
    entry.path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        quarantine_one(scan, entry, confirmed=True)
    with pytest.raises(ValueError):
        assert_local_path(root, root / ".." / "outside")
    forged = FileEntry(tmp_path / "outside", 1, 0, 0, "缓存")
    with pytest.raises(ValueError):
        quarantine_one(scan, forged, confirmed=True)
    with pytest.raises(ValueError):
        restore_one(MoveReceipt(root, root / "document.txt", root / "document.txt", 0), confirmed=True)


def test_storage_deduplicates_hardlinks(tmp_path):
    import os
    root = synthetic_folder(tmp_path)
    os.link(root / "document.txt", root / "document_link.txt")
    assert len(scan_directory(str(root), event(), progress).files) == 3


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_software_four_scenarios_never_execute_target(tmp_path, scenario):
    exe = tmp_path / "quoted' program.exe"
    exe.write_bytes(b"synthetic data, not executable")
    runner = Runner(values=[{"Version": "1.0"}, {"Signature": "NotSigned"}, [], [], [], []])
    result = analyze_software(str(exe), scenario, event(), progress, runner)
    assert len(result.findings) == 6
    assert "quoted'' program.exe" in runner.scripts[0]
    assert all("Start-Process" not in s for s in runner.scripts)
    assert "存在不等于" in result.markdown()
    assert "11708" in runner.scripts[3] if scenario == "安装失败" else "1000" in runner.scripts[3]


def test_read_failures_are_not_health_claims(tmp_path, monkeypatch):
    exe = tmp_path / "example.exe"
    exe.write_bytes(b"synthetic")
    software = analyze_software(str(exe), "闪退", event(), progress, Runner(failure=True))
    assert all(f.state == "权限不足" for f in software.findings)
    from helppack.diagnostics import peripherals
    def unavailable():
        raise OSError()
    monkeypatch.setattr(peripherals, "default_volume", unavailable)
    for kind in ("声音", "蓝牙", "打印机"):
        if kind == "蓝牙":
            monkeypatch.setattr(peripherals, "classic_bluetooth", unavailable)
        result = inspect_peripherals(kind, event(), progress, Runner(failure=True))
        assert "无法" in result.markdown() or "权限不足" in result.markdown()


def test_timeline_order_limits_and_non_causal_warning():
    records = [[{"Time": "2026-01-01", "Message": "synthetic crash", "Id": 1000}],
               [{"Time": "2026-01-02", "Message": "synthetic change", "Id": 19}], []]
    runner = Runner(records)
    result = collect_timeline(event(), progress, runner)
    report = result.markdown()
    assert report.index("2026-01-02") < report.index("2026-01-01")
    assert "不直接证明" in report
    assert all("-MaxEvents 150" in s for s in runner.scripts)


def test_monitor_ring_limits_markers_and_early_stop():
    buffer = MonitorBuffer()
    with pytest.raises(ValueError):
        buffer.mark_incident()
    for elapsed in range(0, 702, 2):
        buffer.append({"elapsed": elapsed, "time": "synthetic"})
    assert buffer.samples[0]["elapsed"] == 100
    marker = buffer.mark_incident()
    assert marker["samples"][0]["elapsed"] == 640
    buffer.append({"elapsed": 730, "time": "synthetic"})
    assert marker["complete"]
    buffer.mark_incident()
    buffer.stop()
    assert not buffer.append({"elapsed": 732, "time": "synthetic"})
    assert not buffer.incidents[-1]["complete"]
    assert not MonitorBuffer().append({"elapsed": 7201, "time": "synthetic"})


def test_resource_sampler_rates_and_counter_reset(monkeypatch):
    from helppack.diagnostics import monitoring
    count = iter([100, 200, 1])
    monkeypatch.setattr(monitoring.psutil, "cpu_percent", lambda: 2)
    monkeypatch.setattr(monitoring.psutil, "virtual_memory", lambda: SimpleNamespace(percent=50))
    monkeypatch.setattr(monitoring.psutil, "disk_io_counters", lambda: SimpleNamespace(read_bytes=next(count), write_bytes=0))
    monkeypatch.setattr(monitoring.psutil, "net_io_counters", lambda: SimpleNamespace(bytes_recv=0, bytes_sent=0))
    sampler = ResourceSampler()
    assert sampler.sample(0)["disk_read_Bps"] == 0
    assert sampler.sample(2)["disk_read_Bps"] == 50
    assert sampler.sample(4)["disk_read_Bps"] == 0


def test_query_timeout_and_literal_injection_are_rejected():
    class TimeoutRunner:
        def powershell_json(self, script, *, timeout):
            return CommandResult(("powershell.exe",), -1, "", "", timed_out=True)
    with pytest.raises(TimeoutError):
        query(TimeoutRunner(), "fixed")
    assert ps_literal("'; Remove-Item x") == "'''; Remove-Item x'"
    with pytest.raises(ValueError):
        ps_literal("path\ncommand")
    report = Investigation("测试", findings=[Finding("证据", "未知", "test@example.com 192.0.2.1")]).markdown()
    assert "<EMAIL>" in report and "<IP_ADDRESS>" in report


def test_missing_monitor_counter_is_unknown_not_zero(monkeypatch):
    from helppack.diagnostics import monitoring
    monkeypatch.setattr(monitoring.psutil, "disk_io_counters", lambda: None)
    sample = ResourceSampler().sample(0)
    assert sample["disk_read_Bps"] is None


def test_signature_failure_does_not_hide_version(tmp_path):
    exe = tmp_path / "synthetic.exe"
    exe.write_bytes(b"not a real EXE")
    class PartialRunner(Runner):
        def powershell_json(self, script, *, timeout):
            if "Get-AuthenticodeSignature" in script:
                return CommandResult(("powershell.exe",), 1, "", "module unavailable")
            return CommandResult(("powershell.exe",), 0, json.dumps({"Version": "1.2"}), "")
    result = analyze_software(str(exe), "闪退", event(), progress, PartialRunner())
    assert result.findings[0].state == "已读取" and "1.2" in result.findings[0].detail
    assert result.findings[1].state == "无法验证"
