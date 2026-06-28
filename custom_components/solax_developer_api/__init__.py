"""SolaX Developer API integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import SolaxDeveloperApiClient
from .const import (
    CONF_ALARM_NOTIFICATIONS,
    CONF_API_REGION,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_ENTITY_PREFIX,
    CONF_SCAN_INTERVAL,
    CONF_RATE_LIMIT_NOTIFICATIONS,
    CONF_SYSTEM_NAME,
    CONFIG_ENTRY_VERSION,
    CONTROL_SERVICE_DEFINITIONS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SYSTEM_NAME,
    DOMAIN,
    EVENT_DRY_RUN_CONTROL,
    EVENT_EV_CHARGER_CONTROL,
    EV_CHARGER_CONTROL_SERVICES,
    MAX_LIVE_VIEW_DURATION,
    MAX_LIVE_VIEW_INTERVAL,
    MIN_LIVE_VIEW_DURATION,
    MIN_LIVE_VIEW_INTERVAL,
    PLATFORMS,
    RUNTIME_RELOAD_STATE,
    SERVICE_CANCEL_FETCH,
    SERVICE_FETCH_PLANT_MONTH_STATISTICS,
    SERVICE_FETCH_PLANT_YEAR_STATISTICS,
    SERVICE_FETCH_DEVICE_HISTORY,
    SERVICE_FETCH_ALARM_INFORMATION,
    SERVICE_LIST_ALARM_TARGETS,
    SERVICE_LIST_HISTORY_DEVICES,
    SERVICE_LIST_PLANT_STATISTICS_TARGETS,
    SERVICE_MANUAL_REFRESH,
    SERVICE_START_LIVE_VIEW,
    SERVICE_STOP_LIVE_VIEW,
    SERVICE_QUERY_MASTER_CONTROL_DEVICE,
    SERVICE_QUERY_REQUEST_RESULT,
    config_value,
)
from .coordinator import SolaxDeveloperCoordinator
from .i18n import async_ensure_catalog_loaded, translate
from .runtime import SolaxConfigEntry, SolaxRuntimeData
from .validation import ControlValidationError, validate_control_payload

_LOGGER = logging.getLogger(__name__)


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
FRONTEND_STATIC_URL_PATH = f"/api/{DOMAIN}/frontend"
REPAIR_API_RATE_LIMIT = "api_rate_limit"
REPAIR_API_PERMISSION = "api_permission"
ALARM_NOTIFICATION_NONE = "none"
ALARM_NOTIFICATION_ACTIVE = "active"
ALARM_NOTIFICATION_CLEARED = "cleared"
_SENSITIVE_LOG_KEY_HINTS = (
    "token",
    "secret",
    "authorization",
    "api_key",
    "apikey",
    "password",
)
_SERIAL_LOG_KEY_HINTS = ("serial", "devicesn", "device_sn", "snlist", "sn_list", "registerno")


def _normalize_log_key(key: str | None) -> str:
    return str(key or "").strip().replace("-", "_").replace(" ", "_").casefold()


def _mask_log_secret(value: Any) -> Any:
    if value is None:
        return None
    text = str(value)
    if len(text) <= 2:
        return "*" * len(text)
    if len(text) <= 8:
        return f"{text[:1]}***{text[-1:]}"
    return f"{text[:4]}***{text[-4:]}"


def _mask_log_serial(value: Any) -> Any:
    if value is None:
        return None
    text = str(value)
    if len(text) <= 4:
        return "***"
    if len(text) <= 10:
        return f"{text[:2]}***{text[-2:]}"
    middle_start = max(2, (len(text) // 2) - 3)
    middle_end = min(len(text) - 2, middle_start + 6)
    return f"{text[:middle_start]}***{text[middle_end:]}"


def _sanitize_dry_run_payload_for_log(value: Any, *, key_hint: str | None = None) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_dry_run_payload_for_log(nested, key_hint=str(key))
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_dry_run_payload_for_log(item, key_hint=key_hint) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_dry_run_payload_for_log(item, key_hint=key_hint) for item in value]

    if not isinstance(value, str):
        return value

    normalized_key = _normalize_log_key(key_hint)
    if any(hint in normalized_key for hint in _SENSITIVE_LOG_KEY_HINTS):
        return _mask_log_secret(value)
    if any(hint in normalized_key for hint in _SERIAL_LOG_KEY_HINTS):
        return _mask_log_serial(value)
    if value.casefold().startswith("bearer "):
        return f"bearer {_mask_log_secret(value[7:].strip())}"
    return value


async def _async_register_frontend_assets(hass: HomeAssistant) -> None:
    runtime_state = hass.data.setdefault(RUNTIME_RELOAD_STATE, {})
    if runtime_state.get("frontend_registered"):
        return

    frontend_dir = Path(__file__).resolve().parent / "frontend"
    if not frontend_dir.exists():
        return

    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_STATIC_URL_PATH, str(frontend_dir), cache_headers=False)]
        )
        runtime_state["frontend_registered"] = True
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Failed to register frontend assets for %s: %s", DOMAIN, err)


def _rate_limit_notification_id(entry_id: str) -> str:
    return f"{DOMAIN}_rate_limit_{entry_id}"


def _alarm_notification_id(entry_id: str) -> str:
    return f"{DOMAIN}_alarm_{entry_id}"


def _rate_limit_notifications_enabled(hass: HomeAssistant, entry_id: str) -> bool:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        return True
    return bool(entry.options.get(CONF_RATE_LIMIT_NOTIFICATIONS, True))


def _alarm_notifications_enabled(hass: HomeAssistant, entry_id: str) -> bool:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        return True
    return bool(entry.options.get(CONF_ALARM_NOTIFICATIONS, True))


def _update_rate_limit_notification(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: SolaxDeveloperCoordinator,
) -> None:
    if not _rate_limit_notifications_enabled(hass, entry_id):
        persistent_notification.async_dismiss(hass, _rate_limit_notification_id(entry_id))
        return

    notification_id = _rate_limit_notification_id(entry_id)
    if not coordinator.rate_limited:
        persistent_notification.async_dismiss(hass, notification_id)
        return

    contexts = ", ".join(coordinator.rate_limited_context) or translate(
        hass,
        "runtime.labels.unknown",
        fallback="Unknown",
    )
    body = translate(
        hass,
        "runtime.notifications.rate_limit_body",
        placeholders={"contexts": contexts},
        fallback=(
            "SolaX Developer API rate/usage limit is active.\n"
            "Affected area(s): {contexts}\n"
            "Previous values are retained while recovery is in progress."
        ),
    )
    persistent_notification.async_create(
        hass,
        body,
        title=translate(
            hass,
            "runtime.notifications.rate_limit_title",
            fallback="SolaX Developer API - Rate Limit",
        ),
        notification_id=notification_id,
    )


def _alarm_notification_state(
    hass: HomeAssistant,
    entry_id: str,
) -> str:
    entry = hass.config_entries.async_get_entry(entry_id)
    runtime = getattr(entry, "runtime_data", None) if entry is not None else None
    return str(
        getattr(runtime, "alarm_notification_state", ALARM_NOTIFICATION_NONE)
        or ALARM_NOTIFICATION_NONE
    )


def _set_alarm_notification_state(
    hass: HomeAssistant,
    entry_id: str,
    state: str,
) -> None:
    entry = hass.config_entries.async_get_entry(entry_id)
    runtime = getattr(entry, "runtime_data", None) if entry is not None else None
    if runtime is not None:
        runtime.alarm_notification_state = state


def _alarm_refresh_has_errors(coordinator: SolaxDeveloperCoordinator) -> bool:
    for error in (coordinator.data.get("last_errors") or []):
        if not isinstance(error, Mapping):
            continue
        context = str(error.get("context") or "").casefold()
        endpoint = str(error.get("endpoint") or "").casefold()
        if "alarm" in context or "alarm" in endpoint:
            return True
    return False


def _plant_alarm_label(
    hass: HomeAssistant,
    plant_id: str,
    plants: Mapping[str, Any],
) -> str:
    plant = plants.get(plant_id) if isinstance(plants, Mapping) else None
    if isinstance(plant, Mapping):
        for key in ("plantName", "plant_name", "name"):
            label = str(plant.get(key) or "").strip()
            if label:
                return label
    return translate(
        hass,
        "runtime.entity_templates.plant_name",
        placeholders={"plant_id": plant_id},
        fallback="Plant {plant_id}",
    )


def _alarm_field_text(hass: HomeAssistant, value: Any) -> str:
    text = str(value or "").strip()
    if text:
        return text
    return translate(hass, "runtime.labels.unknown", fallback="Unknown")


def _active_alarm_summary(
    hass: HomeAssistant,
    coordinator: SolaxDeveloperCoordinator,
) -> tuple[int, list[dict[str, str]]]:
    alarms = coordinator.data.get("alarms") or {}
    plants = coordinator.data.get("plants") or {}
    total = 0
    details: list[dict[str, str]] = []

    if not isinstance(alarms, Mapping):
        return 0, []

    for plant_id_raw, alarm_payload in sorted(alarms.items(), key=lambda item: str(item[0])):
        plant_id = str(plant_id_raw)
        if not isinstance(alarm_payload, Mapping):
            continue
        records = alarm_payload.get("records") or []
        if not isinstance(records, list):
            records = []
        try:
            total += int(alarm_payload.get("total") or len(records))
        except (TypeError, ValueError):
            total += len(records)
        plant_label = _plant_alarm_label(hass, plant_id, plants)
        for record in records:
            if not isinstance(record, Mapping):
                continue
            details.append(
                {
                    "plant": plant_label,
                    "alarm_name": _alarm_field_text(hass, record.get("alarmName")),
                    "error_code": _alarm_field_text(hass, record.get("errorCode")),
                    "alarm_type": _alarm_field_text(hass, record.get("alarmType")),
                }
            )

    return total, details


def _alarm_detail_lines(
    hass: HomeAssistant,
    total: int,
    details: list[dict[str, str]],
) -> str:
    rendered: list[str] = []
    for detail in details[:3]:
        rendered.append(
            translate(
                hass,
                "runtime.notifications.alarm_active_detail_line",
                placeholders=detail,
                fallback=(
                    "- {plant}: {alarm_name} "
                    "(code: {error_code}, type: {alarm_type})"
                ),
            )
        )

    remaining = max(0, total - len(rendered))
    if remaining:
        rendered.append(
            translate(
                hass,
                "runtime.notifications.alarm_active_more_line",
                placeholders={"count": remaining},
                fallback="- and {count} more active alarm(s)",
            )
        )

    if rendered:
        return "\n".join(rendered)

    return translate(
        hass,
        "runtime.notifications.alarm_active_no_details",
        fallback="- No detailed alarm records were returned by SolaX.",
    )


def _update_alarm_notification(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: SolaxDeveloperCoordinator,
) -> None:
    notification_id = _alarm_notification_id(entry_id)
    if not _alarm_notifications_enabled(hass, entry_id):
        persistent_notification.async_dismiss(hass, notification_id)
        _set_alarm_notification_state(hass, entry_id, ALARM_NOTIFICATION_NONE)
        return

    total, details = _active_alarm_summary(hass, coordinator)
    previous_state = _alarm_notification_state(hass, entry_id)

    if total > 0:
        body = translate(
            hass,
            "runtime.notifications.alarm_active_body",
            placeholders={
                "count": total,
                "alarm_details": _alarm_detail_lines(hass, total, details),
            },
            fallback=(
                "SolaX reports {count} active alarm(s).\n"
                "{alarm_details}\n"
                "Open the SolaX Alarm Viewer card for full details."
            ),
        )
        persistent_notification.async_create(
            hass,
            body,
            title=translate(
                hass,
                "runtime.notifications.alarm_active_title",
                fallback="SolaX active alarm detected",
            ),
            notification_id=notification_id,
        )
        _set_alarm_notification_state(hass, entry_id, ALARM_NOTIFICATION_ACTIVE)
        return

    if _alarm_refresh_has_errors(coordinator):
        return

    if previous_state == ALARM_NOTIFICATION_ACTIVE:
        persistent_notification.async_create(
            hass,
            translate(
                hass,
                "runtime.notifications.alarm_cleared_body",
                fallback=(
                    "SolaX reports no active alarms now.\n"
                    "The previous active alarm notification has cleared."
                ),
            ),
            title=translate(
                hass,
                "runtime.notifications.alarm_cleared_title",
                fallback="SolaX alarms cleared",
            ),
            notification_id=notification_id,
        )
        _set_alarm_notification_state(hass, entry_id, ALARM_NOTIFICATION_CLEARED)
        return

    if previous_state == ALARM_NOTIFICATION_NONE:
        persistent_notification.async_dismiss(hass, notification_id)


def _repair_issue_id(entry_id: str, issue_type: str) -> str:
    return f"{entry_id}_{issue_type}"


def _update_repairs(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: SolaxDeveloperCoordinator,
) -> None:
    """Create only actionable issues and clear them after recovery."""
    rate_issue_id = _repair_issue_id(entry_id, REPAIR_API_RATE_LIMIT)
    if coordinator.rate_limited:
        ir.async_create_issue(
            hass,
            DOMAIN,
            rate_issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=REPAIR_API_RATE_LIMIT,
            translation_placeholders={
                "contexts": ", ".join(coordinator.rate_limited_context) or "API",
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, rate_issue_id)

    permission_contexts = sorted(
        {
            str(error.get("context") or "API")
            for error in (coordinator.data.get("last_errors") or [])
            if isinstance(error, Mapping)
            and str(error.get("classification") or "").casefold() == "permission"
        }
    )
    permission_issue_id = _repair_issue_id(entry_id, REPAIR_API_PERMISSION)
    if permission_contexts:
        ir.async_create_issue(
            hass,
            DOMAIN,
            permission_issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=REPAIR_API_PERMISSION,
            translation_placeholders={"contexts": ", ".join(permission_contexts)},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, permission_issue_id)


def _loaded_runtime_for_entry(
    hass: HomeAssistant,
    entry_id: str,
) -> SolaxRuntimeData | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        return None
    return getattr(entry, "runtime_data", None)


def _translated_service_error(
    translation_key: str,
    *,
    placeholders: Mapping[str, Any] | None = None,
) -> ServiceValidationError:
    """Build a frontend-translatable service validation error."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=translation_key.rsplit(".", 1)[-1],
        translation_placeholders={
            key: str(value) for key, value in (placeholders or {}).items()
        },
    )


