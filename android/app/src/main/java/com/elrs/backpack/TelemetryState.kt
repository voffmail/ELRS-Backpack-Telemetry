package com.elrs.backpack

import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.ArrayDeque
import java.util.Date
import java.util.Locale
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.round

private data class Link(
    val rssi1: Int,
    val rssi2: Int,
    val lq: Int,
    val snr: Int,
    val activeAnt: Int,
    val rfMode: Int,
    val txPower: Int,
    val rssiD: Int,
    val lqD: Int,
    val snrD: Int,
) {
    fun toJson() = JSONObject()
        .put("rssi1", rssi1)
        .put("rssi2", rssi2)
        .put("lq", lq)
        .put("snr", snr)
        .put("active_ant", activeAnt)
        .put("rf_mode", rfMode)
        .put("tx_power", txPower)
        .put("rssi_d", rssiD)
        .put("lq_d", lqD)
        .put("snr_d", snrD)
}

private data class Attitude(val pitch: Double, val roll: Double, val yaw: Double) {
    fun toJson() = JSONObject().put("pitch", pitch).put("roll", roll).put("yaw", yaw)
}

private data class Gps(
    val lat: Double,
    val lon: Double,
    val speed: Double,
    val heading: Double,
    val alt: Double,
    val sats: Int,
    val fix: Boolean,
    val fix3d: Boolean,
) {
    fun toJson() = JSONObject()
        .put("lat", lat)
        .put("lon", lon)
        .put("speed", speed)
        .put("heading", heading)
        .put("alt", alt)
        .put("sats", sats)
        .put("fix", fix)
        .put("fix3d", fix3d)
}

private data class Battery(
    val voltage: Double,
    val current: Double,
    val capacity: Int,
    val remaining: Int,
) {
    fun toJson() = JSONObject()
        .put("voltage", voltage)
        .put("current", current)
        .put("capacity", capacity)
        .put("remaining", remaining)
}

private data class Baro(val alt: Double, val vario: Double) {
    fun toJson() = JSONObject().put("alt", alt).put("vario", vario)
}

private data class GpsExt(
    val fixType: Int,
    val vn: Double,
    val ve: Double,
    val vv: Double,
    val hAcc: Double,
    val vAcc: Double,
    val hdop: Double,
    val vdop: Double,
) {
    fun toJson() = JSONObject()
        .put("fix_type", fixType)
        .put("vn", vn)
        .put("ve", ve)
        .put("vv", vv)
        .put("h_acc", hAcc)
        .put("v_acc", vAcc)
        .put("hdop", hdop)
        .put("vdop", vdop)
}

data class TrackPoint(
    val t: Double,
    val lat: Double,
    val lon: Double,
    val alt: Double,
    val speed: Double,
    val heading: Double,
    val sats: Int,
) {
    fun toJson() = JSONObject()
        .put("t", t)
        .put("lat", lat)
        .put("lon", lon)
        .put("alt", alt)
        .put("speed", speed)
        .put("heading", heading)
        .put("sats", sats)
}

class TelemetryState(initialStore: TrackStore) {

    private var store: TrackStore = initialStore

    fun setTrackStore(newStore: TrackStore) = synchronized(lock) {
        store = newStore
    }

    fun currentStore(): TrackStore = synchronized(lock) { store }

    fun tracksLocation(): String = synchronized(lock) { store.location() }

    fun isRecording(): Boolean = synchronized(lock) { recording.active }

    fun totalPackets(): Long = synchronized(lock) { total }

    fun lastPacketAgeSeconds(): Double? = synchronized(lock) {
        if (last == 0L) null else (System.currentTimeMillis() - last) / 1000.0
    }

    fun recentPps(windowSeconds: Double): Int = synchronized(lock) {
        if (windowSeconds <= 0.0) {
            0
        } else {
            val cutoff = System.currentTimeMillis() - (windowSeconds * 1000.0).toLong()
            var count = 0
            for (t in times) if (t >= cutoff) count += 1
            (count / windowSeconds).toInt()
        }
    }

