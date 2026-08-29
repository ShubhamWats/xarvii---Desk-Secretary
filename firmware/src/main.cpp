#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include "pins.h"
#include "ws_client.h"
#include "audio.h"
#include "io.h"
#include "services.h"

SysState g_state = SysState::BOOT;
bool g_muted = false;

// cross-module prototypes (defined in their .cpp files)
void wifiBegin();
void rtcInit();
void otaBegin();
void otaLoop();
void powerLoop();
void rtcLoop();
void tonesInit();
void remindersCacheLoop();

void setup() {
  Serial.begin(115200);
  delay(200);
  pinMode(PIN_BTN_PTT, INPUT_PULLUP);
  pinMode(PIN_SW_MUTE, INPUT_PULLUP);

  storageBegin();
  ledsInit();
  audioInit();
  audioTaskStart();
  buttonsInit();
  tonesInit();
  g_state = SysState::IDLE;

  wifiBegin();                       // blocks in AP-portal if unprovisioned
  rtcInit();
  wsBegin();
  otaBegin();
}

void loop() {
  wsLoop();
  buttonsLoop();
  ledsLoop();
  rtcLoop();
  otaLoop();
  powerLoop();
  delay(1);
}
