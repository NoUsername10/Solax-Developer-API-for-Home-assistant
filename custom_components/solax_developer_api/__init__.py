"""The SolaX Cloud integration."""
import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, SCAN_INTERVAL
from .api import SolaxCloudAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SolaX Cloud from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    api = SolaxCloudAPI(
        entry.data["client_id"],
        entry.data["client_secret"],
        entry.data["access_token"],
        entry.data["plant_id"],
        entry.data.get("business_type", 1)
    )
    
    coordinator = SolaxCloudCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()
    
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

class SolaxCloudCoordinator(DataUpdateCoordinator):
    """Class to manage fetching SolaX Cloud data."""
    
    def __init__(self, hass, api):
        """Initialize."""
        self.api = api
        self.plant_id = api.plant_id
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
    
    async def _async_update_data(self):
        """Update data via library."""
        try:
            return await self.hass.async_add_executor_job(self.api.get_all_data)
        except Exception as err:
            _LOGGER.error("Error updating SolaX Cloud data: %s", err)
            raise