    companion object {
        private val TRACK_ID = Regex("[A-Za-z0-9_-]{1,80}")
        private const val MAX_TIMES = 4000
        private val RAD_TO_DEG = 180.0 / Math.PI / 10000.0
    }

    private class Recording(
        var active: Boolean = false,
        var id: String? = null,
        var startMono: Long = 0L,
        var startedAt: String? = null,
        val points: MutableList<TrackPoint> = ArrayList(),
    )

    private val lock = Any()

    private var link: Link? = null
    private var battery: Battery? = null
    private var gps: Gps? = null
    private var gpsLast: Gps? = null
    private var gpsExt: GpsExt? = null
    private var gpsExtAt = 0L
    private var gpsTime: String? = null
    private var attitude: Attitude? = null
    private var baro: Baro? = null
    private var vario: Double? = null
    private var flightMode: String? = null
    private var device: String? = null
    private val frames = LinkedHashMap<Int, Int>()
    private val unknown = LinkedHashMap<Int, String>()

    private var total = 0L
    private val times = ArrayDeque<Long>()
    private var last = 0L

    private val recording = Recording()

    fun onDatagram(data: ByteArray, length: Int) {
        val now = System.currentTimeMillis()
        synchronized(lock) {
            total += 1
            times.addLast(now)
            while (times.size > MAX_TIMES) times.removeFirst()
            last = now

            var i = 0
            val n = length
            while (i < n - 2) {
                val address = u(data, i)
                if (address == 0xC8 || address == 0xEA || address == 0xEE) {
                    val frameLength = u(data, i + 1)
                    if (frameLength in 2..62 && i + 2 + frameLength <= n) {
                        val crcIndex = i + 2 + frameLength - 1
                        if (crc8(data, i + 2, crcIndex) == u(data, crcIndex)) {
                            val type = u(data, i + 2)
                            frames[type] = (frames[type] ?: 0) + 1
                            parseFrame(type, data, i + 3, crcIndex)
                            i += 2 + frameLength
                            continue
                        }
                    }
                }
                i += 1
            }
        }
    }

