"""API client for SolaX Cloud."""
import requests
import logging
from typing import Dict, Any

from .const import BASE_URL_EU, TOKEN_URL_PATH, PLANT_LIST_URL_PATH, REALTIME_DATA_URL_PATH, DEVICE_LIST_URL_PATH, DEVICE_TYPES

_LOGGER = logging.getLogger(__name__)

class SolaxCloudAPI:
    """Solax Cloud API client."""
    
    def __init__(self, client_id: str, client_secret: str, access_token: str, plant_id: str, business_type: int = 1):
        """Initialize the API client."""
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.plant_id = plant_id
        self.business_type = business_type
        self.base_url = BASE_URL_EU

    def get_token(self) -> Dict[str, Any]:
        """Get access token. This is a POST request."""
        return self._api_call("POST", TOKEN_URL_PATH, {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "CICS"
        })

    def get_plants(self, token: str) -> Dict[str, Any]:
        """Get plant list. This is a GET request but requires a JSON body."""
        self.access_token = token
        return self._api_call("GET", PLANT_LIST_URL_PATH, {
            "pageNo": 1,
            "businessType": self.business_type
        })

    def get_all_data(self) -> Dict[str, Any]:
        """Get all plant and device data."""
        data = {}
        
        try:
            # 1. Get Plant real-time data. This is a GET request.
            plant_data = self._api_call("GET", REALTIME_DATA_URL_PATH, {
                "plantId": self.plant_id,
                "businessType": self.business_type
            })
            data["plant"] = plant_data.get("result", {})
            
            # 2. Get all devices by looping through device types. This is a GET request.
            all_devices = []
            for device_type_code, _ in DEVICE_TYPES.items():
                device_list_data = self._api_call("GET", DEVICE_LIST_URL_PATH, {
                    "plantId": self.plant_id,
                    "businessType": self.business_type,
                    "deviceType": device_type_code,
                    "pageNo": 1
                })
                devices_on_page = device_list_data.get("result", {}).get("records", [])
                if devices_on_page:
                    all_devices.extend(devices_on_page)

            # 3. Filter devices into categories
            data["inverters"] = [d for d in all_devices if d.get("deviceType") == 1]
            data["batteries"] = [d for d in all_devices if d.get("deviceType") == 2]
            data["meters"] = [d for d in all_devices if d.get("deviceType") == 3]
            data["ev_chargers"] = [d for d in all_devices if d.get("deviceType") == 4]
            
        except Exception as err:
            _LOGGER.error("Error fetching data: %s", err)
            raise
        
        return data

    def _api_call(self, method: str, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make API call with error handling, sending a JSON body for both GET and POST."""
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        
        # Add Authorization header for all endpoints except token generation
        if endpoint != TOKEN_URL_PATH:
            headers["Authorization"] = f"Bearer {self.access_token}"
        
        try:
            # Use requests.request to flexibly handle methods.
            # CRITICAL: Pass the payload to the 'json' parameter for BOTH GET and POST requests
            # to accommodate the SolaX API's non-standard requirement for a body on GET requests.
            response = requests.request(method.upper(), url, json=params, headers=headers, timeout=30)
            
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") != 10000:
                raise Exception(f"API Error {data.get('code')}: {data.get('message')}")
            
            return data
            
        except requests.exceptions.RequestException as err:
            _LOGGER.error("Request error: %s", err)
            raise Exception(f"Cannot connect to SolaX Cloud: {err}")
