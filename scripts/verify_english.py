"""Native Qt workflow check; only bounded read-only collection is performed."""
from pathlib import Path

from helppack.validation import run_self_check

if __name__ == "__main__":
    raise SystemExit(run_self_check(str(Path(__file__).resolve().parents[1] / "dist/validation/english")))
