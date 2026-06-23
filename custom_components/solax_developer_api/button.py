"""Button entities for SolaX Developer API integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .entity import SolaxSystemCoordinatorEntity, system_identity

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data.coordinator
    system_name, system_slug = system_identity(hass, entry)
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


class SolaxLiveViewBoostButton(SolaxSystemCoordinatorEntity, ButtonEntity):
    """Start temporary live-view refresh profile."""

    _attr_translation_key = "live_view_boost"

    def __init__(self, *, hass, coordinator, system_name: str, system_slug: str):
        super().__init__(
            coordinator,
            system_name=system_name,
            system_slug=system_slug,
        )
        self.hass = hass
        self._attr_unique_id = f"{system_slug}_live_view_boost_solax"
        self.entity_id = f"button.{system_slug}_live_view_boost"

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
