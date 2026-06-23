import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.solax_developer_api import diagnostics, i18n, validation


class _Config:
    language = "es"


class _Hass:
    def __init__(self):
        self.config = _Config()
        self.tasks = []

    async def async_add_executor_job(self, target, *args):
        return target(*args)

    def async_create_task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task


@pytest.mark.asyncio
async def test_i18n_disk_cache_schedule_and_fallbacks():
    i18n._CATALOG_CACHE.clear()
    i18n._CATALOG_LOAD_TASKS.clear()
    hass = _Hass()

    assert i18n._normalize_lang("") == "en"
    assert i18n._normalize_lang("SV_se") == "sv"
    assert i18n._read_catalog_from_disk("missing")["runtime"]
    assert i18n._resolve_key({"a": {"b": "value"}}, "a.b") == "value"
    assert i18n._resolve_key({"a": {}}, "a.b") is None
    assert i18n._resolve_key({"a": {"b": 1}}, "a.b") is None

    await i18n.async_ensure_catalog_loaded(hass)
    assert "es" in i18n._CATALOG_CACHE
    assert "en" in i18n._CATALOG_CACHE
    assert i18n.translate(hass, "runtime.labels.none") == "(Ninguno)"
    assert (
        i18n.translate(
            hass,
            "runtime.entity_templates.plant_name",
            placeholders={"plant_id": "P1"},
        )
        == "Planta P1"
    )
    assert i18n.translate(hass, "missing.key", fallback="Fallback") == "Fallback"
    assert i18n.translate(hass, "missing.key") == "missing.key"

    i18n._CATALOG_CACHE.clear()
    i18n._schedule_catalog_load(None)
    i18n._schedule_catalog_load(object())
    i18n._schedule_catalog_load(hass, "sv")
    await asyncio.gather(*hass.tasks)
    assert "sv" in i18n._CATALOG_CACHE
    assert i18n._CATALOG_LOAD_TASKS == {}

    bad_hass = SimpleNamespace(
        config=property(lambda self: (_ for _ in ()).throw(RuntimeError()))
    )
    assert i18n.translate(bad_hass, "missing", fallback="{missing}") == "{missing}"


def test_diagnostics_helper_edge_cases_and_serial_collection():
    assert diagnostics._normalize_key(" A-B ") == "a_b"
    assert diagnostics._is_mask_meta_key("token_masked")
    assert not diagnostics._is_secret_key("token_expires_at")
    assert diagnostics._is_secret_key("client_secret")
    assert not diagnostics._is_serial_key("serial_present")
    assert diagnostics._is_serial_key("deviceSn")
    assert diagnostics._is_personal_key("nested_plantAddress")
    assert diagnostics._mask_secret(None) is None
    assert diagnostics._mask_secret("") == ""
    assert diagnostics._mask_secret("a") == "*"
    assert diagnostics._mask_secret("abcdef") == "a***f"
    assert diagnostics._mask_serial(None) is None
    assert diagnostics._mask_serial("") == ""
    assert diagnostics._mask_serial("abc") == "***"
    assert diagnostics._mask_serial("abcdef") == "a***f"
    assert diagnostics._mask_serial("abcdefghi") == "ab***hi"
    assert diagnostics._to_iso(None) is None
    assert diagnostics._to_iso(datetime(2026, 1, 1, tzinfo=timezone.utc))

    class _BadIso:
        def isoformat(self):
            raise RuntimeError("bad")

        def __str__(self):
            return "fallback"

    assert diagnostics._to_iso(_BadIso()) == "fallback"
    assert diagnostics._flatten_dict({"a": {"b": 1}}) == {"a_b": 1}
    assert diagnostics._drop_nulls(
        {"a": None, "b": {}, "c": [], "d": {"x": 1}, "e": [None, {}, 2]}
    ) == {"d": {"x": 1}, "e": [2]}

    state = {
        "devices": {"INV1": {}},
        "manual_meter_entries": [
            "invalid",
            {"serial": "METER1"},
            {"serial": ""},
        ],
        "manual_ems_entries": [{"serial": "EMS1"}],
    }
    assert diagnostics._collect_known_serials(state) == {
        "inv1",
        "meter1",
        "ems1",
    }

    raw = {
        "page_device_info": [
            "invalid",
            {"response": "invalid"},
            {
                "response": {
                    "result": {
                        "records": [
                            "invalid",
                            {"deviceSn": "INV1"},
                        ]
                    }
                }
            },
        ],
        "device_realtime_data": [
            {
                "request": {"snList": ["METER1", ""]},
                "response": {
                    "result": [
                        {"deviceSn": "METER1"},
                        "invalid",
                    ]
                },
            }
        ],
        "ems_attribute_info": [
            {"response": {"result": {"registerNo": "EMS1"}}}
        ],
        "master_control_device": [
            {"response": {"result": {"controlDeviceSn": "EMS2"}}}
        ],
    }
    assert diagnostics._collect_known_serials_from_raw(raw) == {
        "inv1",
        "meter1",
        "ems1",
        "ems2",
    }


