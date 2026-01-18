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

# key -> entity
# key format: "<entry_id>:<dev_id>:<endpoint>:<metric>"
_ENTITIES: dict[str, "EtBusValueSensor"] = {}


def _endpoint_from_class(cls: str) -> str:
    return cls.replace(".", "_")


def _entity_key(entry_id: str, dev_id: str, endpoint: str, metric: str) -> str:
    return f"{entry_id}:{dev_id}:{endpoint}:{metric}"


@dataclass
class _Msg:
    entry_id: str
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
        if msg.get("v") != 1:
            return
        if msg.get("type") != "state":
            return

        dev_id = msg.get("id")
        cls = msg.get("class")
        payload = msg.get("payload") or {}

        if not dev_id or not cls:
            return

        # Only sensors
        if not cls.startswith("sensor."):
            return

        if not isinstance(payload, dict):
            return

        _process_state(async_add_entities, _Msg(entry.entry_id, dev_id, cls, payload))

    hub.register_listener(_on_message)
    _LOGGER.info("ET-Bus sensor platform ready")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    prefix = f"{entry.entry_id}:"
    to_delete = [k for k in list(_ENTITIES.keys()) if k.startswith(prefix)]
    for k in to_delete:
        _ENTITIES.pop(k, None)
    _LOGGER.info("ET-Bus sensor platform unloaded (%d cached entities cleared)", len(to_delete))
    return True


@callback
def _process_state(async_add_entities: AddEntitiesCallback, m: _Msg) -> None:
    endpoint = _endpoint_from_class(m.cls)

    # Case A: single-value
    if "value" in m.payload:
        metric = m.cls.replace("sensor.", "") or "value"
        _get_or_create_and_update(async_add_entities, m, endpoint, metric, m.payload.get("value"), m.payload)
        return

    # Case B: multi-metric
    for metric, value in m.payload.items():
        if metric in ("unit",):
            continue
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            continue
        _get_or_create_and_update(async_add_entities, m, endpoint, str(metric), value, m.payload)


def _get_or_create_and_update(
    async_add_entities: AddEntitiesCallback,
    m: _Msg,
    endpoint: str,
    metric: str,
    value: Any,
    payload: dict[str, Any],
) -> None:
    k = _entity_key(m.entry_id, m.dev_id, endpoint, metric)

    ent = _ENTITIES.get(k)
    if ent is None:
        ent = EtBusValueSensor(m.dev_id, m.cls, endpoint, metric)
        _ENTITIES[k] = ent
        async_add_entities([ent])
        _LOGGER.info("ET-Bus created sensor: %s", k)

    ent.handle_value(value, payload)


class EtBusValueSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True

    def __init__(self, dev_id: str, cls: str, endpoint: str, metric: str):
        self._dev_id = dev_id
        self._cls = cls
        self._endpoint = endpoint
        self._metric = metric
        self._native_value = None

        self._attr_unique_id = f"etbus_{dev_id}_{endpoint}_{metric}"

        pretty = {
            "temp": "Temperature",
            "temperature": "Temperature",
            "humidity": "Humidity",
            "co2": "CO2",
        }.get(metric.lower(), metric)
        self._attr_name = pretty

        self._attr_device_info = {
            "identifiers": {(DOMAIN, dev_id)},
            "name": dev_id,
            "manufacturer": "ElectronicsTech",
        }

        mlow = metric.lower()
        if mlow in ("temp", "temperature"):
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        elif mlow in ("humidity", "rh"):
            self._attr_native_unit_of_measurement = PERCENTAGE
        elif mlow == "co2":
            self._attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION

    @property
    def native_value(self):
        return self._native_value

    def handle_value(self, value: Any, payload: dict[str, Any]) -> None:
        self._native_value = value

        unit = payload.get("unit")
        if unit and not getattr(self, "_attr_native_unit_of_measurement", None):
            self._attr_native_unit_of_measurement = unit

        if self.hass is not None:
            self.async_write_ha_state()
