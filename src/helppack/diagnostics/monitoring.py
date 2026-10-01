from __future__ import annotations

import time
from collections import deque
from datetime import datetime

import psutil


class ResourceSampler:
    def __init__(self):
        self.previous = None
        psutil.cpu_percent()

    def sample(self, elapsed: float) -> dict:
        start = time.perf_counter()
        def read_counter(function):
            try:
                return function()
            except (OSError, psutil.Error):
                return None
        disk, net = read_counter(psutil.disk_io_counters), read_counter(psutil.net_io_counters)
        counters = (disk.read_bytes if disk else None, disk.write_bytes if disk else None, net.bytes_recv if net else None, net.bytes_sent if net else None)
        rates = [0.0 if current is not None else None for current in counters]
        if self.previous:
            previous_time, previous_values = self.previous
            period = max(elapsed - previous_time, 0.001)
            rates = [max(0, current - old) / period if current is not None and old is not None else None for current, old in zip(counters, previous_values, strict=True)]
        self.previous = (elapsed, counters)
        return {"elapsed": elapsed, "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "cpu_percent": psutil.cpu_percent(), "memory_percent": psutil.virtual_memory().percent,
                "disk_read_Bps": rates[0], "disk_write_Bps": rates[1], "net_recv_Bps": rates[2], "net_send_Bps": rates[3],
                "sampler_ms": round((time.perf_counter() - start) * 1000, 3)}


class MonitorBuffer:
    def __init__(self, window_seconds: int = 600, max_seconds: int = 7200):
        self.window_seconds = min(max(window_seconds, 1), 600)
        self.max_seconds = min(max(max_seconds, 1), 7200)
        self.samples = deque()
        self.incidents: list[dict] = []
        self.stopped = False

    def append(self, sample: dict) -> bool:
        elapsed = sample["elapsed"]
        if self.stopped or elapsed > self.max_seconds:
            self.stopped = True
            return False
        self.samples.append(sample)
        while self.samples and self.samples[0]["elapsed"] < elapsed - self.window_seconds:
            self.samples.popleft()
        for incident in self.incidents:
            if incident["at"] < elapsed <= incident["at"] + 30:
                incident["samples"].append(sample)
            if elapsed >= incident["at"] + 30:
                incident["complete"] = True
        return True

    def mark_incident(self) -> dict:
        if not self.samples:
            raise ValueError("尚未取得采样，稍后再标记")
        if len(self.incidents) >= 50:
            raise ValueError("本次已标记 50 个片段，请停止并保存")
        elapsed = self.samples[-1]["elapsed"]
        incident = {"at": elapsed, "time": self.samples[-1]["time"], "complete": False,
                    "samples": [s.copy() for s in self.samples if s["elapsed"] >= elapsed - 60]}
        self.incidents.append(incident)
        return incident

    def stop(self):
        self.stopped = True

    def markdown(self) -> str:
        import json

        from ..redaction import redact_text
        value = {"recent_samples": list(self.samples), "incidents": self.incidents, "stopped": self.stopped}
        return redact_text("## 间歇性故障监测\n\n仅含资源计数，不含进程/网络目标。首次速率是采样基线；null 表示该计数无法读取，不是零活动。前后片段不证明故障原因；停止时未采满后 30 秒的片段保留 complete=false 状态。\n\n```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```")
