from types import SimpleNamespace

import pytest
from homeassistant.helpers import selector

from custom_components.solax_developer_api import config_flow
from custom_components.solax_developer_api.api import SolaxApiError


class _Config:
    language = "en"


class _ConfigEntries:
    def __init__(self):
        self.updates = []
        self.reloads = []

    def async_update_entry(self, entry, **kwargs):
        self.updates.append((entry, kwargs))
        if "data" in kwargs:
            entry.data = kwargs["data"]
        if "options" in kwargs:
            entry.options = kwargs["options"]
        if "title" in kwargs:
            entry.title = kwargs["title"]

    async def async_reload(self, entry_id):
        self.reloads.append(entry_id)


class _Hass:
    def __init__(self):
        self.config = _Config()
        self.config_entries = _ConfigEntries()


def _entry(**overrides):
    values = {
        "entry_id": "entry-1",
        "title": "SDS",
        "data": {
            "client_id": "client",
            "client_secret": "secret",
            "api_region": "eu",
        },
        "options": {
            "system_name": "SDS",
            "entity_prefix": "sds",
            "scan_interval": 120,
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def _loaded(_hass):
    return None


def _capture_flow_methods(handler):
    handler.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    handler.async_show_menu = lambda **kwargs: {"type": "menu", **kwargs}
    handler.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}
    handler.async_abort = lambda **kwargs: {"type": "abort", **kwargs}
    handler.async_update_reload_and_abort = (
        lambda entry, **kwargs: {"type": "abort", "entry": entry, **kwargs}
    )


def _flow_handler(hass=None):
    handler = object.__new__(config_flow.SolaxDeveloperFlowHandler)
    handler.hass = hass or _Hass()
    _capture_flow_methods(handler)
    handler._async_current_entries = lambda: []
    return handler


def _options_handler(entry=None, hass=None):
    handler = config_flow.SolaxDeveloperOptionsFlowHandler(entry or _entry())
    handler.hass = hass or _Hass()
    _capture_flow_methods(handler)
    return handler


def test_config_flow_helpers_and_selectors():
    hass = _Hass()
    assert config_flow._slugify_name("My-Solax Home") == "my_solax_home"
    assert set(config_flow._region_options(hass)) == {"eu", "cn"}
    assert isinstance(config_flow._text_selector(), selector.TextSelector)
    assert isinstance(
        config_flow._text_selector(password=True, multiline=True),
        selector.TextSelector,
    )
    assert isinstance(config_flow._number_selector(1, 10), selector.NumberSelector)
    assert isinstance(config_flow._region_selector(hass), selector.SelectSelector)
    assert isinstance(
        config_flow._mapped_select_selector({"one": "One"}),
        selector.SelectSelector,
    )
    assert (
        config_flow._manual_meter_notification_id("entry")
        == "solax_developer_api_manual_meter_options_entry"
    )
    assert (
        config_flow._manual_ems_notification_id("entry")
        == "solax_developer_api_manual_ems_options_entry"
    )


def test_manual_meter_text_parsing_and_coercion():
    assert config_flow._manual_meter_entries_to_text(
        [
            {"serial": "METER1", "business_type": 1},
            {"serial": "METER4", "business_type": 4},
            {"serial": "", "business_type": 1},
        ]
    ) == "METER1\nMETER4|4"
    assert config_flow._parse_manual_meter_entries_text("")[0] == []
    assert config_flow._parse_manual_meter_entries_text("METER1,METER1")[0] == [
        {"serial": "METER1", "business_type": 1, "source": "manual"}
    ]
    assert config_flow._parse_manual_meter_entries_text("METER1,\n\nMETER2")[0][
        1
    ]["serial"] == "METER2"
    assert config_flow._parse_manual_meter_entries_text("METER|bad")[1] is not None
    assert config_flow._parse_manual_meter_entries_text("METER|2")[1] is not None
    assert config_flow._parse_manual_meter_entries_text("BAD SERIAL")[1] is not None
    assert config_flow._coerce_manual_meter_entries(None) == []
    assert config_flow._coerce_manual_meter_entries("") == []
    assert config_flow._coerce_manual_meter_entries(3) == []
    assert config_flow._coerce_manual_meter_entries({"serial": "DIRECT"})[0][
        "serial"
    ] == "DIRECT"
    assert config_flow._coerce_manual_meter_entries('{"deviceSn":"M1"}')[0][
        "serial"
    ] == "M1"
    assert config_flow._coerce_manual_meter_entries("['M1', 'M2']")[1][
        "serial"
    ] == "M2"
    assert config_flow._coerce_manual_meter_entries("M1|4")[0][
        "business_type"
    ] == 4
    assert config_flow._coerce_manual_meter_entries("M1|bad") == []
    coerced = config_flow._coerce_manual_meter_entries(
        (
            {
                "device_sn": "M1",
                "business_type": "bad",
                "realtimeFields": ["z", "", "a"],
            },
            {"serial": "m1", "businessType": 4},
            "",
        )
    )
    assert coerced == [
        {
            "serial": "M1",
            "business_type": 1,
            "source": "manual",
            "realtime_fields": ["a", "z"],
        }
    ]
    assert config_flow._coerce_manual_meter_entries(
        [{"serial": "M2", "business_type": 2}]
    )[0]["business_type"] == 1


def test_manual_meter_merge_and_remove_options():
    hass = _Hass()
    merged = config_flow._merge_manual_meter_entry_sources(
        [{"serial": "M1", "business_type": 1, "realtime_fields": ["power"]}],
        [{"serial": "m1", "business_type": 4}, "M2"],
        42,
    )
    assert [item["serial"] for item in merged] == ["M1", "M2"]
    assert merged[0]["realtime_fields"] == ["power"]
    assert config_flow._probe_realtime_fields_from_summary(None) == []
    assert config_flow._probe_realtime_fields_from_summary(
        {"realtime_non_null_fields": "bad"}
    ) == []
    assert config_flow._probe_realtime_fields_from_summary(
        {"realtime_non_null_fields": ["z", "a", ""]}
    ) == ["a", "z"]
    options = config_flow._manual_meter_remove_options(
        hass,
        [
            {"serial": "", "business_type": 1},
            {"serial": "M1", "business_type": "bad"},
            {"serial": "M4", "business_type": 4},
        ],
    )
    assert config_flow.MANUAL_METER_REMOVE_NONE in options
    assert "M1" in options and "M4" in options


def test_manual_ems_parsing_coercion_and_options():
    hass = _Hass()
    assert config_flow._parse_manual_ems_entries_text("") == ([], None)
    parsed, error = config_flow._parse_manual_ems_entries_text(
        "EMS1|PLANT1,EMS1|PLANT1"
    )
    assert error is None and len(parsed) == 1
    assert config_flow._parse_manual_ems_entries_text("missing-separator")[1]
    assert config_flow._parse_manual_ems_entries_text("BAD EMS|PLANT")[1]
    assert config_flow._coerce_manual_ems_entries("") == []
    assert config_flow._coerce_manual_ems_entries(1) == []
    assert config_flow._coerce_manual_ems_entries(
        {"serial": "DIRECT", "plant_id": "P1"}
    )[0]["serial"] == "DIRECT"
    assert config_flow._coerce_manual_ems_entries(
        '{"registerNo":"EMS1","stationId":"P1"}'
    )[0]["plant_id"] == "P1"
    assert config_flow._coerce_manual_ems_entries("EMS1|P1")[0][
        "business_type"
    ] == 4
    assert config_flow._coerce_manual_ems_entries(
        "[{'serial':'LIST','plant_id':'P1'}]"
    )[0]["serial"] == "LIST"
    assert config_flow._coerce_manual_ems_entries("invalid") == []
    coerced = config_flow._coerce_manual_ems_entries(
        (
            {"register_no": "EMS1", "plantId": "P1"},
            {"serial": "ems1", "plant_id": "P2"},
            "invalid",
            {"serial": "", "plant_id": "P"},
        )
    )
    assert len(coerced) == 1
    options = config_flow._manual_ems_remove_options(
        hass,
        [{"serial": "", "plant_id": "P"}, {"serial": "EMS1", "plant_id": "P1"}],
    )
    assert config_flow.MANUAL_EMS_REMOVE_NONE in options
    assert "EMS1" in options


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token_error", "expected"),
    [
        (
            SolaxApiError(
                code=10402,
                message="auth",
                classification="auth",
            ),
            "invalid_credentials",
        ),
        (
            SolaxApiError(
                code=None,
                message="http",
                classification="http",
            ),
            "cannot_connect",
        ),
        (RuntimeError("unexpected"), "cannot_connect"),
    ],
)
async def test_validate_credentials_token_failures(monkeypatch, token_error, expected):
    class _Client:
        def __init__(self, **kwargs):
            pass

        async def ensure_token(self, **kwargs):
            raise token_error

    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(config_flow, "SolaxDeveloperApiClient", _Client)

    assert await config_flow._validate_credentials(
        _Hass(),
        client_id="id",
        client_secret="secret",
        region="eu",
    ) == (False, expected)


