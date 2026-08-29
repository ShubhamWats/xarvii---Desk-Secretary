#pragma once
#include <Arduino.h>

void wsBegin();
void wsLoop();                       // call every loop iteration
bool wsConnected();
void wsSendJson(const String& line);
void wsSendAudio(const uint8_t* data, size_t len);
void wsRequestStop();                // graceful close (provisioning etc.)
