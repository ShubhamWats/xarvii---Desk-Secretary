#pragma once
#include <Arduino.h>

// ---- pins (DevKitC-1 N16R8; GPIO35-37 reserved by OPI PSRAM)
#define PIN_MIC_SCK   14
#define PIN_MIC_WS    15
#define PIN_MIC_SD    16
#define PIN_SPK_BCLK  17
#define PIN_SPK_LRC   18
#define PIN_SPK_DIN   8
#define PIN_BTN_PTT   4      // to GND, internal pullup, active-low
#define PIN_SW_MUTE   5      // to GND, active-low = muted
#define PIN_LED       48     // WS2812 (future)

// ---- starter build feature flags (flip to 1 when parts arrive)
#define HAS_AMP_SPEAKER 0     // MAX98357A + speaker
#define HAS_I2S_MIC     0     // INMP441
#define HAS_WS2812      0     // addressable LED
#define HAS_LEDS_PLAIN  1     // discrete LEDs on GPIOs

// plain status LEDs (active-HIGH through ~330R resistors)
#define LED_GREEN      41     // idle / connected
#define LED_BLUE       42     // listening / thinking (blink while thinking)
#define LED_RED        40     // speaking / muted-red / alert
#define LED_YELLOW     39     // warning / provisioning

// ---- audio
#define AUDIO_RATE        16000
#define FRAME_MS          20
#define FRAME_SAMPLES     (AUDIO_RATE / 1000 * FRAME_MS)         // 320
#define FRAME_BYTES       (FRAME_SAMPLES * 2)                    // 640
#define MIC_SHIFT         14                                     // INMP441 32bit -> int16
#define SPK_PREBUFFER_BYTES (AUDIO_RATE * 2 * 2 / 5)            // 0.4 s
#define WS_AUDIO_CHUNK    1280                                   // 40 ms per binary frame

// ---- follow-up window tuning (satellite contract recommendations)
#define FU_RMS_GATE       500.0f
#define FU_SILENCE_S      1.2f

// ---- timers
#define HEARTBEAT_MS      15000
#define DEBOUNCE_MS       30

enum class SysState : uint8_t {
  BOOT, WIFI_SETUP, IDLE, LISTENING, THINKING, SPEAKING, ERROR
};

extern SysState g_state;
extern bool g_muted;
