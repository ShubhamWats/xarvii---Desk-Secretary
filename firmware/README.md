# ESP32-S3 Satellite Firmware (Phase 4)

PlatformIO + pioarduino (Arduino core 3.x on ESP-IDF 5.5). FreeRTOS tasks with
ring buffers for glitch-free I2S audio; WebSocket client multiplexing NDJSON
control and binary PCM frames; PTT button, mute switch, WS2812 status LED.

```
[platformio]
default_envs = esp32-s3

[env:esp32-s3]
platform = https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip
board = esp32-s3-devkitc-1
framework = arduino
monitor_speed = 115200
build_flags =
    -DCORE_DEBUG_LEVEL=1
lib_deps =
    bblanchon/ArduinoJson@^7
    links2004/WebSockets@^2.4
    fastled/FastLED@^3.6
```

## Pin map (v1)

| Function | GPIO |
|---|---|
| INMP441 SCK / WS / SD | 14 / 15 / 16 |
| MAX98357A BCLK / LRC / DIN | 17 / 18 / 8 |
| PTT button (to GND) | 4 |
| Mute switch (to GND) | 5 |
| WS2812 status LED | 48 |

## Module map

| File | Responsibility |
|---|---|
| main.cpp | init chain + loop orchestration |
| proto.cpp/h | frozen protocol v1 codec (both directions) |
| wifi_mgr.cpp | STA connect + AP-portal provisioning fallback |
| ws_client.cpp | reconnecting WS client, text/binary mux, heartbeat |
| audio.cpp | two I2S instances (INMP441 RX / MAX98357A TX), FreeRTOS ring buffers, follow-up VAD |
| buttons.cpp | debounced PTT FSM + mute switch reporting |
| leds.cpp | WS2812 state patterns (breath/solid/spin/pulse/alert) |
| rtc_tones.cpp | SNTP clock + local chime synthesis through the amp |
| storage.cpp | NVS creds + LittleFS reminder cache + offline firing |
| ota.cpp | ElegantOTA web updater (xarvii/update123) |
| power.cpp | deep-sleep hooks (compile-time flag) |
