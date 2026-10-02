# Final Verification Results (2026-10-02)

| Check | Chinese edition | English edition |
|---|---|---|
| Full pytest, isolated temporary folder | 151 passed | 171 passed |
| Ruff | All checks passed | All checks passed |
| Source privacy scan | No blocking findings; explicit fictional key fixtures only | Same |
| English fixed-copy scan | Shared paired resources | Zero unreviewed Chinese literals; compatible IDs/raw input retained |
| Native source window | Read-only network, six resource samples and selected EXE/log checks completed | Same |
| Final standalone EXE acceptance | Exit 0; frozen=true; Windows native widgets | Same |
| Default EXE homepage startup | Exit 0 | Exit 0 |
| Plan and narrow-window layouts | Visible native widgets; scrollable long evidence; high-impact item unchecked; plan cancelled | Same; render captures inspected |
| Fictional exports | Unicode Markdown/ZIP and manifest SHA-256 passed | Same; English fixed headings and Unicode input preserved |
| Simulated repair GUI workflow | Background worker → results → history → report passed | Same |

The final EXE check clears `PYTHONPATH` and uses only the Windows root/System32 in `PATH`, with no development Python or PowerShell folder. Native system-directory lookup locates built-in commands. No system configuration or installation was changed.

Selected-program checks return seven groups. Version/path, process, event, named crash fields and runtime data can be read; the local signature query remains unverified and is not reported as valid. Empty event records are not a real reproduced crash or proof of a root cause.

## Builds

- Chinese: `dist/repair-plan/HelpPack.exe` in the Chinese workspace, 56,903,158 bytes.
  SHA-256: `2ae9e6463aa8e6b8f4a992d3d663cf82985d07c70c31868da441714df249d825`
- English: `dist/repair-plan/HelpPack-English.exe`, 56,977,974 bytes.
  SHA-256: `6f9d92222812b4091b7b2e107ff009553adf95383713c1f0d252b7c7cf9eca58`

Final local EXE evidence: `dist/exe-plan-final/c28131810e4e49519ed81dac74e0f6bf/results.json` with fictional exports and native renders. Chinese evidence is in that workspace's `dist/exe-plan-final/246d682c13774da6ae91876f58c3059d/`. All are ignored local artifacts.

## Not verified

No real development-computer DNS, proxy, service, startup, queue or component mutation was performed. Repairs/elevation refusal/timeouts use mocks, cache restoration uses test-created temporary directories and DPAPI uses fictional bytes. Restorable-VM repair acceptance, real UAC clicks, external mouse end-to-end interaction, English Windows hardware and physical peripherals remain unverified.

Repairs are not production live-acceptance certified. Existing system writers are never forcibly killed. Signature APIs, disk busy counters and some logs may be unavailable. PAC/WPAD/browser paths and absolute clock comparisons are limited. Same-volume cache recovery does not free space. Legacy backups without post-change snapshots cannot be restored automatically.

See the [action, confirmation and recovery matrix](repair-plan-verification.md). `main` and `english` retain their prior HEADs; no commit, push or Release was created. Changes remain local for review.
