"""GUI settings read model and panel registration use the existing options data."""

from types import SimpleNamespace

import pytest
from homeassistant.exceptions import Unauthorized

from custom_components.solax_developer_api import settings_panel


def test_snapshot_lists_profiles_without_credentials():
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="Solar home",
        data={"client_id": "private-id", "client_secret": "private-secret"},
        options={
            "inverter_mode_controls_enabled": True,
            "inverter_mode_profiles": {
                "INV-1": {
                    "self_use": {
                        "profiles": {
                            "stable-id": {
                                "name": "Cloudy",
                                "family": "standard",
                                "min_soc": 20,
                                "charge_from_grid_enable": True,
                                "client_secret": "must-not-leak",
                            }
                        }
                    }
                }
            },
        },
        runtime_data=SimpleNamespace(
            coordinator=SimpleNamespace(
                data={
                    "devices": {
                        "INV-1": {
                            "deviceSn": "INV-1",
                            "deviceType": 1,
                            "deviceModel": 33,
                            "businessType": 1,
                        },
                        "METER-1": {
                            "deviceSn": "METER-1",
                            "deviceType": 3,
                            "deviceModel": 5,
                            "businessType": 1,
                        },
                    }
                }
            )
        ),
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_entries=lambda _domain: [entry])
    )

    result = settings_panel.settings_snapshot_payload(hass)
    assert result["entries"][0]["entry_id"] == "entry-1"
    inverter = result["entries"][0]["inverters"][0]
    assert inverter["serial"] == "INV-1"
    assert inverter["profiles"][0]["name"] == "Cloudy"
    assert inverter["profiles"][0]["id"] == "stable-id"
    assert "private-secret" not in str(result)
    assert "private-id" not in str(result)
    assert "must-not-leak" not in str(result)
    assert len(result["entries"][0]["inverters"]) == 1


def test_snapshot_handles_unloaded_entry_and_unknown_device():
    entry = SimpleNamespace(
        entry_id="entry-2",
        title="Unloaded",
        options={},
        runtime_data=None,
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_entries=lambda _domain: [entry])
    )
    result = settings_panel.settings_snapshot_payload(hass)
    assert result["entries"][0]["inverters"] == []
    assert result["entries"][0]["controls_enabled"] is False


def test_snapshot_ignores_invalid_device_records_and_a1_has_only_supported_modes():
    entry = SimpleNamespace(
        entry_id="entry-3",
        title="A1",
        options={},
        runtime_data=SimpleNamespace(
            coordinator=SimpleNamespace(
                data={
                    "devices": {
                        "invalid": None,
                        "mismatch": {
                            "deviceSn": "other",
                            "deviceType": 1,
                            "deviceModel": 33,
                            "businessType": 1,
                        },
                        "A1": {
                            "deviceSn": "A1",
                            "deviceType": 1,
                            "deviceModel": 19,
                            "businessType": 1,
                        },
                    }
                }
            )
        ),
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_entries=lambda _domain: [entry])
    )
    inverters = settings_panel.settings_snapshot_payload(hass)["entries"][0]["inverters"]
    assert len(inverters) == 1
    assert inverters[0]["family"] == "a1_hybrid_g2"
    assert inverters[0]["modes"] == ["self_use", "feed_in_priority", "back_up"]


def test_snapshot_websocket_requires_admin():
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_entries=lambda _domain: [])
    )
    results = []
    connection = SimpleNamespace(
        user=SimpleNamespace(is_admin=True),
        send_result=lambda message_id, payload: results.append((message_id, payload)),
    )
    settings_panel.async_settings_snapshot(hass, connection, {"id": 42})
    assert results == [(42, {"entries": []})]

    connection.user.is_admin = False
    with pytest.raises(Unauthorized):
        settings_panel.async_settings_snapshot(hass, connection, {"id": 43})


@pytest.mark.asyncio
async def test_register_panel_is_hidden_and_admin_only(monkeypatch):
    calls = {}

    def register_command(_hass, command):
        calls["command"] = command

    async def register_panel(_hass, **kwargs):
        calls["panel"] = kwargs

    monkeypatch.setattr(settings_panel.websocket_api, "async_register_command", register_command)
    monkeypatch.setattr(settings_panel.panel_custom, "async_register_panel", register_panel)
    await settings_panel.async_register_settings_panel(SimpleNamespace(), version="v0.4.11")
    assert calls["command"] is settings_panel.async_settings_snapshot
    assert calls["panel"]["sidebar_title"] is None
    assert calls["panel"]["require_admin"] is True
    assert "solax-settings-panel.js" in calls["panel"]["module_url"]
