from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.solax_developer_api import sensor


class _Config:
    language = "en"


class _Hass:
    config = _Config()


class _Coordinator:
    def __init__(self):
        self.hass = _Hass()
        now = datetime.now(timezone.utc)
        self.client = SimpleNamespace(token_expires_at=now + timedelta(days=10))
        self.last_update_attempt = now
        self.last_successful_update = now
        self.last_rate_limit_at = now
        self.rate_limited = True
        self.rate_limited_context = ["device_realtime"]
        self.update_interval = timedelta(seconds=120)
        self.device_capability_fields = {
            "inv1": {"totalActivePower", "offlineCapability"},
            "meter1": {"importEnergy"},
        }
        self.listener = None
        self.data = _state()

    def async_add_listener(self, listener):
        self.listener = listener
        return lambda: None


def _state():
    stat_records = [
        {
            "pvGeneration": 10,
            "inverterACOutputEnergy": "9",
            "exportEnergy": 2,
            "importEnergy": 3,
            "loadConsumption": 8,
            "batteryCharged": 1,
            "batteryDischarged": 0.5,
            "earnings": 4.2,
        },
        "invalid",
        {"pvGeneration": "bad", "exportEnergy": None},
    ]
    return {
        "plants": {
            "P1": {
                "plantId": "P1",
                "plantName": "Main Plant",
                "businessType": 1,
                "plantState": 2,
                "plantTimeZone": "Europe/Madrid",
                "electricityPriceUnit": "EUR",
                "otherInfo": "extra",
            },
            "P2": {"plantId": "P2", "businessType": 4},
        },
        "plant_realtime": {
            "P1": {
                "dailyYield": 4.5,
                "totalYield": 100.5,
                "acPower": 1500,
                "nested": {"voltage": 230},
                "nullField": None,
            },
            "P2": {"dailyYield": "bad", "totalYield": None},
        },
        "plant_stats": {
            "P1": {
                "year": {"plantEnergyStatDataList": stat_records},
                "month": {"plantEnergyStatDataList": stat_records},
            }
        },
        "alarms": {
            "P1": {
                "total": 2,
                "records": [
                    {
                        "alarmName": "Grid",
                        "errorCode": "E1",
                        "alarmType": 2,
                    },
                    "invalid",
                    {"alarmName": "Temperature"},
                ],
            }
        },
        "devices": {
            "INV1": {
                "deviceSn": "INV1",
                "deviceType": 1,
                "businessType": 1,
                "deviceModel": 14,
                "onlineStatus": 1,
                "flag": 0,
                "armVersion": "1.0",
            },
            "INV2": {
                "deviceSn": "INV2",
                "deviceType": 1,
                "businessType": 4,
                "deviceModel": 25,
                "onlineStatus": "bad",
                "flag": 1,
            },
            "METER1": {
                "deviceSn": "METER1",
                "deviceType": 3,
                "businessType": 1,
                "deviceModel": 50,
                "onlineStatus": 1,
                "flag": 0,
            },
            "EMS1": {
                "deviceSn": "EMS1",
                "deviceType": 100,
                "businessType": 4,
                "onlineStatus": 1,
            },
        },
        "device_realtime": {
            "INV1": {
                "deviceSn": "INV1",
                "deviceType": 1,
                "businessType": 1,
                "totalActivePower": 1000,
                "MPPTTotalInputPower": 1250,
                "dailyYield": 4,
                "deviceStatus": 1,
                "deviceWorkingMode": 1,
                "dataTime": "2026-06-23T12:00:00+00:00",
                "mpptMap": {"mppt1Power": 600, "mppt2Power": 650},
            },
            "INV2": {
                "deviceSn": "INV2",
                "deviceType": 1,
                "businessType": 4,
                "acPower1": 1,
                "acPower2": 2,
                "acPower3": 3,
                "mpptMap": {"mppt1Power": 5, "ignored": None},
            },
            "METER1": {
                "deviceSn": "METER1",
                "deviceType": 3,
                "businessType": 1,
                "importEnergy": 90.5,
                "totalActivePower": 650,
            },
            "UNKNOWN": "invalid",
        },
        "last_errors": [{"classification": "timeout"}],
        "meta": {
            "poll_profile": "live_view",
            "effective_scan_interval": 8,
            "live_view_active": True,
            "live_view_remaining_seconds": 55,
            "live_view_until": "2026-06-23T12:01:00+00:00",
            "live_view_target_interval": 5,
            "live_view_call_budget_per_minute": 20,
            "live_view_estimated_calls_per_cycle": 2,
            "night_scan_interval": 600,
            "dry_run_commands": 1,
            "last_dry_run": {"service": "set_export_control"},
        },
    }


