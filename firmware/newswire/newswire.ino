#include <WiFi.h>
#include <ESPmDNS.h>
#include "secrets.h"
#include "config.h"
#include "broadcast.h"
#include "feed_fetch.h"

void setup() {
  Serial.begin(115200);  // Never wait for a USB host: this device is headless.
  configBegin();
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  broadcastBegin(); // WiFi initialization has brought up the TCP/IP stack.
  configTime(0, 0, "pool.ntp.org", "time.cloudflare.com");
  feedBegin();
}

void loop() {
  static uint32_t retryAt = 0;
  static bool mdns = false;
  if (WiFi.status() == WL_CONNECTED) {
    if (!mdns) {
      mdns = MDNS.begin("newswire");
      if (mdns) MDNS.addService("ws", "tcp", 81);
      Serial.print("WebSocket: ws://"); Serial.print(WiFi.localIP()); Serial.println(":81/");
    }
  } else {
    if (mdns) { MDNS.end(); mdns = false; }
    if (int32_t(millis() - retryAt) >= 0) {
      WiFi.reconnect(); retryAt = millis() + 15000;
    }
  }
  configSerialLoop();
  broadcastLoop();
  delay(2);
}
