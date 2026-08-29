# Flashing & Building

## 1. One-time toolchain

```bash
pip install platformio            # or: pipx install platformio
cd firmware
pio run                            # first run downloads toolchain (~10 min)
```

Expected first-build result: `SUCCESS` (or small errors we patch together).

## 2. Provisioning flow (first boot)

1. Flash: `pio run -t upload`
2. Monitor: `pio device monitor`
3. No Wi-Fi stored? Device opens **AP portal**:
   - Join SSID `xarvii-setup` / password `xarvii1234`
   - Open `http://192.168.4.1`
   - Enter your home Wi-Fi + the laptop's server host and port `8765`
     - Host options: `xarvii.local` (mDNS, advertised by the daemon) — if the
       device can't resolve `.local`, find the laptop IP with `hostname -I`
       and provision that instead.
   - Device saves & reboots

The daemon advertises itself as `xarvii.local` via mDNS (zeroconf), so no
static IPs needed.

## 3. OTA updates (no cable)

Once running, browse to:

```
http://<device-ip>/update      user: xarvii   pass: update123
```

Upload a new `.bin` built with `pio run`. Device reboots into it.

## 4. Troubleshooting

| Symptom | Fix |
|---|---|
| Boot loop right after flash | PSRAM flag mismatch — confirm `memory_type = qio_opi` |
| Mic records silence | Swap SCK/WS; try L/R to 3V3 + RIGHT slot mode |
| Speaker hiss/crackle | Shorten wires; ensure common GND between S3 and amp |
| WS never connects | Daemon reachable? `curl http://xarvii.local:8767/api/status` from another machine |
| Portal unreachable | Disable mobile hotspot on phone that auto-connects |

## 5. Conformance after wiring

From the laptop:

```bash
python scripts/conformance.py --wave tests/fixtures/reminder_query.wav
```

Then press PTT and speak — the same lifecycle checks apply to real audio.
