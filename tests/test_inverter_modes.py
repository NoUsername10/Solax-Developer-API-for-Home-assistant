"""Safety checks for explicitly enabled inverter mode commands."""

import pytest

from custom_components.solax_developer_api.inverter_modes import (
    command_for_mode,
    configured_modes,
    inverter_family,
    profile_settings,
)


def _options(serial, family, mode, **settings):
    return {
        "inverter_mode_controls_enabled": True,
        "inverter_mode_profiles": {
            serial: {mode: {"family": family, "reviewed": True, **settings}}
        },
    }


def test_standard_mode_uses_only_required_fields_and_inventory_business_type():
    serial = "INV-1"
    device = {"deviceSn": serial, "deviceType": 1, "deviceModel": 33, "businessType": 4}
    options = _options(
        serial,
        "standard",
        "self_use",
        min_soc=20,
        charge_upper_soc=80,
        charge_from_grid_enable=False,
    )
    service, payload = command_for_mode(
        options=options, device=device, serial=serial, action="self_use"
    )
    assert service == "batch_set_spontaneity_self_use"
    assert payload == {
        "snList": [serial],
        "businessType": 4,
        "minSoc": 20,
        "chargeUpperSoc": 80,
        "chargeFromGridEnable": 0,
    }


def test_a1_backup_requires_documented_times_but_not_optional_periods():
    serial = "A1-1"
    device = {"deviceSn": serial, "deviceType": 1, "deviceModel": 19, "businessType": 1}
    options = _options(
        serial,
        "a1_hybrid_g2",
        "back_up",
        back_up_grid_enable=True,
        back_up_charge_start_time="08:00",
        back_up_charge_end_time="23:00",
    )
    service, payload = command_for_mode(
        options=options, device=device, serial=serial, action="back_up"
    )
    assert service == "back_up_mode"
    assert payload == {
        "snList": [serial],
        "businessType": 1,
        "backUpGridEnable": 1,
        "backUpChargeStartTime": "08:00",
        "backUpChargeEndTime": "23:00",
    }
    assert inverter_family(device) == "a1_hybrid_g2"
    assert "manual" not in configured_modes(options, serial, "a1_hybrid_g2")


def test_manual_actions_require_one_reviewed_manual_profile():
    serial = "INV-2"
    device = {"deviceSn": serial, "deviceType": 1, "deviceModel": 33, "businessType": 1}
    options = _options(serial, "standard", "manual")
    for action, value in (
        ("manual_stop", 0),
        ("manual_charge", 1),
        ("manual_discharge", 2),
    ):
        service, payload = command_for_mode(
            options=options, device=device, serial=serial, action=action
        )
        assert service == "batch_set_manual_mode"
        assert payload["manualMode"] == value


def test_unreviewed_or_missing_inventory_context_blocks_commands():
    serial = "INV-3"
    device = {"deviceSn": serial, "deviceType": 1, "deviceModel": 33, "businessType": 1}
    options = _options(serial, "standard", "manual")
    options["inverter_mode_profiles"][serial]["manual"]["reviewed"] = False
    with pytest.raises(ValueError, match="inverter_mode_not_enabled"):
        command_for_mode(
            options=options, device=device, serial=serial, action="manual_charge"
        )
    options["inverter_mode_profiles"][serial]["manual"]["reviewed"] = True
    with pytest.raises(ValueError, match="inverter_mode_target_unverified"):
        command_for_mode(
            options=options,
            device={"deviceType": 1, "deviceModel": 33},
            serial=serial,
            action="manual_charge",
        )
    options["inverter_mode_controls_enabled"] = False
    with pytest.raises(ValueError, match="inverter_mode_not_enabled"):
        command_for_mode(
            options=options, device=device, serial=serial, action="manual_charge"
        )


def test_invalid_soc_and_time_values_do_not_enable_modes():
    with pytest.raises(ValueError, match="charge_upper_soc"):
        profile_settings(
            "standard", "feed_in_priority", {"min_soc": 80, "charge_upper_soc": 20}
        )
    with pytest.raises(ValueError, match="back_up_charge_end_time"):
        profile_settings(
            "a1_hybrid_g2",
            "back_up",
            {
                "back_up_grid_enable": True,
                "back_up_charge_start_time": "08:00",
                "back_up_charge_end_time": "25:00",
            },
        )


def test_saved_profiles_are_revalidated_before_exposing_controls():
    serial = "INV-4"
    device = {"deviceSn": serial, "deviceType": 1, "deviceModel": 33, "businessType": 1}
    assert inverter_family({**device, "deviceType": 2}) is None
    assert inverter_family({**device, "deviceModel": "invalid"}) is None
    options = _options(serial, "standard", "self_use", min_soc=20,
                       charge_upper_soc=80, charge_from_grid_enable=True)
    assert configured_modes(options, serial, "standard") == ["self_use"]

    options["inverter_mode_profiles"][serial]["self_use"]["family"] = "a1_hybrid_g2"
    assert configured_modes(options, serial, "standard") == []
    options["inverter_mode_profiles"][serial]["self_use"]["family"] = "standard"

    options["inverter_mode_profiles"][serial]["self_use"].pop("min_soc")
    assert configured_modes(options, serial, "standard") == []
    with pytest.raises(ValueError, match="inverter_mode_not_enabled"):
        command_for_mode(options=options, device=device, serial=serial, action="self_use")

    options["inverter_mode_profiles"][serial]["self_use"]["min_soc"] = 20
    options["inverter_mode_profiles"][serial]["self_use"]["charge_from_grid_enable"] = 1
    assert configured_modes(options, serial, "standard") == []
    options["inverter_mode_profiles"][serial]["self_use"]["charge_from_grid_enable"] = True
    options["inverter_mode_profiles"][serial]["self_use"]["charge_upper_soc"] = 120
    assert configured_modes(options, serial, "standard") == []
    assert configured_modes(options, "OTHER", "standard") == []
    with pytest.raises(ValueError, match="inverter_mode_target_unverified"):
        command_for_mode(options=options, device=device, serial="OTHER", action="self_use")


def test_a1_time_picker_seconds_are_normalized_before_api_submission():
    serial = "A1-2"
    device = {"deviceSn": serial, "deviceType": 1, "deviceModel": 19, "businessType": 1}
    options = _options(serial, "a1_hybrid_g2", "back_up",
                       back_up_grid_enable=False,
                       back_up_charge_start_time="08:00:00",
                       back_up_charge_end_time="23:00:00")
    service, payload = command_for_mode(
        options=options, device=device, serial=serial, action="back_up"
    )
    assert service == "back_up_mode"
    assert payload["backUpChargeStartTime"] == "08:00"
    assert payload["backUpChargeEndTime"] == "23:00"
    assert inverter_family({**device, "businessType": 2}) is None
