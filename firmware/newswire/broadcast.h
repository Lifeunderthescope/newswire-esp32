#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
void broadcastBegin();
void broadcastLoop();
// Worker-to-loop transfer: only the Arduino loop touches WebSocketsServer.
bool broadcastEnqueue(JsonDocument& document);
