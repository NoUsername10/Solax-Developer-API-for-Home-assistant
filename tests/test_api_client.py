from unittest.mock import AsyncMock

import pytest

from custom_components.solax_developer_api import api as api_module
from custom_components.solax_developer_api.api import SolaxDeveloperApiClient


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def text(self):
        return str(self._payload)

    async def json(self):
        return self._payload


class FakeRequestContext:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, data=None, json=None, headers=None):
        return self.request("POST", url, data=data, json=json, headers=headers)

    def request(self, method, url, params=None, data=None, json=None, headers=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": params,
                "data": data,
                "json": json,
                "headers": headers or {},
            }
        )
        if not self._responses:
            raise AssertionError("No fake response left")
        return FakeRequestContext(self._responses.pop(0))


@pytest.mark.asyncio
async def test_token_and_read_request_flow():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "code": 0,
                    "result": {
                        "access_token": "token-1",
                        "expires_in": 3600,
                        "scope": "API_Info_V2",
                        "grant_type": "client_credentials",
                        "auth_station": "all",
                    },
                },
            ),
            FakeResponse(
                200,
                {
                    "code": 10000,
                    "result": {"records": [], "pages": 1, "current": 1},
                },
            ),
        ]
    )
    client = SolaxDeveloperApiClient(
        client_id="id",
        client_secret="secret",
        region="eu",
        session=session,
    )

    payload = await client.page_plant_info(business_type=1, page_no=1)
    assert payload["code"] == 10000
    assert len(session.calls) == 2
    assert session.calls[1]["headers"]["Authorization"].startswith("bearer ")
    assert client.token_scope == "API_Info_V2"
    assert client.token_grant_type == "client_credentials"
    assert client.token_auth_station == "all"


@pytest.mark.asyncio
async def test_auth_retry_on_10402_then_success():
    session = FakeSession(
        [
            FakeResponse(200, {"code": 0, "result": {"access_token": "token-1", "expires_in": 3600}}),
            FakeResponse(200, {"code": 10402, "message": "token invalid"}),
            FakeResponse(200, {"code": 0, "result": {"access_token": "token-2", "expires_in": 3600}}),
            FakeResponse(
                200,
                {
                    "code": 10000,
                    "result": {"records": [], "pages": 1, "current": 1},
                },
            ),
        ]
    )
    client = SolaxDeveloperApiClient(
        client_id="id",
        client_secret="secret",
        region="eu",
        session=session,
    )

    payload = await client.page_plant_info(business_type=1, page_no=1)
    assert payload["code"] == 10000
    assert len(session.calls) == 4


@pytest.mark.asyncio
async def test_device_realtime_batched_chunks_to_max_10():
    responses = [
        FakeResponse(200, {"code": 0, "result": {"access_token": "token-1", "expires_in": 3600}}),
        FakeResponse(200, {"code": 10000, "result": [{"deviceSn": "SN1"}]}),
        FakeResponse(200, {"code": 10000, "result": [{"deviceSn": "SN11"}]}),
    ]
    session = FakeSession(responses)
    client = SolaxDeveloperApiClient(
        client_id="id",
        client_secret="secret",
        region="eu",
        session=session,
    )

    sn_list = [f"SN{i}" for i in range(1, 12)]
    rows = await client.device_realtime_data_batched(
        sn_list=sn_list,
        device_type=1,
        business_type=1,
    )

    assert [row["deviceSn"] for row in rows] == ["SN1", "SN11"]
    realtime_calls = [call for call in session.calls if "device/realtime_data" in call["url"]]
    assert len(realtime_calls) == 2
    first_sns = realtime_calls[0]["params"]["snList"].split(",")
    second_sns = realtime_calls[1]["params"]["snList"].split(",")
    assert len(first_sns) == 10
    assert len(second_sns) == 1


@pytest.mark.asyncio
async def test_query_request_result_accepts_string_request_id_and_code_zero():
    session = FakeSession(
        [
            FakeResponse(200, {"code": 0, "result": {"access_token": "token-1", "expires_in": 3600}}),
            FakeResponse(200, {"code": 0, "result": []}),
        ]
    )
    client = SolaxDeveloperApiClient(
        client_id="id",
        client_secret="secret",
        region="eu",
        session=session,
    )

    payload = await client.query_request_result(request_id="123456789")
    assert payload["code"] == 0
    assert session.calls[-1]["json"] == {"requestId": "123456789"}


