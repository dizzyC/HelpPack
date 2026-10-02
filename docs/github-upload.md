# Source Upload Scope and Checks (2026-10-02)

After local acceptance, the user separately authorized uploading to GitHub. This is a pre-push gate, not proof that a push succeeded; remote refs must be checked afterward. Earlier "no commit/push" verification statements describe the development phase, not a permanent prohibition.

- Existing public repository: `dizzyC/HelpPack`; Chinese `main`, English `english`. Do not merge editions or change the default branch.
- Preserve all existing history with append-only commits and ordinary pushes; no force-push or history rewriting.
- Include source, tests, README, usage/safety/capability/verification records and existing license/dependency notices.
- Exclude EXEs, build directories, environments, caches, real diagnostic outputs, user attachments, generated ZIPs and local screenshots. Do not create a Release.
- Pre-upload full pytest: Chinese 151 passed; English 171 passed. Ruff and English fixed-copy audits pass.
- Source privacy scanning has no blocking findings. Key-shaped fixtures are explicit fictional test data, not real authentication credentials.
- Repair/elevation-denial verification remains simulated; no live development-computer system changes occurred. Restorable VM, English Windows hardware and external click acceptance remain incomplete. Source publication is not live repair certification.

See the [repair verification results](repair-plan-results.md) and [action matrix](repair-plan-verification.md).
