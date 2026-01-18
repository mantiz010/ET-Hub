from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, QOS_RETRY_DELAYS_S, QOS_MAX_TOTAL_S
from .hub import EtBusHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: EtBusHub = hass.data[DOMAIN][entry.entry_id]
    entities: dict[str, EtBusRgbLight] = {}

    @callback
    def handle_message(msg: dict[str, Any]) -> None:
        if msg.get("v") != 1:
            return

        mtype = msg.get("type")
        dev_id = msg.get("id")
        dev_class = msg.get("class")
        payload = msg.get("payload", {}) or {}

        if not dev_id or dev_class != "light.rgb":
            return

        if mtype in ("discover", "state", "pong"):
            if dev_id not in entities:
                name = payload.get("name", dev_id)
                ent = EtBusRgbLight(hass, hub, dev_id, name)
                entities[dev_id] = ent
                async_add_entities([ent])
                _LOGGER.info("ET-Bus: discovered light.rgb %s", dev_id)

            if mtype == "state":
                entities[dev_id].handle_state(payload)

    hub.register_listener(handle_message)


class EtBusRgbLight(LightEntity):
    _attr_should_poll = False
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_color_mode = ColorMode.RGB
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, hub: EtBusHub, dev_id: str, name: str):
        self.hass = hass
        self._hub = hub
        self._dev_id = dev_id
        self._attr_name = name

        self._is_on = False
        self._rgb = (255, 255, 255)
        self._brightness = 255

        self._pending: dict[str, Any] | None = None
        self._pending_started: float = 0.0
        self._pending_try: int = 0
        self._pending_unsub = None

        self._attr_unique_id = f"etbus_{dev_id}_rgb"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, dev_id)},
            "name": dev_id,
            "manufacturer": "ElectronicsTech",
        }

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def rgb_color(self):
        return self._rgb

    @property
    def brightness(self):
        return self._brightness

    def handle_state(self, payload: dict[str, Any]) -> None:
        if "on" in payload:
            self._is_on = bool(payload["on"])
        if "r" in payload and "g" in payload and "b" in payload:
            self._rgb = (int(payload["r"]), int(payload["g"]), int(payload["b"]))
        if "brightness" in payload:
            self._brightness = int(payload["brightness"])

        if self._pending is not None:
            want_on = bool(self._pending.get("on", self._is_on))
            want_rgb = (
                int(self._pending.get("r", self._rgb[0])),
                int(self._pending.get("g", self._rgb[1])),
                int(self._pending.get("b", self._rgb[2])),
            )
            want_b = int(self._pending.get("brightness", self._brightness))
            if self._is_on == want_on and self._rgb == want_rgb and self._brightness == want_b:
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

    def _send_payload_now(self, payload: dict[str, Any]) -> None:
        self._hub.send_to(
            self._dev_id,
            {
                "v": 1,
                "type": "command",
                "id": self._dev_id,
                "class": "light.rgb",
                "payload": payload,
            },
        )

    def _qos_tick(self, _now=None) -> None:
        if self._pending is None:
            return

        if (time.monotonic() - self._pending_started) > QOS_MAX_TOTAL_S:
            _LOGGER.warning("ET-Bus QoS timeout (light): %s", self._dev_id)
            self._qos_clear()
            return

        self._send_payload_now(self._pending)

        self._pending_try += 1
        delay_idx = min(self._pending_try, len(QOS_RETRY_DELAYS_S) - 1)
        delay = QOS_RETRY_DELAYS_S[delay_idx]
        self._pending_unsub = async_call_later(self.hass, delay, self._qos_tick)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if "rgb_color" in kwargs and kwargs["rgb_color"] is not None:
            self._rgb = kwargs["rgb_color"]
        if "brightness" in kwargs and kwargs["brightness"] is not None:
            self._brightness = int(kwargs["brightness"])
        self._is_on = True

        self._pending = {
            "on": True,
            "r": int(self._rgb[0]),
            "g": int(self._rgb[1]),
            "b": int(self._rgb[2]),
            "brightness": int(self._brightness),
        }
        self._pending_started = time.monotonic()
        self._pending_try = 0
        self._qos_tick()

        if self.hass is not None:
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._is_on = False
        self._pending = {
            "on": False,
            "r": int(self._rgb[0]),
            "g": int(self._rgb[1]),
            "b": int(self._rgb[2]),
            "brightness": int(self._brightness),
        }
        self._pending_started = time.monotonic()
        self._pending_try = 0
        self._qos_tick()

        if self.hass is not None:
            self.async_write_ha_state()


