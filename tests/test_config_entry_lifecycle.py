from types import SimpleNamespace

import pytest

from custom_components.solax_developer_api import (
    REPAIR_API_PERMISSION,
    REPAIR_API_RATE_LIMIT,
    _repair_issue_id,
    _update_repairs,
)
from custom_components.solax_developer_api import config_flow
from custom_components.solax_developer_api.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET


def test_config_entry_schema_uses_current_version():
    assert config_flow.SolaxDeveloperFlowHandler.VERSION == 2
    assert "MINOR_VERSION" not in config_flow.SolaxDeveloperFlowHandler.__dict__
    assert "async_step_import" not in config_flow.SolaxDeveloperFlowHandler.__dict__


def test_repairs_create_and_clear_actionable_issues(monkeypatch):
    created = []
    deleted = []
    monkeypatch.setattr(
        "custom_components.solax_developer_api.ir.async_create_issue",
        lambda hass, domain, issue_id, **kwargs: created.append(
            (domain, issue_id, kwargs)
        ),
    )
    monkeypatch.setattr(
        "custom_components.solax_developer_api.ir.async_delete_issue",
        lambda hass, domain, issue_id: deleted.append((domain, issue_id)),
    )
    coordinator = SimpleNamespace(
        rate_limited=True,
        rate_limited_context=["device_realtime"],
        data={
            "last_errors": [
                {"classification": "permission", "context": "plant_stats"}
            ]
        },
    )

    _update_repairs(object(), "entry-1", coordinator)

    created_ids = {item[1] for item in created}
    assert _repair_issue_id("entry-1", REPAIR_API_RATE_LIMIT) in created_ids
    assert _repair_issue_id("entry-1", REPAIR_API_PERMISSION) in created_ids

    created.clear()
    coordinator.rate_limited = False
    coordinator.data = {"last_errors": []}
    _update_repairs(object(), "entry-1", coordinator)

    deleted_ids = {item[1] for item in deleted}
    assert _repair_issue_id("entry-1", REPAIR_API_RATE_LIMIT) in deleted_ids
    assert _repair_issue_id("entry-1", REPAIR_API_PERMISSION) in deleted_ids


@pytest.mark.asyncio
async def test_options_root_is_a_four_page_menu(monkeypatch):
    async def _loaded(hass):
        return None

    monkeypatch.setattr(config_flow, "async_ensure_catalog_loaded", _loaded)
    entry = SimpleNamespace(entry_id="entry-1", data={}, options={})
    handler = config_flow.SolaxDeveloperOptionsFlowHandler(entry)
    handler.hass = SimpleNamespace()
    captured = {}

    def _show_menu(**kwargs):
        captured.update(kwargs)
        return kwargs

    handler.async_show_menu = _show_menu
    result = await handler.async_step_init()

    assert result["step_id"] == "init"
    assert result["menu_options"] == [
        "credentials",
        "polling",
        "manual_devices",
        "advanced",
    ]


@pytest.mark.asyncio
async def test_reauth_updates_credentials_after_strict_validation(monkeypatch):
    async def _loaded(hass):
        return None

    async def _valid(*args, **kwargs):
        return True, None

    monkeypatch.setattr(config_flow, "async_ensure_catalog_loaded", _loaded)
    monkeypatch.setattr(config_flow, "_validate_credentials", _valid)
    entry = SimpleNamespace(
        data={
            CONF_CLIENT_ID: "old-client",
            CONF_CLIENT_SECRET: "old-secret",
            "api_region": "eu",
        }
    )
    handler = object.__new__(config_flow.SolaxDeveloperFlowHandler)
    handler.hass = SimpleNamespace()
    handler._get_reauth_entry = lambda: entry
    captured = {}

    def _update_reload(target, **kwargs):
        captured["entry"] = target
        captured.update(kwargs)
        return kwargs

    handler.async_update_reload_and_abort = _update_reload
    result = await handler.async_step_reauth_confirm(
        {
            CONF_CLIENT_ID: "new-client",
            CONF_CLIENT_SECRET: "new-secret",
            "api_region": "eu",
        }
    )

    assert result["reason"] == "reauth_successful"
    assert captured["data_updates"][CONF_CLIENT_ID] == "new-client"
    assert captured["data_updates"][CONF_CLIENT_SECRET] == "new-secret"
