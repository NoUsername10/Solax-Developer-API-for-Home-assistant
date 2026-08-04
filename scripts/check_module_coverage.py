"""Fail when a production integration module misses its coverage target."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PRODUCTION_PREFIX = "custom_components/solax_developer_api/"


def module_failures(
    report: dict[str, Any],
    *,
    minimum: float,
) -> list[tuple[str, float]]:
    """Return production modules that do not exceed the minimum percentage."""
    failures: list[tuple[str, float]] = []
    for filename, payload in sorted((report.get("files") or {}).items()):
        normalized = str(filename).replace("\\", "/")
        if not normalized.startswith(PRODUCTION_PREFIX):
            continue
        summary = payload.get("summary") or {}
        statements = int(summary.get("num_statements") or 0)
        if statements == 0:
            continue
        percent = float(summary.get("percent_covered") or 0.0)
        if percent <= minimum:
            failures.append((normalized, percent))
    return failures


def main() -> int:
    """Validate a Coverage.py JSON report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--minimum", type=float, default=95.0)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    failures = module_failures(report, minimum=args.minimum)
    if failures:
        for filename, percent in failures:
            print(f"{filename}: {percent:.2f}% (must exceed {args.minimum:.2f}%)")
        return 1

    checked = sum(
        1
        for filename, payload in (report.get("files") or {}).items()
        if str(filename).replace("\\", "/").startswith(PRODUCTION_PREFIX)
        and int((payload.get("summary") or {}).get("num_statements") or 0) > 0
    )
    print(
        f"Module coverage validation passed for {checked} production module(s); "
        f"each exceeds {args.minimum:.2f}%."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
