from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
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
                ent = EtBusRgbLight(hub, dev_id, name)
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

    def __init__(self, hub: EtBusHub, dev_id: str, name: str):
        self._hub = hub
        self._dev_id = dev_id
        self._attr_name = name

        self._is_on = False
        self._rgb = (255, 255, 255)
        self._brightness = 255

        # ✅ Registry-safe stable unique_id:
        self._attr_unique_id = f"etbus_{dev_id}_rgb"

        # ✅ One device per ET-Bus node (matches switch/fan/sensor)
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

        if self.hass is not None:
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        if "rgb_color" in kwargs and kwargs["rgb_color"] is not None:
            self._rgb = kwargs["rgb_color"]
        if "brightness" in kwargs and kwargs["brightness"] is not None:
            self._brightness = int(kwargs["brightness"])
        self._is_on = True
        self._send_command()
        if self.hass is not None:
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._is_on = False
        self._send_command()
        if self.hass is not None:
            self.async_write_ha_state()

    def _send_command(self) -> None:
        self._hub.send(
            {
                "v": 1,
                "type": "command",
                "id": self._dev_id,
                "class": "light.rgb",
                "payload": {
                    "on": self._is_on,
                    "r": int(self._rgb[0]),
                    "g": int(self._rgb[1]),
                    "b": int(self._rgb[2]),
                    "brightness": int(self._brightness),
                },
            }
        )
