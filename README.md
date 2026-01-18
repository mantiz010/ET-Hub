# ET-Bus (ElectronicsTech Bus)

ET-Bus is a **low-latency local control bus** for ESP-class devices tightly integrated with **Home Assistant**.

It is designed for **fast, reliable physical control** (relays, pumps, fans, RGB lights, sensors) on a local LAN, without a broker, cloud service, or persistent sessions.

ET-Bus prioritizes **state correctness over protocol complexity**.

---

## Why ET-Bus Exists

Many existing solutions optimize for configuration convenience or protocol purity.  
ET-Bus is optimized for **engineering reality**:

- Wi-Fi drops packets
- ESPs reboot
- Home Assistant restarts
- Physical devices must still behave correctly

ET-Bus is built around one core rule:

> **The ESP publishes the truth. Home Assistant retries until it sees that truth.**

There are no retained commands, no ACK packets, and no hidden state.

---

## Key Features

- ⚡ **Very low latency**
  - UDP unicast commands
  - Typical relay response < 10–20 ms on LAN
- 🔁 **State-based QoS**
  - Retries stop automatically when state confirms
  - No ACK packets required
- 🔄 **Self-healing**
  - ESP reboot → rediscover + state → HA converges
  - HA restart → entities reappear automatically
- 🌐 **Pure local operation**
  - No broker
  - No cloud
  - No internet dependency
- 🧠 **Simple ESP firmware**
  - ESP publishes state
  - HA handles retries and logic
- 🧩 **Native Home Assistant entities**
  - switch
  - light
  - fan
  - sensor
- 📡 **Multicast discovery & state fan-out**
- 🎯 **Unicast commands for speed**

---

## Design Philosophy

ET-Bus is deliberately **asymmetric**:

### ESP devices
- Publish discover messages
- Publish state messages
- Apply hardware
- Never retry commands
- Never maintain sessions

### Home Assistant
- Creates entities dynamically
- Sends commands
- Implements QoS retries
- Treats ESP state as authoritative

This separation keeps firmware **small, stable, and deterministic**.

---

## System Architecture

High-level flow:

### Transport Summary

- **UDP multicast**
  - Device discovery
  - State fan-out
- **UDP unicast**
  - Commands only
  - Lowest possible latency

---

## Boot & Discovery Flow

1. ESP boots
2. ESP connects to Wi-Fi
3. ESP sends multicast `discover`
4. ESP sends multicast `state`
5. Home Assistant:
   - creates or updates entities
   - associates them with a device
6. UI becomes available immediately

There is:
- no provisioning step
- no pairing
- no retained configuration
- no dependency on HA startup order

---

## Command & Confirmation Flow (Relay Example)

1. User toggles a switch in Home Assistant
2. HA entity sends a **unicast command**
3. ESP:
   - receives command
   - applies GPIO
   - publishes multicast state
4. HA sees matching state
5. QoS retries stop immediately

There is **no ACK packet**.

**State is confirmation.**

---

## QoS Model (Home Assistant Side)

QoS is implemented entirely inside Home Assistant entities.

### How it works
- When a command is issued:
  - HA starts a retry loop
  - Each retry sends the same unicast command
- When a matching state arrives:
  - retries stop immediately
- If confirmation never arrives:
  - retries stop after a hard timeout

### Example Retry Schedule
(Default values, configurable)

- 0 ms
- 50 ms
- 150 ms
- 300 ms
- 600 ms
- hard stop at ~2000 ms

This gives:
- instant UI feedback
- resilience to packet loss
- no duplicated actions

---

## Failure Modes & Recovery

| Scenario | Behaviour | Result |
|-------|----------|--------|
| UDP packet lost | HA retries | Command still succeeds |
| ESP reboots | ESP re-announces | HA converges |
| HA restarts | Hub restarts | Entities reappear |
| Wi-Fi hiccup | QoS retries | Temporary delay only |
| Multicast blocked | No discover/state | Devices invisible until fixed |

ET-Bus fails **safe and visible**, not silently.

---

## ET-Bus vs ESPHome vs MQTT

| Feature | ET-Bus | ESPHome API | MQTT |
|------|------|------------|------|
| Latency | **Very low** | Medium | Medium–High |
| Architecture | Direct LAN | API session | Broker |
| QoS model | State-based | Implicit | Broker-based |
| Broker required | ❌ | ❌ | ✅ |
| Cloud required | ❌ | ❌ | ❌ |
| Offline recovery | Automatic | Limited | Depends on retain |
| Firmware complexity | Low | Medium | High |

### When ET-Bus is the right choice
- Relays
- Pumps
- Fans
- RGB lighting
- Any device where **physical correctness matters more than protocol semantics**

---

## Home Assistant Integration

ET-Bus is implemented as a **custom Home Assistant integration**.

It provides:
- `switch.py`
- `light.py`
- `fan.py`
- `sensor.py`
- central `hub.py`
- optional sidebar UI (HTML)

Entities are created dynamically based on ESP messages.

No YAML configuration is required for devices.

---

## ESP Firmware Model

ESP firmware responsibilities:
- connect to Wi-Fi
- publish `discover`
- publish `state`
- apply hardware changes
- publish state after every change

ESP firmware does **not**:
- retry commands
- track QoS
- maintain sessions
- store HA state

This keeps firmware:
- small
- predictable
- easy to debug
- resilient to restarts

---

## Repository Structure


---

## Project Status

- Actively developed
- Used in real systems
- Designed for LAN reliability
- API stable but evolving
- Not yet a default HACS integration

---

## Future Work

- HACS packaging
- SVG architecture diagrams
- Protocol changelog
- Optional encryption layer
- Extended diagnostics UI

---

## Links

- GitHub: https://github.com/mantiz010/ET-Hub
- Author: ElectronicsTech

