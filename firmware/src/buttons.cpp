#include <Arduino.h>
#include "pins.h"
#include "ws_client.h"
#include "proto.h"

extern bool g_muted;

static bool lastPtt = false;         // true = pressed
static uint32_t lastChange = 0;
static bool lastMuteLevel = false;

// PTT press also dismisses expired timers server-side (watchdog sees listening state)

void buttonsInit() {
  pinMode(PIN_BTN_PTT, INPUT_PULLUP);
  pinMode(PIN_SW_MUTE, INPUT_PULLUP);
  lastMuteLevel = digitalRead(PIN_SW_MUTE) == LOW;
}

void buttonsLoop() {
  bool pressed = digitalRead(PIN_BTN_PTT) == LOW;
  if (pressed != lastPtt && millis() - lastChange > DEBOUNCE_MS) {
    lastPtt = pressed;
    lastChange = millis();
    Serial.printf("[buttons] PTT %s (g_muted=%d)\n",
                  pressed ? "down" : "up", g_muted);
    if (!g_muted) wsSendJson(buildPtt(pressed));
    else Serial.println("[buttons] PTT ignored while muted");
  }

  bool muteLevel = digitalRead(PIN_SW_MUTE) == LOW;
  if (muteLevel != lastMuteLevel) {
    lastMuteLevel = muteLevel;
    g_muted = muteLevel;
    wsSendJson(buildMute(muteLevel));
    Serial.printf("[buttons] mute=%d (g_muted=%d)\n", muteLevel, g_muted);
  }
}
