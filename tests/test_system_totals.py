from datetime import timedelta

from custom_components.solax_developer_api.sensor import SolaxSystemSensor


class _Config:
    language = "en"


class _Hass:
    config = _Config()


class _Client:
    token_expires_at = None


class _Coordinator:
    def __init__(self, data):
        self.hass = _Hass()
        self.data = data
        self.rate_limited = False
        self.rate_limited_context = []
        self.last_rate_limit_at = None
        self.last_successful_update = None
        self.last_update_attempt = None
        self.update_interval = timedelta(seconds=120)
        self.client = _Client()


def test_system_ac_power_uses_inverters_only_and_reports_breakdown():
    coordinator = _Coordinator(
        {
            "plants": {"P1": {}},
            "devices": {
                "INV001": {"deviceType": 1},
                "MTR001": {"deviceType": 3},
            },
            "device_realtime": {
                "INV001": {
                    "deviceType": 1,
                    "businessType": 1,
                    "totalActivePower": 3200,
                },
                "MTR001": {
                    "deviceType": 3,
                    "businessType": 1,
                    "totalActivePower": -1400,
                },
            },
        }
    )

    sensor = SolaxSystemSensor(coordinator, "system_ac_power", "System", "system")
    attrs = sensor.extra_state_attributes

    assert sensor.native_value == 3200.0
    assert attrs["included_device_serials"] == ["INV001"]
    assert attrs["excluded_non_inverter_serials"] == ["MTR001"]
    assert attrs["excluded_non_inverter_devices"]["MTR001"]["device_type"] == 3
    assert attrs["per_device_power_w"]["INV001"] == 3200.0


def test_system_efficiency_returns_zero_when_ac_and_dc_are_zero():
    coordinator = _Coordinator(
        {
            "plants": {},
            "devices": {"INV001": {"deviceType": 1}},
            "device_realtime": {
                "INV001": {
                    "deviceType": 1,
                    "businessType": 1,
                    "totalActivePower": 0,
                    "MPPTTotalInputPower": 0,
                }
            },
        }
    )

    sensor = SolaxSystemSensor(coordinator, "system_efficiency", "System", "system")

    assert sensor.native_value == 0.0


def test_system_yield_breakdown_tracks_included_and_missing_plants():
    coordinator = _Coordinator(
        {
            "plants": {
                "PLANT_A": {"plantName": "A"},
                "PLANT_B": {"plantName": "B"},
                "PLANT_C": {"plantName": "C"},
            },
            "devices": {},
            "device_realtime": {},
            "plant_realtime": {
                "PLANT_A": {"dailyYield": 2.5, "totalYield": 100.3},
                "PLANT_B": {"dailyYield": "invalid", "totalYield": None},
            },
        }
    )

    today = SolaxSystemSensor(coordinator, "system_yield_today", "System", "system")
    lifetime = SolaxSystemSensor(coordinator, "system_yield_total", "System", "system")

    assert today.native_value == 2.5
    assert lifetime.native_value == 100.3

    today_attrs = today.extra_state_attributes
    assert today_attrs["included_plant_ids"] == ["PLANT_A"]
    assert today_attrs["missing_plant_ids"] == ["PLANT_B", "PLANT_C"]
    assert today_attrs["per_plant_kwh"] == {"PLANT_A": 2.5}
