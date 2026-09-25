from helppack import collector
from helppack.models import UNAVAILABLE


def test_single_probe_failure_does_not_abort_collection(monkeypatch) -> None:
    monkeypatch.setattr(collector, "_windows_version", lambda: "Windows 11")
    monkeypatch.setattr(collector, "_cpu_name", lambda: "CPU")
    monkeypatch.setattr(collector, "_memory", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(collector, "_disks", lambda: "C: 100 GB")
    monkeypatch.setattr(collector, "_gpu", lambda: "GPU")
    monkeypatch.setattr(collector, "_network_interfaces", lambda: "以太网：已连接")
    monkeypatch.setattr(collector, "_gateway_status", lambda: "可达")
    monkeypatch.setattr(collector, "_dns_status", lambda: "正常")

    snapshot = collector.collect_system_info()

    assert snapshot.windows_version == "Windows 11"
    assert snapshot.memory_total == UNAVAILABLE
    assert snapshot.memory_usage == UNAVAILABLE
    assert snapshot.gpu == "GPU"
