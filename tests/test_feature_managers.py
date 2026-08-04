"""Focused contracts for extracted feature managers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.solax_developer_api.features.alarms import AlarmManager


class _AlarmClient:
    def __init__(self, *, failures: set[str] | None = None) -> None:
        self.failures = failures or set()

    async def page_alarm_info(self, *, plant_id: str, **kwargs):
        if plant_id in self.failures:
            raise TimeoutError(f"alarm timeout for {plant_id}")
        records = (
            []
            if plant_id == "P1"
            else [{"alarmName": "Grid fault", "alarmState": 1}]
        )
        return {
            "code": 10000,
            "result": {"total": len(records), "records": records},
        }


class _AlarmOwner:
    def __init__(self, *, failures: set[str] | None = None) -> None:
        self.client = _AlarmClient(failures=failures)
        self.data = {
            "plants": {
                "P1": {"plantId": "P1", "businessType": 1},
                "P2": {"plantId": "P2", "businessType": 4},
            },
            "alarms": {
                "P1": {
                    "total": 1,
                    "records": [{"alarmName": "Old P1", "alarmState": 1}],
                },
                "P2": {
                    "total": 1,
                    "records": [{"alarmName": "Old P2", "alarmState": 1}],
                },
            },
        }

    @staticmethod
    def _new_raw_api_response_snapshot():
        return {}

    @staticmethod
    def _append_raw_snapshot(
        snapshot,
        *,
        endpoint,
        request,
        response=None,
        error=None,
    ):
        snapshot.setdefault(endpoint, []).append(
            {
                "request": request,
                "response": response,
                "error": str(error) if error else None,
            }
        )

    @staticmethod
    def _begin_fetch_request(request_id):
        return request_id

    @staticmethod
    def _finish_fetch_request(request_id):
        return None

    @staticmethod
    def _is_fetch_cancelled(request_id):
        return False

    @staticmethod
    def _coerce_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def list_alarm_targets():
        return {"plants": [], "devices": []}


def _manager(owner: _AlarmOwner) -> AlarmManager:
    manager = object.__new__(AlarmManager)
    manager._owner = owner
    manager.scan_interval = 120
    manager.last_update_attempt = None
    manager.last_successful_update = None
    manager.last_error = None
    manager.last_errors = []
    manager.last_api_calls = 0
    manager.raw_cycle = {}
    manager.data = {}
    return manager


async def test_alarm_manager_success_replaces_zero_and_nonzero_results():
    manager = _manager(_AlarmOwner())

    result = await manager._async_update_data()

    assert result["P1"] == {"total": 0, "records": []}
    assert result["P2"]["records"][0]["alarmName"] == "Grid fault"
    assert manager.last_api_calls == 2
    assert manager.last_errors == []
    assert manager.last_error is None
    assert manager.last_update_attempt is not None
    assert manager.last_successful_update is not None
    assert manager.raw_cycle["alarm_page_alarm_info"]


async def test_alarm_manager_partial_failure_retains_failed_plant_only():
    manager = _manager(_AlarmOwner(failures={"P2"}))

    result = await manager._async_update_data()

    assert result["P1"] == {"total": 0, "records": []}
    assert result["P2"]["records"][0]["alarmName"] == "Old P2"
    assert manager.last_api_calls == 2
    assert manager.last_errors[0]["context"] == "alarms:P2"
    assert "alarm timeout for P2" in manager.last_error
    assert manager.last_successful_update is not None


async def test_alarm_manager_total_failure_reports_update_failed():
    manager = _manager(_AlarmOwner(failures={"P1", "P2"}))

    with pytest.raises(UpdateFailed, match="alarm timeout"):
        await manager._async_update_data()

    assert manager.last_successful_update is None
    assert len(manager.last_errors) == 2
    assert manager.last_api_calls == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ongoing", [1]),
        ("active", [1]),
        ("closed", [0]),
        ("resolved", [0]),
        (1, [1]),
        (0, [0]),
        (SimpleNamespace(), [1, 0]),
    ],
)
def test_alarm_manager_normalizes_viewer_state(value, expected):
    assert AlarmManager.normalize_alarm_states(value) == expected


async def test_alarm_viewer_empty_targets_returns_without_api_call():
    finished = []
    owner = SimpleNamespace(
        _begin_fetch_request=lambda request_id: request_id,
        _finish_fetch_request=finished.append,
        list_alarm_targets=lambda: {"plants": [], "devices": []},
    )
    manager = object.__new__(AlarmManager)
    manager._owner = owner

    result = await manager.async_fetch_alarm_information(request_id="fetch-1")

    assert result == {
        "ok": True,
        "records": [],
        "count": 0,
        "api_calls_made": 0,
        "targets": [],
        "available_fields": [],
        "state_counts": {"ongoing": 0, "closed": 0},
        "page_summaries": [],
        "cancelled": False,
        "request_id": "fetch-1",
    }
    assert finished == ["fetch-1"]


async def test_alarm_viewer_accepts_explicit_plant_not_in_inventory():
    manager = _manager(_AlarmOwner())

    result = await manager.async_fetch_alarm_information(
        plant_id="EXPLICIT",
        business_type=1,
        alarm_state="ongoing",
        max_pages=1,
        request_id="fetch-explicit",
    )

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["api_calls_made"] == 1
    assert result["targets"][0]["plant_id"] == "EXPLICIT"
    assert result["records"][0]["plantId"] == "EXPLICIT"


async def test_alarm_viewer_resolves_a_device_to_its_plant():
    owner = _AlarmOwner()
    owner.list_alarm_targets = lambda: {
        "plants": [
            {
                "plant_id": "P1",
                "plant_name": "Plant One",
                "business_type": 1,
                "label": "Plant One",
            }
        ],
        "devices": [{"device_sn": "INV-1", "plant_id": "P1"}],
    }
    manager = _manager(owner)

    result = await manager.async_fetch_alarm_information(
        device_sn="INV-1",
        alarm_state="ongoing",
        max_pages=1,
    )

    assert result["ok"] is True
    assert result["count"] == 0
    assert result["api_calls_made"] == 1
    assert result["targets"][0]["plant_id"] == "P1"
