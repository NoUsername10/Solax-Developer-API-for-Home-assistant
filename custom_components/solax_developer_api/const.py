"""Constants for the SolaX Developer API integration."""

from __future__ import annotations

import logging

DOMAIN = "solax_developer_api"
PLATFORMS = ["sensor", "switch", "button", "select", "number", "text", "time"]
CONFIG_ENTRY_VERSION = 2

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SYSTEM_NAME = "system_name"
CONF_ENTITY_PREFIX = "entity_prefix"
CONF_API_REGION = "api_region"
CONF_RATE_LIMIT_NOTIFICATIONS = "rate_limit_notifications"
CONF_LIVE_VIEW_DEFAULT_DURATION = "live_view_default_duration"
CONF_LIVE_VIEW_INTERVAL = "live_view_interval"
CONF_LIVE_VIEW_CALL_BUDGET_PER_MINUTE = "live_view_call_budget_per_minute"
CONF_NIGHT_SCAN_INTERVAL = "night_scan_interval"
CONF_NIGHT_START_HOUR = "night_start_hour"
CONF_NIGHT_END_HOUR = "night_end_hour"
CONF_MANUAL_METER_SERIALS = "manual_meter_serials"
CONF_MANUAL_EMS_SYSTEMS = "manual_ems_systems"
CONF_EV_CHARGER_CONTROLS_ENABLED = "ev_charger_controls_enabled"

DEFAULT_SYSTEM_NAME = "Solax Developer System"
DEFAULT_SCAN_INTERVAL = 120
MIN_SCAN_INTERVAL = 60
MAX_SCAN_INTERVAL = 3600
DEFAULT_LIVE_VIEW_DEFAULT_DURATION = 300
MIN_LIVE_VIEW_DURATION = 30
MAX_LIVE_VIEW_DURATION = 3600
DEFAULT_LIVE_VIEW_INTERVAL = 5
MIN_LIVE_VIEW_INTERVAL = 2
MAX_LIVE_VIEW_INTERVAL = 60
DEFAULT_LIVE_VIEW_CALL_BUDGET_PER_MINUTE = 20
MIN_LIVE_VIEW_CALL_BUDGET_PER_MINUTE = 5
MAX_LIVE_VIEW_CALL_BUDGET_PER_MINUTE = 100
DEFAULT_NIGHT_SCAN_INTERVAL = 600
MIN_NIGHT_SCAN_INTERVAL = 120
MAX_NIGHT_SCAN_INTERVAL = 7200
DEFAULT_NIGHT_START_HOUR = 23
DEFAULT_NIGHT_END_HOUR = 6

API_RATE_LIMIT_PER_MINUTE = 100


def config_value(entry, key: str, default=None):
    """Return an option value with legacy config-data fallback."""
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)

API_REGION_EU = "eu"
API_REGION_CN = "cn"
API_REGION_DEFAULT = API_REGION_EU

API_BASE_URLS = {
    API_REGION_EU: "https://openapi-eu.solaxcloud.com",
    API_REGION_CN: "https://openapi-cn.solaxcloud.com",
}

BUSINESS_TYPES = (1, 4)
DEVICE_TYPES = (1, 2, 3, 4)
EMS_DEVICE_TYPE = 100
MAX_SN_PER_REQUEST = 10
DEVICE_HISTORY_SAFE_WINDOW_MS = 11 * 60 * 60 * 1000

SERVICE_MANUAL_REFRESH = "manual_refresh"
SERVICE_LIST_HISTORY_DEVICES = "list_history_devices"
SERVICE_FETCH_DEVICE_HISTORY = "fetch_device_history"
SERVICE_LIST_PLANT_STATISTICS_TARGETS = "list_plant_statistics_targets"
SERVICE_FETCH_PLANT_YEAR_STATISTICS = "fetch_plant_year_statistics"
SERVICE_FETCH_PLANT_MONTH_STATISTICS = "fetch_plant_month_statistics"
SERVICE_QUERY_REQUEST_RESULT = "query_request_result"
SERVICE_QUERY_MASTER_CONTROL_DEVICE = "query_master_control_device"
SERVICE_START_LIVE_VIEW = "start_live_view"
SERVICE_STOP_LIVE_VIEW = "stop_live_view"

