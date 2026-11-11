# Project agent notes

## Toolchain and build

Detailed setup is in `DEVELOP.md`.

- Local toolchain (JDK 21, Android SDK, Gradle 8.9 and caches): `bash scripts/setup-toolchain.sh`, then `source .toolchain/env.sh`. It lives in `.toolchain/` (git-ignored) and is reused on every run; do not re-download the toolchain into `/tmp`.
- JDK 17+ (tested with 21), Android SDK platform 35, build-tools 34.0.0 and 35.0.0.
- Build: `source .toolchain/env.sh && cd android && ./gradlew assembleDebug` (or use the manual SDK setup from `DEVELOP.md`).
- APK: `android/app/build/outputs/apk/debug/app-debug.apk`
- CI: `.github/workflows/android-apk.yml` uploads the artifact `elrs-backpack-debug-apk`.
- Release: tag `v*` → `.github/workflows/release-apk.yml` (signed APK attached to a GitHub Release).
- Python checks: `python3 -m py_compile tlm_viewer.py replay.py tools/*.py`
- Firmware toolchain (PlatformIO): `./init.sh` (installs into `.toolchain/venv`; do not overwrite the Android `.toolchain/env.sh`), then `./tools/pio run -d firmware -e esp32-c3-usb-otg` or `-e esp32-s3-usb-otg`.
  - Environments: `esp32-c3-usb-otg` and `esp32-s3-usb-otg` (native USB), plus `sim` (backpack simulator).
  - Firmware outputs: `firmware/.pio/build/<env>/firmware.bin`; `firmware/include/secrets.h` is git-ignored.
  - Host tests: `python3 -m unittest discover -s tests` (includes CRSF/MSP, MAVLink framing and session tests).
  - Web flasher: merge each env with `esptool` into `build/firmware-merged-c3.bin` / `-s3.bin`, then `python3 scripts/make_webflasher.py --version <ver> --binary c3=build/firmware-merged-c3.bin --binary s3=build/firmware-merged-s3.bin --out site`. The page uses one combined `manifest.json`; ESP Web Tools picks the build by `chipFamily` (no manual target selector). CI: `.github/workflows/firmware.yml` and `.github/workflows/webflasher.yml`.
  - S3 LED defaults to the DevKitC-1 WS2812 on GPIO48; override with `-DELRS_LED_PIN=<n>` (`-1` disables it) or `-DELRS_LED_RGB=0` for a plain LED.
- Map stack: MapLibre GL JS + OpenFreeMap vector labels/roads + Esri World Imagery with Sentinel-2 fallback; no API key. Shared assets live in `web/static/`; Android offline maps download OpenFreeMap vector areas plus optional EOxCloudless 2025 Sentinel-2 (CC BY-NC-SA 4.0, non-commercial) or import PMTiles, with local style/fonts and `/offline/*` + `/tiles/*` routes. See `DEVELOP.md`.
- Telemetry sources: Wi-Fi/UDP (default) and ESP-NOW via native-USB ESP32-C3/ESP32-S3 dongle (recommended). In Network mode the app auto-detects CRSF or MAVLink; MAVLink is Wi-Fi-only (the ESP-NOW path is CRSF). See `docs/BACKPACK-TELEMETRY-WIFI-VS-ESPNOW.md`, `docs/DESIGN.md`, `docs/REFERENCE.md`.

## Skill: replay ELRS telemetry offline

Use this when you need to reproduce captured ExpressLRS Wi-Fi telemetry without the drone or the TX backpack.

### Prerequisites

- Python 3
- `tlm_viewer.py` and `replay.py` in the project root
- a capture in `testdata/*.jsonl` (current sample: `testdata/tlm_20261105_111628.jsonl`)

### Capture format

JSONL, one UDP payload per line:

```json
{"t": 0.123456, "src": "192.168.0.41:14555", "data": "24583c00..."}
```

- `t` — seconds from capture start
- `src` — original UDP source (`ip:port`)
- `data` — full UDP payload as hex
- the last line may be `{"meta": {...}}`; replay ignores lines without `data`
- the viewer extracts CRSF frames from `data`
- the sample capture is sanitized: GPS coordinates are near Barsovo (Surgutsky District), and the source address is a placeholder `192.168.0.41:14555`

### Run

1. Power off the drone and the TX backpack, or otherwise make sure no live packets arrive on UDP 14550.
2. Restart the viewer to reset counters:

   ```bash
   pkill -f '^python3 tlm_viewer\.py$' || true
   nohup python3 tlm_viewer.py > /tmp/tlm_viewer.log 2>&1 &
   ```

3. Start replay. Defaults: `127.0.0.1:14550`, real time.

   ```bash
   python3 replay.py testdata/tlm_20261105_111628.jsonl
   ```

   Useful options:

   ```bash
   python3 replay.py testdata/tlm_20261105_111628.jsonl --loop
   python3 replay.py testdata/tlm_20261105_111628.jsonl --speed 2
   python3 replay.py testdata/tlm_20261105_111628.jsonl --speed 0
   python3 replay.py testdata/tlm_20261105_111628.jsonl --host 192.168.1.10 --port 14550
   ```

4. Open `http://localhost:8080` or `http://<host-ip>:8080`.
5. Stop replay with `Ctrl+C` (or kill the replay process).

### Verify

```bash
curl -s http://127.0.0.1:8080/api/state
```

Expected: `stats.age` below 1 second, `stats.total` increasing, `link.rf_mode` present, and UI shows band / packet rate / range.

### Notes

- Do not replay while the real backpack is sending; live and recorded packets will mix.
- Replay sends from an ephemeral source port and does not spoof the original source IP. The viewer keys off the UDP payload, not the source address.
- `--speed 0` sends the whole capture instantly; the viewer's online indicator may only flicker.
- Port 14550 must be free for the viewer. If another process owns it, stop that process first.
- `testdata/tlm_20261105_111628.jsonl` contains 60 s, 311 packets, CRSF types `0x02`, `0x07`, `0x08`, `0x09`, `0x14`, `0x1E`, `0x21`, with GPS fix, `AIR*` / `AIR?`, and 10 mW TX power.
