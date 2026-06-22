"""Button entities for SolaX Developer API integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .i18n import translate
from .const import CONF_ENTITY_PREFIX, CONF_SYSTEM_NAME, DOMAIN


def _system_device_info(hass, coordinator, system_name: str, system_slug: str):
    total_devices = len((coordinator.data or {}).get("devices") or {})
    model = translate(
        hass,
        "runtime.device_model.system.single_device"
        if total_devices == 1
        else "runtime.device_model.system.multi_device",
        fallback="Single Device System" if total_devices == 1 else "Multi-Device System",
    )
    return {
        "identifiers": {(DOMAIN, f"system_{system_slug}")},
        "name": translate(
            hass,
            "runtime.entity_templates.system_totals_name",
            placeholders={"system_name": system_name},
            fallback="{system_name} System Totals",
        ),
        "manufacturer": "SolaX",
        "model": model,
    }


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    system_name = entry.data.get(CONF_SYSTEM_NAME)
    if not system_name:
        raise ValueError(
            translate(
                hass,
                "runtime.errors.system_name_required",
                fallback="System name is required",
            )
        )

    system_slug = entry.data.get(
        CONF_ENTITY_PREFIX,
        system_name.lower().replace(" ", "_").replace("-", "_"),
    )
    async_add_entities(
        [
            SolaxLiveViewBoostButton(
                hass=hass,
                coordinator=coordinator,
                system_name=system_name,
                system_slug=system_slug,
            ),
        ]
    )


class SolaxLiveViewBoostButton(CoordinatorEntity, ButtonEntity):
    """Start temporary live-view refresh profile."""

    _attr_has_entity_name = False

    def __init__(self, *, hass, coordinator, system_name: str, system_slug: str):
        super().__init__(coordinator)
        self.hass = hass
        self._system_name = system_name
        self._system_slug = system_slug
        self._attr_name = translate(
            hass,
            "runtime.entity_names.button.live_view_boost",
            fallback="Start Live View Boost",
        )
        self._attr_unique_id = f"{system_slug}_live_view_boost_solax"
        self.entity_id = f"button.{system_slug}_live_view_boost"

    @property
    def device_info(self):
        return _system_device_info(
            self.hass,
            self.coordinator,
            self._system_name,
            self._system_slug,
        )

    @property
    def extra_state_attributes(self):
        meta = (self.coordinator.data or {}).get("meta") or {}
        return {
            "poll_profile": meta.get("poll_profile"),
            "effective_scan_interval": meta.get("effective_scan_interval"),
            "live_view_active": meta.get("live_view_active"),
        }

    async def async_press(self) -> None:
        await self.coordinator.async_start_live_view()
