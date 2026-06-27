from datetime import datetime
from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ServiceValidationError

import custom_components.solax_developer_api as integration
from custom_components.solax_developer_api import (
    _async_register_frontend_assets,
    _coordinator_for_entry,
    _loaded_runtime_for_entry,
    _mask_log_secret,
    _mask_log_serial,
    _normalize_log_key,
    _rate_limit_notification_id,
    _rate_limit_notifications_enabled,
    _resolve_coordinator_for_service,
    _sanitize_dry_run_payload_for_log,
    _translated_service_error,
    _update_rate_limit_notification,
    async_migrate_entry,
    async_remove_config_entry_device,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.solax_developer_api.const import (
    DOMAIN,
    PLATFORMS,
    RUNTIME_RELOAD_STATE,
)
from custom_components.solax_developer_api.runtime import SolaxRuntimeData


class _Config:
    language = "en"


class _Services:
    def __init__(self):
        self.items = {}
        self.removed = []

    def has_service(self, domain, name):
        return (domain, name) in self.items

    def async_register(self, domain, name, handler, **kwargs):
        self.items[(domain, name)] = (handler, kwargs)

    def async_remove(self, domain, name):
        self.removed.append((domain, name))
        self.items.pop((domain, name), None)

    def handler(self, name):
        return self.items[(DOMAIN, name)][0]


class _ConfigEntries:
    def __init__(self, entries=None):
        self.entries = list(entries or [])
        self.updates = []
        self.forwarded = []
        self.unload_result = True

    def async_entries(self, domain=None):
        return list(self.entries)

    def async_get_entry(self, entry_id):
        return next(
            (entry for entry in self.entries if entry.entry_id == entry_id),
            None,
        )

    def async_update_entry(self, entry, **kwargs):
        self.updates.append((entry, kwargs))
        for key in ("data", "options", "version", "title"):
            if key in kwargs:
                setattr(entry, key, kwargs[key])

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry, platforms))

    async def async_unload_platforms(self, entry, platforms):
        return self.unload_result


class _Http:
    def __init__(self):
        self.paths = []
        self.fail = False

    async def async_register_static_paths(self, paths):
        if self.fail:
            raise RuntimeError("frontend failed")
        self.paths.extend(paths)


class _Bus:
    def __init__(self):
        self.events = []

    def async_fire(self, event, data):
        self.events.append((event, data))


class _Hass:
    def __init__(self, entries=None):
        self.config = _Config()
        self.data = {}
        self.services = _Services()
        self.config_entries = _ConfigEntries(entries)
        self.http = _Http()
        self.bus = _Bus()


class _Coordinator:
    def __init__(self):
        self.rate_limited = False
        self.rate_limited_context = []
        self.data = {"last_errors": []}
        self.has_history_capable_devices = True
        self.has_ci_devices = True
        self.available_control_services = {"set_export_control"}
        self.ev_charger_controls_enabled = False
        self.refreshes = 0
        self.listener = None
        self.executed_ev_controls = []

    async def async_request_refresh(self):
        self.refreshes += 1

    async def async_fetch_device_history(self, **kwargs):
        return {"history": kwargs}

    async def async_fetch_plant_year_statistics(self, **kwargs):
        return {"plant_year": kwargs}

    async def async_fetch_plant_month_statistics(self, **kwargs):
        return {"plant_month": kwargs}

    def list_history_devices(self):
        return [
            {
                "device_sn": "INV",
                "device_type": 1,
                "device_type_name": "Inverter",
                "business_type": 1,
                "source": "inventory",
                "label": "Inverter INV",
            }
        ]

    def list_plant_statistics_targets(self):
        return [
            {
                "plant_id": "P1",
                "plant_name": "Plant 1",
                "business_type": 1,
                "label": "Plant 1",
            }
        ]

    async def async_query_request_result(self, request_id):
        return {"request_id": request_id}

    async def async_query_master_control_device(self, **kwargs):
        return {"master": kwargs}

    async def async_start_live_view(self, **kwargs):
        return {"started": kwargs}

    async def async_stop_live_view(self):
        return {"stopped": True}

    def record_control_dry_run(self, **kwargs):
        return {
            **kwargs,
            "reason": "blocked",
            "timestamp": "2026-06-23T00:00:00+00:00",
        }

    async def async_execute_ev_charger_control(self, **kwargs):
        self.executed_ev_controls.append(kwargs)
        return {
            **kwargs,
            "timestamp": "2026-06-23T00:00:00+00:00",
            "blocked": False,
            "sent": True,
            "accepted": True,
            "request_id": "REQ1",
            "device_statuses": {
                "EVC1": {
                    "status": 3,
                    "status_name": "Command issuance succeeded",
                    "accepted": True,
                }
            },
            "response": {
                "code": 10000,
                "message": "success",
                "requestId": "REQ1",
                "result": {"EVC1": {"status": 3}},
            },
        }

    def async_add_listener(self, listener):
        self.listener = listener
        return lambda: setattr(self, "unsubscribed", True)


