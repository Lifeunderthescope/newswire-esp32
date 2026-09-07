# Development history

## 2026-09-07 — Working prototype

- Built headless Arduino-framework ESP32-S3 firmware and a four-panel Textual terminal dashboard.
- Added timed HTTPS fetching, NVS settings, CVSS filtering, bounded dedupe, WebSocket delivery, heartbeats, and reconnect handling.
- Corrected Hacker News certificate validation using full GTS trust anchors; see [TLS-FIX.md](TLS-FIX.md).
- Rebuilt startup replay history independently of persisted dedupe and reserved replay capacity per category; see [STARTUP-FIX.md](STARTUP-FIX.md).
- Replaced Reddit after HTTP 403 responses with The Register Networks and APNIC RSS, each with independent status and backoff; see [NETWORKING-UPDATE.md](NETWORKING-UPDATE.md).
- Stopped incoming cybersecurity alerts from advancing the reader's selection; added End to jump to the latest item. Selection is preserved when older history expires, if the selected item is still retained. See [DASHBOARD-UPDATE.md](DASHBOARD-UPDATE.md).
- Python regression suite: 22 tests passed, including reading-position stability during alert bursts and selection preservation after history eviction.

The user flashed via the PlatformIO command line and showed the dashboard online with Hacker News and NVD items. Serial output also showed successful CISA and EFF fetches. Later user feedback reported the system looking good, with alert scrolling as the remaining usability issue. This is user-reported operating evidence; prolonged stability, notification visibility, and all NVS/reconnect scenarios have not been independently verified on hardware.

This repository begins with the completed prototype snapshot. Earlier changes are documented here and in the troubleshooting guides; they are not reconstructed as historical Git commits.
