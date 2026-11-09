package com.elrs.backpack

import android.content.Context
import android.net.Uri
import android.os.StatFs
import android.provider.OpenableColumns
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

class OfflineManager(
    private val context: Context,
    private val settings: AppSettings,
    private val onChanged: () -> Unit,
) {
    companion object {
        const val MAX_TILES = 3000
        const val MAX_TOTAL_BYTES = 45L * 1024L * 1024L
        private const val CONCURRENCY = 4
        private const val TILEJSON_URL = "https://tiles.openfreemap.org/planet"
        private const val SATELLITE_TEMPLATE =
            "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg"
        private const val SATELLITE_LICENSE = "CC BY-NC-SA 4.0"
        private const val SATELLITE_ATTRIBUTION =
            "EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2025)"
        private const val USER_AGENT = "ELRS-Backpack-Telemetry/" + BuildConfig.VERSION_NAME + " (offline map)"
        private const val MAX_RETRIES = 2
    }

    data class Job(
        val active: Boolean,
        val id: String?,
        val name: String?,
        val total: Int,
        val done: Int,
        val bytes: Long,
        val error: String?,
        val cancelled: Boolean,
        val satellite: Boolean = false,
        val satelliteTotal: Int = 0,
        val satelliteDone: Int = 0,
        val satelliteBytes: Long = 0,
        val satelliteError: String? = null,
    )

    val root = File(context.filesDir, "offline")
    val pmtilesDir = File(context.filesDir, "tiles")
    private val lock = Any()
    @Volatile
    private var job: Job? = null
    @Volatile
    private var cancelled = false
    @Volatile
    private var message: String? = null
    private var worker: Thread? = null

    init {
        root.mkdirs()
        pmtilesDir.mkdirs()
    }

    fun listJson(): String {
        val packs = JSONArray()
        listAreaPacks().forEach { packs.put(it) }
        listPmtilesPacks().forEach { packs.put(it) }
        val used = totalBytes(packs)
        val free = try {
            StatFs(context.filesDir.absolutePath).availableBytes
        } catch (_: Exception) {
            0L
        }
        return JSONObject()
            .put("packs", packs)
            .put("message", message ?: JSONObject.NULL)
            .put("job", jobJson(snapshotJob()))
            .put("storage", JSONObject().put("used_bytes", used).put("free_bytes", free))
            .toString()
    }

    fun startBbox(
        minLon: Double,
        minLat: Double,
        maxLon: Double,
        maxLat: Double,
        maxZoom: Int,
        withSatellite: Boolean = true,
    ): Pair<Boolean, String> {
        if (minLon !in -180.0..180.0 || maxLon !in -180.0..180.0 ||
            minLat !in -85.0..85.0 || maxLat !in -85.0..85.0 ||
            minLon >= maxLon || minLat >= maxLat) {
            return Pair(false, "invalid bbox")
        }
        if (maxZoom !in 0..14) return Pair(false, "max zoom must be 0..14 (OpenFreeMap limit)")
        synchronized(lock) {
            if (job?.active == true) return Pair(false, "download already running")
        }
        val bbox = doubleArrayOf(minLon, minLat, maxLon, maxLat)
        val tiles = tileList(bbox, maxZoom)
        if (tiles.size > MAX_TILES) {
            return Pair(false, "area is larger than $MAX_TILES tiles; zoom in")
        }
        val free = try {
            StatFs(context.filesDir.absolutePath).availableBytes
        } catch (_: Exception) {
            0L
        }
        if (free in 1 until MAX_TOTAL_BYTES * 3) return Pair(false, "not enough free space")
        val id = "area_" + timestampId()
        message = null
        val name = String.format(Locale.US, "Visible area · z%d", maxZoom)
        val target = File(root, id)
        val temp = File(root, id + ".tmp")
        temp.deleteRecursively()
        temp.mkdirs()
        cancelled = false
        synchronized(lock) {
            job = Job(
                active = true,
                id = id,
                name = name,
                total = tiles.size,
                done = 0,
                bytes = 0,
                error = null,
                cancelled = false,
                satellite = withSatellite,
                satelliteTotal = if (withSatellite) tiles.size else 0,
            )
        }
        onChanged()
        worker = Thread({
            runDownload(id, name, bbox, maxZoom, tiles, temp, target, withSatellite)
        }, "elrs-offline-download").also { it.isDaemon = true; it.start() }
        return Pair(true, "")
    }

    fun cancel() {
        cancelled = true
        worker?.interrupt()
        synchronized(lock) {
            val current = job
            if (current != null && current.active) job = current.copy(active = false, cancelled = true, error = "cancelled")
        }
        onChanged()
    }

    fun deletePack(id: String): Boolean {
        if (!safeId(id)) return false
        val area = File(root, id)
        val pmtiles = File(pmtilesDir, "$id.pmtiles")
        val deleted = (area.isDirectory && area.deleteRecursively()) || (pmtiles.isFile && pmtiles.delete())
        if (deleted && settings.offlinePack == id) settings.offlinePack = null
        if (deleted) {
            message = "Deleted $id"
            onChanged()
        }
        return deleted
    }

    fun clearAll(): Boolean {
        var deleted = false
        root.listFiles()?.forEach { file ->
            if (file.deleteRecursively()) deleted = true
        }
        pmtilesDir.listFiles()?.forEach { file ->
            if (file.deleteRecursively()) deleted = true
        }
        settings.offlinePack = null
        message = if (deleted) "Offline maps cleared" else "No offline maps"
        onChanged()
        return true
    }

    fun findPack(id: String): Boolean {
        if (!safeId(id)) return false
        return File(root, id).isDirectory || File(pmtilesDir, "$id.pmtiles").isFile
    }

    fun importPmtiles(uri: Uri) {
        Thread({
            val display = queryName(uri) ?: "imported.pmtiles"
            val base = sanitizeName(display.removeSuffix(".pmtiles"))
            var id = base.ifEmpty { "imported" }
            var n = 2
            while (File(pmtilesDir, "$id.pmtiles").exists()) {
                id = base.ifEmpty { "imported" } + "_" + n
                n += 1
            }
            val dest = File(pmtilesDir, "$id.pmtiles")
            val temp = File(pmtilesDir, "$id.pmtiles.tmp")
            try {
                context.contentResolver.openInputStream(uri)?.use { input ->
                    FileOutputStream(temp).use { output -> input.copyTo(output, 128 * 1024) }
                } ?: throw IllegalStateException("cannot open file")
                if (temp.length() <= 0) throw IllegalStateException("empty file")
                val magic = ByteArray(7)
                val read = temp.inputStream().use { it.read(magic) }
                if (read != 7 || String(magic, Charsets.US_ASCII) != "PMTiles") {
                    throw IllegalStateException("not a PMTiles archive")
                }
                if (!temp.renameTo(dest)) throw IllegalStateException("cannot save file")
                settings.offlinePack = id
                message = "Imported $id.pmtiles"
                onChanged()
            } catch (e: Exception) {
                temp.delete()
                dest.delete()
                message = "Import failed: " + (e.message ?: "unknown error")
                onChanged()
            }
        }, "elrs-offline-import").also { it.isDaemon = true; it.start() }
    }

    private fun runDownload(
        id: String,
        name: String,
        bbox: DoubleArray,
        maxZoom: Int,
        tiles: List<Triple<Int, Int, Int>>,
        temp: File,
        target: File,
        withSatellite: Boolean,
    ) {
        var error: String? = null
        var satelliteError: String? = null
        val done = AtomicLong(0)
        val bytes = AtomicLong(0)
        val satelliteDone = AtomicLong(0)
        val satelliteBytes = AtomicLong(0)
        try {
            val template = fetchTileTemplate()
            val pool = Executors.newFixedThreadPool(CONCURRENCY)
            try {
                for (tile in tiles) {
                    if (cancelled) break
                    pool.execute {
                        if (cancelled) return@execute
                        try {
                            val data = downloadTile(template, tile.first, tile.second, tile.third)
                            val newBytes = bytes.addAndGet(data.size.toLong())
                            if (newBytes > MAX_TOTAL_BYTES) {
                                cancelled = true
                                synchronized(lock) {
                                    job = (job ?: return@execute).copy(error = "vector_size_limit")
                                }
                                return@execute
                            }
                            val file = File(temp, "${tile.first}/${tile.second}/${tile.third}.pbf")
                            file.parentFile?.mkdirs()
                            FileOutputStream(file).use { it.write(data) }
                            val currentDone = done.incrementAndGet().toInt()
                            synchronized(lock) {
                                job = (job ?: return@execute).copy(done = currentDone, bytes = newBytes)
                            }
                            if (currentDone % 10 == 0) onChanged()
                        } catch (e: Exception) {
                            if (!cancelled) {
                                cancelled = true
                                synchronized(lock) {
                                    job = (job ?: return@execute).copy(error = e.message ?: "download failed")
                                }
                            }
                        }
                    }
                }
            } finally {
                pool.shutdown()
                try {
                    while (!pool.awaitTermination(30, TimeUnit.SECONDS)) {
                        if (cancelled) {
                            pool.shutdownNow()
                            break
                        }
                    }
                } catch (_: InterruptedException) {
                    pool.shutdownNow()
                }
            }
            if (!cancelled && withSatellite) {
                val satPool = Executors.newFixedThreadPool(CONCURRENCY)
                try {
                    for (tile in tiles) {
                        if (cancelled || satelliteError != null) break
                        satPool.execute {
                            if (cancelled || satelliteError != null) return@execute
                            try {
                                val data = downloadTile(SATELLITE_TEMPLATE, tile.first, tile.second, tile.third)
                                val newSatBytes = satelliteBytes.addAndGet(data.size.toLong())
                                if (bytes.get() + newSatBytes > MAX_TOTAL_BYTES) {
                                    satelliteError = "satellite_size_limit"
                                    return@execute
                                }
                                val file = File(temp, "sat/${tile.first}/${tile.second}/${tile.third}.jpg")
                                file.parentFile?.mkdirs()
                                FileOutputStream(file).use { it.write(data) }
                                val currentDone = satelliteDone.incrementAndGet().toInt()
                                synchronized(lock) {
                                    job = (job ?: return@execute).copy(
                                        satelliteDone = currentDone,
                                        satelliteBytes = newSatBytes,
                                    )
                                }
                                if (currentDone % 10 == 0) onChanged()
                            } catch (e: Exception) {
                                if (satelliteError == null) satelliteError = e.message ?: "satellite download failed"
                            }
                        }
                    }
                } finally {
                    satPool.shutdown()
                    try {
                        while (!satPool.awaitTermination(30, TimeUnit.SECONDS)) {
                            if (cancelled || satelliteError != null) {
                                satPool.shutdownNow()
                                break
                            }
                        }
                    } catch (_: InterruptedException) {
                        satPool.shutdownNow()
                    }
                }
                if (satelliteError != null) {
                    File(temp, "sat").deleteRecursively()
                }
            }
            if (cancelled) {
                error = synchronized(lock) { job?.error } ?: "cancelled"
            } else {
                writeManifest(
                    temp,
                    id,
                    name,
                    bbox,
                    maxZoom,
                    tiles.size,
                    bytes.get(),
                    withSatellite && satelliteError == null,
                    satelliteDone.get().toInt(),
                    satelliteBytes.get(),
                    satelliteError,
                )
                target.deleteRecursively()
                if (!temp.renameTo(target)) throw IllegalStateException("cannot save pack")
                settings.offlinePack = id
            }
        } catch (e: Exception) {
            error = e.message ?: "download failed"
            temp.deleteRecursively()
        }
        synchronized(lock) {
            job = Job(
                active = false,
                id = id,
                name = name,
                total = tiles.size,
                done = done.get().toInt(),
                bytes = bytes.get(),
                error = error,
                cancelled = error == "cancelled",
                satellite = withSatellite,
                satelliteTotal = if (withSatellite) tiles.size else 0,
                satelliteDone = satelliteDone.get().toInt(),
                satelliteBytes = satelliteBytes.get(),
                satelliteError = satelliteError,
            )
        }
        onChanged()
    }

    private fun writeManifest(
        dir: File,
        id: String,
        name: String,
        bbox: DoubleArray,
        maxZoom: Int,
        tiles: Int,
        bytes: Long,
        satelliteOk: Boolean,
        satelliteTiles: Int,
        satelliteBytes: Long,
        satelliteError: String?,
    ) {
        val manifest = JSONObject()
            .put("id", id)
            .put("kind", "area")
            .put("name", name)
            .put("bbox", JSONArray(bbox.toList()))
            .put("center", JSONArray(listOf((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)))
            .put("minzoom", 0)
            .put("maxzoom", maxZoom)
            .put("tiles", tiles)
            .put("bytes", bytes)
            .put("created", isoNow())
            .put("tile_url", "/offline/$id/{z}/{x}/{y}.pbf")
        if (satelliteOk) {
            manifest.put(
                "satellite",
                JSONObject()
                    .put("source", "EOxCloudless 2025")
                    .put("tile_url", "/offline/$id/sat/{z}/{x}/{y}.jpg")
                    .put("tiles", satelliteTiles)
                    .put("bytes", satelliteBytes)
                    .put("maxzoom", maxZoom)
                    .put("license", SATELLITE_LICENSE)
                    .put("attribution", SATELLITE_ATTRIBUTION)
            )
        } else if (satelliteError != null) {
            manifest.put("satellite_error", satelliteError)
        }
        File(dir, "manifest.json").writeText(manifest.toString(), Charsets.UTF_8)
    }

    private fun fetchTileTemplate(): String {
        val text = httpGet(TILEJSON_URL)
        val json = JSONObject(text)
        val tiles = json.optJSONArray("tiles") ?: throw IllegalStateException("tilejson has no tiles")
        val first = tiles.optString(0, "")
        if (first.isEmpty()) throw IllegalStateException("tilejson has no tile url")
        return first
    }

    private fun downloadTile(template: String, z: Int, x: Int, y: Int): ByteArray {
        val url = template.replace("{z}", z.toString()).replace("{x}", x.toString()).replace("{y}", y.toString())
        var last: Exception? = null
        for (attempt in 0..MAX_RETRIES) {
            try {
                return httpGetBytes(url)
            } catch (e: Exception) {
                last = e
                if (cancelled) break
                Thread.sleep(300L * (attempt + 1))
            }
        }
        throw last ?: IllegalStateException("download failed")
    }

    private fun httpGet(url: String): String = httpGetBytes(url).toString(Charsets.UTF_8)

    private fun httpGetBytes(url: String): ByteArray {
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 20000
            readTimeout = 30000
            requestMethod = "GET"
            setRequestProperty("User-Agent", USER_AGENT)
            setRequestProperty("Accept", "application/json, application/x-protobuf, */*")
        }
        try {
            val code = connection.responseCode
            if (code !in 200..299) throw IllegalStateException("HTTP $code")
            return connection.inputStream.use { it.readBytes() }
        } finally {
            connection.disconnect()
        }
    }

    private fun listAreaPacks(): List<JSONObject> {
        val result = mutableListOf<JSONObject>()
        val dirs = root.listFiles() ?: return result
        for (dir in dirs) {
            if (!dir.isDirectory || dir.name.endsWith(".tmp")) continue
            val manifest = File(dir, "manifest.json")
            if (!manifest.isFile) continue
            try {
                val json = JSONObject(manifest.readText())
                if (json.optString("kind") != "area") json.put("kind", "area")
                result.add(json)
            } catch (_: Exception) {
            }
        }
        return result
    }

    private fun listPmtilesPacks(): List<JSONObject> {
        val result = mutableListOf<JSONObject>()
        val files = pmtilesDir.listFiles() ?: return result
        for (file in files) {
            if (!file.isFile || !file.name.endsWith(".pmtiles")) continue
            val id = file.name.removeSuffix(".pmtiles")
            result.add(
                JSONObject()
                    .put("id", id)
                    .put("kind", "pmtiles")
                    .put("name", id)
                    .put("bytes", file.length())
                    .put("minzoom", 0)
                    .put("maxzoom", 15)
                    .put("url", "/tiles/" + Uri.encode(file.name))
            )
        }
        return result
    }

    private fun totalBytes(packs: JSONArray): Long {
        var total = 0L
        for (i in 0 until packs.length()) {
            val pack = packs.optJSONObject(i) ?: continue
            total += pack.optLong("bytes", 0L)
            total += pack.optJSONObject("satellite")?.optLong("bytes", 0L) ?: 0L
        }
        return total
    }

    private fun snapshotJob(): Job? = synchronized(lock) { job }

    private fun jobJson(job: Job?): JSONObject {
        if (job == null) return JSONObject().put("active", false)
        return JSONObject()
            .put("active", job.active)
            .put("id", job.id ?: JSONObject.NULL)
            .put("name", job.name ?: JSONObject.NULL)
            .put("total", job.total)
            .put("done", job.done)
            .put("bytes", job.bytes)
            .put("error", job.error ?: JSONObject.NULL)
            .put("cancelled", job.cancelled)
            .put("satellite", job.satellite)
            .put("satellite_total", job.satelliteTotal)
            .put("satellite_done", job.satelliteDone)
            .put("satellite_bytes", job.satelliteBytes)
            .put("satellite_error", job.satelliteError ?: JSONObject.NULL)
    }

    private fun queryName(uri: Uri): String? {
        return try {
            context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) cursor.getString(0) else null
            }
        } catch (_: Exception) {
            uri.lastPathSegment
        }
    }

    private fun sanitizeName(value: String): String =
        value.replace(Regex("[^A-Za-z0-9._-]+"), "_").trim('_', '.').take(64)

    private fun safeId(id: String): Boolean =
        id.isNotEmpty() && id.length <= 96 && id.all { it.isLetterOrDigit() || it == '_' || it == '-' || it == '.' }

    private fun bboxFor(lat: Double, lon: Double, radiusKm: Double): DoubleArray {
        val dlat = radiusKm / 111.32
        val dlon = radiusKm / (111.32 * Math.cos(lat * Math.PI / 180.0))
        return doubleArrayOf(
            (lon - dlon).coerceIn(-180.0, 180.0),
            (lat - dlat).coerceIn(-85.05112878, 85.05112878),
            (lon + dlon).coerceIn(-180.0, 180.0),
            (lat + dlat).coerceIn(-85.05112878, 85.05112878),
        )
    }

    private fun tileList(bbox: DoubleArray, maxZoom: Int): List<Triple<Int, Int, Int>> {
        val result = mutableListOf<Triple<Int, Int, Int>>()
        for (z in 0..maxZoom) {
            val x0 = lonToTileX(bbox[0], z)
            val x1 = lonToTileX(bbox[2], z)
            val y0 = latToTileY(bbox[3], z)
            val y1 = latToTileY(bbox[1], z)
            for (x in x0..x1) for (y in y0..y1) {
                result.add(Triple(z, x, y))
                if (result.size > MAX_TILES) return result
            }
        }
        return result
    }

    private fun lonToTileX(lon: Double, z: Int): Int {
        val n = 1 shl z
        return ((lon + 180.0) / 360.0 * n).toInt().coerceIn(0, n - 1)
    }

    private fun latToTileY(lat: Double, z: Int): Int {
        val n = 1 shl z
        val r = Math.toRadians(lat)
        val y = (1.0 - Math.log(Math.tan(r) + 1.0 / Math.cos(r)) / Math.PI) / 2.0 * n
        return y.toInt().coerceIn(0, n - 1)
    }

    private fun timestampId(): String {
        val fmt = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US)
        fmt.timeZone = TimeZone.getDefault()
        return fmt.format(Date())
    }

    private fun isoNow(): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US)
        return fmt.format(Date())
    }
}
