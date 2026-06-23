from types import SimpleNamespace

import pytest

from custom_components.solax_developer_api import button, switch
from custom_components.solax_developer_api.entity import (
    SolaxSystemCoordinatorEntity,
    system_device_info,
    system_identity,
)


class _Config:
    language = "en"


class _ConfigEntries:
    def __init__(self, entry=None):
        self.entry = entry
        self.updates = []

    def async_get_entry(self, entry_id):
        if self.entry is not None and self.entry.entry_id == entry_id:
            return self.entry
        return None

    def async_update_entry(self, entry, **kwargs):
        self.updates.append((entry, kwargs))
        if "options" in kwargs:
            entry.options = kwargs["options"]


class _Hass:
    def __init__(self, entry=None):
        self.config = _Config()
        self.config_entries = _ConfigEntries(entry)


class _Coordinator:
    def __init__(self, hass):
        self.hass = hass
        self.data = {
            "devices": {
                "INV-1": {"deviceType": 1},
                "METER-1": {"deviceType": 3},
            },
            "meta": {
                "poll_profile": "live_view",
                "effective_scan_interval": 8,
                "live_view_active": True,
                "live_view_until": "2026-06-23T12:00:00+00:00",
                "live_view_remaining_seconds": 60,
            },
        }
        self.live_view_active = True
        self.started = 0
        self.stopped = 0

    async def async_start_live_view(self):
        self.started += 1
        return {"ok": True}

    async def async_stop_live_view(self):
        self.stopped += 1
        return {"ok": True}


def _entry(*, system_name="SDS", prefix="sds"):
    return SimpleNamespace(
        entry_id="entry-1",
        data={},
        options={"system_name": system_name, "entity_prefix": prefix},
    )


def test_system_identity_and_device_info_are_shared():
    entry = _entry()
    hass = _Hass(entry)
    coordinator = _Coordinator(hass)

    assert system_identity(hass, entry) == ("SDS", "sds")
    info = system_device_info(hass, coordinator, "SDS", "sds")

    assert info["identifiers"] == {("solax_developer_api", "system_sds")}
    assert info["name"] == "SDS System Totals"
    assert info["model"] == "Single Inverter System"


def test_system_identity_rejects_empty_name():
    entry = _entry(system_name="", prefix="")
    with pytest.raises(ValueError, match="System name is required"):
        system_identity(_Hass(entry), entry)


def test_system_entity_uses_multi_inverter_model():
    hass = _Hass()
    coordinator = _Coordinator(hass)
    coordinator.data["devices"]["INV-2"] = {"deviceType": 1}
    entity = SolaxSystemCoordinatorEntity(
        coordinator,
        system_name="SDS",
        system_slug="sds",
    )

    assert entity.device_info["model"] == "Multi-Inverter System"


@pytest.mark.asyncio
async def test_button_platform_setup_and_press():
    entry = _entry()
    hass = _Hass(entry)
    coordinator = _Coordinator(hass)
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    added = []

    await button.async_setup_entry(hass, entry, added.extend)

    assert len(added) == 1
    entity = added[0]
    assert entity.unique_id == "sds_live_view_boost_solax"
    assert entity.entity_id == "button.sds_live_view_boost"
    assert entity.extra_state_attributes["effective_scan_interval"] == 8
    assert entity.device_info["identifiers"] == {
        ("solax_developer_api", "system_sds")
    }

    await entity.async_press()
    assert coordinator.started == 1


@pytest.mark.asyncio
async def test_switch_platform_setup_and_actions(monkeypatch):
    entry = _entry()
    hass = _Hass(entry)
    coordinator = _Coordinator(hass)
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    added = []
    writes = []
    monkeypatch.setattr(
        switch.SolaxRateLimitNotificationSwitch,
        "async_write_ha_state",
        lambda self: writes.append(self.entity_id),
    )

    await switch.async_setup_entry(hass, entry, added.extend)

    assert len(added) == 2
    notifications, live_view = added
    assert notifications.available is True
    assert notifications.is_on is True
    assert live_view.available is True
    assert live_view.is_on is True
    assert live_view.extra_state_attributes["live_view_remaining_seconds"] == 60

    await notifications.async_turn_off(source="test")
    assert entry.options["rate_limit_notifications"] is False
    assert writes == ["switch.sds_rate_limit_notifications"]
    assert notifications.is_on is False

    await notifications.async_turn_on()
    assert entry.options["rate_limit_notifications"] is True

    await live_view.async_turn_on()
    await live_view.async_turn_off()
    assert coordinator.started == 1
    assert coordinator.stopped == 1


def test_notification_switch_defaults_on_when_entry_is_missing():
    hass = _Hass()
    coordinator = _Coordinator(hass)
    entity = switch.SolaxRateLimitNotificationSwitch(
        hass=hass,
        entry_id="missing",
        coordinator=coordinator,
        system_name="SDS",
        system_slug="sds",
    )

    assert entity.is_on is True


@pytest.mark.asyncio
async def test_notification_switch_ignores_removed_entry():
    hass = _Hass()
    coordinator = _Coordinator(hass)
    entity = switch.SolaxRateLimitNotificationSwitch(
        hass=hass,
        entry_id="missing",
        coordinator=coordinator,
        system_name="SDS",
        system_slug="sds",
    )

    await entity.async_turn_off()
    assert hass.config_entries.updates == []
