# NEWSWIRE — ESP32-S3 broadcast console

A headless WiFi news appliance and a four-panel Python terminal dashboard. Networking news comes from The Register and APNIC public RSS feeds. No display, web page, or GUI is used. The ESP32 pushes individual items as they are parsed; the desktop receives them through a LAN WebSocket on port **81**.

See [VALIDATION.md](VALIDATION.md) for completed checks and the remaining hardware/account checks. [preview.png](preview.png) shows the terminal layout with simulated headlines.

## Project history

See [CHANGELOG.md](CHANGELOG.md) for the prototype history and links to the troubleshooting notes. Credentials, virtual environments, build outputs, and local caches are excluded from Git.

## Files

```text
firmware/newswire/
  newswire.ino       boot, WiFi reconnect, main loop
  feed_fetch.cpp    timed HTTPS fetches, pagination, backoff
  parser.cpp        streaming JSON/RSS, CVSS, dedupe
  broadcast.cpp     WebSocket, heartbeat, recent-item replay
  config.cpp        serial settings and NVS persistence
  *.h               module interfaces, generated CA bundle
  secrets.h.example
  partitions.csv    enlarged NVS; supports boards with at least 4 MB flash
dashboard.py        Textual receiver
dashboard.tcss      terminal theme
mock_esp32.py       simulated device and disconnect scenarios
tools/make_cert_bundle.py
tests/              automated dashboard tests
platformio.ini      reproducible Arduino-framework build
```

## Try the dashboard without hardware

Use Python **3.11 or newer**. Run these commands from the extracted `newswire` folder.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python mock_esp32.py
```

In a second terminal, in the same folder:

```powershell
.venv\Scripts\python dashboard.py ws://127.0.0.1:8765/ --no-notifications
```

On Linux/macOS substitute `.venv/bin/python` for `.venv\Scripts\python`. The simulator labels every headline **[SIMULATED]**. Remove `--no-notifications` to exercise your OS notification service.

Use a UTF-8, color-capable terminal such as Windows Terminal, ideally **120 columns × 36 rows** or larger. A smaller terminal still works, with less room for headlines. Terminal fonts are inherently monospace; choose your preferred monospace font in the terminal. `NO_COLOR` is respected; remove that environment variable if you want the green/cyan/magenta/red theme.

## Hardware and wiring

- ESP32-S3 development board with **at least 4 MB flash**; supplied PlatformIO profile is the **ESP32-S3-DevKitC-1 N8** (8 MB, no PSRAM required).
- USB data cable, computer for flashing, and a 2.4 GHz WiFi network.
- **No external wiring, display, LEDs, sensors, or breadboard needed.** USB supplies power and programming. After flashing, a USB power supply is enough.
- For a different S3 board, select its matching PlatformIO `board` and USB settings. Do not assume PSRAM type from the chip name.

## Configure credentials and flash

Copy `firmware/newswire/secrets.h.example` to `firmware/newswire/secrets.h` and fill in `WIFI_SSID` and `WIFI_PASSWORD`. Optionally add an NVD API key. The real secrets file is excluded from version control. Do not put passwords in `config.cpp` or the dashboard.

### PlatformIO (recommended)

Install PlatformIO Core, then:

```powershell
python -m pip install platformio
pio run
pio run --target upload --upload-port COM5
pio device monitor --port COM5 --baud 115200
```

Replace `COM5` with your device port (`/dev/ttyACM0` or similar on Linux). The project pins Arduino-ESP32 **3.3.11**, ArduinoJson **7.4.2**, and WebSockets **2.7.2** via the pioarduino platform. A first build downloads the compiler and libraries.

If upload does not connect: hold **BOOT**, tap **RESET**, release BOOT, and retry. The supplied flags use native USB CDC; a board connected through its USB-to-UART port may require disabling those flags and using that port instead. Never wait for Serial in `setup()`—the supplied sketch boots without a connected computer.

### Arduino IDE alternative

1. Install Espressif's **esp32 3.3.11** board package and the same ArduinoJson/WebSockets library versions above.
2. Open `firmware/newswire/newswire.ino`; keep all `.cpp`, `.h`, and `partitions.csv` files together in that sketch folder.
3. Select your S3 board, its actual flash size, the correct port, and USB CDC On Boot for native USB. Leave PSRAM disabled for the N8 profile.
4. Use the included sketch-local **custom partitions.csv**. Check the build log confirms it is used: the factory app starts at `0x10000` (size `0x2F0000`), and the 64 KiB NVS region starts at `0x300000`. The normal small NVS layout is insufficient for repeated 8 KiB dedupe snapshots. PlatformIO sets this path explicitly.
5. Compile and upload; open Serial Monitor at **115200**, newline ending enabled.

The custom layout is a single factory application with enlarged NVS; OTA updating and a filesystem are not implemented. Changing an existing device's partition layout can discard earlier settings; back up any existing application data first.

## Connect your computer

After WiFi joins, Serial prints an address such as `ws://192.168.1.42:81/`. Connect using that address:

