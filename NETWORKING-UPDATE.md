# Networking feeds: The Register + APNIC

Reddit fetching and OAuth have been removed. Two independently scheduled public RSS sources now populate the existing Networking panel:

- **The Register — Networks:** https://api.theregister.com/api/v1/article?limit=25&orderBy=published&query=tag%3Anetworks&remapper=rss&site_id=2
- **APNIC Blog:** https://blog.apnic.net/feed/

No accounts, API keys, or Reddit credentials are needed. Each source has its own backoff and health status, so failure of one does not prevent the other from being fetched. HTTPS certificate verification remains enabled. The default interval remains 15 minutes.

## Install the patch

1. Quit the dashboard with **Q**. Close any USB serial monitor.
2. Extract `newswire-networking-update.zip` into your existing project folder containing `platformio.ini`. Replace the supplied firmware files and root-level `dashboard.py`. Your `secrets.h` is not included and is not replaced.
3. Reflash from that folder:

```powershell
pio run --target upload
```

4. Restart the dashboard with your current device address:

```powershell
.\.venv\Scripts\python dashboard.py ws://10.0.0.139:81/
```

Look for **REGISTER: ok** and **APNIC: ok** in the bottom strip, and headlines labeled **The Register** or **APNIC** in Networking. No Python dependency changes are required.

The firmware retains the prior TLS and startup-history corrections. It now fetches HN, The Register, APNIC, and EFF before the potentially lengthy NVD/CISA work.

## Settings

The new sources default to enabled even if Reddit was previously disabled. Existing polling, CVSS, and other feed settings are retained. Send these settings through the USB serial monitor if you want to change them:

```json
{"register":true,"apnic":true}
```

The old `reddit` and `subreddit` configuration fields have been removed. Old `REDDIT_*` definitions in your secrets file are unused; removing them is optional. They are not sent to either source.

## Verification

Both public endpoints returned HTTP 200 with RSS 2.0 content in computer-side checks. Their transmitted TLS chains lead to trust anchors present in the firmware bundle. The firmware build and the dashboard tests are checked before packaging. Device-side fetching still needs confirmation after you flash this update.

Source directory: [The Register's published feeds](https://www.theregister.com/design/page/feeds); [APNIC Blog](https://blog.apnic.net/).
