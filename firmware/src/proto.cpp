#include "proto.h"
#include "pins.h"
#include "ws_client.h"
#include "audio.h"
#include "io.h"
#include "services.h"
#include "rtc_tones.h"
#include <ArduinoJson.h>

extern SysState g_state;
extern bool g_muted;

static String mk(const char* type) {
  JsonDocument doc;
  doc["type"] = type;
  String out;
  serializeJson(doc, out);
  return out;
}

String buildHello() {
  JsonDocument d;
  d["type"] = "hello";
  d["device"] = "esp32s3-n16r8";
  d["fw"] = XARVII_FW_VERSION;
  d["proto"] = 1;
  String o; serializeJson(d, o); return o;
}

String buildPtt(bool down) {
  JsonDocument d;
  d["type"] = "ptt";
  d["event"] = down ? "down" : "up";
  String o; serializeJson(d, o); return o;
}

String buildMute(bool on) {
  JsonDocument d;
  d["type"] = "mute";
  d["on"] = on;
  String o; serializeJson(d, o); return o;
}

String buildHeartbeat() { return mk("heartbeat"); }

void onAudioFrame(uint8_t* data, size_t len) {
  extern void speakerEnqueue(uint8_t* data, size_t len);
  speakerEnqueue(data, len);
}

bool handleControl(const String& line) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, line);
  if (err) return false;

  const char* type = doc["type"] | "";

  if (!strcmp(type, "welcome")) { }
  else if (!strcmp(type, "state")) {
    const char* to = doc["to"] | "";
    if      (!strcmp(to, "idle"))     g_state = SysState::IDLE;
    else if (!strcmp(to, "listening"))g_state = SysState::LISTENING;
    else if (!strcmp(to, "thinking")) g_state = SysState::THINKING;
    else if (!strcmp(to, "speaking")) g_state = SysState::SPEAKING;
  }
  else if (!strcmp(type, "abort")) {
    extern void audioAbortPlayback();
    audioAbortPlayback();
  }
  else if (!strcmp(type, "listen_window")) {
    uint16_t secs = doc["seconds"] | 10;
    extern void audioArmFollowup(uint16_t);
    audioArmFollowup(secs);
  }
  else if (!strcmp(type, "transcript")) { }
  else if (!strcmp(type, "chime")) {
    tonePlay(doc["name"] | "confirm");
  }
  else if (!strcmp(type, "reminder")) {
    cacheReminder(doc["title"] | "Reminder", doc["due"] | "");
  }
  else if (!strcmp(type, "heartbeat")) {
    wsSendJson(buildHeartbeat());
  }
  else if (!strcmp(type, "error")) { }
  else return false;
  return true;
}