    private fun parseFrame(type: Int, data: ByteArray, from: Int, to: Int) {
        val len = to - from
        when (type) {
            0x14 -> if (len >= 10) {
                link = Link(
                    rssi1 = s8(u(data, from)),
                    rssi2 = s8(u(data, from + 1)),
                    lq = u(data, from + 2),
                    snr = s8(u(data, from + 3)),
                    activeAnt = u(data, from + 4),
                    rfMode = u(data, from + 5),
                    txPower = u(data, from + 6),
                    rssiD = s8(u(data, from + 7)),
                    lqD = u(data, from + 8),
                    snrD = s8(u(data, from + 9)),
                )
            }

            0x1E -> if (len >= 6) {
                val pitch = s16(data, from)
                val roll = s16(data, from + 2)
                val yaw = s16(data, from + 4)
                attitude = Attitude(pitch * RAD_TO_DEG, roll * RAD_TO_DEG, yaw * RAD_TO_DEG)
            }

            0x02 -> if (len >= 15) {
                val lat = s32(data, from)
                val lon = s32(data, from + 4)
                val speed = u16(data, from + 8)
                val heading = u16(data, from + 10)
                val alt = u16(data, from + 12)
                val sats = u(data, from + 14)
                val nowMono = SystemClock.elapsedRealtime()
                val freshExt = gpsExt?.let { nowMono - gpsExtAt <= 5000L } == true
                val ext = gpsExt
                val fix3d: Boolean
                val fixPos: Boolean
                if (freshExt && ext != null) {
                    fix3d = ext.fixType == 3 && sats >= 4
                    fixPos = ext.fixType in 2..3 && sats >= 3
                } else {
                    fix3d = sats >= 4
                    fixPos = sats >= 3
                }
                val fixData = Gps(
                    lat = lat / 1e7,
                    lon = lon / 1e7,
                    speed = speed / 10.0,
                    heading = heading / 100.0,
                    alt = (alt - 1000).toDouble(),
                    sats = sats,
                    fix = fixPos,
                    fix3d = fix3d,
                )
                gps = fixData
                if (fixPos) {
                    gpsLast = fixData
                    if (fix3d && recording.active) {
                        recording.points.add(
                            TrackPoint(
                                t = (nowMono - recording.startMono) / 1000.0,
                                lat = fixData.lat,
                                lon = fixData.lon,
                                alt = fixData.alt,
                                speed = fixData.speed,
                                heading = fixData.heading,
                                sats = fixData.sats,
                            ),
                        )
                    }
                }
            }

            0x08 -> if (len >= 8) {
                val voltage = u16(data, from)
                val current = u16(data, from + 2)
                val capacity = (u(data, from + 4) shl 16) or
                    (u(data, from + 5) shl 8) or u(data, from + 6)
                battery = Battery(
                    voltage = voltage / 10.0,
                    current = current / 10.0,
                    capacity = capacity,
                    remaining = u(data, from + 7),
                )
            }

            0x07 -> if (len >= 2) {
                vario = s16(data, from) / 100.0
            }

            0x09 -> if (len >= 3) {
                val raw = u16(data, from)
                val vs = s8(u(data, from + 2))
                val alt = if (raw and 0x8000 != 0) {
                    (raw and 0x7FFF).toDouble()
                } else {
                    (raw - 10000) / 10.0
                }
                val magnitude = (exp(abs(vs) * 0.026) - 1.0) * 100.0
                baro = Baro(alt = alt, vario = (if (vs >= 0) magnitude else -magnitude) / 100.0)
            }

            0x03 -> if (len >= 9) {
                val year = u16(data, from)
                val month = u(data, from + 2)
                val day = u(data, from + 3)
                val hour = u(data, from + 4)
                val minute = u(data, from + 5)
                val second = u(data, from + 6)
                val millis = u16(data, from + 7)
                gpsTime = String.format(
                    Locale.US,
                    "%04d-%02d-%02d %02d:%02d:%02d.%03d",
                    year, month, day, hour, minute, second, millis,
                )
            }

            0x06 -> if (len >= 20) {
                gpsExt = GpsExt(
                    fixType = u(data, from),
                    vn = s16(data, from + 1) / 100.0,
                    ve = s16(data, from + 3) / 100.0,
                    vv = s16(data, from + 5) / 100.0,
                    hAcc = s16(data, from + 13) / 100.0,
                    vAcc = s16(data, from + 15) / 100.0,
                    hdop = u(data, from + 18) / 10.0,
                    vdop = u(data, from + 19) / 10.0,
                )
                gpsExtAt = SystemClock.elapsedRealtime()
            }

            0x21 -> if (len > 0) {
                flightMode = asciiReplace(data, from, to)
            }

            0x29 -> if (len > 2) {
                val name = asciiReplace(data, from + 2, to)
                if (name.isNotEmpty()) device = name
            }

            else -> unknown[type] = hex(data, from, to)
        }
    }

    fun snapshotJson(): String = synchronized(lock) {
        buildSnapshot().toString()
    }