def test_diagnostics_sanitizer_and_extractors_cover_nested_keys():
    sanitized = diagnostics._sanitize_for_diagnostics(
        {
            "SECRET": "secret-value",
            "INV1": {"plantName": "Home", "longitude": 1.2},
            "tuple": ("INV1",),
            "authorization": "bearer token-value",
            "raw_api_token_masked": "abcd***wxyz",
            "emptyPlantName": "",
            "boolLatitude": True,
        },
        known_secrets={"secret", "secret-value"},
        known_serials={"inv1"},
    )
    assert "S***T" in sanitized
    assert "***" in sanitized
    assert sanitized["***"]["plantName"] == diagnostics.REDACTED_VALUE
    assert sanitized["authorization"].startswith("bearer ")
    assert sanitized["raw_api_token_masked"] == "abcd***wxyz"
    assert sanitized["emptyPlantName"] == ""
    assert sanitized["boolLatitude"] == diagnostics.REDACTED_VALUE
    assert diagnostics._sanitize_comparison_value("plantId", "P1")
    assert diagnostics._value_meta("", serial=True)["present"] is False

    raw = {
        "plant_realtime_data": [
            "invalid",
            {"request": "bad", "response": {}},
            {
                "request": {"plantId": "P1"},
                "response": {"result": {"power": 1}},
            },
        ],
        "device_realtime_data": [
            "invalid",
            {"response": "bad"},
            {
                "response": {
                    "result": [
                        "invalid",
                        {"deviceSn": ""},
                        {"deviceSn": "INV1", "power": 1},
                    ]
                }
            },
        ],
        "ems_summary_data": [
            {"response": {"result": [{"registerNo": "EMS1", "sysPVPower": 2}]}}
        ],
    }
    assert diagnostics._extract_raw_plant_realtime(raw)["P1"]["power"] == 1
    extracted = diagnostics._extract_raw_device_realtime(raw)
    assert extracted["INV1"]["power"] == 1
    assert extracted["EMS1"]["sysPVPower"] == 2
    summary = diagnostics._field_compare_summary(
        {"power": None, "plantName": "Private"},
        {"plantName": "Private"},
    )
    assert summary["power"]["raw_value_is_null"] is True
    assert (
        summary["plantName"]["filtered_value"]
        == diagnostics.REDACTED_VALUE
    )


@pytest.mark.asyncio
async def test_loaded_diagnostics_empty_refresh_success_and_failure():
    class _Client:
        access_token = "token-value"
        token_expires_at = datetime.now(timezone.utc)
        token_lifetime_seconds = 3600
        token_scope = "all"
        token_grant_type = "client_credentials"
        token_auth_station = "all"

    class _Coordinator:
        def __init__(self, fail=False):
            self.fail = fail
            self.data = {}
            self.raw_api_responses = {}
            self.name = "test"
            self.history_cache = {}
            self.request_result_cache = {}
            self.master_control_cache = {}
            self.control_dry_runs = []
            self.rate_limited = False
            self.rate_limited_context = []
            self.last_update_attempt = None
            self.last_successful_update = None
            self.last_rate_limit_at = None

        async def async_request_refresh(self):
            if self.fail:
                raise RuntimeError("refresh failed")
            self.data = {
                "plants": {"P1": {"plantId": "P1"}},
                "plant_realtime": {"P1": {"power": 1}},
            }

    entry = SimpleNamespace(
        entry_id="entry",
        title="SDS",
        state=ConfigEntryState.LOADED,
        data={"client_id": "id", "client_secret": "secret", "api_region": "eu"},
        options={},
    )
    coordinator = _Coordinator()
    entry.runtime_data = SimpleNamespace(
        client=_Client(),
        coordinator=coordinator,
    )
    payload = await diagnostics.async_get_config_entry_diagnostics(
        SimpleNamespace(),
        entry,
    )
    assert payload["fallback_probe"]["success"] is True

    coordinator = _Coordinator(fail=True)
    entry.runtime_data = SimpleNamespace(
        client=_Client(),
        coordinator=coordinator,
    )
    payload = await diagnostics.async_get_config_entry_diagnostics(
        SimpleNamespace(),
        entry,
    )
    assert payload["fallback_probe"]["success"] is False
    assert payload["issues"][0]["type"] == "fallback_probe_failed"


