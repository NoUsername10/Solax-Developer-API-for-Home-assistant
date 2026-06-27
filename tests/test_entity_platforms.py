from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.solax_developer_api import button, number, select, switch, text, time
from custom_components.solax_developer_api.entity import (
    SolaxSystemCoordinatorEntity,
    system_device_info,
    system_identity,
)
from custom_components.solax_developer_api.ev_charger import (
    SolaxEVChargerEntity,
    _device_model_text,
    _device_type_text,
    ev_charger_devices,
    translated_option,
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
        self.ev_charger_controls_enabled = False
        self.available_control_services = set()
        self.ev_commands = []
        self.force_unaccepted = False
        self.force_value_error = None

    async def async_start_live_view(self):
        self.started += 1
        return {"ok": True}

    async def async_stop_live_view(self):
        self.stopped += 1
        return {"ok": True}

    def async_add_listener(self, listener):
        self.listener = listener
        return lambda: None

    def get_known_ev_charger_serial(self, serial):
        device = (self.data.get("devices") or {}).get(serial)
        if not device or int(device.get("deviceType") or 0) != 4:
            return None
        return {
            "serial": serial,
            "source": "inventory",
            "business_type": int(device.get("businessType") or 1),
            "device": dict(device),
        }

    async def async_execute_ev_charger_control(self, *, service, endpoint, payload):
        if self.force_value_error:
            raise ValueError(self.force_value_error)
        accepted = not self.force_unaccepted
        event = {
            "service": service,
            "endpoint": endpoint,
            "payload": payload,
            "accepted": accepted,
            "device_statuses": {
                payload["snList"][0]: {
                    "status": 3 if accepted else 5,
                    "status_name": (
                        "Command issuance succeeded"
                        if accepted
                        else "Device execution failed"
                    ),
                }
            },
        }
        self.ev_commands.append(event)
        return event


class _EntryWithUnload(SimpleNamespace):
    def async_on_unload(self, callback):
        self.unload_callback = callback


def _entry(*, system_name="SDS", prefix="sds", with_unload=False):
    cls = _EntryWithUnload if with_unload else SimpleNamespace
    return cls(
        entry_id="entry-1",
        data={},
        options={"system_name": system_name, "entity_prefix": prefix},
    )


def _add_ev_charger(coordinator, serial="EVC-1", **extra):
    payload = {
        "deviceSn": serial,
        "deviceType": 4,
        "businessType": 1,
        "deviceModel": 1,
    }
    payload.update(extra)
    coordinator.data.setdefault("devices", {})[serial] = payload
    return payload


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
async def test_ev_charger_button_entities_attach_to_ev_device(monkeypatch):
    entry = _entry()
    hass = _Hass(entry)
    coordinator = _Coordinator(hass)
    coordinator.data["devices"]["EVC-1"] = {
        "deviceSn": "EVC-1",
        "deviceType": 4,
        "businessType": 1,
        "deviceModel": 1,
    }
    coordinator.ev_charger_controls_enabled = True
    coordinator.available_control_services = {"set_evc_charge_command"}
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    added = []
    monkeypatch.setattr(SolaxEVChargerEntity, "async_write_ha_state", lambda self: None)

    await button.async_setup_entry(hass, entry, added.extend)

    start = next(entity for entity in added if entity.translation_key == "ev_charger_start_charging")
    assert start.entity_id == "button.sds_ev_charger_start_charging_device_evc_1"
    assert start.device_info["identifiers"] == {("solax_developer_api", "EVC-1")}

    await start.async_press()
    assert coordinator.ev_commands[-1]["service"] == "set_evc_charge_command"
    assert coordinator.ev_commands[-1]["payload"]["workCmd"] == 2
    assert coordinator.ev_commands[-1]["payload"]["snList"] == ["EVC-1"]


@pytest.mark.asyncio
async def test_ev_charger_gui_controls_validate_and_send(monkeypatch):
    entry = _entry()
    hass = _Hass(entry)
    coordinator = _Coordinator(hass)
    _add_ev_charger(coordinator)
    coordinator.data["device_realtime"] = {
        "EVC-1": {
            "workMode": 2,
            "currentGear": 16,
            "startMode": 2,
            "chargerScene": 1,
            "currentLimit": "18",
        }
    }
    coordinator.ev_charger_controls_enabled = True
    coordinator.available_control_services = {
        "set_charge_scene",
        "set_evc_qr_code",
        "set_evc_work_mode",
        "set_evc_start_mode",
        "set_evc_reserve_charge",
        "set_evc_current_limit",
    }
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    monkeypatch.setattr(SolaxEVChargerEntity, "async_write_ha_state", lambda self: None)

    select_entities = []
    number_entities = []
    text_entities = []
    time_entities = []
    await select.async_setup_entry(hass, entry, select_entities.extend)
    await number.async_setup_entry(hass, entry, number_entities.extend)
    await text.async_setup_entry(hass, entry, text_entities.extend)
    await time.async_setup_entry(hass, entry, time_entities.extend)

    work_mode = next(entity for entity in select_entities if entity.translation_key == "ev_charger_work_mode")
    await work_mode.async_select_option("ECO 16 A")
    assert coordinator.ev_commands[-1]["payload"]["workMode"] == 2
    assert coordinator.ev_commands[-1]["payload"]["currentGear"] == 16
    assert work_mode.current_option == "ECO 16 A"

    start_mode = next(entity for entity in select_entities if entity.translation_key == "ev_charger_start_mode")
    assert start_mode.current_option == "APP"
    await start_mode.async_select_option("APP")
    assert coordinator.ev_commands[-1]["payload"]["startMode"] == 2

    scene = next(entity for entity in select_entities if entity.translation_key == "ev_charger_charge_scene")
    scene._ev_gui_state["ocpp_url"] = "wss://example.com/ocpp"
    scene._ev_gui_state["ocpp_charger_id"] = "charger-1"
    await scene.async_select_option("OCPP")
    assert coordinator.ev_commands[-1]["payload"]["chargerScene"] == 1
    assert coordinator.ev_commands[-1]["payload"]["ocppUrl"] == "wss://example.com/ocpp"
    assert scene.current_option == "OCPP"

    current_limit = next(entity for entity in number_entities if entity.translation_key == "ev_charger_current_limit")
    assert current_limit.native_value == 18.0
    await current_limit.async_set_native_value(24)
    assert coordinator.ev_commands[-1]["payload"]["currentLimit"] == 24
    assert current_limit.native_value == 24.0

    reserve_current = next(entity for entity in number_entities if entity.translation_key == "ev_charger_reserve_current")
    assert reserve_current.native_value == 16.0
    await reserve_current.async_set_native_value(20)
    assert reserve_current.native_value == 20.0

    qr = next(entity for entity in text_entities if entity.translation_key == "ev_charger_qr_code")
    await qr.async_set_value("qr-value")
    assert qr.native_value == "qr-value"

    reserve_start = next(entity for entity in time_entities if entity.translation_key == "ev_charger_reserve_start_time")
    assert reserve_start.native_value.hour == 8
    from datetime import time as dt_time

    await reserve_start.async_set_value(dt_time(9, 30))
    assert reserve_start.native_value.hour == 9


@pytest.mark.asyncio
async def test_ev_charger_apply_buttons_use_staged_values(monkeypatch):
    entry = _entry()
    hass = _Hass(entry)
    coordinator = _Coordinator(hass)
    _add_ev_charger(coordinator)
    coordinator.ev_charger_controls_enabled = True
    coordinator.available_control_services = {
        "set_charge_scene",
        "set_evc_qr_code",
        "set_evc_reserve_charge",
    }
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    monkeypatch.setattr(SolaxEVChargerEntity, "async_write_ha_state", lambda self: None)
    added = []

    await button.async_setup_entry(hass, entry, added.extend)

    scene = next(entity for entity in added if entity.translation_key == "ev_charger_apply_charge_scene")
    scene._ev_gui_state.update(
        {
            "charger_scene": 1,
            "ocpp_url": "wss://example.com/ocpp",
            "ocpp_charger_id": "charger-1",
        }
    )
    await scene.async_press()
    assert coordinator.ev_commands[-1]["service"] == "set_charge_scene"
    assert coordinator.ev_commands[-1]["payload"]["ocppChargerId"] == "charger-1"

    qr = next(entity for entity in added if entity.translation_key == "ev_charger_apply_qr_code")
    qr._ev_gui_state["qr_code"] = "qr-value"
    await qr.async_press()
    assert coordinator.ev_commands[-1]["payload"]["qrCode"] == "qr-value"

    reserve = next(entity for entity in added if entity.translation_key == "ev_charger_apply_reserve_charge")
    reserve._ev_gui_state.update(
        {
            "reserve_start_time": "08:15",
            "reserve_end_time": "10:45",
            "reserve_current": 22,
        }
    )
    await reserve.async_press()
    assert coordinator.ev_commands[-1]["payload"]["chargeStartTime"] == "08:15"
    assert coordinator.ev_commands[-1]["payload"]["chargeCurrent"] == 22


@pytest.mark.asyncio
async def test_ev_charger_controls_raise_when_option_disabled(monkeypatch):
    hass = _Hass()
    coordinator = _Coordinator(hass)
    coordinator.data["devices"]["EVC-1"] = {
        "deviceSn": "EVC-1",
        "deviceType": 4,
        "businessType": 1,
    }
    coordinator.available_control_services = {"set_evc_charge_command"}
    monkeypatch.setattr(SolaxEVChargerEntity, "async_write_ha_state", lambda self: None)
    entity = button.SolaxEVChargeCommandButton(
        coordinator=coordinator,
        system_slug="sds",
        device=coordinator.data["devices"]["EVC-1"],
        translation_key="ev_charger_start_charging",
        field_slug="start_charging",
        work_cmd=2,
    )

    assert entity.available is False
    with pytest.raises(HomeAssistantError, match="EV charger controls are disabled"):
        await entity.async_press()


@pytest.mark.asyncio
async def test_ev_charger_control_error_paths(monkeypatch):
    hass = _Hass()
    coordinator = _Coordinator(hass)
    device = _add_ev_charger(coordinator)
    coordinator.ev_charger_controls_enabled = True
    coordinator.available_control_services = {"set_evc_charge_command"}
    monkeypatch.setattr(SolaxEVChargerEntity, "async_write_ha_state", lambda self: None)
    entity = button.SolaxEVChargeCommandButton(
        coordinator=coordinator,
        system_slug="sds",
        device=device,
        translation_key="ev_charger_start_charging",
        field_slug="start_charging",
        work_cmd=2,
    )

    with pytest.raises(HomeAssistantError, match="not an EV charger control service"):
        await entity._execute_evc_service("not_real", entity._payload_base())

    coordinator.available_control_services = set()
    with pytest.raises(HomeAssistantError, match="no compatible device capability"):
        await entity.async_press()

    coordinator.available_control_services = {"set_evc_charge_command"}
    coordinator.force_value_error = "control_ev_charger_target_unknown"
    with pytest.raises(HomeAssistantError, match="discovered EV chargers"):
        await entity.async_press()

    coordinator.force_value_error = None
    coordinator.force_unaccepted = True
    with pytest.raises(HomeAssistantError, match="did not accept"):
        await entity.async_press()


def test_ev_charger_helper_edge_cases():
    hass = _Hass()
    coordinator = _Coordinator(hass)
    coordinator.data["devices"] = {
        "": {"deviceSn": "", "deviceType": 4},
        "bad-map": "not-a-map",
        "bad-type": {"deviceSn": "BAD", "deviceType": "x"},
        "fallback-serial": {"deviceSn": "", "deviceType": 4},
        "bad-business": {"deviceSn": "EVC-B", "deviceType": 4, "businessType": "x"},
    }

    assert ev_charger_devices(coordinator) == [
        {"deviceSn": "EVC-B", "deviceType": 4, "businessType": 1},
        {"deviceSn": "fallback-serial", "deviceType": 4, "businessType": 1},
    ]
    assert _device_type_text(hass, "bad") == "Device"
    assert _device_model_text(hass, "bad") == "bad"
    assert translated_option(hass, "work_mode", "fast", "FAST") == "FAST"


@pytest.mark.asyncio
async def test_ev_charger_dynamic_platform_listeners(monkeypatch):
    hass = _Hass()
    coordinator = _Coordinator(hass)
    coordinator.ev_charger_controls_enabled = True
    coordinator.available_control_services = {
        "set_evc_charge_command",
        "set_evc_work_mode",
        "set_evc_current_limit",
    }
    monkeypatch.setattr(SolaxEVChargerEntity, "async_write_ha_state", lambda self: None)

    for platform in (button, select, number, text, time):
        entry = _entry(with_unload=True)
        entry.runtime_data = SimpleNamespace(coordinator=coordinator)
        added = []
        await platform.async_setup_entry(hass, entry, added.extend)
        before = len(added)
        _add_ev_charger(coordinator, serial=f"EVC-{platform.__name__.rsplit('.', 1)[-1]}")
        coordinator.listener()
        assert len(added) > before


@pytest.mark.asyncio
async def test_ev_charger_select_and_number_fallbacks(monkeypatch):
    hass = _Hass()
    coordinator = _Coordinator(hass)
    device = _add_ev_charger(coordinator)
    coordinator.ev_charger_controls_enabled = True
    coordinator.available_control_services = {
        "set_evc_work_mode",
        "set_evc_start_mode",
        "set_charge_scene",
        "set_evc_current_limit",
    }
    monkeypatch.setattr(SolaxEVChargerEntity, "async_write_ha_state", lambda self: None)

    work = select.SolaxEVWorkModeSelect(
        coordinator=coordinator,
        system_slug="sds",
        device=device,
    )
    assert work.current_option is None
    coordinator.data["device_realtime"] = {"EVC-1": {"deviceWorkingMode": 1}}
    assert work.current_option == "FAST"

    start = select.SolaxEVStartModeSelect(
        coordinator=coordinator,
        system_slug="sds",
        device=device,
    )
    assert start.current_option is None

    scene = select.SolaxEVChargeSceneSelect(
        coordinator=coordinator,
        system_slug="sds",
        device=device,
    )
    assert scene.current_option is None

    current = number.SolaxEVCurrentLimitNumber(
        coordinator=coordinator,
        system_slug="sds",
        device=device,
    )
    assert current.native_value is None

    reserve_start = time.SolaxEVReserveStartTime(
        coordinator=coordinator,
        system_slug="sds",
        device=device,
    )
    reserve_start._ev_gui_state["reserve_start_time"] = "bad"
    assert reserve_start.native_value.hour == 8

    coordinator._ev_charger_gui_state = {"EVC-1": "bad"}
    assert reserve_start._ev_gui_state == {}


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
