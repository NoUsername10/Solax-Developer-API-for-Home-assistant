"""Device model code to name mappings for SolaX devices."""

# Residential Inverters (businessType=1, deviceType=1)
RESIDENTIAL_INVERTER_MODELS = {
    1: "X1-LX",
    2: "X-Hybrid",
    3: "X1-Hybrid-G3",
    4: "X1-Boost/Air/Mini",
    5: "X3-Hybrid-G1/G2",
    6: "X3-20K/30K",
    7: "X3-MIC/PRO",
    8: "X1-Smart",
    9: "X1-AC",
    10: "A1-Hybrid",
    11: "A1-FIT",
    12: "A1",
    13: "J1-ESS",
    14: "X3-Hybrid-G4",
    15: "X1-Hybrid-G4",
    16: "X3-MIC/PRO-G2",
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
    43: "X3-ULT-GLV",
    44: "X1-MINI-G4 PLUS",
    46: "X1-Reno-LV",
    47: "A1-HYB-G3",
    100: "X3-FTH",
    101: "X3-MGA-G2",
    102: "X1-Hybrid-LV",
    103: "X1-Lite-LV",
    104: "X3-GRAND-HV",
    105: "X3-FORTH-PLUS"
}

# Commercial & Industrial Inverters (businessType=4, deviceType=1)
COMMERCIAL_INVERTER_MODELS = {
    1: "X3-AELIO (Commercial)",
    2: "X3-TRENE-100KI",
    3: "X3-TRENE-100K",
    4: "X3-TRENE",
    16: "X3-PRO G2",
    31: "X3-AELIO (Commercial)",
    42: "X3-AELIO (Commercial)",
    100: "X3-FORTH",
    101: "X3-MEGA G2",
    104: "X3-GRAND",
    105: "X3-FORTH PLUS"
}

# Residential Batteries (businessType=1, deviceType=2)
RESIDENTIAL_BATTERY_MODELS = {
    1: "TB-HR140",
    2: "TB-HR522",
    145: "TSYS-HS51",
    163: "TR-HR140"
}

# Commercial Batteries (businessType=4, deviceType=2)
COMMERCIAL_BATTERY_MODELS = {
    1: "TB-HR140 (Commercial)",
    2: "TB-HR522 (Commercial)",
    145: "TSYS-HS51 (Commercial)",
    163: "TR-HR140 (Commercial)"
}

# Residential Meters (businessType=1, deviceType=3)
RESIDENTIAL_METER_MODELS = {
    50: "Meter X",
    176: "M1-40",
    178: "M3-40",
    179: "M3-40-Dual",
    181: "M3-40-Wide"
}

# Commercial Meters (businessType=4, deviceType=3)
COMMERCIAL_METER_MODELS = {
    0: "DTSU666-CT",
    1: "DTSU666-CT",
    2: "DTSU666-CT",
    3: "DTSU666-CT",
    4: "Wi-BR DTSU666-CT",
    5: "Wi-BR DTSU666-CT",
    6: "CT",
    7: "DTSU666-CT",
    8: "UMG 103-CBM",
    9: "M3-40-Dual",
    10: "M3-40",
    11: "PRISMA-310A"
}

# EV Chargers (deviceType=4)
EV_CHARGER_MODELS = {
    1: "X1/X3-EVC",
    2: "X1/X3-EVC G1.1",
    3: "X1/X3-HAC",
    4: "J1-EVC",
    5: "A1-HAC",
    6: "C1/C3-HAC"
}

def get_inverter_model_name(model_code, business_type=1):
    """Get human-readable name for inverter model code."""
    if business_type == 1:
        return RESIDENTIAL_INVERTER_MODELS.get(model_code, f"Residential Inverter {model_code}")
    else:
        return COMMERCIAL_INVERTER_MODELS.get(model_code, f"Commercial Inverter {model_code}")

def get_battery_model_name(model_code, business_type=1):
    """Get human-readable name for battery model code."""
    if business_type == 1:
        return RESIDENTIAL_BATTERY_MODELS.get(model_code, f"Residential Battery {model_code}")
    else:
        return COMMERCIAL_BATTERY_MODELS.get(model_code, f"Commercial Battery {model_code}")

def get_meter_model_name(model_code, business_type=1):
    """Get human-readable name for meter model code."""
    if business_type == 1:
        return RESIDENTIAL_METER_MODELS.get(model_code, f"Residential Meter {model_code}")
    else:
        return COMMERCIAL_METER_MODELS.get(model_code, f"Commercial Meter {model_code}")

def get_ev_charger_model_name(model_code):
    """Get human-readable name for EV charger model code."""
    return EV_CHARGER_MODELS.get(model_code, f"EV Charger {model_code}")

def get_device_model_name(device_type, model_code, business_type=1):
    """Get human-readable name for any device type."""
    if device_type == 1:
        return get_inverter_model_name(model_code, business_type)
    elif device_type == 2:
        return get_battery_model_name(model_code, business_type)
    elif device_type == 3:
        return get_meter_model_name(model_code, business_type)
    elif device_type == 4:
        return get_ev_charger_model_name(model_code)
    else:
        return f"Device {model_code}"