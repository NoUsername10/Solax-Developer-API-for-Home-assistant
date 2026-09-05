import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.solax_developer_api import coordinator as coordinator_module
from custom_components.solax_developer_api.api import SolaxApiError
from custom_components.solax_developer_api.coordinator import (
    EMS_DEVICE_TYPE,
    RAW_ENDPOINT_PAGE_PLANT_INFO,
    SolaxDeveloperCoordinator,
    _flatten_dict,
)
from custom_components.solax_developer_api.features.history import HistoryManager
from custom_components.solax_developer_api.features import live_view as live_view_module


class _Config:
    language = "en"


class _Hass:
    config = _Config()


class _Store:
    def __init__(self, payload=None):
        self.payload = payload
        self.saved = 0

    async def async_load(self):
        return self.payload

    def async_delay_save(self, callback, delay):
        self.saved += 1
        self.last_payload = callback()


class _FullClient:
    token_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    token_scope = "all"
    token_grant_type = "client_credentials"
    token_auth_station = "P1 P4"

    async def page_plant_info(self, **kwargs):
        business_type = kwargs["business_type"]
        page_no = kwargs["page_no"]
        records = []
        if page_no == 1:
            records = [
                {
                    "plantId": f"P{business_type}",
                    "plantName": f"Plant {business_type}",
                    "businessType": business_type,
                }
            ]
        return {
            "code": 10000,
            "result": {
                "records": records,
                "current": page_no,
                "pages": 2 if page_no == 1 else 2,
            },
        }

    async def page_device_info(self, **kwargs):
        business_type = kwargs["business_type"]
        device_type = kwargs["device_type"]
        page_no = kwargs["page_no"]
        records = []
        if page_no == 1:
            serial = f"D{business_type}{device_type}"
            records = [
                {
                    "deviceSn": serial,
                    "plantId": f"P{business_type}",
                    "deviceType": device_type,
                    "businessType": business_type,
                    "onlineStatus": 1,
                    "deviceModel": 19 if device_type == 1 else 1,
                }
            ]
        return {
            "code": 10000,
            "result": {
                "records": records,
                "current": page_no,
                "pages": 2 if page_no == 1 else 2,
            },
        }

    async def get_master_control_device(self, **kwargs):
        return {
            "code": 10000,
            "result": {
                "deviceSn": kwargs["device_sn"],
                "controlDeviceSn": "EMS1",
                "controlDeviceType": EMS_DEVICE_TYPE,
            },
        }

    async def ems_attribute_info(self, **kwargs):
        return {
            "code": 10000,
            "result": {
                "registerNo": kwargs["register_no"],
                "stationId": kwargs["plant_id"],
                "deviceName": "EMS",
                "sysACRatedPower": 100,
            },
        }

    async def plant_realtime_data(self, **kwargs):
        return {
            "code": 10000,
            "result": {
                "plantId": kwargs["plant_id"],
                "dailyYield": 2,
                "totalYield": 20,
            },
        }

    async def page_alarm_info(self, **kwargs):
        return {
            "code": 10000,
            "result": {
                "records": [{"alarmName": "Test"}],
                "total": 1,
                "current": 1,
                "pages": 1,
            },
        }

    async def plant_stat_data(self, **kwargs):
        return {
            "code": 10000,
            "result": {
                "plantEnergyStatDataList": [
                    {
                        "date": kwargs["date"],
                        "pvGeneration": kwargs["date_type"],
                    }
                ]
            },
        }

    async def device_realtime_data(self, **kwargs):
        return {
            "code": 10000,
            "result": [
                {
                    "deviceSn": serial,
                    "deviceType": kwargs["device_type"],
                    "businessType": kwargs["business_type"],
                    "onlineStatus": 1,
                    "totalActivePower": 10,
                }
                for serial in kwargs["sn_list"]
            ],
        }

    async def ems_summary_data(self, **kwargs):
        return {
            "code": 10000,
            "result": [
                {"registerNo": serial, "sysPVPower": 11}
                for serial in kwargs["register_no_list"]
            ],
        }

    async def device_history_data_windowed(self, **kwargs):
        return {
            "code": 10000,
            "message": "ok",
            "result": [{"deviceSn": kwargs["sn_list"][0], "value": 1}],
            "windowSummary": {"windowCount": 1},
        }

    async def query_request_result(self, **kwargs):
        return {
            "code": 0,
            "result": [{"sn": "D14", "status": 4}],
            "requestId": kwargs["request_id"],
        }

    async def execute_control(self, **kwargs):
        return {
            "code": 10000,
            "message": "success",
            "requestId": "REQ-EVC",
            "result": {"D14": {"status": 3}},
        }


def _make(client=None):
    instance = object.__new__(SolaxDeveloperCoordinator)
    instance.hass = _Hass()
    instance.client = client or _FullClient()
    instance._base_scan_interval = 120
    instance._effective_scan_interval = 120
    instance._live_view_requested_interval = 10
    instance._live_view_call_budget_per_minute = 20
    instance._live_view_default_duration = 300
    instance._live_view_until = None
    instance._night_scan_interval = 600
    instance._night_start_hour = 23
    instance._night_end_hour = 6
    instance._poll_profile = "standard"
    instance._estimated_live_calls_per_cycle = 0
    instance._live_view_budget_adjusted = False
    instance._refresh_failure_streak = 0
    instance._refresh_backoff_seconds = 0
    instance._last_refresh_failure_classification = None
    instance._last_refresh_failure_context = None
    instance._last_refresh_failure_at = None
    instance._poll_count = 0
    instance._history_cache = {}
    instance._active_fetch_request_ids = set()
    instance._cancelled_fetch_request_ids = set()
    instance._request_result_cache = {}
    instance._master_control_cache = {}
    instance._control_dry_runs = []
    instance._ev_charger_controls_enabled = False
    instance._ev_charger_control_commands = []
    instance._manual_meter_entries = [
        {
            "serial": "MANUALMETER",
            "business_type": 1,
            "source": "manual",
            "realtime_fields": ["importEnergy"],
        }
    ]
    instance._manual_ems_entries = [
        {
            "serial": "MANUALEMS",
            "plant_id": "P4",
            "business_type": 4,
            "source": "manual",
        }
    ]
    instance._entry_id = "entry-1"
    instance._alarm_scan_interval = 120
    instance._alarm_reserved_calls_per_minute = 0.0
    instance._alarm_manager = None
    instance._alarm_manager_unsub = None
    instance._alarm_merge_task = None
    instance._alarm_last_merge_at = None
    instance._history_manager = None
    instance._live_view_manager = None
    instance._state_merge_lock = asyncio.Lock()
    instance._device_capabilities = {}
    instance._raw_api_responses = instance._new_raw_api_response_snapshot()
    instance._capability_store = _Store()
    instance.rate_limited = False
    instance.rate_limited_context = []
    instance.last_rate_limit_at = None
    instance.last_update_attempt = None
    instance.last_successful_update = None
    instance.last_update_success = True
    instance.last_exception = None
    instance._listeners = {}
    instance.update_interval = timedelta(seconds=120)
    instance.data = instance._empty_state()
    return instance


class _AlarmManagerStub:
    def __init__(self, *, data=None, successful=True):
        self.data = dict(data or {})
        self.last_update_success = successful
        self.last_update_attempt = datetime(2026, 7, 1, tzinfo=timezone.utc)
        self.last_successful_update = datetime(2026, 7, 1, tzinfo=timezone.utc)
        self.last_error = None
        self.last_errors = []
        self.last_api_calls = 1
        self.raw_cycle = {}
        self.scan_interval = 120
        self.estimated_calls_per_minute = 0.5
        self.refreshes = 0
        self.listeners = []
        self.unsubscribed = False

    def async_add_listener(self, listener):
        self.listeners.append(listener)

        def _unsubscribe():
            self.unsubscribed = True

        return _unsubscribe

    async def async_refresh(self):
        self.refreshes += 1
        self.last_update_success = True
        self.data = {"P1": {"total": 0, "records": []}}


