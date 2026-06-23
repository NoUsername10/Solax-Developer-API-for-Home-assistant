"""Shared entity helpers for the SolaX Developer API integration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENTITY_PREFIX,
    CONF_SYSTEM_NAME,
    DEFAULT_SYSTEM_NAME,
    DOMAIN,
    config_value,
)
from .i18n import translate


def system_identity(hass: Any, entry: Any) -> tuple[str, str]:
    """Return the configured system name and stable entity prefix."""
    system_name = str(
        config_value(entry, CONF_SYSTEM_NAME, DEFAULT_SYSTEM_NAME) or ""
    ).strip()
    if not system_name:
        raise ValueError(
            translate(
                hass,
                "runtime.errors.system_name_required",
                fallback="System name is required",
            )
        )

    system_slug = str(
        config_value(
            entry,
            CONF_ENTITY_PREFIX,
            system_name.lower().replace(" ", "_").replace("-", "_"),
        )
    ).strip()
    return system_name, system_slug


def system_device_info(
    hass: Any,
    coordinator: Any,
    system_name: str,
    system_slug: str,
) -> DeviceInfo:
    """Return consistent registry information for the System Totals device."""
    devices = (coordinator.data or {}).get("devices") or {}
    inverter_count = sum(
        1
        for device in devices.values()
        if int((device or {}).get("deviceType") or 0) == 1
    )
    model = translate(
        hass,
        "runtime.device_model.system.single_inverter"
        if inverter_count == 1
        else "runtime.device_model.system.multi_inverter",
        fallback=(
            "Single Inverter System"
            if inverter_count == 1
            else "Multi-Inverter System"
        ),
    )
    return DeviceInfo(
        identifiers={(DOMAIN, f"system_{system_slug}")},
        name=translate(
            hass,
            "runtime.entity_templates.system_totals_name",
            placeholders={"system_name": system_name},
            fallback="{system_name} System Totals",
        ),
        manufacturer="SolaX",
        model=model,
    )


class SolaxSystemCoordinatorEntity(CoordinatorEntity):
    """Coordinator entity attached to the shared System Totals device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Any,
        *,
        system_name: str,
        system_slug: str,
    ) -> None:
        super().__init__(coordinator)
        self._system_name = system_name
        self._system_slug = system_slug

    @property
    def device_info(self) -> DeviceInfo:
        """Return the shared System Totals device."""
        return system_device_info(
            self.coordinator.hass,
            self.coordinator,
            self._system_name,
            self._system_slug,
        )
