"""DataUpdateCoordinator for SolaX Developer API."""

from __future__ import annotations

import ast
import asyncio
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import json
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    SolaxApiError,
    SolaxDeveloperApiClient,
    normalize_sn_list,
    serialize_api_error,
)
from .i18n import translate
from .features.alarms import AlarmManager
from .features.history import HistoryManager
from .features.live_view import LiveViewManager
from .const import (
    API_RATE_LIMIT_PER_MINUTE,
    BUSINESS_TYPES,
    COMMAND_STATUS_MAP,
    CONF_ALARM_SCAN_INTERVAL,
    CONF_EV_CHARGER_CONTROLS_ENABLED,
    CONF_MANUAL_EMS_SYSTEMS,
    CONF_MANUAL_METER_SERIALS,
    CONF_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
    CONF_LIVE_VIEW_DEFAULT_DURATION,
    CONF_LIVE_VIEW_INTERVAL,
    CONF_NIGHT_END_HOUR,
    CONF_NIGHT_SCAN_INTERVAL,
    CONF_NIGHT_START_HOUR,
    DEFAULT_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
    DEFAULT_ALARM_SCAN_INTERVAL,
    DEFAULT_LIVE_VIEW_DEFAULT_DURATION,
    DEFAULT_LIVE_VIEW_INTERVAL,
    DEFAULT_NIGHT_END_HOUR,
    DEFAULT_NIGHT_SCAN_INTERVAL,
    DEFAULT_NIGHT_START_HOUR,
    DEVICE_TYPES,
    DEVICE_MODEL_MAP,
    DEVICE_MODEL_MAP_BY_CONTEXT,
    DEVICE_TYPE_NAMES,
    DOMAIN,
    EMS_DEVICE_TYPE,
    CONTROL_SERVICE_CAPABILITIES,
    EV_CHARGER_ACCEPTED_COMMAND_STATUSES,
    EV_CHARGER_CONTROL_SERVICES,
    EV_CHARGER_DEVICE_ACKNOWLEDGED_STATUSES,
    EV_CHARGER_FAILED_COMMAND_STATUSES,
    ERROR_QUOTA_CODES,
    ERROR_RATE_LIMIT_CODES,
    MAX_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
    MAX_ALARM_SCAN_INTERVAL,
    MAX_LIVE_VIEW_DURATION,
    MAX_LIVE_VIEW_INTERVAL,
    MAX_NIGHT_SCAN_INTERVAL,
    MIN_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
    MIN_ALARM_SCAN_INTERVAL,
    MIN_LIVE_VIEW_DURATION,
    MIN_LIVE_VIEW_INTERVAL,
    MIN_NIGHT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    MAX_SN_PER_REQUEST,
)

INVENTORY_REFRESH_EVERY_POLLS = 10
EV_CHARGER_CONFIRMATION_POLL_SECONDS = 2
EV_CHARGER_CONFIRMATION_TIMEOUT_SECONDS = 10
CAPABILITY_STORE_VERSION = 1
CAPABILITY_STORE_SAVE_DELAY_SECONDS = 30
RAW_ENDPOINT_PAGE_PLANT_INFO = "page_plant_info"
RAW_ENDPOINT_PAGE_DEVICE_INFO = "page_device_info"
RAW_ENDPOINT_PLANT_REALTIME_DATA = "plant_realtime_data"
RAW_ENDPOINT_ALARM_PAGE_ALARM_INFO = "alarm_page_alarm_info"
RAW_ENDPOINT_PLANT_STAT_DATA = "plant_stat_data"
RAW_ENDPOINT_DEVICE_REALTIME_DATA = "device_realtime_data"
RAW_ENDPOINT_MASTER_CONTROL_DEVICE = "master_control_device"
RAW_ENDPOINT_EMS_ATTRIBUTE_INFO = "ems_attribute_info"
RAW_ENDPOINT_EMS_SUMMARY_DATA = "ems_summary_data"
TEMPORARY_FAILURE_CLASSIFICATIONS = {
    "timeout",
    "http",
    "json",
    "api_error",
    "busy",
    "operation_error",
    "rate_limit",
    "quota",
    "exception",
}
MAX_REFRESH_FAILURE_BACKOFF_SECONDS = 1800

_LOGGER = logging.getLogger(__name__)

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


class SolaxDeveloperCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that fetches inventory + telemetry + diagnostics."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        client: SolaxDeveloperApiClient,
        config_entry: ConfigEntry[Any] | None = None,
        entry_id: str,
        scan_interval: int,
        options: dict[str, Any] | None = None,
    ) -> None:
        base_scan_interval = max(int(scan_interval), MIN_SCAN_INTERVAL)
        if config_entry is None:
            super().__init__(
                hass,
                logger=_LOGGER,
                name="Solax Developer API",
                update_interval=timedelta(seconds=base_scan_interval),
            )
        else:
            super().__init__(
                hass,
                logger=_LOGGER,
                name="Solax Developer API",
                update_interval=timedelta(seconds=base_scan_interval),
                config_entry=config_entry,
            )
        self.config_entry = config_entry
        options = options or {}

        self.client = client
        self._base_scan_interval = base_scan_interval
        self._effective_scan_interval = base_scan_interval
        self._live_view_default_duration = self._clamp_int(
            options.get(CONF_LIVE_VIEW_DEFAULT_DURATION),
            default=DEFAULT_LIVE_VIEW_DEFAULT_DURATION,
            min_value=MIN_LIVE_VIEW_DURATION,
            max_value=MAX_LIVE_VIEW_DURATION,
        )
        self._live_view_requested_interval = self._clamp_int(
            options.get(CONF_LIVE_VIEW_INTERVAL),
            default=DEFAULT_LIVE_VIEW_INTERVAL,
            min_value=MIN_LIVE_VIEW_INTERVAL,
            max_value=MAX_LIVE_VIEW_INTERVAL,
        )
        self._live_view_call_budget_per_minute = self._clamp_int(
            options.get(CONF_LIVE_VIEW_CALL_BUDGET_PER_MINUTE),
            default=DEFAULT_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
            min_value=MIN_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
            max_value=min(MAX_LIVE_VIEW_CALL_BUDGET_PER_MINUTE, API_RATE_LIMIT_PER_MINUTE),
        )
        self._night_scan_interval = self._clamp_int(
            options.get(CONF_NIGHT_SCAN_INTERVAL),
            default=DEFAULT_NIGHT_SCAN_INTERVAL,
            min_value=MIN_NIGHT_SCAN_INTERVAL,
            max_value=MAX_NIGHT_SCAN_INTERVAL,
        )
        self._night_start_hour = self._clamp_int(
            options.get(CONF_NIGHT_START_HOUR),
            default=DEFAULT_NIGHT_START_HOUR,
            min_value=0,
            max_value=23,
        )
        self._night_end_hour = self._clamp_int(
            options.get(CONF_NIGHT_END_HOUR),
            default=DEFAULT_NIGHT_END_HOUR,
            min_value=0,
            max_value=23,
        )
        self._ev_charger_controls_enabled = bool(
            options.get(CONF_EV_CHARGER_CONTROLS_ENABLED, False)
        )
        self._alarm_scan_interval = self._clamp_int(
            options.get(CONF_ALARM_SCAN_INTERVAL),
            default=DEFAULT_ALARM_SCAN_INTERVAL,
            min_value=MIN_ALARM_SCAN_INTERVAL,
            max_value=MAX_ALARM_SCAN_INTERVAL,
        )
        self._live_view_until: datetime | None = None
        self.last_update_attempt: datetime | None = None
        self.last_successful_update: datetime | None = None
        self.last_rate_limit_at: datetime | None = None
        self.rate_limited = False
        self.rate_limited_context: list[str] = []
        self._poll_profile = "standard"
        self._estimated_live_calls_per_cycle = 0
        self._alarm_reserved_calls_per_minute = 0.0
        self._live_view_budget_adjusted = False
        self._refresh_failure_streak = 0
        self._refresh_backoff_seconds = 0
        self._last_refresh_failure_classification: str | None = None
        self._last_refresh_failure_context: str | None = None
        self._last_refresh_failure_at: datetime | None = None

        self._poll_count = 0
        self._history_cache: dict[str, dict[str, Any]] = {}
        self._active_fetch_request_ids: set[str] = set()
        self._cancelled_fetch_request_ids: set[str] = set()
        self._request_result_cache: dict[str, dict[str, Any]] = {}
        self._master_control_cache: dict[str, dict[str, Any]] = {}
        self._control_dry_runs: list[dict[str, Any]] = []
        self._ev_charger_control_commands: list[dict[str, Any]] = []
        self._ev_charger_gui_state: dict[str, dict[str, Any]] = {}
        self._manual_meter_entries = self._normalize_manual_meter_entries(
            options.get(CONF_MANUAL_METER_SERIALS)
        )
        self._manual_ems_entries = self._normalize_manual_ems_entries(
            options.get(CONF_MANUAL_EMS_SYSTEMS)
        )
        self._entry_id = entry_id
        self._device_capabilities: dict[str, dict[str, Any]] = {}
        self._raw_api_responses: dict[str, list[dict[str, Any]]] = (
            self._new_raw_api_response_snapshot()
        )
        self._capability_store: Store[dict[str, Any]] = Store(
            hass,
            CAPABILITY_STORE_VERSION,
            f"{DOMAIN}_device_capabilities_{entry_id}",
        )

        self.data = self._empty_state()
        self._state_merge_lock = asyncio.Lock()
        self._alarm_manager: AlarmManager | None = None
        self._alarm_manager_unsub: Callable[[], None] | None = None
        self._alarm_merge_task: asyncio.Task[None] | None = None
        self._alarm_last_merge_at: datetime | None = None
        self._history_manager = HistoryManager(self)
        self._live_view_manager = LiveViewManager(self)

    @staticmethod
    def _normalize_fetch_request_id(request_id: str | None) -> str | None:
        """Return a normalized frontend fetch request id."""
        normalized = str(request_id or "").strip()
        return normalized or None

    def _begin_fetch_request(self, request_id: str | None) -> str | None:
        """Track a frontend fetch request while it is running."""
        normalized = self._normalize_fetch_request_id(request_id)
        if normalized is not None:
            self._active_fetch_request_ids.add(normalized)
        return normalized

    def _finish_fetch_request(self, request_id: str | None) -> None:
        """Forget a completed frontend fetch request."""
        normalized = self._normalize_fetch_request_id(request_id)
        if normalized is not None:
            self._active_fetch_request_ids.discard(normalized)
            self._cancelled_fetch_request_ids.discard(normalized)

    def _is_fetch_cancelled(self, request_id: str | None) -> bool:
        """Return whether a frontend fetch request was cancelled."""
        normalized = self._normalize_fetch_request_id(request_id)
        return normalized is not None and normalized in self._cancelled_fetch_request_ids

    def cancel_fetch(self, request_id: str) -> dict[str, Any]:
        """Mark a frontend fetch request as cancelled."""
        normalized = self._normalize_fetch_request_id(request_id)
        if normalized is None:
            return {"ok": False, "cancelled": False, "request_id": ""}
        was_active = normalized in self._active_fetch_request_ids
        self._cancelled_fetch_request_ids.add(normalized)
        return {
            "ok": True,
            "cancelled": True,
            "request_id": normalized,
            "was_active": was_active,
        }

    def _get_history_manager(self) -> HistoryManager:
        """Return the on-demand history feature, including test-safe lazy setup."""
        manager = getattr(self, "_history_manager", None)
        if manager is None:
            manager = HistoryManager(self)
            self._history_manager = manager
        return manager

    def _get_live_view_manager(self) -> LiveViewManager:
        """Return the Live View policy component."""
        manager = getattr(self, "_live_view_manager", None)
        if manager is None:
            manager = LiveViewManager(self)
            self._live_view_manager = manager
        return manager

    def _get_alarm_manager(self) -> AlarmManager:
        """Return the independent alarm coordinator."""
        manager = getattr(self, "_alarm_manager", None)
        if manager is None:
            manager = AlarmManager(
                self,
                scan_interval=int(
                    getattr(
                        self,
                        "_alarm_scan_interval",
                        DEFAULT_ALARM_SCAN_INTERVAL,
                    )
                ),
            )
            self._alarm_manager = manager
        return manager

    def _get_state_merge_lock(self) -> asyncio.Lock:
        """Return the shared state lock, restoring reconstructed state safely."""
        lock: object = getattr(self, "_state_merge_lock", None)
        if not isinstance(lock, asyncio.Lock):
            lock = asyncio.Lock()
            self._state_merge_lock = lock
        return lock

    def _schedule_alarm_manager_merge(self) -> None:
        """Schedule one serialized merge of alarm coordinator state."""
        existing = getattr(self, "_alarm_merge_task", None)
        if existing is not None and not existing.done():
            return
        self._alarm_merge_task = self.hass.async_create_task(
            self._async_merge_alarm_manager_state(),
            f"{DOMAIN} merge alarm state",
        )

    async def _async_merge_alarm_manager_state(self) -> None:
        """Merge only alarm-owned state into the public coordinator facade."""
        manager = self._get_alarm_manager()
        async with self._get_state_merge_lock():
            state = dict(self.data or self._empty_state())
            if manager.last_update_success:
                current_plants = set((state.get("plants") or {}).keys())
                state["alarms"] = {
                    plant_id: deepcopy(payload)
                    for plant_id, payload in dict(manager.data or {}).items()
                    if plant_id in current_plants
                }

            if manager.raw_cycle:
                self._merge_raw_api_cycle(manager.raw_cycle)
            errors = [
                dict(item)
                for item in list(state.get("last_errors") or [])
                if str(item.get("context") or "") != "alarms"
                and not str(item.get("context") or "").startswith("alarms:")
            ]
            errors.extend(deepcopy(manager.last_errors))
            state["last_errors"] = errors

            for item in manager.last_errors:
                if item.get("code") in ERROR_RATE_LIMIT_CODES | ERROR_QUOTA_CODES:
                    self._mark_rate_limit(str(item.get("context") or "alarms"))

            self._alarm_last_merge_at = dt_util.utcnow()
            meta = dict(state.get("meta") or {})
            meta.update(
                {
                    "alarm_scan_interval": manager.scan_interval,
                    "alarm_last_merge_at": self._alarm_last_merge_at,
                    "alarm_last_update_attempt": manager.last_update_attempt,
                    "alarm_last_successful_update": manager.last_successful_update,
                    "alarm_last_update_success": manager.last_update_success,
                    "alarm_last_error": manager.last_error,
                    "alarm_last_errors": deepcopy(manager.last_errors),
                    "alarm_last_api_calls": manager.last_api_calls,
                    "alarm_reserved_calls_per_minute": (
                        manager.estimated_calls_per_minute
                    ),
                }
            )
            state["meta"] = meta
            state["raw_api_responses"] = self.raw_api_responses
            # AlarmManager has its own refresh schedule. Publishing its partial
            # state through async_set_updated_data() would cancel and restart the
            # facade coordinator's realtime timer on every alarm poll.
            self.data = state
            self.async_update_listeners()

    async def async_start_alarm_polling(self) -> None:
        """Start independent alarm polling after inventory is available."""
        manager = self._get_alarm_manager()
        plants = dict((self.data or {}).get("plants") or {})
        alarms = dict((self.data or {}).get("alarms") or {})
        has_initial_alarm_state = bool(plants) and all(
            plant_id in alarms for plant_id in plants
        )
        if has_initial_alarm_state:
            manager.data = deepcopy(alarms)
            manager.last_update_attempt = self.last_update_attempt
            manager.last_successful_update = self.last_successful_update
            manager.last_update_success = True
        if getattr(self, "_alarm_manager_unsub", None) is None:
            self._alarm_manager_unsub = manager.async_add_listener(
                self._schedule_alarm_manager_merge
            )
        if not has_initial_alarm_state:
            await manager.async_refresh()
        merge_task = getattr(self, "_alarm_merge_task", None)
        if merge_task is not None:
            await merge_task
        else:
            await self._async_merge_alarm_manager_state()

    async def async_stop_alarm_polling(self) -> None:
        """Stop alarm scheduling and finish any pending state merge."""
        if unsub := getattr(self, "_alarm_manager_unsub", None):
            unsub()
            self._alarm_manager_unsub = None
        merge_task = getattr(self, "_alarm_merge_task", None)
        if merge_task is not None and not merge_task.done():
            await merge_task

    async def async_refresh_alarms_once(self) -> None:
        """Run one alarm refresh without enabling periodic scheduling."""
        manager = self._get_alarm_manager()
        await manager.async_refresh()
        await self._async_merge_alarm_manager_state()

    async def async_load_capability_cache(self) -> None:
        """Load cached observed realtime fields by device serial."""
        stored = await self._capability_store.async_load()
        if not isinstance(stored, dict):
            return

        devices_payload = stored.get("devices")
        if not isinstance(devices_payload, dict):
            return

        restored: dict[str, dict[str, Any]] = {}
        for serial_key, item in devices_payload.items():
            if not isinstance(item, dict):
                continue
            raw_serial = str(item.get("serial") or "").strip()
            normalized_key = str(serial_key).strip().casefold()
            if not normalized_key:
                normalized_key = raw_serial.casefold()
            if not normalized_key:
                continue
            raw_fields = item.get("fields") or []
            if not isinstance(raw_fields, list):
                raw_fields = []
            fields = sorted(
                {
                    str(field).strip()
                    for field in raw_fields
                    if str(field).strip()
                },
                key=str.casefold,
            )
            if not fields:
                continue
            restored[normalized_key] = {
                "serial": raw_serial or str(item.get("serial_key") or normalized_key),
                "fields": fields,
                "device_type": item.get("device_type"),
                "business_type": item.get("business_type"),
                "updated_at": item.get("updated_at"),
                "last_seen_online": item.get("last_seen_online"),
            }

        self._device_capabilities = restored

    def _serialize_capability_cache(self) -> dict[str, Any]:
        devices_payload: dict[str, dict[str, Any]] = {}
        for serial_key, raw_item in self._device_capabilities.items():
            item: object = raw_item
            if not isinstance(item, Mapping):
                continue
            fields = item.get("fields") or []
            if not isinstance(fields, list) or not fields:
                continue
            normalized_fields = sorted(
                {
                    str(field).strip()
                    for field in fields
                    if str(field).strip()
                },
                key=str.casefold,
            )
            if not normalized_fields:
                continue
            devices_payload[str(serial_key)] = {
                "serial": str(item.get("serial") or "").strip(),
                "fields": normalized_fields,
                "device_type": item.get("device_type"),
                "business_type": item.get("business_type"),
                "updated_at": item.get("updated_at"),
                "last_seen_online": item.get("last_seen_online"),
            }
        return {"devices": devices_payload}

    def _schedule_capability_cache_save(self) -> None:
        self._capability_store.async_delay_save(
            self._serialize_capability_cache,
            CAPABILITY_STORE_SAVE_DELAY_SECONDS,
        )

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _device_online_status(
        self,
        *,
        realtime_payload: dict[str, Any] | None,
        inventory_payload: dict[str, Any] | None,
    ) -> int | None:
        realtime_payload = realtime_payload or {}
        inventory_payload = inventory_payload or {}
        return self._coerce_int(
            realtime_payload.get("onlineStatus")
            if realtime_payload.get("onlineStatus") is not None
            else inventory_payload.get("onlineStatus")
        )

    def _update_device_capabilities(
        self,
        devices: dict[str, dict[str, Any]],
        device_realtime: dict[str, dict[str, Any]],
    ) -> None:
        """Persist observed non-null realtime fields by serial."""
        merged_serials = {
            str(serial).strip()
            for serial in list(devices.keys()) + list(device_realtime.keys())
            if str(serial).strip()
        }
        if not merged_serials:
            return

        changed = False
        now_iso = dt_util.utcnow().isoformat()
        for serial in merged_serials:
            serial_key = serial.casefold()
            realtime_payload = device_realtime.get(serial)
            inventory_payload = devices.get(serial)

            if realtime_payload is None:
                realtime_key = self._find_existing_serial_key(serial, device_realtime)
                if realtime_key is not None:
                    realtime_payload = device_realtime.get(realtime_key)
            if inventory_payload is None:
                inventory_key = self._find_existing_serial_key(serial, devices)
                if inventory_key is not None:
                    inventory_payload = devices.get(inventory_key)

            if not isinstance(realtime_payload, dict):
                realtime_payload = {}
            if not isinstance(inventory_payload, dict):
                inventory_payload = {}

            online_status = self._device_online_status(
                realtime_payload=realtime_payload,
                inventory_payload=inventory_payload,
            )

            # Only promote observed fields when the device reports online.
            is_online = online_status == 1 if online_status is not None else True
            if is_online:
                flat_realtime = _flatten_dict(realtime_payload)
                observed_fields = sorted(
                    {
                        str(field).strip()
                        for field, value in flat_realtime.items()
                        if value is not None and str(field).strip()
                    },
                    key=str.casefold,
                )
            else:
                observed_fields = []

            existing = dict(self._device_capabilities.get(serial_key) or {})
            existing_fields = {
                str(field).strip()
                for field in (existing.get("fields") or [])
                if str(field).strip()
            }
            merged_fields = sorted(existing_fields.union(observed_fields), key=str.casefold)
            if not merged_fields:
                continue
            existing_fields_sorted = sorted(existing_fields, key=str.casefold)

            device_type = self._coerce_int(
                realtime_payload.get("deviceType")
                if realtime_payload.get("deviceType") is not None
                else inventory_payload.get("deviceType")
            )
            business_type = self._coerce_int(
                realtime_payload.get("businessType")
                if realtime_payload.get("businessType") is not None
                else inventory_payload.get("businessType")
            )
            serial_value = str(
                realtime_payload.get("deviceSn")
                or inventory_payload.get("deviceSn")
                or existing.get("serial")
                or serial
            ).strip()
            last_seen_online = existing.get("last_seen_online")
            if is_online and (not last_seen_online or merged_fields != existing_fields_sorted):
                last_seen_online = now_iso
            has_meaningful_change = (
                merged_fields != existing_fields_sorted
                or serial_value != str(existing.get("serial") or "").strip()
                or device_type != self._coerce_int(existing.get("device_type"))
                or business_type != self._coerce_int(existing.get("business_type"))
                or last_seen_online != existing.get("last_seen_online")
            )
            if not has_meaningful_change:
                continue

            updated_entry = {
                "serial": serial_value,
                "fields": merged_fields,
                "device_type": device_type,
                "business_type": business_type,
                "updated_at": now_iso,
                "last_seen_online": last_seen_online,
            }
            self._device_capabilities[serial_key] = updated_entry
            changed = True

        if changed:
            self._schedule_capability_cache_save()

    @property
    def device_capability_fields(self) -> dict[str, set[str]]:
        return {
            serial_key: {
                str(field).strip()
                for field in (entry.get("fields") or [])
                if str(field).strip()
            }
            for serial_key, entry in self._device_capabilities.items()
            if isinstance(entry, dict)
        }

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "plants": {},
            "devices": {},
            "inventory_by_type": {},
            "plant_realtime": {},
            "plant_stats": {},
            "alarms": {},
            "device_realtime": {},
            "last_errors": [],
            "manual_meter_entries": [],
            "manual_ems_entries": [],
            "raw_api_responses": {},
            "meta": {},
        }

    @staticmethod
    def _new_raw_api_response_snapshot() -> dict[str, list[dict[str, Any]]]:
        return {
            RAW_ENDPOINT_PAGE_PLANT_INFO: [],
            RAW_ENDPOINT_PAGE_DEVICE_INFO: [],
            RAW_ENDPOINT_PLANT_REALTIME_DATA: [],
            RAW_ENDPOINT_ALARM_PAGE_ALARM_INFO: [],
            RAW_ENDPOINT_PLANT_STAT_DATA: [],
            RAW_ENDPOINT_DEVICE_REALTIME_DATA: [],
            RAW_ENDPOINT_MASTER_CONTROL_DEVICE: [],
            RAW_ENDPOINT_EMS_ATTRIBUTE_INFO: [],
            RAW_ENDPOINT_EMS_SUMMARY_DATA: [],
        }

    def _append_raw_snapshot(
        self,
        raw_cycle: dict[str, list[dict[str, Any]]] | None,
        *,
        endpoint: str,
        request: dict[str, Any],
        response: dict[str, Any] | None = None,
        error: Exception | None = None,
        optional_absence: bool = False,
    ) -> None:
        if raw_cycle is None:
            return
        payload: dict[str, Any] = {
            "request": dict(request),
        }
        if response is not None:
            payload["response"] = response
        if error is not None:
            payload["error"] = serialize_api_error(error)
        if optional_absence:
            payload["optional_absence"] = True
        raw_cycle.setdefault(endpoint, []).append(payload)

    def _merge_raw_api_cycle(self, raw_cycle: dict[str, list[dict[str, Any]]]) -> None:
        for endpoint in self._raw_api_responses:
            updates = raw_cycle.get(endpoint) or []
            if updates:
                self._raw_api_responses[endpoint] = updates

    @property
    def raw_api_responses(self) -> dict[str, list[dict[str, Any]]]:
        return deepcopy(self._raw_api_responses)

    @staticmethod
    def _clamp_int(
        raw_value: Any,
        *,
        default: int,
        min_value: int,
        max_value: int,
    ) -> int:
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            parsed = default
        return max(min_value, min(parsed, max_value))

    @staticmethod
    def _count_raw_cycle_responses(raw_cycle: dict[str, list[dict[str, Any]]]) -> int:
        count = 0
        for payloads in raw_cycle.values():
            for payload in payloads:
                if isinstance(payload, Mapping) and payload.get("response") is not None:
                    count += 1
        return count

    @staticmethod
    def _raw_cycle_error_items(
        raw_cycle: Mapping[str, Sequence[Any]],
    ) -> list[tuple[str, dict[str, Any]]]:
        items: list[tuple[str, dict[str, Any]]] = []
        for endpoint, payloads in raw_cycle.items():
            for payload in payloads:
                if not isinstance(payload, Mapping):
                    continue
                error_payload = payload.get("error")
                if not isinstance(error_payload, Mapping):
                    continue
                if bool(payload.get("optional_absence")):
                    continue
                items.append((endpoint, dict(error_payload)))
        return items

    @staticmethod
    def _is_temporary_failure_classification(classification: str | None) -> bool:
        return str(classification or "").strip().casefold() in TEMPORARY_FAILURE_CLASSIFICATIONS

    def _compute_refresh_backoff_seconds(self, streak: int) -> int:
        if streak <= 0:
            return 0
        base_interval = max(self._base_scan_interval, MIN_SCAN_INTERVAL)
        candidate = int(base_interval * (2 ** (streak - 1)))
        return min(candidate, MAX_REFRESH_FAILURE_BACKOFF_SECONDS)

    def _select_refresh_failure_signal(
        self,
        errors: list[dict[str, Any]],
        raw_cycle: dict[str, list[dict[str, Any]]],
    ) -> tuple[str | None, str, str]:
        if errors:
            latest = errors[-1]
            classification = str(latest.get("classification") or "").strip() or None
            context = str(latest.get("context") or "refresh").strip() or "refresh"
            message = str(latest.get("message") or "refresh failed").strip() or "refresh failed"
            return classification, context, message

        raw_errors = self._raw_cycle_error_items(raw_cycle)
        if raw_errors:
            endpoint, latest = raw_errors[-1]
            classification = str(latest.get("classification") or "").strip() or None
            context = str(endpoint).strip() or "refresh"
            message = str(latest.get("message") or "refresh failed").strip() or "refresh failed"
            return classification, context, message

        return None, "refresh", "No endpoint response was received"

    def _register_refresh_success(self) -> None:
        self._refresh_failure_streak = 0
        self._refresh_backoff_seconds = 0
        self._last_refresh_failure_classification = None
        self._last_refresh_failure_context = None
        self._last_refresh_failure_at = None

    def _register_refresh_failure(self, classification: str | None, context: str) -> None:
        self._last_refresh_failure_classification = classification
        self._last_refresh_failure_context = context
        self._last_refresh_failure_at = dt_util.utcnow()
        if self._is_temporary_failure_classification(classification):
            self._refresh_failure_streak += 1
            self._refresh_backoff_seconds = self._compute_refresh_backoff_seconds(
                self._refresh_failure_streak
            )
            return
        self._refresh_failure_streak = 0
        self._refresh_backoff_seconds = 0

    def _apply_refresh_backoff_to_interval(self) -> None:
        if self._refresh_backoff_seconds <= 0:
            return
        self._effective_scan_interval = max(self._effective_scan_interval, self._refresh_backoff_seconds)
        self.update_interval = timedelta(seconds=self._effective_scan_interval)

    def _merge_raw_errors_into_errors(
        self,
        errors: list[dict[str, Any]],
        raw_cycle: dict[str, list[dict[str, Any]]],
    ) -> None:
        known = {
            (
                str(item.get("context") or ""),
                str(item.get("classification") or ""),
                str(item.get("code") or ""),
                str(item.get("message") or ""),
            )
            for item in errors
            if isinstance(item, Mapping)
        }
        for endpoint, error_payload in self._raw_cycle_error_items(raw_cycle):
            merged = dict(error_payload)
            merged["context"] = endpoint
            key = (
                str(merged.get("context") or ""),
                str(merged.get("classification") or ""),
                str(merged.get("code") or ""),
                str(merged.get("message") or ""),
            )
            if key in known:
                continue
            known.add(key)
            errors.append(merged)
            code = merged.get("code")
            if code in ERROR_RATE_LIMIT_CODES or code in ERROR_QUOTA_CODES:
                self._mark_rate_limit(endpoint)

    @staticmethod
    def _normalize_manual_meter_entries(raw_entries: Any) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()

        if isinstance(raw_entries, str):
            text = raw_entries.strip()
            if not text:
                return entries

            decoded: Any = None
            try:
                decoded = json.loads(text)
            except Exception:
                decoded = None
            if decoded is None:
                try:
                    decoded = ast.literal_eval(text)
                except Exception:
                    decoded = None

            if isinstance(decoded, (list, tuple)):
                raw_entries = list(decoded)
            elif isinstance(decoded, Mapping):
                raw_entries = [decoded]
            else:
                parsed: list[dict[str, Any]] = []
                for raw_line in text.replace(",", "\n").splitlines():
                    line = str(raw_line).strip()
                    if not line:
                        continue
                    serial = line
                    business_type = 1
                    if "|" in line:
                        serial_part, business_part = line.split("|", 1)
                        serial = serial_part.strip()
                        try:
                            business_type = int(business_part.strip())
                        except (TypeError, ValueError):
                            continue
                    if not serial:
                        continue
                    parsed.append(
                        {
                            "serial": serial,
                            "business_type": business_type,
                            "source": "manual",
                        }
                    )
                raw_entries = parsed

        if isinstance(raw_entries, tuple):
            raw_entries = list(raw_entries)
        if isinstance(raw_entries, Mapping):
            raw_entries = [raw_entries]
        if not isinstance(raw_entries, list):
            return entries

        for item in raw_entries:
            realtime_fields: list[str] = []
            if isinstance(item, Mapping):
                serial = str(
                    item.get("serial")
                    or item.get("device_sn")
                    or item.get("deviceSn")
                    or ""
                ).strip()
                try:
                    business_type = int(
                        item.get("business_type") or item.get("businessType") or 1
                    )
                except (TypeError, ValueError):
                    business_type = 1
                raw_realtime_fields = (
                    item.get("realtime_fields")
                    or item.get("realtimeFields")
                    or []
                )
                if isinstance(raw_realtime_fields, (list, tuple)):
                    realtime_fields = sorted(
                        {
                            str(field).strip()
                            for field in raw_realtime_fields
                            if str(field).strip()
                        },
                        key=str.casefold,
                    )
            else:
                serial = str(item).strip()
                business_type = 1

            if not serial:
                continue
            if business_type not in BUSINESS_TYPES:
                business_type = 1
            serial_key = serial.casefold()
            if serial_key in seen:
                continue
            seen.add(serial_key)
            normalized_entry: dict[str, Any] = {
                "serial": serial,
                "business_type": business_type,
                "source": "manual",
            }
            if realtime_fields:
                normalized_entry["realtime_fields"] = realtime_fields
            entries.append(normalized_entry)

        return entries

    @staticmethod
    def _normalize_manual_ems_entries(raw_entries: Any) -> list[dict[str, Any]]:
        if isinstance(raw_entries, str):
            text = raw_entries.strip()
            if not text:
                return []
            try:
                decoded = json.loads(text)
            except Exception:
                decoded = None
            if decoded is None:
                try:
                    decoded = ast.literal_eval(text)
                except Exception:
                    decoded = None
            if isinstance(decoded, Mapping):
                raw_entries = [decoded]
            elif isinstance(decoded, (list, tuple)):
                raw_entries = list(decoded)
            else:
                parsed: list[dict[str, Any]] = []
                for raw_line in text.replace(",", "\n").splitlines():
                    line = str(raw_line).strip()
                    if not line or "|" not in line:
                        continue
                    serial, plant_id = (part.strip() for part in line.split("|", 1))
                    if serial and plant_id:
                        parsed.append({"serial": serial, "plant_id": plant_id})
                raw_entries = parsed
        if isinstance(raw_entries, Mapping):
            raw_entries = [raw_entries]
        if isinstance(raw_entries, tuple):
            raw_entries = list(raw_entries)
        if not isinstance(raw_entries, list):
            return []

        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_entries:
            if not isinstance(item, Mapping):
                continue
            serial = str(
                item.get("serial")
                or item.get("register_no")
                or item.get("registerNo")
                or ""
            ).strip()
            plant_id = str(
                item.get("plant_id")
                or item.get("plantId")
                or item.get("stationId")
                or ""
            ).strip()
            if not serial or not plant_id or serial.casefold() in seen:
                continue
            seen.add(serial.casefold())
            entries.append(
                {
                    "serial": serial,
                    "plant_id": plant_id,
                    "business_type": 4,
                    "source": "manual",
                }
            )
        return entries

    @staticmethod
    def _find_existing_serial_key(serial: str, values: dict[str, Any]) -> str | None:
        target = str(serial).strip().casefold()
        if not target:
            return None
        for key in values:
            if str(key).strip().casefold() == target:
                return key
        return None

    @property
    def manual_meter_entries(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._manual_meter_entries]

    @property
    def manual_ems_entries(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._manual_ems_entries]

    def set_manual_meter_entries(self, entries: list[dict[str, Any]] | list[str]) -> None:
        self._manual_meter_entries = self._normalize_manual_meter_entries(entries)
        self.data.setdefault("meta", {})["manual_meter_serial_count"] = len(self._manual_meter_entries)
        self.data["meta"]["manual_meter_serials"] = [
            dict(item) for item in self._manual_meter_entries
        ]

    def set_manual_ems_entries(self, entries: list[dict[str, Any]]) -> None:
        self._manual_ems_entries = self._normalize_manual_ems_entries(entries)
        self.data.setdefault("meta", {})["manual_ems_system_count"] = len(
            self._manual_ems_entries
        )
        self.data["meta"]["manual_ems_systems"] = [
            dict(item) for item in self._manual_ems_entries
        ]

    def get_known_meter_serial(self, serial: str) -> dict[str, Any] | None:
        normalized = str(serial).strip().casefold()
        if not normalized:
            return None

        for sn, device in (self.data.get("devices") or {}).items():
            if str(sn).strip().casefold() != normalized:
                continue
            try:
                device_type = int((device or {}).get("deviceType") or 0)
            except (TypeError, ValueError):
                device_type = 0
            if device_type != 3:
                continue
            return {
                "serial": str(sn),
                "source": "inventory" if not bool((device or {}).get("manualSerial")) else "manual",
                "business_type": int((device or {}).get("businessType") or 1),
                "device": dict(device or {}),
            }

        for entry in self._manual_meter_entries:
            if str(entry.get("serial", "")).strip().casefold() != normalized:
                continue
            result = {
                "serial": str(entry.get("serial") or ""),
                "source": "manual",
                "business_type": int(entry.get("business_type") or 1),
                "device": None,
            }
            raw_realtime_fields = entry.get("realtime_fields") or []
            if isinstance(raw_realtime_fields, list):
                result["realtime_fields"] = list(raw_realtime_fields)
            return result
        return None

    def get_known_ev_charger_serial(self, serial: str) -> dict[str, Any] | None:
        """Return a discovered EV charger device by serial."""
        normalized = str(serial).strip().casefold()
        if not normalized:
            return None

        for sn, device in (self.data.get("devices") or {}).items():
            if str(sn).strip().casefold() != normalized:
                continue
            if self._coerce_int((device or {}).get("deviceType")) != 4:
                continue
            return {
                "serial": str((device or {}).get("deviceSn") or sn),
                "source": (
                    "manual"
                    if bool((device or {}).get("manualSerial"))
                    else "inventory"
                ),
                "business_type": int((device or {}).get("businessType") or 1),
                "device": dict(device or {}),
            }
        return None

    def get_known_ems_serial(self, serial: str) -> dict[str, Any] | None:
        normalized = str(serial).strip().casefold()
        if not normalized:
            return None
        for sn, device in (self.data.get("devices") or {}).items():
            if str(sn).strip().casefold() != normalized:
                continue
            if self._coerce_int((device or {}).get("deviceType")) != EMS_DEVICE_TYPE:
                continue
            return {
                "serial": str(sn),
                "plant_id": str((device or {}).get("plantId") or "").strip(),
                "source": (
                    "manual"
                    if bool((device or {}).get("manualSerial"))
                    else "master_control"
                ),
                "device": dict(device or {}),
            }
        for entry in getattr(self, "_manual_ems_entries", []):
            if str(entry.get("serial") or "").strip().casefold() == normalized:
                return {
                    "serial": str(entry.get("serial") or ""),
                    "plant_id": str(entry.get("plant_id") or ""),
                    "source": "manual",
                    "device": None,
                }
        return None

    async def async_probe_manual_ems_system(
        self,
        *,
        serial: str,
        plant_id: str,
    ) -> dict[str, Any]:
        input_serial = str(serial).strip()
        input_plant_id = str(plant_id).strip()
        if not input_serial or not input_plant_id:
            return {
                "ok": False,
                "reason": "invalid_ems_identity",
                "serial_input": input_serial,
                "plant_id": input_plant_id,
            }
        try:
            payload = await self.client.ems_attribute_info(
                register_no=input_serial,
                plant_id=input_plant_id,
                business_type=4,
            )
        except SolaxApiError as err:
            return {
                "ok": False,
                "reason": "ems_attribute_query_failed",
                "serial_input": input_serial,
                "plant_id": input_plant_id,
                "error": serialize_api_error(err),
            }
        rows = payload.get("result") or []
        if isinstance(rows, Mapping):
            rows = [rows]
        if not isinstance(rows, list):
            rows = []
        matches = [
            dict(row)
            for row in rows
            if isinstance(row, Mapping)
            and str(row.get("registerNo") or input_serial).strip().casefold()
            == input_serial.casefold()
        ]
        if not matches:
            return {
                "ok": False,
                "reason": "ems_not_found",
                "serial_input": input_serial,
                "plant_id": input_plant_id,
                "code": payload.get("code"),
                "message": payload.get("message"),
            }
        row = matches[0]
        resolved_serial = str(row.get("registerNo") or input_serial).strip()
        resolved_plant_id = str(row.get("stationId") or input_plant_id).strip()
        return {
            "ok": True,
            "reason": "validated",
            "serial_input": input_serial,
            "serial_resolved": resolved_serial,
            "plant_id": resolved_plant_id,
            "business_type": 4,
            "attribute_fields": sorted(
                str(key) for key, value in row.items() if value is not None
            ),
            "sample_attribute_row": row,
        }

    @property
    def capability_families(self) -> set[str]:
        devices = self.data.get("devices") or {}
        realtime = self.data.get("device_realtime") or {}
        families: set[str] = set()
        for serial, device in devices.items():
            device_payload = device if isinstance(device, Mapping) else {}
            device_type = self._coerce_int(device_payload.get("deviceType"))
            business_type = self._coerce_int(device_payload.get("businessType"))
            if device_type == 1:
                families.add("inverter")
                if business_type == 4:
                    families.add("ci_inverter")
                if (
                    business_type == 1
                    and self._coerce_int(device_payload.get("deviceModel")) == 19
                ):
                    families.add("a1_hybrid_g2")
            elif device_type == 2:
                families.add("battery")
                families.add("battery_system")
            elif device_type == 3:
                families.add("meter")
            elif device_type == 4:
                families.add("ev_charger")
            elif device_type == EMS_DEVICE_TYPE:
                families.add("ems")

            realtime_payload = realtime.get(serial)
            if not isinstance(realtime_payload, Mapping):
                existing_key = self._find_existing_serial_key(str(serial), realtime)
                realtime_payload = (
                    realtime.get(existing_key) if existing_key is not None else {}
                )
            if isinstance(realtime_payload, Mapping):
                flattened_keys = {
                    str(key).casefold()
                    for key in _flatten_dict(dict(realtime_payload)).keys()
                }
                if any(
                    marker in key
                    for key in flattened_keys
                    for marker in (
                        "batterysoc",
                        "batterysoh",
                        "batterypower",
                        "chargedischargepower",
                    )
                ):
                    families.add("battery_system")
            cached_fields = {
                str(field).casefold()
                for field in (
                    (
                        self._device_capabilities.get(str(serial).casefold())
                        or {}
                    ).get("fields")
                    or []
                )
            }
            if any(
                marker in key
                for key in cached_fields
                for marker in (
                    "batterysoc",
                    "batterysoh",
                    "batterypower",
                    "chargedischargepower",
                )
            ):
                families.add("battery_system")
        return families

    @property
    def available_control_services(self) -> set[str]:
        families = self.capability_families
        return {
            service
            for service, requirement in CONTROL_SERVICE_CAPABILITIES.items()
            if families.intersection(requirement.get("families") or ())
        }

    @property
    def has_history_capable_devices(self) -> bool:
        return any(
            self._coerce_int((device or {}).get("deviceType")) in DEVICE_TYPES
            for device in (self.data.get("devices") or {}).values()
            if isinstance(device, Mapping)
        )

    def list_history_devices(self) -> list[dict[str, Any]]:
        """Return current devices that can be queried through device history."""
        devices: list[dict[str, Any]] = []
        for serial, payload in (self.data.get("devices") or {}).items():
            if not isinstance(payload, Mapping):
                continue

            device_type = self._coerce_int(payload.get("deviceType"))
            if device_type not in DEVICE_TYPES:
                continue

            business_type = self._coerce_int(payload.get("businessType"))
            if business_type not in BUSINESS_TYPES:
                business_type = 1

            serial_text = str(payload.get("deviceSn") or serial).strip()
            if not serial_text:
                continue

            device_type_name = translate(
                self.hass,
                f"runtime.labels.device_type.{device_type}",
                fallback=DEVICE_TYPE_NAMES.get(device_type or 0, "Device"),
            )
            source = (
                "manual"
                if bool(payload.get("manualSerial"))
                else str(payload.get("discoverySource") or "inventory")
            )
            label = f"{device_type_name} {serial_text}"

            devices.append(
                {
                    "device_sn": serial_text,
                    "device_type": device_type,
                    "device_type_name": device_type_name,
                    "business_type": business_type,
                    "source": source,
                    "label": label,
                }
            )

        return sorted(
            devices,
            key=lambda item: (
                int(item["device_type"]),
                str(item["label"]).casefold(),
                str(item["device_sn"]).casefold(),
            ),
        )

    def list_plant_statistics_targets(self) -> list[dict[str, Any]]:
        """Return current plants that can be queried through plant statistics."""
        targets: list[dict[str, Any]] = []
        for plant_id_key, payload in (self.data.get("plants") or {}).items():
            if not isinstance(payload, Mapping):
                continue

            plant_id = str(payload.get("plantId") or plant_id_key).strip()
            if not plant_id:
                continue

            business_type = self._coerce_int(payload.get("businessType"))
            if business_type not in BUSINESS_TYPES:
                business_type = 1

            plant_name = str(payload.get("plantName") or "").strip()
            label = plant_name or translate(
                self.hass,
                "runtime.entity_templates.plant_name",
                placeholders={"plant_id": plant_id},
                fallback="Plant {plant_id}",
            )

            targets.append(
                {
                    "plant_id": plant_id,
                    "plant_name": plant_name,
                    "business_type": business_type,
                    "label": label,
                }
            )

        return sorted(
            targets,
            key=lambda item: (
                str(item["label"]).casefold(),
                str(item["plant_id"]).casefold(),
            ),
        )

    def list_alarm_targets(self) -> dict[str, list[dict[str, Any]]]:
        """Return loaded plants and devices usable by the alarm endpoint."""
        plants = self.list_plant_statistics_targets()
        plant_business_types = {
            str(plant["plant_id"]): int(plant["business_type"]) for plant in plants
        }
        devices: list[dict[str, Any]] = []

        for serial, payload in (self.data.get("devices") or {}).items():
            if not isinstance(payload, Mapping):
                continue

            serial_text = str(payload.get("deviceSn") or serial).strip()
            plant_id = str(payload.get("plantId") or "").strip()
            if not serial_text or not plant_id:
                continue

            device_type = self._coerce_int(payload.get("deviceType"))
            business_type = self._coerce_int(payload.get("businessType"))
            if business_type not in BUSINESS_TYPES:
                business_type = plant_business_types.get(plant_id, 1)

            device_type_name = translate(
                self.hass,
                f"runtime.labels.device_type.{device_type}",
                fallback=DEVICE_TYPE_NAMES.get(device_type or 0, "Device"),
            )
            devices.append(
                {
                    "device_sn": serial_text,
                    "plant_id": plant_id,
                    "device_type": device_type,
                    "device_type_name": device_type_name,
                    "business_type": business_type,
                    "label": f"{device_type_name} {serial_text}",
                    "source": (
                        "manual"
                        if bool(payload.get("manualSerial"))
                        else str(payload.get("discoverySource") or "inventory")
                    ),
                }
            )

        return {
            "plants": plants,
            "devices": sorted(
                devices,
                key=lambda item: (
                    str(item["plant_id"]).casefold(),
                    int(item["device_type"] or 0),
                    str(item["label"]).casefold(),
                    str(item["device_sn"]).casefold(),
                ),
            ),
        }

    def _device_type_text(self, value: Any) -> str:
        """Return translated Developer API deviceType label."""
        try:
            device_type = int(value)
        except (TypeError, ValueError):
            return str(value)
        fallback = DEVICE_TYPE_NAMES.get(device_type, str(value))
        return translate(
            self.hass,
            f"runtime.labels.device_type.{device_type}",
            fallback=fallback,
        )

    def _device_model_text(
        self,
        value: Any,
        *,
        business_type: Any = None,
        device_type: Any = None,
    ) -> Any:
        """Return translated contextual Developer API deviceModel label."""
        try:
            model_id = int(value)
        except (TypeError, ValueError):
            return value
        try:
            context_key = (int(business_type), int(device_type), model_id)
        except (TypeError, ValueError):
            context_key = None
        contextual = (
            DEVICE_MODEL_MAP_BY_CONTEXT.get(context_key)
            if context_key is not None
            else None
        )
        fallback = str(contextual or DEVICE_MODEL_MAP.get(model_id, value))
        if contextual is not None and context_key is not None:
            return translate(
                self.hass,
                (
                    "runtime.device_model.context."
                    f"{context_key[0]}.{context_key[1]}.{model_id}"
                ),
                fallback=fallback,
            )
        return translate(
            self.hass,
            f"runtime.device_model.code.{model_id}",
            fallback=fallback,
        )

    @property
    def has_ci_devices(self) -> bool:
        return any(
            self._coerce_int((device or {}).get("businessType")) == 4
            and self._coerce_int((device or {}).get("deviceType")) in DEVICE_TYPES
            for device in (self.data.get("devices") or {}).values()
            if isinstance(device, Mapping)
        )

    async def async_probe_manual_meter_serial(self, serial: str) -> dict[str, Any]:
        """Probe meter serial against realtime/history read endpoints before persisting."""
        input_serial = str(serial).strip()
        if not input_serial:
            return {
                "ok": False,
                "reason": "invalid_serial",
                "serial_input": input_serial,
                "realtime_attempts": [],
                "history_probe": {},
                "field_summary": {},
            }

        realtime_attempts: list[dict[str, Any]] = []
        matched_rows: list[tuple[int, dict[str, Any]]] = []
        all_realtime_fields: set[str] = set()
        non_null_realtime_fields: set[str] = set()

        for business_type in BUSINESS_TYPES:
            try:
                payload = await self.client.device_realtime_data(
                    sn_list=[input_serial],
                    device_type=3,
                    business_type=business_type,
                )
                rows = payload.get("result") or []
                if not isinstance(rows, list):
                    rows = []
                matches: list[dict[str, Any]] = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    row_sn = str(row.get("deviceSn") or "").strip()
                    if row_sn and row_sn.casefold() == input_serial.casefold():
                        matches.append(row)
                if not matches and len(rows) == 1 and isinstance(rows[0], dict):
                    # Some accounts only return the matched row without strict serial normalization.
                    matches = [rows[0]]

                for row in matches:
                    for key, value in row.items():
                        all_realtime_fields.add(str(key))
                        if value is not None:
                            non_null_realtime_fields.add(str(key))
                    matched_rows.append((business_type, row))

                realtime_attempts.append(
                    {
                        "business_type": business_type,
                        "code": payload.get("code"),
                        "message": payload.get("message"),
                        "rows": len(rows),
                        "matches": len(matches),
                        "sample_device_sns": sorted(
                            {
                                str(r.get("deviceSn") or "").strip()
                                for r in rows
                                if isinstance(r, dict) and r.get("deviceSn")
                            }
                        )[:10],
                    }
                )
            except SolaxApiError as err:
                realtime_attempts.append(
                    {
                        "business_type": business_type,
                        "code": err.code,
                        "message": err.message,
                        "classification": err.classification,
                        "rows": 0,
                        "matches": 0,
                    }
                )

        if not matched_rows:
            return {
                "ok": False,
                "reason": "realtime_not_found",
                "serial_input": input_serial,
                "realtime_attempts": realtime_attempts,
                "history_probe": {},
                "field_summary": {
                    "realtime_fields": [],
                    "realtime_non_null_fields": [],
                },
            }

        preferred = matched_rows[0]
        business_type = int(preferred[0])
        row = dict(preferred[1])
        resolved_serial = str(row.get("deviceSn") or input_serial).strip()

        history_probe: dict[str, Any] = {}
        history_fields: set[str] = set()
        history_non_null_fields: set[str] = set()
        history_rows_count = 0
        end_time = int(dt_util.utcnow().timestamp() * 1000)
        start_time = end_time - 60 * 60 * 1000
        try:
            history_payload = await self.client.device_history_data_windowed(
                sn_list=[resolved_serial],
                device_type=3,
                business_type=business_type,
                start_time=start_time,
                end_time=end_time,
                time_interval=15,
            )
            history_rows = history_payload.get("result") or []
            if isinstance(history_rows, list):
                history_rows_count = len(history_rows)
                for item in history_rows:
                    if not isinstance(item, dict):
                        continue
                    for key, value in item.items():
                        history_fields.add(str(key))
                        if value is not None:
                            history_non_null_fields.add(str(key))
            history_probe = {
                "code": history_payload.get("code"),
                "message": history_payload.get("message"),
                "rows": history_rows_count,
                "window_summary": history_payload.get("windowSummary") or {},
            }
        except SolaxApiError as err:
            history_probe = {
                "code": err.code,
                "message": err.message,
                "classification": err.classification,
                "rows": 0,
            }

        return {
            "ok": True,
            "reason": "validated",
            "serial_input": input_serial,
            "serial_resolved": resolved_serial,
            "business_type": business_type,
            "realtime_attempts": realtime_attempts,
            "history_probe": history_probe,
            "field_summary": {
                "realtime_fields": sorted(all_realtime_fields),
                "realtime_non_null_fields": sorted(non_null_realtime_fields),
                "history_fields": sorted(history_fields),
                "history_non_null_fields": sorted(history_non_null_fields),
            },
            "sample_realtime_row": row,
        }

    def _is_night_mode(self) -> bool:
        return self._get_live_view_manager().is_night_mode()


    def _expire_live_view_if_needed(self) -> None:
        self._get_live_view_manager().expire_if_needed()


    @property
    def live_view_active(self) -> bool:
        return self._get_live_view_manager().active


    @property
    def live_view_remaining_seconds(self) -> int:
        return self._get_live_view_manager().remaining_seconds


    @property
    def live_view_until(self) -> datetime | None:
        return self._get_live_view_manager().until


    def _estimate_live_cycle_calls(
        self,
        plants: dict[str, dict[str, Any]],
        inventory_by_type: dict[str, list[str]],
    ) -> int:
        return self._get_live_view_manager().estimate_cycle_calls(
            plants, inventory_by_type
        )


    def _compute_safe_live_interval(
        self,
        plants: dict[str, dict[str, Any]],
        inventory_by_type: dict[str, list[str]],
    ) -> int:
        return self._get_live_view_manager().compute_safe_interval(
            plants, inventory_by_type
        )


    def _apply_dynamic_poll_profile(
        self,
        plants: dict[str, dict[str, Any]],
        inventory_by_type: dict[str, list[str]],
    ) -> None:
        self._get_live_view_manager().apply_poll_profile(
            plants, inventory_by_type
        )


    def _refresh_meta_state(self) -> None:
        meta = self.data.setdefault("meta", {})
        meta["effective_scan_interval"] = self._effective_scan_interval
        meta["poll_profile"] = self._poll_profile
        meta["live_view_active"] = self.live_view_active
        meta["live_view_until"] = (
            self._live_view_until.isoformat() if self._live_view_until else None
        )
        meta["live_view_remaining_seconds"] = self.live_view_remaining_seconds
        meta["live_view_target_interval"] = self._live_view_requested_interval
        meta["live_view_budget_adjusted"] = self._live_view_budget_adjusted
        meta["live_view_call_budget_per_minute"] = self._live_view_call_budget_per_minute
        meta["live_view_estimated_calls_per_cycle"] = self._estimated_live_calls_per_cycle
        meta["alarm_reserved_calls_per_minute"] = getattr(
            self,
            "_alarm_reserved_calls_per_minute",
            0.0,
        )
        alarm_manager = getattr(self, "_alarm_manager", None)
        meta["alarm_last_merge_at"] = getattr(
            self,
            "_alarm_last_merge_at",
            None,
        )
        meta["alarm_scan_interval"] = getattr(
            alarm_manager,
            "scan_interval",
            getattr(self, "_alarm_scan_interval", DEFAULT_ALARM_SCAN_INTERVAL),
        )
        meta["alarm_last_update_attempt"] = getattr(
            alarm_manager,
            "last_update_attempt",
            None,
        )
        meta["alarm_last_successful_update"] = getattr(
            alarm_manager,
            "last_successful_update",
            None,
        )
        meta["alarm_last_update_success"] = getattr(
            alarm_manager,
            "last_update_success",
            None,
        )
        meta["alarm_last_error"] = getattr(alarm_manager, "last_error", None)
        meta["alarm_last_errors"] = deepcopy(
            getattr(alarm_manager, "last_errors", [])
        )
        meta["night_scan_interval"] = self._night_scan_interval
        meta["night_start_hour"] = self._night_start_hour
        meta["night_end_hour"] = self._night_end_hour
        meta["refresh_failure_streak"] = self._refresh_failure_streak
        meta["refresh_backoff_seconds"] = self._refresh_backoff_seconds
        meta["last_refresh_failure_classification"] = self._last_refresh_failure_classification
        meta["last_refresh_failure_context"] = self._last_refresh_failure_context
        meta["last_refresh_failure_at"] = (
            self._last_refresh_failure_at.isoformat() if self._last_refresh_failure_at else None
        )
        meta["manual_meter_serial_count"] = len(self._manual_meter_entries)
        meta["manual_meter_serials"] = [dict(item) for item in self._manual_meter_entries]
        manual_ems_entries = getattr(self, "_manual_ems_entries", [])
        meta["manual_ems_system_count"] = len(manual_ems_entries)
        meta["manual_ems_systems"] = [dict(item) for item in manual_ems_entries]
        meta["ev_charger_controls_enabled"] = getattr(
            self,
            "_ev_charger_controls_enabled",
            False,
        )
        meta["ev_charger_control_commands"] = len(
            getattr(self, "_ev_charger_control_commands", []) or []
        )
        meta["capability_families"] = sorted(self.capability_families)
        meta["available_control_services"] = sorted(self.available_control_services)
        meta["token_scope"] = getattr(self.client, "token_scope", None)
        meta["token_grant_type"] = getattr(self.client, "token_grant_type", None)
        token_auth_station = getattr(self.client, "token_auth_station", None)
        meta["token_auth_station_scope"] = (
            "all"
            if token_auth_station == "all"
            else (
                f"scoped:{len(str(token_auth_station).split())}"
                if token_auth_station
                else None
            )
        )

    async def async_start_live_view(
        self,
        *,
        duration_seconds: int | None = None,
        interval_seconds: int | None = None,
    ) -> dict[str, Any]:
        return await self._get_live_view_manager().async_start(
            duration_seconds=duration_seconds,
            interval_seconds=interval_seconds,
        )


    async def async_stop_live_view(self) -> dict[str, Any]:
        return await self._get_live_view_manager().async_stop()


    def _mark_rate_limit(self, context: str) -> None:
        self.rate_limited = True
        if context not in self.rate_limited_context:
            self.rate_limited_context.append(context)
        self.last_rate_limit_at = dt_util.utcnow()

    def _append_error(self, errors: list[dict[str, Any]], err: Exception, context: str) -> None:
        serialized = serialize_api_error(err)
        serialized["context"] = context
        errors.append(serialized)

        code = serialized.get("code")
        if code in ERROR_RATE_LIMIT_CODES or code in ERROR_QUOTA_CODES:
            self._mark_rate_limit(context)

    async def _discover_ems_devices(
        self,
        *,
        devices: dict[str, dict[str, Any]],
        raw_cycle: dict[str, list[dict[str, Any]]] | None,
    ) -> dict[str, dict[str, Any]]:
        """Discover top-level EMS systems through their C&I child devices."""
        ems_devices: dict[str, dict[str, Any]] = {}
        for device_sn, device in list(devices.items()):
            business_type = self._coerce_int(device.get("businessType"))
            device_type = self._coerce_int(device.get("deviceType"))
            if business_type != 4 or device_type not in DEVICE_TYPES:
                continue
            try:
                payload = await self.client.get_master_control_device(
                    device_sn=str(device_sn),
                    device_type=int(device_type),
                    business_type=4,
                )
                self._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_MASTER_CONTROL_DEVICE,
                    request={
                        "deviceSn": str(device_sn),
                        "deviceType": int(device_type),
                        "businessType": 4,
                    },
                    response=payload,
                )
            except SolaxApiError as err:
                # A C&I device without an EMS relationship is a supported topology.
                self._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_MASTER_CONTROL_DEVICE,
                    request={
                        "deviceSn": str(device_sn),
                        "deviceType": int(device_type),
                        "businessType": 4,
                    },
                    error=err,
                    optional_absence=True,
                )
                continue

            result = payload.get("result") or {}
            if not isinstance(result, Mapping):
                continue
            control_type = self._coerce_int(result.get("controlDeviceType"))
            control_serial = str(result.get("controlDeviceSn") or "").strip()
            if control_type != EMS_DEVICE_TYPE or not control_serial:
                continue
            plant_id = str(device.get("plantId") or "").strip()
            ems_devices[control_serial] = {
                "deviceSn": control_serial,
                "registerNo": control_serial,
                "deviceType": EMS_DEVICE_TYPE,
                "businessType": 4,
                "plantId": plant_id,
                "discoverySource": "master_control_device",
                "controlChildDeviceSn": str(device_sn),
            }
        return ems_devices

    async def _hydrate_ems_attributes(
        self,
        *,
        ems_devices: dict[str, dict[str, Any]],
        raw_cycle: dict[str, list[dict[str, Any]]] | None,
    ) -> dict[str, dict[str, Any]]:
        hydrated: dict[str, dict[str, Any]] = {}
        for serial, device in ems_devices.items():
            plant_id = str(device.get("plantId") or "").strip()
            normalized = dict(device)
            if not plant_id:
                hydrated[serial] = normalized
                continue
            try:
                payload = await self.client.ems_attribute_info(
                    register_no=serial,
                    plant_id=plant_id,
                    business_type=4,
                )
                self._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_EMS_ATTRIBUTE_INFO,
                    request={
                        "registerNo": serial,
                        "plantId": plant_id,
                        "deviceType": EMS_DEVICE_TYPE,
                        "businessType": 4,
                    },
                    response=payload,
                )
                rows = payload.get("result") or []
                if isinstance(rows, Mapping):
                    rows = [rows]
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, Mapping):
                            continue
                        row_serial = str(row.get("registerNo") or serial).strip()
                        if row_serial.casefold() != serial.casefold():
                            continue
                        normalized.update(dict(row))
                        break
            except SolaxApiError as err:
                self._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_EMS_ATTRIBUTE_INFO,
                    request={
                        "registerNo": serial,
                        "plantId": plant_id,
                        "deviceType": EMS_DEVICE_TYPE,
                        "businessType": 4,
                    },
                    error=err,
                )
            normalized["deviceSn"] = serial
            normalized["registerNo"] = serial
            normalized["deviceType"] = EMS_DEVICE_TYPE
            normalized["businessType"] = 4
            normalized["plantId"] = str(
                normalized.get("stationId") or normalized.get("plantId") or plant_id
            )
            hydrated[serial] = normalized
        return hydrated

    async def _refresh_inventory(
        self,
        raw_cycle: dict[str, list[dict[str, Any]]] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[str]]]:
        """Load all plants and devices visible to credentials."""
        plants: dict[str, dict[str, Any]] = {}
        devices: dict[str, dict[str, Any]] = {}
        inventory_by_type: dict[str, list[str]] = defaultdict(list)

        # Plants by business type with pagination.
        for business_type in BUSINESS_TYPES:
            page = 1
            while True:
                try:
                    payload = await self.client.page_plant_info(
                        business_type=business_type,
                        page_no=page,
                    )
                    self._append_raw_snapshot(
                        raw_cycle,
                        endpoint=RAW_ENDPOINT_PAGE_PLANT_INFO,
                        request={
                            "businessType": business_type,
                            "pageNo": page,
                        },
                        response=payload,
                    )
                except SolaxApiError as err:
                    self._append_raw_snapshot(
                        raw_cycle,
                        endpoint=RAW_ENDPOINT_PAGE_PLANT_INFO,
                        request={
                            "businessType": business_type,
                            "pageNo": page,
                        },
                        error=err,
                    )
                    if err.classification == "permission":
                        break
                    raise
                result = payload.get("result") or {}
                records = result.get("records") or []
                for plant in records:
                    plant_id = str(plant.get("plantId") or "").strip()
                    if not plant_id:
                        continue
                    normalized = dict(plant)
                    normalized["businessType"] = business_type
                    plants[plant_id] = normalized

                current = int(result.get("current") or page)
                pages = int(result.get("pages") or current)
                if current >= pages:
                    break
                page += 1

        # Devices by type + business type with pagination.
        for business_type in BUSINESS_TYPES:
            for device_type in DEVICE_TYPES:
                page = 1
                while True:
                    try:
                        payload = await self.client.page_device_info(
                            business_type=business_type,
                            device_type=device_type,
                            page_no=page,
                        )
                        self._append_raw_snapshot(
                            raw_cycle,
                            endpoint=RAW_ENDPOINT_PAGE_DEVICE_INFO,
                            request={
                                "businessType": business_type,
                                "deviceType": device_type,
                                "pageNo": page,
                            },
                            response=payload,
                        )
                    except SolaxApiError as err:
                        self._append_raw_snapshot(
                            raw_cycle,
                            endpoint=RAW_ENDPOINT_PAGE_DEVICE_INFO,
                            request={
                                "businessType": business_type,
                                "deviceType": device_type,
                                "pageNo": page,
                            },
                            error=err,
                        )
                        if err.classification == "permission":
                            break
                        raise
                    result = payload.get("result") or {}
                    records = result.get("records") or []
                    for device in records:
                        sn = str(device.get("deviceSn") or "").strip()
                        if not sn:
                            continue
                        normalized = dict(device)
                        normalized["deviceType"] = device_type
                        normalized["businessType"] = business_type
                        devices[sn] = normalized

                        key = f"{business_type}:{device_type}"
                        if sn not in inventory_by_type[key]:
                            inventory_by_type[key].append(sn)

                    current = int(result.get("current") or page)
                    pages = int(result.get("pages") or current)
                    if current >= pages:
                        break
                    page += 1

        # Merge manually configured meter serials that may be hidden from inventory endpoints.
        for entry in self._manual_meter_entries:
            serial = str(entry.get("serial") or "").strip()
            if not serial:
                continue
            business_type = int(entry.get("business_type") or 1)
            if business_type not in BUSINESS_TYPES:
                business_type = 1
            existing_key = self._find_existing_serial_key(serial, devices)
            if existing_key is not None:
                continue

            devices[serial] = {
                "deviceSn": serial,
                "registerNo": serial,
                "deviceType": 3,
                "businessType": business_type,
                "onlineStatus": None,
                "flag": None,
                "manualSerial": True,
                "discoverySource": "manual_meter_serial",
            }
            inventory_key = f"{business_type}:3"
            if serial not in inventory_by_type[inventory_key]:
                inventory_by_type[inventory_key].append(serial)

        ems_devices = await self._discover_ems_devices(
            devices=devices,
            raw_cycle=raw_cycle,
        )
        for entry in getattr(self, "_manual_ems_entries", []):
            serial = str(entry.get("serial") or "").strip()
            plant_id = str(entry.get("plant_id") or "").strip()
            if not serial or not plant_id:
                continue
            existing_key = self._find_existing_serial_key(serial, ems_devices)
            if existing_key is not None:
                continue
            ems_devices[serial] = {
                "deviceSn": serial,
                "registerNo": serial,
                "deviceType": EMS_DEVICE_TYPE,
                "businessType": 4,
                "plantId": plant_id,
                "manualSerial": True,
                "discoverySource": "manual_ems_system",
            }

        hydrated_ems = await self._hydrate_ems_attributes(
            ems_devices=ems_devices,
            raw_cycle=raw_cycle,
        )
        for serial, ems_device in hydrated_ems.items():
            devices[serial] = ems_device
            inventory_key = f"4:{EMS_DEVICE_TYPE}"
            if serial not in inventory_by_type[inventory_key]:
                inventory_by_type[inventory_key].append(serial)

        return plants, devices, dict(inventory_by_type)

    async def _refresh_plant_realtime(
        self,
        plants: dict[str, dict[str, Any]],
        raw_cycle: dict[str, list[dict[str, Any]]] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], list[tuple[str, Exception]]]:
        plant_realtime: dict[str, dict[str, Any]] = {}
        errors: list[tuple[str, Exception]] = []
        for plant_id, plant in plants.items():
            business_type = int(plant.get("businessType") or 1)
            try:
                payload = await self.client.plant_realtime_data(
                    plant_id=plant_id,
                    business_type=business_type,
                )
                self._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_PLANT_REALTIME_DATA,
                    request={
                        "plantId": plant_id,
                        "businessType": business_type,
                    },
                    response=payload,
                )
                result = payload.get("result") or {}
                if isinstance(result, dict):
                    plant_realtime[plant_id] = result
            except Exception as err:  # noqa: BLE001
                self._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_PLANT_REALTIME_DATA,
                    request={
                        "plantId": plant_id,
                        "businessType": business_type,
                    },
                    error=err,
                )
                errors.append((f"plant_realtime:{plant_id}", err))
        return plant_realtime, errors

    async def _refresh_alarms(
        self,
        plants: dict[str, dict[str, Any]],
        raw_cycle: dict[str, list[dict[str, Any]]] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], list[tuple[str, Exception]]]:
        cycle = raw_cycle or self._new_raw_api_response_snapshot()
        alarms, errors, _api_calls = await self._get_alarm_manager()._refresh_active_alarms(
            plants, raw_cycle=cycle
        )
        return alarms, errors


    async def _refresh_stats(
        self,
        plants: dict[str, dict[str, Any]],
        raw_cycle: dict[str, list[dict[str, Any]]] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], list[tuple[str, Exception]]]:
        stats: dict[str, dict[str, Any]] = {}
        errors: list[tuple[str, Exception]] = []
        now = dt_util.now()
        current_year = f"{now.year}"
        current_month = f"{now.year}-{now.month:02d}"

        for plant_id, plant in plants.items():
            business_type = int(plant.get("businessType") or 1)
            try:
                year_payload = await self.client.plant_stat_data(
                    plant_id=plant_id,
                    business_type=business_type,
                    date_type=1,
                    date=current_year,
                )
                self._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_PLANT_STAT_DATA,
                    request={
                        "plantId": plant_id,
                        "businessType": business_type,
                        "dateType": 1,
                        "date": current_year,
                    },
                    response=year_payload,
                )
                stats.setdefault(plant_id, {})["year"] = year_payload.get("result") or {}
            except Exception as err:  # noqa: BLE001
                self._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_PLANT_STAT_DATA,
                    request={
                        "plantId": plant_id,
                        "businessType": business_type,
                        "dateType": 1,
                        "date": current_year,
                    },
                    error=err,
                )
                errors.append((f"plant_stats_year:{plant_id}", err))

            try:
                month_payload = await self.client.plant_stat_data(
                    plant_id=plant_id,
                    business_type=business_type,
                    date_type=2,
                    date=current_month,
                )
                self._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_PLANT_STAT_DATA,
                    request={
                        "plantId": plant_id,
                        "businessType": business_type,
                        "dateType": 2,
                        "date": current_month,
                    },
                    response=month_payload,
                )
                stats.setdefault(plant_id, {})["month"] = month_payload.get("result") or {}
            except Exception as err:  # noqa: BLE001
                self._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_PLANT_STAT_DATA,
                    request={
                        "plantId": plant_id,
                        "businessType": business_type,
                        "dateType": 2,
                        "date": current_month,
                    },
                    error=err,
                )
                errors.append((f"plant_stats_month:{plant_id}", err))
        return stats, errors

    async def _refresh_device_realtime(
        self,
        inventory_by_type: dict[str, list[str]],
        raw_cycle: dict[str, list[dict[str, Any]]] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], list[tuple[str, SolaxApiError]]]:
        device_realtime: dict[str, dict[str, Any]] = {}
        refresh_errors: list[tuple[str, SolaxApiError]] = []

        for key, sn_list in inventory_by_type.items():
            business_type_str, device_type_str = key.split(":", 1)
            business_type = int(business_type_str)
            device_type = int(device_type_str)
            if device_type == EMS_DEVICE_TYPE:
                continue
            normalized_sn_list = normalize_sn_list(sn_list)
            if not normalized_sn_list:
                continue
            for chunk_start in range(0, len(normalized_sn_list), MAX_SN_PER_REQUEST):
                sn_chunk = normalized_sn_list[chunk_start : chunk_start + MAX_SN_PER_REQUEST]
                chunk_index = (chunk_start // MAX_SN_PER_REQUEST) + 1
                try:
                    payload = await self.client.device_realtime_data(
                        sn_list=sn_chunk,
                        device_type=device_type,
                        business_type=business_type,
                    )
                    self._append_raw_snapshot(
                        raw_cycle,
                        endpoint=RAW_ENDPOINT_DEVICE_REALTIME_DATA,
                        request={
                            "businessType": business_type,
                            "deviceType": device_type,
                            "snList": list(sn_chunk),
                            "chunkIndex": chunk_index,
                        },
                        response=payload,
                    )
                    records = payload.get("result") or []
                    if not isinstance(records, list):
                        records = []
                except SolaxApiError as err:
                    self._append_raw_snapshot(
                        raw_cycle,
                        endpoint=RAW_ENDPOINT_DEVICE_REALTIME_DATA,
                        request={
                            "businessType": business_type,
                            "deviceType": device_type,
                            "snList": list(sn_chunk),
                            "chunkIndex": chunk_index,
                        },
                        error=err,
                    )
                    refresh_errors.append((f"device_realtime:{key}:chunk:{chunk_index}", err))
                    continue

                for item in records:
                    sn = str(item.get("deviceSn") or "").strip()
                    if not sn:
                        continue
                    payload = dict(item)
                    payload["deviceType"] = device_type
                    payload["businessType"] = business_type
                    device_realtime[sn] = payload

        return device_realtime, refresh_errors

    async def _refresh_ems_realtime(
        self,
        inventory_by_type: dict[str, list[str]],
        raw_cycle: dict[str, list[dict[str, Any]]] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], list[tuple[str, SolaxApiError]]]:
        ems_realtime: dict[str, dict[str, Any]] = {}
        refresh_errors: list[tuple[str, SolaxApiError]] = []
        serials = normalize_sn_list(
            inventory_by_type.get(f"4:{EMS_DEVICE_TYPE}") or []
        )
        for chunk_start in range(0, len(serials), MAX_SN_PER_REQUEST):
            serial_chunk = serials[chunk_start : chunk_start + MAX_SN_PER_REQUEST]
            chunk_index = (chunk_start // MAX_SN_PER_REQUEST) + 1
            try:
                payload = await self.client.ems_summary_data(
                    register_no_list=serial_chunk,
                    business_type=4,
                )
                self._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_EMS_SUMMARY_DATA,
                    request={
                        "registerNoList": list(serial_chunk),
                        "deviceType": EMS_DEVICE_TYPE,
                        "businessType": 4,
                        "chunkIndex": chunk_index,
                    },
                    response=payload,
                )
                rows = payload.get("result") or []
                if not isinstance(rows, list):
                    rows = []
            except SolaxApiError as err:
                self._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_EMS_SUMMARY_DATA,
                    request={
                        "registerNoList": list(serial_chunk),
                        "deviceType": EMS_DEVICE_TYPE,
                        "businessType": 4,
                        "chunkIndex": chunk_index,
                    },
                    error=err,
                )
                refresh_errors.append((f"ems_realtime:chunk:{chunk_index}", err))
                continue

            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                serial = str(row.get("registerNo") or "").strip()
                if not serial:
                    continue
                normalized = dict(row)
                normalized["deviceSn"] = serial
                normalized["registerNo"] = serial
                normalized["deviceType"] = EMS_DEVICE_TYPE
                normalized["businessType"] = 4
                ems_realtime[serial] = normalized
        return ems_realtime, refresh_errors

    async def _async_update_data(self) -> dict[str, Any]:
        """Serialize public state refreshes with independent alarm state merges."""
        async with self._get_state_merge_lock():
            return await self._async_update_data_unlocked()

    async def _async_update_data_unlocked(self) -> dict[str, Any]:
        """Fetch all read endpoints for telemetry model."""
        self._expire_live_view_if_needed()
        live_view_active = self.live_view_active
        self.last_update_attempt = dt_util.utcnow()
        self.rate_limited = False
        self.rate_limited_context = []
        self._poll_count += 1

        state = dict(self.data or self._empty_state())
        errors: list[dict[str, Any]] = []
        raw_cycle = self._new_raw_api_response_snapshot()

        refresh_inventory = (
            self._poll_count == 1
            or (not live_view_active and self._poll_count % INVENTORY_REFRESH_EVERY_POLLS == 0)
            or not state.get("plants")
            or not state.get("devices")
            or not state.get("inventory_by_type")
        )

        plants = dict(state.get("plants") or {})
        devices = dict(state.get("devices") or {})
        inventory_by_type = dict(state.get("inventory_by_type") or {})

        if refresh_inventory:
            try:
                plants, devices, inventory_by_type = await self._refresh_inventory(raw_cycle=raw_cycle)
            except Exception as err:  # noqa: BLE001
                self._append_error(errors, err, "inventory")

        plant_realtime = dict(state.get("plant_realtime") or {})
        try:
            if plants:
                refreshed_plant_realtime, plant_realtime_errors = await self._refresh_plant_realtime(
                    plants,
                    raw_cycle=raw_cycle,
                )
                for context, endpoint_error in plant_realtime_errors:
                    self._append_error(errors, endpoint_error, context)
                if plant_realtime_errors:
                    plant_realtime = {
                        plant_id: plant_realtime[plant_id]
                        for plant_id in plants
                        if plant_id in plant_realtime
                    }
                    plant_realtime.update(refreshed_plant_realtime)
                else:
                    plant_realtime = refreshed_plant_realtime
        except Exception as err:  # noqa: BLE001
            self._append_error(errors, err, "plant_realtime")

        alarms = dict(state.get("alarms") or {})
        if (
            not live_view_active
            and getattr(self, "_alarm_manager_unsub", None) is None
        ):
            try:
                if plants:
                    refreshed_alarms, alarm_errors = await self._refresh_alarms(
                        plants,
                        raw_cycle=raw_cycle,
                    )
                    for context, endpoint_error in alarm_errors:
                        self._append_error(errors, endpoint_error, context)
                    if alarm_errors:
                        alarms = {
                            plant_id: alarms[plant_id]
                            for plant_id in plants
                            if plant_id in alarms
                        }
                        alarms.update(refreshed_alarms)
                    else:
                        alarms = refreshed_alarms
            except Exception as err:  # noqa: BLE001
                self._append_error(errors, err, "alarms")

        plant_stats = dict(state.get("plant_stats") or {})
        if not live_view_active:
            try:
                if plants:
                    refreshed_stats, stats_errors = await self._refresh_stats(
                        plants,
                        raw_cycle=raw_cycle,
                    )
                    for context, endpoint_error in stats_errors:
                        self._append_error(errors, endpoint_error, context)
                    if stats_errors:
                        merged_stats: dict[str, dict[str, Any]] = {}
                        for plant_id in plants:
                            prior = dict(plant_stats.get(plant_id) or {})
                            prior.update(refreshed_stats.get(plant_id) or {})
                            if prior:
                                merged_stats[plant_id] = prior
                        plant_stats = merged_stats
                    else:
                        plant_stats = refreshed_stats
            except Exception as err:  # noqa: BLE001
                self._append_error(errors, err, "plant_stats")

        device_realtime = dict(state.get("device_realtime") or {})
        try:
            if inventory_by_type:
                refreshed_realtime, realtime_errors = await self._refresh_device_realtime(
                    inventory_by_type,
                    raw_cycle=raw_cycle,
                )
                if realtime_errors:
                    for context, endpoint_error in realtime_errors:
                        self._append_error(errors, endpoint_error, context)
                    if refreshed_realtime:
                        stale_merged = dict(device_realtime)
                        stale_merged.update(refreshed_realtime)
                        device_realtime = stale_merged
                else:
                    device_realtime = refreshed_realtime
        except Exception as err:  # noqa: BLE001
            self._append_error(errors, err, "device_realtime")

        try:
            if inventory_by_type.get(f"4:{EMS_DEVICE_TYPE}"):
                refreshed_ems, ems_errors = await self._refresh_ems_realtime(
                    inventory_by_type,
                    raw_cycle=raw_cycle,
                )
                if ems_errors:
                    for context, endpoint_error in ems_errors:
                        self._append_error(errors, endpoint_error, context)
                if refreshed_ems:
                    device_realtime.update(refreshed_ems)
        except Exception as err:  # noqa: BLE001
            self._append_error(errors, err, "ems_realtime")

        self._update_device_capabilities(devices, device_realtime)
        self._merge_raw_errors_into_errors(errors, raw_cycle)
        self._merge_raw_api_cycle(raw_cycle)

        has_fresh_endpoint_data = self._count_raw_cycle_responses(raw_cycle) > 0
        if has_fresh_endpoint_data:
            self._register_refresh_success()
            self.last_successful_update = dt_util.utcnow()
        else:
            failure_classification, failure_context, failure_message = self._select_refresh_failure_signal(
                errors,
                raw_cycle,
            )
            self._register_refresh_failure(failure_classification, failure_context)

        self._apply_dynamic_poll_profile(plants, inventory_by_type)

        manual_ems_entries = getattr(self, "_manual_ems_entries", [])
        token_scope = getattr(self.client, "token_scope", None)
        token_grant_type = getattr(self.client, "token_grant_type", None)
        token_auth_station = getattr(self.client, "token_auth_station", None)
        state.update(
            {
                "plants": plants,
                "devices": devices,
                "inventory_by_type": inventory_by_type,
                "plant_realtime": plant_realtime,
                "plant_stats": plant_stats,
                "alarms": alarms,
                "device_realtime": device_realtime,
                "last_errors": errors,
                "manual_meter_entries": [dict(item) for item in self._manual_meter_entries],
                "manual_ems_entries": [dict(item) for item in manual_ems_entries],
                "raw_api_responses": self.raw_api_responses,
                "meta": {
                    "poll_count": self._poll_count,
                    "last_update_attempt": self.last_update_attempt,
                    "last_successful_update": self.last_successful_update,
                    "rate_limited": self.rate_limited,
                    "rate_limited_context": list(self.rate_limited_context),
                    "last_rate_limit_at": self.last_rate_limit_at,
                    "token_expires_at": self.client.token_expires_at,
                    "history_cache_entries": len(self._history_cache),
                    "dry_run_commands": len(self._control_dry_runs),
                    "ev_charger_controls_enabled": getattr(
                        self,
                        "_ev_charger_controls_enabled",
                        False,
                    ),
                    "ev_charger_control_commands": len(
                        getattr(self, "_ev_charger_control_commands", []) or []
                    ),
                    "effective_scan_interval": self._effective_scan_interval,
                    "poll_profile": self._poll_profile,
                    "live_view_active": self.live_view_active,
                    "live_view_until": (
                        self._live_view_until.isoformat() if self._live_view_until else None
                    ),
                    "live_view_remaining_seconds": self.live_view_remaining_seconds,
                    "live_view_target_interval": self._live_view_requested_interval,
                    "live_view_budget_adjusted": self._live_view_budget_adjusted,
                    "live_view_call_budget_per_minute": self._live_view_call_budget_per_minute,
                    "live_view_estimated_calls_per_cycle": self._estimated_live_calls_per_cycle,
                    "alarm_reserved_calls_per_minute": getattr(
                        self,
                        "_alarm_reserved_calls_per_minute",
                        0.0,
                    ),
                    "alarm_scan_interval": getattr(
                        getattr(self, "_alarm_manager", None),
                        "scan_interval",
                        getattr(
                            self,
                            "_alarm_scan_interval",
                            DEFAULT_ALARM_SCAN_INTERVAL,
                        ),
                    ),
                    "alarm_last_merge_at": getattr(
                        self,
                        "_alarm_last_merge_at",
                        None,
                    ),
                    "alarm_last_update_attempt": getattr(
                        getattr(self, "_alarm_manager", None),
                        "last_update_attempt",
                        None,
                    ),
                    "alarm_last_successful_update": getattr(
                        getattr(self, "_alarm_manager", None),
                        "last_successful_update",
                        None,
                    ),
                    "alarm_last_update_success": getattr(
                        getattr(self, "_alarm_manager", None),
                        "last_update_success",
                        None,
                    ),
                    "alarm_last_error": getattr(
                        getattr(self, "_alarm_manager", None),
                        "last_error",
                        None,
                    ),
                    "alarm_last_errors": deepcopy(
                        getattr(
                            getattr(self, "_alarm_manager", None),
                            "last_errors",
                            [],
                        )
                    ),
                    "night_scan_interval": self._night_scan_interval,
                    "night_start_hour": self._night_start_hour,
                    "night_end_hour": self._night_end_hour,
                    "refresh_failure_streak": self._refresh_failure_streak,
                    "refresh_backoff_seconds": self._refresh_backoff_seconds,
                    "last_refresh_failure_classification": self._last_refresh_failure_classification,
                    "last_refresh_failure_context": self._last_refresh_failure_context,
                    "last_refresh_failure_at": self._last_refresh_failure_at,
                    "manual_meter_serial_count": len(self._manual_meter_entries),
                    "manual_meter_serials": [dict(item) for item in self._manual_meter_entries],
                    "manual_ems_system_count": len(manual_ems_entries),
                    "manual_ems_systems": [dict(item) for item in manual_ems_entries],
                    "capability_serial_count": len(self._device_capabilities),
                    "capability_field_total": sum(
                        len(entry.get("fields") or [])
                        for entry in self._device_capabilities.values()
                        if isinstance(entry, dict)
                    ),
                    "capability_families": sorted(self.capability_families),
                    "available_control_services": sorted(
                        self.available_control_services
                    ),
                    "token_scope": token_scope,
                    "token_grant_type": token_grant_type,
                    "token_auth_station_scope": (
                        "all"
                        if token_auth_station == "all"
                        else (
                            f"scoped:{len(str(token_auth_station).split())}"
                            if token_auth_station
                            else None
                        )
                    ),
                },
            }
        )

        self.data = state
        self._refresh_meta_state()
        if not has_fresh_endpoint_data:
            if failure_classification == "auth":
                raise ConfigEntryAuthFailed(failure_message)
            raise UpdateFailed(
                f"No fresh API data this cycle ({failure_context}): {failure_message}"
            )
        return self.data

    async def async_fetch_device_history(
        self,
        *,
        sn_list: list[str],
        device_type: int,
        business_type: int,
        start_time: int,
        end_time: int,
        time_interval: int,
        request_sn_type: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._get_history_manager().async_fetch_device_history(
            sn_list=sn_list,
            device_type=device_type,
            business_type=business_type,
            start_time=start_time,
            end_time=end_time,
            time_interval=time_interval,
            request_sn_type=request_sn_type,
            request_id=request_id,
        )


    async def async_fetch_alarm_information(
        self,
        *,
        plant_id: str | None = None,
        business_type: int | None = None,
        alarm_state: str | int = "all",
        device_sn: str | None = None,
        max_pages: int = 20,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._get_alarm_manager().async_fetch_alarm_information(
            plant_id=plant_id,
            business_type=business_type,
            alarm_state=alarm_state,
            device_sn=device_sn,
            max_pages=max_pages,
            request_id=request_id,
        )


    @staticmethod
    def _normalize_alarm_states(alarm_state: str | int) -> list[int]:
        return AlarmManager.normalize_alarm_states(alarm_state)


    async def async_fetch_plant_year_statistics(
        self,
        *,
        plant_id: str,
        business_type: int,
        year: int,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._get_history_manager().async_fetch_plant_year_statistics(
            plant_id=plant_id,
            business_type=business_type,
            year=year,
            request_id=request_id,
        )


    async def async_fetch_plant_month_statistics(
        self,
        *,
        plant_id: str,
        business_type: int,
        year: int,
        month: int,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._get_history_manager().async_fetch_plant_month_statistics(
            plant_id=plant_id,
            business_type=business_type,
            year=year,
            month=month,
            request_id=request_id,
        )


    @staticmethod
    def _plant_stat_daily_timestamp(
        row: Mapping[str, Any],
        *,
        year: int,
        month: int,
        fallback_day: int,
    ) -> tuple[str, int]:
        return HistoryManager.plant_stat_daily_timestamp(
            row,
            year=year,
            month=month,
            fallback_day=fallback_day,
        )


    async def async_query_request_result(self, request_id: str | int) -> dict[str, Any]:
        normalized_request_id = str(request_id).strip()
        if not normalized_request_id:
            raise ValueError("request_id must not be empty")
        payload = await self.client.query_request_result(request_id=normalized_request_id)
        self._request_result_cache[normalized_request_id] = {
            "updated_at": dt_util.utcnow().isoformat(),
            "response": payload,
        }
        return payload

    async def async_query_master_control_device(
        self,
        *,
        device_sn: str,
        device_type: int,
        business_type: int,
    ) -> dict[str, Any]:
        payload = await self.client.get_master_control_device(
            device_sn=device_sn,
            device_type=device_type,
            business_type=business_type,
        )
        self._master_control_cache[device_sn] = {
            "updated_at": dt_util.utcnow().isoformat(),
            "response": payload,
        }
        return payload

    @property
    def ev_charger_controls_enabled(self) -> bool:
        """Return whether real EV charger write calls are enabled."""
        return bool(getattr(self, "_ev_charger_controls_enabled", False))

    def _validate_ev_charger_control_targets(
        self,
        *,
        service: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if service not in EV_CHARGER_CONTROL_SERVICES:
            raise ValueError("not_ev_charger_control")

        business_type = self._coerce_int(payload.get("businessType"))
        known_targets: list[dict[str, Any]] = []
        for serial in payload.get("snList") or []:
            known = self.get_known_ev_charger_serial(str(serial))
            if known is None:
                raise ValueError("control_ev_charger_target_unknown")
            known_business_type = self._coerce_int(known.get("business_type"))
            if (
                business_type in BUSINESS_TYPES
                and known_business_type in BUSINESS_TYPES
                and known_business_type != business_type
            ):
                raise ValueError("control_ev_charger_business_type_mismatch")
            known_targets.append(known)
        return known_targets

    @staticmethod
    def _control_response_status_summary(payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result") or {}
        statuses: dict[str, dict[str, Any]] = {}
        accepted = payload.get("code") in {0, 10000}

        records: list[tuple[str, Any]] = []
        if isinstance(result, Mapping):
            if "status" in result:
                serial = str(
                    result.get("sn")
                    or result.get("deviceSn")
                    or result.get("registerNo")
                    or "device"
                )
                records.append((serial, result))
            else:
                records.extend(
                    (str(serial), item)
                    for serial, item in result.items()
                    if isinstance(item, Mapping) and "status" in item
                )
        elif isinstance(result, list):
            for index, item in enumerate(result):
                if not isinstance(item, Mapping):
                    continue
                serial = str(
                    item.get("sn")
                    or item.get("deviceSn")
                    or item.get("registerNo")
                    or f"device_{index + 1}"
                )
                records.append((serial, item))

        for serial, item in records:
            status_value = item.get("status") if isinstance(item, Mapping) else None
            status_int = SolaxDeveloperCoordinator._coerce_int(status_value)
            status_accepted = status_int in EV_CHARGER_ACCEPTED_COMMAND_STATUSES
            statuses[serial] = {
                "status": status_int,
                "status_name": COMMAND_STATUS_MAP.get(status_int or 0, "Unknown"),
                "accepted": status_accepted,
                "device_acknowledged": (
                    status_int in EV_CHARGER_DEVICE_ACKNOWLEDGED_STATUSES
                ),
                "failed": status_int in EV_CHARGER_FAILED_COMMAND_STATUSES,
            }

        if statuses:
            accepted = all(item["accepted"] for item in statuses.values())

        command_failed = any(item["failed"] for item in statuses.values())
        device_acknowledged = bool(statuses) and all(
            item["device_acknowledged"] for item in statuses.values()
        )
        pending = bool(statuses) and not command_failed and not device_acknowledged

        return {
            "accepted": accepted,
            "device_statuses": statuses,
            "command_failed": command_failed,
            "device_acknowledged": device_acknowledged,
            "pending": pending,
        }

    async def _confirm_ev_charger_control(
        self,
        *,
        request_id: str,
        initial_summary: dict[str, Any],
    ) -> dict[str, Any]:
        if initial_summary.get("command_failed"):
            return {
                "confirmation_state": "failed",
                "confirmation_attempts": 0,
                "confirmation_response": None,
                "confirmation_error": None,
                **initial_summary,
            }
        if initial_summary.get("device_acknowledged"):
            return {
                "confirmation_state": "device_acknowledged",
                "confirmation_attempts": 0,
                "confirmation_response": None,
                "confirmation_error": None,
                **initial_summary,
            }
        if not request_id:
            return {
                "confirmation_state": "unavailable",
                "confirmation_attempts": 0,
                "confirmation_response": None,
                "confirmation_error": None,
                **initial_summary,
            }

        attempts = max(
            1,
            EV_CHARGER_CONFIRMATION_TIMEOUT_SECONDS
            // EV_CHARGER_CONFIRMATION_POLL_SECONDS,
        )
        latest_summary = dict(initial_summary)
        latest_response: dict[str, Any] | None = None
        latest_error: dict[str, Any] | None = None
        completed_attempts = 0

        for _ in range(attempts):
            await asyncio.sleep(EV_CHARGER_CONFIRMATION_POLL_SECONDS)
            completed_attempts += 1
            try:
                latest_response = await self.async_query_request_result(request_id)
                latest_error = None
            except Exception as err:  # noqa: BLE001
                latest_error = serialize_api_error(err)
                continue

            queried_summary = self._control_response_status_summary(latest_response)
            if queried_summary.get("device_statuses"):
                latest_summary = queried_summary
            if latest_summary.get("command_failed"):
                return {
                    "confirmation_state": "failed",
                    "confirmation_attempts": completed_attempts,
                    "confirmation_response": latest_response,
                    "confirmation_error": latest_error,
                    **latest_summary,
                }
            if latest_summary.get("device_acknowledged"):
                return {
                    "confirmation_state": "device_acknowledged",
                    "confirmation_attempts": completed_attempts,
                    "confirmation_response": latest_response,
                    "confirmation_error": latest_error,
                    **latest_summary,
                }

        confirmation_state = "query_failed" if latest_error else "pending"
        return {
            "confirmation_state": confirmation_state,
            "confirmation_attempts": completed_attempts,
            "confirmation_response": latest_response,
            "confirmation_error": latest_error,
            **latest_summary,
        }

    async def async_execute_ev_charger_control(
        self,
        *,
        service: str,
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a validated EV charger control command."""
        targets = self._validate_ev_charger_control_targets(
            service=service,
            payload=payload,
        )
        response = await self.client.execute_control(
            path=endpoint,
            payload=payload,
        )
        initial_summary = self._control_response_status_summary(response)
        request_id = str(response.get("requestId") or "").strip()
        confirmation = await self._confirm_ev_charger_control(
            request_id=request_id,
            initial_summary=initial_summary,
        )
        event = {
            "timestamp": dt_util.utcnow().isoformat(),
            "service": service,
            "endpoint": endpoint,
            "payload": dict(payload),
            "target_count": len(targets),
            "targets": [
                {
                    "serial": str(target.get("serial") or ""),
                    "business_type": target.get("business_type"),
                    "source": target.get("source"),
                }
                for target in targets
            ],
            "blocked": False,
            "sent": True,
            "accepted": bool(initial_summary["accepted"]),
            "request_id": request_id or None,
            "response": response,
            "initial_device_statuses": initial_summary["device_statuses"],
            "device_statuses": confirmation["device_statuses"],
            "confirmation_state": confirmation["confirmation_state"],
            "confirmation_attempts": confirmation["confirmation_attempts"],
            "confirmation_response": confirmation["confirmation_response"],
            "confirmation_error": confirmation["confirmation_error"],
            "device_acknowledged": bool(confirmation["device_acknowledged"]),
            "execution_started": bool(confirmation["device_acknowledged"]),
            "command_failed": bool(confirmation["command_failed"]),
            "pending": confirmation["confirmation_state"] in {
                "pending",
                "query_failed",
                "unavailable",
            },
        }
        commands = getattr(self, "_ev_charger_control_commands", None)
        if not isinstance(commands, list):
            commands = []
            self._ev_charger_control_commands = commands
        commands.append(event)
        if len(commands) > 100:
            self._ev_charger_control_commands = commands[-100:]

        meta = self.data.setdefault("meta", {})
        meta["ev_charger_control_commands"] = len(self._ev_charger_control_commands)
        meta["last_ev_charger_control"] = event
        return event

    def record_control_dry_run(
        self,
        *,
        service: str,
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Record a dry-run command without sending write requests."""
        event = {
            "timestamp": dt_util.utcnow().isoformat(),
            "service": service,
            "endpoint": endpoint,
            "payload": payload,
            "blocked": True,
            "reason": translate(
                self.hass,
                "runtime.messages.dry_run_block_reason",
                fallback="Hard-blocked write path in development phase",
            ),
        }
        self._control_dry_runs.append(event)
        if len(self._control_dry_runs) > 100:
            self._control_dry_runs = self._control_dry_runs[-100:]

        self.data.setdefault("meta", {})["dry_run_commands"] = len(self._control_dry_runs)
        self.data["meta"]["last_dry_run"] = event
        return event

    @property
    def control_dry_runs(self) -> list[dict[str, Any]]:
        return list(self._control_dry_runs)

    @property
    def ev_charger_control_commands(self) -> list[dict[str, Any]]:
        return list(getattr(self, "_ev_charger_control_commands", []) or [])

    @property
    def history_cache(self) -> dict[str, dict[str, Any]]:
        return dict(self._history_cache)

    @property
    def request_result_cache(self) -> dict[str, dict[str, Any]]:
        return dict(self._request_result_cache)

    @property
    def master_control_cache(self) -> dict[str, dict[str, Any]]:
        return dict(self._master_control_cache)
