from datetime import timedelta

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.solax_developer_api import _sanitize_dry_run_payload_for_log
from custom_components.solax_developer_api import config_flow
from custom_components.solax_developer_api.api import SolaxApiError
from custom_components.solax_developer_api.coordinator import SolaxDeveloperCoordinator


class _DummyHass:
    pass


@pytest.mark.asyncio
async def test_validate_credentials_requires_at_least_one_read(monkeypatch):
    class _ReadFailClient:
        def __init__(self, **kwargs):
            return

        async def ensure_token(self, *, force_refresh=False):
            return

        async def page_plant_info(self, *, business_type, page_no):
            raise SolaxApiError(
                code=10500,
                message="permission denied",
                classification="permission",
            )

    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(config_flow, "SolaxDeveloperApiClient", _ReadFailClient)

    valid, err = await config_flow._validate_credentials(
        _DummyHass(),
        client_id="id",
        client_secret="secret",
        region="eu",
    )
    assert valid is False
    assert err == "cannot_read_data"


@pytest.mark.asyncio
async def test_validate_credentials_succeeds_when_one_business_type_reads(monkeypatch):
    class _ReadSuccessClient:
        def __init__(self, **kwargs):
            return

        async def ensure_token(self, *, force_refresh=False):
            return

        async def page_plant_info(self, *, business_type, page_no):
            if business_type == 1:
                raise SolaxApiError(
                    code=10500,
                    message="permission denied",
                    classification="permission",
                )
            return {"code": 10000, "result": {"records": [], "pages": 1, "current": 1}}

    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(config_flow, "SolaxDeveloperApiClient", _ReadSuccessClient)

    valid, err = await config_flow._validate_credentials(
        _DummyHass(),
        client_id="id",
        client_secret="secret",
        region="eu",
    )
    assert valid is True
    assert err is None


@pytest.mark.asyncio
async def test_validate_credentials_returns_cannot_connect_for_read_timeout(monkeypatch):
    class _TimeoutReadClient:
        def __init__(self, **kwargs):
            return

        async def ensure_token(self, *, force_refresh=False):
            return

        async def page_plant_info(self, *, business_type, page_no):
            raise SolaxApiError(
                code=None,
                message="timeout",
                classification="timeout",
            )

    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(config_flow, "SolaxDeveloperApiClient", _TimeoutReadClient)

    valid, err = await config_flow._validate_credentials(
        _DummyHass(),
        client_id="id",
        client_secret="secret",
        region="eu",
    )
    assert valid is False
    assert err == "cannot_connect"


@pytest.mark.asyncio
async def test_validate_credentials_returns_cannot_connect_for_unexpected_read_error(monkeypatch):
    class _UnexpectedReadClient:
        def __init__(self, **kwargs):
            return

        async def ensure_token(self, *, force_refresh=False):
            return

        async def page_plant_info(self, *, business_type, page_no):
            raise RuntimeError("network exploded")

    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(config_flow, "SolaxDeveloperApiClient", _UnexpectedReadClient)

    valid, err = await config_flow._validate_credentials(
        _DummyHass(),
        client_id="id",
        client_secret="secret",
        region="eu",
    )
    assert valid is False
    assert err == "cannot_connect"


def _make_minimal_coordinator():
    coordinator = object.__new__(SolaxDeveloperCoordinator)
    coordinator.hass = _DummyHass()
    coordinator.client = type("_Client", (), {"token_expires_at": None})()
    coordinator._base_scan_interval = 120
    coordinator._effective_scan_interval = 120
    coordinator._live_view_requested_interval = 5
    coordinator._live_view_call_budget_per_minute = 20
    coordinator._live_view_default_duration = 300
    coordinator._live_view_until = None
    coordinator._night_scan_interval = 600
    coordinator._night_start_hour = 23
    coordinator._night_end_hour = 6
    coordinator._poll_profile = "standard"
    coordinator._estimated_live_calls_per_cycle = 0
    coordinator._live_view_budget_adjusted = False
    coordinator._refresh_failure_streak = 0
    coordinator._refresh_backoff_seconds = 0
    coordinator._last_refresh_failure_classification = None
    coordinator._last_refresh_failure_context = None
    coordinator._last_refresh_failure_at = None
    coordinator._poll_count = 0
    coordinator._history_cache = {}
    coordinator._request_result_cache = {}
    coordinator._master_control_cache = {}
    coordinator._control_dry_runs = []
    coordinator._manual_meter_entries = []
    coordinator._manual_ems_entries = []
    coordinator._entry_id = "entry-test"
    coordinator._device_capabilities = {}
    coordinator._raw_api_responses = coordinator._new_raw_api_response_snapshot()
    coordinator.rate_limited = False
    coordinator.rate_limited_context = []
    coordinator.last_rate_limit_at = None
    coordinator.last_update_attempt = None
    coordinator.last_successful_update = None
    coordinator.update_interval = timedelta(seconds=120)
    coordinator.data = coordinator._empty_state()
    return coordinator