def test_constructor_clamps_options_and_initializes_store(monkeypatch):
    def _coordinator_init(self, hass, *, logger, name, update_interval):
        self.hass = hass
        self.name = name
        self.update_interval = update_interval

    class _PatchedStore(_Store):
        def __init__(self, hass, version, key):
            super().__init__()
            self.key = key

    monkeypatch.setattr(
        coordinator_module.DataUpdateCoordinator,
        "__init__",
        _coordinator_init,
    )
    monkeypatch.setattr(coordinator_module, "Store", _PatchedStore)
    instance = SolaxDeveloperCoordinator(
        _Hass(),
        client=_FullClient(),
        entry_id="entry-x",
        scan_interval=1,
        options={
            "alarm_scan_interval": 999999,
            "live_view_default_duration": 999999,
            "live_view_interval": 5,
            "live_view_call_budget_per_minute": 999,
            "night_scan_interval": 1,
            "night_start_hour": -1,
            "night_end_hour": 99,
            "manual_meter_serials": "M1|4",
            "manual_ems_systems": "E1|P4",
        },
    )

    assert instance._base_scan_interval == 60
    assert instance._live_view_requested_interval == 10
    assert instance._live_view_call_budget_per_minute <= 100
    assert instance._alarm_scan_interval == 3600
    assert instance._night_start_hour == 0
    assert instance._night_end_hour == 23
    assert instance.manual_meter_entries[0]["serial"] == "M1"
    assert instance.manual_ems_entries[0]["serial"] == "E1"
    assert instance._capability_store.key.endswith("entry-x")


def test_live_view_reserves_alarm_polling_budget():
    instance = _make()
    instance._alarm_scan_interval = 120
    instance._live_view_call_budget_per_minute = 20
    instance._live_view_requested_interval = 2
    instance.data["plants"] = {
        "P1": {"plantId": "P1"},
        "P2": {"plantId": "P2"},
    }

    effective = instance._get_live_view_manager().compute_safe_interval(
        instance.data["plants"],
        {"1:1": [f"INV-{index}" for index in range(11)]},
    )

    assert instance._alarm_reserved_calls_per_minute == 1.0
    assert instance._estimated_live_calls_per_cycle == 4
    assert effective == 13


@pytest.mark.asyncio
async def test_alarm_manager_lifecycle_serializes_state_and_retains_cached_alarms():
    instance = _make()
    instance.data["plants"] = {
        "P1": {"plantId": "P1"},
        "P2": {"plantId": "P2"},
    }
    instance.data["alarms"] = {
        "P1": {"total": 1, "records": [{"alarmName": "Cached"}]},
        "P2": {"total": 0, "records": []},
    }
    instance.data["last_errors"] = [
        {"context": "alarms:P1", "message": "old alarm error"},
        {"context": "device_realtime", "message": "keep me"},
    ]
    manager = _AlarmManagerStub(
        data={
            "P1": {"total": 2, "records": [{"alarmName": "Fresh"}]},
            "REMOVED": {"total": 1, "records": [{"alarmName": "Ignore"}]},
        }
    )
    manager.last_errors = [
        {
            "context": "alarms:P2",
            "code": 10406,
            "classification": "rate_limit",
            "message": "slow down",
        }
    ]
    manager.last_error = "alarms:P2: slow down"
    manager.last_api_calls = 2
    instance._alarm_manager = manager

    await instance._async_merge_alarm_manager_state()

    assert instance.data["alarms"] == {
        "P1": {"total": 2, "records": [{"alarmName": "Fresh"}]}
    }
    assert instance.data["last_errors"][0]["context"] == "device_realtime"
    assert instance.data["last_errors"][1]["context"] == "alarms:P2"
    assert instance.data["meta"]["alarm_last_api_calls"] == 2
    assert instance.data["meta"]["alarm_last_merge_at"] is not None
    assert instance.data["meta"]["alarm_reserved_calls_per_minute"] == 0.5
    assert instance.rate_limited is True
    assert "alarms:P2" in instance.rate_limited_context

    # Cached alarm state seeds the independent coordinator without another API read.
    instance.data["alarms"] = {
        "P1": {"total": 1, "records": []},
        "P2": {"total": 0, "records": []},
    }
    await instance.async_start_alarm_polling()
    assert manager.refreshes == 0
    assert manager.data == instance.data["alarms"]
    assert len(manager.listeners) == 1

    await instance.async_refresh_alarms_once()
    assert manager.refreshes == 1
    assert instance.data["alarms"]["P1"]["total"] == 0

    await instance.async_stop_alarm_polling()
    assert manager.unsubscribed is True
    assert instance._alarm_manager_unsub is None


@pytest.mark.asyncio
async def test_alarm_manager_initial_refresh_task_deduplication_and_lazy_setup(
    monkeypatch,
):
    instance = _make()
    instance.data["plants"] = {"P1": {"plantId": "P1"}}
    manager = _AlarmManagerStub()

    monkeypatch.setattr(
        coordinator_module,
        "AlarmManager",
        lambda owner, scan_interval: manager,
    )
    instance._alarm_manager = None
    assert instance._get_alarm_manager() is manager
    assert instance._get_alarm_manager() is manager

    instance._state_merge_lock = object()
    assert isinstance(instance._get_state_merge_lock(), asyncio.Lock)

    class _TaskHass(_Hass):
        @staticmethod
        def async_create_task(coro, _name):
            return asyncio.create_task(coro)

    instance.hass = _TaskHass()

    blocker = asyncio.Event()

    async def _blocked():
        await blocker.wait()

    existing = asyncio.create_task(_blocked())
    instance._alarm_merge_task = existing
    instance._schedule_alarm_manager_merge()
    assert instance._alarm_merge_task is existing
    blocker.set()
    await existing

    instance._alarm_merge_task = None
    instance._schedule_alarm_manager_merge()
    scheduled = instance._alarm_merge_task
    assert scheduled is not None
    await scheduled

    instance._alarm_merge_task = None
    instance.data["alarms"] = {}
    await instance.async_start_alarm_polling()
    assert manager.refreshes == 1
    assert instance.data["alarms"]["P1"]["total"] == 0


@pytest.mark.asyncio
async def test_alarm_merges_do_not_reset_realtime_schedule_or_success_state():
    instance = _make()
    instance.data["plants"] = {"P1": {"plantId": "P1"}}
    manager = _AlarmManagerStub(
        data={"P1": {"total": 0, "records": []}},
    )
    instance._alarm_manager = manager

    scheduled_refresh = object()
    instance._unsub_refresh = scheduled_refresh
    instance.last_update_success = False
    listener_calls = 0

    def _listener() -> None:
        nonlocal listener_calls
        listener_calls += 1

    instance._listeners = {1: (_listener, None)}

    def _fail_if_timer_reset(_state):
        pytest.fail("alarm merge reset the realtime coordinator timer")

    instance.async_set_updated_data = _fail_if_timer_reset

    for alarm_count in (0, 1, 0):
        manager.data = {
            "P1": {
                "total": alarm_count,
                "records": ([{"alarmName": "Test"}] if alarm_count else []),
            }
        }
        await instance._async_merge_alarm_manager_state()

        assert instance._unsub_refresh is scheduled_refresh
        assert instance.last_update_success is False

    assert listener_calls == 3
    assert instance.data["alarms"]["P1"]["total"] == 0
    assert instance.data["meta"]["alarm_last_merge_at"] is not None


def test_poll_profile_transitions_log_old_and_new_intervals(monkeypatch, caplog):
    instance = _make()
    manager = instance._get_live_view_manager()
    current_hour = 23
    monkeypatch.setattr(
        live_view_module.dt_util,
        "now",
        lambda: datetime(2026, 8, 9, current_hour, tzinfo=timezone.utc),
    )

    with caplog.at_level("INFO", logger=live_view_module.__name__):
        manager.apply_poll_profile({}, {})
        current_hour = 6
        manager.apply_poll_profile({}, {})

    assert instance._poll_profile == "standard"
    assert instance.update_interval == timedelta(seconds=120)
    assert "standard (120s) to night (600s)" in caplog.text
    assert "night (600s) to standard (120s)" in caplog.text