def _entry(coordinator=None, *, entry_id="entry-1", state=ConfigEntryState.LOADED):
    entry = SimpleNamespace(
        entry_id=entry_id,
        state=state,
        title="SDS",
        version=2,
        data={
            "client_id": "client",
            "client_secret": "secret",
            "api_region": "eu",
        },
        options={
            "system_name": "SDS",
            "entity_prefix": "sds",
            "scan_interval": 120,
        },
    )
    if coordinator is not None:
        entry.runtime_data = SolaxRuntimeData(
            client=SimpleNamespace(),
            coordinator=coordinator,
        )
    return entry


def _call(**data):
    return SimpleNamespace(data=data)


def test_log_redaction_helpers_cover_all_shapes():
    assert _normalize_log_key(" API-Key ") == "api_key"
    assert _mask_log_secret(None) is None
    assert _mask_log_secret("a") == "*"
    assert _mask_log_secret("abcd") == "a***d"
    assert _mask_log_secret("abcdefghijkl") == "abcd***ijkl"
    assert _mask_log_serial(None) is None
    assert _mask_log_serial("abc") == "***"
    assert _mask_log_serial("abcdef") == "ab***ef"
    assert "***" in _mask_log_serial("TESTSERIAL0001")
    assert _sanitize_dry_run_payload_for_log(
        {
            "Authorization": "bearer abcdefghijk",
            "serial": ("TESTSERIAL0001",),
            "value": 1,
            "plain": "text",
        }
    )["plain"] == "text"


@pytest.mark.asyncio
async def test_frontend_registration_success_repeat_and_failure():
    hass = _Hass()
    await _async_register_frontend_assets(hass)
    assert hass.http.paths
    await _async_register_frontend_assets(hass)
    assert len(hass.http.paths) == 1

    failed = _Hass()
    failed.http.fail = True
    await _async_register_frontend_assets(failed)
    assert "frontend_registered" not in failed.data[RUNTIME_RELOAD_STATE]


def test_runtime_resolution_and_translated_errors():
    coordinator = _Coordinator()
    loaded = _entry(coordinator)
    unloaded = _entry(
        _Coordinator(),
        entry_id="unloaded",
        state=ConfigEntryState.NOT_LOADED,
    )
    hass = _Hass([loaded, unloaded])
    assert _loaded_runtime_for_entry(hass, "entry-1").coordinator is coordinator
    assert _loaded_runtime_for_entry(hass, "missing") is None
    assert _loaded_runtime_for_entry(hass, "unloaded") is None
    assert _coordinator_for_entry(hass, "entry-1") is coordinator
    with pytest.raises(ServiceValidationError):
        _coordinator_for_entry(hass, "missing")
    assert _resolve_coordinator_for_service(hass, _call())[0] == "entry-1"
    assert _resolve_coordinator_for_service(
        hass, _call(entry_id="entry-1")
    )[1] is coordinator
    with pytest.raises(ServiceValidationError):
        _resolve_coordinator_for_service(_Hass(), _call())
    error = _translated_service_error(
        "runtime.errors.control_not_available",
        placeholders={"service": "test"},
    )
    assert error.translation_key == "control_not_available"


def test_rate_limit_preferences_and_notifications(monkeypatch):
    coordinator = _Coordinator()
    entry = _entry(coordinator)
    hass = _Hass([entry])
    created = []
    dismissed = []
    monkeypatch.setattr(
        integration.persistent_notification,
        "async_create",
        lambda *args, **kwargs: created.append((args, kwargs)),
    )
    monkeypatch.setattr(
        integration.persistent_notification,
        "async_dismiss",
        lambda *args, **kwargs: dismissed.append((args, kwargs)),
    )

    assert _rate_limit_notification_id("x").endswith("_x")
    assert _rate_limit_notifications_enabled(hass, "missing") is True
    entry.options["rate_limit_notifications"] = False
    assert _rate_limit_notifications_enabled(hass, entry.entry_id) is False
    _update_rate_limit_notification(hass, entry.entry_id, coordinator)
    assert dismissed

    entry.options["rate_limit_notifications"] = True
    coordinator.rate_limited = False
    _update_rate_limit_notification(hass, entry.entry_id, coordinator)
    coordinator.rate_limited = True
    coordinator.rate_limited_context = []
    _update_rate_limit_notification(hass, entry.entry_id, coordinator)
    assert created


