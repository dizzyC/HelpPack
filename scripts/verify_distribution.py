"""Verify release archives without launching or changing system settings."""
import hashlib
import json
import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


def verify(path):
    archive = CArchiveReader(str(path))
    names = {name.replace("\\", "/"): name for name in archive.toc}
    forbidden = {"qt6virtualkeyboard.dll", "qtvirtualkeyboardplugin.dll", "qt6pdf.dll", "qpdf.dll",
                 "report.md", "plans.jsonl", ".env"}
    assert not any(Path(name).name.lower() in forbidden for name in names)
    manifest = json.loads(archive.extract(names["licenses/manifest.json"]))
    for row in manifest:
        payload = archive.extract(names["licenses/" + row["path"]])
        assert hashlib.sha256(payload).hexdigest() == row["sha256"]
        assert str(Path.home()).encode("utf-8").lower() not in payload.lower()
    print(f"{path.name}: PASS; {len(manifest)} embedded notices verified; unused plugins excluded")


if __name__ == "__main__":
    for argument in sys.argv[1:]:
        verify(Path(argument))
