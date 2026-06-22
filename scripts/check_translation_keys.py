#!/usr/bin/env python3
"""Validate translation key parity across language files."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_DIR = ROOT / "custom_components" / "solax_developer_api" / "translations"
RUNTIME_TRANSLATIONS_DIR = (
    ROOT / "custom_components" / "solax_developer_api" / "runtime_translations"
)
STRINGS_PATH = ROOT / "custom_components" / "solax_developer_api" / "strings.json"


def flatten_keys(node, prefix=""):
    keys = set()
    if isinstance(node, dict):
        for key, value in node.items():
            current = f"{prefix}.{key}" if prefix else key
            keys.add(current)
            keys |= flatten_keys(value, current)
    return keys


def flatten_strings(node, prefix=""):
    strings = {}
    if isinstance(node, dict):
        for key, value in node.items():
            current = f"{prefix}.{key}" if prefix else key
            strings.update(flatten_strings(value, current))
    elif isinstance(node, str):
        strings[prefix] = node
    return strings


def discover_translation_paths() -> list[Path]:
    return sorted(path for path in TRANSLATIONS_DIR.glob("*.json") if path.is_file())


def validate_catalog_group(
    paths: list[Path],
    *,
    label: str,
    issues: list[str],
) -> None:
    catalogs: dict[str, dict[str, str]] = {}
    for path in paths:
        try:
            catalogs[path.name] = flatten_strings(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except Exception as err:  # noqa: BLE001
            issues.append(f"{label}/{path.name}: invalid JSON ({err})")
    if "en.json" not in catalogs:
        issues.append(f"{label}: missing en.json")
        return
    baseline = catalogs["en.json"]
    for filename, catalog in catalogs.items():
        if catalog.keys() != baseline.keys():
            issues.append(f"{label}/{filename}: key mismatch from en.json")
            continue
        for key, baseline_value in baseline.items():
            if set(re.findall(r"{([^{}]+)}", baseline_value)) != set(
                re.findall(r"{([^{}]+)}", catalog[key])
            ):
                issues.append(
                    f"{label}/{filename}: placeholder mismatch at {key}"
                )


def main() -> int:
    paths = discover_translation_paths()
    if not paths:
        print(f"No translation files found in {TRANSLATIONS_DIR}")
        return 1
    runtime_paths = sorted(
        path for path in RUNTIME_TRANSLATIONS_DIR.glob("*.json") if path.is_file()
    )

    key_sets: dict[str, set[str]] = {}
    issues: list[str] = []

    strings_keys: set[str] | None = None
    strings_values: dict[str, str] | None = None
    if not STRINGS_PATH.exists():
        issues.append(f"Missing strings source file: {STRINGS_PATH}")
    else:
        try:
            strings_data = json.loads(STRINGS_PATH.read_text(encoding="utf-8"))
            strings_keys = flatten_keys(strings_data)
            strings_values = flatten_strings(strings_data)
        except Exception as err:  # noqa: BLE001
            issues.append(f"{STRINGS_PATH.name}: invalid JSON ({err})")

    catalogs: dict[str, dict[str, str]] = {}
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as err:  # noqa: BLE001
            issues.append(f"{path.name}: invalid JSON ({err})")
            continue

        if not data.get("entity", {}).get("switch", {}).get("rate_limit_notifications", {}).get("name"):
            issues.append(f"{path.name}: missing entity.switch.rate_limit_notifications.name")

        key_sets[path.name] = flatten_keys(data)
        catalogs[path.name] = flatten_strings(data)

    if "en.json" not in key_sets:
        issues.append("Missing baseline translation file: en.json")
    else:
        baseline = key_sets["en.json"]
        if strings_keys is not None:
            missing_from_en = sorted(strings_keys - baseline)
            extra_in_en = sorted(baseline - strings_keys)
            if missing_from_en:
                issues.append(
                    "en.json: missing keys from strings.json: "
                    + ", ".join(missing_from_en)
                )
            if extra_in_en:
                issues.append(
                    "en.json: extra keys not in strings.json: "
                    + ", ".join(extra_in_en)
                )
        if strings_values is not None and catalogs.get("en.json") != strings_values:
            issues.append("en.json: values differ from strings.json")
        for filename, keys in key_sets.items():
            if filename == "en.json":
                continue
            missing = sorted(baseline - keys)
            extra = sorted(keys - baseline)
            if missing:
                issues.append(f"{filename}: missing keys from en.json: {', '.join(missing)}")
            if extra:
                issues.append(f"{filename}: extra keys not in en.json: {', '.join(extra)}")
            for key, baseline_value in catalogs["en.json"].items():
                translated_value = catalogs.get(filename, {}).get(key, "")
                baseline_placeholders = set(
                    re.findall(r"{([^{}]+)}", baseline_value)
                )
                translated_placeholders = set(
                    re.findall(r"{([^{}]+)}", translated_value)
                )
                if baseline_placeholders != translated_placeholders:
                    issues.append(
                        f"{filename}: placeholder mismatch at {key}"
                    )

    if issues:
        print("Translation validation failed:")
        for issue in issues:
            print(f" - {issue}")
        return 1

    validate_catalog_group(
        runtime_paths,
        label="runtime_translations",
        issues=issues,
    )
    if issues:
        print("Translation validation failed:")
        for issue in issues:
            print(f" - {issue}")
        return 1

    print(
        "Translation validation passed for "
        f"{len(paths)} Home Assistant and {len(runtime_paths)} runtime file(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
