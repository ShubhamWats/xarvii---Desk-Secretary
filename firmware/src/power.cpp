#include <Arduino.h>
#include "pins.h"

// Deep sleep is OFF by default (desk device is USB-powered).
// Enable with -DENABLE_DEEPSLEEP and set idle hours below.

#ifndef IDLE_SLEEP_AFTER_MIN
#define IDLE_SLEEP_AFTER_MIN 240
#endif

extern bool g_muted;
extern SysState g_state;

void powerLoop() {
#if defined(ENABLE_DEEPSLEEP)
  static uint32_t lastActivity = 0;
  bool activity = (g_state != SysState::IDLE) || (!g_muted);
  // PTT press wakes via ext1; here we just track idle time
  if (activity) lastActivity = millis();
  if (lastActivity && millis() - lastActivity > IDLE_SLEEP_AFTER_MIN * 60000UL) {
    Serial.println("[power] deep sleep");
    delay(50);
    esp_sleep_enable_ext1_wakeup(1ULL << PIN_BTN_PTT, ESP_EXT1_WAKEUP_ANY_LOW);
    esp_deep_sleep_start();
  }
#endif
}
