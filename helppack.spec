# -*- mode: python ; coding: utf-8 -*-
import json
from pathlib import Path

license_root = Path("dist/distribution-licenses")
license_manifest = json.loads((license_root / "manifest.json").read_text(encoding="utf-8"))
license_data = [(str(license_root / row["path"]), "licenses/" + str(Path(row["path"]).parent)) for row in license_manifest]
license_data.append((str(license_root / "manifest.json"), "licenses"))

a = Analysis(
    ["helppack_launcher.py"],
    pathex=["src"],
    binaries=[],
    datas=license_data,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=1,
)
# These unrelated plugins are pulled in by Qt hooks, not used by this Widgets app.
excluded = {"qt6virtualkeyboard.dll", "qtvirtualkeyboardplugin.dll", "qt6pdf.dll", "qpdf.dll"}
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() not in excluded]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HelpPack",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
