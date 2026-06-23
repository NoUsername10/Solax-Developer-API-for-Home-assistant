"""Switch entities for SolaX Developer API integration."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity

from .const import CONF_RATE_LIMIT_NOTIFICATIONS
from .entity import SolaxSystemCoordinatorEntity, system_identity

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data.coordinator
    system_name, system_slug = system_identity(hass, entry)

    async_add_entities(
        [
            SolaxRateLimitNotificationSwitch(
                hass=hass,
                entry_id=entry.entry_id,
                coordinator=coordinator,
                system_name=system_name,
                system_slug=system_slug,
            ),
            SolaxLiveViewSwitch(
                hass=hass,
                entry_id=entry.entry_id,
                coordinator=coordinator,
                system_name=system_name,
                system_slug=system_slug,
            ),
        ]
    )


class SolaxRateLimitNotificationSwitch(SolaxSystemCoordinatorEntity, SwitchEntity):
    """Toggle persistent notifications for rate-limit events."""

    _attr_translation_key = "rate_limit_notifications"

    def __init__(self, *, hass, entry_id: str, coordinator, system_name: str, system_slug: str):
        super().__init__(
            coordinator,
            system_name=system_name,
            system_slug=system_slug,
        )
        self.hass = hass
        self._entry_id = entry_id
        self._attr_unique_id = f"{system_slug}_rate_limit_notifications_solax"
        self.entity_id = f"switch.{system_slug}_rate_limit_notifications"

    @property
    def is_on(self):
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return True
        return bool(entry.options.get(CONF_RATE_LIMIT_NOTIFICATIONS, True))

    @property
    def available(self):
        return True

    async def async_turn_on(self, **kwargs):
        _ = kwargs
        await self._async_set_notification_state(True)

    async def async_turn_off(self, **kwargs):
        _ = kwargs
        await self._async_set_notification_state(False)

    async def _async_set_notification_state(self, enabled: bool):
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return

        updated_options = dict(entry.options)
        updated_options[CONF_RATE_LIMIT_NOTIFICATIONS] = enabled
        self.hass.config_entries.async_update_entry(entry, options=updated_options)
        self.async_write_ha_state()


class SolaxLiveViewSwitch(SolaxSystemCoordinatorEntity, SwitchEntity):
    """Toggle temporary live view polling mode."""

    _attr_translation_key = "live_view_mode"

    def __init__(self, *, hass, entry_id: str, coordinator, system_name: str, system_slug: str):
        super().__init__(
            coordinator,
            system_name=system_name,
            system_slug=system_slug,
        )
        self.hass = hass
        self._entry_id = entry_id
        self._attr_unique_id = f"{system_slug}_live_view_mode_solax"
        self.entity_id = f"switch.{system_slug}_live_view_mode"

    @property
    def is_on(self):
        return bool(self.coordinator.live_view_active)

    @property
    def available(self):
        return True

    @property
    def extra_state_attributes(self):
        meta = (self.coordinator.data or {}).get("meta") or {}
        return {
            "poll_profile": meta.get("poll_profile"),
            "effective_scan_interval": meta.get("effective_scan_interval"),
            "live_view_until": meta.get("live_view_until"),
            "live_view_remaining_seconds": meta.get("live_view_remaining_seconds"),
        }

    async def async_turn_on(self, **kwargs):
        _ = kwargs
        await self.coordinator.async_start_live_view()

    async def async_turn_off(self, **kwargs):
        _ = kwargs
        await self.coordinator.async_stop_live_view()