@pytest.mark.asyncio
async def test_validate_credentials_read_auth_failure(monkeypatch):
    class _Client:
        def __init__(self, **kwargs):
            pass

        async def ensure_token(self, **kwargs):
            pass

        async def page_plant_info(self, **kwargs):
            raise SolaxApiError(
                code=10402,
                message="auth",
                classification="auth",
            )

    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: object())
    monkeypatch.setattr(config_flow, "SolaxDeveloperApiClient", _Client)
    assert await config_flow._validate_credentials(
        _Hass(),
        client_id="id",
        client_secret="secret",
        region="eu",
    ) == (False, "invalid_credentials")


@pytest.mark.asyncio
async def test_user_flow_all_paths(monkeypatch):
    monkeypatch.setattr(config_flow, "async_ensure_catalog_loaded", _loaded)
    handler = _flow_handler()
    handler._async_current_entries = lambda: [object()]
    assert (await handler.async_step_user())["reason"] == "already_configured"

    handler._async_current_entries = lambda: []
    form = await handler.async_step_user()
    assert form["step_id"] == "user"

    base = {
        "client_id": "client",
        "client_secret": "secret",
        "system_name": "My System",
        "scan_interval": 120,
        "api_region": "eu",
    }
    for changes, expected in (
        ({"client_id": ""}, "invalid_credentials"),
        ({"system_name": ""}, "invalid_system_name"),
        ({"api_region": "invalid"}, "invalid_region"),
    ):
        result = await handler.async_step_user({**base, **changes})
        assert result["errors"]["base"] == expected

    async def _invalid(*args, **kwargs):
        return False, "cannot_read_data"

    monkeypatch.setattr(config_flow, "_validate_credentials", _invalid)
    result = await handler.async_step_user(base)
    assert result["errors"]["base"] == "cannot_read_data"

    async def _valid(*args, **kwargs):
        return True, None

    monkeypatch.setattr(config_flow, "_validate_credentials", _valid)
    result = await handler.async_step_user(base)
    assert result["type"] == "create_entry"
    assert result["data"] == {
        "client_id": "client",
        "client_secret": "secret",
        "api_region": "eu",
    }
    assert result["options"]["entity_prefix"] == "my_system"


