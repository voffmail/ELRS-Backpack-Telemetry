# Third-party notices

The project uses [usb-serial-for-android](https://github.com/mik3y/usb-serial-for-android)
(Apache-2.0) for the USB serial transport, and
[esp-web-tools](https://github.com/esphome/esp-web-tools) (Apache-2.0) in the web flasher.
PlatformIO (Apache-2.0) is installed into the local `.toolchain/venv` and is not vendored.

Map rendering uses [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js) (BSD-3-Clause).
Vector tiles and styles come from [OpenFreeMap](https://openfreemap.org/) / OpenMapTiles;
map data is © OpenStreetMap contributors (ODbL). Satellite imagery is provided by
Esri World Imagery and EOxCloudless 2025 by EOX IT Services GmbH. EOxCloudless 2018–2025 is licensed under CC BY-NC-SA 4.0 for non-commercial use; required attribution: “EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2025)”. Commercial use requires a separate EOX license.
[PMTiles](https://github.com/protomaps/PMTiles) (BSD-3-Clause) is included for optional
offline tile archives. Offline styles use bundled Noto Sans glyph ranges (SIL Open Font License 1.1) and the OpenFreeMap sprite (see `web/static/glyphs/`, `web/static/sprite/`). See `web/static/LICENSE-*.txt` and the on-map attribution.
