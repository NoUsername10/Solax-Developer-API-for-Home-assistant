"""Live View timing and API-budget policy."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import math
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from ..const import (
    API_RATE_LIMIT_PER_MINUTE,
    DEFAULT_ALARM_SCAN_INTERVAL,
    MAX_LIVE_VIEW_INTERVAL,
    MAX_LIVE_VIEW_DURATION,
    MAX_SN_PER_REQUEST,
    MIN_LIVE_VIEW_DURATION,
    MIN_LIVE_VIEW_INTERVAL,
)

if TYPE_CHECKING:
    from ..coordinator import SolaxDeveloperCoordinator

_LOGGER = logging.getLogger(__name__)


class LiveViewManager:
    """Own Live View state, profile selection, and call-budget calculations."""

    def __init__(self, coordinator: SolaxDeveloperCoordinator) -> None:
        self._owner = coordinator

    def is_night_mode(self) -> bool:
        """Return whether the configured night period is active."""
        owner = self._owner
        hour = dt_util.now().hour
        start = owner._night_start_hour
        end = owner._night_end_hour
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def expire_if_needed(self) -> None:
        """Expire a completed Live View period."""
        owner = self._owner
        if owner._live_view_until is not None and dt_util.utcnow() >= owner._live_view_until:
            owner._live_view_until = None

    @property
    def active(self) -> bool:
        """Return whether Live View is currently active."""
        self.expire_if_needed()
        return self._owner._live_view_until is not None

    @property
    def remaining_seconds(self) -> int:
        """Return whole seconds remaining in the current Live View period."""
        if not self.active:
            return 0
        live_view_until = self._owner._live_view_until
        if live_view_until is None:
            return 0
        remaining = int((live_view_until - dt_util.utcnow()).total_seconds())
        return max(0, remaining)

    @property
    def until(self) -> datetime | None:
        """Return the current Live View expiry timestamp."""
        self.expire_if_needed()
        return self._owner._live_view_until

    @staticmethod
    def estimate_cycle_calls(
        plants: dict[str, dict[str, Any]],
        inventory_by_type: dict[str, list[str]],
    ) -> int:
        """Estimate realtime API requests in one Live View cycle."""
        plant_calls = len(plants)
        device_calls = sum(
            math.ceil(len(sn_list) / MAX_SN_PER_REQUEST)
            for sn_list in inventory_by_type.values()
            if sn_list
        )
        return max(1, plant_calls + device_calls)

    def alarm_reserved_calls_per_minute(self) -> float:
        """Reserve budget for independent active-alarm polling."""
        owner = self._owner
        manager = getattr(owner, "_alarm_manager", None)
        if manager is not None:
            return float(manager.estimated_calls_per_minute)
        interval = max(
            1,
            int(getattr(owner, "_alarm_scan_interval", DEFAULT_ALARM_SCAN_INTERVAL)),
        )
        plants = dict((getattr(owner, "data", {}) or {}).get("plants") or {})
        return max(1, len(plants)) * 60 / interval

    def compute_safe_interval(
        self,
        plants: dict[str, dict[str, Any]],
        inventory_by_type: dict[str, list[str]],
    ) -> int:
        """Compute a safe effective interval after background call reservation."""
        owner = self._owner
        owner._estimated_live_calls_per_cycle = self.estimate_cycle_calls(
            plants,
            inventory_by_type,
        )
        safe_budget = max(
            1,
            min(owner._live_view_call_budget_per_minute, API_RATE_LIMIT_PER_MINUTE),
        )
        owner._alarm_reserved_calls_per_minute = self.alarm_reserved_calls_per_minute()
        available_budget = max(
            1,
            math.floor(safe_budget - owner._alarm_reserved_calls_per_minute),
        )
        minimum_interval = math.ceil(
            owner._estimated_live_calls_per_cycle * 60 / available_budget
        )
        target = max(
            owner._live_view_requested_interval,
            minimum_interval,
            MIN_LIVE_VIEW_INTERVAL,
        )
        if owner.rate_limited:
            target = max(target, owner._base_scan_interval)
        owner._live_view_budget_adjusted = (
            target > owner._live_view_requested_interval
        )
        return target

    def apply_poll_profile(
        self,
        plants: dict[str, dict[str, Any]],
        inventory_by_type: dict[str, list[str]],
    ) -> None:
        """Apply standard, night, or Live View polling to the facade coordinator."""
        owner = self._owner
        previous_profile = owner._poll_profile
        previous_interval = owner._effective_scan_interval
        if self.active:
            owner._poll_profile = "live_view"
            owner._effective_scan_interval = self.compute_safe_interval(
                plants,
                inventory_by_type,
            )
        elif self.is_night_mode():
            owner._poll_profile = "night"
            owner._effective_scan_interval = owner._night_scan_interval
            owner._live_view_budget_adjusted = False
        else:
            owner._poll_profile = "standard"
            owner._effective_scan_interval = owner._base_scan_interval
            owner._live_view_budget_adjusted = False

        owner._apply_refresh_backoff_to_interval()
        owner.update_interval = timedelta(seconds=owner._effective_scan_interval)
        if (
            owner._poll_profile != previous_profile
            or owner._effective_scan_interval != previous_interval
        ):
            _LOGGER.info(
                "Polling profile changed from %s (%ss) to %s (%ss)",
                previous_profile,
                previous_interval,
                owner._poll_profile,
                owner._effective_scan_interval,
            )

    async def async_start(
        self,
        *,
        duration_seconds: int | None = None,
        interval_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Start or extend Live View without failing after a refresh error."""
        owner = self._owner
        duration = owner._clamp_int(
            duration_seconds,
            default=owner._live_view_default_duration,
            min_value=MIN_LIVE_VIEW_DURATION,
            max_value=MAX_LIVE_VIEW_DURATION,
        )
        if interval_seconds is not None:
            owner._live_view_requested_interval = owner._clamp_int(
                interval_seconds,
                default=owner._live_view_requested_interval,
                min_value=MIN_LIVE_VIEW_INTERVAL,
                max_value=MAX_LIVE_VIEW_INTERVAL,
            )
        owner._live_view_until = dt_util.utcnow() + timedelta(seconds=duration)
        plants = dict((owner.data or {}).get("plants") or {})
        inventory = dict((owner.data or {}).get("inventory_by_type") or {})
        self.apply_poll_profile(plants, inventory)
        owner._refresh_meta_state()
        owner.async_set_updated_data(dict(owner.data))
        refresh_attempt_success = True
        refresh_error: str | None = None
        try:
            await owner.async_request_refresh()
        except Exception as err:  # noqa: BLE001
            refresh_attempt_success = False
            refresh_error = str(err)
        return {
            "ok": True,
            "live_view_active": self.active,
            "live_view_until": (
                owner._live_view_until.isoformat()
                if owner._live_view_until
                else None
            ),
            "effective_scan_interval": owner._effective_scan_interval,
            "live_view_target_interval": owner._live_view_requested_interval,
            "live_view_budget_adjusted": owner._live_view_budget_adjusted,
            "live_view_call_budget_per_minute": owner._live_view_call_budget_per_minute,
            "live_view_estimated_calls_per_cycle": owner._estimated_live_calls_per_cycle,
            "alarm_reserved_calls_per_minute": owner._alarm_reserved_calls_per_minute,
            "refresh_backoff_seconds": owner._refresh_backoff_seconds,
            "poll_profile": owner._poll_profile,
            "refresh_attempt_success": refresh_attempt_success,
            "refresh_error": refresh_error,
        }

    async def async_stop(self) -> dict[str, Any]:
        """Stop Live View and restore the normal dynamic profile."""
        owner = self._owner
        owner._live_view_until = None
        plants = dict((owner.data or {}).get("plants") or {})
        inventory = dict((owner.data or {}).get("inventory_by_type") or {})
        self.apply_poll_profile(plants, inventory)
        owner._refresh_meta_state()
        owner.async_set_updated_data(dict(owner.data))
        return {
            "ok": True,
            "live_view_active": False,
            "effective_scan_interval": owner._effective_scan_interval,
            "live_view_target_interval": owner._live_view_requested_interval,
            "live_view_budget_adjusted": owner._live_view_budget_adjusted,
            "live_view_call_budget_per_minute": owner._live_view_call_budget_per_minute,
            "live_view_estimated_calls_per_cycle": owner._estimated_live_calls_per_cycle,
            "alarm_reserved_calls_per_minute": owner._alarm_reserved_calls_per_minute,
            "refresh_backoff_seconds": owner._refresh_backoff_seconds,
            "poll_profile": owner._poll_profile,
        }
