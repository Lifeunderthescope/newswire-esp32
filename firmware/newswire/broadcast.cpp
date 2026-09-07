#include "broadcast.h"
#include "config.h"
#include <WebSocketsServer.h>
#include <WiFi.h>
#include <esp_timer.h>
static WebSocketsServer server(81);
static QueueHandle_t queue;
struct Frame { char data[2048]; };
static String history[64];
// Reserve history for every panel; one busy feed must not evict other categories.
static size_t historyNext[4]{}, historyCount[4]{}, historyBytes[4]{};
static const char* categories[] = {"cybersecurity", "networking", "tech", "privacy"};
static String feedStates[FEED_COUNT];
static const char* feedNames[] = {"hn", "nvd", "cisa", "register", "eff", "apnic"};
static String heartbeat() {
  JsonDocument d;
  d["type"] = "heartbeat"; d["protocol"] = 1;
  d["device"] = "newswire-esp32-s3";
  d["uptime"] = uint64_t(esp_timer_get_time()) / 1000000;
  d["timestamp"] = time(nullptr); d["rssi"] = WiFi.RSSI(); d["free_heap"] = ESP.getFreeHeap();
  for (int i=0;i<FEED_COUNT;++i) d["feeds"][feedNames[i]] = feedStates[i];
  String out; serializeJson(d, out); return out;
}
void broadcastBegin() {
  queue = xQueueCreate(8, sizeof(Frame));
  if (!queue) { Serial.println("FATAL: broadcast queue allocation failed"); while (true) delay(1000); }
  for (auto& state : feedStates) state = "waiting";
  server.begin();
  server.onEvent([](uint8_t client, WStype_t type, uint8_t*, size_t) {
    if (type != WStype_CONNECTED) return;
    String hello = heartbeat(); server.sendTXT(client, hello);
    for (size_t category=0;category<4;++category) {
     for (size_t i=0;i<historyCount[category];++i) {
      size_t slot = category*16 + (historyNext[category] + 16 - historyCount[category] + i) % 16;
      // Replays are explicit; clients suppress notifications for backlog.
      JsonDocument d; deserializeJson(d, history[slot]); d["replay"] = true;
      String out; serializeJson(d, out); server.sendTXT(client, out);
     }
    }
  });
}
bool broadcastEnqueue(JsonDocument& d) {
  Frame f{};
  if (measureJson(d) >= sizeof(f.data)) return false;
  serializeJson(d, f.data, sizeof(f.data));
  return xQueueSend(queue, &f, pdMS_TO_TICKS(1000)) == pdTRUE;
}
void broadcastLoop() {
  server.loop();
  Frame f;
  for (int n=0;n<4 && xQueueReceive(queue, &f, 0) == pdTRUE;++n) {
    JsonDocument d; deserializeJson(d, f.data);
    if (d["type"] == "item") {
      int category=-1;
      for (int i=0;i<4;++i) if (d["category"]==categories[i]) {category=i;break;}
      size_t length = strlen(f.data);
      // Cap bytes as well as item count so TLS retains heap on non-PSRAM boards.
      if (category>=0) {
        auto& count=historyCount[category];auto& next=historyNext[category];auto& bytes=historyBytes[category];
        while (count && (count == 16 || bytes + length > 12*1024)) {
          size_t oldest = category*16 + (next + 16 - count) % 16;
          bytes -= history[oldest].length(); history[oldest] = String(); --count;
        }
        size_t slot=category*16+next;
        history[slot] = f.data;
        if (history[slot].length() == length) {
          bytes += length; next = (next+1)%16; ++count;
        } else history[slot] = String();
      }
    } else if (d["type"] == "feed_status") {
      for (int i=0;i<FEED_COUNT;++i) if (d["feed"] == feedNames[i]) feedStates[i] = d["state"].as<String>();
    }
    server.broadcastTXT(f.data);
  }
  static uint32_t last = 0;
  if (uint32_t(millis()-last) >= 30000) { last = millis(); String h = heartbeat(); server.broadcastTXT(h); }
}