@pytest.mark.asyncio
async def test_reauth_and_reconfigure_paths(monkeypatch):
    monkeypatch.setattr(config_flow, "async_ensure_catalog_loaded", _loaded)
    entry = _entry()
    handler = _flow_handler()
    handler._get_reauth_entry = lambda: entry
    handler._get_reconfigure_entry = lambda: entry

    async def _valid(*args, **kwargs):
        return True, None

    monkeypatch.setattr(config_flow, "_validate_credentials", _valid)
    async def _reauth_called():
        return "reauth-called"

    handler.async_step_reauth_confirm = _reauth_called
    assert await handler.async_step_reauth({}) == "reauth-called"

    handler.async_step_reauth_confirm = (
        config_flow.SolaxDeveloperFlowHandler.async_step_reauth_confirm.__get__(
            handler
        )
    )
    assert (await handler.async_step_reauth_confirm())["step_id"] == "reauth_confirm"
    invalid = await handler.async_step_reauth_confirm(
        {"client_id": "", "client_secret": "", "api_region": "eu"}
    )
    assert invalid["errors"]["base"] == "invalid_credentials"
    invalid_region = await handler.async_step_reauth_confirm(
        {"client_id": "id", "client_secret": "secret", "api_region": "x"}
    )
    assert invalid_region["errors"]["base"] == "invalid_region"
    success = await handler.async_step_reauth_confirm(
        {"client_id": "id", "client_secret": "secret", "api_region": "cn"}
    )
    assert success["reason"] == "reauth_successful"

    assert (await handler.async_step_reconfigure())["step_id"] == "reconfigure"
    invalid_name = await handler.async_step_reconfigure(
        {
            "client_id": "id",
            "client_secret": "secret",
            "api_region": "eu",
            "system_name": "",
        }
    )
    assert invalid_name["errors"]["base"] == "invalid_system_name"
    invalid_credentials = await handler.async_step_reconfigure(
        {
            "client_id": "",
            "client_secret": "",
            "api_region": "eu",
            "system_name": "New",
        }
    )
    assert invalid_credentials["errors"]["base"] == "invalid_credentials"
    invalid_region = await handler.async_step_reconfigure(
        {
            "client_id": "id",
            "client_secret": "secret",
            "api_region": "x",
            "system_name": "New",
        }
    )
    assert invalid_region["errors"]["base"] == "invalid_region"
    async def _invalid(*args, **kwargs):
        return False, "cannot_read_data"

    monkeypatch.setattr(config_flow, "_validate_credentials", _invalid)
    denied = await handler.async_step_reconfigure(
        {
            "client_id": "id",
            "client_secret": "secret",
            "api_region": "eu",
            "system_name": "New",
        }
    )
    assert denied["errors"]["base"] == "cannot_read_data"
    denied = await handler.async_step_reauth_confirm(
        {"client_id": "id", "client_secret": "secret", "api_region": "eu"}
    )
    assert denied["errors"]["base"] == "cannot_read_data"

    monkeypatch.setattr(config_flow, "_validate_credentials", _valid)
    success = await handler.async_step_reconfigure(
        {
            "client_id": "id",
            "client_secret": "secret",
            "api_region": "eu",
            "system_name": "New",
        }
    )
    assert success["reason"] == "reconfigure_successful"
    assert handler.hass.config_entries.updates[-1][1]["title"] == "New"
    assert isinstance(
        config_flow.SolaxDeveloperFlowHandler.async_get_options_flow(entry),
        config_flow.SolaxDeveloperOptionsFlowHandler,
    )


