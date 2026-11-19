"""One-command, privacy-safe inverter work-mode diagnostic."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
import re
from time import monotonic
from typing import Any

from .api import SolaxApiError
from .const import CONTROL_SERVICE_DEFINITIONS
from .coordinator import SolaxDeveloperCoordinator
from .inverter_modes import command_for_mode, inverter_family, mode_profiles

# Check promptly, then align later checks with :15 past each UTC minute.
# This covers a possible five-minute device/cloud refresh without assuming
# that status 5 is final. Status 4 is the strongest documented acknowledgement.
EARLY_QUERY_DELAYS_SECONDS = (2, 4, 6, 12, 16)
OBSERVATION_SECONDS = 360
MINUTE_QUERY_SECOND = 15
_PARAM_ERROR_FIELD = re.compile(r"PARAM_ERROR:\s*([A-Za-z][A-Za-z0-9_]*)")


def _seconds_until_minute_query(now: datetime) -> float:
    """Return the delay to the next :15 past the minute."""
    second = now.second + now.microsecond / 1_000_000
    delay = (MINUTE_QUERY_SECOND - second) % 60
    return delay if delay > 0 else 60.0


def _safe_error(error: SolaxApiError) -> dict[str, Any]:
    """Keep useful error codes without exposing an arbitrary server message."""
    match = _PARAM_ERROR_FIELD.search(error.message)
    return {
        "api_code": error.code,
        "classification": error.classification,
        "parameter_field": match.group(1) if match else None,
    }


def _response_sample(
    coordinator: SolaxDeveloperCoordinator,
    response: Mapping[str, Any],
    serial: str,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Project one response without serial-keyed records or opaque IDs."""
    summary = coordinator._control_response_status_summary(dict(response))
    target = coordinator._target_control_status_summary(summary, serial)
    status = next(iter(target["device_statuses"].values()), None)
    echoed_id = response.get("requestId")
    return {
        "api_code": coordinator._coerce_int(response.get("code")),
        "result_shape": coordinator._control_result_shape(response.get("result")),
        "target_present": status is not None,
        "status": status["status"] if status else None,
        "status_name": status["status_name"] if status else None,
        "request_id_echo_match": (
            None if request_id is None or echoed_id is None
            else str(echoed_id).strip() == request_id
        ),
    }


async def run_inverter_mode_diagnostic(
    coordinator: SolaxDeveloperCoordinator,
    *,
    serial: str,
    mode: str,
    profile_id: str,
) -> dict[str, Any]:
    """Send one saved profile, then observe its request even after failure."""
    if not coordinator.inverter_mode_controls_enabled:
        raise ValueError("inverter_mode_controls_disabled")
    if mode == "manual":
        raise ValueError("manual_mode_diagnostic_not_supported")
    device = ((coordinator.data or {}).get("devices") or {}).get(serial)
    if not isinstance(device, Mapping):
        raise ValueError("inverter_mode_target_unverified")
    service, payload = command_for_mode(
        options=coordinator.inverter_mode_options,
        device=device,
        serial=serial,
        action=mode,
        profile_id=profile_id,
    )
    devices = (coordinator.data or {}).get("devices") or {}
    inverter_serials = sorted(
        key for key, candidate in devices.items()
        if isinstance(candidate, Mapping) and inverter_family(candidate) is not None
    )
    profile_ids = sorted(mode_profiles(coordinator.inverter_mode_options, serial, mode))
    started = monotonic()
    report: dict[str, Any] = {
        "report_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "inverter": f"Inverter {inverter_serials.index(serial) + 1}",
        "profile": f"Profile {profile_ids.index(profile_id) + 1}",
        "family": inverter_family(device),
        "service": service,
        "request_path": CONTROL_SERVICE_DEFINITIONS[service]["endpoint"],
        "sent_parameters": {key: value for key, value in payload.items() if key != "snList"},
        "command_count": 1,
        "query_samples": [],
    }
    try:
        response = await coordinator.client.execute_control(
            path=report["request_path"], payload=payload
        )
    except SolaxApiError as error:
        report["initial"] = _safe_error(error)
        report["query_skipped_reason"] = "command_request_rejected"
        return report

    report["initial"] = _response_sample(coordinator, response, serial)
    request_id = str(response.get("requestId") or "").strip()
    report["request_id_present"] = bool(request_id)
    if not request_id:
        report["query_skipped_reason"] = "no_request_id"
        return report

    if report["initial"]["status"] == 4:
        report["stop_reason"] = "device_acknowledged"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        return report

    async def query_once() -> bool:
        sample: dict[str, Any] = {
            "elapsed_seconds": round(monotonic() - started, 1),
        }
        query_request_id_match: bool | None = None

        def audit_request_id(outgoing_request_id: str) -> None:
            nonlocal query_request_id_match
            query_request_id_match = outgoing_request_id == request_id

        try:
            queried = await coordinator.client.query_request_result(
                request_id=request_id,
                audit_request_id=audit_request_id,
            )
        except SolaxApiError as error:
            sample.update(_safe_error(error))
        else:
            sample.update(_response_sample(coordinator, queried, serial, request_id=request_id))
        sample["query_request_id_match"] = query_request_id_match
        report["query_samples"].append(sample)
        return sample.get("target_present") is True and sample.get("status") == 4

    for early_delay in EARLY_QUERY_DELAYS_SECONDS:
        if monotonic() - started + early_delay > OBSERVATION_SECONDS:
            break
        await asyncio.sleep(early_delay)
        if await query_once():
            report["stop_reason"] = "device_acknowledged"
            break
    else:
        while monotonic() - started < OBSERVATION_SECONDS:
            aligned_delay = _seconds_until_minute_query(datetime.now(timezone.utc))
            await asyncio.sleep(aligned_delay)
            if await query_once():
                report["stop_reason"] = "device_acknowledged"
                break

    report.setdefault("stop_reason", "observation_window_ended")

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report
