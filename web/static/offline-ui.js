(function () {
  "use strict";

  var OFFLINE_I18N = {
    en: {
      offline_section: "Map",
      map_type: "Map type",
      offline_mode: "Map mode",
      offline_mode_online: "Online",
      offline_mode_auto: "Auto",
      offline_mode_offline: "Offline",
      offline_mode_online_desc: "Always online: OpenFreeMap + Esri/Sentinel. Offline packs are ignored; internet is required.",
      offline_mode_auto_desc: "Uses a downloaded pack when it covers the current area, otherwise online. Switches to another local pack when you move into it.",
      offline_mode_offline_desc: "Uses only downloaded packs, with no map requests to the network. Outside coverage the map stays empty; without packs it reports that offline maps are unavailable.",
      offline_pack: "Offline pack",
      offline_pack_none: "— none —",
      offline_storage: "Storage: {used} used, {free} free",
      offline_download: "Download area",
      offline_import: "Import .pmtiles",
      offline_delete: "Delete pack",
      offline_clear: "Clear offline maps",
      offline_clear_confirm: "Delete all downloaded offline maps?",
      offline_cleared: "Offline maps cleared",
      offline_packs_summary: "Downloaded packs: {count} ({size})",
      offline_check: "Check coverage",
      offline_check_note: "Checks that the current place has tiles, satellite and local fonts.",
      offline_cancel: "Cancel",
      offline_radius: "Radius, km",
      offline_maxzoom: "Max zoom",
      offline_maxzoom_note: "Max zoom: 0–14. The upper limit is set by OpenFreeMap.",
      offline_estimate: "≈{tiles} tiles · ≈{mb} MB",
      offline_estimate_over: "{tiles} tiles — over the 3000-tile limit; reduce radius or zoom",
      offline_estimate_hybrid: "≈{tiles} vector + {sat} satellite tiles · ≈{vector_mb} MB vector + ≈{sat_mb} MB satellite (≈{total_mb} MB total)",
      offline_area_info: "Area: a circle with radius {radius} km around the map center ({lat}, {lon})",
      offline_vector_limit_warn: "Vector estimate exceeds 50 MB; reduce radius or zoom",
      offline_progress: "Downloading: {done}/{total}, {mb}",
      offline_done: "Downloaded: {name}",
      offline_cancelled: "Download cancelled",
      offline_error: "Offline error: {error}",
      offline_no_packs: "No offline packs yet",
      offline_no_point: "Open the map or wait for GPS to choose an area",
      offline_checking: "Checking offline map…",
      offline_check_ok: "Offline map ready: {name}",
      offline_check_fail: "Offline map unavailable: {reason}",
      offline_reason_no_pack: "no offline pack for the current place",
      offline_reason_bbox: "the area is outside the pack",
      offline_reason_zoom: "zoom is outside the pack",
      offline_reason_tile: "a required tile is missing",
      offline_reason_style: "local style, fonts or sprites are missing",
      offline_reason_pmtiles: "PMTiles archive is unreadable",
      offline_badge_online: "Online map",
      offline_badge_auto: "Online · offline: {name}",
      offline_badge_offline: "Offline: {name}",
      offline_badge_none: "Offline: no pack",
      offline_delete_confirm: "Delete offline pack “{name}”?",
      offline_import_hint: "Import a .pmtiles file prepared for OpenFreeMap/OpenMapTiles.",
      offline_download_hint: "OpenFreeMap allows up to 3000 tiles or 50 MB per download. For larger areas, import a .pmtiles pack.",
      offline_download_title: "Download visible area",
      offline_btn: "Offline",
      offline_visible_hint: "Download the visible area with the map button at zoom 10 or higher.",
      offline_satellite: "Sentinel-2 satellite (10 m)",
      offline_satellite_note: "Satellite: EOxCloudless 2025, CC BY-NC-SA 4.0 (non-commercial)",
      offline_hybrid: "hybrid",
      offline_badge_hybrid: "Offline hybrid: {name}",
      offline_check_hybrid: "Offline hybrid ready: {name}",
      offline_check_vector_only: "Vector offline ready; satellite is missing",
      offline_satellite_failed: "Satellite not downloaded: {error}",
      offline_error_vector_size_limit: "Vector data exceeded the 50 MB limit. Max zoom reduced to z{zoom}; press Download again.",
      offline_error_satellite_size_limit: "Satellite data exceeded the 50 MB limit.",
      offline_not_android: "Offline maps are available in the Android app",
      offline_check_need_map: "Open the map to check coverage",
      offline_pack_area: "area",
      offline_pack_pmtiles: "PMTiles",
      offline_selected_none: "No offline pack selected"
    },
    ru: {
      offline_section: "Карта",
      map_type: "Тип карты",
      offline_mode: "Режим карты",
      offline_mode_online: "Онлайн",
      offline_mode_auto: "Авто",
      offline_mode_offline: "Оффлайн",
      offline_mode_online_desc: "Всегда онлайн-карта: OpenFreeMap + Esri/Sentinel. Офлайн-паки игнорируются, нужен интернет.",
      offline_mode_auto_desc: "Локальный пак, если он покрывает текущую область; иначе онлайн. При переходе в другую скачанную область переключается на неё.",
      offline_mode_offline_desc: "Только локальные паки, без запросов карты в сеть. Вне покрытия — пусто/ошибка; без паков — сообщение, что офлайн-карта недоступна.",
      offline_pack: "Офлайн-пак",
      offline_pack_none: "— нет —",
      offline_storage: "Хранилище: занято {used}, свободно {free}",
      offline_download: "Скачать область",
      offline_import: "Импорт .pmtiles",
      offline_delete: "Удалить пак",
      offline_clear: "Очистить оффлайн карты",
      offline_clear_confirm: "Удалить все скачанные оффлайн-карты?",
      offline_cleared: "Оффлайн-карты очищены",
      offline_packs_summary: "Скачано паков: {count} ({size})",
      offline_check: "Проверить покрытие",
      offline_check_note: "Проверяет, что для текущего места есть тайлы, спутник и локальные шрифты.",
      offline_cancel: "Отмена",
      offline_radius: "Радиус, км",
      offline_maxzoom: "Макс. зум",
      offline_maxzoom_note: "Макс. зум: 0–14. Верхний предел задан OpenFreeMap.",
      offline_estimate: "≈{tiles} тайлов · ≈{mb} МБ",
      offline_estimate_over: "{tiles} тайлов — больше лимита 3000; уменьшите радиус или зум",
      offline_estimate_hybrid: "≈{tiles} векторных + {sat} спутниковых тайлов · ≈{vector_mb} МБ вектор + ≈{sat_mb} МБ спутник (всего ≈{total_mb} МБ)",
      offline_area_info: "Область: круг радиусом {radius} км вокруг центра карты ({lat}, {lon})",
      offline_vector_limit_warn: "Оценка вектора больше 50 МБ; уменьшите радиус или зум",
      offline_progress: "Скачивание: {done}/{total}, {mb}",
      offline_done: "Скачано: {name}",
      offline_cancelled: "Скачивание отменено",
      offline_error: "Ошибка офлайна: {error}",
      offline_no_packs: "Офлайн-паков пока нет",
      offline_no_point: "Откройте карту или дождитесь GPS, чтобы выбрать область",
      offline_checking: "Проверяю офлайн-карту…",
      offline_check_ok: "Офлайн-карта готова: {name}",
      offline_check_fail: "Офлайн-карта недоступна: {reason}",
      offline_reason_no_pack: "нет офлайн-пака для текущего места",
      offline_reason_bbox: "точка вне покрытия пака",
      offline_reason_zoom: "зум вне покрытия пака",
      offline_reason_tile: "не найден нужный тайл",
      offline_reason_style: "нет локального стиля, шрифтов или sprite",
      offline_reason_pmtiles: "архив PMTiles не читается",
      offline_badge_online: "Онлайн-карта",
      offline_badge_auto: "Онлайн · офлайн: {name}",
      offline_badge_offline: "Офлайн: {name}",
      offline_badge_none: "Офлайн: нет пака",
      offline_delete_confirm: "Удалить офлайн-пак «{name}»?",
      offline_import_hint: "Импортируйте .pmtiles, подготовленный для OpenFreeMap/OpenMapTiles.",
      offline_download_hint: "OpenFreeMap разрешает до 3000 тайлов или 50 МБ на одно скачивание. Для больших областей импортируйте .pmtiles.",
      offline_download_title: "Скачать видимую область",
      offline_btn: "Офлайн",
      offline_visible_hint: "Скачивание видимой области — кнопкой на карте, при зуме не меньше z10.",
      offline_satellite: "Спутник Sentinel-2 (10 м)",
      offline_satellite_note: "Спутник: EOxCloudless 2025, CC BY-NC-SA 4.0 (некоммерческое использование)",
      offline_hybrid: "гибрид",
      offline_badge_hybrid: "Офлайн-гибрид: {name}",
      offline_check_hybrid: "Офлайн-гибрид готов: {name}",
      offline_check_vector_only: "Векторная офлайн-карта готова; спутник отсутствует",
      offline_satellite_failed: "Спутник не скачан: {error}",
      offline_error_vector_size_limit: "Вектор превысил лимит 50 МБ. Макс. зум уменьшен до z{zoom}; нажмите «Скачать» ещё раз.",
      offline_error_satellite_size_limit: "Спутник превысил лимит 50 МБ.",
      offline_not_android: "Офлайн-карты доступны в Android-приложении",
      offline_check_need_map: "Откройте карту, чтобы проверить покрытие",
      offline_pack_area: "область",
      offline_pack_pmtiles: "PMTiles",
      offline_selected_none: "Офлайн-пак не выбран"
    },
    zh: {
      offline_section: "地图",
      map_type: "地图类型",
      offline_mode: "地图模式",
      offline_mode_online: "在线",
      offline_mode_auto: "自动",
      offline_mode_offline: "离线",
      offline_mode_online_desc: "始终使用在线地图：OpenFreeMap + Esri/Sentinel。忽略离线包，需要互联网。",
      offline_mode_auto_desc: "当前区域有已下载的离线包时使用它，否则使用在线地图。移动到其他已下载区域时会自动切换。",
      offline_mode_offline_desc: "只使用已下载的离线包，不向网络请求地图。超出覆盖范围时地图为空；没有离线包时提示离线地图不可用。",
      offline_pack: "离线包",
      offline_pack_none: "— 无 —",
      offline_storage: "存储：已用 {used}，可用 {free}",
      offline_download: "下载区域",
      offline_import: "导入 .pmtiles",
      offline_delete: "删除离线包",
      offline_clear: "清除离线地图",
      offline_clear_confirm: "删除所有已下载的离线地图？",
      offline_cleared: "离线地图已清除",
      offline_packs_summary: "已下载离线包：{count}（{size}）",
      offline_check: "检查覆盖",
      offline_check_note: "检查当前位置是否有瓦片、卫星影像和本地字体。",
      offline_cancel: "取消",
      offline_radius: "半径，公里",
      offline_maxzoom: "最大缩放",
      offline_maxzoom_note: "最大缩放：0–14，上限由 OpenFreeMap 设定。",
      offline_estimate: "约 {tiles} 个瓦片 · 约 {mb} MB",
      offline_estimate_over: "{tiles} 个瓦片，超过 3000 限制；请减小半径或缩放",
      offline_estimate_hybrid: "约 {tiles} 个矢量 + {sat} 个卫星瓦片 · 约 {vector_mb} MB 矢量 + {sat_mb} MB 卫星（总计约 {total_mb} MB）",
      offline_area_info: "区域：以地图中心 ({lat}, {lon}) 为圆心、半径 {radius} 公里的圆",
      offline_vector_limit_warn: "矢量估算超过 50 MB；请减小半径或缩放",
      offline_progress: "下载中：{done}/{total}，{mb}",
      offline_done: "已下载：{name}",
      offline_cancelled: "下载已取消",
      offline_error: "离线错误：{error}",
      offline_no_packs: "暂无离线包",
      offline_no_point: "请打开地图或等待 GPS 以选择区域",
      offline_checking: "正在检查离线地图…",
      offline_check_ok: "离线地图可用：{name}",
      offline_check_fail: "离线地图不可用：{reason}",
      offline_reason_no_pack: "当前位置没有离线包",
      offline_reason_bbox: "区域超出离线包范围",
      offline_reason_zoom: "缩放超出离线包范围",
      offline_reason_tile: "缺少所需瓦片",
      offline_reason_style: "缺少本地样式、字体或 sprite",
      offline_reason_pmtiles: "PMTiles 档案无法读取",
      offline_badge_online: "在线地图",
      offline_badge_auto: "在线 · 离线：{name}",
      offline_badge_offline: "离线：{name}",
      offline_badge_none: "离线：无离线包",
      offline_delete_confirm: "删除离线包“{name}”？",
      offline_import_hint: "导入为 OpenFreeMap/OpenMapTiles 准备的 .pmtiles 文件。",
      offline_download_hint: "OpenFreeMap 每次下载最多允许 3000 个瓦片或 50 MB。更大区域请导入 .pmtiles。",
      offline_download_title: "下载可见区域",
      offline_btn: "离线",
      offline_visible_hint: "使用地图上的按钮下载可见区域，缩放至少为 z10。",
      offline_satellite: "Sentinel-2 卫星影像（10 米）",
      offline_satellite_note: "卫星：EOxCloudless 2025，CC BY-NC-SA 4.0（非商业用途）",
      offline_hybrid: "混合",
      offline_badge_hybrid: "离线混合：{name}",
      offline_check_hybrid: "离线混合地图可用：{name}",
      offline_check_vector_only: "矢量离线地图可用；缺少卫星影像",
      offline_satellite_failed: "卫星影像未下载：{error}",
      offline_error_vector_size_limit: "矢量数据超过 50 MB 限制。最大缩放已降至 z{zoom}；请再次下载。",
      offline_error_satellite_size_limit: "卫星影像超过 50 MB 限制。",
      offline_not_android: "离线地图仅在 Android 应用中可用",
      offline_check_need_map: "打开地图以检查覆盖范围",
      offline_pack_area: "区域",
      offline_pack_pmtiles: "PMTiles",
      offline_selected_none: "未选择离线包"
    }
  };
  window.OFFLINE_I18N = OFFLINE_I18N;

  var state = { packs: [], job: null, storage: {} };
  var lastPackId = null;
  var lastSizeErrorJob = null;

  function el(id) { return document.getElementById(id); }
  function txt(id, value) { var e = el(id); if (e) e.textContent = value; }
  function fmtBytes(n) {
    n = Number(n) || 0;
    if (n >= 1024 * 1024 * 1024) return (n / (1024 * 1024 * 1024)).toFixed(1) + " GB";
    if (n >= 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + " MB";
    if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
    return Math.round(n) + " B";
  }
  function msg(text, isError) {
    var ids = ["offlineMsg", "mapOfflineMsg"];
    for (var i = 0; i < ids.length; i++) {
      var e = el(ids[i]);
      if (!e) continue;
      e.textContent = text || "";
      e.classList.toggle("err", !!isError);
    }
  }
  function currentMode() {
    var e = el("offlineMode");
    if (e && e.value) return e.value;
    return (typeof currentSettings !== "undefined" && currentSettings && currentSettings.offline_mode) || "online";
  }
  function selectedPack() {
    var id = (typeof currentSettings !== "undefined" && currentSettings && currentSettings.offline_pack) || "";
    var packs = state.packs || [];
    for (var i = 0; i < packs.length; i++) if (packs[i].id === id) return packs[i];
    return null;
  }
  function center() {
    try {
      if (typeof mapObj !== "undefined" && mapObj && mapObj.getCenter) {
        var c = mapObj.getCenter();
        if (c && isFinite(c.lng) && isFinite(c.lat)) return { lon: c.lng, lat: c.lat };
      }
    } catch (e) {}
    try {
      if (typeof mapLastGps !== "undefined" && mapLastGps && isFinite(Number(mapLastGps.lat)) && isFinite(Number(mapLastGps.lon))) {
        return { lon: Number(mapLastGps.lon), lat: Number(mapLastGps.lat) };
      }
    } catch (e2) {}
    try {
      if (typeof lastState !== "undefined" && lastState && lastState.gps && isFinite(Number(lastState.gps.lat)) && isFinite(Number(lastState.gps.lon))) {
        return { lon: Number(lastState.gps.lon), lat: Number(lastState.gps.lat) };
      }
    } catch (e3) {}
    var p = selectedPack();
    if (p && p.center && p.center.length === 2) return { lon: Number(p.center[0]), lat: Number(p.center[1]) };
    return null;
  }
  function intValue(id, fallback) {
    var e = el(id);
    if (!e) return fallback;
    var v = parseInt(e.value, 10);
    return isFinite(v) ? v : fallback;
  }
  function syncZoomLabel(inputId, labelId) {
    var input = el(inputId);
    var label = el(labelId);
    if (input && label) label.textContent = String(intValue(inputId, 14));
  }
  function syncZoomLabels() {
    syncZoomLabel("offlineMaxZoom", "offlineMaxZoomValue");
    syncZoomLabel("mapOfflineMaxZoom", "mapOfflineMaxZoomValue");
  }
  function zoom() {
    try {
      if (typeof mapObj !== "undefined" && mapObj && mapObj.getZoom) return mapObj.getZoom();
    } catch (e) {}
    return intValue("offlineMaxZoom", 14);
  }
  function radiusKm() { var e = el("offlineRadius"); return e ? Number(e.value) || 10 : 10; }
  function maxZoom() { return intValue("offlineMaxZoom", 14); }
  function bboxFor(lat, lon, km) {
    var dlat = km / 111.32;
    var dlon = km / (111.32 * Math.cos(lat * Math.PI / 180));
    return [Math.max(-180, lon - dlon), Math.max(-85.05112878, lat - dlat),
            Math.min(180, lon + dlon), Math.min(85.05112878, lat + dlat)];
  }
  function lon2x(lon, z) { return Math.floor((lon + 180) / 360 * Math.pow(2, z)); }
  function lat2y(lat, z) {
    var r = lat * Math.PI / 180;
    return Math.floor((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * Math.pow(2, z));
  }
  function tileCount(lat, lon, km, zmax) {
    var b = bboxFor(lat, lon, km), total = 0;
    for (var z = 0; z <= zmax; z++) {
      var x0 = lon2x(b[0], z), x1 = lon2x(b[2], z);
      var y0 = lat2y(b[3], z), y1 = lat2y(b[1], z);
      total += (x1 - x0 + 1) * (y1 - y0 + 1);
    }
    return total;
  }
  function tileCountBbox(bbox, zmax) {
    var total = 0;
    for (var z = 0; z <= zmax; z++) {
      var x0 = lon2x(bbox[0], z), x1 = lon2x(bbox[2], z);
      var y0 = lat2y(bbox[3], z), y1 = lat2y(bbox[1], z);
      total += (x1 - x0 + 1) * (y1 - y0 + 1);
    }
    return total;
  }
  function paddedBbox() {
    if (typeof mapObj === "undefined" || !mapObj || !mapObj.getBounds) return null;
    var b = mapObj.getBounds();
    var west = b.getWest(), south = b.getSouth(), east = b.getEast(), north = b.getNorth();
    var padLon = (east - west) * 0.05;
    var padLat = (north - south) * 0.05;
    return [
      Math.max(-180, west - padLon),
      Math.max(-85.05112878, south - padLat),
      Math.min(180, east + padLon),
      Math.min(85.05112878, north + padLat)
    ];
  }
  var DOWNLOAD_MIN_ZOOM = 10;
  var TOTAL_BUDGET = 45 * 1024 * 1024;
  var VECTOR_BYTES_PER_TILE = 80 * 1024;
  var SATELLITE_BYTES_PER_TILE = 8 * 1024;
  function bboxEstimate(bbox) {
    var n = tileCountBbox(bbox, 14);
    return { tiles: n, bytes: n * (VECTOR_BYTES_PER_TILE + SATELLITE_BYTES_PER_TILE) };
  }
  function coveringAreaPack(lat, lon) {
    var packs = state.packs || [];
    for (var i = 0; i < packs.length; i++) {
      var p = packs[i];
      if (p.kind === "pmtiles" || !p.bbox || p.bbox.length !== 4) continue;
      if (lon >= p.bbox[0] && lon <= p.bbox[2] && lat >= p.bbox[1] && lat <= p.bbox[3]) return p;
    }
    return null;
  }
  function maybeSwitchOfflinePack() {
    if (typeof mapReady === "undefined" || !mapReady || typeof mapObj === "undefined" || !mapObj) return;
    if (typeof mapLoading !== "undefined" && mapLoading) return;
    var mode = (typeof currentSettings !== "undefined" && currentSettings && currentSettings.offline_mode) || currentMode();
    if (mode === "online") return;
    var c = center();
    if (!c) return;
    var p = coveringAreaPack(c.lat, c.lon);
    if (!p) return;
    if (typeof mapOfflinePack !== "undefined" && mapOfflinePack && mapOfflinePack.id === p.id) return;
    if (typeof resetMap === "function") {
      resetMap();
      if (typeof ensureMap === "function") ensureMap();
    }
  }

  function updateOfflineButton() {
    var btn = el("mapOfflineBtn");
    if (!btn) return;
    if (typeof mapReady === "undefined" || !mapReady || typeof mapObj === "undefined" || !mapObj) {
      btn.hidden = true;
      return;
    }
    if (mapObj.getZoom() < DOWNLOAD_MIN_ZOOM) {
      btn.hidden = true;
      return;
    }
    var bbox = paddedBbox();
    if (!bbox) { btn.hidden = true; return; }
    var est = bboxEstimate(bbox);
    var active = !!(state.job && state.job.active);
    btn.hidden = active || est.tiles > 3000 || est.bytes > TOTAL_BUDGET;
  }
  async function downloadVisibleArea() {
    if (typeof mapReady === "undefined" || !mapReady || !mapObj) return;
    if (mapObj.getZoom() < DOWNLOAD_MIN_ZOOM) { updateOfflineButton(); return; }
    if (state.job && state.job.active) return;
    var bbox = paddedBbox();
    if (!bbox) return;
    var est = bboxEstimate(bbox);
    if (est.tiles > 3000 || est.bytes > TOTAL_BUDGET) {
      msg(t("offline_visible_hint"), true);
      updateOfflineButton();
      return;
    }
    var panel = el("mapOfflinePanel");
    if (panel) panel.hidden = false;
    msg(t("offline_progress", { done: 0, total: est.tiles, mb: fmtBytes(0) }));
    try {
      var res = await fetch("/api/offline/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bbox: bbox, maxzoom: 14, satellite: true })
      });
      var data = await res.json();
      if (!data.ok) { msg(data.error || "error", true); return; }
      updateOfflineButton();
      await loadOfflineState();
    } catch (e) {
      msg(String(e), true);
    }
  }

  function approxVectorMb(n) { return n * 100 * 1024 / (1024 * 1024); }
  function approxSatMb(n) { return n * 12 * 1024 / (1024 * 1024); }
  function mb(v) { return (Math.round(v * 10) / 10).toFixed(1); }
  function areaInfoText(id, radius, c) {
    var e = el(id);
    if (!e) return;
    if (!c) { e.textContent = ""; return; }
    e.textContent = t("offline_area_info", {
      radius: radius,
      lat: Number(c.lat).toFixed(5),
      lon: Number(c.lon).toFixed(5)
    });
  }
  function estimateText(n, sat) {
    var vectorMb = approxVectorMb(n);
    var satMb = sat ? approxSatMb(n) : 0;
    if (n > 3000) return { text: t("offline_estimate_over", { tiles: n }), error: true };
    if (sat) return {
      text: t("offline_estimate_hybrid", {
        tiles: n, sat: n, vector_mb: mb(vectorMb), sat_mb: mb(satMb), total_mb: mb(vectorMb + satMb)
      }),
      error: vectorMb > 50
    };
    return { text: t("offline_estimate", { tiles: n, mb: mb(vectorMb) }), error: vectorMb > 50 };
  }
  function updateEstimate() {
    var c = center();
    var e = el("offlineEstimate");
    if (!e) return 0;
    if (!c) { e.textContent = t("offline_no_point"); e.classList.remove("err"); return 0; }
    var n = tileCount(c.lat, c.lon, radiusKm(), maxZoom());
    syncZoomLabel("offlineMaxZoom", "offlineMaxZoomValue");
    var sat = el("offlineSatellite") ? el("offlineSatellite").checked : true;
    var estimate = estimateText(n, sat);
    e.textContent = estimate.text;
    e.classList.toggle("err", estimate.error);
    areaInfoText("offlineAreaInfo", radiusKm(), c);
    return n;
  }
  function renderPacks() {
    var packs = state.packs || [];
    var total = 0;
    for (var i = 0; i < packs.length; i++) {
      total += Number(packs[i].bytes || 0);
      total += Number((packs[i].satellite && packs[i].satellite.bytes) || 0);
    }
    txt("offlinePacksSummary", t("offline_packs_summary", { count: packs.length, size: fmtBytes(total) }));
    var clear = el("offlineClear");
    if (clear) clear.disabled = packs.length === 0;
  }
  function renderStatus() {
    var storage = state.storage || {};
    txt("offlineStorage", t("offline_storage", { used: fmtBytes(storage.used_bytes), free: fmtBytes(storage.free_bytes) }));
    var job = state.job;
    if (job && job.active) {
      msg(t("offline_progress", { done: job.done || 0, total: job.total || 0, mb: fmtBytes(job.bytes || 0) }));
    } else if (state.message) {
      msg(state.message);
    } else if (job && job.satellite_error) {
      var satErr = job.satellite_error === "satellite_size_limit"
        ? t("offline_error_satellite_size_limit")
        : t("offline_satellite_failed", { error: job.satellite_error });
      msg(satErr, true);
    } else if (job && job.error) {
      if (job.error === "vector_size_limit") {
        if (lastSizeErrorJob !== job.id) {
          lastSizeErrorJob = job.id;
          var suggested = Math.max(0, Math.min(maxZoom(), intValue("mapOfflineMaxZoom", 14)) - 1);
          if (el("offlineMaxZoom")) {
            el("offlineMaxZoom").value = String(suggested);
            syncZoomLabel("offlineMaxZoom", "offlineMaxZoomValue");
            updateEstimate();
          }
          if (el("mapOfflineMaxZoom")) {
            el("mapOfflineMaxZoom").value = String(suggested);
            syncZoomLabel("mapOfflineMaxZoom", "mapOfflineMaxZoomValue");
            updateMapEstimate();
          }
        }
        msg(t("offline_error_vector_size_limit", { zoom: maxZoom() }), true);
      } else {
        msg(t("offline_error", { error: job.error }), true);
      }
    } else if (job && job.name) {
      msg(t("offline_done", { name: job.name }));
    } else if (!(state.packs || []).length) {
      msg(t("offline_no_packs"));
    } else {
      msg("");
    }
    var cancel = el("offlineCancel");
    if (cancel) cancel.hidden = !(job && job.active);
    var cancelMap = el("mapOfflineCancel");
    if (cancelMap) cancelMap.hidden = !(job && job.active);
    var dl = el("offlineDownload");
    if (dl) dl.disabled = !!(job && job.active);
    var dlMap = el("mapOfflineDownload");
    if (dlMap) dlMap.disabled = !!(job && job.active);
    updateOfflineButton();
  }
  function updateBadge() {
    var e = el("mapOfflineBadge");
    if (!e) return;
    if (!window.AndroidSettings) { e.hidden = true; return; }
    e.hidden = false;
    var onMap = typeof mapVisible === "function" && mapVisible() &&
      typeof mapReady !== "undefined" && mapReady;
    var mode = onMap && typeof mapOfflineMode !== "undefined" ? mapOfflineMode : currentMode();
    var p = onMap && typeof mapOfflinePack !== "undefined" ? mapOfflinePack : selectedPack();
    if (mode === "offline") {
      e.textContent = p ? t(p.satellite ? "offline_badge_hybrid" : "offline_badge_offline", { name: p.name || p.id }) : t("offline_badge_none");
      e.classList.toggle("bad", !p);
    } else if (mode === "auto" && p) {
      e.textContent = t(p.satellite ? "offline_badge_hybrid" : "offline_badge_auto", { name: p.name || p.id });
      e.classList.remove("bad");
    } else {
      e.textContent = t("offline_badge_online");
      e.classList.remove("bad");
    }
  }
  async function loadOfflineState() {
    if (!window.AndroidSettings) return;
    try {
      var res = await fetch("/api/offline", { cache: "no-store" });
      if (!res.ok) return;
      state = await res.json();
      var selected = (typeof currentSettings !== "undefined" && currentSettings && currentSettings.offline_pack) || "";
      if (lastPackId !== null && selected !== lastPackId && typeof resetMap === "function") {
        resetMap();
        if (typeof mapVisible === "function" && mapVisible() && typeof ensureMap === "function") ensureMap();
      }
      lastPackId = selected;
      renderPacks();
      renderStatus();
      updateBadge();
      updateOfflineButton();
    } catch (e) {}
  }
  function updateModeDescription() {
    var mode = el("offlineMode");
    var desc = el("offlineModeDesc");
    if (!mode || !desc) return;
    desc.textContent = t("offline_mode_" + (mode.value || "online") + "_desc");
  }

  function applyOfflineData(data) {
    if (!data) return;
    var mode = el("offlineMode");
    if (mode) mode.value = data.offline_mode === "offline" ? "offline" : data.offline_mode === "auto" ? "auto" : "online";
    var quick = el("mapModeQuick");
    if (quick) quick.value = mode ? mode.value : "online";
    updateModeDescription();
    loadOfflineState();
  }
  async function saveSetting(payload) {
    try {
      var res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      var data = await res.json();
      if (!data.ok) { msg(data.error || "error", true); return false; }
      if (data.settings) currentSettings = data.settings;
      if (typeof resetMap === "function") resetMap();
      if (typeof mapVisible === "function" && mapVisible() && typeof ensureMap === "function") ensureMap();
      await loadOfflineState();
      updateBadge();
      return true;
    } catch (e) {
      msg(String(e), true);
      return false;
    }
  }
  async function onModeChange() {
    updateModeDescription();
    await saveSetting({ offline_mode: currentMode() });
  }
  async function onQuickModeChange() {
    var quick = el("mapModeQuick");
    var mode = el("offlineMode");
    var value = quick ? quick.value : "online";
    if (mode) mode.value = value;
    updateModeDescription();
    await saveSetting({ offline_mode: value });
    updateBadge();
  }
  async function downloadArea() {
    var c = center();
    if (!c) { msg(t("offline_no_point"), true); return; }
    var n = updateEstimate();
    if (n > 3000) { msg(t("offline_estimate_over", { tiles: n }), true); return; }
    try {
      var res = await fetch("/api/offline/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lat: c.lat,
          lon: c.lon,
          radius_km: radiusKm(),
          maxzoom: maxZoom(),
          satellite: el("offlineSatellite") ? el("offlineSatellite").checked : true
        })
      });
      var data = await res.json();
      if (!data.ok) { msg(data.error || "error", true); return; }
      msg(t("offline_progress", { done: 0, total: data.job ? data.job.total : n, mb: fmtBytes(0) }));
      await loadOfflineState();
    } catch (e) { msg(String(e), true); }
  }
  async function cancelDownload() {
    try { await fetch("/api/offline/cancel", { method: "POST", body: "{}" }); } catch (e) {}
    await loadOfflineState();
  }
  async function clearOfflinePacks() {
    if (!(state.packs || []).length) return;
    if (!window.confirm(t("offline_clear_confirm"))) return;
    try {
      var res = await fetch("/api/offline/packs", { method: "DELETE" });
      var data = await res.json();
      if (!data.ok) { msg(data.error || "error", true); return; }
      if (currentSettings) currentSettings.offline_pack = null;
      if (typeof resetMap === "function") resetMap();
      await loadOfflineState();
      msg(t("offline_cleared"));
    } catch (e) { msg(String(e), true); }
  }
  function reasonText(code) {
    var key = "offline_reason_" + (code || "style");
    return t(key);
  }
  function mapSatellite() {
    var e = el("mapOfflineSatellite");
    return e ? e.checked : true;
  }
  function updateMapEstimate() {
    var c = center();
    var e = el("mapOfflineEstimate");
    if (!e) return 0;
    if (!c) { e.textContent = t("offline_no_point"); e.classList.remove("err"); return 0; }
    var r = el("mapOfflineRadius") ? Number(el("mapOfflineRadius").value) || 10 : 10;
    var z = intValue("mapOfflineMaxZoom", 14);
    syncZoomLabel("mapOfflineMaxZoom", "mapOfflineMaxZoomValue");
    var n = tileCount(c.lat, c.lon, r, z);
    var estimate = estimateText(n, mapSatellite());
    e.textContent = estimate.text;
    e.classList.toggle("err", estimate.error);
    areaInfoText("mapOfflineAreaInfo", r, c);
    return n;
  }
  function openMapPanel() {
    var p = el("mapOfflinePanel");
    if (p) p.hidden = false;
    syncZoomLabels();
    updateMapEstimate();
  }
  function closeMapPanel() {
    var p = el("mapOfflinePanel");
    if (p) p.hidden = true;
  }
  async function downloadFromMap() {
    var c = center();
    if (!c) { msg(t("offline_no_point"), true); return; }
    var n = updateMapEstimate();
    if (n > 3000) { msg(t("offline_estimate_over", { tiles: n }), true); return; }
    var r = el("mapOfflineRadius") ? Number(el("mapOfflineRadius").value) || 10 : 10;
    var z = intValue("mapOfflineMaxZoom", 14);
    try {
      var res = await fetch("/api/offline/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lat: c.lat, lon: c.lon, radius_km: r, maxzoom: z, satellite: mapSatellite() })
      });
      var data = await res.json();
      if (!data.ok) { msg(data.error || "error", true); return; }
      msg(t("offline_progress", { done: 0, total: data.job ? data.job.total : n, mb: fmtBytes(0) }));
      await loadOfflineState();
    } catch (e) { msg(String(e), true); }
  }

  function importPack() {
    if (window.AndroidSettings && typeof window.AndroidSettings.chooseOfflinePack === "function") {
      window.AndroidSettings.chooseOfflinePack();
      msg(t("offline_import_hint"));
    } else {
      msg(t("offline_not_android"), true);
    }
  }
  function setupSettingsAccordion() {
    var groups = Array.prototype.slice.call(document.querySelectorAll("#settingsPage .settingsBody > .settingsGroup"));
    if (!groups.length) return;
    groups.forEach(function (group) {
      if (group.dataset.accordionReady === "1") return;
      var title = null;
      for (var i = 0; i < group.children.length; i++) {
        if (group.children[i].classList && group.children[i].classList.contains("settingsLabel")) {
          title = group.children[i];
          break;
        }
      }
      if (!title) return;
      var header = document.createElement("div");
      header.className = "settingsAccordionHeader";
      header.setAttribute("role", "button");
      header.setAttribute("tabindex", "0");
      header.setAttribute("aria-expanded", "false");
      var body = document.createElement("div");
      body.className = "settingsAccordionBody";
      Array.prototype.slice.call(group.children).forEach(function (child) {
        if (child !== title) body.appendChild(child);
      });
      group.insertBefore(header, group.firstChild);
      header.appendChild(title);
      group.appendChild(body);
      group.classList.add("settingsAccordion");
      group.dataset.accordionReady = "1";
      function toggle() {
        var wasOpen = group.classList.contains("open");
        groups.forEach(function (other) {
          other.classList.remove("open");
          var h = other.querySelector(".settingsAccordionHeader");
          if (h) h.setAttribute("aria-expanded", "false");
        });
        if (!wasOpen) {
          group.classList.add("open");
          header.setAttribute("aria-expanded", "true");
        }
      }
      header.addEventListener("click", toggle);
      header.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggle();
        }
      });
    });
    var preferred = document.getElementById("sectionMap");
    if (!preferred) preferred = groups[0];
    if (preferred) {
      preferred.classList.add("open");
      var h = preferred.querySelector(".settingsAccordionHeader");
      if (h) h.setAttribute("aria-expanded", "true");
    }
  }

  function init() {
    if (!window.AndroidSettings) return;
    setupSettingsAccordion();
    var mode = el("offlineMode");
    if (mode) {
      mode.addEventListener("change", onModeChange);
      updateModeDescription();
    }
    var quick = el("mapModeQuick");
    if (quick) quick.addEventListener("change", onQuickModeChange);
    var dl = el("offlineDownload");
    if (dl) dl.addEventListener("click", downloadArea);
    var cancel = el("offlineCancel");
    if (cancel) cancel.addEventListener("click", cancelDownload);
    var imp = el("offlineImport");
    if (imp) imp.addEventListener("click", importPack);
    var clear = el("offlineClear");
    if (clear) clear.addEventListener("click", clearOfflinePacks);
    ["offlineRadius", "offlineMaxZoom"].forEach(function (id) {
      var e = el(id);
      if (e) e.addEventListener("input", updateEstimate);
    });
    var sat = el("offlineSatellite");
    if (sat) sat.addEventListener("change", updateEstimate);
    var mo = el("mapOfflineBtn");
    if (mo) {
      mo.title = t("offline_download_title");
      mo.setAttribute("aria-label", t("offline_download_title"));
      mo.addEventListener("click", downloadVisibleArea);
    }
    var mc = el("mapOfflineClose");
    if (mc) mc.addEventListener("click", closeMapPanel);
    var md = el("mapOfflineDownload");
    if (md) md.addEventListener("click", downloadFromMap);
    var mcx = el("mapOfflineCancel");
    if (mcx) mcx.addEventListener("click", cancelDownload);
    var msat = el("mapOfflineSatellite");
    if (msat) msat.addEventListener("change", updateMapEstimate);
    ["mapOfflineRadius", "mapOfflineMaxZoom"].forEach(function (id) {
      var e = el(id);
      if (e) e.addEventListener("input", updateMapEstimate);
    });
    syncZoomLabels();
    loadOfflineState();
  }

  window.applyOfflineData = applyOfflineData;
  window.loadOfflineState = loadOfflineState;
  window.updateOfflineBadge = updateBadge;
  window.updateOfflineButton = updateOfflineButton;
  window.maybeSwitchOfflinePack = maybeSwitchOfflinePack;
  window.addEventListener("DOMContentLoaded", init);
})();