def _assert_validation_error(service, payload, key):
    with pytest.raises(validation.ControlValidationError) as err:
        validation.validate_control_payload(service, payload)
    assert err.value.key == key


def test_validation_remaining_error_branches():
    assert validation.validate_hhmm("23:59")
    assert not validation.validate_hhmm("24:00")
    assert validation._expected_type_name((int, float)) == "int or float"
    assert validation._expected_type_name(str) == "str"
    assert not validation._is_expected_type(True, int)
    assert validation._time_minutes("01:30") == 90
    assert validation.control_service_field_name("businessType") == "business_type"
    assert validation._service_key_to_api_key("single") == "single"
    assert validation.build_api_control_payload(
        {"param_list": [{"target_soc": 80}]}
    ) == {"paramList": [{"targetSoc": 80}]}
    assert validation._has_invalid_service_field_name(
        {"valid": [{"Bad": 1}]}
    )
    _assert_validation_error(
        "missing",
        {},
        "runtime.errors.control_unknown_service",
    )

    base = {
        "sn_list": ["INV"],
        "device_type": 100,
        "is_enable": 1,
        "limit_value": 1.0,
        "business_type": 4,
        "control_mode": 1,
    }
    _assert_validation_error(
        "set_export_control",
        {**base, "limit_value": float("inf")},
        "runtime.errors.control_field_number_invalid",
    )
    _assert_validation_error(
        "set_export_control",
        {**base, "sn_list": []},
        "runtime.errors.control_sn_list_empty",
    )
    _assert_validation_error(
        "set_export_control",
        {**base, "sn_list": [str(i) for i in range(11)]},
        "runtime.errors.control_sn_list_too_long",
    )
    _assert_validation_error(
        "set_export_control",
        {**base, "business_type": 2},
        "runtime.errors.control_business_type_invalid",
    )

    heating = {
        "sn_list": ["INV"],
        "heating_enable": 1,
        "heating_level": 9,
        "heating_period1_start_time": "10:00",
        "heating_period1_end_time": "09:00",
        "business_type": 1,
    }
    _assert_validation_error(
        "set_battery_heating",
        heating,
        "runtime.errors.control_field_value_invalid",
    )
    _assert_validation_error(
        "set_battery_heating",
        {**heating, "heating_level": 1},
        "runtime.errors.control_time_order_invalid",
    )
    valid_heating = {
        **heating,
        "heating_level": 1,
        "heating_period1_start_time": "09:00",
        "heating_period1_end_time": "10:00",
    }
    _assert_validation_error(
        "set_battery_heating",
        {**valid_heating, "heating_period2_start_time": "11:00"},
        "runtime.errors.control_missing_required_field",
    )
    _assert_validation_error(
        "set_battery_heating",
        {
            **valid_heating,
            "heating_period2_start_time": "12:00",
            "heating_period2_end_time": "11:00",
        },
        "runtime.errors.control_time_order_invalid",
    )

    ems = {
        "device_type": 100,
        "business_type": 4,
        "param_list": [{"register_no": "EMS", "manual_mode": 0}],
    }
    _assert_validation_error(
        "set_ems_manual_mode",
        {**ems, "device_type": 1},
        "runtime.errors.control_ems_context_invalid",
    )
    _assert_validation_error(
        "set_ems_manual_mode",
        {**ems, "param_list": []},
        "runtime.errors.control_param_list_length_invalid",
    )
    _assert_validation_error(
        "set_ems_manual_mode",
        {**ems, "param_list": ["bad"]},
        "runtime.errors.control_param_list_item_invalid",
    )
    _assert_validation_error(
        "set_ems_manual_mode",
        {**ems, "param_list": [{"manual_mode": 0}]},
        "runtime.errors.control_missing_required_field",
    )
    _assert_validation_error(
        "set_ems_manual_mode",
        {**ems, "param_list": [{"register_no": "EMS", "manual_mode": True}]},
        "runtime.errors.control_field_type_mismatch",
    )
    _assert_validation_error(
        "set_ems_manual_mode",
        {**ems, "param_list": [{"register_no": "EMS", "manual_mode": 9}]},
        "runtime.errors.control_field_value_invalid",
    )
    _assert_validation_error(
        "set_ems_manual_mode",
        {
            **ems,
            "param_list": [
                {
                    "register_no": "EMS",
                    "manual_mode": 1,
                    "power": True,
                    "target_soc": 80,
                }
            ],
        },
        "runtime.errors.control_field_type_mismatch",
    )
    _assert_validation_error(
        "set_ems_manual_mode",
        {
            **ems,
            "param_list": [
                {
                    "register_no": "EMS",
                    "manual_mode": 1,
                    "power": 1,
                    "target_soc": 1,
                }
            ],
        },
        "runtime.errors.control_field_value_invalid",
    )
