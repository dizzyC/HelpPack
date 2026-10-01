# English Edition Verification Report

Date: 2026-10-01. Environment: Chinese Windows 11 build 26200, Python 3.12.14, PySide6 6.8.3. There is **no real English-Windows installation** in this environment.

## Automated

The inherited functional/safety tests remain in the suite. Edition-specific expectations were updated to English, without translating internal enums or Unicode input fixtures. New checks cover fixed copy, choice compatibility, bilingual symptom/permission parsing, locale-independent numeric gateway parsing, refusal to guess localized human output, Unicode Markdown/ZIP exports, unchanged manifest keys and file hashes, opaque original logs, explicit time zones and a scrollable cancel-default repair review.

Final recorded run: **131 passed**. Ruff checks passed. The preview action's minimum-size layout and translated history labels are regression-tested, including unchanged saved values.

## Actual native source workflow

`scripts/verify_english.py` opens native Windows Qt widgets and activates the actual problem/collection/preview/export flow. Read-only system collection completes in a worker while the event loop continues. Real snapshot data is replaced by fictional data before exporting or taking report screenshots.

It generates per-page renders, all eight targeted-tab renders, a narrow-window long-text render, screenshot-editor and scrollable repair-review renders. Markdown and ZIP are opened and validated; manifest keys remain compatible, all listed SHA-256 values match, Chinese paths/input/attachment names survive, edited images are exported and originals remain unchanged.

Source native run: platform `windows`, Segoe UI, 760×560 logical narrow window, visible native widget and retained `END_MARKER`. Render review found a vertically compressed Update Preview button; its field sidebar was changed to a scroll area with a separate minimum-height action button, then rerun.

Actual source rendering was checked at device-pixel ratios 1.25 and 1.875 (additional `QT_SCALE_FACTOR=1.5` on this desktop). All wizard pages, eight targeted tabs, bottom-scrolled controls, screenshot editor and long repair review were rendered and inspected. This does not establish every physical monitor configuration.

`verify_feature_completeness.py --live` completed read-only symptom/performance, network, software, folder, audio/Bluetooth/printer and timeline checks, five resource samples, history reload and ZIP/hash validation. Some gateway, signature, Bluetooth and printer results were unavailable or permission-denied; a completed check is not a healthy-device claim. No repairs, playback or printing occurred.

These are app-internal native Qt tests and render inspection, **not external mouse/keyboard testing**. File pickers are bypassed with predetermined paths for repeatable export verification. Physical audio/printing are not triggered.

## Packaging

Build target: one-file `dist/HelpPack-English.exe`, English product/file-description metadata, unchanged app version 0.2.2 and MIT copyright.

PyInstaller 6.22.3 completed the one-file build. The EXE is 56,482,085 bytes; SHA-256: `031a479a55783123e44407ed5125b2846093045206c32cbc39aeb617c23d8bcc`.

The final EXE was copied alone to an ignored standalone directory. Python environment paths were cleared and PATH restricted to Windows directories. Native `--self-check` returned 0 with `frozen=true`, `platform=windows`, visible widget, completed read-only collection, 15 event-loop ticks, intact long-text marker, Unicode export and all ZIP hashes passing. Original screenshot remained unchanged. Normal EXE startup and the source launch script each returned 0 in separate timed smoke checks. English product name, description, original filename and version 0.2.2 were read from the built PE metadata.

`--self-check <output-folder>` works without pytest and writes evidence into a unique child folder. It performs only read-only collection, uses fictional exports, makes no repairs, does not elevate, play audio or print.

## Publication audit

The fixed-copy audit classified all remaining Chinese literals: English resource keys, compatible stored IDs/values, bilingual input/parser markers, structured script state markers and synthetic Unicode fixtures. It found no unreviewed literals. The English catalog contains 1,001 templates.

The source privacy scanner passed with zero blocking findings. Additional review covered email/IP/MAC/path/phone/secret-assignment matches, file lists and staged differences. Matches were synthetic tests, allowlisted official URLs, numeric route selectors and generic Windows system paths, not personal diagnostics or credentials. This is a best-effort audit, not a guarantee against every possible secret format.

Only project sources, tests, scripts, English documents, the fictional example and build metadata are submitted. `.env`, keys, local IDE state, logs, dumps, real diagnostic output, user attachments, ZIPs, caches, build directories and EXEs are excluded. MIT and copyright remain unchanged. Original Chinese `main` and its 24 pre-existing changed/untracked entries are preserved in their separate checkout; a scoped baseline snapshot is an ancestor of `english`, not a commit to `main`.

## Explicitly unverified

- A real English Windows installation; multilingual output is fixture-tested only.
- Actual system repairs, successful UAC mutation, Store startup/content recovery, Windows Update driver installation, DISM/SFC and reliable rollback on real damaged systems.
- Physical hearing/printing and every Bluetooth/BLE device/profile.
- Native OS file-picker interaction and external desktop mouse/keyboard acceptance.
- A real two-hour monitoring endurance run.
- Full EXE redistribution license compliance, Authenticode signing and release distribution. No Release is created in this task.

Personal diagnostics, rendered local evidence, test ZIPs, histories, EXEs and build caches remain under ignored output directories and are not committed.
