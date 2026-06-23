import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.solax_developer_api.diagnostics import (
    REDACTED_VALUE,
    async_get_config_entry_diagnostics,
    _build_filtered_api_projection,
    _build_raw_vs_filtered_summary,
    _has_meaningful_state,
    _mask_secret,
    _mask_serial,
    _sanitize_for_diagnostics,
)


def test_mask_secret_first_last():
    assert _mask_secret("2026031712349532") == "2026***9532"
    assert _mask_secret("abcd") == "a***d"


def test_mask_serial_middle_six():
    masked = _mask_serial("TESTMETER000001")
    assert masked != "TESTMETER000001"
    assert "***" in masked
    assert masked.startswith("T")
    assert masked.endswith("1")
    assert len(masked) == len("TESTMETER000001") - 3


def test_sanitize_masks_nested_secret_and_serial_values():
    payload = {
        "client_secret": "test-client-secret-never-used-for-live-requests",
        "Authorization": "bearer 0YU_CJKbSZjRVz1iZpgzu5token",
        "deviceSn": "TESTMETER000001",
        "nested": {
            "snList": ["TESTMETER000001", "TESTINV000001"],
            "raw_api_token_masked": "2026***9532",
        },
    }
    sanitized = _sanitize_for_diagnostics(payload)
    assert sanitized["client_secret"] != payload["client_secret"]
    assert "bearer " in sanitized["Authorization"]
    assert sanitized["deviceSn"] != payload["deviceSn"]
    assert sanitized["nested"]["snList"][0] != "TESTMETER000001"
    assert sanitized["nested"]["raw_api_token_masked"] == "2026***9532"


def test_sanitize_redacts_personal_fields_and_keeps_token_expires_at():
    payload = {
        "plantId": "1983359809783000000",
        "plantName": "My Home Plant",
        "loginName": "user@example.com",
        "plantAddress": "Street 123",
        "longitude": 5.0,
        "latitude": 10.0,
        "token_expires_at": "2026-04-13T11:05:11.310430+00:00",
    }
    sanitized = _sanitize_for_diagnostics(payload)
    assert sanitized["plantId"] == "*REDACTED*"
    assert sanitized["plantName"] == "*REDACTED*"
    assert sanitized["loginName"] == "*REDACTED*"
    assert sanitized["plantAddress"] == "*REDACTED*"
    assert sanitized["longitude"] == "*REDACTED*"
    assert sanitized["latitude"] == "*REDACTED*"
    assert sanitized["token_expires_at"] == "2026-04-13T11:05:11.310430+00:00"


def test_filtered_projection_and_raw_vs_filtered_summary():
    state = {
        "plant_realtime": {
            "PLANT1": {"acPower": 0.0, "dcPower": None, "gridPower": 1450},
        },
        "device_realtime": {
            "SERIAL_A": {"deviceSn": "SERIAL_A", "importEnergy": 12.3, "exportEnergy": None},
        },
        "plants": {"PLANT1": {"plantId": "PLANT1"}},
        "devices": {"SERIAL_A": {"deviceSn": "SERIAL_A", "deviceType": 3}},
    }
    filtered = _build_filtered_api_projection(state)
    assert "dcPower" not in filtered["plant_realtime"]["PLANT1"]
    assert "exportEnergy" not in filtered["device_realtime"]["SERIAL_A"]

    raw_api = {
        "plant_realtime_data": [
            {
                "request": {"plantId": "PLANT1", "businessType": 1},
                "response": {
                    "code": 10000,
                    "result": {"acPower": 0.0, "dcPower": None, "gridPower": 1450},
                },
            }
        ],
        "device_realtime_data": [
            {
                "request": {"deviceType": 3, "businessType": 1, "snList": ["SERIAL_A"]},
                "response": {
                    "code": 10000,
                    "result": [
                        {
                            "deviceSn": "SERIAL_A",
                            "importEnergy": 12.3,
                            "exportEnergy": None,
                        }
                    ],
                },
            }
        ],
    }
    summary = _build_raw_vs_filtered_summary(raw_api, filtered)
    assert summary["plants"]["PLANT1"]["dcPower"]["present_in_raw_result"] is True
    assert summary["plants"]["PLANT1"]["dcPower"]["present_in_filtered_payload"] is False
    assert summary["devices"]["SERIAL_A"]["exportEnergy"]["present_in_raw_result"] is True
    assert summary["devices"]["SERIAL_A"]["exportEnergy"]["present_in_filtered_payload"] is False


