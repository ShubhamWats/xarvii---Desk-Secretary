#pragma once
#include <Arduino.h>

void buttonsInit();
void buttonsLoop();

void ledsInit();
void ledsLoop();                     // pattern render per g_state / alerts
void ledFlashAlert();