def test_list_history_devices_filters_sorts_and_includes_manual_meter():
    instance = _make()
    instance.data["devices"] = {
        "EMS1": {
            "deviceSn": "EMS1",
            "deviceType": EMS_DEVICE_TYPE,
            "businessType": 4,
        },
        "METER1": {
            "deviceSn": "METER1",
            "deviceType": 3,
            "businessType": 1,
            "manualSerial": True,
            "discoverySource": "manual_meter_serial",
        },
        "INV1": {
            "deviceSn": "INV1",
            "deviceType": 1,
            "businessType": 1,
            "discoverySource": "inventory",
        },
        "EV1": {
            "deviceSn": "EV1",
            "deviceType": 4,
            "businessType": 4,
        },
        "UNKNOWN": {
            "deviceSn": "UNKNOWN",
            "deviceType": 999,
            "businessType": 1,
        },
    }

    devices = instance.list_history_devices()

    assert [device["device_sn"] for device in devices] == ["INV1", "METER1", "EV1"]
    assert devices[0]["device_type_name"] == "Inverter"
    assert devices[1]["source"] == "manual"
    assert all(device["device_type"] in (1, 2, 3, 4) for device in devices)


def test_list_plant_statistics_targets_sorts_loaded_plants():
    instance = _make()
    instance.data["plants"] = {
        "P2": {"plantId": "P2", "plantName": "Zeta", "businessType": 4},
        "P1": {"plantId": "P1", "plantName": "Alpha", "businessType": 1},
        "bad": "ignored",
    }

    plants = instance.list_plant_statistics_targets()

    assert [plant["plant_id"] for plant in plants] == ["P1", "P2"]
    assert plants[0]["label"] == "Alpha"
    assert plants[1]["business_type"] == 4


def test_list_alarm_targets_returns_loaded_plants_and_devices():
    instance = _make()
    instance.data["plants"] = {
        "P1": {"plantId": "P1", "plantName": "Alpha", "businessType": 1},
    }
    instance.data["devices"] = {
        "INV1": {
            "deviceSn": "INV1",
            "plantId": "P1",
            "deviceType": 1,
            "businessType": 1,
        },
        "METER1": {
            "deviceSn": "METER1",
            "plantId": "P1",
            "deviceType": 3,
            "manualSerial": True,
        },
        "NO_PLANT": {
            "deviceSn": "NO_PLANT",
            "deviceType": 1,
        },
    }

    targets = instance.list_alarm_targets()

    assert [plant["plant_id"] for plant in targets["plants"]] == ["P1"]
    assert [device["device_sn"] for device in targets["devices"]] == ["INV1", "METER1"]
    assert targets["devices"][1]["source"] == "manual"
    assert targets["devices"][1]["business_type"] == 1


class _AlarmClient:
    def __init__(self):
        self.calls = []

    async def page_alarm_info(self, **kwargs):
        self.calls.append(kwargs)
        state = kwargs["alarm_state"]
        page_no = kwargs["page_no"]
        if state == 1 and page_no == 1:
            records = [
                {
                    "alarmStartTime": "2026-06-27 10:00:00",
                    "alarmName": "Grid Fault",
                    "errorCode": "60",
                    "alarmState": 1,
                    "deviceModel": "2",
                    "deviceType": 1,
                    "deviceSn": kwargs.get("device_sn") or "INV1",
                }
            ]
            pages = 2
        elif state == 1 and page_no == 2:
            records = [
                {
                    "alarmStartTime": "2026-06-27 11:00:00",
                    "alarmName": "Temperature",
                    "errorCode": "70",
                    "alarmState": 1,
                    "deviceModel": "14",
                    "deviceType": 1,
                    "deviceSn": kwargs.get("device_sn") or "INV1",
                }
            ]
            pages = 2
        else:
            records = [
                {
                    "alarmStartTime": "2026-06-26 10:00:00",
                    "alarmName": "Recovered",
                    "errorCode": "80",
                    "alarmState": 0,
                    "deviceModel": "50",
                    "deviceType": 3,
                    "deviceSn": kwargs.get("device_sn") or "INV1",
                }
            ]
            pages = 1
        return {
            "code": 10000,
            "result": {
                "plantId": kwargs["plant_id"],
                "records": records,
                "total": len(records),
                "current": page_no,
                "pages": pages,
                "size": 10,
            },
        }


@pytest.mark.asyncio
async def test_fetch_alarm_information_paginates_states_and_device_filter():
    client = _AlarmClient()
    instance = _make(client)
    instance.data["plants"] = {
        "P1": {"plantId": "P1", "plantName": "Alpha", "businessType": 1},
    }

    result = await instance.async_fetch_alarm_information(
        plant_id="P1",
        business_type=1,
        alarm_state="all",
        device_sn="INV1",
        max_pages=5,
    )

    assert [call["alarm_state"] for call in client.calls] == [1, 1, 0]
    assert all(call["device_sn"] == "INV1" for call in client.calls)
    assert result["count"] == 3
    assert result["api_calls_made"] == 3
    assert result["state_counts"] == {"ongoing": 2, "closed": 1}
    assert "alarmName" in result["available_fields"]
    assert result["records"][0]["plantId"] == "P1"
    assert result["records"][0]["deviceTypeName"] == "Inverter"
    assert result["records"][0]["deviceModelName"] == "X3-Hybrid-G4"
    assert result["records"][2]["deviceTypeName"] == "Meter"
    assert result["records"][2]["deviceModelName"] == "Meter X"


@pytest.mark.asyncio
async def test_cancel_fetch_stops_alarm_and_plant_statistics_before_next_call():
    alarm_client = _AlarmClient()
    alarm_instance = _make(alarm_client)
    alarm_instance.data["plants"] = {
        "P1": {"plantId": "P1", "plantName": "Alpha", "businessType": 1},
    }
    assert alarm_instance.cancel_fetch("alarm-1")["cancelled"] is True

    alarm_result = await alarm_instance.async_fetch_alarm_information(
        plant_id="P1",
        business_type=1,
        alarm_state="all",
        max_pages=5,
        request_id="alarm-1",
    )

    assert alarm_result["cancelled"] is True
    assert alarm_result["api_calls_made"] == 0
    assert alarm_client.calls == []

    plant_client = _PlantYearClient()
    plant_instance = _make(plant_client)
    assert plant_instance.cancel_fetch("plant-year-1")["cancelled"] is True

    plant_result = await plant_instance.async_fetch_plant_year_statistics(
        plant_id="P1",
        business_type=1,
        year=2025,
        request_id="plant-year-1",
    )

    assert plant_result["cancelled"] is True
    assert plant_result["api_calls_made"] == 0
    assert plant_client.calls == []


class _PlantYearClient:
    def __init__(self):
        self.calls = []

    async def plant_stat_data(self, **kwargs):
        self.calls.append(kwargs)
        month = int(str(kwargs["date"]).split("-")[1])
        return {
            "code": 10000,
            "result": {
                "plantEnergyStatDataList": [
                    {
                        "date": kwargs["date"],
                        "pvGeneration": month,
                        "earnings": str(month / 10),
                    }
                ]
            },
        }


@pytest.mark.asyncio
async def test_fetch_plant_year_statistics_past_year_fetches_12_months():
    client = _PlantYearClient()
    instance = _make(client)

    result = await instance.async_fetch_plant_year_statistics(
        plant_id="P1",
        business_type=1,
        year=2025,
    )

    assert result["api_calls_made"] == 12
    assert result["month_count"] == 12
    assert len(client.calls) == 12
    assert client.calls[0]["date"] == "2025-01"
    assert client.calls[-1]["date"] == "2025-12"
    assert result["rows"][0]["month"] == "2025-01"
    assert result["rows"][0]["pvGeneration"] == 1
    assert result["rows"][-1]["earnings"] == 1.2
    assert "pvGeneration" in result["available_metric_names"]


@pytest.mark.asyncio
async def test_fetch_plant_year_statistics_current_year_fetches_to_current_month(monkeypatch):
    client = _PlantYearClient()
    instance = _make(client)
    monkeypatch.setattr(
        coordinator_module.dt_util,
        "now",
        lambda: datetime(2026, 6, 24, tzinfo=timezone.utc),
    )

    result = await instance.async_fetch_plant_year_statistics(
        plant_id="P1",
        business_type=1,
        year=2026,
    )

    assert result["api_calls_made"] == 6
    assert result["month_count"] == 6
    assert [call["date"] for call in client.calls] == [
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
    ]


