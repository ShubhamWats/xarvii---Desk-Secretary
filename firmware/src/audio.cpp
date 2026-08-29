#include <Arduino.h>
#include "pins.h"
#include "audio.h"
#include "ws_client.h"

extern SysState g_state;
extern bool g_muted;

#if HAS_AMP_SPEAKER || HAS_I2S_MIC
#include <ESP_I2S.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/ringbuf.h>

#define SPK_RING_SIZE (192 * 1024)

static void i2sInit() {
  i2sRx.setPins(PIN_MIC_SCK, PIN_MIC_WS, -1, PIN_MIC_SD);
  i2sRx.begin(I2S_MODE_STD, AUDIO_RATE,
              I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO);
  // INMP441 outputs 24 msb in a 32-bit frame; let the driver convert
  i2sRx.configureRX(AUDIO_RATE, I2S_DATA_BIT_WIDTH_32BIT,
                    I2S_SLOT_MODE_MONO, I2S_RX_TRANSFORM_32_TO_16);

  i2sTx.setPins(PIN_SPK_BCLK, PIN_SPK_LRC, PIN_SPK_DIN);
  i2sTx.begin(I2S_MODE_STD, AUDIO_RATE,
              I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO);
}

// ---------------- speaker task ----------------
static void spkTask(void*) {
  static int16_t tmp[256];
  for (;;) {
    if (flushSpk) {
      size_t n = 0;
      while (uint8_t* d = (uint8_t*)xRingbufferReceiveUpTo(
                 spkRing, &n, pdMS_TO_TICKS(5), 16384)) {
        vRingbufferReturnItem(spkRing, d);
        if (n < 16384) break;
      }
      flushSpk = false;
    }
    size_t got = 0;
    uint8_t* data = (uint8_t*)xRingbufferReceiveUpTo(
        spkRing, &got, pdMS_TO_TICKS(40), 4096);
    if (!data) { vTaskDelay(pdMS_TO_TICKS(10)); continue; }
    memcpy(tmp, data, got);
    vRingbufferReturnItem(spkRing, data);
    i2sTx.write((uint8_t*)tmp, got);
  }
}

// ---------------- mic + uplink task ----------------
static void micTask(void*) {
  static int16_t conv[FRAME_SAMPLES];

  for (;;) {
    if (mode == AudioMode::IDLE || g_muted) { vTaskDelay(pdMS_TO_TICKS(30)); continue; }

    size_t br = i2sRx.readBytes((char*)conv, sizeof(conv));
    if (br == 0) { vTaskDelay(pdMS_TO_TICKS(1)); continue; }
    size_t n = br / 2;
    if (n == 0) continue;
    float rms = 0;
    for (size_t i = 0; i < n; i++) rms += (float)conv[i] * conv[i];
    rms = sqrtf(rms / (float)n);

    bool send = false;
    if (mode == AudioMode::RECORDING) {
      send = true;
    } else if (mode == AudioMode::FOLLOWUP) {
      uint32_t now = millis();
      if (!fuSpeech && rms > FU_RMS_GATE) {
        fuSpeech = true;
        Serial.println("[followup] voice detected");
        wsSendJson("{\"type\":\"ptt\",\"event\":\"down\"}");
      }
      if (fuSpeech) {
        send = true;
        if (rms <= FU_RMS_GATE) {
          fuSilence += FRAME_MS / 1000.0f;
          if (fuSilence > FU_SILENCE_S) {
            wsSendJson("{\"type\":\"ptt\",\"event\":\"up\"}");
            mode = AudioMode::IDLE;
            fuSpeech = false;
            fuSilence = 0;
            g_state = SysState::IDLE;
            Serial.println("[followup] sent");
            continue;
          }
        } else fuSilence = 0;
      } else if (now > fuDeadline) {
        mode = AudioMode::IDLE;
      }
    }

    if (send) {
      xRingbufferSend(micRing, conv, n * 2, pdMS_TO_TICKS(20));
      size_t got = 0;
      uint8_t* d = (uint8_t*)xRingbufferReceive(micRing, &got, pdMS_TO_TICKS(20));
      if (d) {
        wsSendAudio(d, got);
        vRingbufferReturnItem(micRing, d);
      }
    }
  }
}

// ---------------- public API ----------------

void audioSetMode(AudioMode m) { mode = m; }

void audioAbortPlayback() { flushSpk = true; }

void speakerEnqueue(uint8_t* data, size_t len) {
  if (len) xRingbufferSend(spkRing, data, len, 0);
}

size_t audioTxWrite(const uint8_t* buf, size_t len) {
  return i2sTx.write(buf, len);
}

size_t audioSpeakerBuffered() {
  return SPK_RING_SIZE - xRingbufferGetCurFreeSize(spkRing);
}

void audioArmFollowup(uint16_t seconds) {
  fuDeadline = millis() + seconds * 1000UL;
  mode = AudioMode::FOLLOWUP;
  Serial.printf("[audio] followup armed %us\n", seconds);
}

void audioInit() {
  micRing = xRingbufferCreate(64 * 1024, RINGBUF_TYPE_BYTEBUF);
  spkRing = xRingbufferCreate(SPK_RING_SIZE, RINGBUF_TYPE_BYTEBUF);
  i2sInit();
}

void audioTaskStart() {
  xTaskCreatePinnedToCore(micTask, "mic", 6144, nullptr, 4, nullptr, 0);
  xTaskCreatePinnedToCore(spkTask, "spk", 6144, nullptr, 4, nullptr, 1);
}

#else   // starter build: no audio hardware on the satellite

void audioSetMode(AudioMode) {}
void audioAbortPlayback() {}
size_t audioSpeakerBuffered() { return 0; }
void speakerEnqueue(uint8_t*, size_t) {}
size_t audioTxWrite(const uint8_t* buf, size_t len) { (void)buf; (void)len; return len; }
size_t audioSpeakerBuffered2() { return 0; }
void audioArmFollowup(uint16_t seconds) {
  Serial.printf("[audio] followup window %us ignored (no mic yet)\n", seconds);
}
void audioInit() {}
void audioTaskStart() {}

#endif
