\
#pragma once

#include <WiFi.h>
#include <WiFiUdp.h>
#include <ArduinoJson.h>

class ETBus {
public:
  typedef void (*CommandHandler)(const char* dev_class, JsonObject payload);

  ETBus();

  // Start ET-Bus for a single device/entity (one id + one class)
  void begin(
      const char* device_id,
      const char* device_class,
      const char* device_name,
      const char* fw_version
  );

  // Call often in loop()
  void loop();

  // Optional: handle incoming "command" messages for this device id
  void onCommand(CommandHandler cb);

  // Outgoing messages
  void sendDiscover();
  void sendPong();
  void sendState(JsonObject payload);

  // Convenience helpers for common entities
  void sendSwitchState(bool on);
  void sendRgbState(bool on, uint8_t r, uint8_t g, uint8_t b, uint8_t brightness);

private:
  WiFiUDP _udp;

  const char* _id = nullptr;
  const char* _class = nullptr;
  const char* _name = nullptr;
  const char* _fw = nullptr;

  CommandHandler _cmdHandler = nullptr;

  void _send(const JsonDocument& doc);
  bool _addrMatchesMe(const JsonDocument& doc);
};