@pytest.mark.asyncio
async def test_fetch_plant_month_statistics_returns_daily_rows():
    class _PlantMonthClient:
        def __init__(self):
            self.calls = []

        async def plant_stat_data(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "code": 10000,
                "result": {
                    "plantEnergyStatDataList": [
                        {
                            "date": "2026-06-01",
                            "pvGeneration": "4.2",
                            "exportEnergy": 1,
                            "ignored": 100,
                        },
                        {
                            "date": "2026-06-02",
                            "pvGeneration": 5,
                            "loadConsumption": "3.5",
                        },
                    ]
                },
            }

    client = _PlantMonthClient()
    instance = _make(client)

    result = await instance.async_fetch_plant_month_statistics(
        plant_id="P1",
        business_type=1,
        year=2026,
        month=6,
    )

    assert client.calls == [
        {
            "plant_id": "P1",
            "business_type": 1,
            "date_type": 2,
            "date": "2026-06",
        }
    ]
    assert result["api_calls_made"] == 1
    assert result["day_count"] == 2
    assert result["rows"][0]["date"] == "2026-06-01"
    assert result["rows"][0]["day"] == 1
    assert result["rows"][0]["pvGeneration"] == 4.2
    assert result["rows"][1]["loadConsumption"] == 3.5
    assert result["available_metric_names"] == [
        "exportEnergy",
        "loadConsumption",
        "pvGeneration",
    ]


@pytest.mark.asyncio
async def test_history_cancellation_after_response_and_malformed_month_rows():
    class _CancelAfterResponseClient:
        def __init__(self):
            self.owner = None
            self.calls = 0

        async def plant_stat_data(self, **kwargs):
            self.calls += 1
            self.owner.cancel_fetch(kwargs["date"])
            return {
                "code": 10000,
                "result": {
                    "plantEnergyStatDataList": [
                        None,
                        {"date": "2026-06-02", "notAMetric": "text"},
                    ]
                },
            }

    client = _CancelAfterResponseClient()
    instance = _make(client)
    client.owner = instance

    year = await instance.async_fetch_plant_year_statistics(
        plant_id="P1",
        business_type=1,
        year=2025,
        request_id="2025-01",
    )
    assert year["cancelled"] is True
    assert year["api_calls_made"] == 1

    month = await instance.async_fetch_plant_month_statistics(
        plant_id="P1",
        business_type=1,
        year=2026,
        month=6,
        request_id="2026-06",
    )
    assert month["cancelled"] is True
    assert month["day_count"] == 0
    assert month["available_metric_names"] == []

    instance.cancel_fetch("pre-cancelled-month")
    calls_before = client.calls
    pre_cancelled = await instance.async_fetch_plant_month_statistics(
        plant_id="P1",
        business_type=1,
        year=2026,
        month=7,
        request_id="pre-cancelled-month",
    )
    assert pre_cancelled["cancelled"] is True
    assert pre_cancelled["api_calls_made"] == 0
    assert client.calls == calls_before


@pytest.mark.parametrize(
    ("raw_value", "fallback_day", "expected_date"),
    [
        (1782864000, 9, "2026-07-01"),
        (1782950400000, 9, "2026-07-02"),
        ("2026-07-03", 9, "2026-07-03"),
        ("2026/07/04", 9, "2026-07-04"),
        ("2026-07-05 12:34:56", 9, "2026-07-05"),
        ("2026-07-06T12:34:56", 9, "2026-07-06"),
        ("7", 9, "2026-07-07"),
        ("not-a-date", 8, "2026-07-08"),
        ("", 10, "2026-07-10"),
        (None, 11, "2026-07-11"),
        ("99", 1, "2026-07-31"),
    ],
)
def test_plant_stat_daily_timestamp_supported_and_fallback_shapes(
    raw_value,
    fallback_day,
    expected_date,
):
    row = {} if raw_value is None else {"date": raw_value}

    date_text, timestamp = HistoryManager.plant_stat_daily_timestamp(
        row,
        year=2026,
        month=7,
        fallback_day=fallback_day,
    )

    assert date_text == expected_date
    assert datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).hour == 0


def test_plant_stat_daily_timestamp_invalid_calendar_date_falls_back():
    date_text, timestamp = HistoryManager.plant_stat_daily_timestamp(
        {},
        year=2026,
        month=2,
        fallback_day=31,
    )

    assert date_text == "2026-02-01"
    assert timestamp == int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)


class _FailingPlantYearClient:
    async def plant_stat_data(self, **kwargs):
        raise SolaxApiError(
            code=10500,
            message="permission",
            classification="permission",
        )


@pytest.mark.asyncio
async def test_fetch_plant_year_statistics_surfaces_api_errors():
    instance = _make(_FailingPlantYearClient())

    with pytest.raises(SolaxApiError):
        await instance.async_fetch_plant_year_statistics(
            plant_id="P1",
            business_type=1,
            year=2025,
        )


@pytest.mark.asyncio
async def test_capability_cache_load_serialize_and_raw_helpers():
    instance = _make()
    assert _flatten_dict({"outer": {"inner": 1}}) == {"outer_inner": 1}
    instance._capability_store = _Store(None)
    await instance.async_load_capability_cache()
    instance._capability_store = _Store({"devices": "invalid"})
    await instance.async_load_capability_cache()
    instance._capability_store = _Store(
        {
            "devices": {
                "": {"serial": "INV1", "fields": ["power", "", "power"]},
                "bad": "invalid",
                "empty": {"serial": "EMPTY", "fields": []},
                "nofields": {"serial": "NOFIELDS", "fields": "invalid"},
                "nokey": {"serial": "", "fields": ["power"]},
            }
        }
    )
    await instance.async_load_capability_cache()
    assert instance.device_capability_fields["inv1"] == {"power"}
    assert instance._serialize_capability_cache()["devices"]["inv1"]["fields"] == [
        "power"
    ]
    instance._device_capabilities["bad"] = "invalid"
    instance._device_capabilities["empty"] = {"fields": []}
    instance._device_capabilities["blank"] = {"fields": [""]}
    assert "bad" not in instance._serialize_capability_cache()["devices"]
    instance._schedule_capability_cache_save()
    assert instance._capability_store.saved == 1

    raw = instance._new_raw_api_response_snapshot()
    instance._append_raw_snapshot(
        raw,
        endpoint=RAW_ENDPOINT_PAGE_PLANT_INFO,
        request={"page": 1},
        response={"code": 10000},
    )
    instance._append_raw_snapshot(
        raw,
        endpoint=RAW_ENDPOINT_PAGE_PLANT_INFO,
        request={"page": 2},
        error=SolaxApiError(
            code=10406,
            message="limited",
            classification="rate_limit",
        ),
        optional_absence=True,
    )
    assert instance._count_raw_cycle_responses(raw) == 1
    assert instance._raw_cycle_error_items(raw) == []
    instance._merge_raw_api_cycle(raw)
    assert len(instance.raw_api_responses[RAW_ENDPOINT_PAGE_PLANT_INFO]) == 2


def test_normalization_lookup_and_known_devices():
    instance = _make()
    assert instance._normalize_manual_meter_entries("") == []
    assert instance._normalize_manual_meter_entries({"serial": "M1"})[0][
        "serial"
    ] == "M1"
    assert instance._normalize_manual_meter_entries(["", "M1", "m1"])[0][
        "serial"
    ] == "M1"
    assert instance._normalize_manual_meter_entries("BAD|x") == []
    assert instance._normalize_manual_ems_entries("") == []
    assert instance._normalize_manual_ems_entries({"serial": "E", "plant_id": "P"})[
        0
    ]["serial"] == "E"
    assert instance._normalize_manual_ems_entries("invalid") == []
    assert instance._find_existing_serial_key("", {}) is None
    assert instance._find_existing_serial_key("abc", {"ABC": 1}) == "ABC"
    assert instance._find_existing_serial_key("missing", {"ABC": 1}) is None

    instance.set_manual_meter_entries([{"serial": "M2", "business_type": 4}])
    instance.set_manual_ems_entries([{"serial": "E2", "plant_id": "P4"}])
    assert instance.data["meta"]["manual_meter_serial_count"] == 1
    assert instance.data["meta"]["manual_ems_system_count"] == 1

    instance.data["devices"] = {
        "AUTO": {"deviceType": 3, "businessType": 1},
        "EMS": {"deviceType": EMS_DEVICE_TYPE, "plantId": "P4"},
        "INV": {"deviceType": 1},
    }
    assert instance.get_known_meter_serial("") is None
    assert instance.get_known_meter_serial("AUTO")["source"] == "inventory"
    assert instance.get_known_meter_serial("M2")["source"] == "manual"
    assert instance.get_known_meter_serial("INV") is None
    assert instance.get_known_ems_serial("") is None
    assert instance.get_known_ems_serial("EMS")["source"] == "master_control"
    assert instance.get_known_ems_serial("E2")["source"] == "manual"
    assert instance.get_known_ems_serial("missing") is None