def test_sensor_helpers_cover_types_mappings_and_units():
    hass = _Hass()
    assert sensor._flatten_dict({"a": {"b": 1}}) == {"a_b": 1}
    assert sensor._snake("AC Power!") == "ac_power"
    assert sensor._humanize_key("acPower") == "AC Power"
    assert sensor._humanize_key("epsL1") == "EPS L1"
    assert sensor._humanize_key("L1L2Voltage") == "L1-L2 Voltage"

    kinds = {
        "powerFactor": "factor",
        "reactivePower": "reactive_power",
        "apparentPower": "apparent_power",
        "activePower": "power",
        "dailyYield": "energy",
        "batterySOC": "battery_percent",
        "temperature": "temperature",
        "gridFrequency": "frequency",
        "voltage": "voltage",
        "current": "current",
        "dataTime": "time",
        "earnings": "earnings",
        "name": None,
    }
    for key, expected in kinds.items():
        assert sensor._field_kind(key) == expected

    assert sensor._safe_float("1.5") == 1.5
    assert sensor._safe_float("bad") is None
    assert sensor._normalize_numeric_value("activePower", 1.5, 4) == 1500.0
    assert sensor._normalize_numeric_value("dataTime", "now", 1) == "now"
    assert sensor._normalize_numeric_value("activePower", "bad", 1) == "bad"
    assert sensor._normalize_numeric_value("name", "x", 1) == "x"

    assert sensor._status_text(hass, 1, 1, "deviceStatus", None) is None
    assert sensor._status_text(hass, 1, 1, "deviceStatus", "bad") == "bad"
    assert sensor._status_text(hass, 1, 1, "deviceStatus", 999) == "999"
    assert sensor._status_text(hass, 2, 1, "deviceStatus", 999) == "999"
    assert sensor._status_text(hass, 4, 1, "deviceStatus", 999) == "999"
    assert sensor._status_text(hass, 4, 1, "deviceStatus", 1)
    assert sensor._status_text(hass, 1, 1, "deviceWorkingMode", 1)
    assert sensor._status_text(hass, 1, 1, "deviceWorkingMode", 999) == "999"
    assert sensor._status_text(hass, 1, 1, "deviceModel", 14)
    assert sensor._status_text(hass, 1, 1, "status", 0)
    assert sensor._status_text(hass, 1, 1, "status", 999) == "999"
    assert sensor._status_text(hass, 1, 1, "unchanged", 1) == 1
    assert (
        sensor._status_text(hass, 1, 1, "businessType", 1)
        == "Type 1, Residential"
    )
    assert (
        sensor._status_text(hass, 1, 4, "businessType", 4)
        == "Type 4, Commercial & Industrial"
    )
    for device_type, label in (
        (1, "Inverter"),
        (2, "Battery"),
        (3, "Meter"),
        (4, "EV Charger"),
        (100, "EMS"),
    ):
        assert sensor._status_text(
            hass, device_type, 1, "deviceType", device_type
        ) == f"Type {device_type}, {label}"
    assert (
        sensor._status_text(hass, 999, 1, "deviceType", 999)
        == "Type 999, Unknown"
    )
    assert (
        sensor._status_text(hass, 1, 999, "businessType", 999)
        == "Type 999, Unknown"
    )
    assert (
        sensor._status_text(hass, 1, 1, "deviceType", "malformed")
        == "Type malformed, Unknown"
    )

    expectations = {
        "batterySOC": ("%", SensorDeviceClass.BATTERY),
        "temperature": ("°C", SensorDeviceClass.TEMPERATURE),
        "frequency": ("Hz", SensorDeviceClass.FREQUENCY),
        "voltage": ("V", SensorDeviceClass.VOLTAGE),
        "current": ("A", SensorDeviceClass.CURRENT),
        "activePower": ("W", SensorDeviceClass.POWER),
        "reactivePower": ("var", None),
        "apparentPower": ("VA", None),
        "dailyEnergy": ("kWh", SensorDeviceClass.ENERGY),
        "powerFactor": (None, None),
        "name": (None, None),
    }
    for key, expected in expectations.items():
        unit, device_class, _state_class = sensor._infer_unit_and_classes(key)
        assert (unit, device_class) == expected

    assert sensor._device_model_text(hass, "bad") == "bad"
    assert sensor._device_model_text(hass, 14, business_type="x", device_type=1)
    assert sensor._device_type_text(hass, "bad") == "Device"
    assert sensor._device_type_text(hass, 999) == "Device"
    assert sensor._business_type_text(hass, "bad") == "Unknown"
    assert sensor._plant_state_text(hass, 1, "bad") == "bad"
    assert sensor._plant_state_text(hass, 1, 0) == "Connecting"
    assert sensor._plant_state_text(hass, 1, 1) == "Offline"
    assert sensor._plant_state_text(hass, 1, 2) == "Online"
    assert sensor._plant_state_text(hass, 4, 1)
    assert sensor._online_status_text(hass, "bad") == "bad"
    assert sensor._online_status_text(hass, 1) == "Online"
    assert sensor._online_status_text(hass, 0) == "Offline"
    assert sensor._parallel_flag_text(hass, 1, "bad") == "bad"
    assert sensor._parallel_flag_text(hass, 1, 0)
    assert sensor._parallel_flag_text(hass, 4, 1)


