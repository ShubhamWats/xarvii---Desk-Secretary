# Wiring Guide — xarvii satellite (ESP32-S3 DevKitC-1 N16R8)

# ⚠️ READ FIRST — SERIES RESISTORS ARE NOT OPTIONAL

Every LED **must** have a resistor (~330 Ω, anything 220–470 Ω works) in
series with its anode leg. Without it:

* the LED passes 30–40 mA (rated ~15 mA) → overheats and burns out in minutes
* the GPIO driver on the S3 is stressed beyond spec → can degrade or kill the pin
* the whole board's power rail gets noisy → random WiFi/audio glitches

**Firmware mitigation already applied:** the starter build now drives LEDs
through PWM at ~47% duty (`LED_SOFT_LIMIT_DUTY`), halving average current as a
safety net. This is a *backup*, not a substitute for the resistor.

**If you already wired without resistors:** unplug, check each LED still
lights with a 3 V coin cell or multimeter diode mode, add resistors, then
reconnect. Flash the new build before powering again.

---

## 🟡 STARTER BUILD (what you have NOW: 4 LEDs + 2 buttons + breadboard)

Firmware ships with `HAS_LEDS_PLAIN=1`, mic/speaker/WS2812 compiled out.
Voice **input** stays on the laptop (`xarvii device`); this board is a
status orb + remote buttons today, and grows into full audio when the
INMP441/MAX98357A arrive (flip flags in `include/pins.h`).

```
LED leg            series resistor      ESP32-S3 / GND rail
─────────          ───────────────       ───────────────────
GREEN anode  ──▶   330 Ω            ──▶  GPIO 41
BLUE  anode  ──▶   330 Ω            ──▶  GPIO 42
RED   anode  ──▶   330 Ω            ──▶  GPIO 40
YELLOW anode ──▶   330 Ω            ──▶  GPIO 39
(all cathodes)                          → GND

PTT button   one leg GPIO 4, other GND
MUTE switch  one leg GPIO 5, other GND
```

That's it — flash and go. Sections below are for the FULL build later.

---

## 🔊 FULL BUILD (when INMP441 / MAX98357A / WS2812 arrive)

All connections are 3.3 V logic. Double-check before powering.

## INMP441 (I2S microphone)
```
INMP441        ESP32-S3
────────       ────────
VDD     →      3V3
GND     →      GND
L/R     →      GND          (left channel)
SCK     →      GPIO 14      (bit clock)
WS      →      GPIO 15      (word select)
SD      →      GPIO 16      (data out)
```

## MAX98357A (I2S amplifier + speaker)
```
MAX98357A       ESP32-S3
─────────       ────────
VIN     →       5V (VIN pin)
GND     →       GND
BCLK    →       GPIO 17
LRC     →       GPIO 18
DIN     →       GPIO 8
GAIN    →       leave floating (9 dB) or tie to GND for 15 dB
Speaker +/−  →  speaker terminals (4 Ω or 8 Ω)
```

## Controls
```
PTT button   →  one leg GPIO 4, other leg GND     (internal pullup used)
Mute switch  →  one leg GPIO 5, other leg GND     (closed = muted)
WS2812 LED   →  DIN GPIO 48, VCC 5V, GND shared
```

## Power
USB-C from a 5 V/1 A source is sufficient.
The amp draws peaks during loud playback — keep the speaker wires short.

## Notes
- GPIO 35–37 are reserved by the octal PSRAM on N16R8 boards. Never wire there.
- Keep I2S wires <10 cm and away from the WiFi antenna end of the board.
- If the mic produces silence: swap WS/SCK first, then try L/R to 3V3 with
  `I2S_SLOT_MODE_RIGHT` in `audio.cpp`.
