"""Sensor platform for SolaX Developer API."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util, slugify

from .i18n import translate
from .const import (
    BATTERY_STATUS_MAP,
    BATTERY_STATUS_MAP_BY_BUSINESS,
    COMMAND_STATUS_MAP,
    DEVICE_MODEL_MAP,
    DEVICE_MODEL_MAP_BY_CONTEXT,
    DEVICE_TYPE_NAMES,
    DEVICE_WORK_MODE_MAP,
    DOMAIN,
    EV_STATUS_MAP,
    INVERTER_STATUS_MAP,
)
from .entity import system_device_info, system_identity
from .statistics import extract_plant_stat_metrics

PARALLEL_UPDATES = 0

CORE_PLANT_INFO_KEYS = {"plantState", "plantTimeZone", "electricityPriceUnit"}
CORE_DEVICE_INFO_KEYS = {"onlineStatus", "flag", "deviceModel"}


def _t(hass, key: str, *, placeholders: dict[str, Any] | None = None, fallback: str | None = None) -> str:
    return translate(hass, key, placeholders=placeholders, fallback=fallback)


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


def _snake(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value)
    return value.lower().strip("_")


def _humanize_key(key: str) -> str:
    if key.startswith("mpptMap_"):
        nested = _humanize_key(key[len("mpptMap_") :])
        if nested.startswith("MPPT "):
            return nested
        return f"MPPT {nested}"
    if key.startswith("pvMap_"):
        nested = _humanize_key(key[len("pvMap_") :])
        if nested.startswith("PV "):
            return nested
        return f"PV {nested}"

    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"(?i)l([123])l([123])", r"L\1-L\2", text)
    text = re.sub(r"(?i)\bl([123])\s+l([123])\b", r"L\1-L\2", text)
    text = text.replace("_", " ")

    words = []
    for raw_word in text.split():
        word = raw_word.strip()
        if not word:
            continue
        lowered = word.casefold()
        if lowered in {"ac", "dc", "eps", "soc", "mppt", "pv", "utc", "rfid"}:
            words.append(word.upper())
        elif re.fullmatch(r"l[123]-l[123]", lowered):
            words.append(f"L{lowered[1]}-L{lowered[-1]}")
        elif re.fullmatch(r"l[123]", lowered):
            words.append(word.upper())
        elif re.fullmatch(r"epsl[123]", lowered):
            words.append(f"EPS L{lowered[-1]}")
        elif re.fullmatch(r"mppt[0-9]+", lowered):
            words.append(f"MPPT {lowered[4:]}")
        elif re.fullmatch(r"pv[0-9]+", lowered):
            words.append(f"PV {lowered[2:]}")
        else:
            words.append(word.capitalize())

    return " ".join(words)


def _field_kind(key: str) -> str | None:
    lowered = key.casefold()
    if "powerfactor" in lowered:
        return "factor"
    if "reactivepower" in lowered:
        return "reactive_power"
    if "apparentpower" in lowered:
        return "apparent_power"
    if "power" in lowered:
        return "power"
    if (
        "yield" in lowered
        or "energy" in lowered
        or "charged" in lowered
        or "discharged" in lowered
        or lowered.endswith("batterycapacity")
        or lowered.endswith("batteryremainings")
    ):
        return "energy"
    if "soc" in lowered or lowered.endswith("batterysoh"):
        return "battery_percent"
    if "temperature" in lowered:
        return "temperature"
    if "frequency" in lowered:
        return "frequency"
    if "voltage" in lowered:
        return "voltage"
    if "current" in lowered:
        return "current"
    if "time" in lowered:
        return "time"
    if "earnings" in lowered:
        return "earnings"
    return None


def _device_sensor_unique_suffix(*, field_slug: str, device_sn: str, info: bool = False) -> str:
    serial_slug = slugify(device_sn)
    if info:
        return f"{field_slug}_info_device_{serial_slug}"
    return f"{field_slug}_device_{serial_slug}"


def _device_field_display_name(hass, *, device_type: int, field_name: str) -> str:
    if int(device_type) == 1:
        return _t(
            hass,
            "runtime.entity_templates.device_field_inverter",
            placeholders={"field_name": field_name},
            fallback="{field_name}",
        )
    if int(device_type) == 100 and field_name.startswith("Sys "):
        field_name = field_name[4:]
    return _t(
        hass,
        "runtime.entity_templates.device_field",
        placeholders={
            "device_type": _device_type_text(hass, device_type),
            "field_name": field_name,
        },
        fallback="{device_type} {field_name}",
    )


def _device_info_display_name(hass, *, device_type: int, key_name: str) -> str:
    if int(device_type) == 1:
        return _t(
            hass,
            "runtime.entity_templates.device_info_inverter",
            placeholders={"key_name": key_name},
            fallback="{key_name}",
        )
    if int(device_type) == 100 and key_name.startswith("Sys "):
        key_name = key_name[4:]
    return _t(
        hass,
        "runtime.entity_templates.device_info",
        placeholders={
            "device_type": _device_type_text(hass, device_type),
            "key_name": key_name,
        },
        fallback="{device_type} {key_name}",
    )


def _energy_state_class(key: str) -> SensorStateClass:
    lowered = key.casefold()
    if any(
        marker in lowered
        for marker in (
            "daily",
            "today",
            "thissession",
            "this_session",
            "capacity",
            "remainings",
        )
    ):
        return SensorStateClass.TOTAL
    return SensorStateClass.TOTAL_INCREASING


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_numeric_value(key: str, value: Any, business_type: int) -> Any:
    kind = _field_kind(key)
    if kind is None:
        return value
    if kind in {"time", "earnings"}:
        return value

    num = _safe_float(value)
    if num is None:
        return value

    # Developer API docs: C&I businessType=4 uses kW/kVar/kVA for power fields.
    if business_type == 4 and kind in {"power", "reactive_power", "apparent_power"}:
        num = num * 1000.0

    return round(num, 3)


def _status_text(
    hass,
    device_type: int,
    business_type: int,
    key: str,
    value: Any,
) -> str | Any:
    if value is None:
        return None
    try:
        int_val = int(value)
    except Exception:
        return value

    if key == "deviceStatus":
        if device_type == 1:
            mapped = INVERTER_STATUS_MAP.get(int_val)
            if mapped is None:
                return str(value)
            return _t(
                hass,
                f"runtime.status.inverter.{int_val}",
                fallback=str(mapped),
            )
        if device_type == 2:
            mapped = (
                BATTERY_STATUS_MAP_BY_BUSINESS.get(int(business_type), {}).get(int_val)
                or BATTERY_STATUS_MAP.get(int_val)
            )
            if mapped is None:
                return str(value)
            return _t(
                hass,
                f"runtime.status.battery_{'ci' if int(business_type) == 4 else 'residential'}.{int_val}",
                fallback=str(mapped),
            )
        if device_type == 4:
            mapped = EV_STATUS_MAP.get(int_val)
            if mapped is None:
                return str(value)
            return _t(
                hass,
                f"runtime.status.ev.{int_val}",
                fallback=str(mapped),
            )
    if key == "deviceWorkingMode":
        mapped = DEVICE_WORK_MODE_MAP.get(int_val)
        if mapped is None:
            return str(value)
        return _t(
            hass,
            f"runtime.status.device_work_mode.{int_val}",
            fallback=str(mapped),
        )
    if key == "deviceModel":
        return _device_model_text(
            hass,
            int_val,
            business_type=business_type,
            device_type=device_type,
        )
    if key == "status":
        mapped = COMMAND_STATUS_MAP.get(int_val)
        if mapped is None:
            return str(value)
        return _t(
            hass,
            f"runtime.status.command.{int_val}",
            fallback=str(mapped),
        )
    return value


def _infer_unit_and_classes(
    key: str,
) -> tuple[str | None, SensorDeviceClass | None, SensorStateClass | None]:
    kind = _field_kind(key)
    if kind == "battery_percent":
        return "%", SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT
    if kind == "temperature":
        return "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT
    if kind == "frequency":
        return "Hz", SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT
    if kind == "voltage":
        return "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT
    if kind == "current":
        return "A", SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT
    if kind == "power":
        return "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT
    if kind == "reactive_power":
        return "var", None, SensorStateClass.MEASUREMENT
    if kind == "apparent_power":
        return "VA", None, SensorStateClass.MEASUREMENT
    if kind == "energy":
        return "kWh", SensorDeviceClass.ENERGY, _energy_state_class(key)
    if kind == "factor":
        return None, None, SensorStateClass.MEASUREMENT

    return None, None, None


def _device_model_text(
    hass,
    value: Any,
    *,
    business_type: Any = None,
    device_type: Any = None,
) -> Any:
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
        return _t(
            hass,
            f"runtime.device_model.context.{context_key[0]}.{context_key[1]}.{model_id}",
            fallback=fallback,
        )
    return _t(hass, f"runtime.device_model.code.{model_id}", fallback=fallback)


def _device_type_text(hass, value: Any) -> str:
    try:
        device_type = int(value)
    except (TypeError, ValueError):
        return _t(hass, "runtime.labels.device", fallback="Device")
    fallback = DEVICE_TYPE_NAMES.get(device_type, _t(hass, "runtime.labels.device", fallback="Device"))
    return _t(hass, f"runtime.labels.device_type.{device_type}", fallback=fallback)


def _business_type_text(hass, value: Any) -> str:
    try:
        business_type = int(value)
    except (TypeError, ValueError):
        return _t(hass, "runtime.labels.unknown", fallback="Unknown")
    fallback = str(business_type)
    return _t(hass, f"runtime.labels.business_type.{business_type}", fallback=fallback)


def _plant_state_text(hass, business_type: int, value: Any) -> Any:
    try:
        state = int(value)
    except (TypeError, ValueError):
        return value
    if business_type == 4:
        return _t(
            hass,
            f"runtime.status.plant_ci.{state}",
            fallback=str(value),
        )
    if state == 0:
        return _t(hass, "runtime.status.plant_residential.0", fallback="Connecting")
    if state == 1:
        return _t(hass, "runtime.status.plant_residential.1", fallback="Offline")
    return _t(hass, "runtime.status.plant_residential.2", fallback="Online")


def _online_status_text(hass, value: Any) -> Any:
    try:
        status = int(value)
    except (TypeError, ValueError):
        return value
    if status == 1:
        return _t(hass, "runtime.status.online.1", fallback="Online")
    return _t(hass, "runtime.status.online.0", fallback="Offline")


def _parallel_flag_text(hass, business_type: int, value: Any) -> Any:
    try:
        flag = int(value)
    except (TypeError, ValueError):
        return value

    if business_type == 4:
        return _t(
            hass,
            f"runtime.status.parallel_ci.{flag}",
            fallback=str(value),
        )

    return _t(
        hass,
        f"runtime.status.parallel_residential.{flag}",
        fallback=str(value),
    )


def _extract_stat_metrics(stat_payload: dict[str, Any] | None) -> dict[str, float]:
    return extract_plant_stat_metrics(stat_payload)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensors for a config entry."""
    coordinator = entry.runtime_data.coordinator
    system_name, system_slug = system_identity(hass, entry)

    entities: list[SensorEntity] = []
    created: set[tuple[str, str, str]] = set()
    entity_registry = er.async_get(hass)

    def _maybe_auto_enable_entity(entity: SensorEntity) -> None:
        unique_id = entity.unique_id
        if not unique_id:
            return
        entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if not entity_id:
            return
        registry_entry = entity_registry.async_get(entity_id)
        if (
            registry_entry is None
            or registry_entry.disabled_by != er.RegistryEntryDisabler.INTEGRATION
        ):
            return
        entity_registry.async_update_entity(entity_id, disabled_by=None)

    for key in (
        "system_ac_power",
        "system_dc_power",
        "system_yield_today",
        "system_yield_total",
        "system_efficiency",
        "system_health",
        "api_rate_limit_status",
        "poll_profile",
        "effective_scan_interval",
        "live_view_active",
        "live_view_remaining_seconds",
        "last_poll_attempt",
        "next_scheduled_poll",
        "token_expires_at",
        "dry_run_command_count",
    ):
        entities.append(
            SolaxSystemSensor(
                coordinator,
                key,
                system_name,
                system_slug,
            )
        )

    def _build_dynamic() -> list[SensorEntity]:
        new_entities: list[SensorEntity] = []
        state = coordinator.data or {}

        plants = state.get("plants") or {}
        plant_realtime = state.get("plant_realtime") or {}
        plant_stats = state.get("plant_stats") or {}
        alarms = state.get("alarms") or {}
        devices = state.get("devices") or {}
        device_realtime = state.get("device_realtime") or {}
        capability_field_catalog: dict[str, set[str]] = {
            str(serial_key).casefold(): {str(field).strip() for field in fields if str(field).strip()}
            for serial_key, fields in coordinator.device_capability_fields.items()
            if str(serial_key).strip()
        }

        for plant_id, plant_data in plant_realtime.items():
            flat = _flatten_dict(plant_data)
            for field_key, value in flat.items():
                if value is None:
                    continue
                token = ("plant", plant_id, field_key)
                if token in created:
                    continue
                created.add(token)
                new_entities.append(
                    SolaxPlantFieldSensor(
                        coordinator,
                        system_slug,
                        plant_id,
                        field_key,
                    )
                )

            alarm_token = ("plant_alarm", plant_id, "active_alarm_count")
            if alarm_token not in created:
                created.add(alarm_token)
                new_entities.append(
                    SolaxPlantAlarmCountSensor(
                        coordinator,
                        system_slug,
                        plant_id,
                    )
                )

            # Year/month stat summary sensors.
            for period in ("year", "month"):
                metrics = _extract_stat_metrics((plant_stats.get(plant_id) or {}).get(period))
                for metric_name, metric_val in metrics.items():
                    if metric_val is None:
                        continue
                    token = (f"plant_stat_{period}", plant_id, metric_name)
                    if token in created:
                        continue
                    created.add(token)
                    new_entities.append(
                        SolaxPlantStatSensor(
                            coordinator,
                            system_slug,
                            plant_id,
                            period,
                            metric_name,
                        )
                    )

            # Plant info fields as diagnostics.
            plant_inventory = plants.get(plant_id) or {}
            for field_key, value in plant_inventory.items():
                if value is None:
                    continue
                if field_key in {"plantId", "plantName"}:
                    continue
                token = ("plant_info", plant_id, field_key)
                if token in created:
                    continue
                created.add(token)
                new_entities.append(
                    SolaxPlantInfoSensor(
                        coordinator,
                        system_slug,
                        plant_id,
                        field_key,
                    )
                )

            if plant_id in alarms and isinstance(alarms[plant_id], dict):
                records = alarms[plant_id].get("records") or []
                for idx, alarm in enumerate(records[:3]):
                    if not isinstance(alarm, dict):
                        continue
                    for alarm_key in ("alarmName", "errorCode", "alarmType"):
                        if alarm.get(alarm_key) is None:
                            continue
                        token = ("alarm_preview", f"{plant_id}_{idx}", alarm_key)
                        if token in created:
                            continue
                        created.add(token)
                        new_entities.append(
                            SolaxPlantAlarmPreviewSensor(
                                coordinator,
                                system_slug,
                                plant_id,
                                idx,
                                alarm_key,
                            )
                        )

        device_field_candidates: dict[str, dict[str, bool]] = {}
        for sn, realtime_data in device_realtime.items():
            serial = str(sn).strip()
            if not serial:
                continue
            serial_key = serial.casefold()
            flat = _flatten_dict(realtime_data) if isinstance(realtime_data, dict) else {}
            candidate_fields: dict[str, bool] = {}
            for field_key, value in flat.items():
                if value is None:
                    continue
                candidate_fields[str(field_key)] = True
            capability_seed_fields = capability_field_catalog.get(serial_key, set())

            if capability_seed_fields:
                for field_key in capability_seed_fields:
                    candidate_fields.setdefault(str(field_key), False)
            if candidate_fields:
                device_field_candidates[serial] = candidate_fields

        for serial in devices:
            serial_str = str(serial).strip()
            if not serial_str:
                continue
            serial_key = serial_str.casefold()
            if serial_str in device_field_candidates:
                continue
            capability_seed_fields = set(capability_field_catalog.get(serial_key, set()))
            seed_fields = capability_seed_fields
            if seed_fields:
                device_field_candidates[serial_str] = {
                    str(field_key): False for field_key in seed_fields
                }

        for sn in sorted(device_field_candidates.keys(), key=str.casefold):
            realtime_data = device_realtime.get(sn) or {}
            inventory_data = devices.get(sn) or {}
            device_type = None
            if isinstance(realtime_data, dict):
                device_type = realtime_data.get("deviceType")
            if device_type is None and isinstance(inventory_data, dict):
                device_type = inventory_data.get("deviceType")

            for field_key in sorted(device_field_candidates[sn].keys(), key=str.casefold):
                token = ("device", sn, field_key)
                if token in created:
                    continue
                created.add(token)
                has_live_value = bool(device_field_candidates[sn].get(field_key, False))
                new_entity = SolaxDeviceFieldSensor(
                    coordinator,
                    system_slug,
                    sn,
                    device_type,
                    field_key,
                    enabled_by_default=has_live_value,
                )
                if has_live_value:
                    _maybe_auto_enable_entity(new_entity)
                new_entities.append(new_entity)

        # Build inventory diagnostics from full device inventory, even when realtime is unavailable.
        for sn, device_inventory in devices.items():
            for field_key, value in device_inventory.items():
                if value is None:
                    continue
                if field_key in {"deviceSn"}:
                    continue
                token = ("device_info", sn, field_key)
                if token in created:
                    continue
                created.add(token)
                new_entities.append(
                    SolaxDeviceInfoSensor(
                        coordinator,
                        system_slug,
                        sn,
                        device_inventory.get("deviceType"),
                        field_key,
                    )
                )

        return new_entities

    entities.extend(_build_dynamic())

    async_add_entities(entities, update_before_add=True)

    def _coordinator_updated() -> None:
        additions = _build_dynamic()
        if additions:
            async_add_entities(additions, update_before_add=True)

    entry.async_on_unload(coordinator.async_add_listener(_coordinator_updated))