def test_extract_stat_metrics_tolerates_invalid_rows():
    metrics = sensor._extract_stat_metrics(
        {
            "plantEnergyStatDataList": [
                {"pvGeneration": 1, "earnings": "2.5"},
                None,
                {"pvGeneration": "bad", "exportEnergy": None},
            ]
        }
    )
    assert metrics["pvGeneration"] == 1
    assert metrics["earnings"] == 2.5
    assert sensor._extract_stat_metrics(None)["pvGeneration"] == 0


def test_system_sensors_values_and_attributes():
    coordinator = _Coordinator()
    values = {}
    attributes = {}
    for key in (
        "system_ac_power",
        "system_dc_power",
        "system_yield_today",
        "system_yield_total",
        "system_efficiency",
        "system_health",
        "device_connectivity",
        "api_rate_limit_status",
        "poll_profile",
        "effective_scan_interval",
        "live_view_active",
        "live_view_remaining_seconds",
        "last_poll_attempt",
        "next_scheduled_poll",
        "token_expires_at",
        "dry_run_command_count",
        "unknown",
    ):
        entity = sensor.SolaxSystemSensor(coordinator, key, "SDS", "sds")
        values[key] = entity.native_value
        attributes[key] = entity.extra_state_attributes
        assert entity.device_info["identifiers"] == {
            ("solax_developer_api", "system_sds")
        }

    assert values["system_ac_power"] == 7000
    assert values["system_dc_power"] == 6250
    assert values["system_yield_today"] == 4.5
    assert values["system_yield_total"] == 100.5
    assert values["system_efficiency"] == 112.0
    assert values["system_health"] == "Degraded"
    assert values["device_connectivity"] == "Degraded"
    assert values["api_rate_limit_status"] == "Rate Limited"
    assert values["poll_profile"] == "live_view"
    assert values["effective_scan_interval"] == 8
    assert values["live_view_active"] == "Active"
    assert values["live_view_remaining_seconds"] == 55
    assert values["next_scheduled_poll"] is not None
    assert values["dry_run_command_count"] == 1
    assert values["unknown"] is None
    assert attributes["system_ac_power"]["calculation_scope"]
    assert attributes["system_dc_power"]["excluded_non_inverter_serials"] == [
        "METER1"
    ]
    assert attributes["system_efficiency"]["zero_input_behavior"]
    assert attributes["system_health"]["errors"]
    assert attributes["system_health"]["active_alarm_count"] == 2
    assert attributes["device_connectivity"]["offline_device_serials"] == []
    assert attributes["device_connectivity"]["unknown_device_serials"] == ["INV2"]
    assert attributes["api_rate_limit_status"]["last_rate_limit_at"]
    assert attributes["dry_run_command_count"]["last_dry_run"]
    assert attributes["next_scheduled_poll"]["seconds_until_next_poll"] >= 0
    assert attributes["poll_profile"]["live_view_target_interval"] == 5


