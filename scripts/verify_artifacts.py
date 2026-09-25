from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QColor, QImage

from helppack.attachments import add_attachments
from helppack.collector import collect_system_info
from helppack.exporter import export_markdown, export_zip, safe_timestamp
from helppack.models import ProblemDetails, ReportBundle
from helppack.report import generate_markdown


def main() -> int:
    output_dir = Path("dist") / "validation"
    output_dir.mkdir(parents=True, exist_ok=True)
    screenshot = output_dir / "verification_screen.png"
    image = QImage(64, 40, QImage.Format.Format_RGB32)
    image.fill(QColor("#2467B7"))
    if not image.save(str(screenshot), "PNG"):
        raise RuntimeError("无法创建验证截图")

    problem = ProblemDetails(
        category="软件无法启动或崩溃",
        title="端到端验证",
        description=(
            f"截图原路径：{screenshot.resolve()}，联系 test.user@example.com，"
            "网络地址 192.0.2.8 和 2001:db8::8，MAC AA-BB-CC-DD-EE-FF，"
            "Authorization: Bearer fake.header.signature，GitHub ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456，"
            "API_KEY=FAKE-KEY-123456789，PaSsWoRd=should-not-leak，nested={token:FAKE-NESTED-TOKEN}"
        ),
        preceding_actions="启动验证构建",
        attempted_solutions="尚未尝试",
    )
    bundle = ReportBundle(
        problem=problem,
        snapshot=collect_system_info(),
        attachments=add_attachments([], [screenshot]),
    )
    report = generate_markdown(bundle)
    required_placeholders = {"<USER_PATH>", "<EMAIL>", "<IP_ADDRESS>", "<MAC_ADDRESS>", "<REDACTED_SECRET>"}
    if not all(token in report for token in required_placeholders):
        raise AssertionError("报告未包含预期脱敏占位符")
    forbidden_values = (
        str(screenshot.resolve()),
        "test.user@example.com",
        "192.0.2.8",
        "2001:db8::8",
        "AA-BB-CC-DD-EE-FF",
        "fake.header.signature",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "FAKE-KEY-123456789",
        "should-not-leak",
        "FAKE-NESTED-TOKEN",
    )
    for forbidden in forbidden_values:
        if forbidden in report:
            raise AssertionError(f"报告仍含敏感样例：{forbidden}")

    report_path = export_markdown(report, output_dir / "verified_report.md")
    generated = datetime.now().astimezone()
    zip_path = export_zip(
        report,
        bundle,
        output_dir / f"HelpPack_{safe_timestamp(generated)}.zip",
        generated_at=generated,
    )
    if not __import__("re").fullmatch(r"HelpPack_\d{8}_\d{6}\.zip", zip_path.name):
        raise AssertionError("ZIP 文件名不符合安全格式")
    with zipfile.ZipFile(zip_path) as archive:
        expected_names = {"report.md", "attachments/verification_screen.png", "manifest.json"}
        if set(archive.namelist()) != expected_names:
            raise AssertionError(f"ZIP 结构异常：{archive.namelist()}")
        manifest_bytes = archive.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        serialized = json.dumps(manifest, ensure_ascii=False)
        if str(screenshot.resolve()) in serialized or ":\\" in serialized:
            raise AssertionError("manifest 包含绝对路径")
        if any(value in serialized or value in zip_path.name for value in forbidden_values):
            raise AssertionError("manifest 或 ZIP 文件名包含敏感样例")
        for entry in manifest["files"]:
            actual = hashlib.sha256(archive.read(entry["name"])).hexdigest()
            if actual != entry["sha256"]:
                raise AssertionError(f"SHA-256 不一致：{entry['name']}")

    result = {
        "status": "ok",
        "report": str(report_path.resolve()),
        "zip": str(zip_path.resolve()),
        "zip_entries": sorted(expected_names),
        "verified_hashes": len(manifest["files"]),
        "redaction_placeholders": sorted(required_placeholders),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