EVENT_DRY_RUN_CONTROL = f"{DOMAIN}_dry_run_control"
EVENT_EV_CHARGER_CONTROL = f"{DOMAIN}_ev_charger_control"

RUNTIME_RELOAD_STATE = f"{DOMAIN}_reload_state"

SUCCESS_CODE_TOKEN = 0
SUCCESS_CODE_API = 10000
ERROR_AUTH_CODES = {10400, 10401, 10402}
ERROR_QUOTA_CODES = {10405}
ERROR_RATE_LIMIT_CODES = {10406}
ERROR_PERMISSION_CODES = {10403, 10500, 10505, 10506}
ERROR_CALLBACK_CODES = {10404}
ERROR_BUSY_CODES = {11500}
ERROR_OPERATION_CODES = {10001, 10200}
ERROR_PARAM_CODES: set[int] = set()

LOGGER = logging.getLogger(__package__)

# Human readable mappings from Developer API appendices.
BUSINESS_TYPE_NAMES = {
    1: "Residential",
    4: "Commercial & Industrial",
}

DEVICE_TYPE_NAMES = {
    1: "Inverter",
    2: "Battery",
    3: "Meter",
    4: "EV Charger",
    100: "EMS System",
}

DEVICE_WORK_MODE_MAP = {
    0: "STOP",
    1: "FAST",
    2: "ECO",
    3: "GREEN",
}

COMMAND_STATUS_MAP = {
    1: "Device Offline",
    2: "Command issuance failed",
    3: "Command issuance succeeded",
    4: "Device received and started execution",
    5: "Device execution failed",
    6: "Execution timed out",
}

EV_CHARGER_CONTROL_SERVICES = frozenset(
    {
        "set_charge_scene",
        "set_evc_qr_code",
        "set_evc_work_mode",
        "set_evc_start_mode",
        "set_evc_charge_command",
        "set_evc_reserve_charge",
        "set_evc_current_limit",
    }
)

EV_CHARGER_ACCEPTED_COMMAND_STATUSES = frozenset({3, 4})

INVERTER_STATUS_MAP = {
    100: "Waiting",
    101: "Self-check",
    102: "Normal",
    103: "Fault",
    104: "Permanent Fault",
    105: "Update Mode",
    106: "EPS Check Mode",
    107: "EPS Mode",
    108: "Self Test",
    109: "Idle Mode",
    110: "Standby Mode",
    111: "PV Wake Up BAT Mode",
    112: "GEN Check Mode",
    113: "GEN Run Mode",
    114: "RSD Standby",
    130: "VPP Mode",
    131: "TOU Self Use",
    132: "TOU Charging",
    133: "TOU Discharging",
    134: "TOU Battery Off",
    135: "TOU Peak Shaving",
    136: "Normal Mode (GEN)",
    137: "Normal Mode (BAT-E)",
    138: "Normal Mode (BAT-H)",
    139: "EPS Mode (BAT-H)",
    140: "Start Mode",
    141: "Normal Mode (R-1)",
    142: "Normal Mode (R-2)",
    143: "Normal Mode (R-3)",
    144: "Normal Mode (R-4)",
    145: "Normal Mode (R-5)",
    146: "Normal Mode (R-6)",
    147: "Normal Mode (R-7)",
    150: "Self Use",
    151: "Force Time Use",
    152: "Back Up Mode",
    153: "Feed-in Priority",
    154: "Demand Mode",
    155: "ConstPower Mode",
    160: "OpenADR Mode",
    170: "Stop Mode",
    171: "Debug Mode",
    174: "Normal (Smart selfuse)",
    175: "Normal (Smart feedin)",
    176: "Normal (Smart battery not discharge)",
    177: "Normal (WLV 0%)",
    1301: "Power Control Mode",
    1302: "Electric Quantity Target Control Mode",
    1303: "SOC Target Control Mode",
    1304: "Push Power Positive/Negative",
    1305: "Push Power Zero",
    1306: "Self-Consume Charge/Discharge",
    1307: "Self-Consume Charge Only",
    1308: "PV&BAT Duration Mode",
    1309: "PV&BAT Target SOC Mode",
}

