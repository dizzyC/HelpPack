# Privacy and Safety Boundaries

HelpPack reads relevant system counters, device/service state and bounded troubleshooting logs. It does not collect browser history, document contents, passwords, clipboard contents, Wi-Fi passwords or a full personal file inventory.

Reports/history are automatically redacted for common usernames, home paths, IPv4/IPv6, MACs, emails and secret/password fields. Manifests contain relative archive names and SHA-256, not original paths. Edited images are exported as copies; originals remain unchanged.

Redaction is best effort. Unusual tokens, personal names, phone numbers and image contents may remain. Original logs and user text may contain private information. Review every exported report and image. No OCR or automatic screenshot-content redaction is performed.

No account, telemetry backend or automatic report upload. DNS/gateway/HTTPS and Windows Update checks use the network; selected targets/custom DNS receive the relevant request. Official support pages open in your browser. The application never calls a translation service.

History and backups stay in the user's local HelpPack application-data directory. Sensitive network snapshots use Windows DPAPI. Backups never enter support bundles. Shared computers and accessible local files are part of your privacy threat model.

Repairs are individually confirmed, allowlisted and scope-checked; high-risk actions need a second confirmation. UAC is requested only for eligible operations. Current-user Store registration must not run under another administrator account. Enterprise policies, security software, VPN and BitLocker settings are not silently changed. Backups are not guaranteed rollback.

English labels do not change saved enum/config/manifest fields. User input, file names and original logs are not automatically translated. Historical Chinese records remain original data.