def _coordinator_for_entry(hass: HomeAssistant, entry_id: str) -> SolaxDeveloperCoordinator:
    runtime = _loaded_runtime_for_entry(hass, entry_id)
    if runtime is None:
        raise _translated_service_error(
            "no_active_entry",
            placeholders={"domain": DOMAIN, "entry_id": entry_id},
        )
    return runtime.coordinator


def _resolve_coordinator_for_service(
    hass: HomeAssistant,
    call: ServiceCall,
) -> tuple[str, SolaxDeveloperCoordinator]:
    loaded_entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        and getattr(entry, "runtime_data", None) is not None
    ]
    if not loaded_entries:
        raise _translated_service_error("no_configured_entries")

    explicit_entry_id = str(call.data.get("entry_id", "")).strip()
    if explicit_entry_id:
        return explicit_entry_id, _coordinator_for_entry(hass, explicit_entry_id)

    entry = loaded_entries[0]
    return entry.entry_id, entry.runtime_data.coordinator


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up integration domain level services."""
    await async_ensure_catalog_loaded(hass)
    await _async_register_frontend_assets(hass)

    async def _handle_manual_refresh(call: ServiceCall):
        explicit_entry_id = str(call.data.get("entry_id", "")).strip()
        refreshed_entries = []
        for config_entry in hass.config_entries.async_entries(DOMAIN):
            entry_id = config_entry.entry_id
            if explicit_entry_id and entry_id != explicit_entry_id:
                continue
            runtime = _loaded_runtime_for_entry(hass, entry_id)
            if runtime is None:
                continue
            coordinator = runtime.coordinator
            await coordinator.async_request_refresh()
            refreshed_entries.append(entry_id)
        return {
            "ok": True,
            "entries": refreshed_entries,
            "count": len(refreshed_entries),
        }

    async def _handle_list_history_devices(call: ServiceCall):
        explicit_entry_id = str(call.data.get("entry_id", "")).strip()
        devices: list[dict[str, Any]] = []
        entry_ids: list[str] = []

        for config_entry in hass.config_entries.async_entries(DOMAIN):
            entry_id = config_entry.entry_id
            if explicit_entry_id and entry_id != explicit_entry_id:
                continue
            runtime = _loaded_runtime_for_entry(hass, entry_id)
            if runtime is None:
                continue
            coordinator = runtime.coordinator
            for device in coordinator.list_history_devices():
                devices.append({**device, "entry_id": entry_id})
            entry_ids.append(entry_id)

        return {
            "ok": True,
            "entry_id": explicit_entry_id or (entry_ids[0] if len(entry_ids) == 1 else None),
            "entries": entry_ids,
            "count": len(devices),
            "devices": devices,
        }

    async def _handle_list_plant_statistics_targets(call: ServiceCall):
        explicit_entry_id = str(call.data.get("entry_id", "")).strip()
        plants: list[dict[str, Any]] = []
        entry_ids: list[str] = []

        for config_entry in hass.config_entries.async_entries(DOMAIN):
            entry_id = config_entry.entry_id
            if explicit_entry_id and entry_id != explicit_entry_id:
                continue
            runtime = _loaded_runtime_for_entry(hass, entry_id)
            if runtime is None:
                continue
            coordinator = runtime.coordinator
            for plant in coordinator.list_plant_statistics_targets():
                plants.append({**plant, "entry_id": entry_id})
            entry_ids.append(entry_id)

        return {
            "ok": True,
            "entry_id": explicit_entry_id or (entry_ids[0] if len(entry_ids) == 1 else None),
            "entries": entry_ids,
            "count": len(plants),
            "plants": plants,
        }

    async def _handle_list_alarm_targets(call: ServiceCall):
        explicit_entry_id = str(call.data.get("entry_id", "")).strip()
        plants: list[dict[str, Any]] = []
        devices: list[dict[str, Any]] = []
        entry_ids: list[str] = []

        for config_entry in hass.config_entries.async_entries(DOMAIN):
            entry_id = config_entry.entry_id
            if explicit_entry_id and entry_id != explicit_entry_id:
                continue
            runtime = _loaded_runtime_for_entry(hass, entry_id)
            if runtime is None:
                continue
            targets = runtime.coordinator.list_alarm_targets()
            plants.extend({**plant, "entry_id": entry_id} for plant in targets["plants"])
            devices.extend({**device, "entry_id": entry_id} for device in targets["devices"])
            entry_ids.append(entry_id)

        return {
            "ok": True,
            "entry_id": explicit_entry_id or (entry_ids[0] if len(entry_ids) == 1 else None),
            "entries": entry_ids,
            "plant_count": len(plants),
            "device_count": len(devices),
            "plants": plants,
            "devices": devices,
        }

    async def _handle_fetch_history(call: ServiceCall):
        _entry_id, coordinator = _resolve_coordinator_for_service(hass, call)
        start_time = int(call.data["start_time"])
        end_time = int(call.data["end_time"])
        if end_time <= start_time:
            raise _translated_service_error("history_end_before_start")
        response = await coordinator.async_fetch_device_history(
            sn_list=call.data["sn_list"],
            device_type=int(call.data["device_type"]),
            business_type=int(call.data["business_type"]),
            start_time=start_time,
            end_time=end_time,
            time_interval=int(call.data["time_interval"]),
            request_sn_type=(
                int(call.data["request_sn_type"])
                if call.data.get("request_sn_type") is not None
                else None
            ),
            request_id=str(call.data.get("request_id") or "").strip() or None,
        )
        return response

    async def _handle_fetch_plant_year_statistics(call: ServiceCall):
        _entry_id, coordinator = _resolve_coordinator_for_service(hass, call)
        year = int(call.data["year"])
        current_year = dt_util.now().year
        if year < 2000 or year > current_year:
            raise _translated_service_error(
                "plant_year_invalid",
                placeholders={"min_year": 2000, "max_year": current_year},
            )
        return await coordinator.async_fetch_plant_year_statistics(
            plant_id=str(call.data["plant_id"]).strip(),
            business_type=int(call.data["business_type"]),
            year=year,
            request_id=str(call.data.get("request_id") or "").strip() or None,
        )

    async def _handle_fetch_plant_month_statistics(call: ServiceCall):
        _entry_id, coordinator = _resolve_coordinator_for_service(hass, call)
        year = int(call.data["year"])
        month = int(call.data["month"])
        current = dt_util.now()
        if year < 2000 or year > current.year:
            raise _translated_service_error(
                "plant_year_invalid",
                placeholders={"min_year": 2000, "max_year": current.year},
            )
        if year == current.year and month > current.month:
            raise _translated_service_error(
                "plant_month_invalid",
                placeholders={"min_month": 1, "max_month": current.month},
            )
        if month < 1 or month > 12:
            raise _translated_service_error(
                "plant_month_invalid",
                placeholders={"min_month": 1, "max_month": 12},
            )
        return await coordinator.async_fetch_plant_month_statistics(
            plant_id=str(call.data["plant_id"]).strip(),
            business_type=int(call.data["business_type"]),
            year=year,
            month=month,
            request_id=str(call.data.get("request_id") or "").strip() or None,
        )

    async def _handle_fetch_alarm_information(call: ServiceCall):
        _entry_id, coordinator = _resolve_coordinator_for_service(hass, call)
        return await coordinator.async_fetch_alarm_information(
            plant_id=str(call.data.get("plant_id") or "").strip() or None,
            business_type=(
                int(call.data["business_type"])
                if call.data.get("business_type") is not None
                else None
            ),
            alarm_state=call.data.get("alarm_state", "all"),
            device_sn=str(call.data.get("device_sn") or "").strip() or None,
            max_pages=int(call.data.get("max_pages") or 20),
            request_id=str(call.data.get("request_id") or "").strip() or None,
        )

    async def _handle_cancel_fetch(call: ServiceCall):
        request_id = str(call.data["request_id"]).strip()
        explicit_entry_id = str(call.data.get("entry_id") or "").strip()
        if explicit_entry_id:
            entry_id, coordinator = _resolve_coordinator_for_service(hass, call)
            result = coordinator.cancel_fetch(request_id)
            return {"ok": result["ok"], "entries": {entry_id: result}}
        results: dict[str, Any] = {}
        for config_entry in hass.config_entries.async_entries(DOMAIN):
            runtime = _loaded_runtime_for_entry(hass, config_entry.entry_id)
            if runtime is None:
                continue
            results[config_entry.entry_id] = runtime.coordinator.cancel_fetch(request_id)
        return {
            "ok": bool(results),
            "request_id": request_id,
            "entries": results,
        }

    async def _handle_query_request_result(call: ServiceCall):
        _entry_id, coordinator = _resolve_coordinator_for_service(hass, call)
        payload = await coordinator.async_query_request_result(
            str(call.data["request_id"]).strip()
        )
        return payload

    async def _handle_query_master_control_device(call: ServiceCall):
        _entry_id, coordinator = _resolve_coordinator_for_service(hass, call)
        business_type = int(call.data["business_type"])
        if business_type != 4:
            raise _translated_service_error("master_control_requires_ci")
        payload = await coordinator.async_query_master_control_device(
            device_sn=str(call.data["device_sn"]).strip(),
            device_type=int(call.data["device_type"]),
            business_type=business_type,
        )
        return payload

    async def _handle_start_live_view(call: ServiceCall):
        _entry_id, coordinator = _resolve_coordinator_for_service(hass, call)
        return await coordinator.async_start_live_view(
            duration_seconds=(
                int(call.data["duration_seconds"])
                if call.data.get("duration_seconds") is not None
                else None
            ),
            interval_seconds=(
                int(call.data["interval_seconds"])
                if call.data.get("interval_seconds") is not None
                else None
            ),
        )

    async def _handle_stop_live_view(call: ServiceCall):
        _entry_id, coordinator = _resolve_coordinator_for_service(hass, call)
        return await coordinator.async_stop_live_view()

    def _register_service(name: str, handler, schema=None) -> None:
        if hass.services.has_service(DOMAIN, name):
            return
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=schema,
            supports_response=SupportsResponse.OPTIONAL,
        )

    _register_service(
        SERVICE_MANUAL_REFRESH,
        _handle_manual_refresh,
        schema=vol.Schema({vol.Optional("entry_id"): str}),
    )

    list_history_devices_schema = vol.Schema({vol.Optional("entry_id"): str})
    list_plant_statistics_targets_schema = vol.Schema({vol.Optional("entry_id"): str})
    list_alarm_targets_schema = vol.Schema({vol.Optional("entry_id"): str})

    history_schema = vol.Schema(
        {
            vol.Optional("entry_id"): str,
            vol.Required("sn_list"): vol.All([str], vol.Length(min=1, max=200)),
            vol.Required("device_type"): vol.All(
                vol.Coerce(int), vol.In([1, 2, 3, 4])
            ),
            vol.Required("business_type"): vol.All(
                vol.Coerce(int), vol.In([1, 4])
            ),
            vol.Required("start_time"): vol.Coerce(int),
            vol.Required("end_time"): vol.Coerce(int),
            vol.Required("time_interval"): vol.All(
                vol.Coerce(int), vol.In([5, 10, 15, 30, 60])
            ),
            vol.Optional("request_sn_type"): vol.All(
                vol.Coerce(int), vol.In([1, 2])
            ),
            vol.Optional("request_id"): vol.All(
                vol.Coerce(str), vol.Length(min=1)
            ),
        }
    )

    plant_year_statistics_schema = vol.Schema(
        {
            vol.Optional("entry_id"): str,
            vol.Required("plant_id"): vol.All(str, vol.Length(min=1)),
            vol.Required("business_type"): vol.All(
                vol.Coerce(int), vol.In([1, 4])
            ),
            vol.Required("year"): vol.Coerce(int),
            vol.Optional("request_id"): vol.All(
                vol.Coerce(str), vol.Length(min=1)
            ),
        }
    )
    plant_month_statistics_schema = vol.Schema(
        {
            vol.Optional("entry_id"): str,
            vol.Required("plant_id"): vol.All(str, vol.Length(min=1)),
            vol.Required("business_type"): vol.All(
                vol.Coerce(int), vol.In([1, 4])
            ),
            vol.Required("year"): vol.Coerce(int),
            vol.Required("month"): vol.Coerce(int),
            vol.Optional("request_id"): vol.All(
                vol.Coerce(str), vol.Length(min=1)
            ),
        }
    )
    alarm_information_schema = vol.Schema(
        {
            vol.Optional("entry_id"): str,
            vol.Optional("plant_id"): str,
            vol.Optional("business_type"): vol.All(
                vol.Coerce(int), vol.In([1, 4])
            ),
            vol.Optional("alarm_state", default="all"): vol.All(
                vol.Coerce(str), vol.In(["all", "ongoing", "closed", "0", "1"])
            ),
            vol.Optional("device_sn"): str,
            vol.Optional("max_pages", default=20): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=100)
            ),
            vol.Optional("request_id"): vol.All(
                vol.Coerce(str), vol.Length(min=1)
            ),
        }
    )

    cancel_fetch_schema = vol.Schema(
        {
            vol.Optional("entry_id"): str,
            vol.Required("request_id"): vol.All(
                vol.Coerce(str), vol.Length(min=1)
            ),
        }
    )

    request_result_schema = vol.Schema(
        {
            vol.Optional("entry_id"): str,
            vol.Required("request_id"): vol.All(
                vol.Coerce(str), vol.Length(min=1)
            ),
        }
    )

    master_control_schema = vol.Schema(
        {
            vol.Optional("entry_id"): str,
            vol.Required("device_sn"): str,
            vol.Required("device_type"): vol.All(
                vol.Coerce(int), vol.In([1, 2, 3, 4, 100])
            ),
            vol.Required("business_type"): vol.All(
                vol.Coerce(int), vol.In([4])
            ),
        }
    )

    _register_service(
        SERVICE_START_LIVE_VIEW,
        _handle_start_live_view,
        schema=vol.Schema(
            {
                vol.Optional("entry_id"): str,
                vol.Optional("duration_seconds"): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_LIVE_VIEW_DURATION, max=MAX_LIVE_VIEW_DURATION),
                ),
                vol.Optional("interval_seconds"): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_LIVE_VIEW_INTERVAL, max=MAX_LIVE_VIEW_INTERVAL),
                ),
            }
        ),
    )

    _register_service(
        SERVICE_STOP_LIVE_VIEW,
        _handle_stop_live_view,
        schema=vol.Schema({vol.Optional("entry_id"): str}),
    )

    def _register_universal_services() -> None:
        _register_service(
            SERVICE_MANUAL_REFRESH,
            _handle_manual_refresh,
            schema=vol.Schema({vol.Optional("entry_id"): str}),
        )
        _register_service(
            SERVICE_LIST_HISTORY_DEVICES,
            _handle_list_history_devices,
            schema=list_history_devices_schema,
        )
        _register_service(
            SERVICE_LIST_PLANT_STATISTICS_TARGETS,
            _handle_list_plant_statistics_targets,
            schema=list_plant_statistics_targets_schema,
        )
        _register_service(
            SERVICE_LIST_ALARM_TARGETS,
            _handle_list_alarm_targets,
            schema=list_alarm_targets_schema,
        )
        _register_service(
            SERVICE_START_LIVE_VIEW,
            _handle_start_live_view,
            schema=vol.Schema(
                {
                    vol.Optional("entry_id"): str,
                    vol.Optional("duration_seconds"): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_LIVE_VIEW_DURATION,
                            max=MAX_LIVE_VIEW_DURATION,
                        ),
                    ),
                    vol.Optional("interval_seconds"): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_LIVE_VIEW_INTERVAL,
                            max=MAX_LIVE_VIEW_INTERVAL,
                        ),
                    ),
                }
            ),
        )
        _register_service(
            SERVICE_STOP_LIVE_VIEW,
            _handle_stop_live_view,
            schema=vol.Schema({vol.Optional("entry_id"): str}),
        )
        _register_service(
            SERVICE_CANCEL_FETCH,
            _handle_cancel_fetch,
            schema=cancel_fetch_schema,
        )

    control_handlers: dict[str, Any] = {}
    for service_name, definition in CONTROL_SERVICE_DEFINITIONS.items():

        async def _handler(call: ServiceCall, _service_name=service_name, _definition=definition):
            _entry_id, coordinator = _resolve_coordinator_for_service(hass, call)
            raw_payload = {
                key: value
                for key, value in call.data.items()
                if key != "entry_id"
            }
            try:
                validated_payload = validate_control_payload(_service_name, raw_payload)
            except ControlValidationError as err:
                raise _translated_service_error(
                    err.key,
                    placeholders=err.placeholders,
                ) from err
            if _service_name not in coordinator.available_control_services:
                raise _translated_service_error(
                    "control_not_available",
                    placeholders={"service": _service_name},
                )
            if (
                _service_name in EV_CHARGER_CONTROL_SERVICES
                and getattr(coordinator, "ev_charger_controls_enabled", False)
            ):
                try:
                    event = await coordinator.async_execute_ev_charger_control(
                        service=_service_name,
                        endpoint=_definition["endpoint"],
                        payload=validated_payload,
                    )
                except ValueError as err:
                    raise _translated_service_error(
                        str(err),
                        placeholders={"service": _service_name},
                    ) from err
                hass.bus.async_fire(EVENT_EV_CHARGER_CONTROL, event)
                _LOGGER.warning(
                    "Executed EV charger control service '%s' endpoint '%s'",
                    _service_name,
                    _definition["endpoint"],
                )
                _LOGGER.debug(
                    "EV charger control sanitized payload service='%s' endpoint='%s' payload=%s",
                    _service_name,
                    _definition["endpoint"],
                    _sanitize_dry_run_payload_for_log(validated_payload),
                )
                return {
                    "ok": bool(event.get("accepted")),
                    "blocked": False,
                    "sent": True,
                    "accepted": bool(event.get("accepted")),
                    "service": _service_name,
                    "endpoint": _definition["endpoint"],
                    "request_id": event.get("request_id"),
                    "device_statuses": event.get("device_statuses") or {},
                    "response": event.get("response") or {},
                    "timestamp": event["timestamp"],
                }
            event = coordinator.record_control_dry_run(
                service=_service_name,
                endpoint=_definition["endpoint"],
                payload=validated_payload,
            )
            hass.bus.async_fire(EVENT_DRY_RUN_CONTROL, event)
            _LOGGER.warning(
                "Dry-run blocked service call '%s' endpoint '%s'",
                _service_name,
                _definition["endpoint"],
            )
            _LOGGER.debug(
                "Dry-run sanitized payload service='%s' endpoint='%s' payload=%s",
                _service_name,
                _definition["endpoint"],
                _sanitize_dry_run_payload_for_log(validated_payload),
            )
            return {
                "ok": False,
                "blocked": True,
                "service": _service_name,
                "endpoint": _definition["endpoint"],
                "reason": event["reason"],
                "payload": validated_payload,
                "timestamp": event["timestamp"],
            }

        control_handlers[service_name] = _handler

    def _sync_capability_services() -> None:
        coordinators = [
            entry.runtime_data.coordinator
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
            and getattr(entry, "runtime_data", None) is not None
        ]
        desired: set[str] = set()
        if any(coordinator.has_history_capable_devices for coordinator in coordinators):
            desired.add(SERVICE_FETCH_DEVICE_HISTORY)
        if any(coordinator.list_plant_statistics_targets() for coordinator in coordinators):
            desired.add(SERVICE_FETCH_PLANT_YEAR_STATISTICS)
            desired.add(SERVICE_FETCH_PLANT_MONTH_STATISTICS)
            desired.add(SERVICE_FETCH_ALARM_INFORMATION)
        if any(coordinator.has_ci_devices for coordinator in coordinators):
            desired.add(SERVICE_QUERY_MASTER_CONTROL_DEVICE)

        available_controls: set[str] = set()
        for coordinator in coordinators:
            available_controls.update(coordinator.available_control_services)
        desired.update(available_controls)
        if available_controls:
            desired.add(SERVICE_QUERY_REQUEST_RESULT)

        registrations = {
            SERVICE_FETCH_DEVICE_HISTORY: (_handle_fetch_history, history_schema),
            SERVICE_FETCH_PLANT_YEAR_STATISTICS: (
                _handle_fetch_plant_year_statistics,
                plant_year_statistics_schema,
            ),
            SERVICE_FETCH_PLANT_MONTH_STATISTICS: (
                _handle_fetch_plant_month_statistics,
                plant_month_statistics_schema,
            ),
            SERVICE_FETCH_ALARM_INFORMATION: (
                _handle_fetch_alarm_information,
                alarm_information_schema,
            ),
            SERVICE_QUERY_REQUEST_RESULT: (
                _handle_query_request_result,
                request_result_schema,
            ),
            SERVICE_QUERY_MASTER_CONTROL_DEVICE: (
                _handle_query_master_control_device,
                master_control_schema,
            ),
        }
        registrations.update(
            {
                service_name: (
                    handler,
                    vol.Schema(
                        {vol.Optional("entry_id"): str},
                        extra=vol.ALLOW_EXTRA,
                    ),
                )
                for service_name, handler in control_handlers.items()
            }
        )
        for service_name, (handler, schema) in registrations.items():
            if service_name in desired:
                _register_service(service_name, handler, schema=schema)
            elif hass.services.has_service(DOMAIN, service_name):
                hass.services.async_remove(DOMAIN, service_name)

    runtime_state = hass.data.setdefault(RUNTIME_RELOAD_STATE, {})
    runtime_state["register_universal_services"] = _register_universal_services
    runtime_state["sync_capability_services"] = _sync_capability_services
    _register_universal_services()
    _sync_capability_services()

    return True


async def async_setup_entry(hass: HomeAssistant, entry: SolaxConfigEntry) -> bool:
    """Set up SolaX Developer API from config entry."""
    await async_ensure_catalog_loaded(hass)

    session = async_get_clientsession(hass)
    client = SolaxDeveloperApiClient(
        client_id=str(entry.data[CONF_CLIENT_ID]).strip(),
        client_secret=str(entry.data[CONF_CLIENT_SECRET]).strip(),
        region=str(entry.data.get(CONF_API_REGION, "eu")).strip().lower(),
        session=session,
    )

    coordinator = SolaxDeveloperCoordinator(
        hass,
        client=client,
        config_entry=entry,
        entry_id=entry.entry_id,
        scan_interval=int(config_value(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        options=dict(entry.options or {}),
    )
    entry.runtime_data = SolaxRuntimeData(
        client=client,
        coordinator=coordinator,
    )

    await coordinator.async_load_capability_cache()
    await coordinator.async_config_entry_first_refresh()

    register_universal_services = hass.data.get(RUNTIME_RELOAD_STATE, {}).get(
        "register_universal_services"
    )
    if callable(register_universal_services):
        register_universal_services()

    _update_rate_limit_notification(hass, entry.entry_id, coordinator)
    _update_alarm_notification(hass, entry.entry_id, coordinator)
    _update_repairs(hass, entry.entry_id, coordinator)

    def _handle_coordinator_update() -> None:
        _update_rate_limit_notification(hass, entry.entry_id, coordinator)
        _update_alarm_notification(hass, entry.entry_id, coordinator)
        _update_repairs(hass, entry.entry_id, coordinator)
        sync_services = hass.data.get(RUNTIME_RELOAD_STATE, {}).get(
            "sync_capability_services"
        )
        if callable(sync_services):
            sync_services()

    unsub = coordinator.async_add_listener(_handle_coordinator_update)

    entry.runtime_data.rate_limit_unsub = unsub
    sync_services = hass.data.get(RUNTIME_RELOAD_STATE, {}).get(
        "sync_capability_services"
    )
    if callable(sync_services):
        sync_services()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy connection data into the correct config-entry stores."""
    if entry.version > CONFIG_ENTRY_VERSION:
        return False
    if entry.version == CONFIG_ENTRY_VERSION:
        return True

    data = dict(entry.data)
    options = dict(entry.options)
    for key, default in (
        (CONF_SYSTEM_NAME, DEFAULT_SYSTEM_NAME),
        (CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        (CONF_ENTITY_PREFIX, None),
    ):
        value = data.pop(key, default)
        if value is not None:
            options.setdefault(key, value)

    system_name = str(options.get(CONF_SYSTEM_NAME) or DEFAULT_SYSTEM_NAME).strip()
    options[CONF_SYSTEM_NAME] = system_name
    options.setdefault(
        CONF_ENTITY_PREFIX,
        system_name.lower().replace(" ", "_").replace("-", "_"),
    )

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        version=CONFIG_ENTRY_VERSION,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SolaxConfigEntry) -> bool:
    """Unload config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    if unsub := entry.runtime_data.rate_limit_unsub:
        unsub()

    persistent_notification.async_dismiss(hass, _rate_limit_notification_id(entry.entry_id))
    persistent_notification.async_dismiss(hass, _alarm_notification_id(entry.entry_id))
    ir.async_delete_issue(
        hass,
        DOMAIN,
        _repair_issue_id(entry.entry_id, REPAIR_API_RATE_LIMIT),
    )
    ir.async_delete_issue(
        hass,
        DOMAIN,
        _repair_issue_id(entry.entry_id, REPAIR_API_PERMISSION),
    )
    sync_services = hass.data.get(RUNTIME_RELOAD_STATE, {}).get(
        "sync_capability_services"
    )
    if callable(sync_services):
        sync_services()

    # Remove services when no entries remain.
    if not any(
        config_entry.state is ConfigEntryState.LOADED
        for config_entry in hass.config_entries.async_entries(DOMAIN)
        if config_entry.entry_id != entry.entry_id
    ):
        for service_name in [
            SERVICE_MANUAL_REFRESH,
            SERVICE_LIST_HISTORY_DEVICES,
            SERVICE_FETCH_DEVICE_HISTORY,
            SERVICE_LIST_PLANT_STATISTICS_TARGETS,
            SERVICE_FETCH_PLANT_YEAR_STATISTICS,
            SERVICE_FETCH_PLANT_MONTH_STATISTICS,
            SERVICE_LIST_ALARM_TARGETS,
            SERVICE_FETCH_ALARM_INFORMATION,
            SERVICE_CANCEL_FETCH,
            SERVICE_START_LIVE_VIEW,
            SERVICE_STOP_LIVE_VIEW,
            SERVICE_QUERY_REQUEST_RESULT,
            SERVICE_QUERY_MASTER_CONTROL_DEVICE,
            *CONTROL_SERVICE_DEFINITIONS.keys(),
        ]:
            if hass.services.has_service(DOMAIN, service_name):
                hass.services.async_remove(DOMAIN, service_name)

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: SolaxConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow removal only when a device is absent from current SolaX inventory."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return False

    state = runtime.coordinator.data or {}
    current_identifiers = {
        f"plant_{plant_id}" for plant_id in (state.get("plants") or {})
    }
    current_identifiers.update(str(serial) for serial in (state.get("devices") or {}))

    system_name = str(config_value(entry, CONF_SYSTEM_NAME, DEFAULT_SYSTEM_NAME))
    system_slug = str(
        config_value(
            entry,
            CONF_ENTITY_PREFIX,
            system_name.lower().replace(" ", "_").replace("-", "_"),
        )
    )
    current_identifiers.add(f"system_{system_slug}")

    integration_identifiers = {
        identifier
        for domain, identifier in device_entry.identifiers
        if domain == DOMAIN
    }
    return bool(integration_identifiers) and integration_identifiers.isdisjoint(
        current_identifiers
    )
