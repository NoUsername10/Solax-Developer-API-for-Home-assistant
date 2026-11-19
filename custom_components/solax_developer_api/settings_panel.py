"""Admin-only read model and hidden GUI settings panel.

The panel submits changes through Home Assistant's existing options flow. This
module exposes only the inventory needed to present saved inverter profiles.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components import panel_custom, websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_INVERTER_MODE_CONTROLS_ENABLED,
    CONF_INVERTER_MODE_DEBUG_TEST_ENABLED,
    DOMAIN,
)
from .inverter_modes import (
    MODE_FIELDS,
    MODE_SERVICES,
    SCHEDULE_PAIRS,
    inverter_family,
    mode_profiles,
)
from .inverter_mode_diagnostic import run_inverter_mode_diagnostic

PANEL_URL_PATH = "solax-developer-api-settings"
PANEL_ELEMENT = "solax-developer-settings-panel"
SNAPSHOT_COMMAND = f"{DOMAIN}/settings_snapshot"
DIAGNOSTIC_COMMAND = f"{DOMAIN}/run_inverter_mode_diagnostic"


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
                "debug_test_enabled": bool(
                    entry.options.get(CONF_INVERTER_MODE_DEBUG_TEST_ENABLED, False)
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


@websocket_api.websocket_command(
    {
        "type": DIAGNOSTIC_COMMAND,
        "entry_id": str,
        "serial": str,
        "mode": str,
        "profile_id": str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def async_run_inverter_mode_diagnostic(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Run one reviewed profile and return a copyable, redacted timeline."""
    if any(not isinstance(msg.get(key), str) or not msg[key] for key in (
        "entry_id", "serial", "mode", "profile_id"
    )):
        connection.send_error(msg["id"], "invalid_request", "Select a saved work-mode profile")
        return
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "entry_not_found", "Integration entry was not found")
        return
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        connection.send_error(msg["id"], "entry_not_loaded", "Integration is not loaded")
        return
    if not entry.options.get(CONF_INVERTER_MODE_DEBUG_TEST_ENABLED, False):
        connection.send_error(
            msg["id"],
            "diagnostic_disabled",
            "Enable the debug test button under Advanced first",
        )
        return
    if runtime.inverter_diagnostic_lock.locked():
        connection.send_error(msg["id"], "diagnostic_busy", "A diagnostic is already running")
        return
    async with runtime.inverter_diagnostic_lock:
        try:
            result = await run_inverter_mode_diagnostic(
                runtime.coordinator,
                serial=msg["serial"],
                mode=msg["mode"],
                profile_id=msg["profile_id"],
            )
        except ValueError:
            connection.send_error(
                msg["id"], "invalid_profile", "The saved profile is unavailable or invalid"
            )
            return
    connection.send_result(msg["id"], result)


async def async_register_settings_panel(hass: HomeAssistant, *, version: str) -> None:
    """Expose the page without adding a sidebar item."""
    websocket_api.async_register_command(hass, async_settings_snapshot)
    websocket_api.async_register_command(hass, async_run_inverter_mode_diagnostic)
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
