"""Shared fixtures for real Home Assistant lifecycle tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load this repository's custom integration."""
    yield


@pytest.fixture(autouse=True)
async def _mock_storage_delay_save(
    hass,
    monkeypatch,
) -> AsyncGenerator[None, None]:
    """Keep delayed Store writes from surviving beyond individual tests."""
    scheduled = []
    original = hass.async_create_task

    def _tracked_create_task(coro, *args, **kwargs):
        task = original(coro, *args, **kwargs)
        scheduled.append(task)
        return task

    monkeypatch.setattr(hass, "async_create_task", _tracked_create_task)
    yield
    for task in scheduled:
        if not task.done():
            task.cancel()
