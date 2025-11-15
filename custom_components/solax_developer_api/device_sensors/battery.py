"""Battery sensor definitions for SolaX Cloud."""
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    UnitOfPower,
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    UnitOfTemperature,
    PERCENTAGE,
)

from ..models.sensor_models import SensorConfig, online_status_converter

BATTERY_SENSORS = {
    "onlineStatus": SensorConfig(
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        enabled_by_default=True,
        value_converter=online_status_converter
    ),
    "batterySOC": SensorConfig(
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        enabled_by_default=True
    ),
    "batterySOH": SensorConfig(
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        enabled_by_default=False
    ),
    "chargeDischargePower": SensorConfig(
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=1,
        enabled_by_default=True
    ),
    "batteryVoltage": SensorConfig(
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
        enabled_by_default=False,
        entity_category="diagnostic"
    ),
    "batteryCurrent": SensorConfig(
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=1,
        enabled_by_default=False,
        entity_category="diagnostic"
    ),
    "batteryTemperature": SensorConfig(
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        enabled_by_default=False,
        entity_category="diagnostic"
    ),
    "batteryCycleTimes": SensorConfig(
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        enabled_by_default=False,
        entity_category="diagnostic"
    ),
    "totalDeviceCharge": SensorConfig(
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        enabled_by_default=False
    ),
    "totalDeviceDischarge": SensorConfig(
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        enabled_by_default=False
    )
}