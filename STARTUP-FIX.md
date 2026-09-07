# Empty dashboard after ESP32 reboot

The original firmware persisted headline hashes in NVS but kept replay headlines only in RAM. After reboot, it skipped previously seen headlines while its replay buffer was empty. A successful feed status therefore did not necessarily populate a newly opened dashboard.

The correction tracks delivery during the current boot separately from persistent history. Startup fetches send previously seen items as `replay:true`; the dashboard displays them without desktop notifications. Newly discovered items still trigger the normal alert behavior. Subsequent polls suppress duplicates during that boot. CISA's early dedupe check also uses current-boot delivery, allowing its old entries to be re-enriched and replayed after restart.

Existing bounded-history limits still apply: the device reserves up to 16 items / 12 KiB for each category (64 items / 48 KiB total) for reconnecting clients, and the hash rings retain 1024 IDs. This rebuilds available feed history; it is not a full persistent news archive.

## Apply

1. Extract `newswire-startup-fix.zip` inside the existing project folder (the one containing `platformio.ini`). Replace the supplied parser and broadcast files. Keep the earlier TLS patch installed. No credentials or settings are changed.
2. Close any serial monitor that is using the USB port. Run:

```powershell
pio run --target upload
```

3. Start or leave the dashboard connected:

```powershell
.\.venv\Scripts\python dashboard.py ws://10.0.0.139:81/
```

Use the device's current IP if it changed. Headlines populate as each startup fetch completes. General Tech should fill when HN reports `ok`; Privacy follows EFF. NVD pagination and CISA enrichment can take longer. Reddit still needs authorized OAuth access to resolve its separate HTTP 403.

No NVS erase is needed. Replay suppression in the dashboard is already supported, so no dashboard update is required.

