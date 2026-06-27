"""Shared plant statistics helpers for SolaX Developer API."""

from __future__ import annotations

from typing import Any

PLANT_STAT_METRICS: tuple[str, ...] = (
    "pvGeneration",
    "inverterACOutputEnergy",
    "exportEnergy",
    "importEnergy",
    "loadConsumption",
    "batteryCharged",
    "batteryDischarged",
    "earnings",
)


def extract_plant_stat_row_metrics(stat_row: dict[str, Any] | None) -> dict[str, float]:
    """Extract known plant statistic metrics from one Developer API stat row."""
    stat_row = stat_row or {}
    metrics: dict[str, float] = {}
    for key in PLANT_STAT_METRICS:
        value = stat_row.get(key)
        if value is None:
            continue
        try:
            metrics[key] = float(value)
        except (TypeError, ValueError):
            continue
    return metrics


def extract_plant_stat_metrics(stat_payload: dict[str, Any] | None) -> dict[str, float]:
    """Aggregate known plant statistic metrics from a Developer API stat payload."""
    stat_payload = stat_payload or {}
    records = stat_payload.get("plantEnergyStatDataList") or []
    metrics = {key: 0.0 for key in PLANT_STAT_METRICS}
    for row in records:
        if not isinstance(row, dict):
            continue
        for key, value in extract_plant_stat_row_metrics(row).items():
            metrics[key] += value
    return metrics
