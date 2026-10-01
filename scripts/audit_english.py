"""Review fixed copy while allowing compatible IDs, bilingual input and raw logs."""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from helppack.english import LABELS, MESSAGES


def main() -> int:
    findings = []
    classified = {}
    for path in (ROOT / "src/helppack").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        resource_args = {id(call.args[0]) for call in ast.walk(tree)
                         if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                         and call.func.id in ("msg", "text") and call.args}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or not re.search("[\u4e00-\u9fff]", node.value):
                continue
            value = node.value
            if path.name == "english.py" or id(node) in resource_args:
                kind = "English resource key"
            elif path.name == "validation.py":
                kind = "Synthetic Unicode test data"
            elif path.name == "symptoms.py":
                kind = "Compatible categories and bilingual symptom keywords"
            elif value in LABELS or value in ("无法读取", "缓存", "症状向导：", "扫描", "拒绝访问"):
                kind = "Compatible stored value or bilingual parser marker"
            elif "ConvertTo-Json" in value:
                kind = "Structured script compatibility marker"
            else:
                findings.append({"file": path.relative_to(ROOT).as_posix(), "line": node.lineno})
                continue
            classified[kind] = classified.get(kind, 0) + 1
    print(json.dumps({"status": "blocked" if findings else "ok", "catalog_entries": len(MESSAGES),
                      "classified": classified, "unreviewed_literals": findings}, indent=2))
    return bool(findings)


if __name__ == "__main__":
    raise SystemExit(main())
