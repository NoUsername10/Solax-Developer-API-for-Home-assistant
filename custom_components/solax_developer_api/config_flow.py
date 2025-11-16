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
    # Class variables to store data between steps
    _client_id = None
    _client_secret = None
    _access_token = None
    _plants = None

    async def async_step_user(self, user_input=None):
        """Handle the first step: Ask for Access Token, with Client ID/Secret as a fallback."""
        errors = {}
        
        if user_input is not None:
            token = user_input.get(CONF_ACCESS_TOKEN)
            plant_id = user_input.get(CONF_PLANT_ID)

            # If the user provided a token and plant_id, try to validate them.
            if token and plant_id:
                try:
                    # Use a dummy client_id and client_secret as they are not needed.
                    api = SolaxCloudAPI("", "", token, plant_id)
                    plant_data = await self.hass.async_add_executor_job(api.get_all_data)
                    plant_name = plant_data.get("plant", {}).get("plantName", f"Plant {plant_id}")
                    
                    # If the API call is successful, create the entry and we're done.
                    return self.async_create_entry(
                        title=plant_name,
                        data={
                            CONF_ACCESS_TOKEN: token,
                            CONF_PLANT_ID: plant_id,
                            CONF_CLIENT_ID: "",
                            CONF_CLIENT_SECRET: "",
                            CONF_BUSINESS_TYPE: plant_data.get("plant", {}).get("businessType", 1),
                        }
                    )
                except Exception:
                    # If the token/plant_id are invalid, show an error on the same page.
                    errors["base"] = "invalid_auth"
            else:
                # If the user submitted the form with blank fields, proceed to the Client ID/Secret step.
                return await self.async_step_client_auth()

        # Show the initial form. Fields are optional to allow submitting it blank.
        data_schema = vol.Schema({
            vol.Optional(CONF_ACCESS_TOKEN, description={"suggested_value": user_input.get(CONF_ACCESS_TOKEN) if user_input else ""}): str,
            vol.Optional(CONF_PLANT_ID, description={"suggested_value": user_input.get(CONF_PLANT_ID) if user_input else ""}): str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )

    async def async_step_client_auth(self, user_input=None):
        """Handle authentication using Client ID and Client Secret."""
        errors = {}
        if user_input is not None:
            self._client_id = user_input[CONF_CLIENT_ID]
            self._client_secret = user_input[CONF_CLIENT_SECRET]

            try:
                api = SolaxCloudAPI(self._client_id, self._client_secret, "", "")
                token_data = await self.hass.async_add_executor_job(api.get_token)
                self._access_token = token_data["result"]["access"]
                
                plants_data = await self.hass.async_add_executor_job(api.get_plants, self._access_token)
                self._plants = plants_data["result"]["records"]
                
                if len(self._plants) == 1:
                    plant = self._plants[0]
                    return self.async_create_entry(
                        title=plant['plantName'],
                        data={
                            CONF_CLIENT_ID: self._client_id,
                            CONF_CLIENT_SECRET: self._client_secret,
                            CONF_ACCESS_TOKEN: self._access_token,
                            CONF_PLANT_ID: plant["plantId"],
                            CONF_BUSINESS_TYPE: plant.get("businessType", 1)
                        }
                    )
                else:
                    return await self.async_step_plant_selection()
                    
            except Exception:
                errors["base"] = "invalid_auth"

        data_schema = vol.Schema({
            vol.Required(CONF_CLIENT_ID): str,
            vol.Required(CONF_CLIENT_SECRET): str,
        })

        return self.async_show_form(
            step_id="client_auth", data_schema=data_schema, errors=errors
        )

    async def async_step_plant_selection(self, user_input=None):
        """Handle plant selection for accounts with multiple plants."""
        if user_input is not None:
            plant_id = user_input[CONF_PLANT_ID]
            selected_plant = next(p for p in self._plants if p["plantId"] == plant_id)
            
            return self.async_create_entry(
                title=f"Solax Plant {selected_plant['plantName']}",
                data={
                    CONF_CLIENT_ID: self._client_id,
                    CONF_CLIENT_SECRET: self._client_secret,
                    CONF_ACCESS_TOKEN: self._access_token,
                    CONF_PLANT_ID: plant_id,
                    CONF_BUSINESS_TYPE: selected_plant.get("businessType", 1)
                }
            )

        plant_options = {p["plantId"]: p["plantName"] for p in self._plants}
        data_schema = vol.Schema({vol.Required(CONF_PLANT_ID): vol.In(plant_options)})

        return self.async_show_form(step_id="plant_selection", data_schema=data_schema)
