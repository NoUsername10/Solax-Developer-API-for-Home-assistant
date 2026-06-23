from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solax_developer_api import coordinator as coordinator_module
from custom_components.solax_developer_api.api import SolaxApiError
from custom_components.solax_developer_api.coordinator import (
    EMS_DEVICE_TYPE,
    RAW_ENDPOINT_PAGE_PLANT_INFO,
    SolaxDeveloperCoordinator,
    _flatten_dict,
)


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
        return {"code": 0, "result": {"requestId": kwargs["request_id"]}}


def _make(client=None):
    instance = object.__new__(SolaxDeveloperCoordinator)
    instance.hass = _Hass()
    instance.client = client or _FullClient()
    instance._base_scan_interval = 120
    instance._effective_scan_interval = 120
    instance._live_view_requested_interval = 5
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
    instance._request_result_cache = {}
    instance._master_control_cache = {}
    instance._control_dry_runs = []
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
    instance._device_capabilities = {}
    instance._raw_api_responses = instance._new_raw_api_response_snapshot()
    instance._capability_store = _Store()
    instance.rate_limited = False
    instance.rate_limited_context = []
    instance.last_rate_limit_at = None
    instance.last_update_attempt = None
    instance.last_successful_update = None
    instance.update_interval = timedelta(seconds=120)
    instance.data = instance._empty_state()
    return instance


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
            "live_view_default_duration": 999999,
            "live_view_interval": "bad",
            "live_view_call_budget_per_minute": 999,
            "night_scan_interval": 1,
            "night_start_hour": -1,
            "night_end_hour": 99,
            "manual_meter_serials": "M1|4",
            "manual_ems_systems": "E1|P4",
        },
    )

    assert instance._base_scan_interval == 60
    assert instance._live_view_call_budget_per_minute <= 100
    assert instance._night_start_hour == 0
    assert instance._night_end_hour == 23
    assert instance.manual_meter_entries[0]["serial"] == "M1"
    assert instance.manual_ems_entries[0]["serial"] == "E1"
    assert instance._capability_store.key.endswith("entry-x")


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