@pytest.mark.asyncio
async def test_execute_control_uses_authenticated_device_post_contract():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "code": 0,
                    "result": {"access_token": "token-1", "expires_in": 3600},
                },
            ),
            FakeResponse(
                200,
                {
                    "code": 10000,
                    "message": "success",
                    "requestId": "REQ1",
                    "result": {"EVC1": {"status": 3}},
                },
            ),
        ]
    )
    client = SolaxDeveloperApiClient(
        client_id="id",
        client_secret="secret",
        region="eu",
        session=session,
    )

    payload = await client.execute_control(
        path="/openapi/v2/device/evc_control/set_evc_charge_command",
        payload={"snList": ["EVC1"], "workCmd": 2, "businessType": 1},
    )

    assert payload["requestId"] == "REQ1"
    assert session.calls[-1]["method"] == "POST"
    assert session.calls[-1]["json"]["workCmd"] == 2
    assert session.calls[-1]["headers"]["Authorization"].startswith("bearer ")
    with pytest.raises(ValueError):
        await client.execute_control(
            path="/openapi/v2/plant/not_a_control",
            payload={},
        )


@pytest.mark.asyncio
async def test_ems_read_wrappers_use_dedicated_post_contracts():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {"code": 0, "result": {"access_token": "token-1", "expires_in": 3600}},
            ),
            FakeResponse(
                200,
                {
                    "code": 10000,
                    "result": [{"registerNo": "EMS1", "stationId": "PLANT1"}],
                },
            ),
            FakeResponse(
                200,
                {
                    "code": 10000,
                    "result": [{"registerNo": "EMS1", "sysPVPower": 10.5}],
                },
            ),
        ]
    )
    client = SolaxDeveloperApiClient(
        client_id="id",
        client_secret="secret",
        region="eu",
        session=session,
    )

    attributes = await client.ems_attribute_info(
        register_no="EMS1",
        plant_id="PLANT1",
    )
    summary = await client.ems_summary_data(register_no_list=["EMS1"])

    assert attributes["result"][0]["registerNo"] == "EMS1"
    assert summary["result"][0]["sysPVPower"] == 10.5
    assert session.calls[-2]["json"] == {
        "registerNo": "EMS1",
        "plantId": "PLANT1",
        "deviceType": 100,
        "businessType": 4,
    }
    assert session.calls[-1]["json"] == {
        "registerNoList": ["EMS1"],
        "deviceType": 100,
        "businessType": 4,
    }


@pytest.mark.asyncio
async def test_device_history_windowed_splits_and_dedupes_rows():
    session = FakeSession(
        [
            FakeResponse(200, {"code": 0, "result": {"access_token": "token-1", "expires_in": 3600}}),
            FakeResponse(
                200,
                {
                    "code": 10000,
                    "result": [
                        {"deviceSn": "SN1", "dataTime": "2026-01-01 00:00:00", "value": 1},
                        {"deviceSn": "SN1", "dataTime": "2026-01-01 00:05:00", "value": 2},
                    ],
                },
            ),
            FakeResponse(
                200,
                {
                    "code": 10000,
                    "result": [
                        {"deviceSn": "SN1", "dataTime": "2026-01-01 00:05:00", "value": 2},
                        {"deviceSn": "SN1", "dataTime": "2026-01-01 00:10:00", "value": 3},
                    ],
                },
            ),
        ]
    )
    client = SolaxDeveloperApiClient(
        client_id="id",
        client_secret="secret",
        region="eu",
        session=session,
    )

    payload = await client.device_history_data_windowed(
        sn_list=["SN1"],
        device_type=1,
        business_type=1,
        start_time=0,
        end_time=2000,
        time_interval=5,
        max_window_ms=1000,
    )

    assert payload["code"] == 10000
    assert payload["windowSummary"]["windowCount"] == 2
    assert [row["value"] for row in payload["result"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_device_history_windowed_paces_long_requests(monkeypatch):
    session = FakeSession(
        [
            FakeResponse(200, {"code": 0, "result": {"access_token": "token-1", "expires_in": 3600}}),
            FakeResponse(200, {"code": 10000, "result": []}),
            FakeResponse(200, {"code": 10000, "result": []}),
            FakeResponse(200, {"code": 10000, "result": []}),
        ]
    )
    sleep_mock = AsyncMock()
    monkeypatch.setattr(api_module.asyncio, "sleep", sleep_mock)
    client = SolaxDeveloperApiClient(
        client_id="id",
        client_secret="secret",
        region="eu",
        session=session,
    )

    payload = await client.device_history_data_windowed(
        sn_list=["SN1"],
        device_type=1,
        business_type=1,
        start_time=0,
        end_time=3000,
        time_interval=60,
        max_window_ms=1000,
        request_delay_seconds=0.75,
    )

    assert payload["windowSummary"]["windowCount"] == 3
    assert payload["windowSummary"]["requestCount"] == 3
    assert payload["windowSummary"]["requestDelaySeconds"] == 0.75
    assert sleep_mock.await_count == 2
    sleep_mock.assert_awaited_with(0.75)
