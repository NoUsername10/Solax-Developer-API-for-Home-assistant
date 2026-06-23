import json
import re
from pathlib import Path


ROOT = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "solax_developer_api"
)


def _flatten(node, prefix=""):
    values = {}
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            values.update(_flatten(value, path))
    elif isinstance(node, str):
        values[prefix] = node
    return values


def test_translation_catalogs_match_english_keys_and_placeholders():
    strings = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
    english = json.loads(
        (ROOT / "translations" / "en.json").read_text(encoding="utf-8")
    )
    assert english == strings
    baseline = _flatten(english)

    for language in ("es", "sv"):
        translated = json.loads(
            (ROOT / "translations" / f"{language}.json").read_text(
                encoding="utf-8"
            )
        )
        flattened = _flatten(translated)
        assert flattened.keys() == baseline.keys()
        for key, english_value in baseline.items():
            assert set(re.findall(r"{([^{}]+)}", flattened[key])) == set(
                re.findall(r"{([^{}]+)}", english_value)
            )


def test_spanish_and_swedish_are_real_catalogs_not_english_copies():
    english = _flatten(
        json.loads(
            (ROOT / "translations" / "en.json").read_text(encoding="utf-8")
        )
    )
    for language in ("es", "sv"):
        translated = _flatten(
            json.loads(
                (ROOT / "translations" / f"{language}.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        changed = sum(
            translated[key] != value for key, value in english.items()
        )
        assert changed >= int(len(english) * 0.75)


def test_runtime_translation_catalogs_have_full_parity():
    runtime_dir = ROOT / "runtime_translations"
    english = _flatten(
        json.loads((runtime_dir / "en.json").read_text(encoding="utf-8"))
    )
    for language in ("es", "sv"):
        translated = _flatten(
            json.loads(
                (runtime_dir / f"{language}.json").read_text(encoding="utf-8")
            )
        )
        assert translated.keys() == english.keys()
        for key, english_value in english.items():
            assert set(re.findall(r"{([^{}]+)}", translated[key])) == set(
                re.findall(r"{([^{}]+)}", english_value)
            )
