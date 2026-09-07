# Hacker News certificate fix

The supplied PlatformIO versions are correct. Hacker News currently sends a chain through a GTS root cross-signed by GlobalSign. The compact ESP32 bundle verifier follows the transmitted chain to the GlobalSign issuer, which is absent from the supplied Mozilla trust store. A desktop verifier can instead terminate at the trusted GTS root. This explains why the earlier computer-side HTTPS test passed while the board reported a verification failure.

The patch uses the available full GTS root certificates from the same Mozilla trust store for Hacker News, allowing normal mbedTLS chain construction. Hostname, certificate signature, and validity checks remain enabled. Other feeds retain the compact bundle. No WiFi credentials or NVS settings change.

1. Extract `newswire-tls-fix.zip` **inside your existing newswire project folder**, replacing the included files. The archive contains `firmware/newswire/feed_fetch.cpp`, `firmware/newswire/hn_roots.h`, the updated certificate generator, and this note. It does not contain `secrets.h`.
2. Disconnect the browser serial terminal so it releases the USB port.
3. In your project's PowerShell terminal, run:

```powershell
pio run --target upload
pio device monitor --baud 115200
```

Use your previous `--upload-port` / `--port` arguments if you needed them before. No full flash erase is needed.

Expect `[TLS] GTS PEM roots; UTC ...` followed by `[hn] ok`. A successful fetch with no new headlines may simply mean items were already deduplicated. If verification still fails, capture the printed UTC time and the full error lines; a wrong device clock or a different network certificate chain would need a separate diagnosis.

The revised firmware is compile-checked; confirmation of this fix on your physical board is still needed.

Implementation reference: [Espressif 5.5.5 certificate-bundle verifier](https://github.com/espressif/esp-idf/blob/v5.5.5/components/mbedtls/esp_crt_bundle/esp_crt_bundle.c).

