#include "services.h"
#include "rtc_tones.h"
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <vector>
#include <time.h>

static Preferences nvs;

void storageBegin() {
  LittleFS.begin(true, "/lfs", 10);
}

String wifiSsid() { nvs.begin("xarvii", false); String s = nvs.getString("ssid"); nvs.end(); return s; }
String wifiPass() { nvs.begin("xarvii", false); String s = nvs.getString("pass"); nvs.end(); return s; }
String serverHost() {
  nvs.begin("xarvii", false);
  String s = nvs.getString("host", XARVII_SERVER_HOST_DEFAULT);
  nvs.end(); return s;
}
uint16_t serverPort() { nvs.begin("xarvii", false); uint16_t p = nvs.getUShort("port", 8765); nvs.end(); return p; }

void saveWifi(const String& ssid, const String& pass) {
  nvs.begin("xarvii", false);
  nvs.putString("ssid", ssid); nvs.putString("pass", pass);
  nvs.end();
}
void saveServer(const String& host, uint16_t port) {
  nvs.begin("xarvii", false);
  nvs.putString("host", host); nvs.putUShort("port", port);
  nvs.end();
}

// ---------------- reminder cache (offline firing) ----------------

struct CachedRem { String title; time_t due; bool fired; };
static std::vector<CachedRem> g_cache;
static const char* CACHE_FILE = "/lfs/reminders.json";

static void loadCache() {
  g_cache.clear();
  File f = LittleFS.open(CACHE_FILE, "r");
  if (!f) return;
  JsonDocument doc;
  DeserializationError e = deserializeJson(doc, f);
  f.close();
  if (e) return;
  for (JsonVariant v : doc["items"].as<JsonArray>()) {
    g_cache.push_back({String((const char*)(v["title"] | "Reminder")),
                       (time_t)(v["due"].as<long long>()),
                       v["fired"] | false});
  }
}

static void saveCache() {
  File f = LittleFS.open(CACHE_FILE, "w");
  if (!f) return;
  JsonDocument doc;
  JsonArray arr = doc["items"].to<JsonArray>();
  for (auto& r : g_cache) {
    JsonObject o = arr.add<JsonObject>();
    o["title"] = r.title;
    o["due"] = (long long)r.due;
    o["fired"] = r.fired;
  }
  serializeJson(doc, f);
  f.close();
}

void cacheReminder(const String& title, const String& dueIso) {
  if (dueIso.length() < 10) return;
  struct tm tmv = {};
  // daemon sends ISO "%Y-%m-%dT%H:%M:%S"
  strptime(dueIso.c_str(), "%Y-%m-%dT%H:%M:%S", &tmv);
  time_t due = mktime(&tmv);
  if (due < 0) return;
  loadCache();
  g_cache.push_back({title, due, false});
  saveCache();
}

void clearFiredReminders() {
  loadCache();
  bool changed = false;
  time_t now = time(nullptr);
  for (auto& r : g_cache)
    if (r.fired && now - r.due > 3600) { changed = true; r.fired = true; }
  if (changed) saveCache();
}

void remindersCacheLoop() {
  static uint32_t last = 0;
  if (millis() - last < 1000) return;
  last = millis();
  if (!timeIsValid()) return;
  loadCache();
  time_t now = time(nullptr);
  bool changed = false;
  for (auto& r : g_cache) {
    if (!r.fired && now >= r.due) {
      r.fired = changed = true;
      tonePlay("alert");
      extern void ledFlashAlert();
      ledFlashAlert();
    }
  }
  if (changed) saveCache();
}
