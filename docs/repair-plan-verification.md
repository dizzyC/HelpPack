# Diagnostics and Repair Plans — Verification Boundary (2026-10-02)

Local development only: no Git commit, push or Release in this round. Existing Chinese work and Git history are preserved. Shared repair behavior uses paired Chinese/English resources without changing stored IDs or user input.

## Audit

Existing working code: read-only diagnostic engine and workers, individual repair handlers, restricted UAC helper, DPAPI backups, redacted history, targeted network/software/storage/device checks, timeline, monitoring, screenshot copies and Support Bundle exports.

Fixed defects: proxy/custom DNS presence offered resets; healthy services offered restarts; rollback did not check current state against post-change snapshots; performance used brief samples; crash association relied mainly on localized messages; no evidence-scoped plan scheduler existed. The changes add safe recommendations, structured service dependencies, conflict-aware rollback, six consecutive resource samples, named crash XML fields and serial repair plans.

Incomplete capabilities are not presented as successful repairs: vendor driver downloading/installing and real hardware recovery remain unvalidated and excluded from repair entry points this round. There is no reliable automatic evidence producer for network-stack corruption, unresponsive services or component corruption; these remain manual recommendations.

## Workflow

Open Diagnostics and choose a scene. For networking, enter a standard-port HTTPS target and select All Websites / One Website / Wi-Fi. Targeted Checks retain optional custom DNS comparison and program/EXE selection.

Findings → Review Repair Plan → choose actions → confirm. High-impact actions start unchecked and require individual confirmation. Applicability is checked again immediately before execution. Plans and source findings expire after five minutes. A cross-process lock prevents simultaneous plans. Failed dependencies skip their children while independent actions continue. Cancellation stops further scheduling, never forcibly kills a system writer.

Results separate improved evidence, unchanged problems, failure, restart required and unknown. Related scene checks run again; the user decides whether the original issue is resolved. Review remains available without actions and includes manual Windows settings links. Restore This Plan or Restore Previous HelpPack Changes uses only app-created backups containing post-change snapshots; conflicts refuse overwrites. Legacy backups without such snapshots cannot be restored automatically.

## Current action matrix — real repairs not performed on the development computer

| Action | Availability and evidence | Confirmation / permissions | Recovery |
|---|---|---|---|
| Flush DNS cache | Both reference domains fail; fresh applicability check | Plan approval and UAC when needed | Cannot restore prior cache; DNS servers unchanged |
| Start audio/Bluetooth/print/update services | Relevant scene, Automatic but Stopped; dependencies must run | Plan approval and UAC when needed | Best effort to stop again; interrupted tasks cannot be recovered; running dependents block recovery |
| Quarantine HelpPack / VS Code cache | Other abnormal/sustained-pressure evidence in this scan; exact allowlisted directory, app closed, no links, up to 5000 entries / 512 MiB. Cached data alone does not create a plan | Plan approval | Original bytes and hashes retained; newly created cache or edited backups cause conflict |
| Disable selected HKCU Run/RunOnce entry | Existing startup check; explicit item selection | Individual confirmation; current-user permissions | DPAPI original state; conflicts refuse overwrites |
| Restore previous app-made DNS/proxy/startup/cache/service changes | Valid post-change snapshot and unchanged current state | Restore confirmation; DNS/services require individual approval and UAC | Original state restored; no promise to undo the restore itself |
| DHCP renewal / DHCP DNS / proxy reset | Backend and individual interfaces retained and hardened; no plan without adequate fault evidence | Individual confirmation; validated adapter and fresh state | Renewal cannot be undone; DNS saves IPv4/IPv6 automatic/manual settings; proxy backed up |
| Service restart / SFC / DISM | Backend retained; no automatic plan without reliable fault evidence | Individual confirmation; administrator | No reliable full rollback; cannot recover interrupted tasks or components |
| Adapter restart/disable, Winsock/network stack, process termination, print-job cancellation | No safe automatic entry in this round; manual handling explained | No ineffective repair button | No automatic recovery promise |

Cache quarantine retains recovery data on the same volume and **does not free disk space**. Configured proxies/PAC/custom DNS are not inherently faulty. Local time is not proof of absolute clock accuracy. HTTPS certificate validation is never bypassed; PAC/WPAD and complete browser paths remain limited.

## Validation categories

- Automated simulations: normal/configuration-only findings, approval, extra approval, expiry/tampering, denied elevation, changed applicability, failures/timeouts/cancellation, dependencies/conflicts/replay, rechecks, recovery conflicts, temporary-cache restoration, injection defenses and redaction.
- Actual Windows native source and standalone EXE checks via `--plan-self-check <output>`: background read-only network/resource probes, visible/resizeable widgets, long text, fictional plan preview cancelled without execution, Unicode Markdown/ZIP and manifest SHA-256.
- Real mutations use only mocks and test-owned temporary files. DPAPI tests use fictional bytes. No development-computer DNS, proxy, startup entry, service or component was modified.
- Not verified: restorable Windows VM repairs, real UAC acceptance/denial clicks, external mouse end-to-end interaction, English Windows hardware and physical peripherals. Simulation is not live repair acceptance.
- Repair deadlines flag timeout, but existing system writers are allowed to finish safely. Cancellation stops later actions, not the active transaction; exact progress and forced termination are not promised.

Final test counts and build hashes are recorded in `repair-plan-results.md`. Captures and fictional exports remain ignored under `dist/`.

Services use structured CIM data; crash fields use named event XML rather than Chinese/English message parsing. Missing fields remain unknown. References: [Microsoft Start-Service](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-service), [Microsoft crash events](https://learn.microsoft.com/en-us/troubleshoot/windows-server/performance/troubleshoot-application-service-crashing-behavior).