    private fun buildSnapshot(): JSONObject {
        val now = System.currentTimeMillis()
        var pps = 0
        for (t in times) {
            if (now - t <= 1000L) pps += 1
        }
        val age: Any = if (last != 0L) (now - last) / 1000.0 else JSONObject.NULL

        val record = JSONObject()
            .put("active", recording.active)
            .put("id", recording.id ?: JSONObject.NULL)
            .put("started_at", recording.startedAt ?: JSONObject.NULL)
            .put(
                "duration",
                if (recording.active) (SystemClock.elapsedRealtime() - recording.startMono) / 1000.0 else 0.0,
            )
            .put("point_count", recording.points.size)

        val framesJson = JSONObject()
        for ((key, value) in frames) framesJson.put(key.toString(), value)
        val unknownJson = JSONObject()
        for ((key, value) in unknown) unknownJson.put(key.toString(), value)

        return JSONObject()
            .put("link", link?.toJson() ?: JSONObject.NULL)
            .put("battery", battery?.toJson() ?: JSONObject.NULL)
            .put("gps", gps?.toJson() ?: JSONObject.NULL)
            .put("gps_last", gpsLast?.toJson() ?: JSONObject.NULL)
            .put("gps_ext", gpsExt?.toJson() ?: JSONObject.NULL)
            .put("gps_time", gpsTime ?: JSONObject.NULL)
            .put("attitude", attitude?.toJson() ?: JSONObject.NULL)
            .put("baro", baro?.toJson() ?: JSONObject.NULL)
            .put("vario", vario ?: JSONObject.NULL)
            .put("flight_mode", flightMode ?: JSONObject.NULL)
            .put("device", device ?: JSONObject.NULL)
            .put("frames", framesJson)
            .put("unknown", unknownJson)
            .put("record", record)
            .put("stats", JSONObject().put("total", total).put("pps", pps).put("age", age))
    }

    fun startRecording(): Pair<Boolean, String> = synchronized(lock) {
        if (recording.active) {
            return@synchronized Pair(false, "already recording")
        }
        recording.active = true
        recording.id = nextTrackId()
        recording.startMono = SystemClock.elapsedRealtime()
        recording.startedAt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(Date())
        recording.points.clear()
        Pair(true, "")
    }

    fun stopRecording(): Pair<JSONObject?, String> {
        var points: List<TrackPoint>? = null
        var trackId: String? = null
        var startedAt: String? = null
        var targetStore: TrackStore? = null
        synchronized(lock) {
            if (!recording.active) return Pair(null, "not recording")
            points = ArrayList(recording.points)
            trackId = recording.id
            startedAt = recording.startedAt
            targetStore = store
            recording.active = false
            recording.id = null
            recording.startedAt = null
            recording.startMono = 0L
            recording.points.clear()
        }
        val savedPoints = points ?: return Pair(null, "not recording")
        val savedId = trackId ?: return Pair(null, "not recording")
        if (savedPoints.isEmpty()) return Pair(null, "no GPS points recorded")

        val duration = round(savedPoints.last().t * 1000.0) / 1000.0
        val meta = JSONObject()
            .put("id", savedId)
            .put("started_at", startedAt ?: JSONObject.NULL)
            .put("duration", duration)
            .put("point_count", savedPoints.size)
        val pointsJson = JSONArray()
        for (point in savedPoints) pointsJson.put(point.toJson())
        meta.put("points", pointsJson)

        val storeToUse = targetStore ?: return Pair(null, "not recording")
        if (!storeToUse.write(savedId, meta.toString())) {
            return Pair(null, "failed to save track")
        }
        return Pair(meta.toJsonMeta(), "")
    }

    fun recordSnapshotJson(since: Int): String = synchronized(lock) {
        val totalPoints = recording.points.size
        val start = since.coerceIn(0, totalPoints)
        val pointsJson = JSONArray()
        for (index in start until totalPoints) pointsJson.put(recording.points[index].toJson())
        JSONObject()
            .put("active", recording.active)
            .put("id", recording.id ?: JSONObject.NULL)
            .put("started_at", recording.startedAt ?: JSONObject.NULL)
            .put(
                "duration",
                if (recording.active) (SystemClock.elapsedRealtime() - recording.startMono) / 1000.0 else 0.0,
            )
            .put("total", totalPoints)
            .put("points", pointsJson)
            .toString()
    }

