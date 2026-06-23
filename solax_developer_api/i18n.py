"""Lightweight runtime translation helper with English fallback."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"
RUNTIME_TRANSLATIONS_DIR = Path(__file__).resolve().parent / "runtime_translations"
DEFAULT_LANGUAGE = "en"
_CATALOG_CACHE: dict[str, dict[str, Any]] = {}
_CATALOG_LOAD_TASKS: dict[str, asyncio.Task[None]] = {}


def _normalize_lang(lang: str | None) -> str:
    value = str(lang or DEFAULT_LANGUAGE).strip().lower().replace("_", "-")
    if not value:
        return DEFAULT_LANGUAGE
    return value.split("-", 1)[0]


def _read_catalog_from_disk(language: str) -> dict[str, Any]:
    lang = _normalize_lang(language)
    catalog: dict[str, Any] = {}
    for directory in (TRANSLATIONS_DIR, RUNTIME_TRANSLATIONS_DIR):
        path = directory / f"{lang}.json"
        if not path.exists():
            path = directory / f"{DEFAULT_LANGUAGE}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            catalog.update(payload)
    return catalog


async def async_ensure_catalog_loaded(hass, language: str | None = None) -> None:
    """Load active + fallback catalogs via executor to avoid loop blocking."""
    lang = _normalize_lang(language or getattr(getattr(hass, "config", None), "language", None))
    targets = [lang]
    if lang != DEFAULT_LANGUAGE:
        targets.append(DEFAULT_LANGUAGE)

    for target in targets:
        if target in _CATALOG_CACHE:
            continue
        payload = await hass.async_add_executor_job(_read_catalog_from_disk, target)
        _CATALOG_CACHE[target] = payload if isinstance(payload, dict) else {}


def _schedule_catalog_load(hass, language: str | None = None) -> None:
    if hass is None or not hasattr(hass, "async_create_task"):
        return
    lang = _normalize_lang(language or getattr(getattr(hass, "config", None), "language", None))
    targets = [lang]
    if lang != DEFAULT_LANGUAGE:
        targets.append(DEFAULT_LANGUAGE)

    for target in targets:
        if target in _CATALOG_CACHE or target in _CATALOG_LOAD_TASKS:
            continue

        async def _loader(target_lang: str = target) -> None:
            try:
                await async_ensure_catalog_loaded(hass, target_lang)
            finally:
                _CATALOG_LOAD_TASKS.pop(target_lang, None)

        _CATALOG_LOAD_TASKS[target] = hass.async_create_task(_loader())


def _load_catalog_from_cache(language: str) -> dict[str, Any]:
    return _CATALOG_CACHE.get(_normalize_lang(language), {})


def _resolve_key(catalog: dict[str, Any], key: str) -> str | None:
    node: Any = catalog
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    if isinstance(node, str):
        return node
    return None


def translate(
    hass,
    key: str,
    *,
    placeholders: dict[str, Any] | None = None,
    fallback: str | None = None,
) -> str:
    """Translate a key for the current HA language with English fallback."""
    language = DEFAULT_LANGUAGE
    try:
        language = _normalize_lang(getattr(getattr(hass, "config", None), "language", None))
    except Exception:
        language = DEFAULT_LANGUAGE

    catalogs = []
    primary_catalog = _load_catalog_from_cache(language)
    if primary_catalog:
        catalogs.append(primary_catalog)
    if language != DEFAULT_LANGUAGE:
        fallback_catalog = _load_catalog_from_cache(DEFAULT_LANGUAGE)
        if fallback_catalog:
            catalogs.append(fallback_catalog)

    if not catalogs:
        _schedule_catalog_load(hass, language)

    template: str | None = None
    for catalog in catalogs:
        template = _resolve_key(catalog, key)
        if template is not None:
            break

    if template is None:
        template = fallback if fallback is not None else key

    values = {k: str(v) for k, v in (placeholders or {}).items()}
    try:
        return template.format(**values)
    except Exception:
        return template
