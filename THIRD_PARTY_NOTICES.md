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

The local Qt Multimedia build includes FFmpeg backend DLLs such as avcodec-61, avformat-61, avutil-59 and swresample-5. These are not covered by HelpPack's MIT license. Exact attribution, source availability and LGPL replacement/relinking obligations still need distribution review. This task does not upload the EXE or create a Release.

Official references: [Python](https://docs.python.org/3/license.html), [Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html), [Qt 6.8 Multimedia](https://doc.qt.io/qt-6.8/qtmultimedia-index.html#licenses-and-attributions), [psutil](https://github.com/giampaolo/psutil/blob/master/LICENSE), [pytest](https://github.com/pytest-dev/pytest/blob/main/LICENSE), [Ruff](https://github.com/astral-sh/ruff/blob/main/LICENSE), [PyInstaller](https://pyinstaller.org/en/stable/license.html).