def test_normalization_and_lookup_edge_branches():
    instance = _make()

    assert instance._normalize_manual_meter_entries(123) == []
    assert instance._normalize_manual_meter_entries('{"serial":"JSONM","businessType":"bad"}') == [
        {"serial": "JSONM", "business_type": 1, "source": "manual"}
    ]
    assert instance._normalize_manual_meter_entries(
        [{"deviceSn": "ALT", "businessType": 9, "realtimeFields": ["b", "", "A"]}]
    ) == [
        {
            "serial": "ALT",
            "business_type": 1,
            "source": "manual",
            "realtime_fields": ["A", "b"],
        }
    ]
    assert instance._normalize_manual_meter_entries("\n,VALID|4,,BAD|x") == [
        {"serial": "VALID", "business_type": 4, "source": "manual"}
    ]

    assert instance._normalize_manual_ems_entries(123) == []
    assert instance._normalize_manual_ems_entries('{"registerNo":"EMSJSON","stationId":"P4"}') == [
        {
            "serial": "EMSJSON",
            "plant_id": "P4",
            "business_type": 4,
            "source": "manual",
        }
    ]
    assert instance._normalize_manual_ems_entries(
        ("EMS1|P1", {"registerNo": "EMS2", "plantId": "P2"}, "bad")
    ) == [
        {
            "serial": "EMS2",
            "plant_id": "P2",
            "business_type": 4,
            "source": "manual",
        }
    ]
    assert instance._normalize_manual_ems_entries(
        [{"serial": "", "plant_id": "P"}, {"serial": "EMS", "plant_id": ""}]
    ) == []

    instance.set_manual_meter_entries(
        [{"serial": "MRT", "business_type": 4, "realtime_fields": ["power"]}]
    )
    instance.data["devices"] = {
        "BADTYPE": {"deviceType": "bad", "businessType": 1},
        "EV": {"deviceType": 4, "businessType": 4, "deviceSn": "EV"},
        "EMS_BADTYPE": {"deviceType": "bad", "plantId": "P4"},
    }
    known = instance.get_known_meter_serial("MRT")
    assert known["source"] == "manual"
    assert known["realtime_fields"] == ["power"]
    assert instance.get_known_meter_serial("BADTYPE") is None
    assert instance.get_known_ev_charger_serial("") is None
    assert instance.get_known_ev_charger_serial("EV")["business_type"] == 4
    assert instance.get_known_ems_serial("EMS_BADTYPE") is None


@pytest.mark.asyncio
async def test_manual_ems_probe_failure_shapes():
    instance = _make()
    assert (
        await instance.async_probe_manual_ems_system(serial="", plant_id="")
    )["reason"] == "invalid_ems_identity"

    class _ErrorClient:
        async def ems_attribute_info(self, **kwargs):
            raise SolaxApiError(
                code=10500,
                message="permission",
                classification="permission",
            )

    instance.client = _ErrorClient()
    assert (
        await instance.async_probe_manual_ems_system(serial="EMS", plant_id="P4")
    )["reason"] == "ems_attribute_query_failed"

    class _MissingClient:
        async def ems_attribute_info(self, **kwargs):
            return {"code": 10000, "result": "invalid"}

    instance.client = _MissingClient()
    assert (
        await instance.async_probe_manual_ems_system(serial="EMS", plant_id="P4")
    )["reason"] == "ems_not_found"


@pytest.mark.asyncio
async def test_ems_discovery_handles_optional_absence_malformed_and_valid_relations():
    class _EmsDiscoveryClient:
        async def get_master_control_device(self, **kwargs):
            serial = kwargs["device_sn"]
            if serial == "NO_RELATION":
                raise SolaxApiError(
                    code=10500,
                    message="not managed by EMS",
                    classification="permission",
                )
            if serial == "MALFORMED":
                return {"code": 10000, "result": "not-a-mapping"}
            if serial == "WRONG_TYPE":
                return {
                    "code": 10000,
                    "result": {
                        "controlDeviceSn": "NOT-EMS",
                        "controlDeviceType": 4,
                    },
                }
            return {
                "code": 10000,
                "result": {
                    "controlDeviceSn": "EMS-VALID",
                    "controlDeviceType": EMS_DEVICE_TYPE,
                },
            }

    instance = _make(_EmsDiscoveryClient())
    raw = instance._new_raw_api_response_snapshot()
    devices = {
        "RESIDENTIAL": {
            "deviceSn": "RESIDENTIAL",
            "businessType": 1,
            "deviceType": 1,
            "plantId": "P1",
        },
        "NO_RELATION": {
            "deviceSn": "NO_RELATION",
            "businessType": 4,
            "deviceType": 1,
            "plantId": "P4",
        },
        "MALFORMED": {
            "deviceSn": "MALFORMED",
            "businessType": 4,
            "deviceType": 2,
            "plantId": "P4",
        },
        "WRONG_TYPE": {
            "deviceSn": "WRONG_TYPE",
            "businessType": 4,
            "deviceType": 3,
            "plantId": "P4",
        },
        "CHILD": {
            "deviceSn": "CHILD",
            "businessType": 4,
            "deviceType": 4,
            "plantId": "P4",
        },
    }

    discovered = await instance._discover_ems_devices(
        devices=devices,
        raw_cycle=raw,
    )

    assert list(discovered) == ["EMS-VALID"]
    assert discovered["EMS-VALID"]["controlChildDeviceSn"] == "CHILD"
    snapshots = raw["master_control_device"]
    assert len(snapshots) == 4
    optional = next(item for item in snapshots if item["request"]["deviceSn"] == "NO_RELATION")
    assert optional["optional_absence"] is True


@pytest.mark.asyncio
async def test_ems_attribute_hydration_retains_identity_across_partial_failures():
    class _EmsAttributeClient:
        async def ems_attribute_info(self, **kwargs):
            serial = kwargs["register_no"]
            if serial == "ERROR":
                raise SolaxApiError(
                    code=10406,
                    message="rate limited",
                    classification="rate_limit",
                )
            if serial == "MIXED":
                return {
                    "code": 10000,
                    "result": [
                        "malformed",
                        {"registerNo": "OTHER", "sysPVPower": 1},
                    ],
                }
            return {
                "code": 10000,
                "result": {
                    "registerNo": serial,
                    "stationId": "P4-NORMALIZED",
                    "sysPVPower": 9,
                },
            }

    instance = _make(_EmsAttributeClient())
    raw = instance._new_raw_api_response_snapshot()
    hydrated = await instance._hydrate_ems_attributes(
        ems_devices={
            "NO-PLANT": {
                "deviceSn": "NO-PLANT",
                "deviceType": EMS_DEVICE_TYPE,
                "businessType": 4,
            },
            "MIXED": {
                "deviceSn": "MIXED",
                "plantId": "P4",
            },
            "ERROR": {
                "deviceSn": "ERROR",
                "plantId": "P4",
            },
            "VALID": {
                "deviceSn": "VALID",
                "plantId": "P4",
            },
        },
        raw_cycle=raw,
    )

    assert hydrated["NO-PLANT"]["deviceSn"] == "NO-PLANT"
    assert hydrated["MIXED"]["plantId"] == "P4"
    assert hydrated["ERROR"]["registerNo"] == "ERROR"
    assert hydrated["VALID"]["plantId"] == "P4-NORMALIZED"
    assert hydrated["VALID"]["sysPVPower"] == 9
    assert any(item.get("error") for item in raw["ems_attribute_info"])


