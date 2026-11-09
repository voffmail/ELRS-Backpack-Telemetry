# Development and toolchain

This document describes how to build, run and test the project on a development machine.

User-facing overview and installation: [README.md](README.md). Technical reference
(API, CRSF frames, Range, map details, troubleshooting): [docs/REFERENCE.md](docs/REFERENCE.md).
Wi-Fi/ESP-NOW comparison: [docs/BACKPACK-TELEMETRY-WIFI-VS-ESPNOW.md](docs/BACKPACK-TELEMETRY-WIFI-VS-ESPNOW.md).
USB dongle design: [docs/DESIGN.md](docs/DESIGN.md).

## Telemetry paths

The app supports two independent sources:

- **Wi-Fi/UDP (default)** — the backpack sends CRSF over UDP; no extra hardware.
- **ESP-NOW via USB (recommended)** — the backpack sends ESP-NOW to an ESP32-C3
  dongle, which forwards CRSF over native USB CDC. Less RF pollution, but needs
  OTG and a dongle.

Both paths feed the same CRSF parser and UI. Switching is done in the app
settings (gear icon): `source: "network"` or `"usb"` in `/api/settings`.
The firmware and web flasher in this repository are for the USB path only.

## Requirements

- **JDK 17+** (the project is tested with Temurin 21).
- **Android SDK**:
  - Android platform `35`
  - Build-tools `34.0.0` and `35.0.0` (AGP uses 34 by default; 35 for the current platform)
  - Platform-tools (`adb`)
- **Gradle** — not installed manually; use the wrapper in `android/` (Gradle 8.9).
- **Python 3.8+** for the desktop viewer and replay tool. No third-party packages are required.
- **Python 3.11+ with `venv`** for the PlatformIO firmware toolchain (`./init.sh`).
- No map API key is required. The map uses MapLibre GL JS, OpenFreeMap vector tiles, Esri World Imagery and Sentinel-2 fallback.
- Free ports: UDP `14550` (telemetry) and TCP `8080` (web UI).

## Quick toolchain bootstrap (Linux x86_64)

The recommended setup keeps the whole toolchain inside the project but out of git:

```bash
bash scripts/setup-toolchain.sh
source .toolchain/env.sh
cd android && ./gradlew assembleDebug
```

The script stores JDK 21, Gradle 8.9, Android SDK and the Gradle cache in `.toolchain/`
at the repository root. `.toolchain/` is git-ignored; reruns reuse existing downloads
instead of fetching everything again. It also writes `android/local.properties` and
`.toolchain/env.sh`.

Use the manual setup below on macOS/Windows or if you prefer Android Studio.

## Firmware toolchain (PlatformIO)

The ESP32-C3 dongle firmware and the backpack simulator use PlatformIO. They share
`.toolchain/` with the Android tools but are installed separately:

```bash
./init.sh                     # creates .toolchain/venv and PlatformIO 6.2.0
source .toolchain/pio-env.sh  # optional when using ./tools/pio
```

Build the main native-USB firmware:

```bash
./tools/pio run -d firmware -e esp32-c3-usb
```

Other builds:

```bash
./tools/pio run -d sim -e sim                  # backpack simulator
```

Firmware binaries: `firmware/.pio/build/<env>/firmware.bin`. Runtime phrase/UID are
configured from the Android app or `tools/dongle_config.py`; no `secrets.h` is required
unless you want a build-time default.

Host checks:

```bash
python3 -m py_compile tools/*.py
python3 -m unittest discover -s tests
```

Runtime tools (they need `pyserial` from the same venv):

```bash
source .toolchain/pio-env.sh
python3 tools/dongle_config.py --port /dev/ttyACM0 --show
python3 tools/serial_bridge.py --serial /dev/ttyACM1 --udp 127.0.0.1:14550
```

`./init.sh` only sets up PlatformIO. The Android toolchain is still bootstrapped by
`bash scripts/setup-toolchain.sh`; its environment file is `.toolchain/env.sh`, while
PlatformIO uses `.toolchain/pio-env.sh`.

