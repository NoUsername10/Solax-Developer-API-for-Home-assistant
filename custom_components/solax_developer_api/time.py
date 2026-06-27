"""Time entities for SolaX Developer API integration."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity

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
            for cls in (
                SolaxEVReserveStartTime,
                SolaxEVReserveEndTime,
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


class _SolaxEVReserveTime(SolaxEVChargerEntity, TimeEntity):
    """Base staged schedule time entity."""

    STATE_KEY = ""
    FIELD_SLUG = ""
    DEFAULT_VALUE = time(8, 0)

    def __init__(self, *, coordinator, system_slug: str, device) -> None:
        super().__init__(coordinator, system_slug, device, self.FIELD_SLUG, "time")
        self._ev_gui_state.setdefault(self.STATE_KEY, self.DEFAULT_VALUE.strftime("%H:%M"))

    @property
    def native_value(self) -> time:
        raw_value = str(
            self._ev_gui_state.get(self.STATE_KEY)
            or self.DEFAULT_VALUE.strftime("%H:%M")
        )
        try:
            hour, minute = raw_value.split(":", 1)
            return time(int(hour), int(minute))
        except (TypeError, ValueError):
            return self.DEFAULT_VALUE

    async def async_set_value(self, value: time) -> None:
        self._ev_gui_state[self.STATE_KEY] = value.strftime("%H:%M")
        self.async_write_ha_state()


class SolaxEVReserveStartTime(_SolaxEVReserveTime):
    """Staged EV reserve start time."""

    FIELD_SLUG = "ev_charger_reserve_start_time"
    STATE_KEY = "reserve_start_time"
    DEFAULT_VALUE = time(8, 0)
    _attr_translation_key = "ev_charger_reserve_start_time"


class SolaxEVReserveEndTime(_SolaxEVReserveTime):
    """Staged EV reserve end time."""

    FIELD_SLUG = "ev_charger_reserve_end_time"
    STATE_KEY = "reserve_end_time"
    DEFAULT_VALUE = time(10, 0)
    _attr_translation_key = "ev_charger_reserve_end_time"
