from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfTemperature,
    PERCENTAGE,
    CONCENTRATION_PARTS_PER_MILLION,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_ENTITIES: dict[str, "EtBusValueSensor"] = {}


def _endpoint_from_class(cls: str) -> str:
    # sensor.temp -> sensor_temp
    return cls.replace(".", "_")


def _key(dev_id: str, endpoint: str) -> str:
    # ✅ No entry_id in keys (prevents duplicates across reloads)
    return f"{dev_id}:{endpoint}"


@dataclass
class _Msg:
    dev_id: str
    cls: str
    payload: dict[str, Any]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = hass.data[DOMAIN][entry.entry_id]

    @callback
    def _on_message(msg: dict[str, Any]) -> None:
        # hub calls listeners on HA loop thread via hass.add_job()
        if msg.get("v") != 1:
            return
        if msg.get("type") != "state":
            return

        dev_id = msg.get("id")
        cls = msg.get("class")
        payload = msg.get("payload") or {}

        if not dev_id or not cls:
            return

        # ✅ CRITICAL FIX:
        # Only create HA Sensor entities for sensor.* classes.
        # Prevents switch/fan/light classes from becoming "Unknown sensors".
        if not cls.startswith("sensor."):
            return

        _process_state(async_add_entities, _Msg(dev_id, cls, payload))

    hub.register_listener(_on_message)
    _LOGGER.info("ET-Bus sensor platform ready")


@callback
def _process_state(async_add_entities: AddEntitiesCallback, m: _Msg) -> None:
    endpoint = _endpoint_from_class(m.cls)
    k = _key(m.dev_id, endpoint)

    ent = _ENTITIES.get(k)
    if ent is None:
        ent = EtBusValueSensor(m.dev_id, m.cls, endpoint)
        _ENTITIES[k] = ent
        async_add_entities([ent])
        _LOGGER.info("ET-Bus created sensor: %s", k)

    ent.handle_state(m.payload)


class EtBusValueSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True

    def __init__(self, dev_id: str, cls: str, endpoint: str):
        self._dev_id = dev_id
        self._cls = cls
        self._endpoint = endpoint
        self._native_value = None

        # ✅ Stable unique_id: etbus_<dev_id>_<endpoint>
        self._attr_unique_id = f"etbus_{dev_id}_{endpoint}"

        # entity name within the device (because _attr_has_entity_name = True)
        self._attr_name = cls.replace("sensor.", "")

        # ✅ One device per ET-Bus node (matches switch/fan/light)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, dev_id)},
            "name": dev_id,
            "manufacturer": "ElectronicsTech",
        }

        # common unit mapping
        if cls == "sensor.temp":
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        elif cls == "sensor.humidity":
            self._attr_native_unit_of_measurement = PERCENTAGE
        elif cls == "sensor.co2":
            self._attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION

    @property
    def native_value(self):
        return self._native_value

    def handle_state(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return

        self._native_value = payload.get("value")

        unit = payload.get("unit")
        if unit and not getattr(self, "_attr_native_unit_of_measurement", None):
            self._attr_native_unit_of_measurement = unit

        if self.hass is not None:
            self.async_write_ha_state()
