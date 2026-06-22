"""SolaX Developer API integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SolaxDeveloperApiClient
from .const import (
    CONF_API_REGION,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_SCAN_INTERVAL,
    CONF_RATE_LIMIT_NOTIFICATIONS,
    CONTROL_SERVICE_DEFINITIONS,
    DOMAIN,
    EVENT_DRY_RUN_CONTROL,
    MAX_LIVE_VIEW_DURATION,
    MAX_LIVE_VIEW_INTERVAL,
    MIN_LIVE_VIEW_DURATION,
    MIN_LIVE_VIEW_INTERVAL,
    PLATFORMS,
    RUNTIME_RELOAD_STATE,
    SERVICE_FETCH_DEVICE_HISTORY,
    SERVICE_MANUAL_REFRESH,
    SERVICE_START_LIVE_VIEW,
    SERVICE_STOP_LIVE_VIEW,
    SERVICE_QUERY_MASTER_CONTROL_DEVICE,
    SERVICE_QUERY_REQUEST_RESULT,
)
from .coordinator import SolaxDeveloperCoordinator
from .i18n import async_ensure_catalog_loaded, translate
from .validation import ControlValidationError, validate_control_payload

_LOGGER = logging.getLogger(__name__)


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
FRONTEND_STATIC_URL_PATH = f"/api/{DOMAIN}/frontend"
REPAIR_API_RATE_LIMIT = "api_rate_limit"
REPAIR_API_PERMISSION = "api_permission"
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


def _rate_limit_notifications_enabled(hass: HomeAssistant, entry_id: str) -> bool:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        return True
    return bool(entry.options.get(CONF_RATE_LIMIT_NOTIFICATIONS, True))


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


def _coordinator_for_entry(hass: HomeAssistant, entry_id: str) -> SolaxDeveloperCoordinator:
    entry_data = hass.data.get(DOMAIN, {}).get(entry_id)
    if not entry_data:
        raise HomeAssistantError(
            translate(
                hass,
                "runtime.errors.no_active_entry",
                placeholders={"domain": DOMAIN, "entry_id": entry_id},
                fallback="No active {domain} entry for {entry_id}",
            )
        )
    return entry_data["coordinator"]


def _resolve_coordinator_for_service(
    hass: HomeAssistant,
    call: ServiceCall,
) -> tuple[str, SolaxDeveloperCoordinator]:
    domain_data = hass.data.get(DOMAIN, {})
    if not domain_data:
        raise HomeAssistantError(
            translate(
                hass,
                "runtime.errors.no_configured_entries",
                fallback="No configured SolaX Developer API entries",
            )
        )

    explicit_entry_id = str(call.data.get("entry_id", "")).strip()
    if explicit_entry_id:
        return explicit_entry_id, _coordinator_for_entry(hass, explicit_entry_id)

    entry_id = next(iter(domain_data.keys()))
    return entry_id, domain_data[entry_id]["coordinator"]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up integration domain level services."""
    await async_ensure_catalog_loaded(hass)
    await _async_register_frontend_assets(hass)

    async def _handle_manual_refresh(call: ServiceCall):
        domain_data = hass.data.get(DOMAIN, {})
        explicit_entry_id = str(call.data.get("entry_id", "")).strip()
        refreshed_entries = []
        for entry_id, entry_data in domain_data.items():
            if explicit_entry_id and entry_id != explicit_entry_id:
                continue
            coordinator: SolaxDeveloperCoordinator = entry_data["coordinator"]
            await coordinator.async_request_refresh()
            refreshed_entries.append(entry_id)
        return {
            "ok": True,
            "entries": refreshed_entries,
            "count": len(refreshed_entries),
        }

    async def _handle_fetch_history(call: ServiceCall):
        _entry_id, coordinator = _resolve_coordinator_for_service(hass, call)
        start_time = int(call.data["start_time"])
        end_time = int(call.data["end_time"])
        if end_time <= start_time:
            raise HomeAssistantError(
                translate(
                    hass,
                    "runtime.errors.history_end_before_start",
                    fallback="end_time must be greater than start_time",
                )
            )
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
        )
        return response

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
            raise HomeAssistantError(
                translate(
                    hass,
                    "runtime.errors.master_control_requires_ci",
                    fallback="query_master_control_device supports business_type=4 only",
                )
            )
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
                raise HomeAssistantError(
                    translate(
                        hass,
                        err.key,
                        placeholders=err.placeholders,
                        fallback=err.key,
                    )
                ) from err
            if _service_name not in coordinator.available_control_services:
                raise HomeAssistantError(
                    translate(
                        hass,
                        "runtime.errors.control_not_available",
                        placeholders={"service": _service_name},
                        fallback=(
                            "{service}: no compatible device capability is "
                            "available in this integration"
                        ),
                    )
                )
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
            entry_data.get("coordinator")
            for entry_data in hass.data.get(DOMAIN, {}).values()
            if isinstance(entry_data, Mapping)
        ]
        coordinators = [item for item in coordinators if item is not None]
        desired: set[str] = set()
        if any(coordinator.has_history_capable_devices for coordinator in coordinators):
            desired.add(SERVICE_FETCH_DEVICE_HISTORY)
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SolaX Developer API from config entry."""
    hass.data.setdefault(DOMAIN, {})
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
        entry_id=entry.entry_id,
        scan_interval=int(entry.data[CONF_SCAN_INTERVAL]),
        options=dict(entry.options or {}),
    )

    await coordinator.async_load_capability_cache()
    await coordinator.async_config_entry_first_refresh()

    register_universal_services = hass.data.get(RUNTIME_RELOAD_STATE, {}).get(
        "register_universal_services"
    )
    if callable(register_universal_services):
        register_universal_services()

    _update_rate_limit_notification(hass, entry.entry_id, coordinator)
    _update_repairs(hass, entry.entry_id, coordinator)

    def _handle_coordinator_update() -> None:
        _update_rate_limit_notification(hass, entry.entry_id, coordinator)
        _update_repairs(hass, entry.entry_id, coordinator)
        sync_services = hass.data.get(RUNTIME_RELOAD_STATE, {}).get(
            "sync_capability_services"
        )
        if callable(sync_services):
            sync_services()

    unsub = coordinator.async_add_listener(_handle_coordinator_update)

    hass.data[DOMAIN][entry.entry_id] = {
        "entry": entry,
        "coordinator": coordinator,
        "client": client,
        "rate_limit_unsub": unsub,
    }
    sync_services = hass.data.get(RUNTIME_RELOAD_STATE, {}).get(
        "sync_capability_services"
    )
    if callable(sync_services):
        sync_services()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    entry_data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if entry_data:
        unsub = entry_data.get("rate_limit_unsub")
        if unsub:
            unsub()

    persistent_notification.async_dismiss(hass, _rate_limit_notification_id(entry.entry_id))
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
    if not hass.data.get(DOMAIN):
        for service_name in [
            SERVICE_MANUAL_REFRESH,
            SERVICE_FETCH_DEVICE_HISTORY,
            SERVICE_START_LIVE_VIEW,
            SERVICE_STOP_LIVE_VIEW,
            SERVICE_QUERY_REQUEST_RESULT,
            SERVICE_QUERY_MASTER_CONTROL_DEVICE,
            *CONTROL_SERVICE_DEFINITIONS.keys(),
        ]:
            if hass.services.has_service(DOMAIN, service_name):
                hass.services.async_remove(DOMAIN, service_name)

    return True