## Build the web flasher

The web flasher is a static page plus a merged ESP32-C3 image:

```bash
./tools/pio run -d firmware -e esp32-c3-usb

PYTHON=.toolchain/venv/bin/python
ESPTOOL=.toolchain/platformio/packages/tool-esptoolpy/esptool.py
BUILD=firmware/.pio/build/esp32-c3-usb
BOOT_APP0=.toolchain/platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin

mkdir -p build
"$PYTHON" "$ESPTOOL" --chip esp32c3 merge_bin \
  -o build/firmware-merged.bin \
  --flash_mode dio --flash_freq 80m --flash_size 4MB \
  0x0 "$BUILD/bootloader.bin" \
  0x8000 "$BUILD/partitions.bin" \
  0xe000 "$BOOT_APP0" \
  0x10000 "$BUILD/firmware.bin"

python3 scripts/make_webflasher.py \
  --version dev \
  --binary build/firmware-merged.bin \
  --out site
```

The generated `site/` is git-ignored. It contains `index.html`, `manifest.json`,
`firmware-merged.bin` and `SHA256SUMS`. Open it over HTTPS or `localhost` (Web Serial
requires a secure context and Chrome/Edge on a desktop).

## Android SDK setup

Install the Android command-line tools from the official Android developer site, then:

```bash
export JAVA_HOME="$HOME/.jdks/temurin-21"
export ANDROID_HOME="$HOME/Android/Sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"

sdkmanager --licenses
sdkmanager "platform-tools" "platforms;android-35" "build-tools;34.0.0" "build-tools;35.0.0"
```

Alternatively, install Android Studio and install SDK Platform 35 and Build-Tools 35.0.0 from
**SDK Manager**.

### SDK path for Gradle

Gradle finds the SDK through `ANDROID_HOME` / `ANDROID_SDK_ROOT`. If you prefer a local file,
create `android/local.properties` (it is git-ignored):

```properties
sdk.dir=/path/to/Android/Sdk
```

Do not commit `local.properties`.

## Build the APK

If you used the bootstrap, activate it first:

```bash
source .toolchain/env.sh
```

Then build:

```bash
cd android
./gradlew assembleDebug
```

Windows:

```bat
cd android
gradlew.bat assembleDebug
```

APK:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

The debug APK is signed with the local debug key and can be installed directly:

```bash
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

## GitHub Actions

`.github/workflows/android-apk.yml` builds the debug APK on every push to `main`/`master`,
on pull requests, and manually via **Actions → Build Android APK → Run workflow**.

The workflow:

1. sets up JDK 21 and the Android SDK (platform 35, build-tools 34.0.0 and 35.0.0);
2. runs `./gradlew assembleDebug` in `android/`;
3. uploads `app-debug.apk` as the artifact **elrs-backpack-debug-apk**.

Download the APK from the workflow run page under **Artifacts**.

### Firmware and web flasher workflows

- `.github/workflows/firmware.yml` builds `esp32-c3-usb`, the simulator (`sim`),
  runs the Python checks/tests and uploads the native-USB `firmware.bin` artifact.
- `.github/workflows/webflasher.yml` builds the native-USB image, merges it with
  `esptool`, generates `site/`, uploads the site artifact, deploys GitHub Pages
  and, for releases, attaches `firmware-merged.bin`, `SHA256SUMS` and
  `firmware.elf` to the GitHub Release.

For Pages, enable **Settings → Pages → Source: GitHub Actions** once.

## Release APK and GitHub Releases

The debug APK is intended for testing. Releases use a signed release build with a stable key.

Local signing files (git-ignored):
- `android/keystore/elrs-release.jks`
- `android/keystore.properties`

Back them up. The same keystore is stored in the GitHub Actions secrets
`ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` and
`ANDROID_KEY_PASSWORD`.

Create a release:
- push a tag: `git tag v1.0.0 && git push origin v1.0.0`; or
- run **Actions → Release APK → Run workflow** with a tag.

`.github/workflows/release-apk.yml` builds `assembleRelease`, verifies the signature, and attaches
`ELRS-Backpack-Telemetry-<tag>.apk` to the GitHub Release. The debug APK workflow remains available
for test artifacts.

## Desktop viewer and replay

The Python viewer listens to Wi-Fi/UDP. For the USB dongle on a PC, bridge the
serial stream to UDP with `tools/serial_bridge.py` (see the firmware section).

```bash
# live viewer (UDP 14550, HTTP 8080)
python3 tlm_viewer.py

