#include "config.h"
#include <ArduinoJson.h>
#include <Preferences.h>
#include <math.h>
static Settings settings;
static SemaphoreHandle_t lock;
static Preferences prefs;

Settings configSnapshot() {
  xSemaphoreTake(lock, portMAX_DELAY);
  Settings copy = settings;
  xSemaphoreGive(lock);
  return copy;
}
void configBegin() {
  lock = xSemaphoreCreateMutex();
  if (!lock) { Serial.println("FATAL: config mutex allocation failed"); while (true) delay(1000); }
  prefs.begin("news-config", false);
  settings.pollSeconds = constrain(prefs.getUInt("poll", 900), 60U, 86400U);
  settings.cvss = prefs.getFloat("cvss", 7);
  if (!isfinite(settings.cvss) || settings.cvss < 0 || settings.cvss > 10) settings.cvss = 7;
  settings.recentHours = constrain(prefs.getUShort("hours", 48), 1, 168);
  settings.kevDays = constrain(prefs.getUShort("kevdays", 7), 1, 30);
  for (int i=0; i<FEED_COUNT; ++i) {
    String key=i==3 ? "register" : i==5 ? "apnic" : String("e")+i;
    settings.enabled[i]=prefs.getBool(key.c_str(),true);
  }
}
static void printSettings() {
  Settings s = configSnapshot();
  JsonDocument d;
  d["poll_seconds"] = s.pollSeconds; d["cvss_threshold"] = s.cvss;
  d["recent_hours"] = s.recentHours; d["kev_days"] = s.kevDays;
  const char* names[] = {"hn", "nvd", "cisa", "register", "eff", "apnic"};
  for (int i=0;i<FEED_COUNT;++i) d[names[i]] = s.enabled[i];
  serializeJson(d, Serial); Serial.println();
}
static void apply(const String& line) {
  if (line == "show") { printSettings(); return; }
  JsonDocument d;
  if (deserializeJson(d, line) || !d.is<JsonObject>()) { Serial.println("ERROR: send show or a JSON settings object"); return; }
  Settings s = configSnapshot();
  for (JsonPair p : d.as<JsonObject>()) {
    String k = p.key().c_str(); JsonVariant v = p.value();
    if (k == "poll_seconds" && v.is<uint32_t>() && v.as<uint32_t>() >= 60 && v.as<uint32_t>() <= 86400) s.pollSeconds = v;
    else if (k == "cvss_threshold" && v.is<float>() && isfinite(v.as<float>()) && v.as<float>() >= 0 && v.as<float>() <= 10) s.cvss = v;
    else if (k == "recent_hours" && v.is<uint16_t>() && v.as<int>() >= 1 && v.as<int>() <= 168) s.recentHours = v;
    else if (k == "kev_days" && v.is<uint16_t>() && v.as<int>() >= 1 && v.as<int>() <= 30) s.kevDays = v;
    else {
      const char* names[] = {"hn", "nvd", "cisa", "register", "eff", "apnic"}; bool matched = false;
      for (int i=0;i<FEED_COUNT;++i) if (k == names[i] && v.is<bool>()) { s.enabled[i] = v; matched = true; }
      if (!matched) { Serial.println("ERROR: unknown key, wrong type, or out-of-range value; nothing saved"); return; }
    }
  }
  prefs.putUInt("poll", s.pollSeconds); prefs.putFloat("cvss", s.cvss);
  prefs.putUShort("hours", s.recentHours); prefs.putUShort("kevdays", s.kevDays);
  for (int i=0;i<FEED_COUNT;++i) prefs.putBool((i==3 ? String("register") : i==5 ? String("apnic") : String("e")+i).c_str(), s.enabled[i]);
  xSemaphoreTake(lock, portMAX_DELAY); settings = s; xSemaphoreGive(lock);
  printSettings();
}
void configSerialLoop() {
  static String line; static bool overflow = false;
  // Bounded work per loop preserves heartbeat scheduling under serial floods.
  for (int n=0; n<64 && Serial.available(); ++n) {
    char c = Serial.read();
    if (c == '\n') { if (!overflow) apply(line); else Serial.println("ERROR: line too long"); line = ""; overflow = false; }
    else if (c != '\r') { if (line.length() < 512) line += c; else overflow = true; }
  }
}