def test_system_sensor_edge_states():
    coordinator = _Coordinator()
    coordinator.data["devices"] = {}
    coordinator.data["device_realtime"] = {}
    coordinator.data["plant_realtime"] = {}
    coordinator.last_update_attempt = None
    coordinator.last_successful_update = None
    coordinator.rate_limited = False
    coordinator.last_rate_limit_at = None

    assert (
        sensor.SolaxSystemSensor(
            coordinator, "system_health", "SDS", "sds"
        ).native_value
        == "Unknown"
    )
    assert (
        sensor.SolaxSystemSensor(
            coordinator, "device_connectivity", "SDS", "sds"
        ).native_value
        == "Unknown"
    )
    assert (
        sensor.SolaxSystemSensor(
            coordinator, "system_efficiency", "SDS", "sds"
        ).native_value
        == 0
    )
    assert (
        sensor.SolaxSystemSensor(
            coordinator, "next_scheduled_poll", "SDS", "sds"
        ).native_value
        is None
    )
    assert (
        sensor.SolaxSystemSensor(
            coordinator, "api_rate_limit_status", "SDS", "sds"
        ).native_value
        == "OK"
    )

    coordinator.data["alarms"] = {}
    coordinator.data["devices"] = {
        "A": {"deviceType": 1, "businessType": 1, "onlineStatus": 0},
        "B": {"deviceType": 1, "businessType": 1, "onlineStatus": 0},
    }
    coordinator.data["device_realtime"] = {
        "A": {"deviceType": 1, "businessType": 1, "deviceStatus": 104}
    }
    assert (
        sensor.SolaxSystemSensor(
            coordinator, "system_health", "SDS", "sds"
        ).native_value
        == "Error"
    )
    assert (
        sensor.SolaxSystemSensor(
            coordinator, "device_connectivity", "SDS", "sds"
        ).native_value
        == "Offline"
    )


def test_system_health_and_connectivity_are_independent():
    coordinator = _Coordinator()
    coordinator.rate_limited = False
    coordinator.data = {
        "plants": {"P1": {"plantId": "P1", "businessType": 1}},
        "alarms": {"P1": {"total": 0, "records": []}},
        "devices": {
            "INV1": {
                "deviceSn": "INV1",
                "deviceType": 1,
                "businessType": 1,
                "onlineStatus": 0,
            },
            "INV2": {
                "deviceSn": "INV2",
                "deviceType": 1,
                "businessType": 1,
                "onlineStatus": 0,
            },
            "METER1": {
                "deviceSn": "METER1",
                "deviceType": 3,
                "businessType": 1,
                "onlineStatus": None,
                "manualSerial": True,
            },
        },
        "device_realtime": {
            "INV1": {
                "deviceSn": "INV1",
                "deviceType": 1,
                "businessType": 1,
                "deviceStatus": 100,
            },
            "INV2": {
                "deviceSn": "INV2",
                "deviceType": 1,
                "businessType": 1,
                "deviceStatus": 100,
            },
            "METER1": {
                "deviceSn": "METER1",
                "deviceType": 3,
                "businessType": 1,
                "totalActivePower": 600,
            },
        },
        "last_errors": [],
        "meta": {"effective_scan_interval": 120},
    }

    health = sensor.SolaxSystemSensor(
        coordinator, "system_health", "SDS", "sds"
    )
    connectivity = sensor.SolaxSystemSensor(
        coordinator, "device_connectivity", "SDS", "sds"
    )

    assert health.native_value == "OK"
    assert connectivity.native_value == "Degraded"
    assert health.extra_state_attributes["healthy_device_serials"] == [
        "INV1",
        "INV2",
    ]
    assert health.extra_state_attributes["not_evaluated_device_serials"] == [
        "METER1"
    ]
    assert connectivity.extra_state_attributes["online_device_serials"] == [
        "METER1"
    ]
    assert connectivity.extra_state_attributes["offline_device_serials"] == [
        "INV1",
        "INV2",
    ]

    coordinator.data["devices"]["INV1"]["onlineStatus"] = 1
    coordinator.data["devices"]["INV2"]["onlineStatus"] = 1
    assert connectivity.native_value == "Online"

    coordinator.data["device_realtime"]["INV2"]["deviceStatus"] = 103
    assert health.native_value == "Degraded"
    coordinator.data["device_realtime"]["INV2"]["deviceStatus"] = 104
    assert health.native_value == "Error"


