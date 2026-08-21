import pytest

from custom_components.solax_developer_api.coordinator import SolaxDeveloperCoordinator


def _make_coordinator(client, manual_entries=None, manual_ems_entries=None):
    coordinator = object.__new__(SolaxDeveloperCoordinator)
    coordinator.client = client
    coordinator._manual_meter_entries = manual_entries or []
    coordinator._manual_ems_entries = manual_ems_entries or []
    coordinator.data = {}
    return coordinator


class _InventoryClient:
    async def page_plant_info(self, *, business_type, page_no):
        return {
            "code": 10000,
            "result": {
                "records": [],
                "current": 1,
                "pages": 1,
            },
        }

    async def page_device_info(self, *, business_type, device_type, page_no):
        if business_type == 1 and device_type == 3:
            return {
                "code": 10000,
                "result": {
                    "records": [
                        {
                            "deviceSn": "AUTO_METER_1",
                            "deviceType": 3,
                            "businessType": 1,
                            "onlineStatus": 1,
                        }
                    ],
                    "current": 1,
                    "pages": 1,
                },
            }
        return {
            "code": 10000,
            "result": {
                "records": [],
                "current": 1,
                "pages": 1,
            },
        }


class _ProbeClient:
    async def device_realtime_data(self, *, sn_list, device_type, business_type, request_sn_type=None):
        serial = list(sn_list)[0]
        if business_type == 1 and serial.casefold() == "testmeter000001":
            return {
                "code": 10000,
                "result": [
                    {
                        "deviceSn": "TESTMETER000001",
                        "dataTime": "2026-03-14T13:00:03.000+00:00",
                        "importEnergy": 87.6,
                        "exportEnergy": 4260.4,
                        "totalActivePower": -1480,
                    }
                ],
            }
        return {"code": 10000, "result": []}

    async def device_history_data_windowed(
        self,
        *,
        sn_list,
        device_type,
        business_type,
        start_time,
        end_time,
        time_interval,
        request_sn_type=None,
        max_window_ms=None,
        request_delay_seconds=0.0,
        cancellation_check=None,
    ):
        return {
            "code": 10000,
            "result": [
                {
                    "deviceSn": "TESTMETER000001",
                    "dataTime": "2026-03-14T13:00:00.000+00:00",
                    "importEnergy": 87.6,
                }
            ],
            "windowSummary": {"windowCount": 1},
        }


class _ProbeEmptyClient:
    async def device_realtime_data(self, *, sn_list, device_type, business_type, request_sn_type=None):
        return {"code": 10000, "result": []}

    async def device_history_data_windowed(
        self,
        *,
        sn_list,
        device_type,
        business_type,
        start_time,
        end_time,
        time_interval,
        request_sn_type=None,
        max_window_ms=None,
        request_delay_seconds=0.0,
        cancellation_check=None,
    ):
        return {"code": 10000, "result": [], "windowSummary": {"windowCount": 0}}


class _EmsInventoryClient:
    async def page_plant_info(self, *, business_type, page_no):
        records = (
            [{"plantId": "CI_PLANT", "businessType": 4}]
            if business_type == 4
            else []
        )
        return {
            "code": 10000,
            "result": {"records": records, "current": 1, "pages": 1},
        }

    async def page_device_info(self, *, business_type, device_type, page_no):
        records = (
            [
                {
                    "deviceSn": "CI_INV",
                    "plantId": "CI_PLANT",
                    "onlineStatus": 1,
                }
            ]
            if business_type == 4 and device_type == 1
            else []
        )
        return {
            "code": 10000,
            "result": {"records": records, "current": 1, "pages": 1},
        }

    async def get_master_control_device(self, *, device_sn, device_type, business_type):
        return {
            "code": 10000,
            "result": {
                "deviceSn": device_sn,
                "controlDeviceType": 100,
                "controlDeviceSn": "EMS_TOP",
            },
        }

    async def ems_attribute_info(self, *, register_no, plant_id, business_type):
        return {
            "code": 10000,
            "result": [
                {
                    "registerNo": register_no,
                    "stationId": plant_id,
                    "deviceModel": 1,
                    "deviceName": "EMS",
                    "sysACRatedPower": 100,
                }
            ],
        }


class _ManualEmsProbeClient:
    async def ems_attribute_info(self, *, register_no, plant_id, business_type):
        return {
            "code": 10000,
            "result": [
                {
                    "registerNo": register_no,
                    "stationId": plant_id,
                    "deviceName": "EMS",
                }
            ],
        }


class _DummyStore:
    def __init__(self):
        self.save_calls = 0

    def async_delay_save(self, _callback, _delay):
        self.save_calls += 1


@pytest.mark.asyncio
async def test_refresh_inventory_merges_manual_meter_serial_without_duplicates():
    coordinator = _make_coordinator(
        _InventoryClient(),
        manual_entries=[
            {"serial": "AUTO_METER_1", "business_type": 1},
            {"serial": "MANUAL_METER_1", "business_type": 1},
        ],
    )

    _plants, devices, inventory = await coordinator._refresh_inventory()
    assert "AUTO_METER_1" in devices
    assert devices["AUTO_METER_1"].get("manualSerial") is not True
    assert "MANUAL_METER_1" in devices
    assert devices["MANUAL_METER_1"]["manualSerial"] is True
    assert sorted(inventory["1:3"]) == ["AUTO_METER_1", "MANUAL_METER_1"]


