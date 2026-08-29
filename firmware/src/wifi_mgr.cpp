#include <Arduino.h>
#include "pins.h"
#include "ws_client.h"
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include "services.h"

extern bool g_muted;

void storageBegin();
String wifiSsid(); String wifiPass();

// ---------------- wifi with AP-portal provisioning fallback ---------------

static void startPortal() {
  extern SysState g_state;
  g_state = SysState::WIFI_SETUP;
  Serial.println("[wifi] PROVISIONING MODE");
  Serial.println("[wifi] 1) Join WiFi: xarvii-setup (pass: xarvii1234)");
  Serial.println("[wifi] 2) Open:   http://192.168.4.1");

  WiFi.mode(WIFI_AP);
  WiFi.softAP("xarvii-setup", "xarvii1234", 1, 0, 4);
  IPAddress ip = WiFi.softAPIP();
  Serial.printf("[wifi] portal IP: %s\n", ip.toString().c_str());

  DNSServer dns;
  dns.start(53, "*", ip);          // catch-all: any domain → portal

  WebServer portal(80);
  portal.on("/", [&]() {
    String html =
      "<!doctype html><html><head><meta charset=utf-8>"
      "<meta name=viewport content='width=device-width,initial-scale=1'>"
      "<style>body{font-family:system-ui;background:#111;color:#eee;"
      "display:flex;justify-content:center;padding-top:60px}"
      "form{background:#222;padding:30px;border-radius:12px}"
      "input{display:block;width:100%;padding:10px;margin:8px 0;"
      "border-radius:6px;border:1px solid #555;background:#333;color:#eee}"
      "button{width:100%;padding:12px;background:#5eead4;color:#000;"
      "border:none;border-radius:8px;font-weight:bold;font-size:16px}"
      "h2{text-align:center}</style></head><body><form action='/save' method='POST'>"
      "<h2>◈ xarvii setup</h2>"
      "WiFi SSID<br><input name='s' placeholder='your wifi name'><br>"
      "WiFi password<br><input name='p' type='password'><br>"
      "Laptop IP<br><input name='h' placeholder='e.g. 192.168.1.100'><br>"
      "Port<br><input name='o' value='8765'><br>"
      "<button>Save & reboot</button></form></body></html>";
    portal.send(200, "text/html", html);
  });
  portal.on("/save", [&]() {
    if (portal.hasArg("s")) saveWifi(portal.arg("s"), portal.arg("p"));
    if (portal.hasArg("h")) {
      uint16_t port = (uint16_t)portal.arg("o").toInt();
      if (!port) port = 8765;
      saveServer(portal.arg("h"), port);
    }
    portal.send(200, "text/html",
                "<h2 style='color:teal'>Saved! Rebooting…</h2>");
    delay(1200);
    ESP.restart();
  });
  // captive portal: all unknown URLs → setup page
  portal.onNotFound([&]() {
    portal.sendHeader("Location", "http://" + ip.toString());
    portal.send(302, "text/plain", "");
  });
  portal.begin();

  while (true) {
    dns.processNextRequest();
    portal.handleClient();
    delay(2);
  }
}

bool wifiConnect(uint32_t timeout_ms = 20000) {
  String ssid = wifiSsid(), pass = wifiPass();
  if (ssid.isEmpty()) return false;
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid.c_str(), pass.c_str());
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < timeout_ms)
    delay(100);
  return WiFi.status() == WL_CONNECTED;
}

void wifiBegin() {
  if (!wifiConnect()) startPortal();   // never returns until provisioned+reboot
}
