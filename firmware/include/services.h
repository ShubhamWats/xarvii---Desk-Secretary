#pragma once
#include <Arduino.h>

void storageBegin();                 // LittleFS + NVS
String wifiSsid();
String wifiPass();
String serverHost();
uint16_t serverPort();
void saveWifi(const String& ssid, const String& pass);
void saveServer(const String& host, uint16_t port);

// reminder cache (offline firing)
void cacheReminder(const String& title, const String& dueIso);
void clearFiredReminders();
void remindersCacheLoop();           // fires tones when offline & due

void otaBegin();
void otaLoop();

void powerLoop();                    // deep-sleep hooks behind flag
