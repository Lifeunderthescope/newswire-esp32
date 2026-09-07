#include "parser.h"
#include "broadcast.h"
#include <Preferences.h>
#include <math.h>
static Preferences dedupe;
static uint64_t hashes[1024]{};
static uint16_t nextHash = 0;
// NVS decides whether an item is new; RAM decides whether this boot has sent it.
// Persisted hashes alone must not suppress rebuilding the lost replay buffer.
static uint64_t sentThisBoot[1024]{};
static uint16_t nextSent = 0;
static bool dirty = false;
static uint64_t hashOf(const String& s) {
  uint64_t h = 14695981039346656037ULL;
  for (size_t i=0;i<s.length();++i) { h ^= uint8_t(s[i]); h *= 1099511628211ULL; }
  return h ? h : 1;
}
void parserBegin() {
  dedupe.begin("news-seen", false);
  if (dedupe.getBytesLength("hashes") == sizeof(hashes)) dedupe.getBytes("hashes", hashes, sizeof(hashes));
  nextHash = dedupe.getUShort("next", 0) % 1024;
}
void parserFlush() {
  if (!dirty) return;
  if (dedupe.putBytes("hashes", hashes, sizeof(hashes)) == sizeof(hashes)) {
    dedupe.putUShort("next", nextHash); dirty = false;
  }
}
bool alreadySeen(const String& identity) {
  uint64_t h = hashOf(identity);
  for (auto x : sentThisBoot) if (x == h) return true;
  return false;
}
static String clean(String s, size_t maxLen) {
  for (size_t i=0;i<s.length();++i) if (uint8_t(s[i])<32 || uint8_t(s[i])==127) s.setCharAt(i, ' ');
  s.trim();
  if (s.length()>maxLen) {
    size_t end=maxLen;
    while (end && (uint8_t(s[end]) & 0xc0) == 0x80) --end;
    s=s.substring(0,end);
  }
  return s;
}
bool publishItem(const char* category, String title, const char* source, String url,
                 float severity, time_t timestamp, String identity) {
  if (!url.startsWith("https://") && !url.startsWith("http://")) return true;
  if (url.length()>768) return true; // Never broadcast a truncated/broken URL.
  title=clean(title, 420); if (!title.length()) return true;
  if (!identity.length()) identity=url;
  identity=String(source)+":"+identity;
  if (alreadySeen(identity)) return true;
  uint64_t h=hashOf(identity); char id[17]; snprintf(id, sizeof(id), "%016llx", (unsigned long long)h);
  bool replay=false;
  for (auto previous : hashes) if (previous==h) { replay=true; break; }
  JsonDocument d;
  d["type"]="item"; d["protocol"]=1; d["id"]=id;
  d["category"]=category; d["title"]=title; d["source"]=source; d["url"]=url;
  if (severity>=0 && isfinite(severity)) d["severity"]=severity; else d["severity"]=nullptr;
  d["timestamp"]=timestamp>0 ? timestamp : time(nullptr);
  d["replay"]=replay;
  if (!broadcastEnqueue(d)) return false;
  sentThisBoot[nextSent]=h; nextSent=(nextSent+1)%1024;
  if (!replay) { hashes[nextHash]=h; nextHash=(nextHash+1)%1024; dirty=true; }
  return true;
}
time_t parseDate(const String& date) {
  tm t{};
  if (strptime(date.c_str(), "%Y-%m-%dT%H:%M:%S", &t)) return mktime(&t);
  t={};
  if (strptime(date.c_str(), "%Y-%m-%d", &t)) return mktime(&t); // TZ is UTC.
  t={};
  char* zone=strptime(date.c_str(), "%a, %d %b %Y %H:%M:%S", &t);
  if (zone) {
    time_t result=mktime(&t);
    while (*zone==' ') ++zone;
    if ((*zone=='+' || *zone=='-') && strlen(zone)>=5) {
      int offset=(String(zone+1).substring(0,2).toInt()*60 + String(zone+3).substring(0,2).toInt())*60;
      result += *zone=='+' ? -offset : offset;
    }
    return result;
  }
  return 0;
}
float cvssScore(JsonObjectConst cve) {
  // Prefer modern vectors, use maximum across providers within that version.
  for (const char* version : {"cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"}) {
    float score=-1;
    for (JsonObjectConst metric : cve["metrics"][version].as<JsonArrayConst>()) {
      JsonVariantConst v=metric["cvssData"]["baseScore"];
      if (v.is<float>() && isfinite(v.as<float>()) && v.as<float>()>=0 && v.as<float>()<=10) score=max(score, v.as<float>());
    }
    if (score>=0) return score;
  }
  return -1; // Missing scores are never invented or treated as zero.
}
bool parseArray(Stream& in, const char* key, JsonDocument& filter, ObjectHandler handler, size_t& count) {
  count=0;
  String token=String('"')+key+'"';
  if (!in.find(token.c_str()) || !in.find("[")) return false;
  bool first=true;
  while (true) {
    int c;
    do { c=in.read(); if (c<0) return false; } while (isspace(c));
    if (c==']') return true;
    if (!first) {
      if (c!=',') return false;
      do { c=in.read(); if(c<0) return false; } while(isspace(c));
    }
    if (c!='{') return false;
    // Supply the consumed opening brace without buffering the whole response.
    class Prefix : public Stream {
      Stream& base; bool initial=true;
    public:
      Prefix(Stream& b):base(b){}
      int available() override { return initial?1:base.available(); }
      int read() override { if(initial){initial=false;return '{';}return base.read(); }
      int peek() override { return initial?'{':base.peek(); }
      size_t write(uint8_t) override { return 0; }
    } prefixed(in);
    JsonDocument object;
    auto error=deserializeJson(object, prefixed, DeserializationOption::Filter(filter), DeserializationOption::NestingLimit(24));
    if (error || object.overflowed()) return false;
    ++count;
    if (!handler(object.as<JsonObjectConst>())) return false;
    first=false;
    taskYIELD();
  }
}
static String xmlText(String value) {
  value.replace("<![CDATA[", ""); value.replace("]]>", "");
  value.replace("&lt;", "<"); value.replace("&gt;", ">"); value.replace("&quot;", "\""); value.replace("&apos;", "'");
  // Decode numeric XML entities as UTF-8, including non-ASCII titles.
  int at=0;
  while ((at=value.indexOf("&#", at))>=0) {
    int end=value.indexOf(';',at); if(end<0 || end-at>12) { ++at; continue; }
    String number=value.substring(at+2,end); bool hex=number.startsWith("x") || number.startsWith("X");
    char* tail; uint32_t cp=strtoul(number.c_str()+(hex?1:0), &tail, hex?16:10);
    if (*tail || !cp || cp>0x10ffff || (cp>=0xd800 && cp<=0xdfff)) { ++at; continue; }
    String utf;
    if(cp<0x80) utf+=char(cp);
    else if(cp<0x800) {utf+=char(0xc0|(cp>>6));utf+=char(0x80|(cp&63));}
    else if(cp<0x10000) {utf+=char(0xe0|(cp>>12));utf+=char(0x80|((cp>>6)&63));utf+=char(0x80|(cp&63));}
    else {utf+=char(0xf0|(cp>>18));utf+=char(0x80|((cp>>12)&63));utf+=char(0x80|((cp>>6)&63));utf+=char(0x80|(cp&63));}
    value=value.substring(0,at)+utf+value.substring(end+1); at+=utf.length();
  }
  value.replace("&amp;", "&"); value.trim(); return value;
}
bool parseRSS(Stream& in) { return parseRSS(in,"privacy","EFF"); }
bool parseRSS(Stream& in, const char* category, const char* source) {
  // A bounded RSS 2.0 token scanner; descriptions and enclosures are discarded.
  // JSON parsers cannot parse XML. Extract RSS fields, then normalize with ArduinoJson.
  String token, field, title, url, date, text;
  bool item=false, inTag=false, cdata=false, channel=false;
  while (true) {
    int n=in.read(); if(n<0) return false; char c=char(n);
    if (cdata) {
      token+=c;
      if(token.endsWith("]]>")) {
        if(field.length()) text+=token.substring(0,token.length()-3);
        token=""; cdata=false;
      } else if(token.length()>4) {
        if(field.length() && text.length()<2048) text+=token[0];
        token.remove(0,1);
      }
      continue;
    }
    if (inTag) {
      token+=c;
      if(token=="![CDATA[") { inTag=false;cdata=true;token="";continue; }
      if(token.length()>512) return false;
      if(c!='>') continue;
      token.remove(token.length()-1); inTag=false;
      if(token=="channel") channel=true;
      if(token=="/rss") return channel && !item;
      if(token=="item") { item=true;title="";url="";date=""; }
      else if(item && (token=="title" || token=="link" || token=="pubDate")) {field=token;text="";}
      else if(field.length() && token=="/"+field) {
        if(field=="title") title=xmlText(text);
        if(field=="link") url=xmlText(text);
        if(field=="pubDate") date=xmlText(text);
        field="";
      } else if(token=="/item") {
        if(!publishItem(category, title, source, url, -1, parseDate(date))) return false;
        item=false; field="";
      }
      token="";
    } else if(c=='<') {inTag=true;token="";}
    else if(field.length() && text.length()<2048) text+=c;
  }
}
