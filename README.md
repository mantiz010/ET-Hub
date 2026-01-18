# ET-Bus (ElectronicsTech Bus)

ET-Bus is a **low-latency local control bus** for ESP-class devices tightly integrated with **Home Assistant**.

It is designed for **fast, reliable physical control** (relays, pumps, fans, RGB lights, sensors) on a local LAN, **without a broker, cloud service, or persistent sessions**.

ET-Bus prioritizes **state correctness over protocol complexity**.

GitHub: https://github.com/mantiz010/ET-Hub

---

## Why ET-Bus Exists

Many existing solutions optimize for configuration convenience or protocol purity.

ET-Bus is optimized for **engineering reality**:

- Wi-Fi drops packets
- ESPs reboot
- Home Assistant restarts
- Physical devices **must still behave correctly**

ET-Bus is built around one core rule:

> **The ESP publishes the truth.  
> Home Assistant retries until it sees that truth.**

There are:
- no retained commands
- no ACK packets
- no hidden or duplicated state

---

## Key Features

- ⚡ **Very low latency**
  - UDP unicast commands
  - Typical relay response **< 10–20 ms** on LAN
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

ET-Bus is **intentionally asymmetric**.

### ESP devices do:
- Publish `discover`
- Publish `state`
- Apply hardware
- Publish state after every change

### ESP devices do NOT:
- Retry commands
- Track QoS
- Maintain sessions
- Store Home Assistant state

### Home Assistant does:
- Create entities dynamically
- Send commands
- Implement QoS retries
- Treat ESP state as authoritative

This keeps firmware:
- small
- deterministic
- easy to debug
- robust against reboots

---

## System Architecture

### Transport model

- **UDP multicast**
  - Discovery
  - State fan-out
- **UDP unicast**
  - Commands only
  - Lowest possible latency

### High-level flow

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
- no provisioning
- no pairing
- no retained configuration
- no dependency on startup order

---

## Command & Confirmation Flow (Relay Example)

1. User toggles a switch in Home Assistant
2. HA entity sends **unicast command**
3. ESP:
   - receives command
   - applies GPIO
   - publishes multicast `state`
4. HA sees matching state
5. QoS retries stop immediately

There is **no ACK packet**.

**State is confirmation.**

---

## QoS Model (Home Assistant Side)

QoS is implemented **entirely inside Home Assistant entities**.

### How it works

- Command issued
- Retry loop starts
- Each retry sends the **same unicast command**
- When a matching state arrives → **stop retries**
- If confirmation never arrives → stop after hard timeout

### Example Retry Schedule

(Default values, configurable)


This provides:
- instant UI response
- tolerance to packet loss
- no duplicate actions

---

## Failure Modes & Recovery

| Scenario | Behaviour | Result |
|--------|----------|--------|
| UDP packet lost | HA retries | Command succeeds |
| ESP reboots | ESP re-announces | HA converges |
| HA restarts | Hub restarts | Entities reappear |
| Wi-Fi hiccup | QoS retries | Temporary delay |
| Multicast blocked | No discover/state | Devices invisible until fixed |

Failures are **visible and recoverable**, not silent.

---

## ET-Bus vs ESPHome vs MQTT

### Architecture Comparison

| Feature | ET-Bus | ESPHome API | MQTT |
|------|------|------------|------|
| Latency | **Very low** | Medium | Medium–High |
| Transport | UDP | TCP | TCP |
| Sessions | ❌ | ✅ | ✅ |
| Broker required | ❌ | ❌ | ✅ |
| QoS model | State-based | Implicit | Broker-based |
| Offline recovery | Automatic | Limited | Depends on retain |
| Firmware size | **Small** | Medium | Large |
| Debug simplicity | **High** | Medium | Low |

### Practical Differences

**ESPHome**
- Excellent YAML experience
- API sessions can stall on reconnects
- Larger firmware footprint

**MQTT**
- Extremely flexible
- Broker adds latency and failure surface
- Retained messages can cause stale state

**ET-Bus**
- Optimized for **physical correctness**
- No sessions
- No broker
- State is always truth
- Minimal firmware

---

## When ET-Bus Is the Right Choice

- Relays
- Pumps
- Fans
- RGB lighting
- Sensors where **physical correctness > protocol elegance**
- Systems that must recover cleanly after reboots

---

## Arduino ESP Firmware (NOT PlatformIO)

ET-Bus is designed to work cleanly with the **Arduino IDE**.

### Requirements

- ESP32 or ESP8266
- Arduino IDE
- Wi-Fi network
- Home Assistant on the same LAN

### Installing the ETBus Arduino Library

1. Clone or download:
2. Copy the `ETBus` folder into:
3. Restart Arduino IDE
4. Include the library:

## Minimal Relay Example (Arduino)

```cpp
#include <WiFi.h>
#include <ETBus.h>

static const char* WIFI_SSID = "your_wifi";
static const char* WIFI_PASS = "your_pass";
static const int RELAY_PIN = 26;

ETBus etbus;
bool relayOn = false;

void applyRelay(bool on) {
  relayOn = on;
  digitalWrite(RELAY_PIN, on ? HIGH : LOW);
  etbus.sendSwitchState(relayOn); // ESP publishes truth
}

void onCommand(const char*, JsonObject payload) {
  if (payload.containsKey("on")) {
    applyRelay((bool)payload["on"]);
  }
}

void setup() {
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(100);

  etbus.begin("relay1", "switch.relay", "Relay 1", "1.0");
  etbus.onCommand(onCommand);

  // publish initial state
  etbus.sendSwitchState(relayOn);
}

void loop() {
  etbus.loop(); // handle network + incoming commands
}


Notes:
- `custom_components/etbus/www/etbus.html` is served by `panel.py` inside Home Assistant.
- QoS retry logic lives in Home Assistant entities (switch/light/fan), not on the ESP.
- ESP devices only apply hardware and publish state (state is confirmation).