BATTERY_STATUS_MAP = {
    0: "Idle",
    1: "Working",
    2: "Pre-Charge",
    3: "Charge-to-discharge pre-charge",
    4: "Discharging",
    5: "Discharging Fault",
    6: "Charge switching current limit",
    7: "Charge Self-Test",
    8: "Charge Pre-Charge",
    9: "Charging",
    10: "Charging Fault",
    11: "Power Off",
}

BATTERY_STATUS_MAP_BY_BUSINESS = {
    1: {
        0: "Idle",
        1: "Work",
    },
    4: {
        0: "Idle",
        1: "Standby",
        2: "Discharge Pre-Charge",
        3: "Charge-to-discharge pre-charge",
        4: "Discharging",
        5: "Discharging Fault",
        6: "Charge switching current limit",
        7: "Charge Self-Test",
        8: "Charge Pre-Charge",
        9: "Charging",
        10: "Charging Fault",
        11: "Power Off Status",
    },
}

EV_STATUS_MAP = {
    0: "Available",
    1: "Preparing",
    2: "Charging",
    3: "Finish",
    4: "Faulted",
    5: "Unavailable",
    6: "Reserved",
    7: "Suspended EV",
    8: "Suspended EVSE",
    9: "Update",
    10: "Card Activation",
    11: "Start Delay",
    12: "Charge Pause",
    13: "Stopping",
}

DEVICE_MODEL_MAP = {
    # Inverter models (common values in docs + existing cloud integration)
    1: "X1-LX / X3-AELIO",
    2: "X-Hybrid / X3-TRENE-100KI",
    3: "X1-Hybrid-G3 / X3-TRENE-100K",
    4: "X1-Boost/Air/Mini / X3-TRENE",
    5: "X3-Hybrid-G1/G2",
    6: "X3-20K/30K / C1/C3-HAC",
    7: "X3-MIC/PRO / DTSU666-CT",
    8: "X1-Smart / UMG103-CBM",
    9: "X1-AC / M3-40-Dual",
    10: "A1-Hybrid / M3-40",
    11: "A1-FIT / PRISMA-310A",
    12: "A1",
    13: "J1-ESS",
    14: "X3-Hybrid-G4",
    15: "X1-Hybrid-G4",
    16: "X3-MIC/PRO-G2 / X3-PRO G2",
    17: "X1-SPT",
    18: "X1-Boost-G4",
    19: "A1-HYB-G2",
    20: "A1-AC-G2",
    21: "A1-SMT-G2",
    22: "X1-Mini-G4",
    23: "X1-IES",
    24: "X3-IES",
    25: "X3-ULT",
    26: "X1-SMART-G2",
    27: "A1-Micro 1 in 1",
    28: "X1-Micro 2 in 1",
    29: "X1-Micro 4 in 1",
    31: "X3-AELIO",
    32: "X3-HYB-G4 PRO",
    33: "X3-NEO-LV",
    34: "X1-VAST",
    35: "X3-IES-P",
    36: "J3-ULT-LV-16.5K",
    37: "J3-ULT-30K",
    38: "J1-ESS-HB-2",
    39: "C3-IES",
    40: "X3-IES-A",
    41: "X1-IES-A",
    42: "X3-AELIO",
    43: "X3-ULT-GLV",
    44: "X1-MINI-G4 PLUS",
    46: "X1-Reno-LV",
    47: "A1-HYB-G3",
    50: "Meter X",
    100: "X3-FTH / X3-FORTH",
    101: "X3-MGA-G2 / X3-MEGA G2",
    102: "X1-Hybrid-LV",
    103: "X1-Lite-LV",
    104: "X3-GRAND-HV / X3-GRAND",
    105: "X3-FORTH-PLUS / X3-FORTH PLUS",
    145: "TSYS-HS51",
    163: "TR-HR140",
    176: "M1-40",
    178: "M3-40",
    179: "M3-40-Dual",
    181: "M3-40-Wide",
}

