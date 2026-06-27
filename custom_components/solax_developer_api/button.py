"""Button entities for SolaX Developer API integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .entity import SolaxSystemCoordinatorEntity, system_identity
from .ev_charger import SolaxEVChargerEntity, ev_charger_devices

PARALLEL_UPDATES = 1

EV_COMMAND_BUTTONS: tuple[tuple[str, str, int], ...] = (
    ("ev_charger_lock", "lock", 0),
    ("ev_charger_available", "available", 1),
    ("ev_charger_start_charging", "start_charging", 2),
    ("ev_charger_stop_charging", "stop_charging", 3),
)

EV_APPLY_BUTTONS: tuple[type["SolaxEVApplyButton"], ...] = ()


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data.coordinator
    system_name, system_slug = system_identity(hass, entry)
    seen: set[tuple[str, str]] = set()

    entities = [
        SolaxLiveViewBoostButton(
            hass=hass,
            coordinator=coordinator,
            system_name=system_name,
            system_slug=system_slug,
        ),
    ]

    def _build_ev_buttons():
        new_entities = []
        for device in ev_charger_devices(coordinator):
            device_sn = str(device.get("deviceSn") or "")
            for translation_key, field_slug, work_cmd in EV_COMMAND_BUTTONS:
                token = (device_sn, translation_key)
                if token in seen:
                    continue
                seen.add(token)
                new_entities.append(
                    SolaxEVChargeCommandButton(
                        coordinator=coordinator,
                        system_slug=system_slug,
                        device=device,
                        translation_key=translation_key,
                        field_slug=field_slug,
                        work_cmd=work_cmd,
                    )
                )
            for cls in EV_APPLY_BUTTONS:
                token = (device_sn, cls.FIELD_SLUG)
                if token in seen:
                    continue
                seen.add(token)
                new_entities.append(
                    cls(
                        coordinator=coordinator,
                        system_slug=system_slug,
                        device=device,
                    )
                )
        return new_entities

    entities.extend(_build_ev_buttons())
    async_add_entities(entities)

    def _coordinator_updated() -> None:
        additions = _build_ev_buttons()
        if additions:
            async_add_entities(additions)

    if hasattr(entry, "async_on_unload"):
        entry.async_on_unload(coordinator.async_add_listener(_coordinator_updated))


class SolaxLiveViewBoostButton(SolaxSystemCoordinatorEntity, ButtonEntity):
    """Start temporary live-view refresh profile."""

    _attr_translation_key = "live_view_boost"

    def __init__(self, *, hass, coordinator, system_name: str, system_slug: str):
        super().__init__(
            coordinator,
            system_name=system_name,
            system_slug=system_slug,
        )
        self.hass = hass
        self._attr_unique_id = f"{system_slug}_live_view_boost_solax"
        self.entity_id = f"button.{system_slug}_live_view_boost"

    @property
    def extra_state_attributes(self):
        meta = (self.coordinator.data or {}).get("meta") or {}
        return {
            "poll_profile": meta.get("poll_profile"),
            "effective_scan_interval": meta.get("effective_scan_interval"),
            "live_view_active": meta.get("live_view_active"),
        }

    async def async_press(self) -> None:
        await self.coordinator.async_start_live_view()


class SolaxEVChargeCommandButton(SolaxEVChargerEntity, ButtonEntity):
    """Immediate EV charger command button."""

    def __init__(
        self,
        *,
        coordinator,
        system_slug: str,
        device,
        translation_key: str,
        field_slug: str,
        work_cmd: int,
    ) -> None:
        super().__init__(
            coordinator,
            system_slug,
            device,
            f"ev_charger_{field_slug}",
            "button",
        )
        self._attr_translation_key = translation_key
        self._work_cmd = int(work_cmd)

    async def async_press(self) -> None:
        payload = self._payload_base()
        payload["work_cmd"] = self._work_cmd
        await self._execute_evc_service("set_evc_charge_command", payload)


class SolaxEVApplyButton(SolaxEVChargerEntity, ButtonEntity):
    """Base EV charger apply button."""

    FIELD_SLUG = ""

    def __init__(self, *, coordinator, system_slug: str, device) -> None:
        super().__init__(
            coordinator,
            system_slug,
            device,
            self.FIELD_SLUG,
            "button",
        )


class SolaxEVApplyChargeSceneButton(SolaxEVApplyButton):
    """Apply staged EV charger charge scene details."""

    FIELD_SLUG = "ev_charger_apply_charge_scene"
    _attr_translation_key = "ev_charger_apply_charge_scene"

    async def async_press(self) -> None:
        payload = self._payload_base()
        payload["charger_scene"] = int(self._ev_gui_state.get("charger_scene") or 0)
        ocpp_url = str(self._ev_gui_state.get("ocpp_url") or "").strip()
        ocpp_charger_id = str(self._ev_gui_state.get("ocpp_charger_id") or "").strip()
        if ocpp_url:
            payload["ocpp_url"] = ocpp_url
        if ocpp_charger_id:
            payload["ocpp_charger_id"] = ocpp_charger_id
        await self._execute_evc_service("set_charge_scene", payload)


class SolaxEVApplyQRCodeButton(SolaxEVApplyButton):
    """Apply staged EV charger QR code."""

    FIELD_SLUG = "ev_charger_apply_qr_code"
    _attr_translation_key = "ev_charger_apply_qr_code"

    async def async_press(self) -> None:
        payload = self._payload_base()
        payload["qr_code"] = str(self._ev_gui_state.get("qr_code") or "")
        await self._execute_evc_service("set_evc_qr_code", payload)


class SolaxEVApplyReserveChargeButton(SolaxEVApplyButton):
    """Apply staged EV charger reserve charge schedule."""

    FIELD_SLUG = "ev_charger_apply_reserve_charge"
    _attr_translation_key = "ev_charger_apply_reserve_charge"

    async def async_press(self) -> None:
        payload = self._payload_base()
        payload["charge_start_time"] = str(
            self._ev_gui_state.get("reserve_start_time") or "08:00"
        )
        payload["charge_end_time"] = str(
            self._ev_gui_state.get("reserve_end_time") or "10:00"
        )
        payload["charge_current"] = int(self._ev_gui_state.get("reserve_current") or 16)
        await self._execute_evc_service("set_evc_reserve_charge", payload)


EV_APPLY_BUTTONS = (
    SolaxEVApplyChargeSceneButton,
    SolaxEVApplyQRCodeButton,
    SolaxEVApplyReserveChargeButton,
)
