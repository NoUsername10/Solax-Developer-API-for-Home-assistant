"""On-demand history and plant-statistics feature support."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import math
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..api import normalize_sn_list
from ..const import DEVICE_HISTORY_SAFE_WINDOW_MS
from ..statistics import extract_plant_stat_metrics, extract_plant_stat_row_metrics

if TYPE_CHECKING:
    from ..coordinator import SolaxDeveloperCoordinator


HISTORY_PACING_THRESHOLD_REQUESTS = 90
HISTORY_TARGET_CALLS_PER_MINUTE = 80


class HistoryManager:
    """Own card-driven history and statistics reads without background polling."""

    def __init__(self, coordinator: SolaxDeveloperCoordinator) -> None:
        self._coordinator = coordinator

    async def async_fetch_device_history(
        self,
        *,
        sn_list: list[str],
        device_type: int,
        business_type: int,
        start_time: int,
        end_time: int,
        time_interval: int,
        request_sn_type: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch history data on demand and cache by parameter key."""
        owner = self._coordinator
        fetch_request_id = owner._begin_fetch_request(request_id)
        normalized_sn = normalize_sn_list(sn_list)
        window_count = max(
            1,
            math.ceil(
                max(0, int(end_time) - int(start_time))
                / DEVICE_HISTORY_SAFE_WINDOW_MS
            ),
        )
        # Multi-SN history responses omit device rows, so isolate each serial.
        sn_request_count = max(1, len(normalized_sn))
        estimated_request_count = window_count * sn_request_count
        request_delay_seconds = (
            60 / HISTORY_TARGET_CALLS_PER_MINUTE
            if estimated_request_count > HISTORY_PACING_THRESHOLD_REQUESTS
            else 0.0
        )
        try:
            payload = await owner.client.device_history_data_windowed(
                sn_list=normalized_sn,
                device_type=device_type,
                business_type=business_type,
                start_time=start_time,
                end_time=end_time,
                time_interval=time_interval,
                request_sn_type=request_sn_type,
                request_delay_seconds=request_delay_seconds,
                cancellation_check=lambda: owner._is_fetch_cancelled(fetch_request_id),
            )
        finally:
            owner._finish_fetch_request(fetch_request_id)

        cache_key = "|".join(
            [
                ",".join(sorted(str(item).strip() for item in normalized_sn)),
                str(device_type),
                str(business_type),
                str(start_time),
                str(end_time),
                str(time_interval),
                str(request_sn_type) if request_sn_type is not None else "",
            ]
        )
        window_summary = payload.get("windowSummary") or {}
        owner._history_cache[cache_key] = {
            "updated_at": dt_util.utcnow().isoformat(),
            "request": {
                "snList": list(normalized_sn),
                "deviceType": device_type,
                "businessType": business_type,
                "startTime": start_time,
                "endTime": end_time,
                "timeInterval": time_interval,
                "requestSnType": request_sn_type,
                "estimatedRequestCount": estimated_request_count,
                "requestDelaySeconds": request_delay_seconds,
                "serialIsolatedRequests": True,
                "requestId": fetch_request_id,
            },
            "window_summary": window_summary,
            "response": payload,
        }
        owner.data.setdefault("meta", {})["history_cache_entries"] = len(
            owner._history_cache
        )
        return {
            "ok": True,
            "cached": True,
            "cache_key": cache_key,
            "result": payload.get("result") or [],
            "code": payload.get("code"),
            "message": payload.get("message"),
            "window_summary": window_summary,
            "cancelled": bool(window_summary.get("cancelled")),
            "request_id": fetch_request_id,
        }

    async def async_fetch_plant_year_statistics(
        self,
        *,
        plant_id: str,
        business_type: int,
        year: int,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch monthly plant statistics for one year and prepare chart rows."""
        owner = self._coordinator
        fetch_request_id = owner._begin_fetch_request(request_id)
        now = dt_util.now()
        normalized_year = int(year)
        month_count = now.month if normalized_year == now.year else 12
        rows: list[dict[str, Any]] = []
        raw_months: list[dict[str, Any]] = []

        try:
            for month in range(1, month_count + 1):
                if owner._is_fetch_cancelled(fetch_request_id):
                    break
                date_text = f"{normalized_year}-{month:02d}"
                payload = await owner.client.plant_stat_data(
                    plant_id=plant_id,
                    business_type=business_type,
                    date_type=2,
                    date=date_text,
                )
                result = payload.get("result") or {}
                metrics = extract_plant_stat_metrics(
                    result if isinstance(result, dict) else {}
                )
                timestamp = int(
                    datetime(
                        normalized_year,
                        month,
                        1,
                        tzinfo=timezone.utc,
                    ).timestamp()
                    * 1000
                )
                rows.append(
                    {"month": date_text, "timestamp": timestamp, **metrics}
                )
                raw_months.append(
                    {
                        "month": date_text,
                        "code": payload.get("code"),
                        "message": payload.get("message"),
                        "result": result,
                    }
                )
                if owner._is_fetch_cancelled(fetch_request_id):
                    break
            cancelled = owner._is_fetch_cancelled(fetch_request_id)
        finally:
            owner._finish_fetch_request(fetch_request_id)

        available_metric_names = sorted(
            {
                key
                for row in rows
                for key, value in row.items()
                if key not in {"month", "timestamp"}
                and isinstance(value, (int, float))
            }
        )
        return {
            "ok": True,
            "plant_id": plant_id,
            "business_type": business_type,
            "year": normalized_year,
            "month_count": month_count,
            "api_calls_made": len(raw_months),
            "available_metric_names": available_metric_names,
            "rows": rows,
            "raw_months": raw_months,
            "cancelled": cancelled,
            "request_id": fetch_request_id,
        }

    async def async_fetch_plant_month_statistics(
        self,
        *,
        plant_id: str,
        business_type: int,
        year: int,
        month: int,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch daily plant statistics for one month and prepare chart rows."""
        owner = self._coordinator
        fetch_request_id = owner._begin_fetch_request(request_id)
        normalized_year = int(year)
        normalized_month = int(month)
        date_text = f"{normalized_year}-{normalized_month:02d}"
        if owner._is_fetch_cancelled(fetch_request_id):
            owner._finish_fetch_request(fetch_request_id)
            return {
                "ok": True,
                "plant_id": plant_id,
                "business_type": business_type,
                "year": normalized_year,
                "month": normalized_month,
                "date": date_text,
                "day_count": 0,
                "api_calls_made": 0,
                "available_metric_names": [],
                "rows": [],
                "raw_month": {},
                "cancelled": True,
                "request_id": fetch_request_id,
            }
        try:
            payload = await owner.client.plant_stat_data(
                plant_id=plant_id,
                business_type=business_type,
                date_type=2,
                date=date_text,
            )
            cancelled = owner._is_fetch_cancelled(fetch_request_id)
        finally:
            owner._finish_fetch_request(fetch_request_id)
        result = payload.get("result") or {}
        records = (
            result.get("plantEnergyStatDataList")
            if isinstance(result, Mapping)
            else None
        ) or []
        rows: list[dict[str, Any]] = []

        for index, row in enumerate(records, start=1):
            if not isinstance(row, Mapping):
                continue
            metrics = extract_plant_stat_row_metrics(dict(row))
            if not metrics:
                continue
            row_date, timestamp = self.plant_stat_daily_timestamp(
                row,
                year=normalized_year,
                month=normalized_month,
                fallback_day=index,
            )
            rows.append(
                {
                    "date": row_date,
                    "day": datetime.fromtimestamp(
                        timestamp / 1000,
                        tz=timezone.utc,
                    ).day,
                    "timestamp": timestamp,
                    **metrics,
                }
            )

        rows.sort(key=lambda item: int(item["timestamp"]))
        available_metric_names = sorted(
            {
                key
                for row in rows
                for key, value in row.items()
                if key not in {"date", "day", "timestamp"}
                and isinstance(value, (int, float))
            }
        )
        return {
            "ok": True,
            "plant_id": plant_id,
            "business_type": business_type,
            "year": normalized_year,
            "month": normalized_month,
            "date": date_text,
            "day_count": len(rows),
            "api_calls_made": 1,
            "available_metric_names": available_metric_names,
            "rows": rows,
            "raw_month": {
                "month": date_text,
                "code": payload.get("code"),
                "message": payload.get("message"),
                "result": result,
            },
            "cancelled": cancelled,
            "request_id": fetch_request_id,
        }

    @staticmethod
    def plant_stat_daily_timestamp(
        row: Mapping[str, Any],
        *,
        year: int,
        month: int,
        fallback_day: int,
    ) -> tuple[str, int]:
        """Return a stable UTC midnight timestamp for a plant statistics row."""
        for key in ("date", "statDate", "dataTime", "time", "plantLocalTime"):
            raw = row.get(key)
            if raw is None:
                continue
            if isinstance(raw, (int, float)) and math.isfinite(float(raw)):
                timestamp = int(raw if raw > 9999999999 else raw * 1000)
                date_text = datetime.fromtimestamp(
                    timestamp / 1000,
                    tz=timezone.utc,
                ).date().isoformat()
                return date_text, timestamp
            text = str(raw).strip()
            if not text:
                continue
            for fmt in (
                "%Y-%m-%d",
                "%Y/%m/%d",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
            ):
                try:
                    parsed = datetime.strptime(text[:19], fmt).replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    continue
                midnight = datetime(
                    parsed.year,
                    parsed.month,
                    parsed.day,
                    tzinfo=timezone.utc,
                )
                return midnight.date().isoformat(), int(midnight.timestamp() * 1000)
            if text.isdigit():
                fallback_day = int(text)
                break

        safe_day = max(1, min(31, int(fallback_day)))
        try:
            midnight = datetime(year, month, safe_day, tzinfo=timezone.utc)
        except ValueError:
            midnight = datetime(year, month, 1, tzinfo=timezone.utc)
        return midnight.date().isoformat(), int(midnight.timestamp() * 1000)
