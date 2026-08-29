#pragma once
#include <ArduinoJson.h>

// ---- outbound builders (device -> daemon)
String buildHello();
String buildPtt(bool down);
String buildMute(bool on);
String buildHeartbeat();

// ---- inbound dispatch (daemon -> device)
// returns true when the frame was a known control message handled here
bool handleControl(const String& line);

// called by ws layer for binary frames (tts audio)
void onAudioFrame(uint8_t* data, size_t len);
