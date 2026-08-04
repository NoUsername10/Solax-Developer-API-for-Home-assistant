"""Service handlers for History, Alarm Viewer, and Live View features."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import SolaxDeveloperCoordinator
    from .runtime import SolaxRuntimeData


class FeatureServiceHandlers:
    """Adapt feature services to the existing coordinator facade."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        loaded_runtime: Callable[[HomeAssistant, str], SolaxRuntimeData | None],
        resolve_coordinator: Callable[
            [HomeAssistant, ServiceCall], tuple[str, SolaxDeveloperCoordinator]
        ],
        translated_error: Callable[..., Exception],
    ) -> None:
        self._hass = hass
        self._loaded_runtime = loaded_runtime
        self._resolve_coordinator = resolve_coordinator
        self._translated_error = translated_error

    async def async_list_history_devices(self, call: ServiceCall) -> dict[str, Any]:
        """List loaded devices supported by the history endpoint."""
        explicit_entry_id = str(call.data.get("entry_id", "")).strip()
        devices: list[dict[str, Any]] = []
        entry_ids: list[str] = []
        for entry in self._hass.config_entries.async_entries(DOMAIN):
            if explicit_entry_id and entry.entry_id != explicit_entry_id:
                continue
            runtime = self._loaded_runtime(self._hass, entry.entry_id)
            if runtime is None:
                continue
            devices.extend(
                {**device, "entry_id": entry.entry_id}
                for device in runtime.coordinator.list_history_devices()
            )
            entry_ids.append(entry.entry_id)
        return {
            "ok": True,
            "entry_id": explicit_entry_id
            or (entry_ids[0] if len(entry_ids) == 1 else None),
            "entries": entry_ids,
            "count": len(devices),
            "devices": devices,
        }

    async def async_list_plant_statistics_targets(
        self,
        call: ServiceCall,
    ) -> dict[str, Any]:
        """List loaded plants supported by plant statistics."""
        explicit_entry_id = str(call.data.get("entry_id", "")).strip()
        plants: list[dict[str, Any]] = []
        entry_ids: list[str] = []
        for entry in self._hass.config_entries.async_entries(DOMAIN):
            if explicit_entry_id and entry.entry_id != explicit_entry_id:
                continue
            runtime = self._loaded_runtime(self._hass, entry.entry_id)
            if runtime is None:
                continue
            plants.extend(
                {**plant, "entry_id": entry.entry_id}
                for plant in runtime.coordinator.list_plant_statistics_targets()
            )
            entry_ids.append(entry.entry_id)
        return {
            "ok": True,
            "entry_id": explicit_entry_id
            or (entry_ids[0] if len(entry_ids) == 1 else None),
            "entries": entry_ids,
            "count": len(plants),
            "plants": plants,
        }

    async def async_list_alarm_targets(self, call: ServiceCall) -> dict[str, Any]:
        """List loaded alarm plants and devices."""
        explicit_entry_id = str(call.data.get("entry_id", "")).strip()
        plants: list[dict[str, Any]] = []
        devices: list[dict[str, Any]] = []
        entry_ids: list[str] = []
        for entry in self._hass.config_entries.async_entries(DOMAIN):
            if explicit_entry_id and entry.entry_id != explicit_entry_id:
                continue
            runtime = self._loaded_runtime(self._hass, entry.entry_id)
            if runtime is None:
                continue
            targets = runtime.coordinator.list_alarm_targets()
            plants.extend(
                {**plant, "entry_id": entry.entry_id}
                for plant in targets["plants"]
            )
            devices.extend(
                {**device, "entry_id": entry.entry_id}
                for device in targets["devices"]
            )
            entry_ids.append(entry.entry_id)
        return {
            "ok": True,
            "entry_id": explicit_entry_id
            or (entry_ids[0] if len(entry_ids) == 1 else None),
            "entries": entry_ids,
            "plant_count": len(plants),
            "device_count": len(devices),
            "plants": plants,
            "devices": devices,
        }

    async def async_fetch_history(self, call: ServiceCall) -> dict[str, Any]:
        """Validate and dispatch an on-demand device-history request."""
        _entry_id, coordinator = self._resolve_coordinator(self._hass, call)
        start_time = int(call.data["start_time"])
        end_time = int(call.data["end_time"])
        if end_time <= start_time:
            raise self._translated_error("history_end_before_start")
        return await coordinator.async_fetch_device_history(
            sn_list=call.data["sn_list"],
            device_type=int(call.data["device_type"]),
            business_type=int(call.data["business_type"]),
            start_time=start_time,
            end_time=end_time,
            time_interval=int(call.data["time_interval"]),
            request_sn_type=(
                int(call.data["request_sn_type"])
                if call.data.get("request_sn_type") is not None
                else None
            ),
            request_id=str(call.data.get("request_id") or "").strip() or None,
        )

    async def async_fetch_plant_year_statistics(
        self,
        call: ServiceCall,
    ) -> dict[str, Any]:
        """Validate and dispatch card-driven yearly plant statistics."""
        _entry_id, coordinator = self._resolve_coordinator(self._hass, call)
        year = int(call.data["year"])
        current_year = dt_util.now().year
        if year < 2000 or year > current_year:
            raise self._translated_error(
                "plant_year_invalid",
                placeholders={"min_year": 2000, "max_year": current_year},
            )
        return await coordinator.async_fetch_plant_year_statistics(
            plant_id=str(call.data["plant_id"]).strip(),
            business_type=int(call.data["business_type"]),
            year=year,
            request_id=str(call.data.get("request_id") or "").strip() or None,
        )

    async def async_fetch_plant_month_statistics(
        self,
        call: ServiceCall,
    ) -> dict[str, Any]:
        """Validate and dispatch card-driven monthly plant statistics."""
        _entry_id, coordinator = self._resolve_coordinator(self._hass, call)
        year = int(call.data["year"])
        month = int(call.data["month"])
        current = dt_util.now()
        if year < 2000 or year > current.year:
            raise self._translated_error(
                "plant_year_invalid",
                placeholders={"min_year": 2000, "max_year": current.year},
            )
        max_month = current.month if year == current.year else 12
        if month < 1 or month > max_month:
            raise self._translated_error(
                "plant_month_invalid",
                placeholders={"min_month": 1, "max_month": max_month},
            )
        return await coordinator.async_fetch_plant_month_statistics(
            plant_id=str(call.data["plant_id"]).strip(),
            business_type=int(call.data["business_type"]),
            year=year,
            month=month,
            request_id=str(call.data.get("request_id") or "").strip() or None,
        )

    async def async_fetch_alarm_information(
        self,
        call: ServiceCall,
    ) -> dict[str, Any]:
        """Dispatch a manual Alarm Viewer fetch."""
        _entry_id, coordinator = self._resolve_coordinator(self._hass, call)
        return await coordinator.async_fetch_alarm_information(
            plant_id=str(call.data.get("plant_id") or "").strip() or None,
            business_type=(
                int(call.data["business_type"])
                if call.data.get("business_type") is not None
                else None
            ),
            alarm_state=call.data.get("alarm_state", "all"),
            device_sn=str(call.data.get("device_sn") or "").strip() or None,
            max_pages=int(call.data.get("max_pages") or 20),
            request_id=str(call.data.get("request_id") or "").strip() or None,
        )

    async def async_cancel_fetch(self, call: ServiceCall) -> dict[str, Any]:
        """Cancel one cooperative card-driven request."""
        request_id = str(call.data["request_id"]).strip()
        explicit_entry_id = str(call.data.get("entry_id") or "").strip()
        if explicit_entry_id:
            entry_id, coordinator = self._resolve_coordinator(self._hass, call)
            result = coordinator.cancel_fetch(request_id)
            return {"ok": result["ok"], "entries": {entry_id: result}}
        results: dict[str, Any] = {}
        for entry in self._hass.config_entries.async_entries(DOMAIN):
            runtime = self._loaded_runtime(self._hass, entry.entry_id)
            if runtime is None:
                continue
            results[entry.entry_id] = runtime.coordinator.cancel_fetch(request_id)
        return {
            "ok": bool(results),
            "request_id": request_id,
            "entries": results,
        }

    async def async_start_live_view(self, call: ServiceCall) -> dict[str, Any]:
        """Start Live View through the coordinator facade."""
        _entry_id, coordinator = self._resolve_coordinator(self._hass, call)
        return await coordinator.async_start_live_view(
            duration_seconds=(
                int(call.data["duration_seconds"])
                if call.data.get("duration_seconds") is not None
                else None
            ),
            interval_seconds=(
                int(call.data["interval_seconds"])
                if call.data.get("interval_seconds") is not None
                else None
            ),
        )

    async def async_stop_live_view(self, call: ServiceCall) -> dict[str, Any]:
        """Stop Live View through the coordinator facade."""
        _entry_id, coordinator = self._resolve_coordinator(self._hass, call)
        return await coordinator.async_stop_live_view()
