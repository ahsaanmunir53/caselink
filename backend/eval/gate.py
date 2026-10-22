"""CI quality gate: fail if linking or extraction got worse than eval/thresholds.json allows."""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    results = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    thresholds = json.loads((HERE / "thresholds.json").read_text(encoding="utf-8"))
    failed = False
    for key, minimum in thresholds.items():
        value = results
        for part in key.split("."):
            value = value[part]
        ok = value >= minimum
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'} {key}: {value} (needs >= {minimum})")
    if failed:
        sys.exit("Quality gate failed.")
    print("Quality gate passed.")


if __name__ == "__main__":
    main()
