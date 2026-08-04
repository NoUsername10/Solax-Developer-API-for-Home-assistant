"""Switch entities for SolaX Developer API integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_RATE_LIMIT_NOTIFICATIONS
from .coordinator import SolaxDeveloperCoordinator
from .entity import SolaxSystemCoordinatorEntity, system_identity
from .runtime import SolaxConfigEntry

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolaxConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
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

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        entry_id: str,
        coordinator: SolaxDeveloperCoordinator,
        system_name: str,
        system_slug: str,
    ) -> None:
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
    def is_on(self) -> bool:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return True
        return bool(entry.options.get(CONF_RATE_LIMIT_NOTIFICATIONS, True))

    @property
    def available(self) -> bool:
        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        _ = kwargs
        await self._async_set_notification_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        _ = kwargs
        await self._async_set_notification_state(False)

    async def _async_set_notification_state(self, enabled: bool) -> None:
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

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        entry_id: str,
        coordinator: SolaxDeveloperCoordinator,
        system_name: str,
        system_slug: str,
    ) -> None:
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
    def is_on(self) -> bool:
        return bool(self.coordinator.live_view_active)

    @property
    def available(self) -> bool:
        return True

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        meta = (self.coordinator.data or {}).get("meta") or {}
        return {
            "poll_profile": meta.get("poll_profile"),
            "effective_scan_interval": meta.get("effective_scan_interval"),
            "live_view_until": meta.get("live_view_until"),
            "live_view_remaining_seconds": meta.get("live_view_remaining_seconds"),
            "live_view_target_interval": meta.get("live_view_target_interval"),
            "live_view_budget_adjusted": meta.get("live_view_budget_adjusted"),
            "live_view_call_budget_per_minute": meta.get("live_view_call_budget_per_minute"),
            "live_view_estimated_calls_per_cycle": meta.get(
                "live_view_estimated_calls_per_cycle"
            ),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        _ = kwargs
        await self.coordinator.async_start_live_view()

    async def async_turn_off(self, **kwargs: Any) -> None:
        _ = kwargs
        await self.coordinator.async_stop_live_view()
