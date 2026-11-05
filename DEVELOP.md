# Development and toolchain

This document describes how to build, run and test the project on a development machine.

## Requirements

- **JDK 17+** (the project is tested with Temurin 21).
- **Android SDK**:
  - Android platform `35`
  - Build-tools `35.0.0`
  - Platform-tools (`adb`)
- **Gradle** — not installed manually; use the wrapper in `android/` (Gradle 8.9).
- **Python 3.8+** for the desktop viewer and replay tool. No third-party packages are required.
- A **MapTiler API key** for the map tab (optional; telemetry works without it). See below.
- Free ports: UDP `14550` (telemetry) and TCP `8080` (web UI).

## Android SDK setup

Install the Android command-line tools from the official Android developer site, then:

```bash
export JAVA_HOME="$HOME/.jdks/temurin-21"
export ANDROID_HOME="$HOME/Android/Sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"

sdkmanager --licenses
sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"
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

1. sets up JDK 21 and the Android SDK (platform 35, build-tools 35.0.0);
2. runs `./gradlew assembleDebug` in `android/`;
3. uploads `app-debug.apk` as the artifact **elrs-backpack-debug-apk**.

Download the APK from the workflow run page under **Artifacts**.

## Desktop viewer and replay

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

## MapTiler key

The key is **not stored in git**. The pages contain `const mapKey = "__MAPTILER_KEY__";` and the
key is injected at build/run time.

Local development:
- put the key in `maptiler.key` at the repo root (copy `maptiler.key.example`; git-ignored); or
- set `MAPTILER_KEY=...` in the environment; or
- add `MAPTILER_KEY=...` to `android/local.properties` for Android builds.

The Python viewer reads `MAPTILER_KEY` or `maptiler.key`. The Android build reads the environment,
the root file, or `local.properties`, writes `BuildConfig.MAPTILER_KEY`, and the app replaces the
placeholder when serving the page.

GitHub Actions:
- add the repository secret `MAPTILER_KEY`
  (**Settings → Secrets and variables → Actions → New repository secret**);
- the workflow passes it to Gradle and GitHub masks it in logs;
- if the secret is not set, the build still succeeds but the map is disabled.

Third-party developers can create their own free key at `https://cloud.maptiler.com/`, put it in
`maptiler.key`, and restrict it by HTTP origin (`localhost`, `127.0.0.1`).

The key is embedded in the built APK. If the APK/artifact is public, it can be extracted; restrict
the key and/or keep the repository/artifact private if this matters.

## Notes

- `maptiler.key`, `android/local.properties`, build outputs, `__pycache__`, backups and APKs are
  git-ignored.
- Android runtime permissions: install-time permissions are granted automatically. Notifications
  and the battery-optimization exemption are requested on first launch and can be managed from the
  **Telemetry → Settings** card.
