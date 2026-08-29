#pragma once
#include <Arduino.h>
#include <time.h>

void rtcInit();                      // SNTP config (called post-wifi)
void rtcLoop();                      // fire cached reminders offline
bool timeIsValid();

void tonesInit();
void tonePlay(const char* name);     // confirm | error | alert