```powershell
.venv\Scripts\python dashboard.py ws://192.168.1.42:81/
```

The default is `ws://newswire.local:81/`, advertised through mDNS. If `.local` resolution is unavailable, use the printed IP or a DHCP reservation. The computer and ESP32 must be able to reach each other on the LAN; guest-network client isolation can prevent that.

The header distinguishes **ONLINE**, **CONNECTED — awaiting heartbeat**, and **OFFLINE — reconnecting…**. A valid heartbeat arrives on connection and every 30 seconds, carries device uptime, and includes per-feed health. A missing heartbeat triggers a reconnect after 75 seconds even when item traffic continues. Retry delays grow from approximately 1 to 30 seconds with jitter. Uptime is device uptime, not time spent running the dashboard.

## Controls

Cybersecurity alerts keep your selection steady as new items arrive. Press **End** to jump to the newest item in the focused panel. History is limited to 200 items per category; the oldest items expire at that limit.

| Key | Action |
| --- | --- |
| Tab / Shift+Tab | Move between panels |
| 1 / 2 / 3 / 4 | Focus Cybersecurity / Networking / General Tech / Privacy |
| Up / Down, Page Up / Page Down, mouse wheel | Navigate and scroll the focused category |
| Enter | Expand the selected item; Enter or Escape closes it |
| O | Open selected URL in a terminal browser |
| F | Toggle critical-only Cybersecurity view (CVSS ≥ 9); other panels stay visible |
| Q | Quit |
| End | Select the newest item in the focused panel |

The dashboard never opens a GUI browser. **O** detects `w3m`, `lynx`, or `links`, temporarily suspends Textual, then returns when you exit the browser. Or supply `--url-command "w3m"` (arguments are supported; the URL is appended as one argument without a shell). On Windows, a WSL terminal is the easiest way to use a terminal browser. Without one, Expand still displays the URL and O explains the missing dependency. Terminal suspension must be supported by the terminal/OS.

Every newly received, non-replay Cybersecurity item queues an OS notification through `plyer`, regardless of which application has focus. **[!]** marks scores ≥ 9. The critical filter only changes the view; it does not silence high-severity notifications. OS notification permissions, Focus Assist/Do Not Disturb, and desktop services can affect delivery. On Linux a running desktop notification service is needed; a bare SSH session usually has none. `--no-notifications` disables this feature. Delivery errors appear in the bottom status strip and never terminate the receiver.

## NVS-backed settings

Send **one JSON object per line** through the USB serial console (115200 baud, newline ending). Send `show` to read the current settings. Unknown keys, wrong types, or out-of-range values reject the whole object before saving.

```json
{"poll_seconds":900,"cvss_threshold":7.0,"recent_hours":48,"kev_days":7,"hn":true,"nvd":true,"cisa":true,"register":true,"apnic":true,"eff":true}
```

