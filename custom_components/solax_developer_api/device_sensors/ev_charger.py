"""EV Charger sensor definitions for SolaX Cloud."""
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    UnitOfPower,
    UnitOfElectricCurrent,
    UnitOfEnergy,
)

from ..models.sensor_models import SensorConfig, online_status_converter

EV_CHARGER_SENSORS = {
    "onlineStatus": SensorConfig(
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        enabled_by_default=True,
        value_converter=online_status_converter
    ),
    "deviceStatus": SensorConfig(
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
        enabled_by_default=True
    ),
    "chargingPower": SensorConfig(
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=1,
        enabled_by_default=True
    ),
    "chargingEnergyThisSession": SensorConfig(
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        enabled_by_default=True
    ),
    "totalChargeEnergy": SensorConfig(
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        enabled_by_default=False
    ),
    "singlePhaseCurrent": SensorConfig(
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=1,
        enabled_by_default=False,
        entity_category="diagnostic"
    )
}