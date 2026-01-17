from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from typing import Any, Callable

from homeassistant.core import HomeAssistant

from .const import (
    MULTICAST_GROUP,
    MULTICAST_PORT,
    PING_INTERVAL,
    OFFLINE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class EtBusHub:
    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self._sock: socket.socket | None = None
        self._devices: dict[str, dict[str, Any]] = {}
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._tasks: list[asyncio.Task] = []

    @property
    def devices(self) -> dict[str, dict[str, Any]]:
        return dict(self._devices)

    def register_listener(self, cb: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.append(cb)

    # -----------------------------------------------------------
    # START / STOP
    # -----------------------------------------------------------
    async def async_start(self) -> None:
        loop = asyncio.get_running_loop()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            pass

        sock.bind(("", MULTICAST_PORT))

        # Join multicast group
        mreq = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton("0.0.0.0")
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        # Prevent receiving our own multicast packets where supported
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
        except Exception:
            pass

        sock.setblocking(True)
        self._sock = sock

        _LOGGER.info(
            "ET-Bus hub listening on %s:%s", MULTICAST_GROUP, MULTICAST_PORT
        )

        self._tasks.append(self.hass.loop.create_task(self._receiver(loop)))
        self._tasks.append(self.hass.loop.create_task(self._pinger()))

    async def async_stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    # -----------------------------------------------------------
    # SEND
    # -----------------------------------------------------------
    def send(self, message: dict[str, Any]) -> None:
        if not self._sock:
            return
        try:
            data = json.dumps(message, separators=(",", ":")).encode("utf-8")
            self._sock.sendto(data, (MULTICAST_GROUP, MULTICAST_PORT))
        except Exception as e:
            _LOGGER.error("ET-Bus send error: %s", e)

    # -----------------------------------------------------------
    # RECEIVE LOOP
    # -----------------------------------------------------------
    async def _receiver(self, loop) -> None:
        if not self._sock:
            return

        while True:
            try:
                data, addr = await loop.run_in_executor(
                    None, self._sock.recvfrom, 4096
                )
            except asyncio.CancelledError:
                return
            except OSError as e:
                _LOGGER.error("ET-Bus recv error: %s", e)
                await asyncio.sleep(1)
                continue

            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue

            # Update device registry
            self._update_registry(msg, addr)

            # ---------------------------------------------------
            # ✅ STEP 1 FIX — FIRE EVENT TO HA EVENT BUS
            # ---------------------------------------------------
            try:
                msg_with_meta = dict(msg)
                msg_with_meta["_src_ip"] = addr[0]
                msg_with_meta["_rx_ts"] = time.time()
                self.hass.bus.async_fire("etbus_message", msg_with_meta)
            except Exception:
                pass

            # Notify platform listeners (sensor/light/etc)
            for cb in list(self._listeners):
                self.hass.add_job(cb, msg)

    # -----------------------------------------------------------
    # PING LOOP
    # -----------------------------------------------------------
    async def _pinger(self) -> None:
        while True:
            try:
                await asyncio.sleep(PING_INTERVAL)
            except asyncio.CancelledError:
                return

            self.send(
                {
                    "v": 1,
                    "type": "ping",
                    "id": "hub",
                    "class": "hub",
                    "payload": {"ts": int(time.time())},
                }
            )

            now = time.time()
            for dev_id, info in list(self._devices.items()):
                last_seen = info.get("last_seen", 0)
                was_online = info.get("online", False)
                is_online = (now - last_seen) < OFFLINE_TIMEOUT
                if is_online != was_online:
                    info["online"] = is_online
                    state = "online" if is_online else "offline"
                    _LOGGER.warning(
                        "ET-Bus device %s is now %s", dev_id, state
                    )

    # -----------------------------------------------------------
    # DEVICE REGISTRY
    # -----------------------------------------------------------
    def _update_registry(self, msg: dict[str, Any], addr) -> None:
        if msg.get("v") != 1:
            return

        dev_id = msg.get("id")
        if not dev_id:
            return

        # ❌ Never register the hub itself as a device
        if dev_id == "hub":
            return

        dev_class = msg.get("class")
        mtype = msg.get("type")
        payload = msg.get("payload", {}) or {}

        now = time.time()
        dev = self._devices.get(dev_id)

        if not dev:
            dev = {
                "id": dev_id,
                "class": dev_class,
                "name": payload.get("name", dev_id),
                "fw": payload.get("fw"),
                "last_addr": addr[0],
                "last_seen": now,
                "online": True,
            }
            self._devices[dev_id] = dev
            _LOGGER.info("ET-Bus new device: %s (%s)", dev_id, dev_class)
        else:
            dev["class"] = dev_class or dev.get("class")
            dev["name"] = payload.get("name", dev.get("name", dev_id))
            if "fw" in payload:
                dev["fw"] = payload.get("fw")
            dev["last_addr"] = addr[0]
            dev["last_seen"] = now
            dev["online"] = True

        if mtype == "pong":
            if "uptime" in payload:
                dev["uptime"] = payload["uptime"]
            if "rssi" in payload:
                dev["rssi"] = payload["rssi"]