# Portal v34 defines deviceModel within businessType + deviceType context.
DEVICE_MODEL_MAP_BY_CONTEXT = {
    (1, 1, 1): "X1-LX",
    (1, 1, 2): "X-Hybrid",
    (1, 1, 3): "X1-Hybrid-G3",
    (1, 1, 4): "X1-Boost/Air/Mini",
    (1, 1, 5): "X3-Hybrid-G1/G2",
    (1, 1, 6): "X3-20K/30K",
    (1, 1, 7): "X3-MIC/PRO",
    (1, 1, 8): "X1-Smart",
    (1, 1, 9): "X1-AC",
    (1, 1, 10): "A1-Hybrid",
    (1, 1, 11): "A1-FIT",
    (1, 1, 12): "A1",
    (1, 1, 13): "J1-ESS",
    (1, 1, 14): "X3-Hybrid-G4",
    (1, 1, 15): "X1-Hybrid-G4",
    (1, 1, 16): "X3-MIC/PRO-G2",
    (1, 1, 17): "X1-SPT",
    (1, 1, 18): "X1-Boost-G4",
    (1, 1, 19): "A1-HYB-G2",
    (1, 1, 20): "A1-AC-G2",
    (1, 1, 21): "A1-SMT-G2",
    (1, 1, 22): "X1-Mini-G4",
    (1, 1, 23): "X1-IES",
    (1, 1, 24): "X3-IES",
    (1, 1, 25): "X3-ULT",
    (1, 1, 26): "X1-SMART-G2",
    (1, 1, 27): "A1-Micro 1 in 1",
    (1, 1, 28): "X1-Micro 2 in 1",
    (1, 1, 29): "X1-Micro 4 in 1",
    (1, 1, 31): "X3-AELIO",
    (1, 1, 32): "X3-HYB-G4 PRO",
    (1, 1, 33): "X3-NEO-LV",
    (1, 1, 34): "X1-VAST",
    (1, 1, 35): "X3-IES-P",
    (1, 1, 36): "J3-ULT-LV-16.5K",
    (1, 1, 37): "J3-ULT-30K",
    (1, 1, 38): "J1-ESS-HB-2",
    (1, 1, 39): "C3-IES",
    (1, 1, 40): "X3-IES-A",
    (1, 1, 41): "X1-IES-A",
    (1, 1, 43): "X3-ULT-GLV",
    (1, 1, 44): "X1-MINI-G4 PLUS",
    (1, 1, 46): "X1-Reno-LV",
    (1, 1, 47): "A1-HYB-G3",
    (1, 1, 48): "X1-Micro 4 in 1G2",
    (1, 1, 49): "X1-Micro 2 in 1G2",
    (1, 1, 50): "X-MS 2700",
    (1, 1, 64): "OG",
    (1, 1, 66): "X1-SPT-10K/12K",
    (1, 1, 67): "LVE",
    (1, 1, 69): "AEGIS",
    (1, 1, 70): "X3-AELIO(LA)",
    (1, 1, 100): "X3-FTH",
    (1, 1, 101): "X3-MGA-G2",
    (1, 1, 102): "X1-Hybrid-LV",
    (1, 1, 103): "X1-Lite-LV",
    (1, 1, 104): "X3-GRAND-HV",
    (1, 1, 105): "X3-FORTH-PLUS",
    (1, 1, 108): "X3-MIC-G3",
    (1, 1, 109): "X3-PRO-G3",
    (1, 3, 50): "Meter X",
    (1, 3, 176): "M1-40",
    (1, 3, 178): "M3-40",
    (1, 3, 179): "M3-40-Dual",
    (1, 3, 181): "M3-40-Wide",
    (1, 4, 1): "X1/X3-EVC",
    (1, 4, 2): "X1/X3-EVC G1.1",
    (1, 4, 3): "X1/X3-HAC",
    (1, 4, 4): "J1-EVC",
    (1, 4, 5): "A1-HAC",
    (1, 4, 6): "C1/C3-HAC",
    (4, 1, 1): "X3-AELIO",
    (4, 1, 2): "X3-TRENE-100KI",
    (4, 1, 3): "X3-TRENE-100K",
    (4, 1, 4): "X3-TRENE",
    (4, 1, 16): "X3-PRO G2",
    (4, 1, 31): "X3-AELIO",
    (4, 1, 42): "X3-AELIO",
    (4, 1, 100): "X3-FORTH",
    (4, 1, 101): "X3-MEGA G2",
    (4, 1, 104): "X3-GRAND",
    (4, 1, 105): "X3-FORTH PLUS",
    (4, 2, 1): "TB-HR140",
    (4, 2, 2): "TB-HR522",
    (4, 2, 145): "TSYS-HS51",
    (4, 2, 163): "TR-HR140",
    (4, 3, 6): "CT",
    (4, 3, 7): "DTSU666-CT",
    (4, 3, 8): "UMG 103-CBM",
    (4, 3, 9): "M3-40-Dual",
    (4, 3, 10): "M3-40",
    (4, 3, 11): "PRISMA-310A",
    (4, 4, 1): "X1/X3-EVC",
    (4, 4, 2): "X1/X3-EVC G1.1",
    (4, 4, 3): "X1/X3-HAC",
    (4, 4, 4): "J1-EVC",
    (4, 4, 5): "A1-HAC",
    (4, 4, 6): "C1/C3-HAC",
}

