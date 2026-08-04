"""Independent alarm polling and on-demand alarm viewer support."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..api import serialize_api_error
from ..const import BUSINESS_TYPES

if TYPE_CHECKING:
    from ..coordinator import SolaxDeveloperCoordinator


RAW_ENDPOINT_ALARM_PAGE_ALARM_INFO = "alarm_page_alarm_info"


class AlarmManager(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Poll active alarms independently and serve manual Alarm Viewer reads."""

    def __init__(
        self,
        coordinator: SolaxDeveloperCoordinator,
        *,
        scan_interval: int,
    ) -> None:
        self._owner = coordinator
        self.scan_interval = int(scan_interval)
        self.last_update_attempt: datetime | None = None
        self.last_successful_update: datetime | None = None
        self.last_error: str | None = None
        self.last_errors: list[dict[str, Any]] = []
        self.last_api_calls = 0
        self.raw_cycle: dict[str, list[dict[str, Any]]] = {}
        config_entry = cast(
            ConfigEntry[Any] | None,
            getattr(coordinator, "config_entry", None),
        )
        super().__init__(
            coordinator.hass,
            logger=logging.getLogger(__name__),
            name="SolaX Developer API alarms",
            update_interval=timedelta(seconds=self.scan_interval),
            config_entry=config_entry,
        )
        self.data: dict[str, dict[str, Any]] = {}

    @property
    def estimated_calls_per_minute(self) -> float:
        """Return reserved background calls used by Live View budgeting."""
        plants = dict((self._owner.data or {}).get("plants") or {})
        calls_per_poll = max(self.last_api_calls, len(plants), 1)
        return calls_per_poll * 60 / self.scan_interval

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch active alarms, preserving last-good values per failed plant."""
        self.last_update_attempt = dt_util.utcnow()
        owner = self._owner
        plants = dict((owner.data or {}).get("plants") or {})
        current = {
            plant_id: dict(value)
            for plant_id, value in dict((owner.data or {}).get("alarms") or {}).items()
            if plant_id in plants and isinstance(value, Mapping)
        }
        raw_cycle = owner._new_raw_api_response_snapshot()
        refreshed, errors, api_calls = await self._refresh_active_alarms(
            plants,
            raw_cycle=raw_cycle,
        )
        self.raw_cycle = raw_cycle
        self.last_api_calls = api_calls
        self.last_errors = [
            {"context": context, **serialize_api_error(error)}
            for context, error in errors
        ]
        self.last_error = (
            "; ".join(
                f"{item['context']}: {item.get('message') or item.get('classification')}"
                for item in self.last_errors
            )
            if self.last_errors
            else None
        )

        merged = {
            plant_id: current[plant_id]
            for plant_id in plants
            if plant_id in current
        }
        merged.update(refreshed)
        if errors and not refreshed and plants:
            raise UpdateFailed(self.last_error or "Alarm refresh failed")

        self.last_successful_update = dt_util.utcnow()
        return merged

    async def _refresh_active_alarms(
        self,
        plants: dict[str, dict[str, Any]],
        *,
        raw_cycle: dict[str, list[dict[str, Any]]],
    ) -> tuple[
        dict[str, dict[str, Any]],
        list[tuple[str, Exception]],
        int,
    ]:
        """Fetch the first active-alarm page for every current plant."""
        owner = self._owner
        alarms: dict[str, dict[str, Any]] = {}
        errors: list[tuple[str, Exception]] = []
        api_calls = 0
        for plant_id, plant in plants.items():
            business_type = int(plant.get("businessType") or 1)
            request = {
                "plantId": plant_id,
                "businessType": business_type,
                "alarmState": 1,
                "pageNo": 1,
            }
            try:
                api_calls += 1
                payload = await owner.client.page_alarm_info(
                    plant_id=plant_id,
                    business_type=business_type,
                    alarm_state=1,
                    page_no=1,
                )
                owner._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_ALARM_PAGE_ALARM_INFO,
                    request=request,
                    response=payload,
                )
                result = payload.get("result") or {}
                records = result.get("records") or []
                alarms[plant_id] = {
                    "total": int(result.get("total") or len(records)),
                    "records": records,
                }
            except Exception as err:  # noqa: BLE001
                owner._append_raw_snapshot(
                    raw_cycle,
                    endpoint=RAW_ENDPOINT_ALARM_PAGE_ALARM_INFO,
                    request=request,
                    error=err,
                )
                errors.append((f"alarms:{plant_id}", err))
        return alarms, errors, api_calls

    async def async_fetch_alarm_information(
        self,
        *,
        plant_id: str | None = None,
        business_type: int | None = None,
        alarm_state: str | int = "all",
        device_sn: str | None = None,
        max_pages: int = 20,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch paged plant alarm information on demand for the viewer card."""
        owner = self._owner
        fetch_request_id = owner._begin_fetch_request(request_id)
        targets = owner.list_alarm_targets()
        plants = targets["plants"]
        target_plants: list[dict[str, Any]] = []
        normalized_plant_id = str(plant_id or "").strip()
        normalized_device_sn = str(device_sn or "").strip()

        if normalized_plant_id:
            target_plants = [
                dict(plant)
                for plant in plants
                if str(plant["plant_id"]) == normalized_plant_id
            ]
            if not target_plants and business_type in BUSINESS_TYPES:
                target_plants.append(
                    {
                        "plant_id": normalized_plant_id,
                        "plant_name": "",
                        "business_type": int(business_type),
                        "label": normalized_plant_id,
                    }
                )
        elif normalized_device_sn:
            device_plants = {
                str(device["plant_id"])
                for device in targets["devices"]
                if str(device["device_sn"]) == normalized_device_sn
            }
            target_plants = [
                dict(plant)
                for plant in plants
                if str(plant["plant_id"]) in device_plants
            ]
        else:
            target_plants = [dict(plant) for plant in plants]

        if not target_plants:
            owner._finish_fetch_request(fetch_request_id)
            return {
                "ok": True,
                "records": [],
                "count": 0,
                "api_calls_made": 0,
                "targets": [],
                "available_fields": [],
                "state_counts": {"ongoing": 0, "closed": 0},
                "page_summaries": [],
                "cancelled": False,
                "request_id": fetch_request_id,
            }

        states = self.normalize_alarm_states(alarm_state)
        bounded_max_pages = max(1, min(int(max_pages or 20), 100))
        records: list[dict[str, Any]] = []
        page_summaries: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        api_calls_made = 0

        def _response(cancelled: bool = False) -> dict[str, Any]:
            records.sort(
                key=lambda item: (
                    owner._coerce_int(item.get("alarmState")),
                    str(item.get("alarmStartTime") or ""),
                    str(item.get("deviceSn") or ""),
                    str(item.get("alarmName") or ""),
                ),
                reverse=True,
            )
            available_fields = sorted({key for row in records for key in row})
            state_counts = {
                "ongoing": sum(
                    1
                    for row in records
                    if owner._coerce_int(row.get("alarmState")) == 1
                ),
                "closed": sum(
                    1
                    for row in records
                    if owner._coerce_int(row.get("alarmState")) == 0
                ),
            }
            return {
                "ok": True,
                "records": records,
                "count": len(records),
                "api_calls_made": api_calls_made,
                "targets": target_plants,
                "available_fields": available_fields,
                "state_counts": state_counts,
                "page_summaries": page_summaries,
                "cancelled": cancelled,
                "request_id": fetch_request_id,
            }

        try:
            for plant in target_plants:
                plant_id_text = str(plant["plant_id"])
                plant_business_type = int(
                    plant.get("business_type") or business_type or 1
                )
                for state in states:
                    page_no = 1
                    while page_no <= bounded_max_pages:
                        if owner._is_fetch_cancelled(fetch_request_id):
                            return _response(cancelled=True)
                        payload = await owner.client.page_alarm_info(
                            plant_id=plant_id_text,
                            business_type=plant_business_type,
                            alarm_state=state,
                            page_no=page_no,
                            device_sn=normalized_device_sn or None,
                        )
                        api_calls_made += 1
                        if owner._is_fetch_cancelled(fetch_request_id):
                            return _response(cancelled=True)
                        result = payload.get("result") or {}
                        if not isinstance(result, Mapping):
                            result = {}
                        raw_records = result.get("records") or []
                        if not isinstance(raw_records, list):
                            raw_records = []

                        page_summaries.append(
                            {
                                "plant_id": plant_id_text,
                                "business_type": plant_business_type,
                                "alarm_state": state,
                                "page_no": page_no,
                                "code": payload.get("code"),
                                "message": payload.get("message"),
                                "total": result.get("total"),
                                "pages": result.get("pages"),
                                "current": result.get("current"),
                                "size": result.get("size"),
                                "record_count": len(raw_records),
                            }
                        )

                        for row in raw_records:
                            if not isinstance(row, Mapping):
                                continue
                            enriched = dict(row)
                            enriched.setdefault(
                                "plantId",
                                result.get("plantId") or plant_id_text,
                            )
                            enriched.setdefault("businessType", plant_business_type)
                            enriched.setdefault("queriedAlarmState", state)
                            if enriched.get("deviceType") is not None:
                                enriched["deviceTypeName"] = owner._device_type_text(
                                    enriched.get("deviceType")
                                )
                            if enriched.get("deviceModel") is not None:
                                enriched["deviceModelName"] = owner._device_model_text(
                                    enriched.get("deviceModel"),
                                    business_type=plant_business_type,
                                    device_type=enriched.get("deviceType"),
                                )
                            dedupe_key = (
                                enriched.get("plantId"),
                                enriched.get("deviceSn"),
                                enriched.get("errorCode"),
                                enriched.get("alarmName"),
                                enriched.get("alarmStartTime"),
                                enriched.get("alarmState"),
                            )
                            if dedupe_key in seen:
                                continue
                            seen.add(dedupe_key)
                            records.append(enriched)

                        pages = owner._coerce_int(result.get("pages")) or 1
                        current = owner._coerce_int(result.get("current")) or page_no
                        if current >= pages or not raw_records:
                            break
                        page_no += 1
            return _response()
        finally:
            owner._finish_fetch_request(fetch_request_id)

    @staticmethod
    def normalize_alarm_states(alarm_state: str | int) -> list[int]:
        """Normalize card alarm-state filters to Developer API values."""
        if isinstance(alarm_state, int):
            return [alarm_state] if alarm_state in (0, 1) else [1, 0]
        normalized = str(alarm_state or "all").strip().casefold()
        if normalized in {"1", "ongoing", "active", "open"}:
            return [1]
        if normalized in {"0", "closed", "cleared", "resolved"}:
            return [0]
        return [1, 0]
