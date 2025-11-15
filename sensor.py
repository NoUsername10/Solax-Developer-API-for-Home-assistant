"""Sensor platform for SolaX Cloud."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .models.sensor_models import SensorConfig, DeviceType
from .models.device_models import get_device_model_name

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
        
        if device_sn:
            self._attr_unique_id = f"solax_{device_type}_{device_sn}_{sensor_key}"
            self._attr_translation_key = sensor_key
            self._attr_has_entity_name = True
            self._device_display_name = self._get_device_display_name()
        else:
            self._attr_unique_id = f"solax_{device_type}_{sensor_key}"
            self._attr_translation_key = sensor_key
            self._attr_has_entity_name = True
        
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
        if self._device_sn:
            return f"{self._device_display_name} {self.translation_key}"
        else:
            return self.translation_key

    def _get_device_display_name(self):
        """Get the display name for the device."""
        model_name = get_device_model_name(
            self._get_device_type_code(), 
            self._device_model_code, 
            self._business_type
        )
        
        type_names = {
            DeviceType.INVERTER: "Inverter",
            DeviceType.BATTERY: "Battery",
            DeviceType.METER: "Meter",
            DeviceType.EV_CHARGER: "EV Charger"
        }
        device_type_name = type_names.get(self._device_type, "Device")
        return f"{model_name} {self._device_sn}"
    
    def _get_device_type_code(self):
        """Convert device type string to numeric code."""
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
        raw_value = self.get_sensor_value()
        if raw_value is None:
            return None
        if self._config.value_converter:
            return self._config.value_converter(raw_value)
        return raw_value

    def get_sensor_value(self):
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
        
    def get_sensor_value(self):
        """Get value from plant data."""
        return self.coordinator.data.get("plant", {}).get(self._sensor_key)

class SolaxInverterSensor(SolaxCloudSensor):
    """Representation of an inverter-specific sensor."""
    
    def __init__(self, coordinator, device_sn, sensor_key, config, device_model_code=None):
        """Initialize the inverter sensor."""
        super().__init__(coordinator, sensor_key, config, DeviceType.INVERTER, device_sn, device_model_code)
        
    @property
    def device_info(self):
        """Return device information for this inverter."""
        inverter_data = self.get_inverter_data()
        if inverter_data:
            model_name = get_device_model_name(
                1,  # inverter
                inverter_data.get("deviceModel"),
                self._business_type
            )
            return {
                "identifiers": {(DOMAIN, f"inverter_{self._device_sn}")},
                "name": f"{model_name} {self._device_sn}",
                "manufacturer": "SolaX Power",
                "model": model_name,
                "sw_version": inverter_data.get("armVersion"),
                "via_device": (DOMAIN, f"plant_{self.coordinator.plant_id}"),
            }
        return None
        
    def get_sensor_value(self):
        """Get value from specific inverter data."""
        inverter_data = self.get_inverter_data()
        return inverter_data.get(self._sensor_key) if inverter_data else None
        
    def get_inverter_data(self):
        """Get data for this specific inverter."""
        inverters = self.coordinator.data.get("inverters", [])
        for inverter in inverters:
            if inverter.get("deviceSn") == self._device_sn:
                return inverter
        return None

class SolaxBatterySensor(SolaxCloudSensor):
    """Representation of a battery-specific sensor."""
    
    def __init__(self, coordinator, device_sn, sensor_key, config, device_model_code=None):
        """Initialize the battery sensor."""
        super().__init__(coordinator, sensor_key, config, DeviceType.BATTERY, device_sn, device_model_code)
        
    @property
    def device_info(self):
        """Return device information for this battery."""
        battery_data = self.get_battery_data()
        if battery_data:
            model_name = get_device_model_name(
                2,  # battery
                battery_data.get("deviceModel"),
                self._business_type
            )
            return {
                "identifiers": {(DOMAIN, f"battery_{self._device_sn}")},
                "name": f"{model_name} {self._device_sn}",
                "manufacturer": "SolaX Power",
                "model": model_name,
                "sw_version": battery_data.get("softwareVersion"),
                "via_device": (DOMAIN, f"plant_{self.coordinator.plant_id}"),
            }
        return None
        
    def get_sensor_value(self):
        """Get value from specific battery data."""
        battery_data = self.get_battery_data()
        return battery_data.get(self._sensor_key) if battery_data else None
        
    def get_battery_data(self):
        """Get data for this specific battery."""
        batteries = self.coordinator.data.get("batteries", [])
        for battery in batteries:
            if battery.get("deviceSn") == self._device_sn:
                return battery
        return None

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SolaX Cloud sensors based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    await async_update_sensors(coordinator, async_add_entities)
    
    async def async_update_sensors():
        await async_update_sensors(coordinator, async_add_entities)
    
    entry.async_on_unload(coordinator.async_add_listener(async_update_sensors))

async def async_update_sensors(coordinator, async_add_entities):
    """Update sensor entities based on latest data."""
    entities = []
    
    from .device_sensors.plant import PLANT_SENSORS
    from .device_sensors.inverter import INVERTER_SENSORS
    from .device_sensors.battery import BATTERY_SENSORS
    
    if "plant" in coordinator.data:
        for sensor_key, config in PLANT_SENSORS.items():
            if coordinator.data["plant"].get(sensor_key) is not None:
                entities.append(SolaxPlantSensor(coordinator, sensor_key, config))
    
    if "inverters" in coordinator.data:
        for inverter_data in coordinator.data["inverters"]:
            device_sn = inverter_data["deviceSn"]
            device_model = inverter_data.get("deviceModel")
            for sensor_key, config in INVERTER_SENSORS.items():
                if inverter_data.get(sensor_key) is not None:
                    entities.append(SolaxInverterSensor(
                        coordinator, device_sn, sensor_key, config, device_model
                    ))
    
    if "batteries" in coordinator.data:
        for battery_data in coordinator.data["batteries"]:
            device_sn = battery_data["deviceSn"]
            device_model = battery_data.get("deviceModel")
            for sensor_key, config in BATTERY_SENSORS.items():
                if battery_data.get(sensor_key) is not None:
                    entities.append(SolaxBatterySensor(
                        coordinator, device_sn, sensor_key, config, device_model
                    ))
    
    async_add_entities(entities)