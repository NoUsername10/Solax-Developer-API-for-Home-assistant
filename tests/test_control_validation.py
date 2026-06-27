from pathlib import Path
import re

import pytest

from custom_components.solax_developer_api.const import CONTROL_SERVICE_DEFINITIONS
from custom_components.solax_developer_api.validation import (
    ControlValidationError,
    control_service_field_name,
    validate_control_payload,
)


def test_validate_control_payload_accepts_valid_payload():
    payload = {
        "sn_list": ["X3******01"],
        "device_type": 100,
        "is_enable": 1,
        "limit_value": 11,
        "business_type": 4,
        "control_mode": 1,
    }
    validated = validate_control_payload("set_export_control", payload)
    assert validated["snList"] == ["X3******01"]
    assert validated["businessType"] == 4


def test_validate_control_payload_rejects_missing_fields():
    with pytest.raises(ControlValidationError) as err:
        validate_control_payload(
            "set_export_control",
            {
                "sn_list": ["X3******01"],
                "device_type": 100,
                "business_type": 4,
            },
        )
    assert err.value.key == "runtime.errors.control_missing_required_field"


def test_validate_control_payload_rejects_invalid_time_format():
    with pytest.raises(ControlValidationError) as err:
        validate_control_payload(
            "set_evc_reserve_charge",
            {
                "sn_list": ["C1******01"],
                "charge_start_time": "9:00",
                "charge_end_time": "10:00",
                "charge_current": 16,
                "business_type": 4,
            },
        )
    assert err.value.key == "runtime.errors.control_time_format_invalid"


def test_export_limit_accepts_documented_decimal_value():
    payload = {
        "sn_list": ["X3******01"],
        "device_type": 100,
        "is_enable": 1,
        "limit_value": 1.25,
        "business_type": 4,
        "control_mode": 1,
    }
    validated = validate_control_payload("set_export_control", payload)
    assert validated["limitValue"] == 1.25


def test_control_payload_accepts_snake_case_and_returns_api_native_keys():
    validated = validate_control_payload(
        "set_export_control",
        {
            "sn_list": ["X3******01"],
            "device_type": 100,
            "is_enable": 1,
            "limit_value": 1.25,
            "business_type": 4,
            "control_mode": 1,
        },
    )
    assert validated["snList"] == ["X3******01"]
    assert validated["limitValue"] == 1.25
    assert "sn_list" not in validated


def test_nested_ems_payload_accepts_snake_case_fields():
    validated = validate_control_payload(
        "set_ems_manual_mode",
        {
            "device_type": 100,
            "business_type": 4,
            "param_list": [
                {
                    "register_no": "EMS1",
                    "manual_mode": 1,
                    "power": 100,
                    "target_soc": 80,
                }
            ],
        },
    )
    assert validated["paramList"][0]["registerNo"] == "EMS1"
    assert validated["paramList"][0]["targetSoc"] == 80


def test_control_payload_rejects_camel_case_fields():
    with pytest.raises(ControlValidationError) as err:
        validate_control_payload(
            "set_export_control",
            {
                "snList": ["X3******01"],
                "device_type": 100,
                "is_enable": 1,
                "limit_value": 1.25,
                "business_type": 4,
            },
        )
    assert err.value.key == "runtime.errors.control_field_name_invalid"

    with pytest.raises(ControlValidationError) as nested_err:
        validate_control_payload(
            "set_ems_manual_mode",
            {
                "device_type": 100,
                "business_type": 4,
                "param_list": [{"registerNo": "EMS1", "manual_mode": 0}],
            },
        )
    assert nested_err.value.key == "runtime.errors.control_field_name_invalid"