def test_live_view_budget_allows_effective_interval_above_60_seconds():
    coordinator = _make_minimal_coordinator()
    plants = {f"plant_{idx}": {} for idx in range(1, 16)}
    inventory_by_type = {"1:1": [f"SN{idx:03d}" for idx in range(1, 152)]}

    interval = coordinator._compute_safe_live_interval(plants, inventory_by_type)

    assert interval > 60
    assert coordinator._live_view_budget_adjusted is True


@pytest.mark.asyncio
async def test_start_live_view_keeps_enabled_when_forced_refresh_fails():
    coordinator = _make_minimal_coordinator()

    def _set_updated_data(data):
        coordinator.data = data

    async def _fail_refresh():
        raise UpdateFailed("temporary read failure")

    coordinator.async_set_updated_data = _set_updated_data
    coordinator.async_request_refresh = _fail_refresh

    result = await coordinator.async_start_live_view()

    assert result["ok"] is True
    assert result["live_view_active"] is True
    assert result["refresh_attempt_success"] is False
    assert "temporary read failure" in result["refresh_error"]


@pytest.mark.asyncio
async def test_update_raises_on_no_fresh_data_and_applies_backoff():
    coordinator = _make_minimal_coordinator()

    async def _fail_inventory(*, raw_cycle=None):
        raise SolaxApiError(
            code=None,
            message="temporary timeout",
            classification="timeout",
        )

    coordinator._refresh_inventory = _fail_inventory

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert coordinator._refresh_failure_streak == 1
    assert coordinator._refresh_backoff_seconds == 120
    assert coordinator.update_interval.total_seconds() == 120


@pytest.mark.asyncio
async def test_update_raises_config_entry_auth_failed_for_auth_rejection():
    coordinator = _make_minimal_coordinator()

    async def _fail_inventory(*, raw_cycle=None):
        raise SolaxApiError(
            code=10402,
            message="access token rejected",
            classification="auth",
        )

    coordinator._refresh_inventory = _fail_inventory

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


def test_refresh_success_resets_failure_backoff_state():
    coordinator = _make_minimal_coordinator()
    coordinator._register_refresh_failure("timeout", "inventory")
    assert coordinator._refresh_failure_streak == 1
    assert coordinator._refresh_backoff_seconds > 0

    coordinator._register_refresh_success()
    assert coordinator._refresh_failure_streak == 0
    assert coordinator._refresh_backoff_seconds == 0
    assert coordinator._last_refresh_failure_classification is None


def test_dry_run_log_sanitizer_masks_sensitive_values():
    payload = {
        "client_secret": "super-secret-value",
        "Authorization": "bearer 0123456789ABCDEF",
        "snList": ["TESTMETER000001"],
    }
    sanitized = _sanitize_dry_run_payload_for_log(payload)
    assert sanitized["client_secret"] != payload["client_secret"]
    assert sanitized["Authorization"] != payload["Authorization"]
    assert sanitized["snList"][0] != payload["snList"][0]


def test_control_capabilities_hide_absent_device_families():
    coordinator = _make_minimal_coordinator()
    coordinator.data = {
        "devices": {
            "INV1": {
                "deviceSn": "INV1",
                "deviceType": 1,
                "businessType": 1,
            }
        },
        "device_realtime": {"INV1": {"acPower": 100}},
    }

    services = coordinator.available_control_services

    assert "set_export_control" in services
    assert "batch_set_manual_mode" not in services
    assert "set_evc_work_mode" not in services
    assert "set_ems_manual_mode" not in services
    assert "set_battery_heating" not in services


def test_battery_and_ems_capabilities_enable_only_matching_controls():
    coordinator = _make_minimal_coordinator()
    coordinator.data = {
        "devices": {
            "INV1": {
                "deviceSn": "INV1",
                "deviceType": 1,
                "businessType": 4,
            },
            "EMS1": {
                "deviceSn": "EMS1",
                "deviceType": 100,
                "businessType": 4,
            },
        },
        "device_realtime": {
            "INV1": {"batterySOC": 50},
            "EMS1": {"sysPVPower": 10},
        },
    }

    services = coordinator.available_control_services

    assert "set_battery_heating" in services
    assert "batch_set_manual_mode" in services
    assert "set_ems_manual_mode" in services
    assert "set_import_control" in services
    assert "set_evc_work_mode" not in services


def test_a1_hybrid_g2_controls_require_exact_model_context():
    coordinator = _make_minimal_coordinator()
    coordinator.data = {
        "devices": {
            "A1": {
                "deviceSn": "A1",
                "deviceType": 1,
                "businessType": 1,
                "deviceModel": 19,
            }
        },
        "device_realtime": {},
    }

    services = coordinator.available_control_services

    assert "self_use_mode" in services
    assert "demand_mode" in services