@pytest.mark.parametrize(
    ("device_type", "device_status"),
    [(2, 5), (2, 10), (4, 4)],
)
def test_system_health_uses_documented_battery_and_ev_faults(
    device_type, device_status
):
    coordinator = _Coordinator()
    coordinator.data = {
        "plants": {"P1": {"plantId": "P1", "businessType": 1}},
        "alarms": {"P1": {"total": 0, "records": []}},
        "devices": {
            "DEVICE1": {
                "deviceSn": "DEVICE1",
                "deviceType": device_type,
                "businessType": 1,
                "onlineStatus": 1,
            }
        },
        "device_realtime": {
            "DEVICE1": {
                "deviceSn": "DEVICE1",
                "deviceType": device_type,
                "businessType": 1,
                "deviceStatus": device_status,
            }
        },
        "last_errors": [],
        "meta": {"effective_scan_interval": 120},
    }
    entity = sensor.SolaxSystemSensor(
        coordinator, "system_health", "SDS", "sds"
    )
    assert entity.native_value == "Degraded"
    assert entity.extra_state_attributes["faulted_device_serials"] == ["DEVICE1"]


def test_device_connectivity_fallback_handles_stale_and_failed_manual_devices():
    coordinator = _Coordinator()
    old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    coordinator.data = {
        "plants": {},
        "alarms": {},
        "devices": {
            "METER1": {
                "deviceSn": "METER1",
                "deviceType": 3,
                "businessType": 1,
                "onlineStatus": None,
            }
        },
        "device_realtime": {
            "METER1": {
                "deviceSn": "METER1",
                "deviceType": 3,
                "businessType": 1,
                "dataTime": old_time,
                "totalActivePower": 100,
            }
        },
        "last_errors": [],
        "meta": {"effective_scan_interval": 120},
    }
    entity = sensor.SolaxSystemSensor(
        coordinator, "device_connectivity", "SDS", "sds"
    )

    assert entity.native_value == "Unknown"
    attrs = entity.extra_state_attributes
    assert attrs["stale_device_serials"] == ["METER1"]
    assert attrs["freshness_threshold_seconds"] == 900
    assert (
        attrs["per_device_connectivity"]["METER1"]["reason"]
        == "realtime_data_stale"
    )

    coordinator.data["device_realtime"]["METER1"].pop("dataTime")
    coordinator.data["last_errors"] = [
        {"context": "device_realtime:1:3:chunk:1", "classification": "timeout"}
    ]
    assert entity.native_value == "Unknown"
    assert (
        entity.extra_state_attributes["per_device_connectivity"]["METER1"][
            "reason"
        ]
        == "latest_realtime_refresh_failed"
    )


