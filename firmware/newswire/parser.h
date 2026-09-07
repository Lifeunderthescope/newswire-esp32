#pragma once
#include <ArduinoJson.h>
#include <functional>
using ObjectHandler = std::function<bool(JsonObjectConst)>;
bool parseArray(Stream& input, const char* key, JsonDocument& filter, ObjectHandler handler, size_t& count);
bool parseRSS(Stream& input);
bool parseRSS(Stream& input, const char* category, const char* source);
float cvssScore(JsonObjectConst cve);
void parserBegin();
void parserFlush();
bool publishItem(const char* category, String title, const char* source, String url,
                 float severity, time_t timestamp, String identity = "");
// True only after successful delivery to the broadcast queue during this boot.
// Persistent history separately controls replay/notification status.
bool alreadySeen(const String& identity);
time_t parseDate(const String& date);
