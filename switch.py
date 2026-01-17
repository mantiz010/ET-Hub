from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    entities: dict[tuple[str, str], EtBusSwitch] = {}

    @callback
    def handle_message(msg: dict[str, Any]) -> None:
        if msg.get("v") != 1:
            return

        mtype = msg.get("type")
        dev_id = msg.get("id")
        dev_class = msg.get("class")
        payload = msg.get("payload", {}) or {}

        if not dev_id or dev_class not in ("switch.relay", "switch.pump"):
            return

        # endpoint must be stable
        endpoint = dev_class.replace(".", "_")
        key = (dev_id, endpoint)

        if mtype in ("discover", "state", "pong"):
            if key not in entities:
                name = payload.get("name", dev_id)
                ent = EtBusSwitch(hub, dev_id, dev_class, endpoint, name)
                entities[key] = ent
                async_add_entities([ent])
                _LOGGER.info("ET-Bus: discovered %s %s", dev_class, dev_id)

            if mtype == "state":
                entities[key].handle_state(payload)

    hub.register_listener(handle_message)


class EtBusSwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = True

    def __init__(self, hub: EtBusHub, dev_id: str, dev_class: str, endpoint: str, name: str):
        self._hub = hub
        self._dev_id = dev_id
        self._dev_class = dev_class

        self._attr_name = name
        self._is_on = False
        self._extra: dict[str, Any] = {}

        # ✅ Registry-safe, stable across restarts:
        # etbus_<dev_id>_<endpoint>
        self._attr_unique_id = f"etbus_{dev_id}_{endpoint}"

        # ✅ One device per ET-Bus node, consistent across ALL platforms
        self._attr_device_info = {
            "identifiers": {(DOMAIN, dev_id)},
            "name": dev_id,
            "manufacturer": "ElectronicsTech",
        }

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def extra_state_attributes(self):
        return self._extra

    def handle_state(self, payload: dict[str, Any]) -> None:
        if "on" in payload:
            self._is_on = bool(payload["on"])

        extra = dict(payload)
        extra.pop("on", None)
        self._extra = extra

        if self.hass is not None:
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
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
                "class": self._dev_class,
                "payload": {"on": self._is_on},
            }
        )