Examples:

```json
{"poll_seconds":300,"cvss_threshold":8.0}
```

```json
{"register":true,"apnic":true}
```

| Setting | Default | Allowed |
| --- | --- | --- |
| `poll_seconds` | 900 (15 min) | Integer 60–86400 |
| `cvss_threshold` | 7.0 | Number 0–10, inclusive |
| `recent_hours` | 48 | Integer 1–168, NVD last-modified lookback |
| `kev_days` | 7 | Integer 1–30, CISA date-added lookback |
| `hn`, `nvd`, `cisa`, `register`, `apnic`, `eff` | true | Boolean feed switches |

Settings persist across reboot. A running fetch finishes with its current snapshot; new settings apply when the worker next checks. Changing the polling interval schedules feeds immediately at that check. Other changes apply to the next scheduled fetch. Feed toggles do not cancel in-flight TLS connections. Poll intervals are measured from completion, and requests are serialized to fit ESP32 memory, so a slow feed or substantial NVD pagination can delay another feed. WebSocket and heartbeat handling continue independently.

## Feed behavior

| Feed | Selection and category |
| --- | --- |
| Hacker News Algolia | 30 stories from the last seven days, relevance-ranked; General Tech |
| NVD CVE API 2.0 | Records modified during `recent_hours`, paginated in batches of 50; locally filtered by CVSS |
| CISA KEV | Streams the catalog; entries added during `kev_days` are enriched with NVD scores before filtering |
| The Register — Networks | Up to 25 articles from its published Networks RSS feed; Networking |
| APNIC Blog | Public RSS feed covering Internet operations and infrastructure; Networking |
| EFF Deeplinks | RSS 2.0 feed at `https://www.eff.org/rss/updates.xml`; Privacy |

**CISA does not publish CVSS in its KEV catalog.** A KEV entry is broadcast only after NVD returns a score at or above the configured threshold. Missing scores are not fabricated; those KEVs are revisited on subsequent polls. This means some known exploited vulnerabilities will be absent until scored. CVSS 4.0 is preferred, then 3.1, 3.0, and 2.0, taking the highest available provider score within that version. CISA and NVD alerts for the same CVE are intentionally separate source records.

NVD requests are spaced by at least 6.5 seconds without a key or 700 ms with a key. Avoid sharing a public-IP rate budget with many other NVD clients. HTTP errors—including access restrictions/403s and rate limits/429s—are reported per feed, backed off exponentially up to 30 minutes, and retried with jitter. Numeric `Retry-After` is honored up to 24 hours; HTTP-date variants use normal backoff.

The Register and APNIC need no OAuth credentials. Their new NVS switches default to enabled; the old `reddit` and `subreddit` fields are removed. See [NETWORKING-UPDATE.md](NETWORKING-UPDATE.md) for upgrade steps.

HTTPS validates hostnames and certificate chains against Mozilla trust anchors. Hacker News uses full GTS PEM roots to support its cross-signed chain; other feeds use the compact CA bundle. See [TLS-FIX.md](TLS-FIX.md) for the certificate correction. SNTP must establish time before fetching; the dashboard can connect before time sync succeeds. DNS, TLS, and body reads have finite timeouts. The feed worker never invokes WebSocket APIs across threads. JSON arrays are streamed through ArduinoJson filters one record at a time; RSS uses a bounded XML tokenizer because ArduinoJson cannot parse XML. Both normalize into the same ArduinoJson item message.

Resource limits: 12 MiB / 90 seconds per response, 15-second stalled-body timeout, 128 recent KEV candidates, and 5000 NVD records per poll. Hitting a bound reports a feed failure rather than silently claiming success; narrow the relevant lookback. The 2048-byte outbound frame limit includes titles capped at 420 UTF-8 bytes and URLs up to 768 bytes. Overlong URLs are skipped rather than truncated. Memory exhaustion or malformed input makes a fetch fail rather than rebooting the board intentionally.

