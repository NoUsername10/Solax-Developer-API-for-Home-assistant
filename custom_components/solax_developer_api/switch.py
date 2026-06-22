"""Switch entities for SolaX Developer API integration."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .i18n import translate
from .const import (
    CONF_ENTITY_PREFIX,
    CONF_RATE_LIMIT_NOTIFICATIONS,
    CONF_SYSTEM_NAME,
    DOMAIN,
)


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


class SolaxRateLimitNotificationSwitch(CoordinatorEntity, SwitchEntity):
    """Toggle persistent notifications for rate-limit events."""

    _attr_has_entity_name = False

    def __init__(self, *, hass, entry_id: str, coordinator, system_name: str, system_slug: str):
        super().__init__(coordinator)
        self.hass = hass
        self._entry_id = entry_id
        self._system_name = system_name
        self._system_slug = system_slug
        self._attr_name = translate(
            hass,
            "runtime.entity_names.switch.rate_limit_notifications",
            fallback="API Rate Limit Notifications",
        )
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

    @property
    def device_info(self):
        return _system_device_info(
            self.hass,
            self.coordinator,
            self._system_name,
            self._system_slug,
        )

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


class SolaxLiveViewSwitch(CoordinatorEntity, SwitchEntity):
    """Toggle temporary live view polling mode."""

    _attr_has_entity_name = False

    def __init__(self, *, hass, entry_id: str, coordinator, system_name: str, system_slug: str):
        super().__init__(coordinator)
        self.hass = hass
        self._entry_id = entry_id
        self._system_name = system_name
        self._system_slug = system_slug
        self._attr_name = translate(
            hass,
            "runtime.entity_names.switch.live_view_mode",
            fallback="Live View Mode",
        )
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

    @property
    def device_info(self):
        return _system_device_info(
            self.hass,
            self.coordinator,
            self._system_name,
            self._system_slug,
        )

    async def async_turn_on(self, **kwargs):
        _ = kwargs
        await self.coordinator.async_start_live_view()

    async def async_turn_off(self, **kwargs):
        _ = kwargs
        await self.coordinator.async_stop_live_view()
