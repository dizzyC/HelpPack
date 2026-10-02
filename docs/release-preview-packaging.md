# Preview distribution verification (2026-10-02)

Release tag: `v0.2.2-repair-preview.1`. Internal executable version remains 0.2.2. The stable v0.2.2 is not replaced.

- Chinese: 151 pytest tests passed; English: 171 passed.
- Both rebuilt EXEs started with the native Qt Windows platform on this Windows 11 computer.
- With PYTHONPATH empty and PATH restricted to Windows system directories, default startup and `--plan-self-check` exited with code 0.
- Frozen read-only network, sustained resource sampling and software diagnostics passed, along with repair-plan preview/cancellation and Unicode Markdown/ZIP export. Native visibility, long text and responsive event-loop checks passed. External mouse interaction was not verified.
- 164 license/attribution files are embedded and supplied as a separate license ZIP. SOURCE-AND-REBUILD.md contains matching upstream source locations and library replacement instructions.
- Unused Qt Virtual Keyboard, Qt PDF and their plugins are excluded. Embedded notice SHA-256 values were checked individually.
- System changes, elevation refusal and rollback conflicts are simulated tests. No developer-PC DNS, proxy, service or system-file repairs were performed. Real repairs in an isolated VM and real English Windows validation remain unverified.
- Executables are unsigned and may trigger SmartScreen. Modified-library rebuilding remains unverified.

The build script first runs `scripts/prepare_distribution.py`. The first build needs network access to official upstream license material. Later builds use the hash-verified `dist/distribution-licenses/` cache. Missing or modified material blocks packaging. Use README's virtual environment commands. Do not commit dist, build or real diagnostic data.