def test_evc_control_payload_validates_documented_enums_and_ranges():
    assert validate_control_payload(
        "set_charge_scene",
        {
            "sn_list": ["C1******01"],
            "charger_scene": 2,
            "business_type": 1,
        },
    )["chargerScene"] == 2
    assert validate_control_payload(
        "set_evc_work_mode",
        {
            "sn_list": ["C1******01"],
            "work_mode": 2,
            "current_gear": 16,
            "business_type": 4,
        },
    )["currentGear"] == 16
    assert validate_control_payload(
        "set_evc_work_mode",
        {
            "sn_list": ["C1******01"],
            "work_mode": 3,
            "current_gear": 6,
            "business_type": 4,
        },
    )["workMode"] == 3
    assert validate_control_payload(
        "set_evc_start_mode",
        {
            "sn_list": ["C1******01"],
            "start_mode": 2,
            "business_type": 1,
        },
    )["startMode"] == 2
    assert validate_control_payload(
        "set_evc_charge_command",
        {
            "sn_list": ["C1******01"],
            "work_cmd": 3,
            "business_type": 1,
        },
    )["workCmd"] == 3
    assert validate_control_payload(
        "set_evc_reserve_charge",
        {
            "sn_list": ["C1******01"],
            "charge_start_time": "22:00",
            "charge_end_time": "06:00",
            "charge_current": 16,
            "business_type": 4,
        },
    )["chargeCurrent"] == 16
    assert validate_control_payload(
        "set_evc_current_limit",
        {
            "sn_list": ["C1******01"],
            "current_limit": 40,
            "business_type": 4,
        },
    )["currentLimit"] == 40

    invalid_payloads = [
        (
            "set_charge_scene",
            {"sn_list": ["C1"], "charger_scene": 9, "business_type": 1},
        ),
        (
            "set_evc_work_mode",
            {
                "sn_list": ["C1"],
                "work_mode": 2,
                "current_gear": 3,
                "business_type": 1,
            },
        ),
        (
            "set_evc_work_mode",
            {
                "sn_list": ["C1"],
                "work_mode": 1,
                "current_gear": 16,
                "business_type": 1,
            },
        ),
        (
            "set_evc_start_mode",
            {"sn_list": ["C1"], "start_mode": 9, "business_type": 1},
        ),
        (
            "set_evc_charge_command",
            {"sn_list": ["C1"], "work_cmd": 9, "business_type": 1},
        ),
        (
            "set_evc_reserve_charge",
            {
                "sn_list": ["C1"],
                "charge_start_time": "08:00",
                "charge_end_time": "08:00",
                "charge_current": 16,
                "business_type": 1,
            },
        ),
        (
            "set_evc_current_limit",
            {"sn_list": ["C1"], "current_limit": 41, "business_type": 1},
        ),
    ]
    for service, payload in invalid_payloads:
        with pytest.raises(ControlValidationError) as err:
            validate_control_payload(service, payload)
        assert err.value.key == "runtime.errors.control_field_value_invalid"


def test_battery_heating_enforces_conditional_fields():
    with pytest.raises(ControlValidationError) as err:
        validate_control_payload(
            "set_battery_heating",
            {
                "sn_list": ["X3******01"],
                "heating_enable": 1,
                "business_type": 1,
            },
        )
    assert err.value.key == "runtime.errors.control_missing_required_field"

    validated = validate_control_payload(
        "set_battery_heating",
        {
            "sn_list": ["X3******01"],
            "heating_enable": 1,
            "heating_level": 1,
            "heating_period1_start_time": "06:00",
            "heating_period1_end_time": "09:00",
            "business_type": 1,
        },
    )
    assert validated["heatingLevel"] == 1


def test_ems_manual_mode_validates_nested_parameters():
    validated = validate_control_payload(
        "set_ems_manual_mode",
        {
            "device_type": 100,
            "business_type": 4,
            "param_list": [
                {
                    "register_no": "EMS1",
                    "manual_mode": 1,
                    "power": 100,
                    "target_soc": 80,
                }
            ],
        },
    )
    assert validated["paramList"][0]["registerNo"] == "EMS1"

    with pytest.raises(ControlValidationError) as err:
        validate_control_payload(
            "set_ems_manual_mode",
            {
                "device_type": 100,
                "business_type": 4,
                "param_list": [{"register_no": "EMS1", "manual_mode": 1}],
            },
        )
    assert err.value.key == "runtime.errors.control_field_type_mismatch"


def _service_blocks(text: str) -> dict[str, str]:
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line and not line.startswith(" ") and line.endswith(":"):
            current = line[:-1]
            blocks[current] = [line]
            continue
        if current is not None:
            blocks[current].append(line)
    return {name: "\n".join(lines) for name, lines in blocks.items()}


def test_services_yaml_documents_all_dry_run_payload_fields():
    services_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "solax_developer_api"
        / "services.yaml"
    )
    blocks = _service_blocks(services_path.read_text())

    for service, definition in CONTROL_SERVICE_DEFINITIONS.items():
        block = blocks[service]
        assert "  fields:" in block
        assert "    entry_id:" in block
        for field in definition.get("required", {}):
            service_field = control_service_field_name(field)
            assert f"    {service_field}:" in block
            match = re.search(
                rf"(?ms)^    {re.escape(service_field)}:\n(.*?)(?=^    \S|\Z)",
                block,
            )
            assert match is not None
            field_block = match.group(1)
            assert "required: true" in field_block
        for field in definition.get("optional", {}):
            assert f"    {control_service_field_name(field)}:" in block
