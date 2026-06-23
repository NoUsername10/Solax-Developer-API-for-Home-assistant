from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from custom_components.solax_developer_api.api import (
    SolaxApiError,
    SolaxDeveloperApiClient,
    _history_row_identity,
    chunked,
    classify_api_code,
    serialize_api_error,
    split_time_windows,
)


class _Response:
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload

    async def text(self):
        return str(self.payload)

    async def json(self):
        return self.payload


class _Context:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        return False


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)

    def post(self, *args, **kwargs):
        return _Context(self.responses.pop(0))

    def request(self, *args, **kwargs):
        return _Context(self.responses.pop(0))


def _client(session=None, region="eu"):
    return SolaxDeveloperApiClient(
        client_id="id",
        client_secret="secret",
        region=region,
        session=session or _Session([]),
    )


def test_api_helper_errors_properties_and_classifications():
    with pytest.raises(ValueError):
        chunked([1], 0)
    with pytest.raises(ValueError):
        split_time_windows(0, 1, 0)
    assert _history_row_identity("bad") is None
    assert _history_row_identity({"deviceSn": "A"}) is None
    assert _history_row_identity(
        {"deviceSn": "A", "plantLocalTime": "now"}
    ) == ("A", "now")
    assert classify_api_code(10401) == "auth"
    assert classify_api_code(10001) == "operation_error"
    assert classify_api_code(99999) == "api_error"

    client = _client(region="unknown")
    assert "openapi-eu" in client.base_url
    assert client.token_expires_at is None
    assert client.access_token is None
    assert client.token_lifetime_seconds == 3600
    client._access_token = "token"
    client._token_expires_at = datetime.now(timezone.utc) + timedelta(days=2)
    assert client.token_valid(padding_seconds=90)
    assert serialize_api_error(RuntimeError("boom"))["classification"] == "exception"


@pytest.mark.asyncio
async def test_token_response_error_shapes_and_default_lifetime():
    client = _client(_Session([_Response(500, {"error": "bad"})]))
    with pytest.raises(SolaxApiError) as err:
        await client.ensure_token()
    assert err.value.classification == "http"

    client = _client(_Session([_Response(200, {"code": 10402, "message": "bad"})]))
    with pytest.raises(SolaxApiError) as err:
        await client.ensure_token()
    assert err.value.classification == "auth"

    client = _client(_Session([_Response(200, {"code": 0, "result": {}})]))
    with pytest.raises(SolaxApiError, match="missing access_token"):
        await client.ensure_token()

    client = _client(
        _Session(
            [
                _Response(
                    200,
                    {"code": 0, "result": {"access_token": "token", "expires_in": 0}},
                )
            ]
        )
    )
    await client.ensure_token()
    assert client.token_lifetime_seconds == 3600
    await client.ensure_token()


@pytest.mark.asyncio
async def test_request_json_http_success_none_and_api_error():
    client = _client(_Session([_Response(500, {"error": "bad"})]))
    client._access_token = "token"
    client._token_expires_at = datetime.now(timezone.utc) + timedelta(days=2)
    with pytest.raises(SolaxApiError) as err:
        await client._request_json(method="GET", path="/test")
    assert err.value.classification == "http"

    client = _client(_Session([_Response(200, {"code": 999, "result": 1})]))
    result = await client._request_json(
        method="GET",
        path="/test",
        success_code=None,
        authenticated=False,
    )
    assert result["code"] == 999

    client = _client(_Session([_Response(200, {"code": 10500, "message": "no"})]))
    with pytest.raises(SolaxApiError) as err:
        await client._request_json(
            method="GET",
            path="/test",
            authenticated=False,
        )
    assert err.value.classification == "permission"


@pytest.mark.asyncio
async def test_all_read_wrappers_build_optional_parameters_and_empty_paths():
    client = _client()
    client._request_json = AsyncMock(return_value={"code": 10000, "result": []})

    await client.page_plant_info(
        business_type=1,
        page_no=2,
        plant_id="P1",
        plant_name="Home",
    )
    assert client._request_json.await_args.kwargs["params"]["plantName"] == "Home"

    await client.page_device_info(
        business_type=1,
        device_type=1,
        page_no=2,
        plant_id="P1",
        device_sn="INV1",
    )
    assert client._request_json.await_args.kwargs["params"]["deviceSn"] == "INV1"

    await client.plant_realtime_data(plant_id="P1", business_type=1)
    await client.page_alarm_info(
        plant_id="P1",
        business_type=1,
        device_sn="INV1",
    )
    assert client._request_json.await_args.kwargs["params"]["deviceSn"] == "INV1"
    await client.plant_stat_data(
        plant_id="P1",
        business_type=1,
        date_type=2,
        date="2026-06",
    )
    assert client._request_json.await_args.kwargs["json_body"]["dateType"] == 2

    assert (await client.device_realtime_data(
        sn_list=[],
        device_type=1,
        business_type=1,
    ))["result"] == []
    await client.device_realtime_data(
        sn_list=["INV1"],
        device_type=1,
        business_type=1,
        request_sn_type=2,
    )
    assert client._request_json.await_args.kwargs["params"]["requestSnType"] == 2
    assert await client.device_realtime_data_batched(
        sn_list=[],
        device_type=1,
        business_type=1,
    ) == []

    await client.device_history_data(
        sn_list=["INV1"],
        device_type=1,
        business_type=1,
        start_time=1,
        end_time=2,
        time_interval=5,
        request_sn_type=1,
    )
    assert client._request_json.await_args.kwargs["params"]["requestSnType"] == 1
    assert (await client.device_history_data_windowed(
        sn_list=[],
        device_type=1,
        business_type=1,
        start_time=1,
        end_time=2,
        time_interval=5,
    ))["windowSummary"]["requestCount"] == 0

    with pytest.raises(ValueError):
        await client.query_request_result(request_id=" ")
    await client.get_master_control_device(
        device_sn="INV1",
        device_type=1,
        business_type=4,
    )
    assert client._request_json.await_args.kwargs["json_body"]["deviceSn"] == "INV1"

    await client.ems_attribute_info(
        register_no="EMS1",
        plant_id="123",
    )
    assert client._request_json.await_args.kwargs["json_body"]["plantId"] == 123
    assert (await client.ems_summary_data(register_no_list=[]))["result"] == []
    with pytest.raises(ValueError):
        await client.ems_summary_data(
            register_no_list=[str(index) for index in range(11)]
        )


@pytest.mark.asyncio
async def test_ems_batched_filters_non_mapping_rows():
    client = _client()
    client.ems_summary_data = AsyncMock(
        return_value={"code": 10000, "result": [{"registerNo": "E1"}, "bad"]}
    )
    rows = await client.ems_summary_data_batched(
        register_no_list=[str(index) for index in range(11)]
    )
    assert rows == [{"registerNo": "E1"}, {"registerNo": "E1"}]


@pytest.mark.asyncio
async def test_history_windowed_accepts_single_mapping_result():
    client = _client()
    client.device_history_data = AsyncMock(
        return_value={
            "code": 10000,
            "result": {"deviceSn": "INV1", "dataTime": "now", "value": 1},
        }
    )
    payload = await client.device_history_data_windowed(
        sn_list=["INV1"],
        device_type=1,
        business_type=1,
        start_time=0,
        end_time=10,
        time_interval=5,
        max_window_ms=10,
    )
    assert payload["result"][0]["value"] == 1