FIELD_UNITS = {
    "acPower": ("W", "power"),
    "chargingPower": ("W", "power"),
    "totalActivePower": ("W", "power"),
    "totalReactivePower": ("var", "power"),
    "totalApparentPower": ("VA", "power"),
    "gridPower": ("W", "power"),
    "gridPowerM2": ("W", "power"),
    "dailyYield": ("kWh", "energy"),
    "totalYield": ("kWh", "energy"),
    "dailyACOutput": ("kWh", "energy"),
    "totalACOutput": ("kWh", "energy"),
    "dailyCharged": ("kWh", "energy"),
    "totalCharged": ("kWh", "energy"),
    "dailyDischarged": ("kWh", "energy"),
    "totalDischarged": ("kWh", "energy"),
    "dailyImported": ("kWh", "energy"),
    "totalImported": ("kWh", "energy"),
    "dailyExported": ("kWh", "energy"),
    "totalExported": ("kWh", "energy"),
    "batterySOC": ("%", "battery"),
    "inverterTemperature": ("°C", "temperature"),
    "batteryTemperature": ("°C", "temperature"),
    "gridFrequency": ("Hz", "frequency"),
    "batteryVoltage": ("V", "voltage"),
    "batteryCurrent": ("A", "current"),
    "chargeDischargePower": ("W", "power"),
}