def test_capability_families_history_ci_and_backoff_helpers(monkeypatch):
    instance = _make()
    instance.data = {
        "devices": {
            "INV": {"deviceType": 1, "businessType": 4},
            "BAT": {"deviceType": 2, "businessType": 1},
            "METER": {"deviceType": 3, "businessType": 1},
            "EV": {"deviceType": 4, "businessType": 1},
            "EMS": {"deviceType": 100, "businessType": 4},
            "BAD": "invalid",
        },
        "device_realtime": {"inv": {"batterySOC": 50}},
    }
    instance._device_capabilities = {
        "inv": {"fields": ["batteryPower"]}
    }
    assert {
        "inverter",
        "ci_inverter",
        "battery",
        "battery_system",
        "meter",
        "ev_charger",
        "ems",
    }.issubset(instance.capability_families)
    assert instance.available_control_services
    assert instance.has_history_capable_devices is True
    assert instance.has_ci_devices is True

    assert instance._clamp_int("bad", default=5, min_value=1, max_value=10) == 5
    assert instance._compute_refresh_backoff_seconds(0) == 0
    assert instance._compute_refresh_backoff_seconds(10) == 1800
    assert instance._is_temporary_failure_classification("timeout")
    assert not instance._is_temporary_failure_classification("permission")
    instance._register_refresh_failure("permission", "inventory")
    assert instance._refresh_failure_streak == 0
    instance._register_refresh_failure("timeout", "inventory")
    instance._apply_refresh_backoff_to_interval()
    assert instance.update_interval.total_seconds() >= 120

    errors = [{"classification": "timeout", "context": "x", "message": "bad"}]
    assert instance._select_refresh_failure_signal(errors, {}) == (
        "timeout",
        "x",
        "bad",
    )
    assert instance._select_refresh_failure_signal([], {})[1] == "refresh"


def test_raw_error_selection_and_rate_limit_merge_helpers():
    instance = _make()
    raw = instance._new_raw_api_response_snapshot()
    raw[RAW_ENDPOINT_PAGE_PLANT_INFO].extend(
        [
            "invalid",
            {"error": "not-a-mapping"},
            {
                "error": {
                    "classification": "rate_limit",
                    "code": 10406,
                    "message": "limited",
                }
            },
            {
                "error": {
                    "classification": "timeout",
                    "code": None,
                    "message": "",
                }
            },
        ]
    )

    errors = instance._raw_cycle_error_items(raw)
    assert len(errors) == 2
    assert instance._select_refresh_failure_signal([], raw) == (
        "timeout",
        RAW_ENDPOINT_PAGE_PLANT_INFO,
        "refresh failed",
    )

    merged: list[dict] = []
    instance._merge_raw_errors_into_errors(merged, raw)
    assert len(merged) == 2
    assert instance.rate_limited is True
    assert RAW_ENDPOINT_PAGE_PLANT_INFO in instance.rate_limited_context


def test_live_view_profiles_and_meta(monkeypatch):
    instance = _make()
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        coordinator_module.dt_util,
        "now",
        lambda: now.replace(hour=0),
    )
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: now)

    instance._night_start_hour = 23
    instance._night_end_hour = 6
    assert instance._is_night_mode() is True
    instance._night_start_hour = 1
    instance._night_end_hour = 1
    assert instance._is_night_mode() is False
    instance._night_start_hour = 0
    instance._night_end_hour = 6
    assert instance._is_night_mode() is True

    instance._live_view_until = now - timedelta(seconds=1)
    assert instance.live_view_active is False
    assert instance.live_view_remaining_seconds == 0
    assert instance.live_view_until is None
    instance._live_view_until = now + timedelta(seconds=30)
    assert instance.live_view_active is True
    assert instance.live_view_remaining_seconds == 30

    assert instance._estimate_live_cycle_calls({}, {"1:1": []}) == 1
    instance.rate_limited = True
    assert instance._compute_safe_live_interval(
        {"P1": {}},
        {"1:1": ["A", "B"]},
    ) >= 120
    instance.rate_limited = False
    instance._apply_dynamic_poll_profile({"P1": {}}, {"1:1": ["A"]})
    assert instance._poll_profile == "live_view"
    instance._refresh_meta_state()
    assert instance.data["meta"]["live_view_active"] is True


@pytest.mark.asyncio
async def test_start_and_stop_live_view_success(monkeypatch):
    instance = _make()
    updates = []

    def _set(data):
        instance.data = data
        updates.append(data)

    async def _refresh():
        return None

    instance.async_set_updated_data = _set
    instance.async_request_refresh = _refresh
    clamped = await instance.async_start_live_view(
        duration_seconds=120,
        interval_seconds=5,
    )
    assert clamped["live_view_target_interval"] == 10
    assert clamped["effective_scan_interval"] >= 10
    result = await instance.async_start_live_view(
        duration_seconds=999999,
        interval_seconds=999,
    )
    assert result["ok"] is True
    assert result["refresh_attempt_success"] is True
    assert updates
    stopped = await instance.async_stop_live_view()
    assert stopped["live_view_active"] is False


def test_error_merging_and_rate_limit_marking():
    instance = _make()
    errors = []
    raw = instance._new_raw_api_response_snapshot()
    err = SolaxApiError(
        code=10406,
        message="limited",
        classification="rate_limit",
    )
    instance._append_raw_snapshot(
        raw,
        endpoint=RAW_ENDPOINT_PAGE_PLANT_INFO,
        request={},
        error=err,
    )
    instance._merge_raw_errors_into_errors(errors, raw)
    instance._merge_raw_errors_into_errors(errors, raw)
    assert len(errors) == 1
    assert instance.rate_limited is True
    assert instance.rate_limited_context == [RAW_ENDPOINT_PAGE_PLANT_INFO]
    instance._append_error(errors, err, "other")
    instance._append_error(errors, RuntimeError("boom"), "runtime")
    assert len(errors) == 3


@pytest.mark.asyncio
async def test_full_refresh_cycle_and_live_view_cycle():
    instance = _make()
    result = await instance._async_update_data()

    assert set(result["plants"]) == {"P1", "P4"}
    assert "D11" in result["devices"]
    assert "MANUALMETER" in result["devices"]
    assert "EMS1" in result["devices"]
    assert "MANUALEMS" in result["devices"]
    assert result["plant_realtime"]["P1"]["dailyYield"] == 2
    assert result["alarms"]["P1"]["total"] == 1
    assert result["plant_stats"]["P1"]["year"]
    assert result["device_realtime"]["D11"]["totalActivePower"] == 10
    assert result["device_realtime"]["EMS1"]["sysPVPower"] == 11
    assert result["meta"]["token_auth_station_scope"] == "scoped:2"
    assert instance.last_successful_update is not None

    instance._live_view_until = datetime.now(timezone.utc) + timedelta(minutes=1)
    previous_alarms = result["alarms"]
    live_result = await instance._async_update_data()
    assert live_result["alarms"] == previous_alarms
    assert live_result["meta"]["poll_profile"] == "live_view"


@pytest.mark.asyncio
async def test_refresh_subpaths_record_partial_errors():
    class _PartialClient(_FullClient):
        async def plant_realtime_data(self, **kwargs):
            if kwargs["plant_id"] == "P4":
                raise SolaxApiError(
                    code=10406,
                    message="limited",
                    classification="rate_limit",
                )
            return await super().plant_realtime_data(**kwargs)

        async def page_alarm_info(self, **kwargs):
            raise SolaxApiError(
                code=10500,
                message="permission",
                classification="permission",
            )

        async def plant_stat_data(self, **kwargs):
            raise SolaxApiError(
                code=10500,
                message="permission",
                classification="permission",
            )

        async def device_realtime_data(self, **kwargs):
            raise SolaxApiError(
                code=10406,
                message="limited",
                classification="rate_limit",
            )

        async def ems_summary_data(self, **kwargs):
            raise SolaxApiError(
                code=10500,
                message="permission",
                classification="permission",
            )

    instance = _make(_PartialClient())
    result = await instance._async_update_data()
    assert result["last_errors"]
    assert instance.rate_limited is True