@pytest.mark.asyncio
async def test_options_finish_and_simple_pages(monkeypatch):
    monkeypatch.setattr(config_flow, "async_ensure_catalog_loaded", _loaded)
    entry = _entry()
    handler = _options_handler(entry)

    assert (await handler.async_step_init())["type"] == "menu"
    assert (await handler.async_step_credentials())["step_id"] == "credentials"
    assert (await handler.async_step_polling())["step_id"] == "polling"
    assert (await handler.async_step_advanced())["step_id"] == "advanced"

    polling = await handler.async_step_polling(
        {
            "scan_interval": 180,
            "live_view_default_duration": 300,
            "live_view_interval": 5,
            "live_view_call_budget_per_minute": 20,
            "night_scan_interval": 600,
            "night_start_hour": 23,
            "night_end_hour": 6,
        }
    )
    assert polling["data"]["scan_interval"] == 180
    assert handler.hass.config_entries.reloads == ["entry-1"]

    advanced = await handler.async_step_advanced(
        {"rate_limit_notifications": False}
    )
    assert advanced["data"]["rate_limit_notifications"] is False


@pytest.mark.asyncio
async def test_options_credentials_changed_and_unchanged(monkeypatch):
    monkeypatch.setattr(config_flow, "async_ensure_catalog_loaded", _loaded)
    entry = _entry()
    handler = _options_handler(entry)
    validations = []

    async def _valid(*args, **kwargs):
        validations.append(kwargs)
        return True, None

    monkeypatch.setattr(config_flow, "_validate_credentials", _valid)
    unchanged = await handler.async_step_credentials(
        {
            "client_id": "client",
            "client_secret": "secret",
            "system_name": "SDS",
            "api_region": "eu",
        }
    )
    assert unchanged["type"] == "create_entry"
    assert validations == []

    changed = await handler.async_step_credentials(
        {
            "client_id": "new",
            "client_secret": "secret",
            "system_name": "New Name",
            "api_region": "eu",
        }
    )
    assert changed["data"]["system_name"] == "New Name"
    assert validations[-1]["client_id"] == "new"

    for changes, expected in (
        ({"client_id": ""}, "invalid_credentials"),
        ({"system_name": ""}, "invalid_system_name"),
        ({"api_region": "x"}, "invalid_region"),
    ):
        result = await handler.async_step_credentials(
            {
                "client_id": "client",
                "client_secret": "secret",
                "system_name": "SDS",
                "api_region": "eu",
                **changes,
            }
        )
        assert result["errors"]["base"] == expected

    async def _invalid(*args, **kwargs):
        return False, "cannot_connect"

    monkeypatch.setattr(config_flow, "_validate_credentials", _invalid)
    result = await handler.async_step_credentials(
        {
            "client_id": "changed",
            "client_secret": "secret",
            "system_name": "SDS",
            "api_region": "eu",
        }
    )
    assert result["errors"]["base"] == "cannot_connect"


