#pragma once
#include <Arduino.h>
constexpr int FEED_COUNT = 6;
struct Settings {
  uint32_t pollSeconds = 900;
  float cvss = 7.0f;
  uint16_t recentHours = 48;
  uint16_t kevDays = 7;
  bool enabled[FEED_COUNT] = {true, true, true, true, true, true};
};
void configBegin();
Settings configSnapshot();
void configSerialLoop();
