from custom_components.solax_developer_api.sensor import (
    SolaxDeviceFieldSensor,
    _device_field_display_name,
    _device_info_display_name,
    _device_model_text,
    _device_sensor_unique_suffix,
    _energy_state_class,
    _humanize_key,
    _status_text,
)
from homeassistant.components.sensor import SensorStateClass


class _DummyConfig:
    language = "en"


class _DummyHass:
    config = _DummyConfig()


class _DummyCoordinator:
    hass = _DummyHass()
    data = {"devices": {"SERIAL-NUMBER": {"businessType": 1}}}


def test_humanize_key_mppt_and_pv_without_duplicate_prefix():
    assert _humanize_key("mpptMap_mppt1Power") == "MPPT 1 Power"
    assert _humanize_key("mpptMap_mppt2Current") == "MPPT 2 Current"
    assert _humanize_key("pvMap_pv1Voltage") == "PV 1 Voltage"


def test_device_sensor_unique_suffix_always_ends_with_serial():
    assert (
        _device_sensor_unique_suffix(
            field_slug="mppt_map_mppt1_power",
            device_sn="SERIAL-NUMBER",
            info=False,
        )
        == "mppt_map_mppt1_power_device_serial_number"
    )
    assert (
        _device_sensor_unique_suffix(
            field_slug="online_status",
            device_sn="SERIAL-NUMBER",
            info=True,
        )
        == "online_status_info_device_serial_number"
    )


def test_inverter_device_names_drop_inverter_prefix():
    hass = _DummyHass()
    assert (
        _device_field_display_name(
            hass,
            device_type=1,
            field_name="MPPT 1 Power",
        )
        == "MPPT 1 Power"
    )
    assert (
        _device_info_display_name(
            hass,
            device_type=1,
            key_name="Online Status",
        )
        == "Online Status"
    )


def test_non_inverter_device_names_keep_device_type_prefix():
    hass = _DummyHass()
    assert (
        _device_field_display_name(
            hass,
            device_type=3,
            field_name="Import Energy",
        )
        == "Meter Import Energy"
    )
    assert (
        _device_info_display_name(
            hass,
            device_type=2,
            key_name="Online Status",
        )
        == "Battery Online Status"
    )


def test_ems_names_remove_redundant_sys_prefix():
    hass = _DummyHass()
    assert (
        _device_field_display_name(
            hass,
            device_type=100,
            field_name="Sys PV Power",
        )
        == "EMS System PV Power"
    )
    assert (
        _device_info_display_name(
            hass,
            device_type=100,
            key_name="Sys AC Rated Power",
        )
        == "EMS System AC Rated Power"
    )


def test_device_field_sensor_can_be_disabled_by_default():
    sensor = SolaxDeviceFieldSensor(
        _DummyCoordinator(),
        "system",
        "SERIAL-NUMBER",
        3,
        "importEnergy",
        enabled_by_default=False,
    )
    assert sensor._attr_entity_registry_enabled_default is False


def test_daily_energy_fields_use_total_state_class():
    assert _energy_state_class("dailyYield") == SensorStateClass.TOTAL
    assert _energy_state_class("todayImportEnergy") == SensorStateClass.TOTAL
    assert _energy_state_class("sysBatteryCapacity") == SensorStateClass.TOTAL
    assert _energy_state_class("sysBatteryRemainings") == SensorStateClass.TOTAL


def test_device_model_uses_business_and_device_context():
    hass = _DummyHass()
    assert (
        _device_model_text(
            hass,
            50,
            business_type=1,
            device_type=1,
        )
        == "X-MS 2700"
    )
    assert (
        _device_model_text(
            hass,
            50,
            business_type=1,
            device_type=3,
        )
        == "Meter X"
    )


def test_battery_status_uses_business_context():
    hass = _DummyHass()
    assert _status_text(hass, 2, 1, "deviceStatus", 1) == "Work"
    assert _status_text(hass, 2, 4, "deviceStatus", 1) == "Standby"
