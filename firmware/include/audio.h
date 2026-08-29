#pragma once
#include <Arduino.h>

void audioInit();
void audioTaskStart();

enum class AudioMode : uint8_t { IDLE, RECORDING, FOLLOWUP };
void audioSetMode(AudioMode m);
void audioAbortPlayback();           // drain speaker ring instantly
size_t audioSpeakerBuffered();
void speakerEnqueue(uint8_t* data, size_t len);
size_t audioTxWrite(const uint8_t* buf, size_t len);

// called by ws layer on listen_window {seconds}
void audioArmFollowup(uint16_t seconds);

// meeting-mode style tap is daemon-side; device only streams when gated.
