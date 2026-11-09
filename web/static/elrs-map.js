(function (global) {
  "use strict";

  var OPENFREEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";
  var OPENFREEMAP_TILES_URL = "https://tiles.openfreemap.org/planet";
  var ESRI_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
  var SENTINEL_TILES = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg";

  var OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';
  var OPENFREEMAP_ATTRIBUTION = 'OpenFreeMap &copy; OpenMapTiles';
  var ESRI_ATTRIBUTION = "Esri, Maxar, Earthstar Geographics";
  var EOX_ATTRIBUTION = '<a href="https://s2maps.eu" target="_blank" rel="noopener noreferrer">Sentinel-2 cloudless</a> by EOX IT Services GmbH (CC BY 4.0)';

  var offlineTilesUrl = null;
  var pmtilesRegistered = false;

  function labelExpression(lang) {
    var fields = [];
    if (lang === "ru") fields = ["name:ru", "name"];
    else if (lang === "en") fields = ["name:en", "name_en", "name:latin", "name"];
    else if (lang === "zh") fields = ["name:zh", "name:zh-Hans", "name:zh-Hant", "name_zh", "name:latin", "name"];
    var expr = ["coalesce"];
    for (var i = 0; i < fields.length; i += 1) expr.push(["get", fields[i]]);
    expr.push(["get", "name"]);
    return expr;
  }

  function isNameLabel(textField) {
    var json = typeof textField === "string" ? textField : JSON.stringify(textField);
    if (json.indexOf('"ref"') >= 0) return false;
    if (typeof textField === "string") return /\bname(:[a-z-]+)?\b/.test(textField);
    return json.indexOf('"name"') >= 0 || json.indexOf('"name:') >= 0;
  }

  function localizeStyle(style, lang) {
    if (!style || !Array.isArray(style.layers)) return style;
    for (var i = 0; i < style.layers.length; i += 1) {
      var layer = style.layers[i];
      if (!layer || layer.type !== "symbol" || !layer.layout || !("text-field" in layer.layout)) continue;
      if (!isNameLabel(layer.layout["text-field"])) continue;
      layer.layout["text-field"] = labelExpression(lang);
    }
    return style;
  }

  function rasterSource(tiles, maxzoom, attribution) {
    return {
      type: "raster",
      tiles: [tiles],
      tileSize: 256,
      maxzoom: maxzoom,
      attribution: attribution
    };
  }

  function rasterLayer(id, source) {
    return {
      id: id,
      type: "raster",
      source: source,
      minzoom: 0,
      maxzoom: 22,
      paint: { "raster-opacity": 1 }
    };
  }

  function addSatellite(style) {
    style.sources = style.sources || {};
    style.sources["elrs-sentinel"] = rasterSource(SENTINEL_TILES, 14, EOX_ATTRIBUTION);
    style.sources["elrs-esri"] = rasterSource(ESRI_TILES, 19, ESRI_ATTRIBUTION);
    var index = style.layers.length && style.layers[0].type === "background" ? 1 : 0;
    style.layers.splice(index, 0,
      rasterLayer("elrs-sentinel", "elrs-sentinel"),
      rasterLayer("elrs-esri", "elrs-esri")
    );
  }

  function fallbackStyle(lang) {
    var style = {
      version: 8,
      sources: {},
      layers: [
        { id: "elrs-background", type: "background", paint: { "background-color": "#0b0f14" } }
      ]
    };
    addSatellite(style);
    localizeStyle(style, lang);
    return style;
  }

  function prepareStyle(raw, lang) {
    var style = JSON.parse(JSON.stringify(raw));
    style.layers = (style.layers || []).filter(function (layer) {
      if (layer.type === "raster" || layer.type === "fill" || layer.type === "fill-extrusion") return false;
      if (layer.id && layer.id.indexOf("poi_") === 0) return false;
      return true;
    });
    if (style.sources && style.sources.openmaptiles) {
      if (offlineTilesUrl) style.sources.openmaptiles.url = offlineTilesUrl;
      else if (!style.sources.openmaptiles.url) style.sources.openmaptiles.url = OPENFREEMAP_TILES_URL;
      style.sources.openmaptiles.attribution = OSM_ATTRIBUTION + " | " + OPENFREEMAP_ATTRIBUTION;
    }
    addSatellite(style);
    localizeStyle(style, lang);
    return style;
  }

  async function loadStyle(lang) {
    registerPmtilesProtocol();
    try {
      var res = await fetch(OPENFREEMAP_STYLE_URL, { cache: "force-cache" });
      if (!res.ok) throw new Error("style " + res.status);
      return prepareStyle(await res.json(), lang);
    } catch (e) {
      return fallbackStyle(lang);
    }
  }

  function registerPmtilesProtocol() {
    if (pmtilesRegistered) return;
    if (!global.maplibregl || !global.pmtiles || !global.pmtiles.Protocol) return;
    var protocol = new global.pmtiles.Protocol();
    global.maplibregl.addProtocol("pmtiles", protocol.tile);
    pmtilesRegistered = true;
  }

  function setOfflineTilesUrl(url) {
    offlineTilesUrl = url || null;
  }

  global.ELRS_MAP = {
    OPENFREEMAP_STYLE_URL: OPENFREEMAP_STYLE_URL,
    OPENFREEMAP_TILES_URL: OPENFREEMAP_TILES_URL,
    ESRI_TILES: ESRI_TILES,
    SENTINEL_TILES: SENTINEL_TILES,
    loadStyle: loadStyle,
    registerPmtilesProtocol: registerPmtilesProtocol,
    setOfflineTilesUrl: setOfflineTilesUrl
  };
})(window);
