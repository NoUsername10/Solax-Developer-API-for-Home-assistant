"""Build a HACS integration ZIP and editable draft release notes."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REPOSITORY = Path(__file__).resolve().parents[1]
INTEGRATION = Path("custom_components/solax_developer_api")
ASSET_NAME = "solax_developer_api.zip"
PROJECT_URL = "https://github.com/NoUsername10/Solax-Developer-API-for-Home-assistant"


def _changelog_entry(text: str, tag: str) -> str:
    lines = text.splitlines()
    heading = f"## [{tag}] - "
    start = next((index for index, line in enumerate(lines) if line.startswith(heading)), None)
    if start is None:
        raise ValueError(f"CHANGELOG.md has no entry for {tag}")
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## [")),
        len(lines),
    )
    entry = "\n".join(lines[start + 1 : end]).strip()
    if not entry:
        raise ValueError(f"CHANGELOG.md entry for {tag} is empty")
    return entry


def _coverage_percent(coverage_file: Path) -> str:
    report = json.loads(coverage_file.read_text(encoding="utf-8"))
    value = float(report["totals"]["percent_covered"])
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("Coverage percentage is invalid")
    return f"{value:.2f}"


def _tracked_integration_files(repository: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", str(INTEGRATION)],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    paths = [Path(name.decode("utf-8")) for name in result.stdout.split(b"\0") if name]
    if not paths:
        raise ValueError("No tracked integration files found")
    for path in paths:
        source = repository / path
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Invalid integration file: {path}")
    return paths


def prepare_release(repository: Path, tag: str, coverage_file: Path, output_dir: Path) -> None:
    manifest = json.loads((repository / INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != tag:
        raise ValueError(f"Manifest version {manifest['version']} does not match tag {tag}")

    entry = _changelog_entry((repository / "CHANGELOG.md").read_text(encoding="utf-8"), tag)
    coverage = _coverage_percent(coverage_file)
    paths = _tracked_integration_files(repository)
    archive_names = {path.relative_to(INTEGRATION).as_posix() for path in paths}
    if not {"__init__.py", "manifest.json"} <= archive_names:
        raise ValueError("Integration ZIP would lack required files")

    output_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_dir / ASSET_NAME, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in paths:
            archive.write(repository / path, path.relative_to(INTEGRATION).as_posix())

    notes = f"""# {tag}

{entry}

### Quality

[![Home Assistant Platinum Aligned](https://img.shields.io/badge/Home%20Assistant%20Quality-Platinum%20aligned-e5e4e2.svg)](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
[![Test Coverage](https://img.shields.io/badge/test%20coverage-{coverage}%25-brightgreen.svg)]({PROJECT_URL}#quality-and-validation)

If you find the integration useful and would like to support its continued development:

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-Support%20Development-orange.svg)](https://www.buymeacoffee.com/DefaultLogin)

For a full overview, see the [CHANGELOG]({PROJECT_URL}/blob/main/CHANGELOG.md).

For the latest documentation, see the [GitHub project]({PROJECT_URL}).

## I need your help

There are many different SolaX systems and configurations, so please let me know how it works for you 👍

If you experience any issues, please create an issue and provide diagnostics. I am happy to help!

Diagnostics are privacy-safe, with credentials, serial numbers, locations, and personal information redacted.

## Help received this release:
"""
    (output_dir / "release-notes.md").write_text(notes, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    prepare_release(REPOSITORY, args.tag, args.coverage, args.output_dir)


if __name__ == "__main__":
    main()
