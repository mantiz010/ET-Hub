from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, QOS_RETRY_DELAYS_S, QOS_MAX_TOTAL_S
from .hub import EtBusHub

_LOGGER = logging.getLogger(__name__)

_PRESET_LIST = ["low", "medium", "high"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: EtBusHub = hass.data[DOMAIN][entry.entry_id]
    entities: dict[tuple[str, str], EtBusFan] = {}

    @callback
    def handle_message(msg: dict[str, Any]) -> None:
        if msg.get("v") != 1:
            return

        mtype = msg.get("type")
        dev_id = msg.get("id")
        dev_class = msg.get("class")
        payload = msg.get("payload", {}) or {}

        if not dev_id or dev_class not in ("fan.speed", "fan.preset"):
            return

        endpoint = dev_class.replace(".", "_")
        key = (dev_id, endpoint)

        if mtype in ("discover", "state", "pong"):
            if key not in entities:
                name = payload.get("name", dev_id)
                ent = EtBusFan(hass, hub, dev_id, dev_class, endpoint, name)
                entities[key] = ent
                async_add_entities([ent])
                _LOGGER.info("ET-Bus: discovered %s %s", dev_class, dev_id)

            if mtype == "state":
                entities[key].handle_state(payload)

    hub.register_listener(handle_message)


class EtBusFan(FanEntity):
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, hub: EtBusHub, dev_id: str, dev_class: str, endpoint: str, name: str):
        self.hass = hass
        self._hub = hub
        self._dev_id = dev_id
        self._dev_class = dev_class
        self._endpoint = endpoint

        self._attr_name = name
        self._is_on = False
        self._percentage = 0
        self._preset = None

        self._extra: dict[str, Any] = {}

        self._pending: dict[str, Any] | None = None
        self._pending_started: float = 0.0
        self._pending_try: int = 0
        self._pending_unsub = None

        self._attr_unique_id = f"etbus_{dev_id}_{endpoint}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, dev_id)},
            "name": dev_id,
            "manufacturer": "ElectronicsTech",
        }

        # Features
        if self._dev_class == "fan.speed":
            self._attr_supported_features = FanEntityFeature.SET_SPEED
        else:
            self._attr_supported_features = FanEntityFeature.PRESET_MODE
            self._attr_preset_modes = list(_PRESET_LIST)

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def percentage(self) -> int | None:
        return self._percentage if self._dev_class == "fan.speed" else None

    @property
    def preset_mode(self) -> str | None:
        return self._preset if self._dev_class == "fan.preset" else None

    @property
    def extra_state_attributes(self):
        return self._extra

    def handle_state(self, payload: dict[str, Any]) -> None:
        if "on" in payload:
            self._is_on = bool(payload["on"])

        if self._dev_class == "fan.speed" and "speed" in payload:
            try:
                self._percentage = int(payload["speed"])
            except Exception:
                pass

        if self._dev_class == "fan.preset" and "preset" in payload:
            self._preset = str(payload["preset"])

        extra = dict(payload)
        extra.pop("on", None)
        self._extra = extra

        # confirm qos
        if self._pending is not None:
            want_on = bool(self._pending.get("on", self._is_on))
            if self._dev_class == "fan.speed":
                want_speed = int(self._pending.get("speed", self._percentage))
                if self._is_on == want_on and self._percentage == want_speed:
                    self._qos_clear()
            else:
                want_preset = str(self._pending.get("preset", self._preset))
                if self._is_on == want_on and (self._preset == want_preset):
                    self._qos_clear()

        if self.hass is not None:
            self.async_write_ha_state()

    def _qos_clear(self) -> None:
        self._pending = None
        self._pending_try = 0
        self._pending_started = 0.0
        if self._pending_unsub:
            try:
                self._pending_unsub()
            except Exception:
                pass
        self._pending_unsub = None

    def _send_now(self) -> None:
        if self._pending is None:
            return
        self._hub.send_to(
            self._dev_id,
            {
                "v": 1,
                "type": "command",
                "id": self._dev_id,
                "class": self._dev_class,
                "payload": dict(self._pending),
            },
        )

    def _qos_tick(self, _now=None) -> None:
        if self._pending is None:
            return

        if (time.monotonic() - self._pending_started) > QOS_MAX_TOTAL_S:
            _LOGGER.warning("ET-Bus QoS timeout (fan): %s", self._dev_id)
            self._qos_clear()
            return

        self._send_now()

        self._pending_try += 1
        delay_idx = min(self._pending_try, len(QOS_RETRY_DELAYS_S) - 1)
        delay = QOS_RETRY_DELAYS_S[delay_idx]
        self._pending_unsub = async_call_later(self.hass, delay, self._qos_tick)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._is_on = True
        # keep last speed/preset
        self._pending = {"on": True}
        if self._dev_class == "fan.speed":
            self._pending["speed"] = int(self._percentage)
        else:
            self._pending["preset"] = str(self._preset or _PRESET_LIST[0])

        self._pending_started = time.monotonic()
        self._pending_try = 0
        self._qos_tick()
        if self.hass is not None:
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._is_on = False
        self._pending = {"on": False}
        if self._dev_class == "fan.speed":
            self._pending["speed"] = int(self._percentage)
        else:
            self._pending["preset"] = str(self._preset or _PRESET_LIST[0])

        self._pending_started = time.monotonic()
        self._pending_try = 0
        self._qos_tick()
        if self.hass is not None:
            self.async_write_ha_state()

    async def async_set_percentage(self, percentage: int) -> None:
        if self._dev_class != "fan.speed":
            return
        self._percentage = int(max(0, min(100, percentage)))
        self._is_on = self._percentage > 0

        self._pending = {"on": self._is_on, "speed": int(self._percentage)}
        self._pending_started = time.monotonic()
        self._pending_try = 0
        self._qos_tick()
        if self.hass is not None:
            self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if self._dev_class != "fan.preset":
            return
        self._preset = preset_mode
        self._is_on = True

        self._pending = {"on": True, "preset": str(preset_mode)}
        self._pending_started = time.monotonic()
        self._pending_try = 0
        self._qos_tick()
        if self.hass is not None:
            self.async_write_ha_state()
