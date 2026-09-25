from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDED_ROOTS = [ROOT / name for name in ("src", "tests", "scripts", "docs", "examples")]
INCLUDED_FILES = [
    ROOT / name
    for name in (
        ".gitignore",
        "README.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "run.ps1",
        "build.ps1",
        "helppack.spec",
        "helppack_launcher.py",
    )
]
TEXT_SUFFIXES = {".py", ".md", ".txt", ".toml", ".ps1", ".spec", ".gitignore"}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


def files_to_scan() -> list[Path]:
    files = [path for path in INCLUDED_FILES if path.is_file()]
    for root in INCLUDED_ROOTS:
        if not root.is_dir():
            continue
        files.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and "__pycache__" not in path.parts
        )
    return sorted(set(files))


def main() -> int:
    username = os.environ.get("USERNAME", "")
    home = str(Path.home())
    blockers = []
    synthetic = []
    scanned = files_to_scan()
    for path in scanned:
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(ROOT).as_posix()
        if username and re.search(rf"(?i)(?<![\w]){re.escape(username)}(?![\w])", text):
            blockers.append({"file": relative, "kind": "current_username"})
        if home and home.casefold() in text.casefold():
            blockers.append({"file": relative, "kind": "current_home_path"})
        for kind, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                context = text[max(0, match.start() - 60) : match.end() + 60].lower()
                if relative.startswith(("tests/", "scripts/")) and any(marker in context for marker in ("fake", "abcdefghijklmnopqrstuvwxyz", "synthetic")):
                    synthetic.append({"file": relative, "kind": kind})
                elif relative == "src/helppack/redaction.py" and "re.compile" in text[max(0, match.start() - 120) : match.start()]:
                    synthetic.append({"file": relative, "kind": f"pattern_{kind}"})
                else:
                    blockers.append({"file": relative, "kind": kind})
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    required_ignores = (".venv/", "build/", "dist/", "*.zip", "*.egg-info/")
    missing_ignores = [value for value in required_ignores if value not in gitignore]
    blockers.extend({"file": ".gitignore", "kind": f"missing_ignore:{value}"} for value in missing_ignores)
    result = {
        "status": "ok" if not blockers else "blocked",
        "scanned_files": len(scanned),
        "blocking_findings": blockers,
        "recognized_synthetic_test_findings": synthetic,
        "excluded_from_release": [".venv/", "build/", "dist/", ".pytest_cache/", "*.zip"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
