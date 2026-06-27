"""Text entities for SolaX Developer API integration."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode

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
                SolaxEVQRCodeText,
                SolaxEVOcppUrlText,
                SolaxEVOcppChargerIdText,
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


class _SolaxEVTextEntity(SolaxEVChargerEntity, TextEntity):
    """Base EV charger staged text entity."""

    STATE_KEY = ""
    FIELD_SLUG = ""
    _attr_mode = TextMode.TEXT

    def __init__(self, *, coordinator, system_slug: str, device) -> None:
        super().__init__(coordinator, system_slug, device, self.FIELD_SLUG, "text")

    @property
    def native_value(self) -> str:
        return str(self._ev_gui_state.get(self.STATE_KEY) or "")

    async def async_set_value(self, value: str) -> None:
        self._ev_gui_state[self.STATE_KEY] = str(value or "").strip()
        self.async_write_ha_state()


class SolaxEVQRCodeText(_SolaxEVTextEntity):
    """Staged EV charger QR code text."""

    FIELD_SLUG = "ev_charger_qr_code"
    STATE_KEY = "qr_code"
    _attr_translation_key = "ev_charger_qr_code"
    _attr_native_max = 255


class SolaxEVOcppUrlText(_SolaxEVTextEntity):
    """Staged EV charger OCPP URL text."""

    FIELD_SLUG = "ev_charger_ocpp_url"
    STATE_KEY = "ocpp_url"
    _attr_translation_key = "ev_charger_ocpp_url"
    _attr_native_max = 128


class SolaxEVOcppChargerIdText(_SolaxEVTextEntity):
    """Staged EV charger OCPP charger ID text."""

    FIELD_SLUG = "ev_charger_ocpp_charger_id"
    STATE_KEY = "ocpp_charger_id"
    _attr_translation_key = "ev_charger_ocpp_charger_id"
    _attr_native_max = 25
