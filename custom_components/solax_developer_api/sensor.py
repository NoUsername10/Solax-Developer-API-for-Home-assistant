"""Sensor platform for SolaX Cloud."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .models.sensor_models import SensorConfig, DeviceType
from .models.device_models import get_device_model_name

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SolaX Cloud sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    # Import sensor configurations
    from .device_sensors.plant import PLANT_SENSORS
    from .device_sensors.inverter import INVERTER_SENSORS
    from .device_sensors.battery import BATTERY_SENSORS

    # Plant Sensors
    if "plant" in coordinator.data:
        for sensor_key, config in PLANT_SENSORS.items():
            if coordinator.data["plant"].get(sensor_key) is not None:
                entities.append(SolaxPlantSensor(coordinator, sensor_key, config))

    # Inverter Sensors
    if "inverters" in coordinator.data:
        for inverter_data in coordinator.data["inverters"]:
            device_sn = inverter_data.get("deviceSn")
            if not device_sn:
                continue
            for sensor_key, config in INVERTER_SENSORS.items():
                if inverter_data.get(sensor_key) is not None:
                    entities.append(SolaxInverterSensor(coordinator, inverter_data, sensor_key, config))

    # Battery Sensors
    if "batteries" in coordinator.data:
        for battery_data in coordinator.data["batteries"]:
            device_sn = battery_data.get("deviceSn")
            if not device_sn:
                continue
            for sensor_key, config in BATTERY_SENSORS.items():
                if battery_data.get(sensor_key) is not None:
                    entities.append(SolaxBatterySensor(coordinator, battery_data, sensor_key, config))

    async_add_entities(entities)

class SolaxCloudSensor(CoordinatorEntity, SensorEntity):
    """Base class for SolaX Cloud sensors."""
    
    def __init__(self, coordinator, sensor_key, config, device_type, device_sn=None, device_model_code=None, business_type=1):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_key = sensor_key
        self._config = config
        self._device_type = device_type
        self._device_sn = device_sn
        self._device_model_code = device_model_code
        self._business_type = business_type
        
        # Set basic attributes
        self._attr_translation_key = sensor_key
        self._attr_has_entity_name = True
        
        # Build unique ID
        if device_sn:
            self._attr_unique_id = f"solax_{device_type.value}_{device_sn}_{sensor_key}"
            self._device_display_name = self._get_device_display_name()
        else:
            self._attr_unique_id = f"solax_{device_type.value}_{coordinator.plant_id}_{sensor_key}"
        
        # Set sensor attributes from config
        if config.device_class:
            self._attr_device_class = config.device_class
        if config.state_class:
            self._attr_state_class = config.state_class
        if config.native_unit_of_measurement:
            self._attr_native_unit_of_measurement = config.native_unit_of_measurement
        if config.entity_category:
            self._attr_entity_category = config.entity_category
            
        self._attr_entity_registry_enabled_default = config.enabled_by_default

    @property
    def name(self):
        """Return the name of the sensor."""
        if hasattr(self, '_device_display_name'):
            return f"{self._device_display_name} {self.translation_key}"
        return super().name

    def _get_device_display_name(self):
        """Get the display name for the device."""
        model_name = get_device_model_name(
            self._get_device_type_code(), 
            self._device_model_code, 
            self._business_type
        )
        return f"{model_name} {self._device_sn}"
    
    def _get_device_type_code(self):
        """Convert device type enum to numeric code."""
        type_map = {
            DeviceType.INVERTER: 1,
            DeviceType.BATTERY: 2,
            DeviceType.METER: 3,
            DeviceType.EV_CHARGER: 4
        }
        return type_map.get(self._device_type, 0)

    @property
    def native_value(self):
        """Return the state of the sensor."""
        raw_value = self._get_sensor_value()
        if raw_value is None:
            return None
        if self._config.value_converter:
            return self._config.value_converter(raw_value)
        return raw_value

    def _get_sensor_value(self):
        """Get sensor value from coordinator data."""
        raise NotImplementedError

class SolaxPlantSensor(SolaxCloudSensor):
    """Representation of a plant-level sensor."""
    
    def __init__(self, coordinator, sensor_key, config):
        """Initialize the plant sensor."""
        super().__init__(coordinator, sensor_key, config, DeviceType.PLANT)
        
    @property
    def device_info(self):
        """Return device information for the plant."""
        plant_data = self.coordinator.data.get("plant", {})
        return {
            "identifiers": {(DOMAIN, f"plant_{self.coordinator.plant_id}")},
            "name": plant_data.get("plantName", "Solar Plant"),
            "manufacturer": "SolaX Power",
            "model": "Solar Plant"
        }
        
    def _get_sensor_value(self):
        """Get value from plant data."""
        return self.coordinator.data.get("plant", {}).get(self._sensor_key)

class SolaxInverterSensor(SolaxCloudSensor):
    """Representation of an inverter-specific sensor."""
    
    def __init__(self, coordinator, inverter_data, sensor_key, config):
        """Initialize the inverter sensor."""
        self._inverter_data = inverter_data
        super().__init__(
            coordinator,
            sensor_key,
            config,
            DeviceType.INVERTER,
            device_sn=self._inverter_data["deviceSn"],
            device_model_code=self._inverter_data.get("deviceModel")
        )
        
    @property
    def device_info(self):
        """Return device information for this inverter."""
        model_name = get_device_model_name(1, self._inverter_data.get("deviceModel"), self._business_type)
        return {
            "identifiers": {(DOMAIN, f"inverter_{self._device_sn}")},
            "name": f"{model_name} {self._device_sn}",
            "manufacturer": "SolaX Power",
            "model": model_name,
            "sw_version": self._inverter_data.get("armVersion"),
            "via_device": (DOMAIN, f"plant_{self.coordinator.plant_id}"),
        }
        
    def _get_sensor_value(self):
        """Get value from specific inverter data."""
        return self._inverter_data.get(self._sensor_key)

class SolaxBatterySensor(SolaxCloudSensor):
    """Representation of a battery-specific sensor."""
    
    def __init__(self, coordinator, battery_data, sensor_key, config):
        """Initialize the battery sensor."""
        self._battery_data = battery_data
        super().__init__(
            coordinator,
            sensor_key,
            config,
            DeviceType.BATTERY,
            device_sn=self._battery_data["deviceSn"],
            device_model_code=self._battery_data.get("deviceModel")
        )
        
    @property
    def device_info(self):
        """Return device information for this battery."""
        model_name = get_device_model_name(2, self._battery_data.get("deviceModel"), self._business_type)
        return {
            "identifiers": {(DOMAIN, f"battery_{self._device_sn}")},
            "name": f"{model_name} {self._device_sn}",
            "manufacturer": "SolaX Power",
            "model": model_name,
            "sw_version": self._battery_data.get("softwareVersion"),
            "via_device": (DOMAIN, f"plant_{self.coordinator.plant_id}"),
        }
        
    def _get_sensor_value(self):
        """Get value from specific battery data."""
        return self._battery_data.get(self._sensor_key)
