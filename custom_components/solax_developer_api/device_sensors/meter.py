"""Meter sensor definitions for SolaX Cloud."""
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    UnitOfPower,
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfFrequency,
)

from ..models.sensor_models import SensorConfig, online_status_converter

METER_SENSORS = {
    "onlineStatus": SensorConfig(
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        enabled_by_default=True,
        value_converter=online_status_converter
    ),
    "totalActivePower": SensorConfig(
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=1,
        enabled_by_default=True
    ),
    "importEnergy": SensorConfig(
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        enabled_by_default=True
    ),
    "exportEnergy": SensorConfig(
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        enabled_by_default=True
    ),
    "gridFrequency": SensorConfig(
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        suggested_display_precision=2,
        enabled_by_default=False,
        entity_category="diagnostic"
    ),
    "powerFactor": SensorConfig(
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        enabled_by_default=False,
        entity_category="diagnostic"
    )
}