class SolaxBaseSensor(CoordinatorEntity, SensorEntity):
    """Common base for all SolaX sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, system_slug: str, unique_suffix: str, name: str) -> None:
        super().__init__(coordinator)
        self._system_slug = system_slug
        self._attr_unique_id = f"{system_slug}_{unique_suffix}".lower()
        self.entity_id = f"sensor.{self._attr_unique_id}"
        self._attr_translation_key = "dynamic_field"
        self._attr_translation_placeholders = {"field_name": name}


class SolaxSystemSensor(SolaxBaseSensor):
    """System total / diagnostic sensors."""

    def __init__(self, coordinator, key: str, system_name: str, system_slug: str) -> None:
        self._key = key
        self._system_name = system_name

        super().__init__(
            coordinator,
            system_slug,
            f"{key}_solax",
            _t(
                coordinator.hass,
                f"runtime.entity_names.system.{key}",
                fallback=_humanize_key(key),
            ),
        )

        if key in ("system_ac_power", "system_dc_power"):
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = "W"
        elif key in ("system_yield_today", "system_yield_total"):
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
            self._attr_native_unit_of_measurement = "kWh"
        elif key == "system_efficiency":
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = "%"
        elif key in (
            "last_poll_attempt",
            "next_scheduled_poll",
            "token_expires_at",
        ):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            if key in ("last_poll_attempt", "next_scheduled_poll"):
                self._attr_entity_registry_enabled_default = False
        elif key in (
            "system_health",
            "api_rate_limit_status",
            "dry_run_command_count",
            "poll_profile",
            "live_view_active",
            "live_view_remaining_seconds",
            "effective_scan_interval",
        ):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            if key in (
                "live_view_remaining_seconds",
                "effective_scan_interval",
            ):
                self._attr_state_class = SensorStateClass.MEASUREMENT
                self._attr_native_unit_of_measurement = "s"

    @property
    def device_info(self):
        return system_device_info(
            self.coordinator.hass,
            self.coordinator,
            self._system_name,
            self._system_slug,
        )

    @staticmethod
    def _sort_strings(values: list[str]) -> list[str]:
        return sorted(values, key=lambda item: str(item).casefold())

    def _device_type_int(self, serial: str, payload: dict[str, Any] | None = None) -> int:
        value = None
        if isinstance(payload, dict):
            value = payload.get("deviceType")
        if value is None:
            inventory = (self.coordinator.data.get("devices") or {}).get(serial) or {}
            value = inventory.get("deviceType")
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _system_ac_breakdown(self) -> dict[str, Any]:
        total = 0.0
        included_serials: list[str] = []
        missing_inverter_realtime_serials: list[str] = []
        per_device_power_w: dict[str, float] = {}
        per_device_source_field: dict[str, str] = {}
        excluded_non_inverter_devices: dict[str, dict[str, Any]] = {}

        data = self.coordinator.data or {}
        devices = data.get("devices") or {}
        device_rt = data.get("device_realtime") or {}

        for sn, payload in device_rt.items():
            if not isinstance(payload, dict):
                continue
            serial = str(sn).strip()
            if not serial:
                continue

            device_type = self._device_type_int(serial, payload)
            if device_type != 1:
                excluded_non_inverter_devices[serial] = {
                    "device_type": device_type,
                    "device_type_name": _device_type_text(self.coordinator.hass, device_type),
                }
                continue

            included_serials.append(serial)
            business_type = int((payload or {}).get("businessType") or 1)

            ac_value = payload.get("totalActivePower")
            source_field = "totalActivePower"
            if ac_value is None:
                source_field = "acPower1+acPower2+acPower3"
                ac_value = sum(
                    _safe_float(
                        _normalize_numeric_value(k, payload.get(k), business_type)
                    )
                    or 0.0
                    for k in ("acPower1", "acPower2", "acPower3")
                )
            else:
                ac_value = _normalize_numeric_value(
                    "totalActivePower", ac_value, business_type
                )

            numeric_value = _safe_float(ac_value)
            if numeric_value is None:
                numeric_value = 0.0
                source_field = "missing->0"
            total += numeric_value
            per_device_power_w[serial] = round(numeric_value, 3)
            per_device_source_field[serial] = source_field

        included_lookup = {sn.casefold() for sn in included_serials}
        for sn, inventory in devices.items():
            serial = str(sn).strip()
            if not serial:
                continue
            try:
                inventory_type = int((inventory or {}).get("deviceType") or 0)
            except (TypeError, ValueError):
                inventory_type = 0
            if inventory_type != 1:
                continue
            if serial.casefold() not in included_lookup:
                missing_inverter_realtime_serials.append(serial)

        sorted_included = self._sort_strings(included_serials)
        sorted_missing = self._sort_strings(missing_inverter_realtime_serials)
        sorted_excluded_serials = self._sort_strings(list(excluded_non_inverter_devices.keys()))
        sorted_excluded = {
            serial: excluded_non_inverter_devices[serial]
            for serial in sorted_excluded_serials
        }
        sorted_power = {
            serial: per_device_power_w[serial]
            for serial in self._sort_strings(list(per_device_power_w.keys()))
        }
        sorted_sources = {
            serial: per_device_source_field[serial]
            for serial in self._sort_strings(list(per_device_source_field.keys()))
        }

        return {
            "total_w": round(total, 3),
            "included_device_serials": sorted_included,
            "included_device_count": len(sorted_included),
            "included_device_type": 1,
            "included_device_type_name": _device_type_text(self.coordinator.hass, 1),
            "missing_inverter_realtime_serials": sorted_missing,
            "excluded_non_inverter_serials": sorted_excluded_serials,
            "excluded_non_inverter_devices": sorted_excluded,
            "per_device_power_w": sorted_power,
            "per_device_source_field": sorted_sources,
        }

    def _system_dc_breakdown(self) -> dict[str, Any]:
        total = 0.0
        included_serials: list[str] = []
        missing_inverter_realtime_serials: list[str] = []
        per_device_power_w: dict[str, float] = {}
        per_device_source_field: dict[str, str] = {}
        excluded_non_inverter_devices: dict[str, dict[str, Any]] = {}

        data = self.coordinator.data or {}
        devices = data.get("devices") or {}
        device_rt = data.get("device_realtime") or {}

        for sn, payload in device_rt.items():
            if not isinstance(payload, dict):
                continue
            serial = str(sn).strip()
            if not serial:
                continue

            device_type = self._device_type_int(serial, payload)
            if device_type != 1:
                excluded_non_inverter_devices[serial] = {
                    "device_type": device_type,
                    "device_type_name": _device_type_text(self.coordinator.hass, device_type),
                }
                continue

            included_serials.append(serial)
            business_type = int((payload or {}).get("businessType") or 1)
            device_total = 0.0
            source_field = "missing->0"

            direct = payload.get("MPPTTotalInputPower")
            if direct is not None:
                normalized_direct = _normalize_numeric_value(
                    "MPPTTotalInputPower", direct, business_type
                )
                device_total = _safe_float(normalized_direct) or 0.0
                source_field = "MPPTTotalInputPower"
            else:
                mppt_map = payload.get("mpptMap") or {}
                mppt_keys: list[str] = []
                if isinstance(mppt_map, dict):
                    for key, value in mppt_map.items():
                        if not str(key).endswith("Power"):
                            continue
                        normalized_val = _normalize_numeric_value(
                            str(key), value, business_type
                        )
                        device_total += _safe_float(normalized_val) or 0.0
                        mppt_keys.append(str(key))
                if mppt_keys:
                    source_field = "mpptMap:" + ",".join(
                        self._sort_strings(mppt_keys)
                    )

            total += device_total
            per_device_power_w[serial] = round(device_total, 3)
            per_device_source_field[serial] = source_field

        included_lookup = {sn.casefold() for sn in included_serials}
        for sn, inventory in devices.items():
            serial = str(sn).strip()
            if not serial:
                continue
            try:
                inventory_type = int((inventory or {}).get("deviceType") or 0)
            except (TypeError, ValueError):
                inventory_type = 0
            if inventory_type != 1:
                continue
            if serial.casefold() not in included_lookup:
                missing_inverter_realtime_serials.append(serial)

        sorted_included = self._sort_strings(included_serials)
        sorted_missing = self._sort_strings(missing_inverter_realtime_serials)
        sorted_excluded_serials = self._sort_strings(list(excluded_non_inverter_devices.keys()))
        sorted_excluded = {
            serial: excluded_non_inverter_devices[serial]
            for serial in sorted_excluded_serials
        }
        sorted_power = {
            serial: per_device_power_w[serial]
            for serial in self._sort_strings(list(per_device_power_w.keys()))
        }
        sorted_sources = {
            serial: per_device_source_field[serial]
            for serial in self._sort_strings(list(per_device_source_field.keys()))
        }

        return {
            "total_w": round(total, 3),
            "included_device_serials": sorted_included,
            "included_device_count": len(sorted_included),
            "included_device_type": 1,
            "included_device_type_name": _device_type_text(self.coordinator.hass, 1),
            "missing_inverter_realtime_serials": sorted_missing,
            "excluded_non_inverter_serials": sorted_excluded_serials,
            "excluded_non_inverter_devices": sorted_excluded,
            "per_device_power_w": sorted_power,
            "per_device_source_field": sorted_sources,
        }

    def _system_yield_breakdown(self, field_key: str) -> dict[str, Any]:
        data = self.coordinator.data or {}
        plants_inventory = data.get("plants") or {}
        plants_rt = data.get("plant_realtime") or {}

        total = 0.0
        per_plant_kwh: dict[str, float] = {}
        included_plant_ids: list[str] = []
        missing_plant_ids: list[str] = []

        all_plant_ids = {
            str(plant_id).strip()
            for plant_id in list(plants_inventory.keys()) + list(plants_rt.keys())
            if str(plant_id).strip()
        }
        for plant_id in self._sort_strings(list(all_plant_ids)):
            row = plants_rt.get(plant_id)
            if not isinstance(row, dict):
                missing_plant_ids.append(plant_id)
                continue
            numeric_value = _safe_float(row.get(field_key))
            if numeric_value is None:
                missing_plant_ids.append(plant_id)
                continue
            numeric_value = round(numeric_value, 3)
            total += numeric_value
            per_plant_kwh[plant_id] = numeric_value
            included_plant_ids.append(plant_id)

        return {
            "source_field": field_key,
            "total_kwh": round(total, 3),
            "included_plant_ids": included_plant_ids,
            "included_plant_count": len(included_plant_ids),
            "missing_plant_ids": missing_plant_ids,
            "per_plant_kwh": per_plant_kwh,
        }

    def _system_ac_total(self) -> float:
        return float((self._system_ac_breakdown()).get("total_w") or 0.0)

    def _system_dc_total(self) -> float:
        return float((self._system_dc_breakdown()).get("total_w") or 0.0)

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        devices = data.get("devices") or {}
        device_rt = data.get("device_realtime") or {}

        if self._key == "system_ac_power":
            return round(self._system_ac_total(), 3)

        if self._key == "system_dc_power":
            return round(self._system_dc_total(), 3)

        if self._key == "system_yield_today":
            return (self._system_yield_breakdown("dailyYield")).get("total_kwh")

        if self._key == "system_yield_total":
            return (self._system_yield_breakdown("totalYield")).get("total_kwh")

        if self._key == "system_efficiency":
            dc = self._system_dc_total()
            ac = self._system_ac_total()
            if dc > 0:
                return round((ac / dc) * 100, 1)
            return 0.0

        if self._key == "system_health":
            total = len(devices)
            if total == 0:
                return _t(
                    self.coordinator.hass,
                    "runtime.status.system_health.unknown",
                    fallback="Unknown",
                )
            online = 0
            for sn, device in devices.items():
                online_status = device.get("onlineStatus")
                if online_status is not None:
                    try:
                        if int(online_status) == 1:
                            online += 1
                    except (TypeError, ValueError):
                        pass
                    continue
                payload = device_rt.get(sn)
                if isinstance(payload, dict):
                    online += 1
            if online == total:
                return _t(self.coordinator.hass, "runtime.status.system_health.ok", fallback="OK")
            if online == 0:
                return _t(
                    self.coordinator.hass,
                    "runtime.status.system_health.error",
                    fallback="Error",
                )
            return _t(
                self.coordinator.hass,
                "runtime.status.system_health.degraded",
                fallback="Degraded",
            )

        if self._key == "api_rate_limit_status":
            if self.coordinator.rate_limited:
                return _t(
                    self.coordinator.hass,
                    "runtime.status.rate_limit.active",
                    fallback="Rate Limited",
                )
            return _t(self.coordinator.hass, "runtime.status.rate_limit.ok", fallback="OK")

        if self._key == "poll_profile":
            profile = str((data.get("meta") or {}).get("poll_profile") or "standard")
            return _t(
                self.coordinator.hass,
                f"runtime.status.poll_profile.{profile}",
                fallback=profile,
            )

        if self._key == "effective_scan_interval":
            return int((data.get("meta") or {}).get("effective_scan_interval", 0))

        if self._key == "live_view_active":
            active = bool((data.get("meta") or {}).get("live_view_active", False))
            return _t(
                self.coordinator.hass,
                "runtime.status.live_view.active" if active else "runtime.status.live_view.inactive",
                fallback="Active" if active else "Inactive",
            )

        if self._key == "live_view_remaining_seconds":
            return int((data.get("meta") or {}).get("live_view_remaining_seconds", 0))

        if self._key == "last_poll_attempt":
            return self.coordinator.last_update_attempt

        if self._key == "next_scheduled_poll":
            if self.coordinator.last_update_attempt is None:
                return None
            return self.coordinator.last_update_attempt + timedelta(
                seconds=self.coordinator.update_interval.total_seconds()
            )

        if self._key == "token_expires_at":
            return self.coordinator.client.token_expires_at

        if self._key == "dry_run_command_count":
            return int((data.get("meta") or {}).get("dry_run_commands", 0))

        return None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        attrs = {
            "plants": len(data.get("plants") or {}),
            "devices": len(data.get("devices") or {}),
        }

        if self._key == "api_rate_limit_status":
            attrs["rate_limited_context"] = list(self.coordinator.rate_limited_context)
            if self.coordinator.last_rate_limit_at is not None:
                attrs["last_rate_limit_at"] = self.coordinator.last_rate_limit_at.isoformat()

        if self._key == "system_health":
            attrs["last_successful_refresh"] = (
                self.coordinator.last_successful_update.isoformat()
                if self.coordinator.last_successful_update
                else None
            )
            attrs["errors"] = self.coordinator.data.get("last_errors") or []

        if self._key == "next_scheduled_poll":
            next_poll = self.native_value
            if next_poll is not None:
                attrs["seconds_until_next_poll"] = max(
                    0,
                    int((next_poll - dt_util.utcnow()).total_seconds()),
                )

        if self._key == "dry_run_command_count":
            last_dry_run = (data.get("meta") or {}).get("last_dry_run")
            if isinstance(last_dry_run, dict):
                attrs["last_dry_run"] = last_dry_run

        if self._key == "system_ac_power":
            breakdown = self._system_ac_breakdown()
            attrs.update(
                {
                    "calculation_scope": "inverter_realtime_only",
                    "included_device_type": breakdown.get("included_device_type"),
                    "included_device_type_name": breakdown.get("included_device_type_name"),
                    "included_device_count": breakdown.get("included_device_count"),
                    "included_device_serials": breakdown.get("included_device_serials"),
                    "missing_inverter_realtime_serials": breakdown.get(
                        "missing_inverter_realtime_serials"
                    ),
                    "excluded_non_inverter_serials": breakdown.get(
                        "excluded_non_inverter_serials"
                    ),
                    "excluded_non_inverter_devices": breakdown.get(
                        "excluded_non_inverter_devices"
                    ),
                    "per_device_power_w": breakdown.get("per_device_power_w"),
                    "per_device_source_field": breakdown.get("per_device_source_field"),
                }
            )

        if self._key == "system_dc_power":
            breakdown = self._system_dc_breakdown()
            attrs.update(
                {
                    "calculation_scope": "inverter_realtime_only",
                    "included_device_type": breakdown.get("included_device_type"),
                    "included_device_type_name": breakdown.get("included_device_type_name"),
                    "included_device_count": breakdown.get("included_device_count"),
                    "included_device_serials": breakdown.get("included_device_serials"),
                    "missing_inverter_realtime_serials": breakdown.get(
                        "missing_inverter_realtime_serials"
                    ),
                    "excluded_non_inverter_serials": breakdown.get(
                        "excluded_non_inverter_serials"
                    ),
                    "excluded_non_inverter_devices": breakdown.get(
                        "excluded_non_inverter_devices"
                    ),
                    "per_device_power_w": breakdown.get("per_device_power_w"),
                    "per_device_source_field": breakdown.get("per_device_source_field"),
                }
            )

        if self._key == "system_yield_today":
            breakdown = self._system_yield_breakdown("dailyYield")
            attrs.update(
                {
                    "calculation_scope": "plant_realtime_sum",
                    "source_field": breakdown.get("source_field"),
                    "included_plant_count": breakdown.get("included_plant_count"),
                    "included_plant_ids": breakdown.get("included_plant_ids"),
                    "missing_plant_ids": breakdown.get("missing_plant_ids"),
                    "per_plant_kwh": breakdown.get("per_plant_kwh"),
                }
            )

        if self._key == "system_yield_total":
            breakdown = self._system_yield_breakdown("totalYield")
            attrs.update(
                {
                    "calculation_scope": "plant_realtime_sum",
                    "source_field": breakdown.get("source_field"),
                    "included_plant_count": breakdown.get("included_plant_count"),
                    "included_plant_ids": breakdown.get("included_plant_ids"),
                    "missing_plant_ids": breakdown.get("missing_plant_ids"),
                    "per_plant_kwh": breakdown.get("per_plant_kwh"),
                }
            )

        if self._key == "system_efficiency":
            ac = self._system_ac_breakdown()
            dc = self._system_dc_breakdown()
            attrs.update(
                {
                    "calculation_scope": "system_ac_power/system_dc_power*100",
                    "zero_input_behavior": "returns_0_when_dc_is_zero_or_missing",
                    "ac_power_w": ac.get("total_w"),
                    "dc_power_w": dc.get("total_w"),
                    "ac_included_device_serials": ac.get("included_device_serials"),
                    "dc_included_device_serials": dc.get("included_device_serials"),
                    "ac_missing_inverter_realtime_serials": ac.get(
                        "missing_inverter_realtime_serials"
                    ),
                    "dc_missing_inverter_realtime_serials": dc.get(
                        "missing_inverter_realtime_serials"
                    ),
                }
            )

        if self._key in ("poll_profile", "effective_scan_interval", "live_view_active"):
            attrs["live_view_until"] = (data.get("meta") or {}).get("live_view_until")
            attrs["live_view_target_interval"] = (
                (data.get("meta") or {}).get("live_view_target_interval")
            )
            attrs["live_view_call_budget_per_minute"] = (
                (data.get("meta") or {}).get("live_view_call_budget_per_minute")
            )
            attrs["live_view_estimated_calls_per_cycle"] = (
                (data.get("meta") or {}).get("live_view_estimated_calls_per_cycle")
            )
            attrs["night_scan_interval"] = (data.get("meta") or {}).get("night_scan_interval")

        return attrs


class SolaxPlantFieldSensor(SolaxBaseSensor):
    """Dynamic sensor for plant realtime fields."""

    def __init__(self, coordinator, system_slug: str, plant_id: str, field_key: str) -> None:
        self._plant_id = plant_id
        self._field_key = field_key
        name = _t(
            coordinator.hass,
            "runtime.entity_templates.plant_field",
            placeholders={"plant_id": plant_id, "field_name": _humanize_key(field_key)},
            fallback="Plant {plant_id} {field_name}",
        )
        super().__init__(coordinator, system_slug, f"plant_{plant_id}_{_snake(field_key)}", name)

        unit, device_class, state_class = _infer_unit_and_classes(field_key)
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        if device_class is not None:
            self._attr_device_class = device_class
        if state_class is not None:
            self._attr_state_class = state_class
        if _field_kind(field_key) == "time":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self):
        plant = (self.coordinator.data.get("plant_realtime") or {}).get(self._plant_id)
        if not isinstance(plant, dict):
            return False
        flat = _flatten_dict(plant)
        return self._field_key in flat and flat[self._field_key] is not None

    @property
    def native_value(self):
        plant = (self.coordinator.data.get("plant_realtime") or {}).get(self._plant_id)
        if not isinstance(plant, dict):
            return None
        flat = _flatten_dict(plant)
        raw_value = flat.get(self._field_key)
        if raw_value is None:
            return None

        plant_info = (self.coordinator.data.get("plants") or {}).get(self._plant_id) or {}
        business_type = int(plant_info.get("businessType") or 1)
        return _normalize_numeric_value(self._field_key, raw_value, business_type)

    @property
    def device_info(self):
        plants = self.coordinator.data.get("plants") or {}
        plant = plants.get(self._plant_id) or {}
        business_type_label = _business_type_text(
            self.coordinator.hass,
            plant.get("businessType"),
        )
        return {
            "identifiers": {(DOMAIN, f"plant_{self._plant_id}")},
            "name": plant.get("plantName")
            or _t(
                self.coordinator.hass,
                "runtime.entity_templates.plant_name",
                placeholders={"plant_id": self._plant_id},
                fallback="Plant {plant_id}",
            ),
            "manufacturer": "SolaX",
            "model": _t(
                self.coordinator.hass,
                "runtime.device_model.plant",
                placeholders={"business_type": business_type_label},
                fallback="Plant {business_type}",
            ),
        }


class SolaxPlantAlarmCountSensor(SolaxBaseSensor):
    """Per-plant ongoing alarm count."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, system_slug: str, plant_id: str) -> None:
        self._plant_id = plant_id
        super().__init__(
            coordinator,
            system_slug,
            f"plant_{plant_id}_active_alarm_count",
            _t(
                coordinator.hass,
                "runtime.entity_templates.plant_alarm_count",
                placeholders={"plant_id": plant_id},
                fallback="Plant {plant_id} Active Alarm Count",
            ),
        )
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        alarms = (self.coordinator.data.get("alarms") or {}).get(self._plant_id) or {}
        return int(alarms.get("total") or 0)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"plant_{self._plant_id}")},
            "name": _t(
                self.coordinator.hass,
                "runtime.entity_templates.plant_name",
                placeholders={"plant_id": self._plant_id},
                fallback="Plant {plant_id}",
            ),
            "manufacturer": "SolaX",
            "model": _t(
                self.coordinator.hass,
                "runtime.device_model.plant_simple",
                fallback="Plant",
            ),
        }


