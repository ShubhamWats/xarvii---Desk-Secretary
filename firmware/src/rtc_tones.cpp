#include "rtc_tones.h"
#include "audio.h"
#include "services.h"

#include <ESP_I2S.h>
#include <time.h>


// ---------------- SNTP clock ----------------

void rtcInit() {
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  setenv("TZ", "IST-5:30", 1);   // default; change via config later
  tzset();
}

bool timeIsValid() { return time(nullptr) > 1700000000; }

void rtcLoop() {
  static uint32_t last = 0;
  if (millis() - last < 1000) return;
  last = millis();
  if (!timeIsValid()) return;
  extern void remindersCacheLoop();
  remindersCacheLoop();
}

// ---------------- local tones through the speaker ----------------

static void beep(float freq, uint16_t ms) {
  const int rate = 16000;
  int16_t buf[64];
  static float phaseacc = 0;
  size_t total = (size_t)(rate * ms / 1000);
  size_t written = 0;
  while (written < total) {
    size_t n = min(total - written, (size_t)64);
    for (size_t i = 0; i < n; i++) {
      phaseacc += 2 * PI * freq / rate;
      if (phaseacc > 2 * PI) phaseacc -= 2 * PI;
      buf[i] = (int16_t)(sinf(phaseacc) * 9000);
    }
    written += audioTxWrite((uint8_t*)buf, n * 2);
  }
}

void tonesInit() {}

void tonePlay(const char* name) {
  if (!strcmp(name, "alert")) {
    beep(880, 120); beep(1175, 160);
  } else if (!strcmp(name, "error")) {
    beep(196, 220);
  } else {
    beep(1319, 70); beep(1760, 90);
  }
}
