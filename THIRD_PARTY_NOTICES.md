# Third-Party Components and Licenses

HelpPack is MIT-licensed. Dependencies keep their own licenses. Review exact packaged versions and complete license texts before distributing an EXE.

| Component | Purpose | License summary |
|---|---|---|
| Python 3.12 | Runtime | Python Software Foundation License |
| PySide6 / Qt for Python | Desktop interface | LGPLv3 / GPLv3 / commercial, according to applicable Qt terms |
| Qt Multimedia / Print Support | Audio enumeration, requested playback and confirmed printing | Applicable module terms; packaging can include FFmpeg libraries |
| psutil | System counters | BSD 3-Clause |
| pytest | Development tests | MIT |
| Ruff | Development checks | MIT |
| PyInstaller | Development packaging | GPLv2-or-later with bootloader exception |

No dependency was added for English localization. Translations are local resources. No online fonts, images or frontend assets are loaded.

The bundled FFmpeg reports version 7.1 and LGPL 2.1-or-later, without GPL, nonfree or external-library build flags. This distribution elects LGPLv3. These libraries are not covered by HelpPack's MIT license.

`scripts/prepare_distribution.py` collects 164 matching-version license and attribution files, embeds them under `licenses/` in the executable and creates `HelpPack-Third-Party-Licenses.zip`. Its `SOURCE-AND-REBUILD.md` provides exact upstream source download locations and library replacement/repackaging instructions. Modified-library rebuilding has not been tested. The formal spec excludes unused Qt Virtual Keyboard, Qt PDF and their plugins. This inventory is not legal advice or patent clearance.

Official references: [Python](https://docs.python.org/3/license.html), [Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html), [Qt 6.8 Multimedia](https://doc.qt.io/qt-6.8/qtmultimedia-index.html#licenses-and-attributions), [psutil](https://github.com/giampaolo/psutil/blob/master/LICENSE), [pytest](https://github.com/pytest-dev/pytest/blob/main/LICENSE), [Ruff](https://github.com/astral-sh/ruff/blob/main/LICENSE), [PyInstaller](https://pyinstaller.org/en/stable/license.html).
