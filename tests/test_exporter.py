import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from test_report import make_bundle

from helppack.exporter import export_markdown, export_zip
from helppack.report import generate_markdown


def test_export_markdown(tmp_path: Path) -> None:
    report = generate_markdown(make_bundle())
    path = export_markdown(report, tmp_path / "report.md")
    assert path.read_text(encoding="utf-8") == report


def test_export_zip_contents_manifest_and_hashes(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path)
    report = generate_markdown(bundle)
    output = export_zip(
        report,
        bundle,
        tmp_path / "HelpPack_20260925_100000.zip",
        generated_at=datetime(2026, 9, 25, 10, 0, tzinfo=UTC),
    )

    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"report.md", "attachments/screen.png", "manifest.json"}
        assert archive.read("report.md").decode("utf-8") == report
        manifest = json.loads(archive.read("manifest.json"))
        serialized = json.dumps(manifest, ensure_ascii=False)
        assert str(tmp_path) not in serialized
        assert ":\\" not in serialized
        assert manifest["attachments"] == ["screen.png"]
        for entry in manifest["files"]:
            actual = hashlib.sha256(archive.read(entry["name"])).hexdigest()
            assert actual == entry["sha256"]