class SolaxPlantStatSensor(SolaxBaseSensor):
    """Per-plant monthly/yearly stat summary metric."""

    def __init__(
        self,
        coordinator,
        system_slug: str,
        plant_id: str,
        period: str,
        metric_name: str,
    ) -> None:
        self._plant_id = plant_id
        self._period = period
        self._metric_name = metric_name
        period_label = _t(
            coordinator.hass,
            f"runtime.labels.period.{period}",
            fallback=period.capitalize(),
        )
        super().__init__(
            coordinator,
            system_slug,
            f"plant_{plant_id}_{period}_{_snake(metric_name)}",
            _t(
                coordinator.hass,
                "runtime.entity_templates.plant_stat",
                placeholders={
                    "plant_id": plant_id,
                    "period": period_label,
                    "metric_name": _humanize_key(metric_name),
                },
                fallback="Plant {plant_id} {period} {metric_name}",
            ),
        )

        lowered = metric_name.casefold()
        if "earnings" in lowered:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        else:
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_state_class = SensorStateClass.TOTAL
            self._attr_native_unit_of_measurement = "kWh"

    @property
    def native_value(self):
        stat = (
            ((self.coordinator.data.get("plant_stats") or {}).get(self._plant_id) or {}).get(
                self._period
            )
            or {}
        )
        metrics = _extract_stat_metrics(stat)
        return round(float(metrics.get(self._metric_name) or 0), 3)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"plant_{self._plant_id}")},
            "name": _t(
                self.coordinator.hass,
                "runtime.entity_templates.plant_name",
                placeholders={"plant_id": self._plant_id},
                fallback="Plant {plant_id}",
            ),
            "manufacturer": "SolaX",
            "model": _t(
                self.coordinator.hass,
                "runtime.device_model.plant_stats",
                fallback="Plant Stats",
            ),
        }