@pytest.mark.asyncio
async def test_refresh_inventory_discovers_ems_through_ci_master_device():
    coordinator = _make_coordinator(_EmsInventoryClient())
    _plants, devices, inventory = await coordinator._refresh_inventory()

    assert devices["EMS_TOP"]["deviceType"] == 100
    assert devices["EMS_TOP"]["deviceName"] == "EMS"
    assert inventory["4:100"] == ["EMS_TOP"]


@pytest.mark.asyncio
async def test_probe_manual_ems_validates_attribute_endpoint():
    coordinator = _make_coordinator(_ManualEmsProbeClient())
    result = await coordinator.async_probe_manual_ems_system(
        serial="EMS_MANUAL",
        plant_id="CI_PLANT",
    )

    assert result["ok"] is True
    assert result["serial_resolved"] == "EMS_MANUAL"
    assert result["plant_id"] == "CI_PLANT"


@pytest.mark.asyncio
async def test_probe_manual_meter_serial_collects_field_summary():
    coordinator = _make_coordinator(_ProbeClient())
    result = await coordinator.async_probe_manual_meter_serial("TESTMETER000001")

    assert result["ok"] is True
    assert result["business_type"] == 1
    assert result["serial_resolved"] == "TESTMETER000001"
    assert "importEnergy" in result["field_summary"]["realtime_fields"]
    assert "deviceSn" in result["field_summary"]["history_fields"]


@pytest.mark.asyncio
async def test_probe_manual_meter_serial_returns_failure_when_not_found():
    coordinator = _make_coordinator(_ProbeEmptyClient())
    result = await coordinator.async_probe_manual_meter_serial("UNKNOWN_METER")

    assert result["ok"] is False
    assert result["reason"] == "realtime_not_found"
    assert len(result["realtime_attempts"]) == 2


def test_normalize_manual_meter_entries_accepts_tuple_and_mapping():
    entries = (
        {"serial": "METER_A", "business_type": 1},
        {"deviceSn": "METER_B", "businessType": 4, "realtime_fields": ["importEnergy", "exportEnergy"]},
    )
    normalized = SolaxDeveloperCoordinator._normalize_manual_meter_entries(entries)
    assert normalized == [
        {"serial": "METER_A", "business_type": 1, "source": "manual"},
        {
            "serial": "METER_B",
            "business_type": 4,
            "source": "manual",
            "realtime_fields": ["exportEnergy", "importEnergy"],
        },
    ]


def test_normalize_manual_meter_entries_accepts_python_literal_string():
    raw = (
        "[{'serial': 'METER_A', 'business_type': 1}, "
        "{'deviceSn': 'METER_B', 'businessType': 4, 'realtime_fields': ['importEnergy']}]"
    )
    normalized = SolaxDeveloperCoordinator._normalize_manual_meter_entries(raw)
    assert normalized == [
        {"serial": "METER_A", "business_type": 1, "source": "manual"},
        {
            "serial": "METER_B",
            "business_type": 4,
            "source": "manual",
            "realtime_fields": ["importEnergy"],
        },
    ]


def test_normalize_manual_meter_entries_accepts_pipe_delimited_string():
    raw = "METER_A|1\nMETER_B|4"
    normalized = SolaxDeveloperCoordinator._normalize_manual_meter_entries(raw)
    assert normalized == [
        {"serial": "METER_A", "business_type": 1, "source": "manual"},
        {"serial": "METER_B", "business_type": 4, "source": "manual"},
    ]


def test_update_device_capabilities_persists_online_observed_fields():
    coordinator = _make_coordinator(_InventoryClient())
    coordinator._device_capabilities = {}
    coordinator._capability_store = _DummyStore()

    coordinator._update_device_capabilities(
        {"INV-1": {"deviceSn": "INV-1", "deviceType": 1, "businessType": 1, "onlineStatus": 1}},
        {
            "INV-1": {
                "deviceSn": "INV-1",
                "deviceType": 1,
                "businessType": 1,
                "onlineStatus": 1,
                "acPower": 5234,
                "dcPower": None,
            }
        },
    )

    cached = coordinator.device_capability_fields
    assert "inv-1" in cached
    assert "acPower" in cached["inv-1"]
    assert "dcPower" not in cached["inv-1"]
    assert coordinator._capability_store.save_calls == 1


def test_update_device_capabilities_does_not_promote_new_fields_while_offline():
    coordinator = _make_coordinator(_InventoryClient())
    coordinator._device_capabilities = {
        "inv-1": {
            "serial": "INV-1",
            "fields": ["acPower"],
            "device_type": 1,
            "business_type": 1,
            "updated_at": "2026-03-17T00:00:00+00:00",
            "last_seen_online": "2026-03-17T00:00:00+00:00",
        }
    }
    coordinator._capability_store = _DummyStore()

    coordinator._update_device_capabilities(
        {"INV-1": {"deviceSn": "INV-1", "deviceType": 1, "businessType": 1, "onlineStatus": 0}},
        {
            "INV-1": {
                "deviceSn": "INV-1",
                "deviceType": 1,
                "businessType": 1,
                "onlineStatus": 0,
                "newField": 99,
            }
        },
    )

    cached = coordinator.device_capability_fields
    assert cached["inv-1"] == {"acPower"}
    assert coordinator._capability_store.save_calls == 0
