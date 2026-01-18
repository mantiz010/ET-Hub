from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.switch import SwitchEntity
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

        endpoint = dev_class.replace(".", "_")
        key = (dev_id, endpoint)

        if mtype in ("discover", "state", "pong"):
            if key not in entities:
                name = payload.get("name", dev_id)
                ent = EtBusSwitch(hass, hub, dev_id, dev_class, endpoint, name)
                entities[key] = ent
                async_add_entities([ent])
                _LOGGER.info("ET-Bus: discovered %s %s", dev_class, dev_id)

            if mtype == "state":
                entities[key].handle_state(payload)

    hub.register_listener(handle_message)


class EtBusSwitch(SwitchEntity):
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, hub: EtBusHub, dev_id: str, dev_class: str, endpoint: str, name: str):
        self.hass = hass
        self._hub = hub
        self._dev_id = dev_id
        self._dev_class = dev_class

        self._attr_name = name
        self._is_on = False
        self._extra: dict[str, Any] = {}

        self._pending_want: bool | None = None
        self._pending_started: float = 0.0
        self._pending_try: int = 0
        self._pending_unsub = None

        self._attr_unique_id = f"etbus_{dev_id}_{endpoint}"
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

        if self._pending_want is not None and self._is_on == self._pending_want:
            self._qos_clear()

        if self.hass is not None:
            self.async_write_ha_state()

    def _qos_clear(self) -> None:
        self._pending_want = None
        self._pending_try = 0
        self._pending_started = 0.0
        if self._pending_unsub:
            try:
                self._pending_unsub()
            except Exception:
                pass
        self._pending_unsub = None

    def _send_command_now(self) -> None:
        self._hub.send_to(
            self._dev_id,
            {
                "v": 1,
                "type": "command",
                "id": self._dev_id,
                "class": self._dev_class,
                "payload": {"on": self._is_on},
            },
        )

    def _qos_tick(self, _now=None) -> None:
        if self._pending_want is None:
            return

        if self._is_on == self._pending_want:
            self._qos_clear()
            return

        if (time.monotonic() - self._pending_started) > QOS_MAX_TOTAL_S:
            _LOGGER.warning("ET-Bus QoS timeout: %s want=%s", self._dev_id, self._pending_want)
            self._qos_clear()
            return

        self._send_command_now()

        self._pending_try += 1
        delay_idx = min(self._pending_try, len(QOS_RETRY_DELAYS_S) - 1)
        delay = QOS_RETRY_DELAYS_S[delay_idx]
        self._pending_unsub = async_call_later(self.hass, delay, self._qos_tick)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._is_on = True
        self._pending_want = True
        self._pending_started = time.monotonic()
        self._pending_try = 0
        self._qos_tick()
        if self.hass is not None:
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._is_on = False
        self._pending_want = False
        self._pending_started = time.monotonic()
        self._pending_try = 0
        self._qos_tick()
        if self.hass is not None:
            self.async_write_ha_state()
