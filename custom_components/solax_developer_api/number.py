"""Number entities for SolaX Developer API integration."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfElectricCurrent

from .entity import system_identity
from .ev_charger import SolaxEVChargerEntity, ev_charger_devices

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data.coordinator
    _system_name, system_slug = system_identity(hass, entry)
    seen: set[tuple[str, str]] = set()

    def _build_entities():
        new_entities = []
        for device in ev_charger_devices(coordinator):
            device_sn = str(device.get("deviceSn") or "")
            for cls in (SolaxEVCurrentLimitNumber, SolaxEVReserveCurrentNumber):
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


class SolaxEVCurrentLimitNumber(SolaxEVChargerEntity, NumberEntity):
    """EV charger current limit number."""

    FIELD_SLUG = "ev_charger_current_limit"
    _attr_translation_key = "ev_charger_current_limit"
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_min_value = 6
    _attr_native_max_value = 40
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def __init__(self, *, coordinator, system_slug: str, device) -> None:
        super().__init__(coordinator, system_slug, device, self.FIELD_SLUG, "number")

    @property
    def native_value(self) -> float | None:
        if self._ev_gui_state.get("current_limit") is not None:
            return float(self._ev_gui_state["current_limit"])
        payload = (self.coordinator.data.get("device_realtime") or {}).get(
            self._device_sn,
        ) or {}
        value = payload.get("currentLimit")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        current_limit = int(round(value))
        payload = self._payload_base()
        payload["current_limit"] = current_limit
        await self._execute_evc_service("set_evc_current_limit", payload)
        self._ev_gui_state["current_limit"] = current_limit


class SolaxEVReserveCurrentNumber(SolaxEVChargerEntity, NumberEntity):
    """Staged EV charger schedule current number."""

    FIELD_SLUG = "ev_charger_reserve_current"
    _attr_translation_key = "ev_charger_reserve_current"
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_min_value = 6
    _attr_native_max_value = 32
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def __init__(self, *, coordinator, system_slug: str, device) -> None:
        super().__init__(coordinator, system_slug, device, self.FIELD_SLUG, "number")
        self._ev_gui_state.setdefault("reserve_current", 16)

    @property
    def native_value(self) -> float:
        return float(self._ev_gui_state.get("reserve_current") or 16)

    async def async_set_native_value(self, value: float) -> None:
        self._ev_gui_state["reserve_current"] = int(round(value))
        self.async_write_ha_state()