# replay the bundled capture to the viewer
python3 replay.py testdata/tlm_20261105_111628.jsonl

# replay to a phone/another host
python3 replay.py testdata/tlm_20261105_111628.jsonl --host 192.168.0.42 --port 14550
```

The bundled capture and the tracks in `tracks/` are sanitized: coordinates are synthetic
(near Barsovo, Surgutsky District) and the source address is a placeholder.

## Regression checks

```bash
python3 -m py_compile tlm_viewer.py replay.py

python3 tlm_viewer.py --http-host 127.0.0.1 --http-port 8099 --udp-port 14599 &
curl -s http://127.0.0.1:8099/api/state
python3 replay.py testdata/tlm_20261105_111628.jsonl --host 127.0.0.1 --port 14599 --speed 0
curl -s http://127.0.0.1:8099/api/state
```

For the Android app:

```bash
cd android
./gradlew clean assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.elrs.backpack/.MainActivity
adb forward tcp:18081 tcp:8080
curl -s http://127.0.0.1:18081/api/state
curl -s http://127.0.0.1:18081/api/settings
```

## Map tiles

The map is keyless. The pages use MapLibre GL JS and load a style from OpenFreeMap
(`https://tiles.openfreemap.org/styles/liberty`), then add satellite raster layers:

- **Esri World Imagery** — the primary high-resolution satellite layer;
- **Sentinel-2 cloudless** (EOX) — an always-on fallback underneath Esri.

Vector labels and roads remain from OpenFreeMap/OpenStreetMap. The shared map code lives in
`web/static/elrs-map.js`; MapLibre and PMTiles are vendored in `web/static/` and packaged into
the Android APK through a Gradle assets source set. No runtime key injection is used.

`/static/*` is served by both the Python viewer and the Android local HTTP server. `/tiles/*` is
also served with HTTP Range support (and is currently empty in the Python viewer; Android reads it
from `filesDir/tiles`). This is the hook for optional offline PMTiles maps: put a regional
`.pmtiles` extract there and point `ELRS_MAP.setOfflineTilesUrl("pmtiles://http://127.0.0.1:8080/tiles/<name>.pmtiles")`
before the map is created. No server or protocol changes are needed for the vector tiles. Full offline labels would also need a cached style JSON and local glyphs/sprites; that is a later step, not a server-side blocker.

Attribution is shown on the map: OpenStreetMap/OpenFreeMap, Esri and EOX. Esri availability and
terms of use should be checked for the target region; Sentinel-2 is the fallback.

## Known issues

- **No notification sounds on some devices.** On Redmi Note 15 (HyperOS) the app plays no sound
  for any notification event, even with the dedicated power-save channel set to the default sound
  and the phone out of silent mode. Visual notifications and the persistent status still work. The
  cause has not been investigated yet; this is not specific to the power-save logic.

## Notes

- `android/local.properties`, build outputs, `__pycache__`, backups and APKs are git-ignored. PlatformIO build outputs (`firmware/.pio/`, `sim/.pio/`), `build/`, `site/` and
  `firmware/include/secrets.h` are git-ignored too.
- Android runtime permissions: install-time permissions are granted automatically. Notifications
  and the battery-optimization exemption are requested on first launch and can be managed from the
  gear icon in the app header.
