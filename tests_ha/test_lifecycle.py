"""Focused integration tests using Home Assistant's real config-entry lifecycle."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.solax_developer_api.api import SolaxApiError, SolaxDeveloperApiClient
from custom_components.solax_developer_api.const import (
    CONF_ALARM_NOTIFICATIONS,
    CONF_ALARM_SCAN_INTERVAL,
    CONF_ENTITY_PREFIX,
    CONF_MANUAL_METER_SERIALS,
    CONF_SCAN_INTERVAL,
    CONF_SYSTEM_NAME,
    DOMAIN,
    SERVICE_MANUAL_REFRESH,
)
from custom_components.solax_developer_api.diagnostics import (
    REDACTED_VALUE,
    async_get_config_entry_diagnostics,
)


@pytest.fixture
def solax_api(monkeypatch):
    state = {
        "plant_power": 500.0,
        "alarms": {"PLANT-1": []},
        "alarm_calls": [],
        "alarm_failures": set(),
        "temporary_failure": False,
    }

    async def page_plant_info(self, *, business_type, page_no=1, **kwargs):
        records = []
        if business_type == 1 and page_no == 1:
            records = [
                {
                    "plantId": "PLANT-1",
                    "plantName": "Fixture Plant",
                    "businessType": 1,
                }
            ]
        return {
            "code": 10000,
            "result": {"records": records, "current": page_no, "pages": 1},
        }

    async def page_device_info(
        self,
        *,
        business_type,
        device_type,
        page_no=1,
        **kwargs,
    ):
        records = []
        if business_type == 1 and device_type == 1 and page_no == 1:
            records = [
                {
                    "deviceSn": "INVERTER-1",
                    "plantId": "PLANT-1",
                    "deviceType": 1,
                    "businessType": 1,
                    "onlineStatus": 1,
                    "deviceModel": 19,
                }
            ]
        return {
            "code": 10000,
            "result": {"records": records, "current": page_no, "pages": 1},
        }

    async def plant_realtime_data(self, *, plant_id, business_type, **kwargs):
        if state["temporary_failure"]:
            raise SolaxApiError(
                code=10406,
                message="temporary rate limit",
                classification="rate_limit",
            )
        return {
            "code": 10000,
            "result": {
                "plantId": plant_id,
                "acPower": state["plant_power"],
                "dailyYield": 2.5,
            },
        }

    async def page_alarm_info(self, **kwargs):
        plant_id = kwargs["plant_id"]
        state["alarm_calls"].append(plant_id)
        if state["temporary_failure"] or plant_id in state["alarm_failures"]:
            raise SolaxApiError(
                code=10406,
                message="temporary rate limit",
                classification="rate_limit",
            )
        records = list(state["alarms"].get(plant_id, []))
        return {
            "code": 10000,
            "result": {"total": len(records), "records": records},
        }

    async def plant_stat_data(self, *, date_type, date, **kwargs):
        if state["temporary_failure"]:
            raise SolaxApiError(
                code=10406,
                message="temporary rate limit",
                classification="rate_limit",
            )
        return {
            "code": 10000,
            "result": {
                "plantEnergyStatDataList": [
                    {"date": date, "pvGeneration": float(date_type)}
                ]
            },
        }

    async def device_realtime_data(
        self,
        *,
        sn_list,
        device_type,
        business_type,
        **kwargs,
    ):
        return {
            "code": 10000,
            "result": [
                {
                    "deviceSn": serial,
                    "deviceType": device_type,
                    "businessType": business_type,
                    "totalActivePower": 250.0 if device_type == 1 else 75.0,
                    "importEnergy": 12.0 if device_type == 3 else None,
                }
                for serial in sn_list
            ],
        }

    async def get_master_control_device(self, **kwargs):
        return {"code": 10000, "result": []}

    monkeypatch.setattr(SolaxDeveloperApiClient, "page_plant_info", page_plant_info)
    monkeypatch.setattr(SolaxDeveloperApiClient, "page_device_info", page_device_info)
    monkeypatch.setattr(SolaxDeveloperApiClient, "plant_realtime_data", plant_realtime_data)
    monkeypatch.setattr(SolaxDeveloperApiClient, "page_alarm_info", page_alarm_info)
    monkeypatch.setattr(SolaxDeveloperApiClient, "plant_stat_data", plant_stat_data)
    monkeypatch.setattr(SolaxDeveloperApiClient, "device_realtime_data", device_realtime_data)
    monkeypatch.setattr(
        SolaxDeveloperApiClient,
        "get_master_control_device",
        get_master_control_device,
    )
    return state


def _entry(*, manual_meter: bool = True, alarm_notifications: bool = True):
    options = {
        CONF_SYSTEM_NAME: "HA Fixture",
        CONF_ENTITY_PREFIX: "ha_fixture",
        CONF_SCAN_INTERVAL: 120,
        CONF_ALARM_NOTIFICATIONS: alarm_notifications,
        CONF_ALARM_SCAN_INTERVAL: 120,
    }
    if manual_meter:
        options[CONF_MANUAL_METER_SERIALS] = [
            {"serial": "MANUAL-METER-1", "business_type": 4}
        ]
    return MockConfigEntry(
        domain=DOMAIN,
        title="HA Fixture",
        data={
            "client_id": "fixture-client-id",
            "client_secret": "fixture-client-secret",
            "api_region": "eu",
        },
        options=options,
        version=2,
    )


async def _setup(hass, entry):
    assert await async_setup_component(hass, "persistent_notification", {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry.runtime_data.coordinator


@pytest.mark.usefixtures("solax_api")
async def test_setup_discovery_registry_and_manual_meter_reload(hass):
    entry = _entry()
    coordinator = await _setup(hass, entry)

    assert set(coordinator.data["plants"]) == {"PLANT-1"}
    assert {"INVERTER-1", "MANUAL-METER-1"}.issubset(coordinator.data["devices"])

    device_registry = dr.async_get(hass)
    inverter = device_registry.async_get_device({(DOMAIN, "INVERTER-1")})
    meter = device_registry.async_get_device({(DOMAIN, "MANUAL-METER-1")})
    assert inverter is not None
    assert meter is not None

    entity_registry = er.async_get(hass)
    entry_entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert entry_entities
    assert any(entity.device_id == inverter.id for entity in entry_entities)
    assert any(entity.device_id == meter.id for entity in entry_entities)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert "MANUAL-METER-1" in entry.runtime_data.coordinator.data["devices"]
    assert entry.runtime_data.coordinator.manual_meter_entries == [
        {"serial": "MANUAL-METER-1", "business_type": 4, "source": "manual"}
    ]


async def test_temporary_failure_retains_values_and_alarm_notification_lifecycle(
    hass,
    solax_api,
):
    entry = _entry()
    coordinator = await _setup(hass, entry)
    prior_plant = dict(coordinator.data["plant_realtime"]["PLANT-1"])
    prior_stats = dict(coordinator.data["plant_stats"]["PLANT-1"])

    solax_api["temporary_failure"] = True
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.data["plant_realtime"]["PLANT-1"] == prior_plant
    assert coordinator.data["plant_stats"]["PLANT-1"] == prior_stats
    assert coordinator.data["last_errors"]

    solax_api["temporary_failure"] = False
    solax_api["alarms"]["PLANT-1"] = [
        {
            "alarmName": "GridFreqFault",
            "errorCode": "4",
            "alarmType": "Grid",
            "alarmState": 1,
        }
    ]
    await coordinator.async_refresh_alarms_once()
    await hass.async_block_till_done()
    notification_id = f"{DOMAIN}_alarm_{entry.entry_id}"
    notifications = persistent_notification._async_get_or_create_notifications(hass)
    notification = notifications.get(notification_id)
    assert notification is not None
    assert "GridFreqFault" in notification["message"]

    solax_api["alarms"]["PLANT-1"] = []
    await coordinator.async_refresh_alarms_once()
    await hass.async_block_till_done()
    cleared = notifications.get(notification_id)
    assert cleared is not None
    assert "cleared" in cleared["title"].casefold()

    options = dict(entry.options)
    options[CONF_ALARM_NOTIFICATIONS] = False
    hass.config_entries.async_update_entry(entry, options=options)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert notification_id not in notifications


async def test_independent_alarm_schedule_inventory_and_stale_merge(hass, solax_api):
    entry = _entry()
    coordinator = await _setup(hass, entry)
    manager = coordinator._get_alarm_manager()

    assert manager.update_interval == timedelta(seconds=120)
    assert coordinator.data["meta"]["alarm_scan_interval"] == 120
    initial_calls = len(solax_api["alarm_calls"])
    solax_api["alarms"]["PLANT-1"] = [
        {"alarmName": "Scheduled alarm", "alarmState": 1}
    ]
    coordinator._live_view_until = dt_util.utcnow() + timedelta(minutes=5)
    coordinator._poll_profile = "live_view"

    async_fire_time_changed(
        hass,
        manager.last_update_attempt + timedelta(seconds=121),
    )
    await hass.async_block_till_done()

    assert len(solax_api["alarm_calls"]) > initial_calls
    assert coordinator.data["alarms"]["PLANT-1"]["total"] == 1
    assert coordinator.data["meta"]["alarm_last_update_success"] is True

    coordinator._live_view_until = None
    coordinator._poll_profile = "night"
    calls_before_night = len(solax_api["alarm_calls"])
    async_fire_time_changed(
        hass,
        manager.last_update_attempt + timedelta(seconds=121),
    )
    await hass.async_block_till_done()
    assert len(solax_api["alarm_calls"]) > calls_before_night

    state = dict(coordinator.data)
    state["plants"] = {
        **state["plants"],
        "PLANT-2": {
            "plantId": "PLANT-2",
            "plantName": "Second Plant",
            "businessType": 1,
        },
    }
    state["alarms"] = {
        **state["alarms"],
        "PLANT-2": {
            "total": 1,
            "records": [{"alarmName": "Last good", "alarmState": 1}],
        },
    }
    coordinator.async_set_updated_data(state)
    solax_api["alarms"]["PLANT-1"] = []
    solax_api["alarm_failures"].add("PLANT-2")

    await coordinator.async_refresh_alarms_once()
    await hass.async_block_till_done()

    assert coordinator.data["alarms"]["PLANT-1"] == {"total": 0, "records": []}
    assert coordinator.data["alarms"]["PLANT-2"]["records"][0]["alarmName"] == "Last good"
    assert coordinator.data["meta"]["alarm_last_update_success"] is True
    assert coordinator.data["meta"]["alarm_last_errors"][0]["context"] == "alarms:PLANT-2"
    assert "PLANT-2" in solax_api["alarm_calls"]

    solax_api["alarm_failures"] = {"PLANT-1", "PLANT-2"}
    prior = coordinator.data["alarms"]
    await coordinator.async_refresh_alarms_once()
    await hass.async_block_till_done()

    assert coordinator.data["alarms"] == prior
    assert coordinator.data["meta"]["alarm_last_update_success"] is False


async def test_options_reload_and_loaded_unloaded_diagnostics(hass, solax_api):
    entry = _entry(manual_meter=False)
    await _setup(hass, entry)

    options = dict(entry.options)
    options[CONF_SYSTEM_NAME] = "Reloaded Fixture"
    options[CONF_SCAN_INTERVAL] = 300
    options[CONF_ALARM_SCAN_INTERVAL] = 300
    options[CONF_MANUAL_METER_SERIALS] = [
        {"serial": "MANUAL-METER-1", "business_type": 4}
    ]
    hass.config_entries.async_update_entry(entry, options=options)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    loaded = await async_get_config_entry_diagnostics(hass, entry)
    assert loaded["config_entry"]["system_name"] == "Reloaded Fixture"
    assert loaded["config_entry"]["scan_interval"] == 300
    assert loaded["coordinator"]["alarm_scan_interval"] == 300
    assert entry.runtime_data.coordinator._get_alarm_manager().update_interval == timedelta(
        seconds=300
    )
    assert loaded["config_entry"]["client_secret_present"] is True
    assert "fixture-client-secret" not in str(loaded)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    unloaded = await async_get_config_entry_diagnostics(hass, entry)
    assert unloaded["fallback_probe"]["executed"] is True
    assert unloaded["config_entry"]["system_name"] == "Reloaded Fixture"
    assert REDACTED_VALUE in str(unloaded)


@pytest.mark.usefixtures("solax_api")
async def test_full_unload_removes_notifications_runtime_and_services(hass):
    entry = _entry()
    await _setup(hass, entry)
    coordinator = entry.runtime_data.coordinator
    assert hass.services.has_service(DOMAIN, SERVICE_MANUAL_REFRESH)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service(DOMAIN, SERVICE_MANUAL_REFRESH)
    notifications = persistent_notification._async_get_or_create_notifications(hass)
    assert f"{DOMAIN}_alarm_{entry.entry_id}" not in notifications
    assert coordinator._listeners == {}
