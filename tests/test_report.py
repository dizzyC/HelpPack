from pathlib import Path

from helppack.models import (
    UNAVAILABLE,
    Attachment,
    ProblemDetails,
    ReportBundle,
    SystemSnapshot,
)
from helppack.report import generate_markdown


def make_bundle(tmp_path: Path | None = None) -> ReportBundle:
    attachments = []
    if tmp_path is not None:
        image = tmp_path / "screen.png"
        image.write_bytes(b"fake png")
        attachments = [Attachment(image, "screen.png")]
    return ReportBundle(
        problem=ProblemDetails(
            category="软件无法启动或崩溃",
            title="示例故障",
            description="启动后立即退出",
            preceding_actions="安装了更新",
            attempted_solutions="已经重启",
        ),
        snapshot=SystemSnapshot(
            windows_version="Windows 11",
            architecture="AMD64",
            cpu="Example CPU",
            logical_cores="16",
            memory_total="32.0 GB",
            memory_usage="42.0%",
            disks="C: 总计 1 TB，剩余 500 GB",
            gpu="Example GPU",
            network_interfaces="以太网：已连接",
            gateway_reachable="可达",
            dns_status="正常",
            current_time="2026-09-25T10:00:00+08:00",
            boot_time="2026-09-25T08:00:00+08:00",
        ),
        attachments=attachments,
    )


def test_generates_structured_markdown(tmp_path: Path) -> None:
    report = generate_markdown(make_bundle(tmp_path))
    for heading in (
        '## Problem Summary',
        '## Your Description',
        '## Actions Already Tried',
        '## System Environment',
        '## Hardware and Resources',
        '## Network Checks',
        '## Attachments',
        '## Privacy Notes',
    ):
        assert heading in report
    assert "not confirmed causes" in report
    assert "screen.png" in report
    assert str(tmp_path) not in report


def test_can_exclude_system_fields() -> None:
    report = generate_markdown(make_bundle(), included_fields=["windows_version"])
    assert 'Windows Version: Windows 11' in report
    assert "Example CPU" not in report


def test_unavailable_value_is_rendered() -> None:
    bundle = make_bundle()
    bundle.snapshot.gpu = UNAVAILABLE
    assert 'Graphics: Unable to read' in generate_markdown(bundle)
