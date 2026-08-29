#include <Arduino.h>
#include <WebSocketsClient.h>
#include "ws_client.h"
#include "proto.h"
#include "services.h"
#include "pins.h"

extern SysState g_state;
static WebSocketsClient ws;
static bool connected = false;

bool wsConnected() { return connected; }

void wsSendJson(const String& line) {
  if (connected) {
    String copy = line;                 // lib takes non-const ref
    ws.sendTXT(copy);
  }
}

void wsSendAudio(const uint8_t* data, size_t len) {
  if (connected) ws.sendBIN(data, len);
}

void wsRequestStop() {
  if (connected) { ws.disconnect(); connected = false; }
}

static void onEvent(WStype_t type, uint8_t* payload, size_t len) {
  switch (type) {
    case WStype_CONNECTED: {
      connected = true;
      wsSendJson(buildHello());
      break;
    }
    case WStype_DISCONNECTED:
      if (connected) Serial.println("[ws] disconnected");
      connected = false;
      break;
    case WStype_TEXT:
      handleControl(String((const char*)payload, len));
      break;
    case WStype_BIN:
      extern void onAudioFrame(uint8_t*, size_t);
      onAudioFrame(payload, len);
      break;
    default: break;
  }
}

void wsBegin() {
  String host = serverHost();
  uint16_t port = serverPort();
  Serial.printf("[ws] connecting %s:%u\n", host.c_str(), port);
  ws.begin(host.c_str(), port, "/");
  ws.onEvent(onEvent);
  ws.setReconnectInterval(5000);
  ws.enableHeartbeat(15000, 3000, 2);
}

void wsLoop() {
  static uint32_t lastHb = 0;
  ws.loop();
  if (connected && millis() - lastHb > HEARTBEAT_MS) {
    lastHb = millis();
    wsSendJson(buildHeartbeat());
  }
}