@pytest.mark.asyncio
async def test_partial_refresh_retains_last_good_plant_alarm_and_stat_values():
    instance = _make()
    initial = await instance._async_update_data()

    class _PartialFailureClient(_FullClient):
        async def plant_realtime_data(self, **kwargs):
            if kwargs["plant_id"] == "P4":
                raise SolaxApiError(
                    code=10406,
                    message="limited",
                    classification="rate_limit",
                )
            payload = await super().plant_realtime_data(**kwargs)
            payload["result"]["dailyYield"] = 77
            return payload

        async def page_alarm_info(self, **kwargs):
            raise SolaxApiError(
                code=10500,
                message="permission",
                classification="permission",
            )

        async def plant_stat_data(self, **kwargs):
            if kwargs["date_type"] == 1:
                raise SolaxApiError(
                    code=10500,
                    message="permission",
                    classification="permission",
                )
            payload = await super().plant_stat_data(**kwargs)
            payload["result"]["plantEnergyStatDataList"][0]["pvGeneration"] = 88
            return payload

    instance.client = _PartialFailureClient()
    refreshed = await instance._async_update_data()

    assert refreshed["plant_realtime"]["P1"]["dailyYield"] == 77
    assert refreshed["plant_realtime"]["P4"] == initial["plant_realtime"]["P4"]
    assert refreshed["alarms"] == initial["alarms"]
    assert refreshed["plant_stats"]["P1"]["year"] == initial["plant_stats"]["P1"]["year"]
    assert (
        refreshed["plant_stats"]["P1"]["month"]["plantEnergyStatDataList"][0][
            "pvGeneration"
        ]
        == 88
    )
    assert any(error["context"].startswith("alarms:") for error in refreshed["last_errors"])


@pytest.mark.asyncio
async def test_successful_zero_alarm_response_replaces_previous_alarm_state():
    instance = _make()
    await instance._async_update_data()

    class _NoAlarmClient(_FullClient):
        async def page_alarm_info(self, **kwargs):
            return {"code": 10000, "result": {"total": 0, "records": []}}

    instance.client = _NoAlarmClient()
    refreshed = await instance._async_update_data()
    assert all(item == {"total": 0, "records": []} for item in refreshed["alarms"].values())


@pytest.mark.asyncio
async def test_unexpected_endpoint_failures_retain_all_last_good_state():
    instance = _make()
    instance._poll_count = 1
    instance.data.update(
        {
            "plants": {"P1": {"plantId": "P1", "businessType": 1}},
            "devices": {
                "INV1": {"deviceSn": "INV1", "deviceType": 1, "businessType": 1},
                "EMS1": {
                    "deviceSn": "EMS1",
                    "deviceType": EMS_DEVICE_TYPE,
                    "businessType": 4,
                },
            },
            "inventory_by_type": {
                "1:1": ["INV1"],
                f"4:{EMS_DEVICE_TYPE}": ["EMS1"],
            },
            "plant_realtime": {"P1": {"dailyYield": 12}},
            "alarms": {"P1": {"total": 1, "records": [{"alarmName": "Keep"}]}},
            "plant_stats": {"P1": {"year": {"pvGeneration": 10}}},
            "device_realtime": {
                "INV1": {"deviceSn": "INV1", "totalActivePower": 50},
                "EMS1": {"deviceSn": "EMS1", "sysPVPower": 60},
            },
        }
    )

    async def _fail(*_args, **_kwargs):
        raise RuntimeError("unexpected endpoint failure")

    instance._refresh_plant_realtime = _fail
    instance._refresh_alarms = _fail
    instance._refresh_stats = _fail
    instance._refresh_device_realtime = _fail
    instance._refresh_ems_realtime = _fail

    with pytest.raises(UpdateFailed, match="No fresh API data"):
        await instance._async_update_data_unlocked()

    assert instance.data["plant_realtime"]["P1"]["dailyYield"] == 12
    assert instance.data["alarms"]["P1"]["records"][0]["alarmName"] == "Keep"
    assert instance.data["plant_stats"]["P1"]["year"]["pvGeneration"] == 10
    assert instance.data["device_realtime"]["INV1"]["totalActivePower"] == 50
    assert instance.data["device_realtime"]["EMS1"]["sysPVPower"] == 60
    assert {item["context"] for item in instance.data["last_errors"]} >= {
        "plant_realtime",
        "alarms",
        "plant_stats",
        "device_realtime",
        "ems_realtime",
    }


@pytest.mark.asyncio
async def test_partial_device_chunk_failure_merges_fresh_and_stale_values():
    instance = _make()
    instance._poll_count = 1
    instance._alarm_manager_unsub = lambda: None
    instance.data.update(
        {
            "plants": {"P1": {"plantId": "P1", "businessType": 1}},
            "devices": {
                "INV1": {"deviceSn": "INV1", "deviceType": 1, "businessType": 1},
                "INV2": {"deviceSn": "INV2", "deviceType": 1, "businessType": 1},
            },
            "inventory_by_type": {"1:1": ["INV1", "INV2"]},
            "plant_realtime": {"P1": {"dailyYield": 12}},
            "alarms": {"P1": {"total": 0, "records": []}},
            "plant_stats": {"P1": {"year": {"pvGeneration": 10}}},
            "device_realtime": {
                "INV1": {
                    "deviceSn": "INV1",
                    "totalActivePower": 10,
                    "battery": {"batterySOC": 70},
                },
                "INV2": {"deviceSn": "INV2", "totalActivePower": 20},
            },
        }
    )

    async def _plant_realtime(plants, *, raw_cycle):
        instance._append_raw_snapshot(
            raw_cycle,
            endpoint="plant_realtime_data",
            request={"plantId": "P1"},
            response={"code": 10000, "result": {"dailyYield": 13}},
        )
        return {"P1": {"dailyYield": 13}}, []

    async def _stats(_plants, *, raw_cycle):
        return instance.data["plant_stats"], []

    async def _device_realtime(_inventory, *, raw_cycle):
        return (
            {"INV1": {"deviceSn": "INV1", "totalActivePower": 99}},
            [
                (
                    "device_realtime:1:1:chunk:2",
                    SolaxApiError(
                        code=10406,
                        message="rate limited",
                        classification="rate_limit",
                    ),
                )
            ],
        )

    instance._refresh_plant_realtime = _plant_realtime
    instance._refresh_stats = _stats
    instance._refresh_device_realtime = _device_realtime

    refreshed = await instance._async_update_data_unlocked()

    assert refreshed["device_realtime"]["INV1"]["totalActivePower"] == 99
    assert refreshed["device_realtime"]["INV1"]["battery"]["batterySOC"] == 70
    assert refreshed["device_realtime"]["INV2"]["totalActivePower"] == 20
    assert refreshed["plant_realtime"]["P1"]["dailyYield"] == 13
    assert any(
        item["context"] == "device_realtime:1:1:chunk:2"
        for item in refreshed["last_errors"]
    )


@pytest.mark.asyncio
async def test_on_demand_caches_and_dry_run_limit():
    instance = _make()
    history = await instance.async_fetch_device_history(
        sn_list=["D11"],
        device_type=1,
        business_type=1,
        start_time=1,
        end_time=2,
        time_interval=5,
    )
    assert history["cached"] is True
    assert instance.history_cache
    assert instance.data["meta"]["history_cache_entries"] == 1

    with pytest.raises(ValueError):
        await instance.async_query_request_result(" ")
    assert (await instance.async_query_request_result("123"))["code"] == 0
    assert instance.request_result_cache
    assert (
        await instance.async_query_master_control_device(
            device_sn="D41",
            device_type=1,
            business_type=4,
        )
    )["code"] == 10000
    assert instance.master_control_cache

    for index in range(101):
        instance.record_control_dry_run(
            service=f"service-{index}",
            endpoint="/write",
            payload={"value": index},
        )
    assert len(instance.control_dry_runs) == 100


