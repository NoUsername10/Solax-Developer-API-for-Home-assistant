"""Shared EV charger control entity helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    CONTROL_SERVICE_DEFINITIONS,
    DEVICE_MODEL_MAP,
    DEVICE_MODEL_MAP_BY_CONTEXT,
    DEVICE_TYPE_NAMES,
    DOMAIN,
    EV_CHARGER_CONTROL_SERVICES,
)
from .i18n import translate
from .validation import ControlValidationError, validate_control_payload

EV_CHARGER_DEVICE_TYPE = 4

WORK_MODE_OPTIONS: tuple[tuple[str, int, int | None], ...] = (
    ("stop", 0, None),
    ("fast", 1, None),
    ("eco_6a", 2, 6),
    ("eco_10a", 2, 10),
    ("eco_16a", 2, 16),
    ("eco_20a", 2, 20),
    ("eco_25a", 2, 25),
    ("green_3a", 3, 3),
    ("green_6a", 3, 6),
)

START_MODE_OPTIONS: tuple[tuple[str, int], ...] = (
    ("plug_and_charge", 0),
    ("swipe_card", 1),
    ("app", 2),
)

CHARGE_SCENE_OPTIONS: tuple[tuple[str, int], ...] = (
    ("home", 0),
    ("ocpp", 1),
    ("standard_solar", 2),
)

CONTROL_VALUE_ERROR_FALLBACKS = {
    "not_ev_charger_control": "{service}: this command is not an EV charger control service",
    "control_ev_charger_target_unknown": (
        "{service}: all serials must be discovered EV chargers before real EV "
        "control is allowed"
    ),
    "control_ev_charger_business_type_mismatch": (
        "{service}: businessType does not match the discovered EV charger"
    ),
}


def ev_charger_devices(coordinator: Any) -> list[dict[str, Any]]:
    """Return discovered EV chargers from coordinator state."""
    devices: list[dict[str, Any]] = []
    for serial, payload in (coordinator.data.get("devices") or {}).items():
        if not isinstance(payload, Mapping):
            continue
        try:
            device_type = int(payload.get("deviceType") or 0)
        except (TypeError, ValueError):
            device_type = 0
        if device_type != EV_CHARGER_DEVICE_TYPE:
            continue

        serial_text = str(payload.get("deviceSn") or serial).strip()
        if not serial_text:
            continue

        item = dict(payload)
        item["deviceSn"] = serial_text
        item["deviceType"] = EV_CHARGER_DEVICE_TYPE
        try:
            item["businessType"] = int(item.get("businessType") or 1)
        except (TypeError, ValueError):
            item["businessType"] = 1
        devices.append(item)

    return sorted(devices, key=lambda item: str(item["deviceSn"]).casefold())


def ev_control_unique_suffix(field_slug: str, device_sn: str) -> str:
    """Return a serial-last unique suffix for EV charger controls."""
    return f"{field_slug}_device_{slugify(device_sn)}"


def _device_type_text(hass: Any, value: Any) -> str:
    try:
        device_type = int(value)
    except (TypeError, ValueError):
        return translate(hass, "runtime.labels.device", fallback="Device")
    fallback = DEVICE_TYPE_NAMES.get(
        device_type,
        translate(hass, "runtime.labels.device", fallback="Device"),
    )
    return translate(
        hass,
        f"runtime.labels.device_type.{device_type}",
        fallback=fallback,
    )


def _device_model_text(
    hass: Any,
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
        return translate(
            hass,
            f"runtime.device_model.context.{context_key[0]}.{context_key[1]}.{model_id}",
            fallback=fallback,
        )
    return translate(hass, f"runtime.device_model.code.{model_id}", fallback=fallback)


def _runtime_error(
    hass: Any,
    key: str,
    *,
    placeholders: dict[str, Any] | None = None,
    fallback: str | None = None,
) -> str:
    return translate(
        hass,
        f"runtime.errors.{key}",
        placeholders=placeholders,
        fallback=fallback,
    )


class SolaxEVChargerEntity(CoordinatorEntity):
    """Base class for entities attached to a discovered EV charger."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Any,
        system_slug: str,
        device: Mapping[str, Any],
        field_slug: str,
        platform: str,
    ) -> None:
        super().__init__(coordinator)
        self._system_slug = system_slug
        self._device_sn = str(device.get("deviceSn") or "").strip()
        self._device_type = EV_CHARGER_DEVICE_TYPE
        self._business_type = int(device.get("businessType") or 1)
        self._attr_unique_id = (
            f"{system_slug}_{ev_control_unique_suffix(field_slug, self._device_sn)}"
        ).lower()
        self.entity_id = f"{platform}.{self._attr_unique_id}"

    @property
    def available(self) -> bool:
        """Return whether the EV charger control path can currently be used."""
        return bool(
            self.coordinator.ev_charger_controls_enabled
            and self.coordinator.get_known_ev_charger_serial(self._device_sn)
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return the shared EV charger device registry entry."""
        device = (self.coordinator.data.get("devices") or {}).get(self._device_sn) or {}
        model_name = _device_model_text(
            self.coordinator.hass,
            device.get("deviceModel"),
            business_type=device.get("businessType", self._business_type),
            device_type=EV_CHARGER_DEVICE_TYPE,
        )
        if model_name in (None, ""):
            model_name = translate(
                self.coordinator.hass,
                "runtime.device_model.inventory",
                fallback="Inventory",
            )
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_sn)},
            name=translate(
                self.coordinator.hass,
                "runtime.entity_templates.device_name",
                placeholders={
                    "device_type": _device_type_text(
                        self.coordinator.hass,
                        EV_CHARGER_DEVICE_TYPE,
                    ),
                    "device_sn": self._device_sn,
                },
                fallback="Solax {device_type} {device_sn}",
            ),
            manufacturer="SolaX",
            model=model_name,
            serial_number=self._device_sn,
        )

    @property
    def _ev_gui_state(self) -> dict[str, Any]:
        state = getattr(self.coordinator, "_ev_charger_gui_state", None)
        if not isinstance(state, dict):
            state = {}
            setattr(self.coordinator, "_ev_charger_gui_state", state)
        device_state = state.setdefault(self._device_sn, {})
        if not isinstance(device_state, dict):
            device_state = {}
            state[self._device_sn] = device_state
        return device_state

    def _payload_base(self) -> dict[str, Any]:
        return {
            "sn_list": [self._device_sn],
            "business_type": self._business_type,
        }

    async def _execute_evc_service(
        self,
        service: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.coordinator.ev_charger_controls_enabled:
            raise HomeAssistantError(
                _runtime_error(
                    self.coordinator.hass,
                    "ev_charger_controls_disabled",
                    fallback=(
                        "EV charger controls are disabled. Enable EV Charger "
                        "Controls in integration options before using this control."
                    ),
                )
            )
        if service not in EV_CHARGER_CONTROL_SERVICES:
            raise HomeAssistantError(
                _runtime_error(
                    self.coordinator.hass,
                    "not_ev_charger_control",
                    placeholders={"service": service},
                    fallback="{service}: this command is not an EV charger control service",
                )
            )
        if service not in self.coordinator.available_control_services:
            raise HomeAssistantError(
                _runtime_error(
                    self.coordinator.hass,
                    "control_not_available",
                    placeholders={"service": service},
                    fallback=(
                        "{service}: no compatible device capability is available "
                        "in this integration"
                    ),
                )
            )

        try:
            validated = validate_control_payload(service, payload)
        except ControlValidationError as err:
            raise HomeAssistantError(
                _runtime_error(
                    self.coordinator.hass,
                    err.key.removeprefix("runtime.errors."),
                    placeholders=err.placeholders,
                    fallback=str(err),
                )
            ) from err

        try:
            event = await self.coordinator.async_execute_ev_charger_control(
                service=service,
                endpoint=CONTROL_SERVICE_DEFINITIONS[service]["endpoint"],
                payload=validated,
            )
        except ValueError as err:
            error_key = str(err)
            raise HomeAssistantError(
                _runtime_error(
                    self.coordinator.hass,
                    error_key,
                    placeholders={"service": service},
                    fallback=CONTROL_VALUE_ERROR_FALLBACKS.get(error_key, error_key),
                )
            ) from err

        if not bool(event.get("accepted")):
            statuses = event.get("device_statuses") or {}
            status_text = ", ".join(
                f"{serial}: {item.get('status_name') or item.get('status')}"
                for serial, item in statuses.items()
                if isinstance(item, Mapping)
            )
            raise HomeAssistantError(
                _runtime_error(
                    self.coordinator.hass,
                    "ev_charger_command_not_accepted",
                    placeholders={
                        "service": service,
                        "statuses": status_text or "unknown",
                    },
                    fallback=(
                        "{service}: SolaX did not accept the EV charger command "
                        "({statuses})"
                    ),
                )
            )

        self.async_write_ha_state()
        return event


def translated_option(hass: Any, group: str, key: str, fallback: str) -> str:
    """Translate an EV charger select option."""
    return translate(
        hass,
        f"runtime.labels.ev_charger.{group}.{key}",
        fallback=fallback,
    )