def test_plant_sensor_classes():
    coordinator = _Coordinator()
    plant = sensor.SolaxPlantFieldSensor(
        coordinator, "sds", "P1", "nested_voltage"
    )
    assert plant.available is True
    assert plant.native_value == 230
    assert plant.device_info["name"] == "Main Plant"

    missing = sensor.SolaxPlantFieldSensor(
        coordinator, "sds", "missing", "power"
    )
    assert missing.available is False
    assert missing.native_value is None

    alarm_count = sensor.SolaxPlantAlarmCountSensor(
        coordinator, "sds", "P1"
    )
    assert alarm_count.native_value == 2
    assert alarm_count.device_info["model"] == "Plant"

    stat = sensor.SolaxPlantStatSensor(
        coordinator, "sds", "P1", "year", "pvGeneration"
    )
    earnings = sensor.SolaxPlantStatSensor(
        coordinator, "sds", "P1", "month", "earnings"
    )
    assert stat.native_value == 10
    assert stat.device_info["model"] == "Plant Stats"
    assert earnings.native_value == 4.2
    assert earnings.state_class == SensorStateClass.MEASUREMENT

    info = sensor.SolaxPlantInfoSensor(
        coordinator, "sds", "P1", "plantState"
    )
    optional_info = sensor.SolaxPlantInfoSensor(
        coordinator, "sds", "P1", "otherInfo"
    )
    assert info.native_value == "Online"
    assert optional_info.native_value == "extra"
    assert optional_info._attr_entity_registry_enabled_default is False
    assert info.device_info["model"] == "Plant"

    alarm = sensor.SolaxPlantAlarmPreviewSensor(
        coordinator, "sds", "P1", 0, "alarmName"
    )
    invalid_alarm = sensor.SolaxPlantAlarmPreviewSensor(
        coordinator, "sds", "P1", 1, "alarmName"
    )
    missing_alarm = sensor.SolaxPlantAlarmPreviewSensor(
        coordinator, "sds", "P1", 99, "alarmName"
    )
    assert alarm.native_value == "Grid"
    assert invalid_alarm.native_value is None
    assert missing_alarm.native_value is None
    assert alarm.device_info["model"] == "Plant Alarms"


def test_device_sensor_classes_and_status_mapping():
    coordinator = _Coordinator()
    power = sensor.SolaxDeviceFieldSensor(
        coordinator, "sds", "INV2", 1, "acPower1"
    )
    assert power.available is True
    assert power.native_value == 1000
    assert power.extra_state_attributes["normalized_value"] == 1000
    assert power.device_info["serial_number"] == "INV2"

    status = sensor.SolaxDeviceFieldSensor(
        coordinator, "sds", "INV1", 1, "deviceStatus"
    )
    assert status.native_value
    assert status.extra_state_attributes["raw_value"] == 1

    realtime_business_type = sensor.SolaxDeviceFieldSensor(
        coordinator, "sds", "INV1", 1, "businessType"
    )
    assert realtime_business_type.native_value == "Type 1, Residential"
    assert realtime_business_type.extra_state_attributes == {
        "raw_value": 1,
        "mapped_value": "Type 1, Residential",
    }

    realtime_device_type = sensor.SolaxDeviceFieldSensor(
        coordinator, "sds", "METER1", 3, "deviceType"
    )
    assert realtime_device_type.native_value == "Type 3, Meter"
    assert realtime_device_type.extra_state_attributes == {
        "raw_value": 3,
        "mapped_value": "Type 3, Meter",
    }

    coordinator.data["device_realtime"]["INV1"]["businessType"] = "malformed"
    malformed_realtime_type = sensor.SolaxDeviceFieldSensor(
        coordinator, "sds", "INV1", 1, "businessType"
    )
    assert malformed_realtime_type.native_value == "Type malformed, Unknown"
    assert malformed_realtime_type.extra_state_attributes["raw_value"] == "malformed"
    coordinator.data["device_realtime"]["INV1"]["businessType"] = 1

    unchanged = sensor.SolaxDeviceFieldSensor(
        coordinator, "sds", "METER1", 3, "importEnergy"
    )
    assert unchanged.extra_state_attributes == {}

    missing = sensor.SolaxDeviceFieldSensor(
        coordinator, "sds", "MISSING", "bad", "power"
    )
    assert missing.available is False
    assert missing.native_value is None
    assert missing.extra_state_attributes == {}
    assert missing.device_info["model"] == "Unknown"

    coordinator.data["device_realtime"]["BROKEN"] = "invalid"
    broken = sensor.SolaxDeviceFieldSensor(
        coordinator, "sds", "BROKEN", 1, "power"
    )
    assert broken.available is False
    assert broken.native_value is None

    for key, expected in (
        ("deviceModel", "X3-Hybrid-G4"),
        ("onlineStatus", "Online"),
        ("flag", "0"),
        ("armVersion", "1.0"),
    ):
        info = sensor.SolaxDeviceInfoSensor(
            coordinator, "sds", "INV1", 1, key
        )
        assert info.native_value == expected
        assert info.device_info["serial_number"] == "INV1"

    ems = sensor.SolaxDeviceInfoSensor(
        coordinator, "sds", "EMS1", 100, "onlineStatus"
    )
    assert ems.device_info["model"] == "EMS System"

    coordinator.data["devices"].update(
        {
            "BATTERY1": {
                "deviceSn": "BATTERY1",
                "deviceType": 2,
                "businessType": 1,
            },
            "EV1": {
                "deviceSn": "EV1",
                "deviceType": 4,
                "businessType": 1,
            },
        }
    )

    for device_sn, device_type, expected in (
        ("INV1", 1, "Type 1, Inverter"),
        ("BATTERY1", 2, "Type 2, Battery"),
        ("METER1", 3, "Type 3, Meter"),
        ("EV1", 4, "Type 4, EV Charger"),
        ("EMS1", 100, "Type 100, EMS"),
    ):
        info = sensor.SolaxDeviceInfoSensor(
            coordinator, "sds", device_sn, device_type, "deviceType"
        )
        assert info.native_value == expected
        assert info.extra_state_attributes == {
            "raw_value": device_type,
            "mapped_value": expected,
        }

    residential = sensor.SolaxDeviceInfoSensor(
        coordinator, "sds", "METER1", 3, "businessType"
    )
    assert residential.native_value == "Type 1, Residential"
    assert residential.extra_state_attributes == {
        "raw_value": 1,
        "mapped_value": "Type 1, Residential",
    }

    commercial = sensor.SolaxDeviceInfoSensor(
        coordinator, "sds", "INV2", 1, "businessType"
    )
    assert commercial.native_value == "Type 4, Commercial & Industrial"
    assert commercial.extra_state_attributes == {
        "raw_value": 4,
        "mapped_value": "Type 4, Commercial & Industrial",
    }

    coordinator.data["devices"]["UNKNOWN_TYPES"] = {
        "deviceSn": "UNKNOWN_TYPES",
        "deviceType": 999,
        "businessType": "malformed",
    }
    unknown_device_type = sensor.SolaxDeviceInfoSensor(
        coordinator, "sds", "UNKNOWN_TYPES", 999, "deviceType"
    )
    malformed_business_type = sensor.SolaxDeviceInfoSensor(
        coordinator, "sds", "UNKNOWN_TYPES", 999, "businessType"
    )
    assert unknown_device_type.native_value == "Type 999, Unknown"
    assert unknown_device_type.extra_state_attributes["raw_value"] == 999
    assert malformed_business_type.native_value == "Type malformed, Unknown"
    assert malformed_business_type.extra_state_attributes["raw_value"] == "malformed"

    inventory = sensor.SolaxDeviceInfoSensor(
        coordinator, "sds", "UNKNOWN", 3, "onlineStatus"
    )
    assert inventory.device_info["model"] == "Inventory"


