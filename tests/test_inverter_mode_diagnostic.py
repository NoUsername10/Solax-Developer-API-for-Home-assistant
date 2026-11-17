"""The GUI diagnostic sends once and observes the same request after status 5."""

from types import SimpleNamespace

import pytest

from custom_components.solax_developer_api.api import SolaxApiError
from custom_components.solax_developer_api.coordinator import SolaxDeveloperCoordinator
from custom_components.solax_developer_api import inverter_mode_diagnostic as diagnostic


def _coordinator(*, response=None, statuses=(), error=None):
    calls = []

    async def execute_control(*, path, payload):
        calls.append(("command", path, payload))
        if error:
            raise error
        return response or {
            "code": 10000,
            "requestId": "private-request-id",
            "result": {"INV-1": {"status": 3}},
        }

    async def query_request_result(*, request_id):
        calls.append(("query", request_id))
        status = statuses[len(calls) - 2]
        if isinstance(status, Exception):
            raise status
        return {"code": 10000, "result": [{"deviceSn": "INV-1", "status": status}]}

    options = {
        "inverter_mode_controls_enabled": True,
        "inverter_mode_profiles": {
            "INV-1": {
                "self_use": {
                    "profiles": {
                        "profile-1": {
                            "name": "Cloudy",
                            "family": "standard",
                            "min_soc": 10,
                            "charge_from_grid_enable": False,
                            "charge_upper_soc": 90,
                        }
                    }
                }
            }
        },
    }
    fake = SimpleNamespace(
        inverter_mode_controls_enabled=True,
        inverter_mode_options=options,
        data={"devices": {"INV-1": {
            "deviceSn": "INV-1", "deviceType": 1, "deviceModel": 33, "businessType": 1,
        }}},
        client=SimpleNamespace(execute_control=execute_control, query_request_result=query_request_result),
        _control_response_status_summary=SolaxDeveloperCoordinator._control_response_status_summary,
        _target_control_status_summary=SolaxDeveloperCoordinator._target_control_status_summary,
        _control_result_shape=SolaxDeveloperCoordinator._control_result_shape,
        _coerce_int=SolaxDeveloperCoordinator._coerce_int,
    )
    return fake, calls


@pytest.mark.asyncio
async def test_diagnostic_continues_querying_after_status_five(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(diagnostic.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(diagnostic, "QUERY_DELAYS_SECONDS", (0, 0, 0, 0))
    coordinator, calls = _coordinator(statuses=(3, 5, 5, 3))
    report = await diagnostic.run_inverter_mode_diagnostic(
        coordinator, serial="INV-1", mode="self_use", profile_id="profile-1"
    )
    assert len([call for call in calls if call[0] == "command"]) == 1
    assert [call[1] for call in calls if call[0] == "query"] == ["private-request-id"] * 4
    assert [item["status"] for item in report["query_samples"]] == [3, 5, 5, 3]
    assert report["initial"]["status"] == 3
    assert report["inverter"] == "Inverter 1"
    assert report["profile"] == "Profile 1"
    assert report["sent_parameters"] == {
        "businessType": 1, "minSoc": 10, "chargeFromGridEnable": 0, "chargeUpperSoc": 90,
    }
    assert "INV-1" not in str(report)
    assert "private-request-id" not in str(report)


@pytest.mark.asyncio
async def test_diagnostic_reports_immediate_parameter_rejection_without_query():
    coordinator, calls = _coordinator(error=SolaxApiError(
        code=10200,
        message="PARAM_ERROR: chargeStartTimePeriod1 in type 'HH:mm'",
        classification="operation_error",
    ))
    report = await diagnostic.run_inverter_mode_diagnostic(
        coordinator, serial="INV-1", mode="self_use", profile_id="profile-1"
    )
    assert len(calls) == 1
    assert report["initial"] == {
        "api_code": 10200,
        "classification": "operation_error",
        "parameter_field": "chargeStartTimePeriod1",
    }
    assert report["query_skipped_reason"] == "command_request_rejected"


@pytest.mark.asyncio
async def test_diagnostic_continues_after_query_error(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(diagnostic.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(diagnostic, "QUERY_DELAYS_SECONDS", (0, 0, 0))
    coordinator, calls = _coordinator(statuses=(
        5,
        SolaxApiError(code=10004, message="private request ID", classification="api_error"),
        3,
    ))
    report = await diagnostic.run_inverter_mode_diagnostic(
        coordinator, serial="INV-1", mode="self_use", profile_id="profile-1"
    )
    assert len([call for call in calls if call[0] == "query"]) == 3
    assert [sample.get("status") for sample in report["query_samples"]] == [5, None, 3]
    assert report["query_samples"][1]["api_code"] == 10004
    assert "private request ID" not in str(report)


@pytest.mark.asyncio
async def test_diagnostic_without_request_id_does_not_query():
    coordinator, calls = _coordinator(response={
        "code": 10000, "result": {"INV-1": {"status": 3}}
    })
    report = await diagnostic.run_inverter_mode_diagnostic(
        coordinator, serial="INV-1", mode="self_use", profile_id="profile-1"
    )
    assert len(calls) == 1
    assert report["query_skipped_reason"] == "no_request_id"


@pytest.mark.asyncio
async def test_diagnostic_rejects_manual_mode_without_sending():
    coordinator, calls = _coordinator()
    with pytest.raises(ValueError, match="manual_mode_diagnostic_not_supported"):
        await diagnostic.run_inverter_mode_diagnostic(
            coordinator, serial="INV-1", mode="manual", profile_id="profile-1"
        )
    assert calls == []
