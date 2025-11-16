"""Constants for the SolaX Cloud integration."""
DOMAIN = "solax_developer_api"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_ACCESS_TOKEN = "access_token"
CONF_PLANT_ID = "plant_id"
CONF_PLANT_INFO = "plant_info"
CONF_BUSINESS_TYPE = "business_type"

BASE_URL_EU = "https://openapi-eu.solaxcloud.com"
BASE_URL_CN = "https://openapi-cn.solaxcloud.com"
TOKEN_URL_PATH = "/openapi/auth/get_token"
PLANT_LIST_URL_PATH = "/openapi/v2/plant/page_plant_info"
REALTIME_DATA_URL_PATH = "/openapi/v2/plant/realtime_data"
DEVICE_LIST_URL_PATH = "/openapi/v2/device/page_device_info"
DEVICE_REALTIME_DATA_URL_PATH = "/openapi/v2/device/realtime_data"

SCAN_INTERVAL = 60

BUSINESS_TYPE_RESIDENTIAL = 1
BUSINESS_TYPE_COMMERCIAL = 4

# Device types mapping
DEVICE_TYPES = {
    1: "Inverter",
    2: "Battery",
    3: "Meter",
    4: "EV Charger"
}
