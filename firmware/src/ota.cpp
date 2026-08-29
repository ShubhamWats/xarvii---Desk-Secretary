#include <Arduino.h>
#include <ElegantOTA.h>
#include <WebServer.h>

static WebServer otaServer(80);
static bool started = false;

void otaBegin() {
  if (started) return;
  otaServer.on("/", []() {
    otaServer.send(200, "text/plain",
                   "ElegantOTA UI at /update — user: xarvii pass: update123");
  });
  ElegantOTA.begin(&otaServer, "xarvii", "update123");
  ElegantOTA.setAutoReboot(true);
  otaServer.begin();
  started = true;
  Serial.println("[ota] http://" + WiFi.localIP().toString() + "/update");
}

void otaLoop() {
  if (started) otaServer.handleClient();
}
