#include "feed_fetch.h"
#include "config.h"
#include "parser.h"
#include "broadcast.h"
#include "secrets.h"
#include "cert_bundle.h"
#include "hn_roots.h"
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <WiFi.h>
#include <vector>
#include <esp_random.h>
static const char* names[] = {"hn", "nvd", "cisa", "register", "eff", "apnic"};
static uint32_t retryAfterMs=0, lastNvd=0;
static bool nvdRequested=false;
static String failure;

// HTTP/1.0 plus identity encoding provides a plain, unchunked response stream.
// Bound response time and byte count even if a remote server trickles forever.
class BoundedStream : public Stream {
  Client& client; uint32_t started=millis(), lastByte=millis();
  size_t bytes=0;
public:
  BoundedStream(Client& c):client(c){ setTimeout(16000); }
  int available() override { return client.available(); }
  int read() override {
    while(uint32_t(millis()-started)<90000 && uint32_t(millis()-lastByte)<15000 && bytes<12*1024*1024) {
      if(client.available()) {int c=client.read();if(c>=0){++bytes;lastByte=millis();return c;}}
      if(!client.connected()) return -1;
      vTaskDelay(pdMS_TO_TICKS(1));
    }
    return -1;
  }
  int peek() override {return client.peek();}
  size_t write(uint8_t) override {return 0;}
};
using Reader=std::function<bool(Stream&)>;
static String iso(time_t t);
static bool fetch(const String& url, Reader reader, bool nvd=false) {
  if(WiFi.status()!=WL_CONNECTED) {failure="WiFi disconnected";return false;}
  if(nvd) {
    // Public NVD permits 5 requests per rolling 30 seconds; 6.5 s is conservative.
    uint32_t spacing=strlen(NVD_API_KEY)?700:6500;
    if(nvdRequested) while(uint32_t(millis()-lastNvd)<spacing) vTaskDelay(pdMS_TO_TICKS(50));
    lastNvd=millis();nvdRequested=true;
  }
  WiFiClientSecure tls;
  bool hnHost=url.startsWith("https://hn.algolia.com/");
  // Full GTS roots allow normal chain building through HN's cross-signed chain.
  // Do not disable verification or trust the server's leaf certificate.
  if(hnHost) tls.setCACert(NEWS_HN_CA_PEM);
  else tls.setCACertBundle(NEWS_CA_BUNDLE, sizeof(NEWS_CA_BUNDLE));
  tls.setHandshakeTimeout(12);
  HTTPClient http;
  http.useHTTP10(true); http.setTimeout(15000);http.setConnectTimeout(10000);
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);http.setRedirectLimit(3);
  const char* headers[]={"Retry-After", "Content-Encoding", "Transfer-Encoding"};
  http.collectHeaders(headers,3);
  if(!http.begin(tls,url)) {failure="HTTP initialization failed";return false;}
  http.setUserAgent(FEED_USER_AGENT);http.addHeader("Accept-Encoding","identity");
  http.addHeader("Accept", "application/json, application/rss+xml, application/xml");
  if(nvd && strlen(NVD_API_KEY)) http.addHeader("apiKey",NVD_API_KEY);
  Serial.printf("[TLS] %s; UTC %sZ\n",hnHost?"GTS PEM roots":"CA bundle",iso(time(nullptr)).c_str());
  int code=http.GET();
  if(code!=HTTP_CODE_OK) {
    failure=String("HTTP ")+code;
    // Delta seconds honored; HTTP-date Retry-After falls back to exponential backoff.
    uint32_t seconds=http.header("Retry-After").toInt();
    retryAfterMs=max(retryAfterMs,min<uint32_t>(seconds,86400)*1000);
    http.end();return false;
  }
  if((http.header("Content-Encoding").length() && http.header("Content-Encoding")!="identity") || http.header("Transfer-Encoding").length()) {
    failure="Unsupported HTTP encoding";http.end();return false;
  }
  BoundedStream stream(http.getStream());
  bool ok=reader(stream);
  if(!ok && !failure.length()) failure="Invalid/truncated feed or resource limit";
  http.end();return ok;
}
static String iso(time_t t) {
  tm utc{};gmtime_r(&t,&utc);char out[24];strftime(out,sizeof(out),"%Y-%m-%dT%H:%M:%S",&utc);return out;
}
static JsonDocument nvdFilter() {
  JsonDocument f;
  f["cve"]["id"]=true;f["cve"]["published"]=true;
  f["cve"]["descriptions"][0]["lang"]=true;f["cve"]["descriptions"][0]["value"]=true;
  for(const char* v:{"cvssMetricV40","cvssMetricV31","cvssMetricV30","cvssMetricV2"}) f["cve"]["metrics"][v][0]["cvssData"]["baseScore"]=true;
  return f;
}
static bool hn() {
  return fetch("https://hn.algolia.com/api/v1/search?tags=story&hitsPerPage=30&numericFilters=created_at_i%3E"+String(time(nullptr)-7*86400),[](Stream& in){
    JsonDocument f;for(const char* k:{"title","url","objectID","created_at_i"}) f[k]=true;
    size_t count;
    return parseArray(in,"hits",f,[](JsonObjectConst o){
      String id=o["objectID"]|"";String url=o["url"]|"";
      if(!url.length()) url="https://news.ycombinator.com/item?id="+id;
      return publishItem("tech",o["title"]|"","Hacker News",url,-1,o["created_at_i"]|0L);
    },count);
  });
}
static bool registerNews() {
  return fetch("https://api.theregister.com/api/v1/article?limit=25&orderBy=published&query=tag%3Anetworks&remapper=rss&site_id=2",
    [](Stream& in){return parseRSS(in,"networking","The Register");});
}
static bool apnicNews() {
  return fetch("https://blog.apnic.net/feed/",
    [](Stream& in){return parseRSS(in,"networking","APNIC");});
}
static bool nvdRecent(const Settings& s) {
  time_t end=time(nullptr),start=end-s.recentHours*3600;
  for(size_t page=0;page<100;++page) {
    size_t count=0;
    String url="https://services.nvd.nist.gov/rest/json/cves/2.0?lastModStartDate="+iso(start)+"&lastModEndDate="+iso(end)+"&resultsPerPage=50&startIndex="+String(page*50);
    bool ok=fetch(url,[&](Stream& in){
      JsonDocument f=nvdFilter();
      return parseArray(in,"vulnerabilities",f,[&](JsonObjectConst o){
        JsonObjectConst c=o["cve"];float score=cvssScore(c);
        if(score<s.cvss)return true;
        String id=c["id"]|"";String title=id;
        for(JsonObjectConst d:c["descriptions"].as<JsonArrayConst>()) if(d["lang"]=="en"){title+=" — ";title+=d["value"]|"";break;}
        return publishItem("cybersecurity",title,"NVD","https://nvd.nist.gov/vuln/detail/"+id,score,parseDate(c["published"]|""),id);
      },count);
    },true);
    if(!ok)return false;
    if(count<50)return true;
  }
  failure="NVD exceeds 5000 records; narrow recent_hours";return false;
}
struct Kev {String id,title,date;};
static bool cisa(const Settings& s) {
  std::vector<Kev> candidates;candidates.reserve(32);
  time_t cutoff=time(nullptr)-s.kevDays*86400;
  bool ok=fetch("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",[&](Stream& in){
    JsonDocument f;for(const char* k:{"cveID","vulnerabilityName","dateAdded"}) f[k]=true;
    size_t count;
    return parseArray(in,"vulnerabilities",f,[&](JsonObjectConst o){
      String id=o["cveID"]|"";
      if(!id.startsWith("CVE-") || alreadySeen("CISA KEV:"+id) || parseDate(o["dateAdded"]|"")<cutoff) return true;
      if(candidates.size()>=128) {failure="KEV exceeds 128 candidates; narrow kev_days";return false;}
      candidates.push_back({id,o["vulnerabilityName"]|"",o["dateAdded"]|""});return true;
    },count);
  });
  if(!ok)return false;
  // Close CISA's TLS connection before opening NVD: only one TLS session in RAM.
  for(const auto& kev:candidates) {
    float score=-1;size_t count=0;
    ok=fetch("https://services.nvd.nist.gov/rest/json/cves/2.0?cveId="+kev.id,[&](Stream& in){
      JsonDocument f=nvdFilter();
      return parseArray(in,"vulnerabilities",f,[&](JsonObjectConst o){score=cvssScore(o["cve"]);return true;},count);
    },true);
    if(!ok)return false;
    if(score>=s.cvss && !publishItem("cybersecurity",kev.id+" — "+kev.title,"CISA KEV","https://www.cisa.gov/known-exploited-vulnerabilities-catalog",score,parseDate(kev.date),kev.id)) return false;
    // Unscored CVEs are retried on the next poll, not marked as seen.
  }
  return true;
}
static void status(int feed,const String& state) {
  Serial.printf("[%s] %s\n",names[feed],state.c_str());
  JsonDocument d;d["type"]="feed_status";d["feed"]=names[feed];d["state"]=state;
  broadcastEnqueue(d);
}
static void worker(void*) {
  parserBegin();
  uint32_t due[FEED_COUNT]={},flushAt=millis(),lastPoll=0;
  uint8_t failures[FEED_COUNT]={};bool wasEnabled[FEED_COUNT]={true,true,true,true,true,true};
  while(true) {
    Settings s=configSnapshot();
    if(s.pollSeconds!=lastPoll) {for(auto& t:due)t=millis();lastPoll=s.pollSeconds;}
    if(WiFi.status()==WL_CONNECTED && time(nullptr)>1700000000) {
      for(int i : {0,3,5,4,1,2}) {
        if(!s.enabled[i]) {if(wasEnabled[i])status(i,"disabled");wasEnabled[i]=false;continue;}
        if(!wasEnabled[i]) {due[i]=millis();wasEnabled[i]=true;}
        if(int32_t(millis()-due[i])<0)continue;
        retryAfterMs=0;failure="";status(i,"fetching");
        bool ok=false;
        switch(i) {
          case 0:ok=hn();break;
          case 1:ok=nvdRecent(s);break;
          case 2:ok=cisa(s);break;
          case 3:ok=registerNews();break;
          case 5:ok=apnicNews();break;
          case 4:ok=fetch("https://www.eff.org/rss/updates.xml",[](Stream& in){return parseRSS(in);});break;
        }
        if(ok) {failures[i]=0;due[i]=millis()+s.pollSeconds*1000;status(i,"ok");}
        else {
          failures[i]=min(int(failures[i])+1,7);
          uint32_t backoff=min(15000U*(1U<<failures[i]),1800000U);
          uint32_t wait=max(backoff,retryAfterMs)+(esp_random()%3000);
          due[i]=millis()+wait;status(i,"retry in "+String(wait/1000)+"s: "+failure);
        }
        if(uint32_t(millis()-flushAt)>=60000) {parserFlush();flushAt=millis();}
      }
    }
    if(uint32_t(millis()-flushAt)>=60000) {parserFlush();flushAt=millis();}
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}
void feedBegin() {
  if(xTaskCreatePinnedToCore(worker,"feeds",16384,nullptr,1,nullptr,0)!=pdPASS) Serial.println("ERROR: feed task allocation failed; WebSocket remains available");
}
