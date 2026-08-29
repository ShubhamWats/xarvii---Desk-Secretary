#include <Arduino.h>
#include "pins.h"

extern SysState g_state;
extern bool g_muted;

static uint32_t lastBlink = 0;
static bool blinkOn = false;
static uint32_t alertUntil = 0;

// Soft current limiting: PWM at reduced duty. Set LED_SOFT_LIMIT_DUTY to 255
// once ~330R series resistors are fitted for full brightness.
#ifndef LED_SOFT_LIMIT_DUTY
#define LED_SOFT_LIMIT_DUTY 120      // ~47% duty -> roughly halves LED current
#endif
#ifndef LED_PWM_FREQ
#define LED_PWM_FREQ 5000
#endif

static const uint8_t PLAIN_PINS[4] = {LED_GREEN, LED_BLUE, LED_RED, LED_YELLOW};

static void plainLed(uint8_t pin, bool on) {
  ledcWrite(pin, on ? LED_SOFT_LIMIT_DUTY : 0);
}

void ledFlashAlert() {
  alertUntil = millis() + 2500;
  plainLed(LED_GREEN, false);
  plainLed(LED_BLUE, false);
}

void ledsInit() {
#if HAS_LEDS_PLAIN
  for (uint8_t pin : PLAIN_PINS)
    ledcAttach(pin, LED_PWM_FREQ, 8);
  for (uint8_t pin : PLAIN_PINS) plainLed(pin, false);
#endif
}

void ledsLoop() {
#if HAS_LEDS_PLAIN
  if (g_muted) {
    plainLed(LED_GREEN, false);
    plainLed(LED_BLUE, false);
    plainLed(LED_RED, true);           // solid red = muted
    return;
  }
  if (millis() < alertUntil) {
    if (millis() - lastBlink > 120) {
      lastBlink = millis();
      blinkOn = !blinkOn;
      plainLed(LED_RED, blinkOn);
    }
    return;
  }

  switch (g_state) {
    case SysState::LISTENING:
      plainLed(LED_GREEN, false);
      plainLed(LED_BLUE, true);
      break;
    case SysState::THINKING:
      if (millis() - lastBlink > 150) {
        lastBlink = millis();
        blinkOn = !blinkOn;
        plainLed(LED_BLUE, blinkOn);
      }
      break;
    case SysState::SPEAKING:
      plainLed(LED_BLUE, false);
      plainLed(LED_RED, true);
      break;
    case SysState::WIFI_SETUP:
      if (millis() - lastBlink > 250) {
        lastBlink = millis();
        blinkOn = !blinkOn;
        plainLed(LED_YELLOW, blinkOn);
      }
      break;
    default:
      plainLed(LED_BLUE, false);
      plainLed(LED_RED, false);
      plainLed(LED_GREEN, true);
  }
#endif
}