# Explicit control services. All are dry-run blocked in this development phase.
CONTROL_SERVICE_DEFINITIONS = {
    "set_export_control": {
        "endpoint": "/openapi/v2/device/device_control/strategy/set_export_control",
        "required": {
            "snList": list,
            "deviceType": int,
            "isEnable": int,
            "limitValue": (int, float),
            "businessType": int,
        },
        "optional": {"controlMode": int},
    },
    "set_import_control": {
        "endpoint": "/openapi/v2/device/device_control/strategy/set_import_control",
        "required": {"snList": list, "deviceType": int, "isEnable": int, "limitValue": int, "businessType": int},
        "optional": {},
    },
    "batch_set_spontaneity_self_use": {
        "endpoint": "/openapi/v2/device/inverter_work_mode/batch_set_spontaneity_self_use",
        "required": {"snList": list, "minSoc": int, "chargeFromGridEnable": int, "chargeUpperSoc": int, "businessType": int},
        "optional": {
            "chargeStartTimePeriod1": str,
            "chargeEndTimePeriod1": str,
            "dischargeStartTimePeriod1": str,
            "dischargeEndTimePeriod1": str,
            "enableTimePeriod2": int,
            "chargeStartTimePeriod2": str,
            "chargeEndTimePeriod2": str,
            "dischargeStartTimePeriod2": str,
            "dischargeEndTimePeriod2": str,
        },
    },
    "batch_set_on_grid_first": {
        "endpoint": "/openapi/v2/device/inverter_work_mode/batch_set_on_grid_first",
        "required": {"snList": list, "minSoc": int, "chargeUpperSoc": int, "businessType": int},
        "optional": {
            "chargeStartTimePeriod1": str,
            "chargeEndTimePeriod1": str,
            "dischargeStartTimePeriod1": str,
            "dischargeEndTimePeriod1": str,
            "enableTimePeriod2": int,
            "chargeStartTimePeriod2": str,
            "chargeEndTimePeriod2": str,
            "dischargeStartTimePeriod2": str,
            "dischargeEndTimePeriod2": str,
        },
    },
    "batch_set_peace_mode": {
        "endpoint": "/openapi/v2/device/inverter_work_mode/batch_set_peace_mode",
        "required": {"snList": list, "minSoc": int, "chargeFromGridEnable": int, "chargeUpperSoc": int, "businessType": int},
        "optional": {
            "chargeStartTimePeriod1": str,
            "chargeEndTimePeriod1": str,
            "dischargeStartTimePeriod1": str,
            "dischargeEndTimePeriod1": str,
            "enableTimePeriod2": int,
            "chargeStartTimePeriod2": str,
            "chargeEndTimePeriod2": str,
            "dischargeStartTimePeriod2": str,
            "dischargeEndTimePeriod2": str,
        },
    },
    "batch_set_manual_mode": {
        "endpoint": "/openapi/v2/device/inverter_work_mode/batch_set_manual_mode",
        "required": {"snList": list, "manualMode": int, "businessType": int},
        "optional": {},
    },
    "self_use_mode": {
        "endpoint": "/openapi/v2/device/inverter_us_work_mode/self_use_mode",
        "required": {"snList": list, "businessType": int},
        "optional": {},
    },
    "feed_in_priority": {
        "endpoint": "/openapi/v2/device/inverter_us_work_mode/feed_in_priority",
        "required": {"snList": list, "businessType": int},
        "optional": {},
    },
    "back_up_mode": {
        "endpoint": "/openapi/v2/device/inverter_us_work_mode/back_up_Mode",
        "required": {
            "snList": list,
            "backUpGridEnable": int,
            "backUpChargeStartTime": str,
            "backUpChargeEndTime": str,
            "businessType": int,
        },
        "optional": {},
    },
    "demand_mode": {
        "endpoint": "/openapi/v2/device/inverter_us_work_mode/demand_mode",
        "required": {
            "snList": list,
            "demandGridEnable": int,
            "peakLimitTime1": int,
            "peakLimitTime2": int,
            "demandDischargeStartTime1": str,
            "demandDischargeEndTime1": str,
            "demandDischargeStartTime2": str,
            "demandDischargeEndTime2": str,
            "chargerPowerLimit": int,
            "demandMaxSoc": int,
            "reserveSoc": int,
            "businessType": int,
        },
        "optional": {},
    },
    "const_power_mode": {
        "endpoint": "/openapi/v2/device/inverter_us_work_mode/const_power_mode",
        "required": {
            "snList": list,
            "constPowerGridEnable": int,
            "constPowerDischargeLimit": int,
            "constPowerChargeStartTime": str,
            "constPowerChargeEndTime": str,
            "constPowerDischargeStartTime": str,
            "constPowerDischargeEndTime": str,
            "businessType": int,
        },
        "optional": {},
    },
    "exit_vpp_mode": {
        "endpoint": "/openapi/v2/device/inverter_vpp_mode/exit_vpp_mode",
        "required": {"snList": list, "businessType": int},
        "optional": {},
    },
    "power_control_mode": {
        "endpoint": "/openapi/v2/device/inverter_vpp_mode/power_control_mode",
        "required": {
            "snList": list,
            "activePowerTarget": int,
            "wReactivePowerTarget": int,
            "timeOfDuration": int,
            "businessType": int,
        },
        "optional": {},
    },
    "electric_quantity_target_control_mode": {
        "endpoint": "/openapi/v2/device/inverter_vpp_mode/electric_quantity_target_control_mode",
        "required": {"snList": list, "targetEngergy": int, "chargeDischargPower": int, "businessType": int},
        "optional": {},
    },
    "soc_target_control_mode": {
        "endpoint": "/openapi/v2/device/inverter_vpp_mode/soc_target_control_mode",
        "required": {"snList": list, "targetSoc": int, "chargeDischargPower": int, "businessType": int},
        "optional": {},
    },
    "push_power_positive_or_negative_mode": {
        "endpoint": "/openapi/v2/device/inverter_vpp_mode/push_power/positive_or_negative_mode",
        "required": {"snList": list, "batteryPower": int, "timeOfDuration": int, "nextMotion": int, "businessType": int},
        "optional": {},
    },
    "push_power_zero_mode": {
        "endpoint": "/openapi/v2/device/inverter_vpp_mode/push_power/zero_mode",
        "required": {"snList": list, "timeOfDuration": int, "nextMotion": int, "businessType": int},
        "optional": {},
    },
    "self_consume_charge_or_discharge_mode": {
        "endpoint": "/openapi/v2/device/inverter_vpp_mode/self_consume/charge_or_discharge_mode",
        "required": {"snList": list, "timeOfDuration": int, "nextMotion": int, "businessType": int},
        "optional": {},
    },
    "self_consume_charge_only_mode": {
        "endpoint": "/openapi/v2/device/inverter_vpp_mode/self_consume/charge_only_mode",
        "required": {"snList": list, "timeOfDuration": int, "nextMotion": int, "businessType": int},
        "optional": {},
    },
    "pv_and_bat_individual_setting_duration_mode": {
        "endpoint": "/openapi/v2/device/inverter_vpp_mode/pv_and_bat/individual_setting_duration_mode",
        "required": {
            "snList": list,
            "batteryPower": int,
            "pvPowerLimit": int,
            "timeOfDuration": int,
            "nextMotion": int,
            "businessType": int,
        },
        "optional": {},
    },
    "pv_and_bat_individual_setting_target_soc_mode": {
        "endpoint": "/openapi/v2/device/inverter_vpp_mode/pv_and_bat/individual_setting_target_soc_mode",
        "required": {
            "snList": list,
            "batteryPower": int,
            "pvPowerLimit": int,
            "targetSoc": int,
            "timeOfDuration": int,
            "nextMotion": int,
            "businessType": int,
        },
        "optional": {},
    },
    "set_charge_scene": {
        "endpoint": "/openapi/v2/device/evc_control/set_charge_scene",
        "required": {"snList": list, "chargerScene": int, "businessType": int},
        "optional": {"ocppUrl": str, "ocppChargerId": str},
    },
    "set_evc_qr_code": {
        "endpoint": "/openapi/v2/device/evc_control/set_evc_qr_code",
        "required": {"snList": list, "qrCode": str, "businessType": int},
        "optional": {},
    },
    "set_evc_work_mode": {
        "endpoint": "/openapi/v2/device/evc_control/set_evc_work_mode",
        "required": {"snList": list, "workMode": int, "businessType": int},
        "optional": {"currentGear": int},
    },
    "set_evc_start_mode": {
        "endpoint": "/openapi/v2/device/evc_control/set_evc_start_mode",
        "required": {"snList": list, "startMode": int, "businessType": int},
        "optional": {},
    },
    "set_evc_charge_command": {
        "endpoint": "/openapi/v2/device/evc_control/set_evc_charge_command",
        "required": {"snList": list, "workCmd": int, "businessType": int},
        "optional": {},
    },
    "set_evc_reserve_charge": {
        "endpoint": "/openapi/v2/device/evc_control/set_evc_reserve_charge",
        "required": {
            "snList": list,
            "chargeStartTime": str,
            "chargeEndTime": str,
            "chargeCurrent": int,
            "businessType": int,
        },
        "optional": {},
    },
    "set_evc_current_limit": {
        "endpoint": "/openapi/v2/device/evc_control/set_evc_current_limit",
        "required": {"snList": list, "currentLimit": int, "businessType": int},
        "optional": {},
    },
    "set_battery_heating": {
        "endpoint": "/openapi/v2/device/config/battery/set_battery_heating",
        "required": {
            "snList": list,
            "heatingEnable": int,
            "businessType": int,
        },
        "optional": {
            "heatingLevel": int,
            "heatingPeriod1StartTime": str,
            "heatingPeriod1EndTime": str,
            "heatingPeriod2StartTime": str,
            "heatingPeriod2EndTime": str,
        },
    },
    "set_ems_manual_mode": {
        "endpoint": "/openapi/v2/device/ems_system/control/work_mode/manual",
        "required": {
            "deviceType": int,
            "businessType": int,
            "paramList": list,
        },
        "optional": {},
    },
}