@pytest.mark.asyncio
async def test_ev_charger_control_execution_and_target_validation(monkeypatch):
    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(coordinator_module.asyncio, "sleep", _no_sleep)
    instance = _make()
    instance._ev_charger_controls_enabled = True
    instance.data["devices"] = {
        "D14": {
            "deviceSn": "D14",
            "deviceType": 4,
            "businessType": 1,
        },
        "D44": {
            "deviceSn": "D44",
            "deviceType": 4,
            "businessType": 4,
        },
        "D11": {
            "deviceSn": "D11",
            "deviceType": 1,
            "businessType": 1,
        },
    }

    assert instance.ev_charger_controls_enabled is True
    assert instance.get_known_ev_charger_serial("D14")["source"] == "inventory"
    assert instance.get_known_ev_charger_serial("D11") is None
    assert instance._control_response_status_summary(
        {"code": 10000, "result": {"D14": {"status": 4}}}
    )["accepted"] is True
    assert instance._control_response_status_summary(
        {"code": 10000, "result": {"D14": {"status": 5}}}
    )["accepted"] is False
    assert instance._control_response_status_summary(
        {"code": 10000, "result": []}
    )["accepted"] is True

    event = await instance.async_execute_ev_charger_control(
        service="set_evc_work_mode",
        endpoint="/openapi/v2/device/evc_control/set_evc_work_mode",
        payload={"snList": ["D14"], "workMode": 2, "current": 16, "businessType": 1},
    )
    assert event["sent"] is True
    assert event["accepted"] is True
    assert event["request_id"] == "REQ-EVC"
    assert event["initial_device_statuses"]["D14"]["status"] == 3
    assert event["device_statuses"]["D14"]["status"] == 4
    assert event["confirmation_state"] == "device_acknowledged"
    assert event["device_acknowledged"] is True
    assert event["execution_started"] is True
    assert event["command_failed"] is False
    assert instance.data["meta"]["last_ev_charger_control"] is event

    with pytest.raises(ValueError, match="not_ev_charger_control"):
        instance._validate_ev_charger_control_targets(
            service="set_export_control",
            payload={"snList": ["D14"], "businessType": 1},
        )
    with pytest.raises(ValueError, match="control_ev_charger_target_unknown"):
        instance._validate_ev_charger_control_targets(
            service="set_evc_work_mode",
            payload={"snList": ["MISSING"], "businessType": 1},
        )
    with pytest.raises(ValueError, match="control_ev_charger_business_type_mismatch"):
        instance._validate_ev_charger_control_targets(
            service="set_evc_work_mode",
            payload={"snList": ["D44"], "businessType": 1},
        )

    instance._ev_charger_control_commands = [{"index": index} for index in range(100)]
    await instance.async_execute_ev_charger_control(
        service="set_evc_charge_command",
        endpoint="/openapi/v2/device/evc_control/set_evc_charge_command",
        payload={"snList": ["D14"], "workCmd": 2, "businessType": 1},
    )
    assert len(instance.ev_charger_control_commands) == 100
    assert instance.ev_charger_control_commands[0]["index"] == 1


@pytest.mark.asyncio
async def test_ev_charger_confirmation_pending_and_failure(monkeypatch):
    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(coordinator_module.asyncio, "sleep", _no_sleep)

    class _PendingClient(_FullClient):
        async def query_request_result(self, **kwargs):
            return {"code": 0, "result": [{"sn": "D14", "status": 3}]}

    pending = _make(_PendingClient())
    pending._ev_charger_controls_enabled = True
    pending.data["devices"] = {
        "D14": {"deviceSn": "D14", "deviceType": 4, "businessType": 1}
    }
    pending_event = await pending.async_execute_ev_charger_control(
        service="set_evc_charge_command",
        endpoint="/openapi/v2/device/evc_control/set_evc_charge_command",
        payload={"snList": ["D14"], "workCmd": 2, "businessType": 1},
    )
    assert pending_event["accepted"] is True
    assert pending_event["pending"] is True
    assert pending_event["device_acknowledged"] is False
    assert pending_event["confirmation_state"] == "pending"
    assert pending_event["confirmation_attempts"] == 5

    class _FailureClient(_FullClient):
        async def query_request_result(self, **kwargs):
            return {"code": 0, "result": [{"sn": "D14", "status": 5}]}

    failed = _make(_FailureClient())
    failed._ev_charger_controls_enabled = True
    failed.data["devices"] = pending.data["devices"]
    failed_event = await failed.async_execute_ev_charger_control(
        service="set_evc_charge_command",
        endpoint="/openapi/v2/device/evc_control/set_evc_charge_command",
        payload={"snList": ["D14"], "workCmd": 2, "businessType": 1},
    )
    assert failed_event["accepted"] is True
    assert failed_event["command_failed"] is True
    assert failed_event["pending"] is False
    assert failed_event["confirmation_state"] == "failed"
    assert failed_event["device_statuses"]["D14"]["status"] == 5


@pytest.mark.asyncio
async def test_ev_charger_response_shapes_and_confirmation_shortcuts(monkeypatch):
    single = SolaxDeveloperCoordinator._control_response_status_summary(
        {
            "code": 10000,
            "result": {"deviceSn": "EV1", "status": 4},
        }
    )
    assert single["device_statuses"]["EV1"]["device_acknowledged"] is True

    serial_mapping = SolaxDeveloperCoordinator._control_response_status_summary(
        {"code": 10000, "result": {"EV2": {"status": 3}, "ignored": "row"}}
    )
    assert serial_mapping["device_statuses"]["EV2"]["accepted"] is True

    list_response = SolaxDeveloperCoordinator._control_response_status_summary(
        {
            "code": 10000,
            "result": [
                "malformed",
                {"registerNo": "EV3", "status": 5},
                {"status": 3},
            ],
        }
    )
    assert list_response["device_statuses"]["EV3"]["failed"] is True
    assert list_response["device_statuses"]["device_3"]["status"] == 3

    instance = _make()
    failed = await instance._confirm_ev_charger_control(
        request_id="REQ",
        initial_summary={
            "accepted": False,
            "device_statuses": {"EV1": {"failed": True}},
            "command_failed": True,
            "device_acknowledged": False,
            "pending": False,
        },
    )
    assert failed["confirmation_state"] == "failed"
    assert failed["confirmation_attempts"] == 0

    acknowledged = await instance._confirm_ev_charger_control(
        request_id="REQ",
        initial_summary={
            "accepted": True,
            "device_statuses": {"EV1": {"device_acknowledged": True}},
            "command_failed": False,
            "device_acknowledged": True,
            "pending": False,
        },
    )
    assert acknowledged["confirmation_state"] == "device_acknowledged"
    assert acknowledged["confirmation_attempts"] == 0

    unavailable = await instance._confirm_ev_charger_control(
        request_id="",
        initial_summary={
            "accepted": True,
            "device_statuses": {},
            "command_failed": False,
            "device_acknowledged": False,
            "pending": False,
        },
    )
    assert unavailable["confirmation_state"] == "unavailable"

    async def _no_sleep(_seconds):
        return None

    async def _query_failure(_request_id):
        raise SolaxApiError(
            code=10406,
            message="rate limited",
            classification="rate_limit",
        )

    monkeypatch.setattr(coordinator_module.asyncio, "sleep", _no_sleep)
    instance.async_query_request_result = _query_failure
    query_failed = await instance._confirm_ev_charger_control(
        request_id="REQ",
        initial_summary={
            "accepted": True,
            "device_statuses": {"EV1": {"status": 3}},
            "command_failed": False,
            "device_acknowledged": False,
            "pending": True,
        },
    )
    assert query_failed["confirmation_state"] == "query_failed"
    assert query_failed["confirmation_attempts"] == 5
    assert query_failed["confirmation_error"]["classification"] == "rate_limit"


@pytest.mark.asyncio
async def test_ev_charger_command_cache_recovers_from_malformed_internal_state(
    monkeypatch,
):
    async def _no_sleep(_seconds):
        return None

    class _AcknowledgedClient(_FullClient):
        async def execute_control(self, **kwargs):
            return {
                "code": 10000,
                "message": "success",
                "result": {"deviceSn": "D14", "status": 4},
            }

    monkeypatch.setattr(coordinator_module.asyncio, "sleep", _no_sleep)
    instance = _make(_AcknowledgedClient())
    instance._ev_charger_controls_enabled = True
    instance._ev_charger_control_commands = "malformed"
    instance.data["devices"] = {
        "D14": {"deviceSn": "D14", "deviceType": 4, "businessType": 1}
    }

    event = await instance.async_execute_ev_charger_control(
        service="set_evc_charge_command",
        endpoint="/openapi/v2/device/evc_control/set_evc_charge_command",
        payload={"snList": ["D14"], "workCmd": 2, "businessType": 1},
    )

    assert event["confirmation_state"] == "device_acknowledged"
    assert instance.ev_charger_control_commands == [event]