def test_raw_vs_filtered_summary_redacts_sensitive_filtered_values():
    raw_api = {
        "plant_realtime_data": [
            {
                "request": {"plantId": "PLANT1", "businessType": 1},
                "response": {
                    "code": 10000,
                    "result": {
                        "plantId": "1983359809783000000",
                        "plantName": "Home Plant",
                        "loginName": "user@example.com",
                        "plantAddress": "Street 123",
                        "longitude": 5.0,
                        "latitude": 10.0,
                    },
                },
            }
        ],
    }
    filtered = {
        "plant_realtime": {
            "PLANT1": {
                "plantId": "1983359809783000000",
                "plantName": "Home Plant",
                "loginName": "user@example.com",
                "plantAddress": "Street 123",
                "longitude": 5.0,
                "latitude": 10.0,
            }
        },
        "device_realtime": {},
    }

    summary = _build_raw_vs_filtered_summary(raw_api, filtered)
    for field in (
        "plantId",
        "plantName",
        "loginName",
        "plantAddress",
        "longitude",
        "latitude",
    ):
        assert summary["plants"]["PLANT1"][field]["filtered_value"] == REDACTED_VALUE


def test_has_meaningful_state_considers_raw_api_payloads():
    empty_state = {}
    raw_empty = {
        "page_plant_info": [],
        "page_device_info": [],
    }
    assert _has_meaningful_state(empty_state, raw_empty) is False

    raw_with_data = {
        "page_plant_info": [{"request": {"businessType": 1}, "response": {"code": 10000}}],
    }
    assert _has_meaningful_state(empty_state, raw_with_data) is True


class _FakeHass:
    data = {}


class _FakeEntry:
    entry_id = "entry-1"
    title = "Test Solax"
    data = {
        "client_id": "client-id-1234",
        "client_secret": "client-secret-1234",
        "api_region": "eu",
        "scan_interval": 120,
        "system_name": "Solax",
    }
    options = {}
    state = ConfigEntryState.NOT_LOADED


class _FallbackProbeClient:
    def __init__(self, **kwargs):
        self.access_token = "token-123456"
        self.token_expires_at = None
        self.token_lifetime_seconds = 3600


class _FallbackProbeCoordinator:
    def __init__(self, *args, **kwargs):
        self.name = "probe"
        self.data = {
            "plants": {},
            "devices": {},
            "plant_realtime": {},
            "device_realtime": {},
            "meta": {},
        }
        self.raw_api_responses = {}
        self.history_cache = {}
        self.request_result_cache = {}
        self.master_control_cache = {}
        self.control_dry_runs = []
        self.rate_limited = False
        self.rate_limited_context = []
        self.last_update_attempt = None
        self.last_successful_update = None
        self.last_rate_limit_at = None

    async def _async_update_data(self):
        self.data = {
            "plants": {"PLANT1": {"plantId": "PLANT1"}},
            "devices": {},
            "plant_realtime": {"PLANT1": {"acPower": 12.3}},
            "device_realtime": {},
            "meta": {"poll_profile": "standard"},
        }
        self.raw_api_responses = {
            "plant_realtime_data": [
                {
                    "request": {"plantId": "PLANT1", "businessType": 1},
                    "response": {"code": 10000, "result": {"acPower": 12.3}},
                }
            ]
        }
        return self.data


class _FallbackFailCoordinator(_FallbackProbeCoordinator):
    async def _async_update_data(self):
        raise RuntimeError("probe failed")


@pytest.mark.asyncio
async def test_unloaded_entry_diagnostics_runs_temporary_probe(monkeypatch):
    from custom_components.solax_developer_api import diagnostics

    monkeypatch.setattr(diagnostics, "async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(diagnostics, "SolaxDeveloperApiClient", _FallbackProbeClient)
    monkeypatch.setattr(diagnostics, "SolaxDeveloperCoordinator", _FallbackProbeCoordinator)

    payload = await async_get_config_entry_diagnostics(_FakeHass(), _FakeEntry())

    assert payload["fallback_probe"]["executed"] is True
    assert payload["fallback_probe"]["success"] is True
    assert payload["filtered_api_responses"]["plant_realtime"]["PLANT1"]["acPower"] == 12.3
    assert any(issue["type"] == "entry_not_loaded" for issue in payload["issues"])


@pytest.mark.asyncio
async def test_unloaded_entry_diagnostics_reports_temporary_probe_failure(monkeypatch):
    from custom_components.solax_developer_api import diagnostics

    monkeypatch.setattr(diagnostics, "async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(diagnostics, "SolaxDeveloperApiClient", _FallbackProbeClient)
    monkeypatch.setattr(diagnostics, "SolaxDeveloperCoordinator", _FallbackFailCoordinator)

    payload = await async_get_config_entry_diagnostics(_FakeHass(), _FakeEntry())

    assert payload["fallback_probe"]["executed"] is True
    assert payload["fallback_probe"]["success"] is False
    assert any(issue["type"] == "unloaded_entry_probe_failed" for issue in payload["issues"])
