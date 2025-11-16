"""Battery-level sensor definitions for SolaX Cloud."""
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import UnitOfPower, UnitOfEnergy, UnitOfElectricCurrent, UnitOfElectricPotential, UnitOfFrequency, PERCENTAGE, UnitOfTemperature

from ..models.sensor_models import SensorConfig

BATTERY_SENSORS = {
    "batterySOC": SensorConfig(
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        enabled_by_default=True
    ),
    "batterySOH": SensorConfig(
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled_by_default=True
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
        enabled_by_default=False
    ),
    "batteryCurrent": SensorConfig(
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=1,
        enabled_by_default=False
    ),
    "batteryTemperature": SensorConfig(
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled_by_default=True
    ),
    "batteryCycleTimes": SensorConfig(
        device_class=None,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        enabled_by_default=False
    ),
    "totalDeviceCharge": SensorConfig(
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        enabled_by_default=True
    ),
    "totalDeviceDischarge": SensorConfig(
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        enabled_by_default=True
    )
}
