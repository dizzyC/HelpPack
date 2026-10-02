# HelpPack — English Edition

## Local Diagnostics and Repair Plans Update

Findings now include **Review Repair Plan**. Only evidence-supported candidates are offered; select actions and confirm, with separate approval for high-impact changes. Implemented candidates include safe service starts, DNS cache flushing, allowlisted cache quarantine, selected startup entries and conflict-safe recovery of app-made changes. Unsupported cases explain why and provide manual settings links, never a fixed set of unrelated commands.

See the [usage, audit and recovery matrix](docs/repair-plan-verification.md) and [actual verification results](docs/repair-plan-results.md). Following acceptance, the user separately authorized source upload; see the [upload scope and checks](docs/github-upload.md). The local build is `dist\repair-plan\HelpPack-English.exe` and is not included in source upload. Run `python -m helppack --plan-self-check dist\plan-native` for read-only native acceptance, fictional report exports and plan preview cancelled without execution.

A privacy-first Windows desktop tool for explaining computer problems, collecting relevant evidence and creating a **Support Bundle** for a friend, technician or AI.

This is the `english` branch. The [Chinese edition is on `main`](https://github.com/dizzyC/HelpPack/tree/main). English development starts from the completed local Chinese feature baseline; published `main` may not yet include all of those local additions. No merge into `main` or new Release is part of this work.

## Features

- Describe a problem, add up to five screenshots, review privacy, edit a report and export Markdown or a ZIP with `report.md`, attachments and SHA-256 manifest.
- Run read-only Diagnostics, inspect Findings and evidence, and review individual Recommended Actions.
- Use a symptom guide and targeted network, software, disk-space, audio, Bluetooth and printer checks.
- Keep local history, compare matching checks, assign Resolved / Unresolved / Later, view an event timeline and optionally monitor resource counters.
- Crop screenshots or cover private areas in an edited copy. Originals remain unchanged. Copy a concise summary of the current preview.

See the [capability matrix](docs/diagnostic-capability-matrix.md), [usage guide](docs/usage.md), [privacy boundary](docs/privacy.md) and [English verification report](docs/verification-report.md).

## Safety and privacy

Checks are read-only by default. Repairs require individual confirmation; high-risk actions require a second confirmation. Administrator rights are requested only for the selected helper action. HelpPack never restarts Windows automatically, disables certificate checks, overrides organizational policies or runs arbitrary user commands.

No account or backend server is required. Reports and backups stay local until **you** share them. Network checks contact their test targets; Windows Update driver searches contact Windows Update. Custom DNS is used only when you supply it. Local processing does not mean every check is offline.

Redaction attempts to hide usernames, home paths, IP/MAC addresses, emails and common secrets; it is not a guarantee. Screenshots are not OCR-redacted. Check every report and image before sharing. User input, file names and original logs are **not automatically translated**. Chinese paths and Unicode input are supported.

## Development setup

Requires Windows 10/11 and **Python 3.12**. Run in PowerShell from this project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

Runtime dependencies are PySide6 and psutil. pytest, Ruff and PyInstaller are development tools. No runtime translation service or localization dependency is used.

## Start

```powershell
.\run.ps1
```

Alternatively, after installation:

```powershell
.\.venv\Scripts\python.exe -m helppack
```

`run.ps1` uses this checkout's `src`, avoiding a different editable checkout. Optional `-PythonExe` selects an existing Python 3.12 environment with required dependencies. It does not install or change system settings.

To run Chinese HelpPack, use its separate `main` checkout and `run.ps1`. Do not merge English code into the Chinese checkout just to launch it.

## Test and audit

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe scripts\audit_english.py
.\.venv\Scripts\python.exe scripts\scan_release_content.py
.\.venv\Scripts\python.exe scripts\verify_english.py
```

The last command opens native Qt windows with fictional data, collects bounded read-only system information, and verifies Markdown/ZIP exports. No repairs, sound playback or printing are run. Evidence stays under ignored `dist/validation/english`. Mocked repairs do not prove real repair success.

## Single-file Windows build

```powershell
.\build.ps1
.\dist\HelpPack-English.exe
```

The checked-in `helppack.spec` uses windowed, one-file PyInstaller packaging and English version metadata. `build.ps1` accepts `-OutputDirectory`, `-WorkDirectory` and `-PythonExe`. Build outputs are ignored and not pushed.

Qt Multimedia can include FFmpeg libraries. See [third-party notices](THIRD_PARTY_NOTICES.md). The local EXE is a validation build; complete redistribution compliance and Authenticode signing remain release work. This task does not create a GitHub Release or upload an EXE.

## English edition architecture

Fixed UI, report, diagnostic, safety and error templates live in `src/helppack/english.py`. Only templates are translated before inserting opaque values. Choices display English but preserve original internal values. Action/check IDs, enums, history/config keys and manifest fields remain compatible. Saved dates keep ISO format; report dates include the UTC offset.

System probes use structured JSON/CIM/native APIs or numeric/exit-code checks. Chinese and English permission messages are recognized where needed. Human-readable localized output is never guessed as structured evidence.

## Known limitations

- No English-Windows installation is available for this run. English/Chinese parsing uses fixtures; actual read-only checks run on Chinese Windows.
- Signatures, runtime presence, completed commands or registered packages do not prove app health. Store must be opened and its content loaded by the user.
- Automatic INF installation is blocked pending signature, hardware-match and recovery validation. OEM connectors open official pages, without scraping unsupported download APIs or silently running vendor EXEs.
- Real UAC repairs, drivers, Store reset, DISM/SFC and physical sound/printing need controlled VM/hardware validation. None are run on this computer for this task.
- PAC/WPAD browser behavior is not fully simulated. HTTPS checks do not verify sign-in, scripts or downloads.
- Folder scans are bounded and skip links/inaccessible entries. Reversible same-partition cache quarantine **does not free partition space**; this is not a general cleaner.
- Bluetooth enumeration does not cover every BLE device/profile. Event and blocking logs may be incomplete.
- Monitoring retains ten minutes for at most two hours. A short live sample is not a real two-hour endurance test.
- Old Chinese history/logs remain original data. Redaction can miss private content.

## Screenshots and contributions

Screenshot/demo placeholder: use fictional data only. Native render evidence is generated locally, not published with personal diagnostics.

Contributions are welcome. Keep conclusions evidence-based, add tests, preserve internal formats and avoid unconfirmed bulk changes. Send English work to `english`, Chinese work to `main`. Never commit credentials, real reports, logs or attachments.

## License

MIT, copyright © 2026 dizzyC. See [LICENSE](LICENSE). Dependencies retain their own licenses.