## Dedupe, replay, and delivery scope

The device keeps **1024 FNV-1a 64-bit hashes**, keyed by source plus URL (CVE ID for vulnerability sources). An item is marked seen only once queued successfully. NVS checkpoints are batched roughly once a minute at fetch boundaries to limit flash writes; abrupt power loss can repeat items since the last checkpoint. Hash collisions are theoretically possible; very old entries can reappear after eviction. Reflashing while retaining NVS retains dedupe state.

Startup fetches rebuild history by sending previously seen items as silent replays once per boot. The ESP32 reserves **16 items / 12 KiB per category (64 items / 48 KiB total) in RAM** and replays that history to a new connection with `replay:true`. The dashboard keeps **200 items per category** and 10,000 recently seen IDs in memory. Replay and duplicate IDs do not trigger desktop notifications. These are bounded recent-history buffers, not a durable event broker: items outside the replay window can be missed during long disconnections, and history is lost when the corresponding process/device restarts. The desktop notification queue holds 256 pending alerts; overflow is reported and the item remains visible in the panel.

The WebSocket is **unauthenticated plaintext LAN transport**. Use it on your trusted network; no router port forwarding is required. Remote access would need a VPN or an authenticated TLS gateway. Settings are changed locally over USB, not through unauthenticated WebSocket messages.

## Protocol v1

One JSON object per text frame; UTC timestamps are Unix seconds and severity is numeric CVSS or null:

```json
{"type":"item","protocol":1,"id":"0123456789abcdef","category":"cybersecurity","title":"CVE-... — example","source":"NVD","url":"https://nvd.nist.gov/vuln/detail/CVE-...","severity":9.8,"timestamp":1788739200,"replay":false}
```

Categories: `cybersecurity`, `networking`, `tech`, `privacy`.

```json
{"type":"heartbeat","protocol":1,"device":"newswire-esp32-s3","uptime":123,"timestamp":1788739200,"rssi":-55,"free_heap":100000,"feeds":{"hn":"ok","nvd":"fetching"}}
```

```json
{"type":"feed_status","feed":"register","state":"retry in 60s: HTTP 403"}
```

Malformed frames are ignored. Feed text is rendered literally and terminal control characters are removed. Only HTTP(S) item URLs are accepted.

## Tests and maintenance

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

The suite exercises actual local WebSocket connections, stale heartbeats despite ongoing item traffic, reconnects, malformed input, dedupe, replay notification suppression, native notification dispatch through a mock, filter/expand controls, and bounded histories. It does not require ESP32 hardware.

Manual reconnect scenarios, each with a fresh simulator process:

```powershell
.venv\Scripts\python mock_esp32.py --drop-after 10
.venv\Scripts\python mock_esp32.py --silent-after 5
```

For the second scenario, the default dashboard should declare offline around 75 seconds after the last heartbeat even though headlines still arrive.

To refresh the CA bundle, update `certifi` and run:

```powershell
.venv\Scripts\python tools/make_cert_bundle.py
pio run
```

The generator targets the compact **ESP-IDF 5.5+** certificate-bundle format used by the pinned Arduino core. Do not substitute an older core without regenerating an appropriate bundle. Native desktop notification display, WiFi reconnection, HTTPS behavior, and long-run heap stability still require validation on your physical board and desktop session.

Primary references: [Textual](https://textual.textualize.io/), [websockets](https://websockets.readthedocs.io/), [ArduinoJson streaming](https://arduinojson.org/v7/how-to/deserialize-a-very-large-document/), [arduinoWebSockets](https://github.com/Links2004/arduinoWebSockets), [NVD API](https://nvd.nist.gov/developers/vulnerabilities), [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog), [HN Algolia API](https://hn.algolia.com/api), [EFF RSS](https://www.eff.org/rss), and [Espressif certificate bundle format](https://github.com/espressif/esp-idf/blob/v5.5.2/components/mbedtls/esp_crt_bundle/gen_crt_bundle.py).


