from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .models import ReportBundle


def safe_timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC).astimezone()).strftime("%Y%m%d_%H%M%S")


def export_markdown(report_text: str, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_text, encoding="utf-8", newline="\n")
    return path


def export_zip(
    report_text: str,
    bundle: ReportBundle,
    destination: str | Path,
    *,
    generated_at: datetime | None = None,
) -> Path:
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    generated = generated_at or datetime.now().astimezone()

    with tempfile.TemporaryDirectory(prefix="helppack_") as temp_dir:
        root = Path(temp_dir)
        report_path = root / "report.md"
        report_path.write_text(report_text, encoding="utf-8", newline="\n")

        files: list[Path] = [report_path]
        attachment_names: list[str] = []
        attachment_root = root / "attachments"
        for attachment in bundle.attachments:
            if not attachment.included:
                continue
            attachment_root.mkdir(exist_ok=True)
            target = attachment_root / Path(attachment.export_name).name
            shutil.copy2(attachment.export_source, target)
            files.append(target)
            attachment_names.append(target.name)

        file_entries = [
            {
                "name": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
            }
            for path in files
        ]
        manifest = {
            "app": "HelpPack",
            "app_version": __version__,
            "generated_at": generated.isoformat(timespec="seconds"),
            "attachments": attachment_names,
            "files": file_entries,
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in [*files, manifest_path]:
                archive.write(path, path.relative_to(root).as_posix())
    return output


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