    fun listTracksJson(): String {
        val activeStore = synchronized(lock) { store }
        val entries = ArrayList<JSONObject>()
        for (storeId in activeStore.listIds()) {
            val data = try {
                JSONObject(activeStore.read(storeId) ?: continue)
            } catch (_: Exception) {
                continue
            }
            val id = data.optString("id", storeId)
            val startedAt = if (data.has("started_at") && !data.isNull("started_at")) {
                data.optString("started_at")
            } else {
                ""
            }
            entries.add(
                JSONObject()
                    .put("id", id)
                    .put("started_at", startedAt)
                    .put("duration", data.optDouble("duration", 0.0))
                    .put(
                        "point_count",
                        data.optInt("point_count", data.optJSONArray("points")?.length() ?: 0),
                    ),
            )
        }
        entries.sortByDescending { it.optString("started_at", "") }
        val result = JSONArray()
        for (entry in entries) result.put(entry)
        return JSONObject().put("tracks", result).toString()
    }

    fun loadTrackJson(trackId: String?): String? {
        val id = trackId ?: return null
        if (!isValidTrackId(id)) return null
        val activeStore = synchronized(lock) { store }
        return try {
            JSONObject(activeStore.read(id) ?: return null).toString()
        } catch (_: Exception) {
            null
        }
    }

    fun deleteTrack(trackId: String?): Boolean {
        val id = trackId ?: return false
        if (!isValidTrackId(id)) return false
        val activeStore = synchronized(lock) { store }
        return activeStore.delete(id)
    }

    private fun isValidTrackId(trackId: String?): Boolean =
        trackId != null && TRACK_ID.matches(trackId)

    private fun nextTrackId(): String {
        val base = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        val existing = store.listIds().toHashSet()
        var candidate = "track_$base"
        var n = 2
        while (existing.contains(candidate)) {
            candidate = "track_${base}_$n"
            n += 1
        }
        return candidate
    }

    private fun JSONObject.toJsonMeta(): JSONObject = JSONObject()
        .put("id", optString("id"))
        .put("started_at", opt("started_at") ?: JSONObject.NULL)
        .put("duration", optDouble("duration", 0.0))
        .put("point_count", optInt("point_count", 0))

    private fun u(data: ByteArray, index: Int): Int = data[index].toInt() and 0xFF

    private fun u16(data: ByteArray, index: Int): Int = (u(data, index) shl 8) or u(data, index + 1)

    private fun s16(data: ByteArray, index: Int): Int {
        val value = u16(data, index)
        return if (value > 0x7FFF) value - 0x10000 else value
    }

    private fun s32(data: ByteArray, index: Int): Int =
        (u(data, index) shl 24) or
            (u(data, index + 1) shl 16) or
            (u(data, index + 2) shl 8) or
            u(data, index + 3)

    private fun s8(value: Int): Int = if (value > 127) value - 256 else value

    private fun crc8(data: ByteArray, from: Int, until: Int): Int {
        var crc = 0
        for (index in from until until) {
            crc = crc xor (data[index].toInt() and 0xFF)
            repeat(8) {
                crc = if (crc and 0x80 != 0) {
                    ((crc shl 1) xor 0xD5) and 0xFF
                } else {
                    (crc shl 1) and 0xFF
                }
            }
        }
        return crc
    }

    private fun asciiReplace(data: ByteArray, from: Int, to: Int): String {
        val builder = StringBuilder()
        for (index in from until to) {
            val value = u(data, index)
            if (value == 0) break
            builder.append(if (value <= 0x7F) value.toChar() else '\uFFFD')
        }
        return builder.toString()
    }

    private fun hex(data: ByteArray, from: Int, to: Int): String {
        val builder = StringBuilder((to - from) * 2)
        for (index in from until to) {
            builder.append(HEX[u(data, index) ushr 4])
            builder.append(HEX[u(data, index) and 0x0F])
        }
        return builder.toString()
    }

    private val HEX = "0123456789abcdef".toCharArray()
}