class _ManualCoordinator:
    def __init__(self):
        self.data = {"plants": {"P1": {"businessType": 4}}, "devices": {}}
        self.meters = {}
        self.ems = {}
        self.probe_meter_result = {
            "ok": True,
            "serial_resolved": "METER1",
            "business_type": 1,
            "field_summary": {"realtime_non_null_fields": ["importEnergy"]},
        }
        self.probe_ems_result = {
            "ok": True,
            "serial_resolved": "EMS1",
            "plant_id": "P1",
        }

    def get_known_meter_serial(self, serial):
        return self.meters.get(serial.casefold())

    def get_known_ems_serial(self, serial):
        return self.ems.get(serial.casefold())

    async def async_probe_manual_meter_serial(self, serial):
        return dict(self.probe_meter_result)

    async def async_probe_manual_ems_system(self, *, serial, plant_id):
        return dict(self.probe_ems_result)


@pytest.mark.asyncio
async def test_manual_validation_and_context(monkeypatch):
    monkeypatch.setattr(config_flow, "async_ensure_catalog_loaded", _loaded)
    coordinator = _ManualCoordinator()
    entry = _entry(runtime_data=SimpleNamespace(coordinator=coordinator))
    handler = _options_handler(entry)

    context = handler._manual_device_context()
    assert context[4] is True
    assert await handler._validate_manual_meter_entries([]) == ([], [], None)
    assert await handler._validate_manual_ems_entries([]) == ([], [], None)

    validated, skipped, error = await handler._validate_manual_meter_entries(
        [{"serial": "METER1", "business_type": 1}]
    )
    assert error is None and skipped == []
    assert validated[0]["realtime_fields"] == ["importEnergy"]

    coordinator.meters["auto"] = {
        "serial": "AUTO",
        "source": "inventory",
        "business_type": 1,
    }
    validated, skipped, error = await handler._validate_manual_meter_entries(
        [{"serial": ""}, {"serial": "AUTO"}, {"serial": "AUTO"}]
    )
    assert validated == [] and skipped == ["AUTO"] and error is None

    coordinator.meters["manual"] = {
        "serial": "MANUAL",
        "source": "manual",
        "business_type": 4,
    }
    coordinator.probe_meter_result = {
        "ok": True,
        "field_summary": {"realtime_non_null_fields": ["exportEnergy"]},
    }
    validated, _, error = await handler._validate_manual_meter_entries(
        [{"serial": "MANUAL", "realtime_fields": []}]
    )
    assert error is None
    assert validated[0]["business_type"] == 4
    assert validated[0]["realtime_fields"] == ["exportEnergy"]

    coordinator.probe_meter_result = {"ok": False}
    assert (
        await handler._validate_manual_meter_entries([{"serial": "UNKNOWN"}])
    )[2] == "manual_meter_serial_validation_failed"

    coordinator.meters["duplicate"] = {
        "serial": "DUPLICATE",
        "source": "manual",
        "business_type": 1,
        "realtime_fields": ["power"],
    }
    validated, _, _ = await handler._validate_manual_meter_entries(
        [{"serial": "DUPLICATE"}, {"serial": "duplicate"}]
    )
    assert len(validated) == 1

    class _ProbeFailureCoordinator(_ManualCoordinator):
        async def async_probe_manual_meter_serial(self, serial):
            raise RuntimeError("probe error")

    failure = _ProbeFailureCoordinator()
    failure.meters["manual"] = {
        "serial": "MANUAL",
        "source": "manual",
        "business_type": 1,
    }
    handler._config_entry.runtime_data = SimpleNamespace(coordinator=failure)
    validated, _, _ = await handler._validate_manual_meter_entries(
        [{"serial": "MANUAL"}]
    )
    assert validated[0]["serial"] == "MANUAL"

    handler._config_entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    coordinator.meters.clear()
    coordinator.probe_meter_result = {
        "ok": True,
        "serial_resolved": "RESOLVED",
        "business_type": 2,
        "field_summary": {},
    }
    coordinator.meters["resolved"] = {
        "serial": "RESOLVED",
        "source": "inventory",
        "business_type": 1,
    }
    validated, skipped, _ = await handler._validate_manual_meter_entries(
        [{"serial": "INPUT"}]
    )
    assert validated == [] and skipped == ["RESOLVED"]

    coordinator.meters.clear()
    validated, skipped, _ = await handler._validate_manual_meter_entries(
        [{"serial": "INPUT1"}, {"serial": "INPUT2"}]
    )
    assert len(validated) == 1 and skipped == []

    coordinator.ems["autoems"] = {
        "serial": "AUTOEMS",
        "source": "master_control",
    }
    validated, skipped, error = await handler._validate_manual_ems_entries(
        [
            {"serial": "", "plant_id": ""},
            {"serial": "AUTOEMS", "plant_id": "P1"},
            {"serial": "EMS1", "plant_id": "P1"},
            {"serial": "EMS1", "plant_id": "P1"},
        ]
    )
    assert error is None and skipped == ["AUTOEMS"]
    assert validated[0]["serial"] == "EMS1"

    coordinator.probe_ems_result = {"ok": False}
    assert (
        await handler._validate_manual_ems_entries(
            [{"serial": "BAD", "plant_id": "P1"}]
        )
    )[2] == "manual_ems_validation_failed"


