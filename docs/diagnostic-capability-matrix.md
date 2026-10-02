# Diagnostic Capabilities — English Edition

Current repair plans and their recovery/confirmation/verification boundaries are recorded in the [repair-plan matrix](repair-plan-verification.md). Performance now uses six consecutive samples rather than treating a momentary peak as a cause; software checks additionally read named crash XML fields.

All default checks are L0/read-only. Findings expose evidence, confidence and unavailable/unsupported/permission/timeout outcomes separately. A suggestion is not a confirmed diagnosis.

| Area | Implemented behavior | Safety / limitations | Verification scope |
|---|---|---|---|
| Support Bundle | Description, screenshots, privacy review, editable Markdown, ZIP and SHA-256 manifest | Best-effort redaction; screenshots require human review | Automated export/security tests; native source and EXE workflow |
| Symptoms | English/Chinese keyword routing to relevant checks | Local rules, not remote AI or proven causes | Bilingual fixtures and Qt entry workflow |
| Performance | Short CPU/memory/disk/network samples and relevant process evidence | Momentary measurements, not causation | Unit tests; local read-only collection |
| Network | Adapter, gateway, system/custom DNS, proxy/direct HTTPS and target response | Selected target only; no certificate bypass or automatic public DNS; PAC limited | Unit simulations and read-only local probes |
| Software | Local EXE/version/path/signature, current processes, bounded crash/blocking logs and runtime registration | Does not run EXE; presence/signature is not health proof | Four-scenario simulations; read-only local probe |
| Storage | Selected-folder ranking, link/access skipping, cancellation and bounded traversal | Cache classification is a clue, not deletion approval | Temporary-folder tests; native UI entry |
| Cache handling | One confirmed cache file moved to same-partition quarantine; persisted restore receipt | Does NOT free space; no permanent deletion or overwrite | Synthetic temporary-file move/restore tests only |
| Audio | Outputs/default, mute/volume, services, requested quiet playback | Never changes system/default volume; physical hearing unverified | Read-only/mocked API and confirmation tests |
| Bluetooth | Adapter, cached classic paired/connection state and services | Not complete BLE/profile coverage | Mocked and local read-only probes; physical devices unverified |
| Printers | Default/offline/paused and queue counters; separately confirmed test page | No document names/owners; queued does not prove printed | Mocked confirmation tests; no physical print |
| History | Local redacted records, user status, matching-scope comparison | Changes do not prove repair causation; original logs untranslated | Persistence/comparison tests and Qt workflows |
| Timeline | Bounded installation/update/driver/crash/restart events | Missing logs may hide events; timing is only a clue | Simulations and local read-only probe |
| Monitoring | Two-second samples, 10-minute ring, 2-hour maximum, before/after marker | Exit stops monitoring; unavailable counters remain null | Short live samples; retention/time limit simulated |
| Store / TLS | Package/policy and supported Internet TLS settings checks; directed official guidance | No policy bypass, old TLS enablement or claimed Store recovery from registration | Mocked checks and safety tests; Store functionality not actually repaired |
| Driver updates | Windows Update applicability search; allowlisted official vendor pages | Installation separately confirmed/high risk; INF execution remains blocked | Simulated matching/failure safeguards; installation unverified |

## Individually confirmed repair actions

| Action | Risk / authority | Recovery | Verification |
|---|---|---|---|
| Clear DNS cache | L1; one action | Cache rebuilds; no configuration rollback | Mocked execution/recheck |
| Renew selected DHCP / restore DHCP DNS | L2; selected interface, admin where required | Renewal not reliably reversible; DNS uses encrypted snapshot | Simulated safety, backup and recheck |
| Reset current-user proxy/PAC or disable selected user startup entry | L2; exact registry allowlist | Restore backed-up values/types | Mocked backup/restore tests |
| Store cache / eligible current-user registration | Selected package only; current-user registration non-elevated | Cache regenerates; registration not guaranteed reversible | Simulated prerequisites and verification |
| Store data reset | High risk; second confirmation **RESET** | Cannot reliably restore app data | Mocked confirmation only |
| Services / time synchronization | Exact allowlisted target; no startup-type/time-zone change | Depends on action; interrupted tasks not recoverable | Mocked execution |
| Winsock / guarded DHCP TCP/IP reset | High risk; strong evidence, second confirmation, admin | Not reliably reversible; manual restart and verification | Guard/permission simulations; real repair unverified |
| WUA driver installation | High risk; match/version/license/export safeguards and second confirmation | Best effort only; never promise rollback | Mocked safety paths; real device install unverified |
| DISM / SFC repair | High risk; evidence, admin, second confirmation, long-running | Not reliably reversible; no forced termination | Mocked execution/recheck; real component repair unverified |

No bulk high-risk repair, automatic restart, registry cleaner, driver accelerator, memory optimizer, security-software bypass, enterprise-policy override, BitLocker change or generic full-disk cleanup is provided.

No real English-Windows environment was available. English output fixtures are not real English-Windows acceptance. See the current verification report for exact runs and exclusions.
