"""Collect upstream license notices for the exact bundled versions; no system changes."""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "distribution-licenses"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "HelpPack-license-packaging"})
    with urllib.request.urlopen(request, timeout=60) as response:
        if not response.url.startswith("https://"):
            raise ValueError("Only HTTPS license sources are permitted")
        return response.read(8 * 1024 * 1024)


def prepare():
    manifest_path = OUT / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if all(hashlib.sha256((OUT / row["path"]).read_bytes()).hexdigest() == row["sha256"] for row in manifest):
            print("Distribution notices: verified cached material", flush=True)
            return
        raise ValueError("License material changed; refusing to package unverified files")
    OUT.mkdir(parents=True, exist_ok=True)
    downloads = []
    for repository, ref in (("qtbase", "v6.8.3"), ("qtdeclarative", "v6.8.3"),
                            ("qtimageformats", "v6.8.3"), ("qtmultimedia", "v6.8.3"),
                            ("qtsvg", "v6.8.3"), ("pyside-setup", "v6.8.3")):
        owner = "pyside" if repository == "pyside-setup" else "qt"
        tree = json.loads(fetch(f"https://api.github.com/repos/{owner}/{repository}/git/trees/{ref}?recursive=1"))
        if tree.get("truncated"):
            raise ValueError("Upstream tree is incomplete")
        for row in tree["tree"]:
            path = row["path"]
            name = Path(path).name.lower()
            if row["type"] == "blob" and (path.startswith("LICENSES/") or
                    ("3rdparty/" in path and (name.startswith(("license", "copying", "copyright", "readme")) or name == "notice"))):
                downloads.append((f"upstream/{repository}/{path}", f"https://raw.githubusercontent.com/{owner}/{repository}/{ref}/{path}"))
        print(f"Reviewed license tree: {repository} {ref}", flush=True)
    for name in ("COPYING.LGPLv2.1", "COPYING.LGPLv3", "COPYING.GPLv3", "LICENSE.md"):
        downloads.append((f"upstream/ffmpeg-7.1/{name}", f"https://raw.githubusercontent.com/FFmpeg/FFmpeg/n7.1/{name}"))
    downloads.append(("upstream/psutil-7.2.2/LICENSE", "https://raw.githubusercontent.com/giampaolo/psutil/release-7.2.2/LICENSE"))

    def download(item):
        relative, url = item
        payload = fetch(url)
        path = OUT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != payload:
            raise ValueError("Do not overwrite existing license material")
        path.write_bytes(payload)
        return {"path": relative, "url": url, "sha256": hashlib.sha256(payload).hexdigest()}
    with ThreadPoolExecutor(max_workers=6) as pool:
        manifest = list(pool.map(download, downloads))
    local_material = {
        "HelpPack-MIT.txt": (ROOT / "LICENSE").read_bytes(),
        "Python-3.12.txt": (Path(sys.base_prefix) / "LICENSE.txt").read_bytes(),
        "PyInstaller-bootloader.txt": (Path(sys.prefix) / "Lib/site-packages/pyinstaller-6.22.3.dist-info/licenses/COPYING.txt").read_bytes(),
        "SOURCE-AND-REBUILD.md": SOURCE.encode("utf-8"),
    }
    for relative, payload in local_material.items():
        (OUT / relative).write_bytes(payload)
        manifest.append({"path": relative, "url": "local upstream license or packaging instructions", "sha256": hashlib.sha256(payload).hexdigest()})
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with zipfile.ZipFile(OUT.parent / "HelpPack-Third-Party-Licenses.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for row in manifest:
            archive.write(OUT / row["path"], row["path"])
        archive.write(manifest_path, "manifest.json")
    print(f"Distribution notices: {len(manifest)} files; hashes recorded; source links included", flush=True)


SOURCE = """# Source and library replacement

HelpPack is MIT licensed; bundled libraries retain their separate licenses.
Qt/PySide6 6.8.3 and Shiboken use LGPL v3 where applicable; FFmpeg 7.1 reports
LGPL 2.1 or later, with no --enable-gpl, --enable-nonfree or external libraries.
This distribution elects LGPL v3 for LGPL 2.1-or-later components.
Unused Qt Virtual Keyboard, Qt PDF and their plugins are excluded.

Exact corresponding upstream source, including license/copyright files:
- Qt 6.8.3: https://download.qt.io/archive/qt/6.8/6.8.3/single/qt-everywhere-src-6.8.3.tar.xz
- PySide6 / Shiboken 6.8.3: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/
- FFmpeg 7.1: https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz
- Python 3.12.14: https://www.python.org/ftp/python/3.12.14/Python-3.12.14.tar.xz
- psutil 7.2.2: https://github.com/giampaolo/psutil/tree/release-7.2.2
- PyInstaller 6.22.3: https://github.com/pyinstaller/pyinstaller/tree/v6.22.3
- HelpPack source and build files: https://github.com/dizzyC/HelpPack
  Select the source commit for your edition given next to the Release binaries.

The Release supplies upstream source directions alongside the executables.
Shared Qt/FFmpeg DLLs are dynamically loaded, not incorporated into HelpPack code.
You may modify/rebuild these libraries and HelpPack and reverse-engineer the
combined application for debugging modifications to those libraries. HelpPack
adds no prohibition on those rights, no signing lock and no automatic updater.
For a replacement build, check out your edition's source commit, use Python 3.12,
follow README's virtual-environment setup, build Qt/PySide6/FFmpeg from the matching
sources following their upstream build instructions, install replacement libraries
in that environment, then run build.ps1. PyInstaller repackages the replacements.
For experimenting with dynamic-library replacements use PyInstaller's onedir mode
with the same application entry point; compatible DLLs can then be replaced there.
Modified-library rebuilding has not been tested as a supported user repair feature.

Full notices are embedded under licenses/ in the PyInstaller runtime archive and
are also supplied as HelpPack-Third-Party-Licenses.zip. Retain the notices when
redistributing. Upstream component licenses, not HelpPack's MIT license, govern
those components. This inventory is not a legal opinion or patent clearance.
"""


if __name__ == "__main__":
    prepare()
