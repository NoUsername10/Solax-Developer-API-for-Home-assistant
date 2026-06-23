"""Validation helpers for control dry-run services."""

from __future__ import annotations

import re
import math
from typing import Any

from .const import BUSINESS_TYPES, CONTROL_SERVICE_DEFINITIONS


class ControlValidationError(ValueError):
    """Validation exception with translation metadata."""

    def __init__(
        self,
        key: str,
        *,
        placeholders: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(key)
        self.key = key
        self.placeholders = placeholders or {}


def validate_hhmm(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value))


def _expected_type_name(expected_type: type | tuple[type, ...]) -> str:
    if isinstance(expected_type, tuple):
        return " or ".join(item.__name__ for item in expected_type)
    return expected_type.__name__


def _is_expected_type(value: Any, expected_type: type | tuple[type, ...]) -> bool:
    numeric_types = expected_type if isinstance(expected_type, tuple) else (expected_type,)
    if isinstance(value, bool) and any(item in (int, float) for item in numeric_types):
        return False
    return isinstance(value, expected_type)


def _time_minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def control_service_field_name(api_field: str) -> str:
    """Return the Home Assistant service-field name for an API payload field."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", str(api_field)).lower()


def _service_key_to_api_key(key: str) -> str:
    parts = str(key).split("_")
    if len(parts) == 1:
        return parts[0]
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def build_api_control_payload(value: Any) -> Any:
    """Convert Home Assistant snake_case fields to SolaX API-native keys."""
    if isinstance(value, dict):
        return {
            _service_key_to_api_key(str(key)): build_api_control_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [build_api_control_payload(item) for item in value]
    return value


def _has_invalid_service_field_name(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", str(key)):
                return True
            if _has_invalid_service_field_name(item):
                return True
    elif isinstance(value, list):
        return any(_has_invalid_service_field_name(item) for item in value)
    return False


def validate_control_payload(service: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate payload against endpoint-specific dry-run schema."""
    if service not in CONTROL_SERVICE_DEFINITIONS:
        raise ControlValidationError(
            "runtime.errors.control_unknown_service",
            placeholders={"service": service},
        )

    if _has_invalid_service_field_name(payload):
        raise ControlValidationError(
            "runtime.errors.control_field_name_invalid",
            placeholders={"service": service},
        )
    payload = build_api_control_payload(payload)
    definition = CONTROL_SERVICE_DEFINITIONS[service]
    required = definition.get("required", {})
    optional = definition.get("optional", {})

    normalized: dict[str, Any] = {}

    for key, expected_type in required.items():
        if key not in payload:
            raise ControlValidationError(
                "runtime.errors.control_missing_required_field",
                placeholders={"service": service, "field": key},
            )
        value = payload[key]
        if not _is_expected_type(value, expected_type):
            raise ControlValidationError(
                "runtime.errors.control_field_type_mismatch",
                placeholders={
                    "service": service,
                    "field": key,
                    "expected_type": _expected_type_name(expected_type),
                },
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise ControlValidationError(
                "runtime.errors.control_field_number_invalid",
                placeholders={"service": service, "field": key},
            )
        normalized[key] = value

    for key, expected_type in optional.items():
        if key not in payload:
            continue
        value = payload[key]
        if not _is_expected_type(value, expected_type):
            raise ControlValidationError(
                "runtime.errors.control_field_type_mismatch",
                placeholders={
                    "service": service,
                    "field": key,
                    "expected_type": _expected_type_name(expected_type),
                },
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise ControlValidationError(
                "runtime.errors.control_field_number_invalid",
                placeholders={"service": service, "field": key},
            )
        normalized[key] = value

    if "snList" in normalized:
        sn_list = [str(sn).strip() for sn in normalized["snList"] if str(sn).strip()]
        if not sn_list:
            raise ControlValidationError(
                "runtime.errors.control_sn_list_empty",
                placeholders={"service": service},
            )
        if len(sn_list) > 10:
            raise ControlValidationError(
                "runtime.errors.control_sn_list_too_long",
                placeholders={"service": service, "max": "10"},
            )
        normalized["snList"] = sn_list

    business_type = normalized.get("businessType")
    if business_type is not None and business_type not in BUSINESS_TYPES:
        raise ControlValidationError(
            "runtime.errors.control_business_type_invalid",
            placeholders={"service": service},
        )

    for key, value in normalized.items():
        if isinstance(value, str) and "Time" in key and not validate_hhmm(value):
            raise ControlValidationError(
                "runtime.errors.control_time_format_invalid",
                placeholders={"service": service, "field": key},
            )

    if service == "set_battery_heating":
        heating_enable = normalized["heatingEnable"]
        if heating_enable not in (0, 1):
            raise ControlValidationError(
                "runtime.errors.control_field_value_invalid",
                placeholders={"service": service, "field": "heatingEnable"},
            )
        if heating_enable == 1:
            for field in (
                "heatingLevel",
                "heatingPeriod1StartTime",
                "heatingPeriod1EndTime",
            ):
                if field not in normalized:
                    raise ControlValidationError(
                        "runtime.errors.control_missing_required_field",
                        placeholders={"service": service, "field": field},
                    )
            if normalized["heatingLevel"] not in (0, 1, 2):
                raise ControlValidationError(
                    "runtime.errors.control_field_value_invalid",
                    placeholders={"service": service, "field": "heatingLevel"},
                )
            if _time_minutes(normalized["heatingPeriod1EndTime"]) <= _time_minutes(
                normalized["heatingPeriod1StartTime"]
            ):
                raise ControlValidationError(
                    "runtime.errors.control_time_order_invalid",
                    placeholders={
                        "service": service,
                        "start_field": "heatingPeriod1StartTime",
                        "end_field": "heatingPeriod1EndTime",
                    },
                )
        second_start = normalized.get("heatingPeriod2StartTime")
        second_end = normalized.get("heatingPeriod2EndTime")
        if bool(second_start) != bool(second_end):
            missing_field = (
                "heatingPeriod2EndTime" if second_start else "heatingPeriod2StartTime"
            )
            raise ControlValidationError(
                "runtime.errors.control_missing_required_field",
                placeholders={"service": service, "field": missing_field},
            )
        if second_start and second_end and _time_minutes(second_end) <= _time_minutes(second_start):
            raise ControlValidationError(
                "runtime.errors.control_time_order_invalid",
                placeholders={
                    "service": service,
                    "start_field": "heatingPeriod2StartTime",
                    "end_field": "heatingPeriod2EndTime",
                },
            )

    if service == "set_ems_manual_mode":
        if normalized["deviceType"] != 100 or normalized["businessType"] != 4:
            raise ControlValidationError(
                "runtime.errors.control_ems_context_invalid",
                placeholders={"service": service},
            )
        param_list = normalized["paramList"]
        if not param_list or len(param_list) > 10:
            raise ControlValidationError(
                "runtime.errors.control_param_list_length_invalid",
                placeholders={"service": service, "max": "10"},
            )
        normalized_params: list[dict[str, Any]] = []
        for index, item in enumerate(param_list):
            if not isinstance(item, dict):
                raise ControlValidationError(
                    "runtime.errors.control_param_list_item_invalid",
                    placeholders={"service": service, "index": str(index)},
                )
            register_no = str(item.get("registerNo") or "").strip()
            manual_mode = item.get("manualMode")
            if not register_no:
                raise ControlValidationError(
                    "runtime.errors.control_missing_required_field",
                    placeholders={
                        "service": service,
                        "field": f"paramList[{index}].registerNo",
                    },
                )
            if isinstance(manual_mode, bool) or not isinstance(manual_mode, int):
                raise ControlValidationError(
                    "runtime.errors.control_field_type_mismatch",
                    placeholders={
                        "service": service,
                        "field": f"paramList[{index}].manualMode",
                        "expected_type": "int",
                    },
                )
            if manual_mode not in (0, 1, 2):
                raise ControlValidationError(
                    "runtime.errors.control_field_value_invalid",
                    placeholders={
                        "service": service,
                        "field": f"paramList[{index}].manualMode",
                    },
                )
            normalized_item: dict[str, Any] = {
                "registerNo": register_no,
                "manualMode": manual_mode,
            }
            if manual_mode in (1, 2):
                for field in ("power", "targetSoc"):
                    value = item.get(field)
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise ControlValidationError(
                            "runtime.errors.control_field_type_mismatch",
                            placeholders={
                                "service": service,
                                "field": f"paramList[{index}].{field}",
                                "expected_type": "int or float",
                            },
                        )
                    normalized_item[field] = value
                if not 10 <= float(normalized_item["targetSoc"]) <= 100:
                    raise ControlValidationError(
                        "runtime.errors.control_field_value_invalid",
                        placeholders={
                            "service": service,
                            "field": f"paramList[{index}].targetSoc",
                        },
                    )
            normalized_params.append(normalized_item)
        normalized["paramList"] = normalized_params

    return normalized
