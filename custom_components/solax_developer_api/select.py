"""Select entities for SolaX Developer API integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity

from .entity import system_identity
from .ev_charger import (
    CHARGE_SCENE_OPTIONS,
    START_MODE_OPTIONS,
    WORK_MODE_OPTIONS,
    SolaxEVChargerEntity,
    ev_charger_devices,
    translated_option,
)

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data.coordinator
    _system_name, system_slug = system_identity(hass, entry)
    seen: set[tuple[str, str]] = set()

    def _build_entities():
        new_entities = []
        for device in ev_charger_devices(coordinator):
            device_sn = str(device.get("deviceSn") or "")
            for cls in (
                SolaxEVWorkModeSelect,
                SolaxEVStartModeSelect,
                SolaxEVChargeSceneSelect,
            ):
                token = (device_sn, cls.FIELD_SLUG)
                if token in seen:
                    continue
                seen.add(token)
                new_entities.append(
                    cls(
                        coordinator=coordinator,
                        system_slug=system_slug,
                        device=device,
                    )
                )
        return new_entities

    async_add_entities(_build_entities())

    def _coordinator_updated() -> None:
        additions = _build_entities()
        if additions:
            async_add_entities(additions)

    if hasattr(entry, "async_on_unload"):
        entry.async_on_unload(coordinator.async_add_listener(_coordinator_updated))


class SolaxEVWorkModeSelect(SolaxEVChargerEntity, SelectEntity):
    """Select EV charger working mode."""

    FIELD_SLUG = "ev_charger_work_mode"
    _attr_translation_key = "ev_charger_work_mode"

    def __init__(self, *, coordinator, system_slug: str, device) -> None:
        super().__init__(coordinator, system_slug, device, self.FIELD_SLUG, "select")
        self._option_map: dict[str, tuple[int, int | None]] = {}
        for key, work_mode, current_gear in WORK_MODE_OPTIONS:
            if current_gear is None:
                fallback = key.upper()
            elif key.startswith("eco"):
                fallback = f"ECO {current_gear} A"
            else:
                fallback = f"GREEN {current_gear} A"
            self._option_map[
                translated_option(
                    coordinator.hass,
                    "work_mode",
                    key,
                    fallback,
                )
            ] = (work_mode, current_gear)
        self._attr_options = list(self._option_map)

    @property
    def current_option(self) -> str | None:
        state_option = self._ev_gui_state.get("work_mode_option")
        if state_option in self._option_map:
            return state_option
        payload = (self.coordinator.data.get("device_realtime") or {}).get(
            self._device_sn,
        ) or {}
        raw_mode = _coerce_int(
            payload.get("workMode")
            if payload.get("workMode") is not None
            else payload.get("deviceWorkingMode")
        )
        raw_gear = _coerce_int(
            payload.get("currentGear")
            if payload.get("currentGear") is not None
            else payload.get("current")
        )
        for option, (work_mode, current_gear) in self._option_map.items():
            if raw_mode != work_mode:
                continue
            if current_gear is None or raw_gear == current_gear:
                return option
        return None

    async def async_select_option(self, option: str) -> None:
        work_mode, current_gear = self._option_map[option]
        payload = self._payload_base()
        payload["work_mode"] = work_mode
        if current_gear is not None:
            payload["current_gear"] = current_gear
        await self._execute_evc_service("set_evc_work_mode", payload)
        self._ev_gui_state["work_mode_option"] = option


class SolaxEVStartModeSelect(SolaxEVChargerEntity, SelectEntity):
    """Select EV charger start mode."""

    FIELD_SLUG = "ev_charger_start_mode"
    _attr_translation_key = "ev_charger_start_mode"

    def __init__(self, *, coordinator, system_slug: str, device) -> None:
        super().__init__(coordinator, system_slug, device, self.FIELD_SLUG, "select")
        fallback_map = {
            "plug_and_charge": "Plug and charge",
            "swipe_card": "Swipe card",
            "app": "APP",
        }
        self._option_map = {
            translated_option(
                coordinator.hass,
                "start_mode",
                key,
                fallback_map[key],
            ): value
            for key, value in START_MODE_OPTIONS
        }
        self._attr_options = list(self._option_map)

    @property
    def current_option(self) -> str | None:
        state_option = self._ev_gui_state.get("start_mode_option")
        if state_option in self._option_map:
            return state_option
        payload = (self.coordinator.data.get("device_realtime") or {}).get(
            self._device_sn,
        ) or {}
        raw_mode = _coerce_int(payload.get("startMode"))
        for option, start_mode in self._option_map.items():
            if raw_mode == start_mode:
                return option
        return None

    async def async_select_option(self, option: str) -> None:
        payload = self._payload_base()
        payload["start_mode"] = self._option_map[option]
        await self._execute_evc_service("set_evc_start_mode", payload)
        self._ev_gui_state["start_mode_option"] = option


class SolaxEVChargeSceneSelect(SolaxEVChargerEntity, SelectEntity):
    """Select EV charger charging scene."""

    FIELD_SLUG = "ev_charger_charge_scene"
    _attr_translation_key = "ev_charger_charge_scene"

    def __init__(self, *, coordinator, system_slug: str, device) -> None:
        super().__init__(coordinator, system_slug, device, self.FIELD_SLUG, "select")
        fallback_map = {
            "home": "HOME",
            "ocpp": "OCPP",
            "standard_solar": "Standard / Solar",
        }
        self._option_map = {
            translated_option(
                coordinator.hass,
                "charge_scene",
                key,
                fallback_map[key],
            ): value
            for key, value in CHARGE_SCENE_OPTIONS
        }
        self._attr_options = list(self._option_map)

    @property
    def current_option(self) -> str | None:
        state_option = self._ev_gui_state.get("charge_scene_option")
        if state_option in self._option_map:
            return state_option
        payload = (self.coordinator.data.get("device_realtime") or {}).get(
            self._device_sn,
        ) or {}
        raw_scene = _coerce_int(payload.get("chargerScene"))
        for option, charger_scene in self._option_map.items():
            if raw_scene == charger_scene:
                return option
        return None

    async def async_select_option(self, option: str) -> None:
        payload = self._payload_base()
        charger_scene = self._option_map[option]
        payload["charger_scene"] = charger_scene
        ocpp_url = str(self._ev_gui_state.get("ocpp_url") or "").strip()
        ocpp_charger_id = str(self._ev_gui_state.get("ocpp_charger_id") or "").strip()
        if ocpp_url:
            payload["ocpp_url"] = ocpp_url
        if ocpp_charger_id:
            payload["ocpp_charger_id"] = ocpp_charger_id
        await self._execute_evc_service("set_charge_scene", payload)
        self._ev_gui_state["charge_scene_option"] = option
        self._ev_gui_state["charger_scene"] = charger_scene


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
