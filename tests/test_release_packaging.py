"""Release assets must be installable and draft notes must use measured coverage."""

import json
import subprocess
from pathlib import Path
from zipfile import ZipFile

from scripts.prepare_release import ASSET_NAME, INTEGRATION, REPOSITORY, prepare_release


def test_release_zip_contains_only_tracked_integration_files(tmp_path: Path):
    tag = json.loads((REPOSITORY / INTEGRATION / "manifest.json").read_text())["version"]
    coverage = tmp_path / "coverage.json"
    coverage.write_text(json.dumps({"totals": {"percent_covered": 97.077144}}))

    prepare_release(REPOSITORY, tag, coverage, tmp_path / "release")

    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", str(INTEGRATION)], cwd=REPOSITORY
    )
    expected = {
        Path(name.decode()).relative_to(INTEGRATION).as_posix()
        for name in tracked.split(b"\0")
        if name
    }
    with ZipFile(tmp_path / "release" / ASSET_NAME) as archive:
        assert set(archive.namelist()) == expected
        assert json.loads(archive.read("manifest.json"))["version"] == tag
        assert "__init__.py" in archive.namelist()
        assert any(name.startswith("frontend/") for name in archive.namelist())

    notes = (tmp_path / "release" / "release-notes.md").read_text()
    assert "test%20coverage-97.08%25" in notes
    assert "### Quality" in notes
    assert notes.endswith("## Help received this release:\n")
    assert "@CozyEnchanter" not in notes
