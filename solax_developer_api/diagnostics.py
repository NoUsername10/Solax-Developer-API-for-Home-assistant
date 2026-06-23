"""Diagnostics support for the SolaX Developer API integration."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SolaxDeveloperApiClient
from .coordinator import SolaxDeveloperCoordinator
from .const import (
    CONF_API_REGION,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_MANUAL_EMS_SYSTEMS,
    CONF_MANUAL_METER_SERIALS,
    CONF_SCAN_INTERVAL,
    CONF_SYSTEM_NAME,
    DEFAULT_SCAN_INTERVAL,
)

MASK_META_SUFFIXES = ("_masked", "_length", "_present")
NON_SECRET_TOKEN_KEYS = ("token_expires_at",)
SECRET_KEY_HINTS = (
    "client_id",
    "client_secret",
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "secret",
)
SERIAL_KEY_HINTS = (
    "serial",
    "device_sn",
    "devicesn",
    "register_no",
    "registerno",
    "sn_list",
    "snlist",
    "invertersn",
    "sn",
)
PERSONAL_REDACTED_KEYS = (
    "plantid",
    "plantname",
    "loginname",
    "plantaddress",
    "longitude",
    "latitude",
)
REDACTED_VALUE = "*REDACTED*"


def _normalize_key(key: str | None) -> str:
    return str(key or "").strip().replace("-", "_").casefold()


def _is_mask_meta_key(key: str | None) -> bool:
    normalized = _normalize_key(key)
    return any(normalized.endswith(suffix) for suffix in MASK_META_SUFFIXES)


def _is_secret_key(key: str | None) -> bool:
    normalized = _normalize_key(key)
    if _is_mask_meta_key(normalized):
        return False
    if normalized in NON_SECRET_TOKEN_KEYS:
        return False
    return any(hint in normalized for hint in SECRET_KEY_HINTS)


def _is_serial_key(key: str | None) -> bool:
    normalized = _normalize_key(key)
    if _is_mask_meta_key(normalized):
        return False
    return any(hint in normalized for hint in SERIAL_KEY_HINTS)


def _is_personal_key(key: str | None) -> bool:
    normalized = _normalize_key(key).replace("_", "")
    return normalized in PERSONAL_REDACTED_KEYS or any(
        normalized.endswith(private_key) for private_key in PERSONAL_REDACTED_KEYS
    )


def _mask_secret(value: Any) -> Any:
    if value is None:
        return None
    text = str(value)
    if not text:
        return text
    if len(text) <= 2:
        return "*" * len(text)
    if len(text) <= 8:
        return f"{text[:1]}***{text[-1:]}"
    return f"{text[:4]}***{text[-4:]}"


def _mask_serial(value: Any) -> Any:
    if value is None:
        return None
    text = str(value)
    if not text:
        return text
    if len(text) <= 4:
        return "***"
    if len(text) <= 8:
        return f"{text[:1]}***{text[-1:]}"
    if len(text) <= 10:
        return f"{text[:2]}***{text[-2:]}"
    midpoint = len(text) // 2
    start = max(1, midpoint - 3)
    end = min(len(text) - 1, start + 6)
    if end <= start:
        return f"{text[:1]}***{text[-1:]}"
    return f"{text[:start]}***{text[end:]}"


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value)


def _flatten_dict(data: dict[str, Any], parent_key: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        key_str = str(key)
        combined = f"{parent_key}_{key_str}" if parent_key else key_str
        if isinstance(value, dict):
            flat.update(_flatten_dict(value, combined))
        else:
            flat[combined] = value
    return flat


def _drop_nulls(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            if nested is None:
                continue
            projected = _drop_nulls(nested)
            if projected == {} or projected == []:
                continue
            result[str(key)] = projected
        return result
    if isinstance(value, list):
        items = []
        for item in value:
            if item is None:
                continue
            projected = _drop_nulls(item)
            if projected == {} or projected == []:
                continue
            items.append(projected)
        return items
    return value


def _collect_known_serials(state: dict[str, Any]) -> set[str]:
    serials: set[str] = set()
    for serial in (state.get("devices") or {}).keys():
        text = str(serial).strip()
        if text:
            serials.add(text.casefold())
    for entry in state.get("manual_meter_entries") or []:
        if not isinstance(entry, Mapping):
            continue
        text = str(entry.get("serial") or "").strip()
        if text:
            serials.add(text.casefold())
    for entry in state.get("manual_ems_entries") or []:
        if not isinstance(entry, Mapping):
            continue
        text = str(entry.get("serial") or "").strip()
        if text:
            serials.add(text.casefold())
    return serials


def _collect_known_serials_from_raw(raw_api_responses: dict[str, Any]) -> set[str]:
    serials: set[str] = set()
    for item in raw_api_responses.get("page_device_info") or []:
        if not isinstance(item, Mapping):
            continue
        response = item.get("response") or {}
        if not isinstance(response, Mapping):
            continue
        records = ((response.get("result") or {}).get("records") or [])
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, Mapping):
                continue
            text = str(record.get("deviceSn") or "").strip()
            if text:
                serials.add(text.casefold())

    for item in raw_api_responses.get("device_realtime_data") or []:
        if not isinstance(item, Mapping):
            continue
        request = item.get("request") or {}
        if isinstance(request, Mapping):
            sn_list = request.get("snList") or []
            if isinstance(sn_list, list):
                for serial in sn_list:
                    text = str(serial).strip()
                    if text:
                        serials.add(text.casefold())
        response = item.get("response") or {}
        if not isinstance(response, Mapping):
            continue
        rows = response.get("result") or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            text = str(row.get("deviceSn") or "").strip()
            if text:
                serials.add(text.casefold())
    for endpoint in ("ems_attribute_info", "ems_summary_data", "master_control_device"):
        for item in raw_api_responses.get(endpoint) or []:
            if not isinstance(item, Mapping):
                continue
            response = item.get("response") or {}
            if not isinstance(response, Mapping):
                continue
            result = response.get("result") or []
            rows = result if isinstance(result, list) else [result]
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                for key in ("deviceSn", "registerNo", "controlDeviceSn"):
                    text = str(row.get(key) or "").strip()
                    if text:
                        serials.add(text.casefold())
    return serials


def _sanitize_for_diagnostics(
    value: Any,
    *,
    key_hint: str | None = None,
    known_secrets: set[str] | None = None,
    known_serials: set[str] | None = None,
) -> Any:
    known_secrets = known_secrets or set()
    known_serials = known_serials or set()

    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, nested in value.items():
            raw_key = str(key)
            safe_key = raw_key
            if raw_key.casefold() in known_serials:
                safe_key = str(_mask_serial(raw_key))
            elif raw_key.casefold() in known_secrets:
                safe_key = str(_mask_secret(raw_key))
            sanitized[safe_key] = _sanitize_for_diagnostics(
                nested,
                key_hint=raw_key,
                known_secrets=known_secrets,
                known_serials=known_serials,
            )
        return sanitized

    if isinstance(value, list):
        return [
            _sanitize_for_diagnostics(
                item,
                key_hint=key_hint,
                known_secrets=known_secrets,
                known_serials=known_serials,
            )
            for item in value
        ]

    if isinstance(value, tuple):
        return [
            _sanitize_for_diagnostics(
                item,
                key_hint=key_hint,
                known_secrets=known_secrets,
                known_serials=known_serials,
            )
            for item in value
        ]

    if isinstance(value, str):
        key = _normalize_key(key_hint)
        value_casefold = value.casefold()
        if _is_mask_meta_key(key):
            return value
        if _is_personal_key(key):
            return REDACTED_VALUE if value.strip() else value
        if value.casefold().startswith("bearer "):
            token = value[7:].strip()
            return f"bearer {_mask_secret(token)}"
        if _is_secret_key(key):
            return _mask_secret(value)
        if _is_serial_key(key):
            return _mask_serial(value)
        if value_casefold in known_secrets:
            return _mask_secret(value)
        if value_casefold in known_serials:
            return _mask_serial(value)
        return value

    if _is_personal_key(key_hint):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return REDACTED_VALUE
        if isinstance(value, bool):
            return REDACTED_VALUE

    return value


def _sanitize_comparison_value(field_key: str, value: Any) -> Any:
    """Sanitize comparison values using the original API field as context."""
    if value is None:
        return None
    return _sanitize_for_diagnostics(value, key_hint=field_key)


def _value_meta(value: Any, *, serial: bool = False) -> dict[str, Any]:
    text = str(value or "").strip()
    masked = _mask_serial(text) if serial else _mask_secret(text)
    return {
        "masked": masked if text else None,
        "length": len(text),
        "present": bool(text),
    }


def _build_config_entry_snapshot(entry: ConfigEntry, state: dict[str, Any], client: Any) -> dict[str, Any]:
    client_id = str(entry.data.get(CONF_CLIENT_ID) or "").strip()
    client_secret = str(entry.data.get(CONF_CLIENT_SECRET) or "").strip()
    token = str(getattr(client, "access_token", "") or "").strip()

    client_id_meta = _value_meta(client_id)
    client_secret_meta = _value_meta(client_secret)

    configured_serials = sorted(
        {str(serial).strip() for serial in (state.get("devices") or {}).keys() if str(serial).strip()},
        key=str.casefold,
    )
    manual_meter_count = len(state.get("manual_meter_entries") or [])
    manual_ems_count = len(state.get("manual_ems_entries") or [])
    auth_station = str(getattr(client, "token_auth_station", "") or "").strip()

    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "system_name": entry.data.get(CONF_SYSTEM_NAME),
        "scan_interval": entry.data.get(CONF_SCAN_INTERVAL),
        "api_region": entry.data.get(CONF_API_REGION),
        "manual_meter_serial_count": manual_meter_count,
        "manual_meter_config_present": bool(entry.options.get(CONF_MANUAL_METER_SERIALS)),
        "manual_ems_system_count": manual_ems_count,
        "manual_ems_config_present": bool(entry.options.get(CONF_MANUAL_EMS_SYSTEMS)),
        "configured_device_serials": configured_serials,
        "client_id_masked": client_id_meta["masked"],
        "client_id_length": client_id_meta["length"],
        "client_id_present": client_id_meta["present"],
        "client_secret_masked": client_secret_meta["masked"],
        "client_secret_length": client_secret_meta["length"],
        "client_secret_present": client_secret_meta["present"],
        "raw_api_token_masked": _mask_secret(token) if token else None,
        "raw_api_token_length": len(token),
        "api_token_present": bool(token),
        "token_expires_at": _to_iso(getattr(client, "token_expires_at", None)),
        "token_lifetime_seconds": getattr(client, "token_lifetime_seconds", None),
        "token_scope": getattr(client, "token_scope", None),
        "token_grant_type": getattr(client, "token_grant_type", None),
        "token_auth_station_scope": (
            "all"
            if auth_station == "all"
            else (f"scoped:{len(auth_station.split())}" if auth_station else None)
        ),
    }


def _build_filtered_api_projection(state: dict[str, Any]) -> dict[str, Any]:
    plants = deepcopy(state.get("plants") or {})
    devices = deepcopy(state.get("devices") or {})
    plant_realtime = deepcopy(state.get("plant_realtime") or {})
    plant_stats = deepcopy(state.get("plant_stats") or {})
    alarms = deepcopy(state.get("alarms") or {})
    device_realtime = deepcopy(state.get("device_realtime") or {})

    filtered_plant_realtime = _drop_nulls(plant_realtime)
    filtered_device_realtime = _drop_nulls(device_realtime)
    filtered_plant_stats = _drop_nulls(plant_stats)
    filtered_alarms = _drop_nulls(alarms)
    filtered_plants = _drop_nulls(plants)
    filtered_devices = _drop_nulls(devices)

    plant_non_null_fields = {
        str(plant_id): sorted(_flatten_dict(payload).keys(), key=str.casefold)
        for plant_id, payload in filtered_plant_realtime.items()
        if isinstance(payload, dict)
    }
    device_non_null_fields = {
        str(serial): sorted(_flatten_dict(payload).keys(), key=str.casefold)
        for serial, payload in filtered_device_realtime.items()
        if isinstance(payload, dict)
    }

    return {
        "plants": filtered_plants,
        "devices": filtered_devices,
        "inventory_by_type": deepcopy(state.get("inventory_by_type") or {}),
        "plant_realtime": filtered_plant_realtime,
        "plant_stats": filtered_plant_stats,
        "alarms": filtered_alarms,
        "device_realtime": filtered_device_realtime,
        "manual_meter_entries": deepcopy(state.get("manual_meter_entries") or []),
        "manual_ems_entries": deepcopy(state.get("manual_ems_entries") or []),
        "meta": _drop_nulls(deepcopy(state.get("meta") or {})),
        "plant_non_null_fields": plant_non_null_fields,
        "device_non_null_fields": device_non_null_fields,
    }


def _extract_raw_plant_realtime(raw_api_responses: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in raw_api_responses.get("plant_realtime_data") or []:
        if not isinstance(item, Mapping):
            continue
        request = item.get("request") or {}
        response = item.get("response") or {}
        if not isinstance(request, Mapping) or not isinstance(response, Mapping):
            continue
        plant_id = str(request.get("plantId") or "").strip()
        payload = response.get("result")
        if plant_id and isinstance(payload, Mapping):
            result[plant_id] = dict(payload)
    return result


def _extract_raw_device_realtime(raw_api_responses: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for endpoint in ("device_realtime_data", "ems_summary_data"):
        for item in raw_api_responses.get(endpoint) or []:
            if not isinstance(item, Mapping):
                continue
            response = item.get("response") or {}
            if not isinstance(response, Mapping):
                continue
            rows = response.get("result") or []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                serial = str(
                    row.get("deviceSn") or row.get("registerNo") or ""
                ).strip()
                if not serial:
                    continue
                result[serial] = dict(row)
    return result


def _field_compare_summary(
    raw_payload: dict[str, Any] | None,
    filtered_payload: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    raw_flat = _flatten_dict(raw_payload or {}) if isinstance(raw_payload, dict) else {}
    filtered_flat = (
        _flatten_dict(filtered_payload or {}) if isinstance(filtered_payload, dict) else {}
    )
    field_keys = sorted(set(raw_flat.keys()) | set(filtered_flat.keys()), key=str.casefold)
    return {
        key: {
            "present_in_raw_result": key in raw_flat,
            "raw_value_is_null": key in raw_flat and raw_flat.get(key) is None,
            "present_in_filtered_payload": key in filtered_flat,
            "filtered_value": _sanitize_comparison_value(key, filtered_flat.get(key)),
        }
        for key in field_keys
    }


def _build_raw_vs_filtered_summary(
    raw_api_responses: dict[str, Any],
    filtered_api_responses: dict[str, Any],
) -> dict[str, Any]:
    raw_plants = _extract_raw_plant_realtime(raw_api_responses)
    raw_devices = _extract_raw_device_realtime(raw_api_responses)
    filtered_plants = filtered_api_responses.get("plant_realtime") or {}
    filtered_devices = filtered_api_responses.get("device_realtime") or {}

    plant_ids = sorted(
        {str(item).strip() for item in list(raw_plants.keys()) + list(filtered_plants.keys()) if str(item).strip()},
        key=str.casefold,
    )
    serials = sorted(
        {str(item).strip() for item in list(raw_devices.keys()) + list(filtered_devices.keys()) if str(item).strip()},
        key=str.casefold,
    )

    return {
        "plants": {
            plant_id: _field_compare_summary(
                raw_plants.get(plant_id),
                filtered_plants.get(plant_id),
            )
            for plant_id in plant_ids
        },
        "devices": {
            serial: _field_compare_summary(
                raw_devices.get(serial),
                filtered_devices.get(serial),
            )
            for serial in serials
        },
    }


def _has_meaningful_state(
    state: dict[str, Any],
    raw_api_responses: dict[str, Any],
) -> bool:
    if state.get("plants") or state.get("devices") or state.get("plant_realtime") or state.get("device_realtime"):
        return True
    for payloads in raw_api_responses.values():
        if payloads:
            return True
    return False


def _build_coordinator_snapshot(coordinator: Any, state: dict[str, Any]) -> dict[str, Any]:
    meta = state.get("meta") or {}
    return {
        "available": bool(state),
        "name": getattr(coordinator, "name", None),
        "last_update_attempt": _to_iso(getattr(coordinator, "last_update_attempt", None)),
        "last_successful_update": _to_iso(getattr(coordinator, "last_successful_update", None)),
        "last_rate_limit_at": _to_iso(getattr(coordinator, "last_rate_limit_at", None)),
        "rate_limited": bool(getattr(coordinator, "rate_limited", False)),
        "rate_limited_context": list(getattr(coordinator, "rate_limited_context", []) or []),
        "poll_profile": meta.get("poll_profile"),
        "effective_scan_interval": meta.get("effective_scan_interval"),
        "live_view_active": meta.get("live_view_active"),
        "live_view_remaining_seconds": meta.get("live_view_remaining_seconds"),
        "history_cache_entries": len(getattr(coordinator, "history_cache", {}) or {}),
        "request_result_cache_entries": len(getattr(coordinator, "request_result_cache", {}) or {}),
        "master_control_cache_entries": len(getattr(coordinator, "master_control_cache", {}) or {}),
        "dry_run_commands": len(getattr(coordinator, "control_dry_runs", []) or []),
        "manual_meter_serial_count": meta.get("manual_meter_serial_count"),
        "manual_ems_system_count": meta.get("manual_ems_system_count"),
        "capability_families": meta.get("capability_families"),
        "available_control_services": meta.get("available_control_services"),
        "capability_serial_count": meta.get("capability_serial_count"),
        "capability_field_total": meta.get("capability_field_total"),
    }


def _build_and_sanitize_payload(
    *,
    entry: ConfigEntry,
    coordinator: Any,
    client: Any,
    state: dict[str, Any],
    raw_api_responses: dict[str, Any],
    fallback_probe: dict[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    filtered_api_responses = _build_filtered_api_projection(state)
    raw_vs_filtered_summary = _build_raw_vs_filtered_summary(
        raw_api_responses,
        filtered_api_responses,
    )

    config_entry_snapshot = _build_config_entry_snapshot(entry, state, client)
    coordinator_snapshot = _build_coordinator_snapshot(coordinator, state)

    raw_api_with_caches = {
        **raw_api_responses,
        "history_cache": deepcopy(getattr(coordinator, "history_cache", {}) or {}),
        "request_result_cache": deepcopy(getattr(coordinator, "request_result_cache", {}) or {}),
        "master_control_cache": deepcopy(getattr(coordinator, "master_control_cache", {}) or {}),
        "dry_run_commands": deepcopy(getattr(coordinator, "control_dry_runs", []) or []),
    }

    diagnostics_payload = {
        "config_entry": config_entry_snapshot,
        "coordinator": coordinator_snapshot,
        "raw_api_responses": raw_api_with_caches,
        "filtered_api_responses": filtered_api_responses,
        "raw_vs_filtered_summary": raw_vs_filtered_summary,
        "fallback_probe": fallback_probe,
        "issues": issues,
    }

    known_secret_values: set[str] = set()
    for raw_secret in (
        str(entry.data.get(CONF_CLIENT_ID) or "").strip(),
        str(entry.data.get(CONF_CLIENT_SECRET) or "").strip(),
        str(getattr(client, "access_token", "") or "").strip(),
    ):
        if raw_secret:
            known_secret_values.add(raw_secret.casefold())

    known_serial_values = _collect_known_serials(state)
    known_serial_values.update(_collect_known_serials_from_raw(raw_api_responses))
    known_serial_values.update(
        str(serial).strip().casefold()
        for serial in (filtered_api_responses.get("device_realtime") or {}).keys()
        if str(serial).strip()
    )
    known_serial_values.update(
        str(serial).strip().casefold()
        for serial in (raw_vs_filtered_summary.get("devices") or {}).keys()
        if str(serial).strip()
    )
    return _sanitize_for_diagnostics(
        diagnostics_payload,
        known_secrets=known_secret_values,
        known_serials=known_serial_values,
    )


async def _build_unloaded_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = [
        {
            "type": "entry_not_loaded",
            "message": "Config entry is not loaded in hass.data",
        }
    ]
    fallback_probe: dict[str, Any] = {
        "executed": True,
        "success": False,
        "reason": "entry_not_loaded",
    }

    session = async_get_clientsession(hass)
    client = SolaxDeveloperApiClient(
        client_id=str(entry.data.get(CONF_CLIENT_ID) or "").strip(),
        client_secret=str(entry.data.get(CONF_CLIENT_SECRET) or "").strip(),
        region=str(entry.data.get(CONF_API_REGION, "eu")).strip().lower(),
        session=session,
    )
    coordinator = SolaxDeveloperCoordinator(
        hass,
        client=client,
        config_entry=entry,
        entry_id=entry.entry_id,
        scan_interval=int(entry.data.get(CONF_SCAN_INTERVAL) or DEFAULT_SCAN_INTERVAL),
        options=dict(entry.options or {}),
    )
    coordinator._schedule_capability_cache_save = lambda: None  # type: ignore[method-assign]

    state = deepcopy(getattr(coordinator, "data", {}) or {})
    raw_api_responses = deepcopy(getattr(coordinator, "raw_api_responses", {}) or {})
    try:
        state = deepcopy(await coordinator._async_update_data())
        raw_api_responses = deepcopy(getattr(coordinator, "raw_api_responses", {}) or {})
        fallback_probe["success"] = True
        fallback_probe["completed_at"] = _to_iso(datetime.now(timezone.utc))
    except Exception as err:  # noqa: BLE001
        state = deepcopy(getattr(coordinator, "data", {}) or state or {})
        raw_api_responses = deepcopy(
            getattr(coordinator, "raw_api_responses", {}) or raw_api_responses or {}
        )
        fallback_probe["error"] = str(err)
        issues.append(
            {
                "type": "unloaded_entry_probe_failed",
                "message": str(err),
            }
        )

    return _build_and_sanitize_payload(
        entry=entry,
        coordinator=coordinator,
        client=client,
        state=state,
        raw_api_responses=raw_api_responses,
        fallback_probe=fallback_probe,
        issues=issues,
    )


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics data for a config entry."""
    issues: list[dict[str, Any]] = []
    if (
        entry.state is not ConfigEntryState.LOADED
        or getattr(entry, "runtime_data", None) is None
    ):
        return await _build_unloaded_entry_diagnostics(hass, entry)

    coordinator = entry.runtime_data.coordinator
    client = entry.runtime_data.client
    state = deepcopy(getattr(coordinator, "data", {}) or {})
    raw_api_responses = deepcopy(getattr(coordinator, "raw_api_responses", {}) or {})

    fallback_probe: dict[str, Any] = {"executed": False, "success": None, "reason": None}
    if not _has_meaningful_state(state, raw_api_responses):
        fallback_probe = {
            "executed": True,
            "success": False,
            "reason": "empty_state",
        }
        try:
            await coordinator.async_request_refresh()
            state = deepcopy(getattr(coordinator, "data", {}) or {})
            raw_api_responses = deepcopy(getattr(coordinator, "raw_api_responses", {}) or {})
            fallback_probe["success"] = True
            fallback_probe["completed_at"] = _to_iso(datetime.now(timezone.utc))
        except Exception as err:  # noqa: BLE001
            fallback_probe["error"] = str(err)
            issues.append(
                {
                    "type": "fallback_probe_failed",
                    "message": str(err),
                }
            )

    return _build_and_sanitize_payload(
        entry=entry,
        coordinator=coordinator,
        client=client,
        state=state,
        raw_api_responses=raw_api_responses,
        fallback_probe=fallback_probe,
        issues=issues,
    )
