"""Async API client for SolaX Developer OpenAPI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import async_timeout

from .const import (
    API_BASE_URLS,
    API_REGION_DEFAULT,
    DEVICE_HISTORY_SAFE_WINDOW_MS,
    ERROR_AUTH_CODES,
    ERROR_BUSY_CODES,
    ERROR_CALLBACK_CODES,
    ERROR_OPERATION_CODES,
    ERROR_PARAM_CODES,
    ERROR_PERMISSION_CODES,
    ERROR_QUOTA_CODES,
    ERROR_RATE_LIMIT_CODES,
    MAX_SN_PER_REQUEST,
    SUCCESS_CODE_API,
    SUCCESS_CODE_TOKEN,
)


def chunked(items: Iterable[Any], size: int) -> list[list[Any]]:
    """Return list chunks of ``size`` from iterable values."""
    if size <= 0:
        raise ValueError("size must be > 0")
    lst = list(items)
    return [lst[i : i + size] for i in range(0, len(lst), size)]


def normalize_sn_list(sn_list: Iterable[str]) -> list[str]:
    """Normalize serial list, remove empties, keep order, dedupe case-insensitive."""
    seen: set[str] = set()
    unique: list[str] = []
    for raw in sn_list:
        sn = str(raw).strip()
        if not sn:
            continue
        key = sn.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(sn)
    return unique


def split_time_windows(start_time: int, end_time: int, max_window_ms: int) -> list[tuple[int, int]]:
    """Split an absolute millisecond time range into bounded windows."""
    if max_window_ms <= 0:
        raise ValueError("max_window_ms must be > 0")
    if end_time <= start_time:
        raise ValueError("end_time must be greater than start_time")

    windows: list[tuple[int, int]] = []
    cursor = int(start_time)
    end = int(end_time)
    window_size = int(max_window_ms)
    while cursor < end:
        window_end = min(cursor + window_size, end)
        windows.append((cursor, window_end))
        cursor = window_end
    return windows


def _history_row_identity(row: Any) -> tuple[str, str] | None:
    if not isinstance(row, dict):
        return None
    device_sn = str(row.get("deviceSn") or "").strip()
    data_time = str(row.get("dataTime") or row.get("plantLocalTime") or "").strip()
    if not device_sn or not data_time:
        return None
    return device_sn, data_time


def classify_api_code(code: int | None) -> str:
    """Classify a SolaX API code into a stable category string."""
    if code in ERROR_AUTH_CODES:
        return "auth"
    if code in ERROR_RATE_LIMIT_CODES:
        return "rate_limit"
    if code in ERROR_QUOTA_CODES:
        return "quota"
    if code in ERROR_PERMISSION_CODES:
        return "permission"
    if code in ERROR_CALLBACK_CODES:
        return "callback_not_configured"
    if code in ERROR_BUSY_CODES:
        return "busy"
    if code in ERROR_OPERATION_CODES:
        return "operation_error"
    if code in ERROR_PARAM_CODES:
        return "param_error"
    return "api_error"


@dataclass(slots=True)
class SolaxApiError(Exception):
    """Normalized API error."""

    code: int | None
    message: str
    classification: str
    payload: dict[str, Any] | None = None

    def __str__(self) -> str:
        return (
            f"SolaX API error classification={self.classification} "
            f"code={self.code} message={self.message}"
        )


class SolaxDeveloperApiClient:
    """Minimal async client around SolaX Developer OpenAPI."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        region: str = API_REGION_DEFAULT,
        session,
        timeout_seconds: int = 20,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._region = region if region in API_BASE_URLS else API_REGION_DEFAULT
        self._session = session
        self._timeout_seconds = timeout_seconds

        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None
        self._token_lifetime_seconds: int = 3600
        self._token_scope: str | None = None
        self._token_grant_type: str | None = None
        self._token_auth_station: str | None = None
        self._token_lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return API_BASE_URLS[self._region]

    @property
    def token_expires_at(self) -> datetime | None:
        return self._token_expires_at

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def token_lifetime_seconds(self) -> int:
        return int(self._token_lifetime_seconds)

    @property
    def token_scope(self) -> str | None:
        return self._token_scope

    @property
    def token_grant_type(self) -> str | None:
        return self._token_grant_type

    @property
    def token_auth_station(self) -> str | None:
        return self._token_auth_station

    def token_valid(self, *, padding_seconds: int = 24 * 60 * 60) -> bool:
        if not self._access_token or self._token_expires_at is None:
            return False
        effective_padding = max(
            90,
            min(int(padding_seconds), int(self._token_lifetime_seconds // 2)),
        )
        return (
            datetime.now(timezone.utc) + timedelta(seconds=effective_padding)
            < self._token_expires_at
        )

    async def ensure_token(self, *, force_refresh: bool = False) -> None:
        """Ensure an unexpired access token exists."""
        if not force_refresh and self.token_valid():
            return

        async with self._token_lock:
            if not force_refresh and self.token_valid():
                return
            await self._refresh_token()

    async def _refresh_token(self) -> None:
        payload = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "client_credentials",
        }
        url = f"{self.base_url}/openapi/auth/oauth/token"

        try:
            async with async_timeout.timeout(self._timeout_seconds):
                async with self._session.post(
                    url,
                    data=payload,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "*/*",
                    },
                ) as response:
                    text = await response.text()
                    if response.status != 200:
                        raise SolaxApiError(
                            code=response.status,
                            message=f"Token HTTP error: {text}",
                            classification="http",
                            payload={"status": response.status, "body": text},
                        )
                    try:
                        data = await response.json()
                    except Exception as json_err:  # pragma: no cover - defensive
                        raise SolaxApiError(
                            code=None,
                            message=f"Token JSON parse error: {json_err}",
                            classification="json",
                            payload={"body": text},
                        ) from json_err
        except asyncio.TimeoutError as err:
            raise SolaxApiError(
                code=None,
                message="Timeout refreshing access token",
                classification="timeout",
            ) from err

        code = data.get("code")
        if code != SUCCESS_CODE_TOKEN:
            raise SolaxApiError(
                code=code,
                message=str(data.get("message") or "Token request failed"),
                classification=classify_api_code(code),
                payload=data,
            )

        result = data.get("result") or {}
        token = result.get("access_token")
        expires_in = int(result.get("expires_in") or 0)
        if not token:
            raise SolaxApiError(
                code=code,
                message="Token response missing access_token",
                classification="api_error",
                payload=data,
            )

        self._access_token = str(token)
        if expires_in <= 0:
            expires_in = 3600
        self._token_lifetime_seconds = int(expires_in)
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        self._token_scope = str(result.get("scope") or "").strip() or None
        self._token_grant_type = str(result.get("grant_type") or "").strip() or None
        self._token_auth_station = str(result.get("auth_station") or "").strip() or None

    async def _request_json(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        success_code: int | Iterable[int] | None = SUCCESS_CODE_API,
        authenticated: bool = True,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        if authenticated:
            await self.ensure_token()

        headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
        }
        if authenticated and self._access_token:
            headers["Authorization"] = f"bearer {self._access_token}"

        url = f"{self.base_url}{path}"

        try:
            async with async_timeout.timeout(self._timeout_seconds):
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                ) as response:
                    text = await response.text()
                    if response.status != 200:
                        raise SolaxApiError(
                            code=response.status,
                            message=f"HTTP {response.status}: {text}",
                            classification="http",
                            payload={"status": response.status, "body": text},
                        )
                    try:
                        data = await response.json()
                    except Exception as json_err:  # pragma: no cover - defensive
                        raise SolaxApiError(
                            code=None,
                            message=f"JSON parse error: {json_err}",
                            classification="json",
                            payload={"body": text},
                        ) from json_err
        except asyncio.TimeoutError as err:
            raise SolaxApiError(
                code=None,
                message=f"Timeout during API request {path}",
                classification="timeout",
            ) from err

        code = data.get("code")
        if success_code is None:
            return data
        success_codes = (
            {int(success_code)}
            if isinstance(success_code, int)
            else {int(item) for item in success_code}
        )
        if code in success_codes:
            return data

        classification = classify_api_code(code)
        if classification == "auth" and authenticated and retry_auth:
            await self.ensure_token(force_refresh=True)
            return await self._request_json(
                method=method,
                path=path,
                params=params,
                json_body=json_body,
                success_code=success_code,
                authenticated=authenticated,
                retry_auth=False,
            )

        raise SolaxApiError(
            code=code,
            message=str(data.get("message") or "API call failed"),
            classification=classification,
            payload=data,
        )

    async def page_plant_info(
        self,
        *,
        business_type: int,
        page_no: int = 1,
        plant_id: str | None = None,
        plant_name: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "businessType": business_type,
            "pageNo": page_no,
        }
        if plant_id:
            params["plantId"] = plant_id
        if plant_name:
            params["plantName"] = plant_name

        return await self._request_json(
            method="GET",
            path="/openapi/v2/plant/page_plant_info",
            params=params,
        )

    async def page_device_info(
        self,
        *,
        business_type: int,
        device_type: int,
        page_no: int = 1,
        plant_id: str | None = None,
        device_sn: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "businessType": business_type,
            "deviceType": device_type,
            "pageNo": page_no,
        }
        if plant_id:
            params["plantId"] = plant_id
        if device_sn:
            params["deviceSn"] = device_sn

        return await self._request_json(
            method="GET",
            path="/openapi/v2/device/page_device_info",
            params=params,
        )

    async def plant_realtime_data(self, *, plant_id: str, business_type: int) -> dict[str, Any]:
        return await self._request_json(
            method="GET",
            path="/openapi/v2/plant/realtime_data",
            params={"plantId": plant_id, "businessType": business_type},
        )

    async def page_alarm_info(
        self,
        *,
        plant_id: str,
        business_type: int,
        alarm_state: int = 1,
        page_no: int = 1,
        device_sn: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "plantId": plant_id,
            "businessType": business_type,
            "alarmState": alarm_state,
            "pageNo": page_no,
        }
        if device_sn:
            params["deviceSn"] = device_sn
        return await self._request_json(
            method="GET",
            path="/openapi/v2/alarm/page_alarm_info",
            params=params,
        )

    async def plant_stat_data(
        self,
        *,
        plant_id: str,
        business_type: int,
        date_type: int,
        date: str,
    ) -> dict[str, Any]:
        body = {
            "plantId": plant_id,
            "dateType": date_type,
            "date": date,
            "businessType": business_type,
        }
        return await self._request_json(
            method="POST",
            path="/openapi/v2/plant/energy/get_stat_data",
            json_body=body,
        )

    async def device_realtime_data(
        self,
        *,
        sn_list: Iterable[str],
        device_type: int,
        business_type: int,
        request_sn_type: int | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_sn_list(sn_list)
        if not normalized:
            return {"code": SUCCESS_CODE_API, "result": []}

        params: dict[str, Any] = {
            "snList": ",".join(normalized),
            "deviceType": device_type,
            "businessType": business_type,
        }
        if request_sn_type is not None:
            params["requestSnType"] = request_sn_type

        return await self._request_json(
            method="GET",
            path="/openapi/v2/device/realtime_data",
            params=params,
        )

    async def device_realtime_data_batched(
        self,
        *,
        sn_list: Iterable[str],
        device_type: int,
        business_type: int,
        request_sn_type: int | None = None,
    ) -> list[dict[str, Any]]:
        """Call realtime endpoint in chunks due max 10 SN request limit."""
        normalized = normalize_sn_list(sn_list)
        if not normalized:
            return []

        results: list[dict[str, Any]] = []
        for sn_chunk in chunked(normalized, MAX_SN_PER_REQUEST):
            payload = await self.device_realtime_data(
                sn_list=sn_chunk,
                device_type=device_type,
                business_type=business_type,
                request_sn_type=request_sn_type,
            )
            chunk_result = payload.get("result") or []
            if isinstance(chunk_result, list):
                results.extend(chunk_result)
        return results

    async def device_history_data(
        self,
        *,
        sn_list: Iterable[str],
        device_type: int,
        business_type: int,
        start_time: int,
        end_time: int,
        time_interval: int,
        request_sn_type: int | None = None,
    ) -> dict[str, Any]:
        normalized = normalize_sn_list(sn_list)
        params: dict[str, Any] = {
            "snList": ",".join(normalized),
            "deviceType": device_type,
            "businessType": business_type,
            "startTime": start_time,
            "endTime": end_time,
            "timeInterval": time_interval,
        }
        if request_sn_type is not None:
            params["requestSnType"] = request_sn_type

        return await self._request_json(
            method="GET",
            path="/openapi/v2/device/history_data",
            params=params,
        )

    async def device_history_data_windowed(
        self,
        *,
        sn_list: Iterable[str],
        device_type: int,
        business_type: int,
        start_time: int,
        end_time: int,
        time_interval: int,
        request_sn_type: int | None = None,
        max_window_ms: int = DEVICE_HISTORY_SAFE_WINDOW_MS,
        request_delay_seconds: float = 0.0,
    ) -> dict[str, Any]:
        """Fetch history by splitting into API-safe windows and aggregating rows."""
        normalized_sn = normalize_sn_list(sn_list)
        if not normalized_sn:
            return {
                "code": SUCCESS_CODE_API,
                "message": None,
                "result": [],
                "windowSummary": {
                    "windowCount": 0,
                    "snChunkCount": 0,
                    "requestCount": 0,
                    "maxWindowMs": max_window_ms,
                    "requestDelaySeconds": 0.0,
                    "requestStartTime": int(start_time),
                    "requestEndTime": int(end_time),
                    "serialIsolatedRequests": True,
                },
            }

        windows = split_time_windows(start_time, end_time, max_window_ms)
        combined_rows: list[Any] = []
        seen_identity: set[tuple[str, str]] = set()
        request_count = 0
        # Live API validation shows history multi-SN requests return one row per
        # interval across the SN list, not one row per interval per device.
        # Query serials individually so multi-device history charts receive the
        # complete per-device dataset. Realtime endpoints still use max-10 SN batching.
        sn_chunks = [[sn] for sn in normalized_sn]
        total_requests = len(windows) * len(sn_chunks)
        safe_delay = max(0.0, float(request_delay_seconds or 0.0))

        for sn_chunk in sn_chunks:
            for window_start, window_end in windows:
                payload = await self.device_history_data(
                    sn_list=sn_chunk,
                    device_type=device_type,
                    business_type=business_type,
                    start_time=window_start,
                    end_time=window_end,
                    time_interval=time_interval,
                    request_sn_type=request_sn_type,
                )
                request_count += 1
                rows = payload.get("result") or []
                if isinstance(rows, list):
                    for row in rows:
                        row_id = _history_row_identity(row)
                        if row_id is not None and row_id in seen_identity:
                            continue
                        if row_id is not None:
                            seen_identity.add(row_id)
                        combined_rows.append(row)
                elif isinstance(rows, dict):
                    combined_rows.append(rows)
                if safe_delay > 0 and request_count < total_requests:
                    await asyncio.sleep(safe_delay)

        return {
            "code": SUCCESS_CODE_API,
            "message": None,
            "result": combined_rows,
            "windowSummary": {
                "windowCount": len(windows),
                "snChunkCount": len(sn_chunks),
                "requestCount": request_count,
                "maxWindowMs": max_window_ms,
                "requestDelaySeconds": safe_delay,
                "requestStartTime": int(start_time),
                "requestEndTime": int(end_time),
                "serialIsolatedRequests": True,
            },
        }

    async def query_request_result(self, *, request_id: str | int) -> dict[str, Any]:
        normalized_request_id = str(request_id).strip()
        if not normalized_request_id:
            raise ValueError("request_id must not be empty")
        return await self._request_json(
            method="POST",
            path="/openapi/apiRequestLog/listByCondition",
            json_body={"requestId": normalized_request_id},
            success_code=(SUCCESS_CODE_TOKEN, SUCCESS_CODE_API),
        )

    async def execute_control(
        self,
        *,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a vetted Developer API control command."""
        normalized_path = str(path or "").strip()
        if not normalized_path.startswith("/openapi/v2/device/"):
            raise ValueError("control path must be a device OpenAPI endpoint")
        return await self._request_json(
            method="POST",
            path=normalized_path,
            json_body=dict(payload),
        )

    async def get_master_control_device(
        self,
        *,
        device_sn: str,
        device_type: int,
        business_type: int,
    ) -> dict[str, Any]:
        return await self._request_json(
            method="POST",
            path="/openapi/v2/device/get_master_control_device",
            json_body={
                "deviceSn": device_sn,
                "deviceType": device_type,
                "businessType": business_type,
            },
        )

    async def ems_attribute_info(
        self,
        *,
        register_no: str,
        plant_id: str,
        business_type: int = 4,
    ) -> dict[str, Any]:
        normalized_plant_id = str(plant_id).strip()
        plant_id_payload: str | int = (
            int(normalized_plant_id)
            if normalized_plant_id.isdecimal()
            else normalized_plant_id
        )
        return await self._request_json(
            method="POST",
            path="/openapi/v2/device/ems_system/attribute_info",
            json_body={
                "registerNo": str(register_no).strip(),
                "plantId": plant_id_payload,
                "deviceType": 100,
                "businessType": int(business_type),
            },
        )

    async def ems_summary_data(
        self,
        *,
        register_no_list: Iterable[str],
        business_type: int = 4,
    ) -> dict[str, Any]:
        normalized = normalize_sn_list(register_no_list)
        if not normalized:
            return {"code": SUCCESS_CODE_API, "result": []}
        if len(normalized) > MAX_SN_PER_REQUEST:
            raise ValueError(f"register_no_list supports max {MAX_SN_PER_REQUEST} values")
        return await self._request_json(
            method="POST",
            path="/openapi/v2/device/ems_system/summary_data",
            json_body={
                "registerNoList": normalized,
                "deviceType": 100,
                "businessType": int(business_type),
            },
        )

    async def ems_summary_data_batched(
        self,
        *,
        register_no_list: Iterable[str],
        business_type: int = 4,
    ) -> list[dict[str, Any]]:
        normalized = normalize_sn_list(register_no_list)
        results: list[dict[str, Any]] = []
        for register_no_chunk in chunked(normalized, MAX_SN_PER_REQUEST):
            payload = await self.ems_summary_data(
                register_no_list=register_no_chunk,
                business_type=business_type,
            )
            rows = payload.get("result") or []
            if isinstance(rows, list):
                results.extend(row for row in rows if isinstance(row, dict))
        return results


def serialize_api_error(err: Exception) -> dict[str, Any]:
    """Serialize known API errors for attributes/diagnostics."""
    if isinstance(err, SolaxApiError):
        return {
            "code": err.code,
            "message": err.message,
            "classification": err.classification,
            "payload": err.payload,
        }
    return {
        "code": None,
        "message": str(err),
        "classification": "exception",
        "payload": None,
    }
