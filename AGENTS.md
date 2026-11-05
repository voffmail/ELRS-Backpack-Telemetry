# Project agent notes

## Toolchain and build

Detailed setup is in `DEVELOP.md`.

- JDK 17+ (tested with 21), Android SDK platform 35, build-tools 35.0.0.
- Build: `cd android && ./gradlew assembleDebug`
- APK: `android/app/build/outputs/apk/debug/app-debug.apk`
- CI: `.github/workflows/android-apk.yml` uploads the artifact `elrs-backpack-debug-apk`.
- Python checks: `python3 -m py_compile tlm_viewer.py replay.py`
- MapTiler key: `MAPTILER_KEY` env or `maptiler.key` (git-ignored); CI uses the `MAPTILER_KEY` secret. See `DEVELOP.md`.

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
