"""Config flow for SolaX Developer API integration."""

from __future__ import annotations

import ast
import logging
from collections.abc import Mapping
import json
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import persistent_notification
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SolaxApiError, SolaxDeveloperApiClient
from .i18n import async_ensure_catalog_loaded, translate
from .const import (
    API_REGION_CN,
    API_REGION_DEFAULT,
    API_REGION_EU,
    CONF_API_REGION,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_ENTITY_PREFIX,
    CONF_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
    CONF_LIVE_VIEW_DEFAULT_DURATION,
    CONF_LIVE_VIEW_INTERVAL,
    CONF_MANUAL_EMS_SYSTEMS,
    CONF_MANUAL_METER_SERIALS,
    CONF_NIGHT_END_HOUR,
    CONF_NIGHT_SCAN_INTERVAL,
    CONF_NIGHT_START_HOUR,
    CONF_RATE_LIMIT_NOTIFICATIONS,
    CONF_SCAN_INTERVAL,
    CONF_SYSTEM_NAME,
    DEFAULT_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
    DEFAULT_LIVE_VIEW_DEFAULT_DURATION,
    DEFAULT_LIVE_VIEW_INTERVAL,
    DEFAULT_NIGHT_END_HOUR,
    DEFAULT_NIGHT_SCAN_INTERVAL,
    DEFAULT_NIGHT_START_HOUR,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SYSTEM_NAME,
    DOMAIN,
    MAX_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
    MAX_LIVE_VIEW_DURATION,
    MAX_LIVE_VIEW_INTERVAL,
    MAX_NIGHT_SCAN_INTERVAL,
    MAX_SCAN_INTERVAL,
    MIN_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
    MIN_LIVE_VIEW_DURATION,
    MIN_LIVE_VIEW_INTERVAL,
    MIN_NIGHT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

CONNECTIVITY_READ_FAILURES = {"timeout", "http", "json", "network"}

CONF_MANUAL_METER_SERIALS_ADD = "manual_meter_serials_add"
CONF_MANUAL_METER_REMOVE_SERIAL = "manual_meter_remove_serial"
CONF_MANUAL_METER_REMOVE_CONFIRM = "manual_meter_remove_confirm"
MANUAL_METER_REMOVE_NONE = "__none__"
CONF_MANUAL_EMS_SYSTEMS_ADD = "manual_ems_systems_add"
CONF_MANUAL_EMS_REMOVE_SERIAL = "manual_ems_remove_serial"
CONF_MANUAL_EMS_REMOVE_CONFIRM = "manual_ems_remove_confirm"
MANUAL_EMS_REMOVE_NONE = "__none_ems__"


def _slugify_name(value: str) -> str:
    return value.lower().replace(" ", "_").replace("-", "_")


def _region_options(hass) -> dict[str, str]:
    return {
        API_REGION_EU: translate(
            hass,
            "runtime.labels.region.eu",
            fallback="EU (openapi-eu.solaxcloud.com)",
        ),
        API_REGION_CN: translate(
            hass,
            "runtime.labels.region.cn",
            fallback="CN (openapi-cn.solaxcloud.com)",
        ),
    }


def _manual_meter_notification_id(entry_id: str) -> str:
    return f"{DOMAIN}_manual_meter_options_{entry_id}"


def _manual_ems_notification_id(entry_id: str) -> str:
    return f"{DOMAIN}_manual_ems_options_{entry_id}"


def _manual_meter_entries_to_text(raw_entries: Any) -> str:
    lines: list[str] = []
    for item in _coerce_manual_meter_entries(raw_entries):
        serial = str(item.get("serial") or "").strip()
        if not serial:
            continue
        business_type = int(item.get("business_type") or 1)
        if business_type in (1, 4) and business_type != 1:
            lines.append(f"{serial}|{business_type}")
        else:
            lines.append(serial)

    return "\n".join(lines)


def _manual_meter_remove_options(hass, entries: list[dict[str, Any]]) -> dict[str, str]:
    options: dict[str, str] = {
        MANUAL_METER_REMOVE_NONE: translate(
            hass,
            "runtime.labels.none",
            fallback="(None)",
        )
    }
    for entry in entries:
        serial = str(entry.get("serial") or "").strip()
        if not serial:
            continue
        try:
            business_type = int(entry.get("business_type") or 1)
        except (TypeError, ValueError):
            business_type = 1
        business_type_label = translate(
            hass,
            f"runtime.labels.business_type.{business_type}",
            fallback=str(business_type),
        )
        options[serial] = translate(
            hass,
            "runtime.entity_templates.manual_meter_option",
            placeholders={
                "serial": serial,
                "business_type": business_type_label,
            },
            fallback="{serial} ({business_type})",
        )
    return options


def _parse_manual_meter_entries_text(raw_text: str) -> tuple[list[dict[str, Any]], str | None]:
    text = str(raw_text or "").strip()
    if not text:
        return [], None

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    normalized_lines = text.replace(",", "\n").splitlines()
    for raw_line in normalized_lines:
        line = str(raw_line).strip()
        if not line:
            continue

        serial = line
        business_type = 1
        if "|" in line:
            serial_part, bt_part = line.split("|", 1)
            serial = serial_part.strip()
            try:
                business_type = int(bt_part.strip())
            except (TypeError, ValueError):
                return [], "invalid_manual_meter_serials"
            if business_type not in (1, 4):
                return [], "invalid_manual_meter_serials"

        if not serial or any(ch.isspace() for ch in serial):
            return [], "invalid_manual_meter_serials"

        serial_key = serial.casefold()
        if serial_key in seen:
            continue
        seen.add(serial_key)
        entries.append(
            {
                "serial": serial,
                "business_type": business_type,
                "source": "manual",
            }
        )

    return entries, None


def _coerce_manual_meter_entries(raw_entries: Any) -> list[dict[str, Any]]:
    if raw_entries is None:
        return []

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
        if isinstance(decoded, (list, tuple)):
            raw_entries = list(decoded)
        elif isinstance(decoded, Mapping):
            raw_entries = [decoded]
        else:
            parsed, parse_err = _parse_manual_meter_entries_text(text)
            return parsed if parse_err is None else []

    if isinstance(raw_entries, tuple):
        raw_entries = list(raw_entries)
    if isinstance(raw_entries, Mapping):
        raw_entries = [raw_entries]
    if not isinstance(raw_entries, list):
        return []

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
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
                    item.get("business_type")
                    or item.get("businessType")
                    or 1
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
        if business_type not in (1, 4):
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


def _probe_realtime_fields_from_summary(summary: Any) -> list[str]:
    """Return observed non-null realtime fields."""
    if not isinstance(summary, Mapping):
        return []

    values = summary.get("realtime_non_null_fields") or []
    if not isinstance(values, (list, tuple)):
        return []
    return sorted(
        {
            str(field).strip()
            for field in values
            if str(field).strip()
        },
        key=str.casefold,
    )


def _merge_manual_meter_entry_sources(*sources: Any) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for source in sources:
        for item in _coerce_manual_meter_entries(source):
            serial = str(item.get("serial") or "").strip()
            if not serial:
                continue
            try:
                business_type = int(item.get("business_type") or 1)
            except (TypeError, ValueError):
                business_type = 1
            if business_type not in (1, 4):
                business_type = 1

            serial_key = serial.casefold()
            if serial_key in seen:
                continue
            seen.add(serial_key)
            raw_realtime_fields = item.get("realtime_fields") or []
            realtime_fields: list[str] = []
            if isinstance(raw_realtime_fields, (list, tuple)):
                realtime_fields = sorted(
                    {
                        str(field).strip()
                        for field in raw_realtime_fields
                        if str(field).strip()
                    },
                    key=str.casefold,
                )
            normalized_entry: dict[str, Any] = {
                "serial": serial,
                "business_type": business_type,
                "source": "manual",
            }
            if realtime_fields:
                normalized_entry["realtime_fields"] = realtime_fields
            merged.append(normalized_entry)

    return merged


def _coerce_manual_ems_entries(raw_entries: Any) -> list[dict[str, Any]]:
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
            parsed, error = _parse_manual_ems_entries_text(text)
            return parsed if error is None else []
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


def _parse_manual_ems_entries_text(
    raw_text: str,
) -> tuple[list[dict[str, Any]], str | None]:
    text = str(raw_text or "").strip()
    if not text:
        return [], None
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_line in text.replace(",", "\n").splitlines():
        line = str(raw_line).strip()
        if not line or "|" not in line:
            return [], "invalid_manual_ems_systems"
        serial, plant_id = (part.strip() for part in line.split("|", 1))
        if (
            not serial
            or not plant_id
            or any(ch.isspace() for ch in serial)
            or any(ch.isspace() for ch in plant_id)
        ):
            return [], "invalid_manual_ems_systems"
        if serial.casefold() in seen:
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
    return entries, None


def _manual_ems_remove_options(hass, entries: list[dict[str, Any]]) -> dict[str, str]:
    options = {
        MANUAL_EMS_REMOVE_NONE: translate(
            hass,
            "runtime.labels.none",
            fallback="(None)",
        )
    }
    for entry in entries:
        serial = str(entry.get("serial") or "").strip()
        plant_id = str(entry.get("plant_id") or "").strip()
        if not serial:
            continue
        options[serial] = translate(
            hass,
            "runtime.entity_templates.manual_ems_option",
            placeholders={"serial": serial, "plant_id": plant_id},
            fallback="{serial} (Plant {plant_id})",
        )
    return options


async def _validate_credentials(
    hass,
    *,
    client_id: str,
    client_secret: str,
    region: str,
) -> tuple[bool, str | None]:
    """Validate credentials by obtaining token and calling plant endpoint."""
    session = async_get_clientsession(hass)
    client = SolaxDeveloperApiClient(
        client_id=client_id,
        client_secret=client_secret,
        region=region,
        session=session,
    )

    try:
        await client.ensure_token(force_refresh=True)

        # Require at least one successful read call in addition to token auth.
        read_ok = False
        for business_type in (1, 4):
            try:
                await client.page_plant_info(business_type=business_type, page_no=1)
                read_ok = True
                break
            except SolaxApiError as err:
                if err.classification == "auth":
                    return False, "invalid_credentials"
                if str(err.classification or "").strip().casefold() in CONNECTIVITY_READ_FAILURES:
                    _LOGGER.debug(
                        "Credential validation businessType=%s failed with connectivity error: %s",
                        business_type,
                        err,
                    )
                    return False, "cannot_connect"
                # permission/range errors can be business-type specific; keep checking.
                _LOGGER.debug(
                    "Credential validation businessType=%s returned %s",
                    business_type,
                    err,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug(
                    "Credential validation businessType=%s failed with unexpected error: %s",
                    business_type,
                    err,
                )
                return False, "cannot_connect"
        if read_ok:
            return True, None
        return False, "cannot_read_data"
    except SolaxApiError as err:
        _LOGGER.warning("SolaX credential validation failed: %s", err)
        if err.classification == "auth":
            return False, "invalid_credentials"
        return False, "cannot_connect"
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Unexpected credential validation error: %s", err)
        return False, "cannot_connect"


class SolaxDeveloperFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle SolaX Developer API config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        await async_ensure_catalog_loaded(self.hass)
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}

        if user_input is not None:
            client_id = str(user_input[CONF_CLIENT_ID]).strip()
            client_secret = str(user_input[CONF_CLIENT_SECRET]).strip()
            system_name = str(user_input[CONF_SYSTEM_NAME]).strip()
            region = str(user_input[CONF_API_REGION]).strip().lower()
            scan_interval = int(user_input[CONF_SCAN_INTERVAL])

            if not client_id or not client_secret:
                errors["base"] = "invalid_credentials"
            elif not system_name:
                errors["base"] = "invalid_system_name"
            elif region not in (API_REGION_EU, API_REGION_CN):
                errors["base"] = "invalid_region"
            else:
                valid, err_key = await _validate_credentials(
                    self.hass,
                    client_id=client_id,
                    client_secret=client_secret,
                    region=region,
                )
                if not valid:
                    errors["base"] = err_key or "cannot_connect"

            if not errors:
                data = {
                    CONF_CLIENT_ID: client_id,
                    CONF_CLIENT_SECRET: client_secret,
                    CONF_SYSTEM_NAME: system_name,
                    CONF_SCAN_INTERVAL: scan_interval,
                    CONF_API_REGION: region,
                    CONF_ENTITY_PREFIX: _slugify_name(system_name),
                }
                return self.async_create_entry(title=system_name, data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_CLIENT_ID): str,
                vol.Required(CONF_CLIENT_SECRET): str,
                vol.Required(
                    CONF_SYSTEM_NAME,
                    default=translate(
                        self.hass,
                        "runtime.defaults.system_name",
                        fallback=DEFAULT_SYSTEM_NAME,
                    ),
                ): str,
                vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Required(
                    CONF_API_REGION,
                    default=API_REGION_DEFAULT,
                ): vol.In(
                    _region_options(self.hass)
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> FlowResult:
        """Start reauthentication after Home Assistant detects invalid credentials."""
        await async_ensure_catalog_loaded(self.hass)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Validate and store replacement Developer API credentials."""
        await async_ensure_catalog_loaded(self.hass)
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            client_id = str(user_input[CONF_CLIENT_ID]).strip()
            client_secret = str(user_input[CONF_CLIENT_SECRET]).strip()
            region = str(user_input[CONF_API_REGION]).strip().lower()
            if not client_id or not client_secret:
                errors["base"] = "invalid_credentials"
            elif region not in (API_REGION_EU, API_REGION_CN):
                errors["base"] = "invalid_region"
            else:
                valid, err_key = await _validate_credentials(
                    self.hass,
                    client_id=client_id,
                    client_secret=client_secret,
                    region=region,
                )
                if not valid:
                    errors["base"] = err_key or "cannot_connect"

            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_CLIENT_ID: client_id,
                        CONF_CLIENT_SECRET: client_secret,
                        CONF_API_REGION: region,
                    },
                    reason="reauth_successful",
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CLIENT_ID,
                        default=entry.data.get(CONF_CLIENT_ID, ""),
                    ): str,
                    vol.Required(CONF_CLIENT_SECRET): str,
                    vol.Required(
                        CONF_API_REGION,
                        default=entry.data.get(CONF_API_REGION, API_REGION_DEFAULT),
                    ): vol.In(_region_options(self.hass)),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return SolaxDeveloperOptionsFlowHandler(config_entry)


class SolaxDeveloperOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow for SolaX Developer API."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def _async_finish(
        self,
        *,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Persist a focused options page and reload the config entry."""
        updated_data = dict(self._config_entry.data if data is None else data)
        updated_options = dict(
            self._config_entry.options if options is None else options
        )
        self.hass.config_entries.async_update_entry(
            self._config_entry,
            data=updated_data,
            options=updated_options,
        )
        await self.hass.config_entries.async_reload(self._config_entry.entry_id)
        return self.async_create_entry(title="", data=updated_options)

    def _runtime_coordinator(self):
        runtime_entry = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        return (
            runtime_entry.get("coordinator")
            if isinstance(runtime_entry, dict)
            else None
        )

    def _manual_device_context(
        self,
    ) -> tuple[
        Any,
        list[dict[str, Any]],
        dict[str, str],
        list[dict[str, Any]],
        bool,
        dict[str, str],
    ]:
        current_options = dict(self._config_entry.options)
        coordinator = self._runtime_coordinator()
        current_manual_entries = _merge_manual_meter_entry_sources(
            current_options.get(CONF_MANUAL_METER_SERIALS)
        )
        current_manual_ems_entries = _coerce_manual_ems_entries(
            current_options.get(CONF_MANUAL_EMS_SYSTEMS)
        )
        runtime_plants = (
            (coordinator.data.get("plants") or {})
            if coordinator is not None
            else {}
        )
        has_ci_plant = any(
            int((plant or {}).get("businessType") or 0) == 4
            for plant in runtime_plants.values()
            if isinstance(plant, Mapping)
        )
        show_manual_ems_options = has_ci_plant or bool(current_manual_ems_entries)
        return (
            coordinator,
            current_manual_entries,
            _manual_meter_remove_options(self.hass, current_manual_entries),
            current_manual_ems_entries,
            show_manual_ems_options,
            _manual_ems_remove_options(self.hass, current_manual_ems_entries),
        )

    async def _validate_manual_meter_entries(
        self,
        entries: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str], str | None]:
        if not entries:
            return [], [], None

        runtime_entry = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        coordinator = runtime_entry.get("coordinator") if isinstance(runtime_entry, dict) else None
        if coordinator is None:
            return [], [], "manual_meter_serial_validation_unavailable"

        skipped_discovered: list[str] = []
        validated: list[dict[str, Any]] = []
        seen: set[str] = set()

        for entry in entries:
            requested_serial = str(entry.get("serial") or "").strip()
            if not requested_serial:
                continue
            existing_realtime_fields = entry.get("realtime_fields") or []
            normalized_existing_realtime_fields: list[str] = []
            if isinstance(existing_realtime_fields, (list, tuple)):
                normalized_existing_realtime_fields = sorted(
                    {
                        str(field).strip()
                        for field in existing_realtime_fields
                        if str(field).strip()
                    },
                    key=str.casefold,
                )

            known = coordinator.get_known_meter_serial(requested_serial)
            if known is not None:
                known_serial = str(known.get("serial") or requested_serial).strip()
                known_source = str(known.get("source") or "inventory")
                known_business_type = int(known.get("business_type") or 1)
                if known_source != "manual":
                    skipped_discovered.append(known_serial)
                    continue
                normalized_key = known_serial.casefold()
                if normalized_key in seen:
                    continue
                seen.add(normalized_key)
                if not normalized_existing_realtime_fields:
                    try:
                        known_probe = await coordinator.async_probe_manual_meter_serial(
                            known_serial
                        )
                    except Exception:  # noqa: BLE001
                        known_probe = {}
                    if bool(known_probe.get("ok")):
                        known_probe_summary = known_probe.get("field_summary") or {}
                        normalized_existing_realtime_fields = _probe_realtime_fields_from_summary(
                            known_probe_summary
                        )
                normalized_entry: dict[str, Any] = {
                    "serial": known_serial,
                    "business_type": known_business_type if known_business_type in (1, 4) else 1,
                    "source": "manual",
                }
                if normalized_existing_realtime_fields:
                    normalized_entry["realtime_fields"] = normalized_existing_realtime_fields
                validated.append(normalized_entry)
                continue

            probe = await coordinator.async_probe_manual_meter_serial(requested_serial)
            if not bool(probe.get("ok")):
                return [], skipped_discovered, "manual_meter_serial_validation_failed"

            resolved_serial = str(probe.get("serial_resolved") or requested_serial).strip()
            business_type = int(probe.get("business_type") or entry.get("business_type") or 1)
            if business_type not in (1, 4):
                business_type = 1
            probe_field_summary = probe.get("field_summary") or {}
            probe_realtime_fields = _probe_realtime_fields_from_summary(probe_field_summary)

            known_after_probe = coordinator.get_known_meter_serial(resolved_serial)
            if known_after_probe is not None and str(known_after_probe.get("source") or "inventory") != "manual":
                skipped_discovered.append(str(known_after_probe.get("serial") or resolved_serial))
                continue

            normalized_key = resolved_serial.casefold()
            if normalized_key in seen:
                continue
            seen.add(normalized_key)
            normalized_entry = {
                "serial": resolved_serial,
                "business_type": business_type,
                "source": "manual",
            }
            normalized_fields = probe_realtime_fields or normalized_existing_realtime_fields
            if normalized_fields:
                normalized_entry["realtime_fields"] = normalized_fields
            validated.append(normalized_entry)

        return validated, sorted(set(skipped_discovered), key=str.casefold), None

    async def _validate_manual_ems_entries(
        self,
        entries: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str], str | None]:
        if not entries:
            return [], [], None
        runtime_entry = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        coordinator = runtime_entry.get("coordinator") if isinstance(runtime_entry, dict) else None
        if coordinator is None:
            return [], [], "manual_ems_validation_unavailable"

        validated: list[dict[str, Any]] = []
        skipped_discovered: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            serial = str(entry.get("serial") or "").strip()
            plant_id = str(entry.get("plant_id") or "").strip()
            if not serial or not plant_id:
                continue
            known = coordinator.get_known_ems_serial(serial)
            if known is not None and str(known.get("source") or "") != "manual":
                skipped_discovered.append(str(known.get("serial") or serial))
                continue
            probe = await coordinator.async_probe_manual_ems_system(
                serial=serial,
                plant_id=plant_id,
            )
            if not bool(probe.get("ok")):
                return [], skipped_discovered, "manual_ems_validation_failed"
            resolved_serial = str(probe.get("serial_resolved") or serial).strip()
            resolved_plant_id = str(probe.get("plant_id") or plant_id).strip()
            if resolved_serial.casefold() in seen:
                continue
            seen.add(resolved_serial.casefold())
            validated.append(
                {
                    "serial": resolved_serial,
                    "plant_id": resolved_plant_id,
                    "business_type": 4,
                    "source": "manual",
                }
            )
        return validated, sorted(set(skipped_discovered), key=str.casefold), None

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Show the focused options menu."""
        await async_ensure_catalog_loaded(self.hass)
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "credentials",
                "polling",
                "manual_devices",
                "advanced",
            ],
        )

    async def async_step_credentials(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Update account credentials and system identity."""
        await async_ensure_catalog_loaded(self.hass)
        current_data = dict(self._config_entry.data)
        errors: dict[str, str] = {}

        if user_input is not None:
            client_id = str(user_input[CONF_CLIENT_ID]).strip()
            client_secret = str(user_input[CONF_CLIENT_SECRET]).strip()
            system_name = str(user_input[CONF_SYSTEM_NAME]).strip()
            region = str(user_input[CONF_API_REGION]).strip().lower()
            if not client_id or not client_secret:
                errors["base"] = "invalid_credentials"
            elif not system_name:
                errors["base"] = "invalid_system_name"
            elif region not in (API_REGION_EU, API_REGION_CN):
                errors["base"] = "invalid_region"
            else:
                credentials_changed = (
                    client_id != str(current_data.get(CONF_CLIENT_ID, ""))
                    or client_secret != str(current_data.get(CONF_CLIENT_SECRET, ""))
                    or region
                    != str(current_data.get(CONF_API_REGION, API_REGION_DEFAULT))
                )
                if credentials_changed:
                    valid, err_key = await _validate_credentials(
                        self.hass,
                        client_id=client_id,
                        client_secret=client_secret,
                        region=region,
                    )
                    if not valid:
                        errors["base"] = err_key or "cannot_connect"

            if not errors:
                current_data.update(
                    {
                        CONF_CLIENT_ID: client_id,
                        CONF_CLIENT_SECRET: client_secret,
                        CONF_SYSTEM_NAME: system_name,
                        CONF_API_REGION: region,
                    }
                )
                current_data.setdefault(
                    CONF_ENTITY_PREFIX,
                    _slugify_name(system_name),
                )
                return await self._async_finish(data=current_data)

        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CLIENT_ID,
                        default=current_data.get(CONF_CLIENT_ID, ""),
                    ): str,
                    vol.Required(
                        CONF_CLIENT_SECRET,
                        default=current_data.get(CONF_CLIENT_SECRET, ""),
                    ): str,
                    vol.Required(
                        CONF_SYSTEM_NAME,
                        default=current_data.get(
                            CONF_SYSTEM_NAME,
                            translate(
                                self.hass,
                                "runtime.defaults.system_name",
                                fallback=DEFAULT_SYSTEM_NAME,
                            ),
                        ),
                    ): str,
                    vol.Required(
                        CONF_API_REGION,
                        default=current_data.get(
                            CONF_API_REGION,
                            API_REGION_DEFAULT,
                        ),
                    ): vol.In(_region_options(self.hass)),
                }
            ),
            errors=errors,
        )

    async def async_step_polling(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Update standard, live-view, and night polling settings."""
        await async_ensure_catalog_loaded(self.hass)
        current_data = dict(self._config_entry.data)
        current_options = dict(self._config_entry.options)

        if user_input is not None:
            current_data[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            current_options.update(
                {
                    CONF_LIVE_VIEW_DEFAULT_DURATION: int(
                        user_input[CONF_LIVE_VIEW_DEFAULT_DURATION]
                    ),
                    CONF_LIVE_VIEW_INTERVAL: int(user_input[CONF_LIVE_VIEW_INTERVAL]),
                    CONF_LIVE_VIEW_CALL_BUDGET_PER_MINUTE: int(
                        user_input[CONF_LIVE_VIEW_CALL_BUDGET_PER_MINUTE]
                    ),
                    CONF_NIGHT_SCAN_INTERVAL: int(
                        user_input[CONF_NIGHT_SCAN_INTERVAL]
                    ),
                    CONF_NIGHT_START_HOUR: int(user_input[CONF_NIGHT_START_HOUR]),
                    CONF_NIGHT_END_HOUR: int(user_input[CONF_NIGHT_END_HOUR]),
                }
            )
            return await self._async_finish(
                data=current_data,
                options=current_options,
            )

        return self.async_show_form(
            step_id="polling",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=current_data.get(
                            CONF_SCAN_INTERVAL,
                            DEFAULT_SCAN_INTERVAL,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                    vol.Required(
                        CONF_LIVE_VIEW_DEFAULT_DURATION,
                        default=current_options.get(
                            CONF_LIVE_VIEW_DEFAULT_DURATION,
                            DEFAULT_LIVE_VIEW_DEFAULT_DURATION,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_LIVE_VIEW_DURATION,
                            max=MAX_LIVE_VIEW_DURATION,
                        ),
                    ),
                    vol.Required(
                        CONF_LIVE_VIEW_INTERVAL,
                        default=current_options.get(
                            CONF_LIVE_VIEW_INTERVAL,
                            DEFAULT_LIVE_VIEW_INTERVAL,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_LIVE_VIEW_INTERVAL,
                            max=MAX_LIVE_VIEW_INTERVAL,
                        ),
                    ),
                    vol.Required(
                        CONF_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
                        default=current_options.get(
                            CONF_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
                            DEFAULT_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
                            max=MAX_LIVE_VIEW_CALL_BUDGET_PER_MINUTE,
                        ),
                    ),
                    vol.Required(
                        CONF_NIGHT_SCAN_INTERVAL,
                        default=current_options.get(
                            CONF_NIGHT_SCAN_INTERVAL,
                            DEFAULT_NIGHT_SCAN_INTERVAL,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_NIGHT_SCAN_INTERVAL,
                            max=MAX_NIGHT_SCAN_INTERVAL,
                        ),
                    ),
                    vol.Required(
                        CONF_NIGHT_START_HOUR,
                        default=current_options.get(
                            CONF_NIGHT_START_HOUR,
                            DEFAULT_NIGHT_START_HOUR,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
                    vol.Required(
                        CONF_NIGHT_END_HOUR,
                        default=current_options.get(
                            CONF_NIGHT_END_HOUR,
                            DEFAULT_NIGHT_END_HOUR,
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
                }
            ),
        )

    async def async_step_manual_devices(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Add or remove manually validated meters and EMS systems."""
        await async_ensure_catalog_loaded(self.hass)
        (
            _coordinator,
            current_manual_entries,
            remove_options,
            current_manual_ems_entries,
            show_manual_ems_options,
            ems_remove_options,
        ) = self._manual_device_context()
        current_options = dict(self._config_entry.options)
        errors: dict[str, str] = {}

        if user_input is not None:
            meter_add_text = str(
                user_input.get(CONF_MANUAL_METER_SERIALS_ADD, "")
            ).strip()
            meter_remove_serial = str(
                user_input.get(
                    CONF_MANUAL_METER_REMOVE_SERIAL,
                    MANUAL_METER_REMOVE_NONE,
                )
            ).strip()
            meter_remove_confirm = bool(
                user_input.get(CONF_MANUAL_METER_REMOVE_CONFIRM, False)
            )
            ems_add_text = (
                str(user_input.get(CONF_MANUAL_EMS_SYSTEMS_ADD, "")).strip()
                if show_manual_ems_options
                else ""
            )
            ems_remove_serial = (
                str(
                    user_input.get(
                        CONF_MANUAL_EMS_REMOVE_SERIAL,
                        MANUAL_EMS_REMOVE_NONE,
                    )
                ).strip()
                if show_manual_ems_options
                else MANUAL_EMS_REMOVE_NONE
            )
            ems_remove_confirm = bool(
                user_input.get(CONF_MANUAL_EMS_REMOVE_CONFIRM, False)
            )

            parsed_meters, meter_parse_error = _parse_manual_meter_entries_text(
                meter_add_text
            )
            parsed_ems, ems_parse_error = _parse_manual_ems_entries_text(
                ems_add_text
            )
            working_meters = [dict(item) for item in current_manual_entries]
            working_ems = [dict(item) for item in current_manual_ems_entries]
            removed_meters: list[str] = []
            removed_ems: list[str] = []

            if meter_parse_error:
                errors[CONF_MANUAL_METER_SERIALS_ADD] = meter_parse_error
            if show_manual_ems_options and ems_parse_error:
                errors[CONF_MANUAL_EMS_SYSTEMS_ADD] = ems_parse_error

            if meter_remove_confirm:
                if meter_remove_serial == MANUAL_METER_REMOVE_NONE:
                    errors[CONF_MANUAL_METER_REMOVE_SERIAL] = (
                        "manual_meter_remove_target_required"
                    )
                else:
                    before = len(working_meters)
                    working_meters = [
                        item
                        for item in working_meters
                        if str(item.get("serial") or "").strip().casefold()
                        != meter_remove_serial.casefold()
                    ]
                    if len(working_meters) == before:
                        errors[CONF_MANUAL_METER_REMOVE_SERIAL] = (
                            "manual_meter_remove_target_missing"
                        )
                    else:
                        removed_meters.append(meter_remove_serial)

            if show_manual_ems_options and ems_remove_confirm:
                if ems_remove_serial == MANUAL_EMS_REMOVE_NONE:
                    errors[CONF_MANUAL_EMS_REMOVE_SERIAL] = (
                        "manual_ems_remove_target_required"
                    )
                else:
                    before = len(working_ems)
                    working_ems = [
                        item
                        for item in working_ems
                        if str(item.get("serial") or "").strip().casefold()
                        != ems_remove_serial.casefold()
                    ]
                    if len(working_ems) == before:
                        errors[CONF_MANUAL_EMS_REMOVE_SERIAL] = (
                            "manual_ems_remove_target_missing"
                        )
                    else:
                        removed_ems.append(ems_remove_serial)

            if not errors:
                working_meters = _merge_manual_meter_entry_sources(
                    working_meters,
                    parsed_meters,
                )
                working_ems = _coerce_manual_ems_entries([*working_ems, *parsed_ems])

                (
                    validated_meters,
                    skipped_meters,
                    meter_validation_error,
                ) = await self._validate_manual_meter_entries(working_meters)
                if meter_validation_error:
                    errors[CONF_MANUAL_METER_SERIALS_ADD] = meter_validation_error

            if not errors and show_manual_ems_options:
                (
                    validated_ems,
                    skipped_ems,
                    ems_validation_error,
                ) = await self._validate_manual_ems_entries(working_ems)
                if ems_validation_error:
                    errors[CONF_MANUAL_EMS_SYSTEMS_ADD] = ems_validation_error
            else:
                validated_ems = current_manual_ems_entries
                skipped_ems = []

            if not errors:
                current_options[CONF_MANUAL_METER_SERIALS] = validated_meters
                current_options[CONF_MANUAL_EMS_SYSTEMS] = validated_ems
                self._notify_manual_device_result(
                    skipped_meters=skipped_meters,
                    removed_meters=removed_meters,
                    skipped_ems=skipped_ems,
                    removed_ems=removed_ems,
                )
                return await self._async_finish(options=current_options)

        schema_fields: dict[Any, Any] = {
            vol.Optional(CONF_MANUAL_METER_SERIALS_ADD, default=""): str,
            vol.Required(
                CONF_MANUAL_METER_REMOVE_SERIAL,
                default=MANUAL_METER_REMOVE_NONE,
            ): vol.In(remove_options),
            vol.Required(
                CONF_MANUAL_METER_REMOVE_CONFIRM,
                default=False,
            ): bool,
        }
        if show_manual_ems_options:
            schema_fields.update(
                {
                    vol.Optional(CONF_MANUAL_EMS_SYSTEMS_ADD, default=""): str,
                    vol.Required(
                        CONF_MANUAL_EMS_REMOVE_SERIAL,
                        default=MANUAL_EMS_REMOVE_NONE,
                    ): vol.In(ems_remove_options),
                    vol.Required(
                        CONF_MANUAL_EMS_REMOVE_CONFIRM,
                        default=False,
                    ): bool,
                }
            )
        return self.async_show_form(
            step_id="manual_devices",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
        )

    def _notify_manual_device_result(
        self,
        *,
        skipped_meters: list[str],
        removed_meters: list[str],
        skipped_ems: list[str],
        removed_ems: list[str],
    ) -> None:
        if skipped_meters or removed_meters:
            persistent_notification.async_create(
                self.hass,
                translate(
                    self.hass,
                    "runtime.notifications.manual_meter_options_result_body",
                    placeholders={
                        "skipped_serials": ", ".join(skipped_meters) or "-",
                        "removed_serials": ", ".join(removed_meters) or "-",
                    },
                    fallback=(
                        "Manual meter settings saved.\n"
                        "Skipped (already auto-discovered): {skipped_serials}\n"
                        "Removed: {removed_serials}"
                    ),
                ),
                title=translate(
                    self.hass,
                    "runtime.notifications.manual_meter_title",
                    fallback="SolaX Developer API - Manual Meter Serials",
                ),
                notification_id=_manual_meter_notification_id(
                    self._config_entry.entry_id
                ),
            )
        else:
            persistent_notification.async_dismiss(
                self.hass,
                _manual_meter_notification_id(self._config_entry.entry_id),
            )

        if skipped_ems or removed_ems:
            persistent_notification.async_create(
                self.hass,
                translate(
                    self.hass,
                    "runtime.notifications.manual_ems_options_result_body",
                    placeholders={
                        "skipped_serials": ", ".join(skipped_ems) or "-",
                        "removed_serials": ", ".join(removed_ems) or "-",
                    },
                    fallback=(
                        "Manual EMS settings saved.\n"
                        "Skipped (already auto-discovered): {skipped_serials}\n"
                        "Removed: {removed_serials}"
                    ),
                ),
                title=translate(
                    self.hass,
                    "runtime.notifications.manual_ems_title",
                    fallback="SolaX Developer API - Manual EMS Systems",
                ),
                notification_id=_manual_ems_notification_id(
                    self._config_entry.entry_id
                ),
            )
        else:
            persistent_notification.async_dismiss(
                self.hass,
                _manual_ems_notification_id(self._config_entry.entry_id),
            )

    async def async_step_advanced(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Update advanced diagnostics and notification behavior."""
        await async_ensure_catalog_loaded(self.hass)
        current_options = dict(self._config_entry.options)
        if user_input is not None:
            current_options[CONF_RATE_LIMIT_NOTIFICATIONS] = bool(
                user_input[CONF_RATE_LIMIT_NOTIFICATIONS]
            )
            return await self._async_finish(options=current_options)

        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RATE_LIMIT_NOTIFICATIONS,
                        default=current_options.get(
                            CONF_RATE_LIMIT_NOTIFICATIONS,
                            True,
                        ),
                    ): bool,
                }
            ),
        )
