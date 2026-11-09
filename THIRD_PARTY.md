# Third-party notices

The project uses [usb-serial-for-android](https://github.com/mik3y/usb-serial-for-android)
(Apache-2.0) for the USB serial transport, and
[esp-web-tools](https://github.com/esphome/esp-web-tools) (Apache-2.0) in the web flasher.
PlatformIO (Apache-2.0) is installed into the local `.toolchain/venv` and is not vendored.

Map rendering uses [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js) (BSD-3-Clause).
Vector tiles and styles come from [OpenFreeMap](https://openfreemap.org/) / OpenMapTiles;
map data is © OpenStreetMap contributors (ODbL). Satellite imagery is provided by
Esri World Imagery and Sentinel-2 cloudless by EOX IT Services GmbH (CC BY 4.0).
[PMTiles](https://github.com/protomaps/PMTiles) (BSD-3-Clause) is included for optional
offline tile archives. See `web/static/LICENSE-*.txt` and the on-map attribution.