@pytest.mark.asyncio
async def test_domain_services_all_read_and_control_paths(monkeypatch):
    async def _loaded(hass):
        return None

    monkeypatch.setattr(integration, "async_ensure_catalog_loaded", _loaded)
    coordinator = _Coordinator()
    entry = _entry(coordinator)
    hass = _Hass([entry])

    assert await async_setup(hass, {}) is True
    assert hass.services.has_service(DOMAIN, "manual_refresh")
    assert hass.services.has_service(DOMAIN, "list_history_devices")
    assert hass.services.has_service(DOMAIN, "fetch_device_history")
    assert hass.services.has_service(DOMAIN, "list_plant_statistics_targets")
    assert hass.services.has_service(DOMAIN, "fetch_plant_year_statistics")
    assert hass.services.has_service(DOMAIN, "fetch_plant_month_statistics")
    assert hass.services.has_service(DOMAIN, "set_export_control")

    manual = await hass.services.handler("manual_refresh")(_call())
    assert manual["count"] == 1
    explicit = await hass.services.handler("manual_refresh")(
        _call(entry_id="other")
    )
    assert explicit["count"] == 0

    history_devices = await hass.services.handler("list_history_devices")(_call())
    assert history_devices["count"] == 1
    assert history_devices["devices"][0]["device_sn"] == "INV"
    assert history_devices["devices"][0]["entry_id"] == "entry-1"
    assert (
        await hass.services.handler("list_history_devices")(
            _call(entry_id="missing")
        )
    )["devices"] == []

    plant_targets = await hass.services.handler("list_plant_statistics_targets")(_call())
    assert plant_targets["count"] == 1
    assert plant_targets["plants"][0]["plant_id"] == "P1"
    assert plant_targets["plants"][0]["entry_id"] == "entry-1"
    assert (
        await hass.services.handler("list_plant_statistics_targets")(
            _call(entry_id="missing")
        )
    )["plants"] == []

    with pytest.raises(ServiceValidationError):
        await hass.services.handler("fetch_device_history")(
            _call(
                sn_list=["INV"],
                device_type=1,
                business_type=1,
                start_time=2,
                end_time=1,
                time_interval=5,
            )
        )
    history = await hass.services.handler("fetch_device_history")(
        _call(
            sn_list=["INV"],
            device_type=1,
            business_type=1,
            start_time=1,
            end_time=2,
            time_interval=5,
            request_sn_type=1,
        )
    )
    assert history["history"]["request_sn_type"] == 1
    plant_year = await hass.services.handler("fetch_plant_year_statistics")(
        _call(plant_id="P1", business_type=1, year=datetime.now().year)
    )
    assert plant_year["plant_year"]["plant_id"] == "P1"
    plant_month = await hass.services.handler("fetch_plant_month_statistics")(
        _call(plant_id="P1", business_type=1, year=datetime.now().year, month=1)
    )
    assert plant_month["plant_month"]["month"] == 1
    with pytest.raises(ServiceValidationError):
        await hass.services.handler("fetch_plant_year_statistics")(
            _call(plant_id="P1", business_type=1, year=datetime.now().year + 1)
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.handler("fetch_plant_month_statistics")(
            _call(plant_id="P1", business_type=1, year=datetime.now().year, month=13)
        )
    assert (
        await hass.services.handler("query_request_result")(
            _call(request_id="123")
        )
    )["request_id"] == "123"

    with pytest.raises(ServiceValidationError):
        await hass.services.handler("query_master_control_device")(
            _call(device_sn="INV", device_type=1, business_type=1)
        )
    master = await hass.services.handler("query_master_control_device")(
        _call(device_sn="INV", device_type=1, business_type=4)
    )
    assert master["master"]["business_type"] == 4

    started = await hass.services.handler("start_live_view")(
        _call(duration_seconds=120, interval_seconds=5)
    )
    assert started["started"]["duration_seconds"] == 120
    assert (await hass.services.handler("stop_live_view")(_call()))["stopped"]

    control = await hass.services.handler("set_export_control")(
        _call(
            sn_list=["INV"],
            device_type=100,
            is_enable=1,
            limit_value=5,
            business_type=4,
            control_mode=1,
        )
    )
    assert control["blocked"] is True
    assert hass.bus.events

    with pytest.raises(ServiceValidationError):
        await hass.services.handler("set_export_control")(_call())

    coordinator.available_control_services = {"set_evc_work_mode"}
    hass.data[RUNTIME_RELOAD_STATE]["sync_capability_services"]()
    assert hass.services.has_service(DOMAIN, "set_evc_work_mode")
    dry_ev = await hass.services.handler("set_evc_work_mode")(
        _call(
            sn_list=["EVC1"],
            work_mode=2,
            current_gear=16,
            business_type=1,
        )
    )
    assert dry_ev["blocked"] is True
    assert coordinator.executed_ev_controls == []

    coordinator.ev_charger_controls_enabled = True
    real_ev = await hass.services.handler("set_evc_work_mode")(
        _call(
            sn_list=["EVC1"],
            work_mode=2,
            current_gear=16,
            business_type=1,
        )
    )
    assert real_ev["blocked"] is False
    assert real_ev["accepted"] is True
    assert real_ev["request_id"] == "REQ1"
    assert coordinator.executed_ev_controls[0]["service"] == "set_evc_work_mode"

    coordinator.available_control_services = set()
    hass.data[RUNTIME_RELOAD_STATE]["sync_capability_services"]()
    assert not hass.services.has_service(DOMAIN, "set_export_control")
    assert hass.services.removed


@pytest.mark.asyncio
async def test_list_history_devices_empty_without_loaded_entries(monkeypatch):
    async def _loaded(hass):
        return None

    monkeypatch.setattr(integration, "async_ensure_catalog_loaded", _loaded)
    hass = _Hass()

    assert await async_setup(hass, {}) is True
    payload = await hass.services.handler("list_history_devices")(_call())

    assert payload == {
        "ok": True,
        "entry_id": None,
        "entries": [],
        "count": 0,
        "devices": [],
    }
    plant_payload = await hass.services.handler("list_plant_statistics_targets")(_call())
    assert plant_payload == {
        "ok": True,
        "entry_id": None,
        "entries": [],
        "count": 0,
        "plants": [],
    }


@pytest.mark.asyncio
async def test_setup_entry_lifecycle_migration_and_removal(monkeypatch):
    async def _loaded(hass):
        return None

    class _Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _SetupCoordinator(_Coordinator):
        def __init__(self, hass, **kwargs):
            super().__init__()
            self.hass = hass
            self.kwargs = kwargs
            self.loaded = False
            self.first = False

        async def async_load_capability_cache(self):
            self.loaded = True

        async def async_config_entry_first_refresh(self):
            self.first = True

    monkeypatch.setattr(integration, "async_ensure_catalog_loaded", _loaded)
    monkeypatch.setattr(integration, "async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(integration, "SolaxDeveloperApiClient", _Client)
    monkeypatch.setattr(integration, "SolaxDeveloperCoordinator", _SetupCoordinator)
    monkeypatch.setattr(integration.ir, "async_delete_issue", lambda *args: None)
    monkeypatch.setattr(
        integration.persistent_notification,
        "async_dismiss",
        lambda *args: None,
    )
    monkeypatch.setattr(
        integration,
        "_update_rate_limit_notification",
        lambda *args: None,
    )
    monkeypatch.setattr(integration, "_update_repairs", lambda *args: None)

    entry = _entry()
    hass = _Hass([entry])
    calls = []
    hass.data[RUNTIME_RELOAD_STATE] = {
        "register_universal_services": lambda: calls.append("register"),
        "sync_capability_services": lambda: calls.append("sync"),
    }
    assert await async_setup_entry(hass, entry) is True
    assert entry.runtime_data.coordinator.loaded is True
    assert entry.runtime_data.coordinator.first is True
    assert hass.config_entries.forwarded == [(entry, PLATFORMS)]
    entry.runtime_data.coordinator.listener()
    assert calls.count("sync") >= 2

    legacy = _entry()
    legacy.version = 1
    legacy.data.update(
        {
            "system_name": "Legacy",
            "scan_interval": 180,
            "entity_prefix": "legacy",
        }
    )
    legacy.options = {}
    assert await async_migrate_entry(hass, legacy) is True
    assert legacy.version == 2
    assert legacy.options["system_name"] == "Legacy"
    assert await async_migrate_entry(hass, legacy) is True
    legacy.version = 99
    assert await async_migrate_entry(hass, legacy) is False

    hass.services.items[(DOMAIN, "manual_refresh")] = (lambda: None, {})
    assert await async_unload_entry(hass, entry) is True
    assert getattr(entry.runtime_data.coordinator, "unsubscribed") is True

    failed_entry = _entry(_Coordinator(), entry_id="failed")
    hass.config_entries.unload_result = False
    assert await async_unload_entry(hass, failed_entry) is False

    no_runtime = _entry()
    assert (
        await async_remove_config_entry_device(
            hass,
            no_runtime,
            SimpleNamespace(identifiers={(DOMAIN, "old")}),
        )
        is False
    )
    entry.runtime_data.coordinator.data = {
        "plants": {"P1": {}},
        "devices": {"INV1": {}},
    }
    assert (
        await async_remove_config_entry_device(
            hass,
            entry,
            SimpleNamespace(identifiers={(DOMAIN, "INV1")}),
        )
        is False
    )
    assert (
        await async_remove_config_entry_device(
            hass,
            entry,
            SimpleNamespace(identifiers={(DOMAIN, "STALE")}),
        )
        is True
    )
    assert (
        await async_remove_config_entry_device(
            hass,
            entry,
            SimpleNamespace(identifiers={("other", "STALE")}),
        )
        is False
    )
