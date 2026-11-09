(function (global) {
  "use strict";

  var OPENFREEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";
  var OPENFREEMAP_TILES_URL = "https://tiles.openfreemap.org/planet";
  var OFFLINE_STYLE_URL = "/static/style-offline.json";
  var ESRI_TILES = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
  var SENTINEL_TILES = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg";

  var OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';
  var OPENFREEMAP_ATTRIBUTION = 'OpenFreeMap &copy; OpenMapTiles';
  var ESRI_ATTRIBUTION = "Esri, Maxar, Earthstar Geographics";
  var EOX_ATTRIBUTION = 'EOxCloudless <a href="https://cloudless.eox.at" target="_blank" rel="noopener noreferrer">https://cloudless.eox.at</a> by <a href="https://eox.at" target="_blank" rel="noopener noreferrer">EOX IT Services GmbH</a> (Contains modified Copernicus Sentinel data 2025) · CC BY-NC-SA 4.0';

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

  function lonToTileX(lon, z) {
    return Math.floor((lon + 180) / 360 * Math.pow(2, z));
  }

  function latToTileY(lat, z) {
    var r = lat * Math.PI / 180;
    return Math.floor((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * Math.pow(2, z));
  }

  function inBbox(bbox, lat, lon) {
    return !!bbox && bbox.length === 4 && lon >= bbox[0] && lat >= bbox[1] && lon <= bbox[2] && lat <= bbox[3];
  }

  function pmtilesHttpUrl(pack) {
    return location.origin + (pack.url || ("/tiles/" + encodeURIComponent(pack.id) + ".pmtiles"));
  }

  function packAttribution(pack) {
    return pack.attribution || "© OpenStreetMap contributors | OpenFreeMap © OpenMapTiles";
  }

  async function loadOfflineStyle(pack, lang) {
    registerPmtilesProtocol();
    var res = await fetch(OFFLINE_STYLE_URL + "?v=1", { cache: "no-store" });
    if (!res.ok) throw new Error("offline style " + res.status);
    var style = await res.json();
    var minzoom = Number(pack.minzoom) || 0;
    var maxzoom = Number(pack.maxzoom) || 15;
    if (pack.kind === "pmtiles") {
      style.sources.openmaptiles = {
        type: "vector",
        url: "pmtiles://" + pmtilesHttpUrl(pack),
        minzoom: minzoom,
        maxzoom: maxzoom,
        attribution: packAttribution(pack)
      };
    } else {
      style.sources.openmaptiles = {
        type: "vector",
        tiles: [location.origin + (pack.tile_url || ("/offline/" + encodeURIComponent(pack.id) + "/{z}/{x}/{y}.pbf"))],
        minzoom: minzoom,
        maxzoom: maxzoom,
        attribution: packAttribution(pack)
      };
    }
    if (pack.satellite) {
      style.layers = (style.layers || []).filter(function (layer) {
        if (layer.type === "raster" || layer.type === "fill" || layer.type === "fill-extrusion") return false;
        if (layer.id && layer.id.indexOf("poi_") === 0) return false;
        return true;
      });
      style.sources["elrs-offline-sat"] = {
        type: "raster",
        tiles: [location.origin + pack.satellite.tile_url],
        tileSize: 256,
        maxzoom: Number(pack.satellite.maxzoom) || maxzoom,
        attribution: EOX_ATTRIBUTION
      };
      var satIndex = style.layers.length && style.layers[0].type === "background" ? 1 : 0;
      style.layers.splice(satIndex, 0, {
        id: "elrs-offline-sat",
        type: "raster",
        source: "elrs-offline-sat",
        minzoom: 0,
        maxzoom: 22,
        paint: { "raster-opacity": 1 }
      });
    }
    style.glyphs = location.origin + "/static/glyphs/{fontstack}/{range}.pbf";
    style.sprite = location.origin + "/static/sprite/ofm";
    localizeStyle(style, lang);
    return style;
  }

  async function packCovers(pack, center) {
    if (!pack || !center || center.length !== 2) return false;
    if (pack.kind === "pmtiles") {
      try {
        var archive = new global.pmtiles.PMTiles(pmtilesHttpUrl(pack));
        var header = await archive.getHeader();
        return center[1] >= header.minLat && center[1] <= header.maxLat &&
          center[0] >= header.minLon && center[0] <= header.maxLon;
      } catch (e) {
        return false;
      }
    }
    return inBbox(pack.bbox, center[1], center[0]);
  }

  async function loadRuntimeStyle(lang, center) {
    if (!global.AndroidSettings) {
      return { mode: "online", pack: null, style: await loadStyle(lang) };
    }
    var settings = null;
    var info = null;
    try {
      var r = await fetch("/api/settings", { cache: "no-store" });
      if (r.ok) settings = await r.json();
    } catch (e) {}
    try {
      var r2 = await fetch("/api/offline", { cache: "no-store" });
      if (r2.ok) info = await r2.json();
    } catch (e2) {}
    var mode = settings && settings.offline_mode ? settings.offline_mode : "online";
    var packs = info && Array.isArray(info.packs) ? info.packs : [];
    var selected = null;
    if (settings && settings.offline_pack) {
      for (var i = 0; i < packs.length; i += 1) {
        if (packs[i].id === settings.offline_pack) { selected = packs[i]; break; }
      }
    }
    var pack = null;
    if (mode === "auto" || mode === "offline") {
      var ordered = [];
      if (selected) ordered.push(selected);
      for (var j = 0; j < packs.length; j += 1) {
        if (!selected || packs[j].id !== selected.id) ordered.push(packs[j]);
      }
      for (var k = 0; k < ordered.length; k += 1) {
        if (await packCovers(ordered[k], center)) { pack = ordered[k]; break; }
      }
      if (!pack && mode === "auto") return { style: await loadStyle(lang), mode: "auto", pack: null };
      if (!pack && mode === "offline") pack = selected || packs[0] || null;
      if (!pack) return { offlineUnavailable: true, mode: mode, pack: null };
    }
    if (pack) {
      try {
        return { style: await loadOfflineStyle(pack, lang), mode: mode, pack: pack };
      } catch (e3) {
        return { offlineUnavailable: true, mode: mode, pack: pack, error: String(e3) };
      }
    }
    return { style: await loadStyle(lang), mode: "online", pack: null };
  }

  async function localAssetsOk() {
    var urls = [
      OFFLINE_STYLE_URL,
      "/static/glyphs/Noto%20Sans%20Regular/0-255.pbf",
      "/static/sprite/ofm.json"
    ];
    for (var i = 0; i < urls.length; i += 1) {
      var res = await fetch(urls[i], { cache: "no-store" });
      if (!res.ok) return false;
    }
    return true;
  }

  async function checkOfflineCoverage(pack, lat, lon, zoom) {
    if (!pack) return { ok: false, reason: "no_pack" };
    var z = Math.max(0, Math.min(Math.floor(Number(zoom) || 0), Number(pack.maxzoom) || 15));
    if (pack.kind === "pmtiles") {
      try {
        registerPmtilesProtocol();
        var archive = new global.pmtiles.PMTiles(pmtilesHttpUrl(pack));
        var header = await archive.getHeader();
        if (lat < header.minLat || lat > header.maxLat || lon < header.minLon || lon > header.maxLon) {
          return { ok: false, reason: "bbox" };
        }
        if (z < header.minZoom || z > header.maxZoom) return { ok: false, reason: "zoom" };
        var tile = await archive.getZxy(z, lonToTileX(lon, z), latToTileY(lat, z));
        if (!tile) return { ok: false, reason: "tile" };
      } catch (e) {
        return { ok: false, reason: "pmtiles" };
      }
    } else {
      if (!inBbox(pack.bbox, lat, lon)) return { ok: false, reason: "bbox" };
      if (z < (Number(pack.minzoom) || 0) || z > (Number(pack.maxzoom) || 15)) return { ok: false, reason: "zoom" };
      var url = (pack.tile_url || ("/offline/" + encodeURIComponent(pack.id) + "/{z}/{x}/{y}.pbf"))
        .replace("{z}", z)
        .replace("{x}", lonToTileX(lon, z))
        .replace("{y}", latToTileY(lat, z));
      try {
        var res = await fetch(location.origin + url, { cache: "no-store" });
        if (!res.ok) return { ok: false, reason: "tile" };
      } catch (e2) {
        return { ok: false, reason: "tile" };
      }
    }
    var satelliteOk = true;
    if (pack.kind !== "pmtiles" && pack.satellite) {
      var satZoom = Math.min(z, Number(pack.satellite.maxzoom) || z);
      var satUrl = (pack.satellite.tile_url || "")
        .replace("{z}", satZoom)
        .replace("{x}", lonToTileX(lon, satZoom))
        .replace("{y}", latToTileY(lat, satZoom));
      try {
        var satRes = await fetch(location.origin + satUrl, { cache: "no-store" });
        satelliteOk = satRes.ok;
      } catch (eSat) {
        satelliteOk = false;
      }
      if (!satelliteOk) return { ok: false, reason: "satellite", satellite: true, satelliteOk: false };
    }
    try {
      if (!(await localAssetsOk())) return { ok: false, reason: "style" };
    } catch (e3) {
      return { ok: false, reason: "style" };
    }
    return { ok: true, reason: "ok", zoom: z, satellite: !!pack.satellite, satelliteOk: satelliteOk };
  }

  global.ELRS_MAP = {
    OPENFREEMAP_STYLE_URL: OPENFREEMAP_STYLE_URL,
    OPENFREEMAP_TILES_URL: OPENFREEMAP_TILES_URL,
    ESRI_TILES: ESRI_TILES,
    SENTINEL_TILES: SENTINEL_TILES,
    OFFLINE_STYLE_URL: OFFLINE_STYLE_URL,
    loadStyle: loadStyle,
    loadOfflineStyle: loadOfflineStyle,
    loadRuntimeStyle: loadRuntimeStyle,
    checkOfflineCoverage: checkOfflineCoverage,
    registerPmtilesProtocol: registerPmtilesProtocol,
    setOfflineTilesUrl: setOfflineTilesUrl
  };
})(window);
