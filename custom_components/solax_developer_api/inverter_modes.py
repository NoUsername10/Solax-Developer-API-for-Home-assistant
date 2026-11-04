"""Validated, opt-in inverter work-mode profiles and command payloads."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

from .const import (
    BUSINESS_TYPES,
    CONF_INVERTER_MODE_CONTROLS_ENABLED,
    CONF_INVERTER_MODE_PROFILES,
)
from .validation import ControlValidationError, validate_control_payload, validate_hhmm

A1_HYBRID_G2_MODEL = 19

MODE_SERVICES: dict[str, dict[str, str]] = {
    "standard": {
        "self_use": "batch_set_spontaneity_self_use",
        "feed_in_priority": "batch_set_on_grid_first",
        "back_up": "batch_set_peace_mode",
        "manual": "batch_set_manual_mode",
    },
    "a1_hybrid_g2": {
        "self_use": "self_use_mode",
        "feed_in_priority": "feed_in_priority",
        "back_up": "back_up_mode",
    },
}

MODE_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "standard": {
        "self_use": ("min_soc", "charge_from_grid_enable", "charge_upper_soc"),
        "feed_in_priority": ("min_soc", "charge_upper_soc"),
        "back_up": ("min_soc", "charge_from_grid_enable", "charge_upper_soc"),
        "manual": (),
    },
    "a1_hybrid_g2": {
        "self_use": (),
        "feed_in_priority": (),
        "back_up": (
            "back_up_grid_enable",
            "back_up_charge_start_time",
            "back_up_charge_end_time",
        ),
    },
}

MANUAL_ACTIONS = {
    "manual_stop": 0,
    "manual_charge": 1,
    "manual_discharge": 2,
}


def inverter_family(device: Mapping[str, Any]) -> str | None:
    """Identify a discovered inverter and its documented command family."""
    device_type_value = device.get("deviceType")
    business_type_value = device.get("businessType")
    model_value = device.get("deviceModel")
    if (
        device_type_value is None
        or business_type_value is None
        or model_value is None
    ):
        return None
    try:
        if int(device_type_value) != 1:
            return None
        business_type = int(business_type_value)
        if business_type not in BUSINESS_TYPES:
            return None
        model = int(model_value)
    except (TypeError, ValueError):
        return None
    if model == A1_HYBRID_G2_MODEL:
        return "a1_hybrid_g2" if business_type == 1 else None
    return "standard"


def profile_settings(
    family: str,
    mode: str,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    """Extract and validate only the documented required user settings."""
    fields = MODE_FIELDS[family][mode]
    settings = {field: values[field] for field in fields}
    for field, value in settings.items():
        if field.endswith("_enable"):
            if type(value) is not bool:
                raise ValueError(field)
        elif field.endswith("_time"):
            if isinstance(value, str) and value.endswith(":00") and len(value) == 8:
                value = value[:5]
            if not isinstance(value, str) or not validate_hhmm(value):
                raise ValueError(field)
            settings[field] = value
        else:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not float(value).is_integer()
                or not 0 <= value <= 100
            ):
                raise ValueError(field)
            settings[field] = int(value)
    if "min_soc" in settings and "charge_upper_soc" in settings:
        if settings["charge_upper_soc"] < settings["min_soc"]:
            raise ValueError("charge_upper_soc")
    return settings


def configured_modes(options: Mapping[str, Any], serial: str, family: str) -> list[str]:
    """Return only reviewed, still-valid modes for an inverter."""
    if not options.get(CONF_INVERTER_MODE_CONTROLS_ENABLED, False):
        return []
    profiles = options.get(CONF_INVERTER_MODE_PROFILES) or {}
    per_device = profiles.get(serial) if isinstance(profiles, Mapping) else None
    if not isinstance(per_device, Mapping):
        return []
    ready: list[str] = []
    for mode in MODE_SERVICES[family]:
        profile = per_device.get(mode)
        if not isinstance(profile, Mapping) or profile.get("reviewed") is not True:
            continue
        if profile.get("family") != family:
            continue
        try:
            profile_settings(family, mode, profile)
        except (KeyError, TypeError, ValueError):
            continue
        ready.append(mode)
    return ready


def command_for_mode(
    *,
    options: Mapping[str, Any],
    device: Mapping[str, Any],
    serial: str,
    action: str,
) -> tuple[str, dict[str, Any]]:
    """Build a validated API command from an explicitly reviewed profile."""
    family = inverter_family(device)
    if family is None:
        raise ValueError("inverter_mode_target_unverified")
    if str(device.get("deviceSn") or "").casefold() != serial.casefold():
        raise ValueError("inverter_mode_target_unverified")
    mode = "manual" if action in MANUAL_ACTIONS else action
    if mode not in configured_modes(options, serial, family):
        raise ValueError("inverter_mode_not_enabled")
    service = MODE_SERVICES[family][mode]
    profiles = options[CONF_INVERTER_MODE_PROFILES]
    settings = profile_settings(family, mode, profiles[serial][mode])
    payload: dict[str, Any] = {
        "sn_list": [serial],
        "business_type": int(device["businessType"]),
    }
    for field, value in settings.items():
        payload[field] = int(value) if field.endswith("_enable") else value
    if action in MANUAL_ACTIONS:
        payload["manual_mode"] = MANUAL_ACTIONS[action]
    try:
        return service, validate_control_payload(service, payload)
    except ControlValidationError as err:
        raise ValueError(err.key) from err