@pytest.mark.asyncio
async def test_sensor_setup_builds_dynamic_entities_and_listener(monkeypatch):
    coordinator = _Coordinator()
    entry = SimpleNamespace(
        data={},
        options={"system_name": "SDS", "entity_prefix": "sds"},
        runtime_data=SimpleNamespace(coordinator=coordinator),
        unload_callbacks=[],
    )
    entry.async_on_unload = entry.unload_callbacks.append

    class _Registry:
        def async_get_entity_id(self, *args):
            return None

        def async_get(self, entity_id):
            return None

        def async_update_entity(self, *args, **kwargs):
            raise AssertionError("not expected")

    monkeypatch.setattr(sensor.er, "async_get", lambda hass: _Registry())
    added = []

    def _add(entities, update_before_add=False):
        added.extend(entities)

    await sensor.async_setup_entry(_Hass(), entry, _add)

    assert len(added) > 40
    assert coordinator.listener is not None
    assert entry.unload_callbacks
    assert any(
        isinstance(entity, sensor.SolaxDeviceFieldSensor)
        and entity.entity_id.endswith("_device_inv1")
        for entity in added
    )
    assert any(
        isinstance(entity, sensor.SolaxDeviceInfoSensor)
        and entity.entity_id.endswith("_info_device_meter1")
        for entity in added
    )

    before = len(added)
    coordinator.data["device_realtime"]["INV1"]["newVoltage"] = 240
    coordinator.listener()
    assert len(added) == before + 1
