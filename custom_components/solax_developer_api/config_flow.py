"""Config flow for SolaX Cloud."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_PLANT_ID, CONF_ACCESS_TOKEN, CONF_BUSINESS_TYPE
from .api import SolaxCloudAPI

class SolaxCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SolaX Cloud."""
    
    VERSION = 1
    _client_id = None
    _client_secret = None
    _plants = None

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            self._client_id = user_input[CONF_CLIENT_ID]
            self._client_secret = user_input[CONF_CLIENT_SECRET]

            try:
                api = SolaxCloudAPI(self._client_id, self._client_secret, "", "")
                token_data = await self.hass.async_add_executor_job(api.get_token)
                plants_data = await self.hass.async_add_executor_job(
                    api.get_plants, token_data["result"]["access"]
                )
                
                self._plants = plants_data["result"]["records"]
                
                if len(self._plants) == 1:
                    return self.async_create_entry(
                        title=f"Solax Plant {self._plants[0]['plantName']}",
                        data={
                            CONF_CLIENT_ID: self._client_id,
                            CONF_CLIENT_SECRET: self._client_secret,
                            CONF_ACCESS_TOKEN: token_data["result"]["access"],
                            CONF_PLANT_ID: self._plants[0]["plantId"],
                            CONF_BUSINESS_TYPE: self._plants[0].get("businessType", 1)
                        }
                    )
                else:
                    return await self.async_step_plant_selection()
                    
            except Exception as err:
                errors["base"] = "invalid_auth"

        data_schema = vol.Schema({
            vol.Required(CONF_CLIENT_ID): str,
            vol.Required(CONF_CLIENT_SECRET): str,
        })

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_plant_selection(self, user_input=None):
        """Handle plant selection step."""
        errors = {}
        if user_input is not None:
            plant_id = user_input[CONF_PLANT_ID]
            selected_plant = next(p for p in self._plants if p["plantId"] == plant_id)
            
            return self.async_create_entry(
                title=f"Solax Plant {selected_plant['plantName']}",
                data={
                    CONF_CLIENT_ID: self._client_id,
                    CONF_CLIENT_SECRET: self._client_secret,
                    CONF_ACCESS_TOKEN: "",  # Will be filled by API
                    CONF_PLANT_ID: plant_id,
                    CONF_BUSINESS_TYPE: selected_plant.get("businessType", 1)
                }
            )

        plant_options = {p["plantId"]: p["plantName"] for p in self._plants}
        
        data_schema = vol.Schema({
            vol.Required(CONF_PLANT_ID): vol.In(plant_options)
        })

        return self.async_show_form(
            step_id="plant_selection", data_schema=data_schema, errors=errors
        )