@pytest.mark.asyncio
async def test_manual_validation_unavailable_without_loaded_runtime():
    handler = _options_handler(_entry())
    assert (
        await handler._validate_manual_meter_entries([{"serial": "M1"}])
    )[2] == "manual_meter_serial_validation_unavailable"
    assert (
        await handler._validate_manual_ems_entries(
            [{"serial": "E1", "plant_id": "P1"}]
        )
    )[2] == "manual_ems_validation_unavailable"


@pytest.mark.asyncio
async def test_manual_devices_page_save_remove_and_errors(monkeypatch):
    monkeypatch.setattr(config_flow, "async_ensure_catalog_loaded", _loaded)
    coordinator = _ManualCoordinator()
    entry = _entry(
        options={
            "system_name": "SDS",
            "manual_meter_serials": [
                {"serial": "OLDMETER", "business_type": 1}
            ],
            "manual_ems_systems": [
                {"serial": "OLDEMS", "plant_id": "P1", "business_type": 4}
            ],
        },
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )
    handler = _options_handler(entry)
    original_meter_validator = handler._validate_manual_meter_entries
    original_ems_validator = handler._validate_manual_ems_entries
    monkeypatch.setattr(handler, "_notify_manual_device_result", lambda **kwargs: None)

    assert (await handler.async_step_manual_devices())["step_id"] == "manual_devices"

    missing_target = await handler.async_step_manual_devices(
        {
            config_flow.CONF_MANUAL_METER_REMOVE_CONFIRM: True,
            config_flow.CONF_MANUAL_METER_REMOVE_SERIAL:
                config_flow.MANUAL_METER_REMOVE_NONE,
        }
    )
    assert (
        missing_target["errors"][config_flow.CONF_MANUAL_METER_REMOVE_SERIAL]
        == "manual_meter_remove_target_required"
    )

    parse_errors = await handler.async_step_manual_devices(
        {
            config_flow.CONF_MANUAL_METER_SERIALS_ADD: "BAD SERIAL",
            config_flow.CONF_MANUAL_EMS_SYSTEMS_ADD: "bad",
        }
    )
    assert config_flow.CONF_MANUAL_METER_SERIALS_ADD in parse_errors["errors"]
    assert config_flow.CONF_MANUAL_EMS_SYSTEMS_ADD in parse_errors["errors"]

    missing_remove = await handler.async_step_manual_devices(
        {
            config_flow.CONF_MANUAL_METER_REMOVE_CONFIRM: True,
            config_flow.CONF_MANUAL_METER_REMOVE_SERIAL: "NOTTHERE",
        }
    )
    assert (
        missing_remove["errors"][config_flow.CONF_MANUAL_METER_REMOVE_SERIAL]
        == "manual_meter_remove_target_missing"
    )
    missing_ems_remove = await handler.async_step_manual_devices(
        {
            config_flow.CONF_MANUAL_EMS_REMOVE_CONFIRM: True,
            config_flow.CONF_MANUAL_EMS_REMOVE_SERIAL: "NOTTHERE",
        }
    )
    assert (
        missing_ems_remove["errors"][config_flow.CONF_MANUAL_EMS_REMOVE_SERIAL]
        == "manual_ems_remove_target_missing"
    )

    async def _bad_meter(entries):
        return [], [], "manual_meter_serial_validation_failed"

    monkeypatch.setattr(handler, "_validate_manual_meter_entries", _bad_meter)
    failed_meter = await handler.async_step_manual_devices(
        {config_flow.CONF_MANUAL_METER_SERIALS_ADD: "METER1"}
    )
    assert config_flow.CONF_MANUAL_METER_SERIALS_ADD in failed_meter["errors"]

    async def _good_meter(entries):
        return entries, [], None

    async def _bad_ems(entries):
        return [], [], "manual_ems_validation_failed"

    monkeypatch.setattr(handler, "_validate_manual_meter_entries", _good_meter)
    monkeypatch.setattr(handler, "_validate_manual_ems_entries", _bad_ems)
    failed_ems = await handler.async_step_manual_devices(
        {config_flow.CONF_MANUAL_EMS_SYSTEMS_ADD: "EMS1|P1"}
    )
    assert config_flow.CONF_MANUAL_EMS_SYSTEMS_ADD in failed_ems["errors"]

    missing_ems = await handler.async_step_manual_devices(
        {
            config_flow.CONF_MANUAL_EMS_REMOVE_CONFIRM: True,
            config_flow.CONF_MANUAL_EMS_REMOVE_SERIAL:
                config_flow.MANUAL_EMS_REMOVE_NONE,
        }
    )
    assert (
        missing_ems["errors"][config_flow.CONF_MANUAL_EMS_REMOVE_SERIAL]
        == "manual_ems_remove_target_required"
    )

    monkeypatch.setattr(
        handler,
        "_validate_manual_meter_entries",
        original_meter_validator,
    )
    monkeypatch.setattr(
        handler,
        "_validate_manual_ems_entries",
        original_ems_validator,
    )
    result = await handler.async_step_manual_devices(
        {
            config_flow.CONF_MANUAL_METER_SERIALS_ADD: "METER1",
            config_flow.CONF_MANUAL_METER_REMOVE_SERIAL: "OLDMETER",
            config_flow.CONF_MANUAL_METER_REMOVE_CONFIRM: True,
            config_flow.CONF_MANUAL_EMS_SYSTEMS_ADD: "EMS1|P1",
            config_flow.CONF_MANUAL_EMS_REMOVE_SERIAL: "OLDEMS",
            config_flow.CONF_MANUAL_EMS_REMOVE_CONFIRM: True,
        }
    )
    assert result["type"] == "create_entry"
    assert result["data"]["manual_meter_serials"][0]["serial"] == "METER1"
    assert result["data"]["manual_ems_systems"][0]["serial"] == "EMS1"


def test_manual_device_notifications(monkeypatch):
    created = []
    dismissed = []
    monkeypatch.setattr(
        config_flow.persistent_notification,
        "async_create",
        lambda *args, **kwargs: created.append((args, kwargs)),
    )
    monkeypatch.setattr(
        config_flow.persistent_notification,
        "async_dismiss",
        lambda *args, **kwargs: dismissed.append((args, kwargs)),
    )
    handler = _options_handler()

    handler._notify_manual_device_result(
        skipped_meters=["M1"],
        removed_meters=[],
        skipped_ems=["E1"],
        removed_ems=[],
    )
    assert len(created) == 2

    handler._notify_manual_device_result(
        skipped_meters=[],
        removed_meters=[],
        skipped_ems=[],
        removed_ems=[],
    )
    assert len(dismissed) == 2
