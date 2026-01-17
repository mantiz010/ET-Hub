\
#include "ETBus.h"

static IPAddress ETBUS_MCAST(239, 10, 0, 1);
static const uint16_t ETBUS_PORT = 5555;

ETBus::ETBus() {}

void ETBus::begin(const char* device_id,
                  const char* device_class,
                  const char* device_name,
                  const char* fw_version) {
  _id = device_id;
  _class = device_class;
  _name = device_name;
  _fw = fw_version;

  // Join multicast group (ESP32 Arduino core 2.x signature)
  // Arduino-ESP32 2.0.x signature is beginMulticast(multicastIP, port)
  // (Some examples show a 3-arg variant; ESP32 core 2.0.17 uses 2 args.)
  _udp.beginMulticast(ETBUS_MCAST, ETBUS_PORT);

  sendDiscover();
  sendPong();
}

void ETBus::onCommand(CommandHandler cb) {
  _cmdHandler = cb;
}

void ETBus::loop() {
  int size = _udp.parsePacket();
  if (size <= 0) return;

  char buf[512];
  int len = _udp.read(buf, sizeof(buf) - 1);
  if (len <= 0) return;
  buf[len] = 0;

  StaticJsonDocument<512> doc;
  if (deserializeJson(doc, buf)) return;

  if (doc["v"] != 1) return;

  const char* type = doc["type"] | "";
  if (!type[0]) return;

  // Always answer hub ping (broadcast)
  if (strcmp(type, "ping") == 0) {
    sendPong();
    return;
  }

  // Only handle commands for my device id
  if (strcmp(type, "command") == 0) {
    if (!_addrMatchesMe(doc)) return;

    if (_cmdHandler) {
      JsonObject payload = doc["payload"].as<JsonObject>();
      _cmdHandler(_class, payload);
    }
    return;
  }
}

bool ETBus:: _addrMatchesMe(const JsonDocument& doc) {
  const char* id = doc["id"] | "";
  if (!id[0] || !_id) return false;
  return strcmp(id, _id) == 0;
}

void ETBus::sendDiscover() {
  StaticJsonDocument<256> doc;
  doc["v"] = 1;
  doc["type"] = "discover";
  doc["id"] = _id;
  doc["class"] = _class;

  JsonObject p = doc.createNestedObject("payload");
  p["name"] = _name;
  p["fw"] = _fw;

  _send(doc);
}

void ETBus::sendPong() {
  StaticJsonDocument<256> doc;
  doc["v"] = 1;
  doc["type"] = "pong";
  doc["id"] = _id;
  doc["class"] = _class;

  JsonObject p = doc.createNestedObject("payload");
  p["uptime"] = millis() / 1000;
  p["rssi"] = WiFi.RSSI();

  _send(doc);
}

void ETBus::sendState(JsonObject payload) {
  StaticJsonDocument<512> doc;
  doc["v"] = 1;
  doc["type"] = "state";
  doc["id"] = _id;
  doc["class"] = _class;

  // Copy payload into document
  JsonObject p = doc.createNestedObject("payload");
  for (JsonPair kv : payload) {
    p[kv.key()] = kv.value();
  }

  _send(doc);
}

void ETBus::sendSwitchState(bool on) {
  StaticJsonDocument<64> doc;
  doc["v"] = 1;
  doc["type"] = "state";
  doc["id"] = _id;
  doc["class"] = _class;
  JsonObject p = doc.createNestedObject("payload");
  p["on"] = on;
  _send(doc);
}

void ETBus::sendRgbState(bool on, uint8_t r, uint8_t g, uint8_t b, uint8_t brightness) {
  StaticJsonDocument<96> doc;
  doc["v"] = 1;
  doc["type"] = "state";
  doc["id"] = _id;
  doc["class"] = _class;
  JsonObject p = doc.createNestedObject("payload");
  p["on"] = on;
  p["r"] = r;
  p["g"] = g;
  p["b"] = b;
  p["brightness"] = brightness;
  _send(doc);
}

void ETBus::_send(const JsonDocument& doc) {
  char buffer[512];
  size_t len = serializeJson(doc, buffer, sizeof(buffer));

  // ESP32 core 2.0.17 WiFiUDP does NOT have beginPacketMulticast().
  // beginPacket() works fine for multicast destinations.
  _udp.beginPacket(ETBUS_MCAST, ETBUS_PORT);
  _udp.write((const uint8_t*)buffer, len);
  _udp.endPacket();
}
