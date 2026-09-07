# Validation record

## Completed

- **22 Python tests passed** on Python 3.11, using the pinned requirements.
- Tested real localhost WebSocket delivery and reconnection, including continuing item traffic after heartbeat loss.
- Tested malformed-frame handling, CVSS validation, literal rendering, dedupe, replay notification suppression, notification dispatch with a mocked OS backend, four category panels, detail view, critical filter, and bounded history.
- Rendered and inspected the colored terminal layout at 120 × 38. `preview.png` contains explicitly simulated example headlines.
- **ESP32-S3 firmware compiled and linked**, and application/factory images were generated with Arduino-ESP32 3.3.11, ArduinoJson 7.4.2, WebSockets 2.7.2, and GCC 14.2.0.
- Final partition table checked: application at `0x10000`, capacity 3,080,192 bytes; NVS at `0x300000`, capacity 65,536 bytes. The generated factory image places the app at the matching `0x10000` address.
- Approximate build footprint: **68 KB static RAM**, **1.27 MB flash**. Heap, task stacks, TLS buffers, and bounded replay storage are allocated at runtime and are not included in the static RAM figure.
- Credential placeholders were used for compilation; the deliverable contains only `secrets.h.example`, never a real `secrets.h` or a preconfigured binary.

## Live source checks from the development computer

HTTPS certificate verification enabled; HTTP/1.0 and identity encoding as in the firmware:

| Source | Result |
| --- | --- |
| Hacker News Algolia | HTTP 200; JSON structure verified |
| CISA KEV | HTTP 200; catalog structure verified |
| NVD | HTTP 200; CVE record structure verified |
| EFF | HTTP 200; RSS parsed successfully |
| The Register Networks RSS | HTTP 200; 25 items; HTTP/1.0, no compression/chunking |
| APNIC RSS | HTTP 200; 30 items; HTTP/1.0, no compression/chunking |

These computer-side requests verify endpoint availability and response formats, **not execution of the firmware parser on a physical ESP32**. They are a point-in-time check, not a guarantee of future feed access.

## Still requires your device/account

- Flashing, WiFi/SNTP/TLS behavior, parser execution, NVS persistence, and long-run heap stability on physical hardware.
- Native desktop notification visibility with your OS notification permissions and focus settings.
- Launching your installed terminal browser from your terminal session.

The isolated Windows build encountered an Espressif launcher path-resolution restriction. Validation used the same underlying compiler, architecture configuration, libraries, and source through a local launcher workaround. The source package retains the standard portable PlatformIO configuration; the workaround and temporary tool copies are not part of the deliverable.

## TLS correction

Hacker News now uses full Mozilla GTS trust anchors instead of the compact bundle callback, which could not complete its cross-signed server chain. A computer-side HTTPS request using only the supplied GTS PEM roots verified successfully and returned HTTP 200. Two certificate structure/anchor regression tests were added. Physical-device confirmation is still required.


## Startup history correction

Persistent seen IDs no longer prevent startup history from being rebuilt. Previously seen items are sent once per boot as silent replays, with separate bounded replay storage for each category. A new real-WebSocket regression test verifies that startup replays populate all four panels without desktop notifications. Physical reboot confirmation remains outstanding.


## Networking replacement

Reddit OAuth and public JSON fetching were removed. Both public RSS sources have independent NVS switches, timers, backoff, and heartbeat status. Existing feed settings survive the migration. The shared RSS parser accepts category/source parameters, retaining EFF behavior. A real-WebSocket test verifies both networking source labels and independent status updates. Both transmitted certificate-chain issuers are present in the compact trust bundle. Firmware compiled successfully; physical-board confirmation remains necessary.

## User-reported hardware progress and reading update

The user successfully flashed with PlatformIO and showed ONLINE status and live Hacker News/NVD items. Serial output showed CISA and EFF success. These observations supersede the earlier flashing/TLS confirmation notes above, but do not establish long-run stability or exhaustive hardware testing. The cybersecurity reading update passed tests for burst scroll stability, End navigation, and selection retention after eviction. See CHANGELOG.md for the project history.