class SolaxPlantInfoSensor(SolaxBaseSensor):
    """Plant metadata as diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, system_slug: str, plant_id: str, key: str) -> None:
        self._plant_id = plant_id
        self._key = key
        super().__init__(
            coordinator,
            system_slug,
            f"plant_{plant_id}_{_snake(key)}_info",
            _t(
                coordinator.hass,
                "runtime.entity_templates.plant_info",
                placeholders={"plant_id": plant_id, "key_name": _humanize_key(key)},
                fallback="Plant {plant_id} {key_name}",
            ),
        )
        if key not in CORE_PLANT_INFO_KEYS:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        plant = (self.coordinator.data.get("plants") or {}).get(self._plant_id) or {}
        value = plant.get(self._key)
        if self._key == "plantState" and value is not None:
            business_type = int(plant.get("businessType") or 1)
            return _plant_state_text(self.coordinator.hass, business_type, value)
        return value

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"plant_{self._plant_id}")},
            "name": _t(
                self.coordinator.hass,
                "runtime.entity_templates.plant_name",
                placeholders={"plant_id": self._plant_id},
                fallback="Plant {plant_id}",
            ),
            "manufacturer": "SolaX",
            "model": _t(
                self.coordinator.hass,
                "runtime.device_model.plant_simple",
                fallback="Plant",
            ),
        }


class SolaxPlantAlarmPreviewSensor(SolaxBaseSensor):
    """Diagnostic preview of top alarms for each plant."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator,
        system_slug: str,
        plant_id: str,
        alarm_index: int,
        alarm_key: str,
    ) -> None:
        self._plant_id = plant_id
        self._alarm_index = alarm_index
        self._alarm_key = alarm_key
        super().__init__(
            coordinator,
            system_slug,
            f"plant_{plant_id}_alarm_{alarm_index}_{_snake(alarm_key)}",
            _t(
                coordinator.hass,
                "runtime.entity_templates.plant_alarm_preview",
                placeholders={
                    "plant_id": plant_id,
                    "alarm_index": alarm_index + 1,
                    "alarm_key": _humanize_key(alarm_key),
                },
                fallback="Plant {plant_id} Alarm {alarm_index} {alarm_key}",
            ),
        )

    @property
    def native_value(self):
        alarms = (self.coordinator.data.get("alarms") or {}).get(self._plant_id) or {}
        records = alarms.get("records") or []
        if self._alarm_index >= len(records):
            return None
        row = records[self._alarm_index]
        if not isinstance(row, dict):
            return None
        return row.get(self._alarm_key)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"plant_{self._plant_id}")},
            "name": _t(
                self.coordinator.hass,
                "runtime.entity_templates.plant_name",
                placeholders={"plant_id": self._plant_id},
                fallback="Plant {plant_id}",
            ),
            "manufacturer": "SolaX",
            "model": _t(
                self.coordinator.hass,
                "runtime.device_model.plant_alarms",
                fallback="Plant Alarms",
            ),
        }


