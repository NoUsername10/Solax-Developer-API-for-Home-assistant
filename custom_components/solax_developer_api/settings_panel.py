"""Admin-only read model and hidden GUI settings panel.

The panel submits changes through Home Assistant's existing options flow. This
module exposes only the inventory needed to present saved inverter profiles.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components import panel_custom, websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import CONF_INVERTER_MODE_CONTROLS_ENABLED, DOMAIN
from .inverter_modes import (
    MODE_FIELDS,
    MODE_SERVICES,
    SCHEDULE_PAIRS,
    inverter_family,
    mode_profiles,
)

PANEL_URL_PATH = "solax-developer-api-settings"
PANEL_ELEMENT = "solax-developer-settings-panel"
SNAPSHOT_COMMAND = f"{DOMAIN}/settings_snapshot"


def settings_snapshot_payload(hass: HomeAssistant) -> dict[str, Any]:
    """Build profile metadata without any connection credentials."""
    entries: list[dict[str, Any]] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        coordinator = getattr(runtime, "coordinator", None)
        devices = ((coordinator.data or {}).get("devices") or {}) if coordinator else {}
        inverters: list[dict[str, Any]] = []
        if isinstance(devices, Mapping):
            for serial, device in devices.items():
                if not isinstance(device, Mapping):
                    continue
                family = inverter_family(device)
                if family is None or str(device.get("deviceSn") or "") != str(serial):
                    continue
                profiles: list[dict[str, Any]] = []
                for mode in MODE_SERVICES[family]:
                    visible_fields = set(MODE_FIELDS[family][mode])
                    if family == "standard" and mode != "manual":
                        visible_fields.update(
                            {"schedule_enabled", "enable_time_period2"}
                        )
                        visible_fields.update(
                            key for pair in SCHEDULE_PAIRS for key in pair
                        )
                    for profile_id, saved in mode_profiles(entry.options, str(serial), mode).items():
                        profiles.append(
                            {
                                "mode": mode,
                                "id": profile_id,
                                "name": str(saved.get("name") or "Default"),
                                "settings": {
                                    key: value
                                    for key, value in saved.items()
                                    if key in visible_fields
                                    and isinstance(value, (str, bool, int, float))
                                },
                            }
                        )
                inverters.append(
                    {
                        "serial": str(serial),
                        "family": family,
                        "modes": list(MODE_SERVICES[family]),
                        "profiles": profiles,
                    }
                )
        entries.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "controls_enabled": bool(
                    entry.options.get(CONF_INVERTER_MODE_CONTROLS_ENABLED, False)
                ),
                "inverters": inverters,
            }
        )
    return {"entries": entries}


@websocket_api.websocket_command({"type": SNAPSHOT_COMMAND})
@websocket_api.require_admin
@callback
def async_settings_snapshot(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return only admin-facing profile metadata, never credentials."""
    connection.send_result(msg["id"], settings_snapshot_payload(hass))


async def async_register_settings_panel(hass: HomeAssistant, *, version: str) -> None:
    """Expose the page without adding a sidebar item."""
    websocket_api.async_register_command(hass, async_settings_snapshot)
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_ELEMENT,
        frontend_url_path=PANEL_URL_PATH,
        module_url=(
            f"/api/{DOMAIN}/frontend/solax-settings-panel.js?v={version}"
        ),
        sidebar_title=None,
        require_admin=True,
    )
