"""Runtime types for the SolaX Developer API integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE

from .api import SolaxDeveloperApiClient
from .coordinator import SolaxDeveloperCoordinator


@dataclass(slots=True)
class SolaxRuntimeData:
    """Non-persisted state owned by a loaded config entry."""

    client: SolaxDeveloperApiClient
    coordinator: SolaxDeveloperCoordinator
    rate_limit_unsub: CALLBACK_TYPE | None = None
    alarm_notification_state: str = "none"


SolaxConfigEntry: TypeAlias = ConfigEntry[SolaxRuntimeData]