# Services are registered only when the loaded account exposes the relevant family.
CONTROL_SERVICE_CAPABILITIES = {
    "set_export_control": {"families": ("inverter", "ems")},
    "set_import_control": {"families": ("ci_inverter", "ems")},
    "batch_set_spontaneity_self_use": {"families": ("battery_system",)},
    "batch_set_on_grid_first": {"families": ("battery_system",)},
    "batch_set_peace_mode": {"families": ("battery_system",)},
    "batch_set_manual_mode": {"families": ("battery_system",)},
    "self_use_mode": {"families": ("a1_hybrid_g2",)},
    "feed_in_priority": {"families": ("a1_hybrid_g2",)},
    "back_up_mode": {"families": ("a1_hybrid_g2",)},
    "demand_mode": {"families": ("a1_hybrid_g2",)},
    "const_power_mode": {"families": ("a1_hybrid_g2",)},
    "exit_vpp_mode": {"families": ("battery_system",)},
    "power_control_mode": {"families": ("battery_system",)},
    "electric_quantity_target_control_mode": {"families": ("battery_system",)},
    "soc_target_control_mode": {"families": ("battery_system",)},
    "push_power_positive_or_negative_mode": {"families": ("battery_system",)},
    "push_power_zero_mode": {"families": ("battery_system",)},
    "self_consume_charge_or_discharge_mode": {"families": ("battery_system",)},
    "self_consume_charge_only_mode": {"families": ("battery_system",)},
    "pv_and_bat_individual_setting_duration_mode": {"families": ("battery_system",)},
    "pv_and_bat_individual_setting_target_soc_mode": {"families": ("battery_system",)},
    "set_charge_scene": {"families": ("ev_charger",)},
    "set_evc_qr_code": {"families": ("ev_charger",)},
    "set_evc_work_mode": {"families": ("ev_charger",)},
    "set_evc_start_mode": {"families": ("ev_charger",)},
    "set_evc_charge_command": {"families": ("ev_charger",)},
    "set_evc_reserve_charge": {"families": ("ev_charger",)},
    "set_evc_current_limit": {"families": ("ev_charger",)},
    "set_battery_heating": {"families": ("battery_system",)},
    "set_ems_manual_mode": {"families": ("ems",)},
}
