"""Safety checks for explicitly enabled inverter mode commands."""

import pytest

from custom_components.solax_developer_api.inverter_modes import (
    ProfileSettingsError,
    command_for_mode,
    configured_modes,
    configured_profiles,
    inverter_family,
    profile_settings,
)


@pytest.mark.parametrize(
    ("settings", "field", "code"),
    [
        ({"charge_upper_soc": 80, "charge_from_grid_enable": True}, "min_soc", "profile_required_value"),
        ({"min_soc": 101, "charge_upper_soc": 80, "charge_from_grid_enable": True}, "min_soc", "profile_invalid_soc"),
        ({"min_soc": 20, "charge_upper_soc": 10, "charge_from_grid_enable": True}, "charge_upper_soc", "profile_upper_soc_below_min"),
        ({"min_soc": 20, "charge_upper_soc": 80, "charge_from_grid_enable": "yes"}, "charge_from_grid_enable", "profile_invalid_boolean"),
        ({"min_soc": 20, "charge_upper_soc": 80, "charge_from_grid_enable": True, "schedule_enabled": True}, "schedule_enabled", "profile_period1_required"),
        ({"min_soc": 20, "charge_upper_soc": 80, "charge_from_grid_enable": True, "schedule_enabled": True, "charge_start_time_period1": "22:00"}, "charge_end_time_period1", "profile_time_pair_incomplete"),
        ({"min_soc": 20, "charge_upper_soc": 80, "charge_from_grid_enable": True, "schedule_enabled": True, "charge_start_time_period1": "22:00", "charge_end_time_period1": "22:00"}, "charge_end_time_period1", "profile_time_same"),
    ],
)
def test_profile_validation_reports_field_and_reason(settings, field, code):
    with pytest.raises(ProfileSettingsError) as caught:
        profile_settings("standard", "self_use", settings)
    assert (caught.value.field, caught.value.code) == (field, code)


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


def test_legacy_review_flag_no_longer_blocks_modes_but_inventory_does():
    serial = "INV-3"
    device = {"deviceSn": serial, "deviceType": 1, "deviceModel": 33, "businessType": 1}
    options = _options(serial, "standard", "manual")
    options["inverter_mode_profiles"][serial]["manual"]["reviewed"] = False
    assert command_for_mode(
        options=options, device=device, serial=serial, action="manual_charge"
    )[1]["manualMode"] == 1
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


def test_named_profiles_apply_distinct_grid_charging_settings():
    serial = "INV-5"
    device = {"deviceSn": serial, "deviceType": 1, "deviceModel": 33, "businessType": 1}
    base = {"name": "Sunny", "family": "standard", "min_soc": 20,
            "charge_upper_soc": 80, "charge_from_grid_enable": False}
    options = {"inverter_mode_controls_enabled": True,
               "inverter_mode_profiles": {serial: {"self_use": {"profiles": {
                   "sunny": base,
                   "cloudy": {**base, "name": "Cloudy", "charge_from_grid_enable": True},
               }}}}}
    assert configured_profiles(options, serial, "standard") == [
        ("self_use", "sunny", "Sunny"), ("self_use", "cloudy", "Cloudy")
    ]
    sunny = command_for_mode(options=options, device=device, serial=serial,
                             action="self_use", profile_id="sunny")[1]
    cloudy = command_for_mode(options=options, device=device, serial=serial,
                              action="self_use", profile_id="cloudy")[1]
    assert sunny["chargeFromGridEnable"] == 0
    assert cloudy["chargeFromGridEnable"] == 1


def test_scheduled_profile_accepts_overnight_and_overlapping_windows():
    values = {"min_soc": 20, "charge_upper_soc": 80,
              "charge_from_grid_enable": True, "schedule_enabled": True,
              "charge_start_time_period1": "22:00",
              "charge_end_time_period1": "06:00",
              "enable_time_period2": True,
              "charge_start_time_period2": "13:00",
              "charge_end_time_period2": "15:00"}
    settings = profile_settings("standard", "self_use", values)
    assert settings["charge_start_time_period1"] == "22:00"
    assert settings["enable_time_period2"] is True
    serial = "INV-SCHEDULE"
    options = _options(serial, "standard", "self_use", **values)
    payload = command_for_mode(
        options=options,
        device={"deviceSn": serial, "deviceType": 1, "deviceModel": 33,
                "businessType": 1},
        serial=serial, action="self_use",
    )[1]
    assert payload["chargeStartTimePeriod1"] == "22:00"
    assert payload["chargeEndTimePeriod1"] == "06:00"
    assert payload["enableTimePeriod2"] == 1
    assert payload["chargeStartTimePeriod2"] == "13:00"
    assert "scheduleEnabled" not in payload
    overlapping = profile_settings("standard", "self_use", {
        **values, "discharge_start_time_period1": "05:00",
        "discharge_end_time_period1": "07:00"})
    assert overlapping["discharge_start_time_period1"] == "05:00"
    assert overlapping["discharge_end_time_period1"] == "07:00"
    overlapping_payload = command_for_mode(
        options=_options(serial, "standard", "self_use", **values,
                         discharge_start_time_period1="05:00",
                         discharge_end_time_period1="07:00"),
        device={"deviceSn": serial, "deviceType": 1, "deviceModel": 33,
                "businessType": 1},
        serial=serial, action="self_use",
    )[1]
    assert overlapping_payload["dischargeStartTimePeriod1"] == "05:00"
    with pytest.raises(ValueError, match="charge_end_time_period1"):
        profile_settings("standard", "self_use", {
            **values, "charge_end_time_period1": ""})


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"schedule_enabled": 1}, "schedule_enabled"),
        ({"schedule_enabled": False}, "schedule_enabled"),
        ({"charge_start_time_period1": "25:00"}, "charge_start_time_period1"),
        ({"charge_end_time_period1": "22:00"}, "charge_end_time_period1"),
        ({"enable_time_period2": False, "charge_start_time_period2": "13:00",
          "charge_end_time_period2": "15:00"}, "enable_time_period2"),
        ({"charge_start_time_period1": None, "charge_end_time_period1": None,
          "enable_time_period2": False}, "schedule_enabled"),
        ({"enable_time_period2": 1}, "enable_time_period2"),
        ({"enable_time_period2": True}, "enable_time_period2"),
    ],
)
def test_schedule_validation_rejects_ambiguous_or_unsafe_windows(changes, field):
    base = {"min_soc": 20, "charge_upper_soc": 80,
            "charge_from_grid_enable": True, "schedule_enabled": True,
            "charge_start_time_period1": "22:00",
            "charge_end_time_period1": "06:00",
            "enable_time_period2": False}
    with pytest.raises(ValueError, match=field):
        profile_settings("standard", "self_use", {**base, **changes})


def test_schedule_picker_seconds_normalize_and_empty_names_hide_profiles():
    values = {"min_soc": 20, "charge_upper_soc": 80,
              "charge_from_grid_enable": True, "schedule_enabled": True,
              "charge_start_time_period1": "22:00:00",
              "charge_end_time_period1": "06:00:00"}
    assert profile_settings("standard", "self_use", values)["charge_start_time_period1"] == "22:00"
    options = {"inverter_mode_controls_enabled": True,
               "inverter_mode_profiles": {"INV": {"self_use": {"profiles": {
                   "invalid": {"name": " ", "family": "standard", **values}
               }}}}}
    assert configured_profiles(options, "INV", "standard") == []
