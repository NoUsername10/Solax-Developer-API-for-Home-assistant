"""Sensor configurations and value converters for SolaX Cloud."""
from dataclasses import dataclass
from typing import Callable
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    UnitOfEnergy,
    UnitOfPower,
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    UnitOfTemperature,
    UnitOfFrequency,
    PERCENTAGE,
)

@dataclass
class SensorConfig:
    """Configuration for a sensor."""
    device_class: str | None = None
    state_class: str | None = None
    native_unit_of_measurement: str | None = None
    suggested_display_precision: int | None = None
    enabled_by_default: bool = True
    entity_category: str | None = None
    value_converter: Callable | None = None

class DeviceType:
    """Device type constants."""
    PLANT = "plant"
    INVERTER = "inverter"
    BATTERY = "battery"
    METER = "meter"
    EV_CHARGER = "ev_charger"

def inverter_status_converter(status_code):
    """Convert inverter status code to human-readable text."""
    status_map = {
        100: "Waiting",
        101: "Self-check", 
        102: "Normal",
        103: "Fault",
        104: "Permanent Fault",
        105: "Updating",
        106: "EPS Check",
        107: "EPS Mode",
        108: "Self Test",
        109: "Idle",
        110: "Standby",
        111: "PV Wake Up Battery",
        112: "Generator Check",
        113: "Generator Running",
        114: "RSD Standby",
        130: "VPP Mode",
        131: "TOU Self Use",
        132: "TOU Charging", 
        133: "TOU Discharging",
        134: "TOU Battery Off",
        135: "TOU Peak Shaving",
        136: "Generator Normal",
        137: "Battery Expansion",
        138: "Grid Battery Heat",
        139: "EPS Battery Heat",
        140: "Starting"
    }
    return status_map.get(status_code, f"Unknown ({status_code})")

def online_status_converter(online_code):
    """Convert online status code to human-readable text."""
    return "Online" if online_code == 1 else "Offline"

def plant_status_converter(plant_state, business_type):
    """Convert plant state considering business type."""
    if business_type == 1:  # Residential
        if plant_state == 0:
            return "Connecting"
        elif plant_state == 1:
            return "Offline"
        else:
            return "Online"
    else:  # Commercial
        status_map = {
            0: "Offline",
            1: "Normal", 
            2: "Failure",
            3: "Warning",
            4: "Connecting"
        }
        return status_map.get(plant_state, f"Unknown ({plant_state})")