class SolaxDeviceFieldSensor(SolaxBaseSensor):
    """Dynamic sensor for device realtime fields."""

    def __init__(
        self,
        coordinator,
        system_slug: str,
        device_sn: str,
        device_type: Any,
        field_key: str,
        *,
        enabled_by_default: bool = True,
    ) -> None:
        self._device_sn = device_sn
        self._field_key = field_key
        try:
            self._device_type = int(device_type or 0)
        except (TypeError, ValueError):
            self._device_type = 0
        field_name = _humanize_key(field_key)
        field_slug = _snake(field_key)
        super().__init__(
            coordinator,
            system_slug,
            _device_sensor_unique_suffix(
                field_slug=field_slug,
                device_sn=device_sn,
                info=False,
            ),
            _device_field_display_name(
                coordinator.hass,
                device_type=self._device_type,
                field_name=field_name,
            ),
        )
        if not enabled_by_default:
            self._attr_entity_registry_enabled_default = False

        inventory = (coordinator.data.get("devices") or {}).get(device_sn) or {}
        self._business_type = int(inventory.get("businessType") or 1)

        unit, device_class, state_class = _infer_unit_and_classes(field_key)
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        if device_class is not None:
            self._attr_device_class = device_class
        if state_class is not None:
            self._attr_state_class = state_class

        if _field_kind(field_key) == "time":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def _payload(self) -> dict[str, Any]:
        return (self.coordinator.data.get("device_realtime") or {}).get(self._device_sn) or {}

    @property
    def available(self):
        payload = self._payload
        if not isinstance(payload, dict):
            return False
        flat = _flatten_dict(payload)
        return self._field_key in flat and flat[self._field_key] is not None

    @property
    def native_value(self):
        payload = self._payload
        if not isinstance(payload, dict):
            return None
        flat = _flatten_dict(payload)
        raw_value = flat.get(self._field_key)
        if raw_value is None:
            return None

        device_type = int(payload.get("deviceType") or 0)
        business_type = int(payload.get("businessType") or self._business_type or 1)
        mapped = _status_text(
            self.coordinator.hass,
            device_type,
            business_type,
            self._field_key,
            raw_value,
        )
        if mapped != raw_value:
            return mapped

        return _normalize_numeric_value(self._field_key, raw_value, business_type)

    @property
    def extra_state_attributes(self):
        payload = self._payload
        flat = _flatten_dict(payload) if isinstance(payload, dict) else {}
        raw_value = flat.get(self._field_key)
        if raw_value is None:
            return {}

        business_type = int(payload.get("businessType") or self._business_type or 1)
        mapped = _status_text(
            self.coordinator.hass,
            int(payload.get("deviceType") or 0),
            business_type,
            self._field_key,
            raw_value,
        )
        normalized = _normalize_numeric_value(self._field_key, raw_value, business_type)
        attrs: dict[str, Any] = {"business_type": business_type}

        if mapped != raw_value:
            attrs["raw_value"] = raw_value
            attrs["mapped_value"] = mapped
        elif normalized != raw_value:
            attrs["raw_value"] = raw_value
            attrs["normalized_value"] = normalized

        # Avoid noisy attributes for unchanged fields.
        if set(attrs.keys()) == {"business_type"}:
            return {}
        return attrs

    @property
    def device_info(self):
        devices = self.coordinator.data.get("devices") or {}
        device = devices.get(self._device_sn) or {}
        device_type = int(device.get("deviceType") or 0)
        model_id = device.get("deviceModel")
        model_name = _device_model_text(
            self.coordinator.hass,
            model_id,
            business_type=device.get("businessType"),
            device_type=device_type,
        )
        if model_name in (None, ""):
            model_name = _t(
                self.coordinator.hass,
                "runtime.labels.unknown",
                fallback="Unknown",
            )

        return {
            "identifiers": {(DOMAIN, self._device_sn)},
            "name": _t(
                self.coordinator.hass,
                "runtime.entity_templates.device_name",
                placeholders={
                    "device_type": _device_type_text(self.coordinator.hass, device_type),
                    "device_sn": self._device_sn,
                },
                fallback="Solax {device_type} {device_sn}",
            ),
            "manufacturer": "SolaX",
            "model": model_name,
            "serial_number": self._device_sn,
        }


class SolaxDeviceInfoSensor(SolaxBaseSensor):
    """Device inventory fields as diagnostics."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator,
        system_slug: str,
        device_sn: str,
        device_type: Any,
        key: str,
    ) -> None:
        self._device_sn = device_sn
        self._key = key
        try:
            self._device_type = int(device_type or 0)
        except (TypeError, ValueError):
            self._device_type = 0
        key_name = _humanize_key(key)
        key_slug = _snake(key)
        super().__init__(
            coordinator,
            system_slug,
            _device_sensor_unique_suffix(
                field_slug=key_slug,
                device_sn=device_sn,
                info=True,
            ),
            _device_info_display_name(
                coordinator.hass,
                device_type=self._device_type,
                key_name=key_name,
            ),
        )
        if key not in CORE_DEVICE_INFO_KEYS:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        device = (self.coordinator.data.get("devices") or {}).get(self._device_sn) or {}
        value = device.get(self._key)
        business_type = int(device.get("businessType") or 1)
        if self._key == "deviceModel" and value is not None:
            return _device_model_text(
                self.coordinator.hass,
                value,
                business_type=business_type,
                device_type=device.get("deviceType"),
            )
        if self._key == "onlineStatus" and value is not None:
            return _online_status_text(self.coordinator.hass, value)
        if self._key == "flag" and value is not None:
            return _parallel_flag_text(self.coordinator.hass, business_type, value)
        return value

    @property
    def device_info(self):
        device = (self.coordinator.data.get("devices") or {}).get(self._device_sn) or {}
        device_type = int(device.get("deviceType") or self._device_type or 0)
        model_name = _device_model_text(
            self.coordinator.hass,
            device.get("deviceModel"),
            business_type=device.get("businessType"),
            device_type=device_type,
        )
        if model_name in (None, "") and device_type == 100:
            model_name = _t(
                self.coordinator.hass,
                "runtime.device_model.ems_system",
                fallback="EMS System",
            )
        if model_name in (None, ""):
            model_name = _t(
                self.coordinator.hass,
                "runtime.device_model.inventory",
                fallback="Inventory",
            )
        return {
            "identifiers": {(DOMAIN, self._device_sn)},
            "name": _t(
                self.coordinator.hass,
                "runtime.entity_templates.device_name",
                placeholders={
                    "device_type": _device_type_text(
                        self.coordinator.hass,
                        device_type,
                    ),
                    "device_sn": self._device_sn,
                },
                fallback="Solax {device_type} {device_sn}",
            ),
            "manufacturer": "SolaX",
            "model": model_name,
            "serial_number": self._device_sn,
        }
