package com.elrs.backpack

import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.ArrayDeque
import java.util.Date
import java.util.Locale
import java.util.TimeZone
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
    val fixType: Int,
    val fixTypeComputed: Boolean,
) {
    fun toJson() = JSONObject()
        .put("lat", lat)
        .put("lon", lon)
        .put("speed", speed)
        .put("heading", heading)
        .put("alt", alt)
        .put("sats", sats)
        .put("fix_type", fixType)
        .put("fix_type_computed", fixTypeComputed)
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
    val speedAcc: Double,
    val trackAcc: Double,
    val altEllipsoid: Double,
    val hAcc: Double,
    val vAcc: Double,
    val reserved: Int,
    val hdop: Double,
    val vdop: Double,
) {
    fun toJson() = JSONObject()
        .put("fix_type", fixType)
        .put("vn", vn)
        .put("ve", ve)
        .put("vv", vv)
        .put("speed_acc", speedAcc)
        .put("track_acc", trackAcc)
        .put("alt_ellipsoid", altEllipsoid)
        .put("h_acc", hAcc)
        .put("v_acc", vAcc)
        .put("reserved", reserved)
        .put("hdop", hdop)
        .put("vdop", vdop)
}

private class MavlinkState(private val onGps: (Gps, JSONObject, Boolean) -> Unit) {
    private companion object {
        const val ONLINE_TIMEOUT_MS = 2000L
        val TELEMETRY_IDS = setOf(1, 2, 24, 30, 33, 49, 74, 147, 242)
    }

    private var rssiPct: Double? = null
    private var heartbeatAt = 0L
    private var armed: Boolean? = null
    private var flightMode: String? = null
    private var device: String? = null
    private var gps: Gps? = null
    private var gpsLast: Gps? = null
    private var gpsExt: JSONObject? = null
    private var gpsTime: String? = null
    private var attitude: Attitude? = null
    private var baro: Baro? = null
    private var vario: Double? = null
    private var batteryJson: JSONObject? = null
    private val frames = LinkedHashMap<Int, Int>()
    private val unknown = LinkedHashMap<Int, String>()
    private var linkAt = 0L
    private var telemetryAt = 0L
    private var total = 0L
    private val times = ArrayDeque<Long>()
    private var messages = 0L
    private val messageTimes = ArrayDeque<Long>()

    fun reset() {
        rssiPct = null
        heartbeatAt = 0L
        armed = null
        flightMode = null
        device = null
        gps = null
        gpsLast = null
        gpsExt = null
        gpsTime = null
        attitude = null
        baro = null
        vario = null
        batteryJson = null
        frames.clear()
        unknown.clear()
        linkAt = 0L
        telemetryAt = 0L
        total = 0
        times.clear()
        messages = 0
        messageTimes.clear()
    }

    fun resetCounters() {
        total = 0
        times.clear()
        messages = 0
        messageTimes.clear()
        linkAt = 0
        telemetryAt = 0
        frames.clear()
        unknown.clear()
    }

    fun totalPackets(): Long = total
    fun lastPacketAgeSeconds(): Double? =
        if (total == 0L) null else (System.currentTimeMillis() - times.last()) / 1000.0
    fun recentPps(windowSeconds: Double): Int {
        if (windowSeconds <= 0.0) return 0
        val cutoff = System.currentTimeMillis() - (windowSeconds * 1000).toLong()
        var count = 0
        for (t in times) if (t >= cutoff) count++
        return (count / windowSeconds).toInt()
    }
    fun telemetryAgeSeconds(): Double? =
        if (telemetryAt == 0L) null else (SystemClock.elapsedRealtime() - telemetryAt) / 1000.0
    fun linkUp(): Boolean =
        heartbeatAt != 0L && (SystemClock.elapsedRealtime() - heartbeatAt) / 1000.0 <= 2.0
    fun online(): Boolean {
        if (linkUp()) return true
        val age = telemetryAgeSeconds() ?: return false
        return age <= 2.0
    }
    fun onlineAgeSeconds(): Double? {
        val now = SystemClock.elapsedRealtime()
        val activity = maxOf(if (linkUp()) heartbeatAt else 0L, telemetryAt)
        return if (activity == 0L) null else (now - activity) / 1000.0
    }

    fun ingest(data: ByteArray, length: Int) {
        val now = System.currentTimeMillis()
        total++
        times.addLast(now)
        while (times.size > 4000) times.removeFirst()
        val nowMono = SystemClock.elapsedRealtime()
        for (frame in MavlinkProtocol.iterFrames(data, length)) {
            if (frame.crcOk != true) continue
            messages++
            messageTimes.addLast(now)
            while (messageTimes.size > 8000) messageTimes.removeFirst()
            frames[frame.msgid] = (frames[frame.msgid] ?: 0) + 1
            if (frame.msgid in TELEMETRY_IDS) telemetryAt = nowMono
            val decoded = MavlinkProtocol.decode(frame)
            when (frame.msgid) {
                0 -> {
                    linkAt = nowMono
                    heartbeatAt = nowMono
                    armed = decoded["armed"] as? Boolean
                    val mode = (decoded["custom_mode"] as? Long)?.toInt() ?: 0
                    flightMode = MavlinkProtocol.bfFlightModes[mode] ?: mode.toString()
                    val autopilot = (decoded["autopilot"] as? Int) ?: 0
                    device = if (autopilot == 22) "Betaflight" else "MAVLink"
                }
                24 -> {
                    val fixType = (decoded["fix_type"] as? Int) ?: 0
                    val sats = (decoded["satellites_visible"] as? Int) ?: 0
                    val fix3d = fixType >= 3
                    val fixPos = fixType >= 2 && sats >= 3
                    val was3d = gps?.fixType == 3
                    val newGps = Gps(
                        lat = ((decoded["lat"] as? Int) ?: 0) / 1e7,
                        lon = ((decoded["lon"] as? Int) ?: 0) / 1e7,
                        speed = ((decoded["vel"] as? Int) ?: 0) * 0.036,
                        heading = ((decoded["cog"] as? Int) ?: 0) / 100.0,
                        alt = ((decoded["alt"] as? Int) ?: 0) / 1000.0,
                        sats = sats,
                        fixType = fixType.coerceIn(0, 3),
                        fixTypeComputed = false,
                    )
                    gps = newGps
                    if (fixPos) gpsLast = newGps
                    val hdop = ((decoded["eph"] as? Int) ?: 0) / 100.0
                    val vdop = ((decoded["epv"] as? Int) ?: 0) / 100.0
                    gpsExt = JSONObject()
                        .put("fix_type", fixType)
                        .put("vn", (gpsExt?.optDouble("vn", 0.0) ?: 0.0))
                        .put("ve", (gpsExt?.optDouble("ve", 0.0) ?: 0.0))
                        .put("vv", (gpsExt?.optDouble("vv", 0.0) ?: 0.0))
                        .put("speed_acc", ((decoded["vel_acc"] as? Long) ?: 0L) / 1000.0)
                        .put("track_acc", JSONObject.NULL)
                        .put("alt_ellipsoid", ((decoded["alt_ellipsoid"] as? Int) ?: 0) / 1000.0)
                        .put("h_acc", ((decoded["h_acc"] as? Long) ?: 0L) / 1000.0)
                        .put("v_acc", ((decoded["v_acc"] as? Long) ?: 0L) / 1000.0)
                        .put("reserved", JSONObject.NULL)
                        .put("hdop", hdop)
                        .put("vdop", vdop)
                    if (fix3d) {
                        val extra = JSONObject().put("mavlink", JSONObject()
                            .put("fix_type", fixType)
                            .put("eph", decoded["eph"] ?: JSONObject.NULL)
                            .put("epv", decoded["epv"] ?: JSONObject.NULL)
                            .put("vel", decoded["vel"] ?: JSONObject.NULL)
                            .put("cog", decoded["cog"] ?: JSONObject.NULL)
                            .put("h_acc", decoded["h_acc"] ?: JSONObject.NULL)
                            .put("v_acc", decoded["v_acc"] ?: JSONObject.NULL)
                            .put("vel_acc", decoded["vel_acc"] ?: JSONObject.NULL))
                        onGps(newGps, extra, !was3d)
                    }
                }
                33 -> {
                    val current = gps
                    val ext = gpsExt ?: JSONObject()
                    ext.put("vn", ((decoded["vx"] as? Int) ?: 0) / 100.0)
                    ext.put("ve", ((decoded["vy"] as? Int) ?: 0) / 100.0)
                    ext.put("vv", -((decoded["vz"] as? Int) ?: 0) / 100.0)
                    gpsExt = ext
                    vario = -((decoded["vz"] as? Int) ?: 0) / 100.0
                }
                30 -> {
                    val pitch = -Math.toDegrees((decoded["pitch"] as? Float)?.toDouble() ?: 0.0)
                    val roll = Math.toDegrees((decoded["roll"] as? Float)?.toDouble() ?: 0.0)
                    val yaw = Math.toDegrees((decoded["yaw"] as? Float)?.toDouble() ?: 0.0)
                    attitude = Attitude(pitch, roll, yaw)
                }
                1 -> {
                    val voltage = ((decoded["voltage_battery"] as? Int) ?: 0) / 1000.0
                    val current = (decoded["current_battery"] as? Int) ?: -1
                    val remaining = (decoded["battery_remaining"] as? Int) ?: -1
                    batteryJson = JSONObject()
                        .put("voltage", voltage)
                        .put("current", if (current >= 0) current / 100.0 else JSONObject.NULL)
                        .put("capacity", batteryJson?.opt("capacity") ?: JSONObject.NULL)
                        .put("remaining", if (remaining >= 0) remaining else JSONObject.NULL)
                }
                147 -> {
                    val b = batteryJson ?: JSONObject()
                    val current = (decoded["current_battery"] as? Int) ?: -1
                    val remaining = (decoded["battery_remaining"] as? Int) ?: -1
                    val consumed = (decoded["current_consumed"] as? Int) ?: -1
                    b.put("voltage", b.opt("voltage") ?: JSONObject.NULL)
                    b.put("current", if (current >= 0) current / 100.0 else b.opt("current") ?: JSONObject.NULL)
                    b.put("capacity", if (consumed >= 0) consumed else b.opt("capacity") ?: JSONObject.NULL)
                    b.put("remaining", if (remaining >= 0) remaining else b.opt("remaining") ?: JSONObject.NULL)
                    batteryJson = b
                }
                74 -> baro = Baro(
                    alt = (decoded["alt"] as? Float)?.toDouble() ?: 0.0,
                    vario = vario ?: 0.0,
                )
                2 -> {
                    val unixUsec = (decoded["time_unix_usec"] as? Long) ?: 0L
                    if (unixUsec > 0) {
                        val fmt = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
                        fmt.timeZone = TimeZone.getTimeZone("UTC")
                        gpsTime = fmt.format(Date(unixUsec / 1000L))
                    }
                }
                35 -> {
                    val rssi = (decoded["rssi"] as? Int) ?: 0
                    rssiPct = 100.0 * minOf(rssi, 254) / 254.0
                }
                else -> if (frame.crcOk == true && frame.msgid !in MavlinkProtocol.names) {
                    unknown[frame.msgid] = frame.payload.joinToString("") { "%02x".format(it) }
                }
            }
        }
    }

    fun snapshotJson(record: JSONObject, session: JSONObject): JSONObject {
        val now = System.currentTimeMillis()
        var pps = 0
        for (t in times) if (now - t <= 1000L) pps++
        var messagesPps = 0
        for (t in messageTimes) if (now - t <= 1000L) messagesPps++
        val age: Any = if (times.isEmpty()) JSONObject.NULL else (now - times.last()) / 1000.0
        val linkUp = linkUp()
        val telemetryAge = telemetryAgeSeconds()
        val online = linkUp || (telemetryAge != null && telemetryAge <= 2.0)
        val linkJson = if (rssiPct == null) JSONObject.NULL else JSONObject()
            .put("rssi_pct", round(rssiPct!! * 10.0) / 10.0)
            .put("lq", JSONObject.NULL)
            .put("lq_d", JSONObject.NULL)
            .put("snr", JSONObject.NULL)
            .put("snr_d", JSONObject.NULL)
            .put("rssi1", JSONObject.NULL)
            .put("rssi2", JSONObject.NULL)
            .put("rssi_d", JSONObject.NULL)
            .put("active_ant", JSONObject.NULL)
            .put("rf_mode", JSONObject.NULL)
            .put("tx_power", JSONObject.NULL)
        val framesJson = JSONObject()
        for ((k, v) in frames) framesJson.put(k.toString(), v)
        val unknownJson = JSONObject()
        for ((k, v) in unknown) unknownJson.put(k.toString(), v)
        val stats = JSONObject()
            .put("total", total)
            .put("pps", pps)
            .put("age", age)
            .put("online", online)
            .put("link_up", linkUp)
            .put("telemetry_age", telemetryAge ?: JSONObject.NULL)
            .put("link_age", if (linkAt == 0L) JSONObject.NULL else (SystemClock.elapsedRealtime() - linkAt) / 1000.0)
            .put("messages", messages)
            .put("messages_pps", messagesPps)
        return JSONObject()
            .put("protocol", "mavlink")
            .put("session", session)
            .put("capabilities", JSONObject()
                .put("link_stats", false)
                .put("rssi_pct", true)
                .put("gps_ext", true)
                .put("gps_time", true)
                .put("device", false))
            .put("link", linkJson)
            .put("battery", batteryJson ?: JSONObject.NULL)
            .put("gps", gps?.toJson() ?: JSONObject.NULL)
            .put("gps_last", gpsLast?.toJson() ?: JSONObject.NULL)
            .put("gps_ext", gpsExt ?: JSONObject.NULL)
            .put("gps_time", gpsTime ?: JSONObject.NULL)
            .put("attitude", attitude?.toJson() ?: JSONObject.NULL)
            .put("baro", baro?.toJson() ?: JSONObject.NULL)
            .put("vario", vario ?: JSONObject.NULL)
            .put("flight_mode", flightMode ?: JSONObject.NULL)
            .put("device", device ?: JSONObject.NULL)
            .put("armed", armed ?: JSONObject.NULL)
            .put("frames", framesJson)
            .put("unknown", unknownJson)
            .put("record", record)
            .put("stats", stats)
    }
}

data class TrackPoint(
    val t: Double,
    val lat: Double,
    val lon: Double,
    val alt: Double,
    val speed: Double,
    val heading: Double,
    val sats: Int,
    val fixType: Int?,
    val fixTypeComputed: Boolean,
    val telemetry: JSONObject,
    val protocol: String? = null,
    val sessionId: String? = null,
    val data: JSONObject? = null,
) {
    fun toJson() = JSONObject()
        .put("t", t)
        .put("lat", lat)
        .put("lon", lon)
        .put("alt", alt)
        .put("speed", speed)
        .put("heading", heading)
        .put("sats", sats)
        .put("fix_type", fixType ?: JSONObject.NULL)
        .put("fix_type_computed", fixTypeComputed)
        .put("protocol", protocol ?: JSONObject.NULL)
        .put("session_id", sessionId ?: JSONObject.NULL)
        .put("telemetry", telemetry)
        .put("data", data ?: JSONObject.NULL)
}

class TelemetryState(initialStore: TrackStore) {

    private var store: TrackStore = initialStore

    fun setTrackStore(newStore: TrackStore) = synchronized(lock) {
        store = newStore
    }

    fun currentStore(): TrackStore = synchronized(lock) { store }

    fun tracksLocation(): String = synchronized(lock) { store.location() }

    fun isRecording(): Boolean = synchronized(lock) { recording.active }

    fun totalPackets(): Long = synchronized(lock) {
        if (protocol == "mavlink") mav.totalPackets() else total
    }

    fun lastPacketAgeSeconds(): Double? = synchronized(lock) {
        if (protocol == "mavlink") mav.lastPacketAgeSeconds()
        else if (last == 0L) null else (System.currentTimeMillis() - last) / 1000.0
    }

    fun telemetryAgeSeconds(): Double? = synchronized(lock) {
        if (protocol == "mavlink") mav.telemetryAgeSeconds()
        else if (telemetryAt == 0L) null else (SystemClock.elapsedRealtime() - telemetryAt) / 1000.0
    }

    fun isOnline(): Boolean = synchronized(lock) {
        if (protocol == "mavlink") mav.online() else onlineLocked()
    }

    fun onlineAgeSeconds(): Double? = synchronized(lock) {
        if (protocol == "mavlink") return@synchronized mav.onlineAgeSeconds()
        val now = SystemClock.elapsedRealtime()
        val linkActivity = if (linkUpLocked()) linkAt else 0L
        val lastActivity = maxOf(linkActivity, telemetryAt)
        if (lastActivity == 0L) null else (now - lastActivity) / 1000.0
    }

    fun recordingTelemetryIdleSeconds(): Double? = synchronized(lock) {
        if (!recording.active) null else {
            val now = SystemClock.elapsedRealtime()
            val base = if (protocol == "mavlink") {
                val age = mav.telemetryAgeSeconds()
                if (age == null) recording.startMono
                else maxOf(recording.startMono, now - (age * 1000.0).toLong())
            } else {
                maxOf(recording.startMono, telemetryAt)
            }
            (now - base) / 1000.0
        }
    }

    private fun linkUpLocked(): Boolean {
        if (protocol == "mavlink") return mav.linkUp()
        if (linkAt == 0L) return false
        val age = (SystemClock.elapsedRealtime() - linkAt) / 1000.0
        val stats = link ?: return false
        return age <= ONLINE_TIMEOUT_SEC && stats.lq > 0 && stats.lqD > 0
    }

    private fun onlineLocked(): Boolean {
        if (protocol == "mavlink") return mav.online()
        if (linkUpLocked()) return true
        if (telemetryAt == 0L) return false
        val age = (SystemClock.elapsedRealtime() - telemetryAt) / 1000.0
        return age <= ONLINE_TIMEOUT_SEC
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

    fun resetCounters() = synchronized(lock) {
        total = 0
        times.clear()
        last = 0
        linkAt = 0
        telemetryAt = 0
        frames.clear()
        unknown.clear()
        mav.resetCounters()
    }

    fun resetTelemetry() = synchronized(lock) {
        resetCrsfData()
        mav.reset()
        protocol = "crsf"
        sessionId = null
        sessionStartedAt = null
        sessionSource = null
        sessionLastValid = 0L
        candidateProtocol = null
        candidateCount = 0
        candidateSince = 0L
    }

    companion object {
        private val TRACK_ID = Regex("[A-Za-z0-9_-]{1,80}")
        private const val MAX_TIMES = 4000
        private const val GPS_EXT_TTL_MS = 5000L
        private const val ONLINE_TIMEOUT_SEC = 2.0
        private val RAD_TO_DEG = 180.0 / Math.PI / 10000.0
        private val TELEMETRY_TYPES = setOf(0x02, 0x03, 0x06, 0x07, 0x08, 0x09, 0x1E, 0x21, 0x29)
    }

    private class Recording(
        var active: Boolean = false,
        var id: String? = null,
        var startMono: Long = 0L,
        var startedAt: String? = null,
        var protocol: String? = null,
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
    private var linkAt = 0L
    private var telemetryAt = 0L

    private var protocol = "crsf"
    private var sessionId: String? = null
    private var sessionStartedAt: String? = null
    private var sessionSource: String? = null
    private var sessionLastValid = 0L
    private var candidateProtocol: String? = null
    private var candidateCount = 0
    private var candidateSince = 0L

    private val recording = Recording()
    private val mav = MavlinkState { gpsData, extra, new3d ->
        if (new3d && autoRecordOn3d && !recording.active) startRecording("mavlink")
        if (recording.active && recording.protocol == "mavlink") {
            val tel = JSONObject()
                .put("gps", gpsData.toJson())
                .put("mavlink", extra.optJSONObject("mavlink") ?: JSONObject.NULL)
            recording.points.add(
                TrackPoint(
                    t = (SystemClock.elapsedRealtime() - recording.startMono).coerceAtLeast(0L) / 1000.0,
                    lat = gpsData.lat, lon = gpsData.lon, alt = gpsData.alt,
                    speed = gpsData.speed, heading = gpsData.heading,
                    sats = gpsData.sats, fixType = gpsData.fixType,
                    fixTypeComputed = false, telemetry = tel,
                    protocol = "mavlink", sessionId = sessionId,
                    data = extra,
                ),
            )
        }
    }
    @Volatile
    private var autoRecordOn3d = false

    @Volatile
    private var keepTracks: Int? = null

    fun setAutoRecordOn3d(enabled: Boolean) = synchronized(lock) {
        autoRecordOn3d = enabled
    }

    fun setKeepTracks(count: Int?) = synchronized(lock) {
        keepTracks = count
    }

    private fun hasCrsfFrame(data: ByteArray, length: Int): Boolean {
        var i = 0
        while (i < length - 2) {
            val address = u(data, i)
            if (address == 0xC8 || address == 0xEA || address == 0xEE) {
                val frameLength = u(data, i + 1)
                if (frameLength in 2..62 && i + 2 + frameLength <= length) {
                    val crcIndex = i + 2 + frameLength - 1
                    if (crc8(data, i + 2, crcIndex) == u(data, crcIndex)) return true
                }
            }
            i += 1
        }
        return false
    }

    private fun detectProtocol(data: ByteArray, length: Int): String? {
        if (length <= 0) return null
        val b0 = data[0].toInt() and 0xFF
        if (b0 == 0xC8 || b0 == 0xEA || b0 == 0xEE || (length >= 3 && b0 == 0x24 &&
                (data[1].toInt() and 0xFF) == 0x58 && (data[2].toInt() and 0xFF) == 0x3C)) {
            return if (hasCrsfFrame(data, length)) "crsf" else null
        }
        if (b0 == 0xFD || b0 == 0xFE) {
            return if (MavlinkProtocol.firstValidFrame(data, length) != null) "mavlink" else null
        }
        return null
    }

    private fun newSessionId(): String =
        "session_" + SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())

    private fun startSession(proto: String, now: Long) {
        protocol = proto
        sessionId = newSessionId()
        sessionStartedAt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(Date())
        sessionSource = null
        sessionLastValid = now
        candidateProtocol = null
        candidateCount = 0
        candidateSince = 0L
    }

    private fun resetCrsfData() {
        link = null
        battery = null
        gps = null
        gpsLast = null
        gpsExt = null
        gpsExtAt = 0L
        gpsTime = null
        attitude = null
        baro = null
        vario = null
        flightMode = null
        device = null
        frames.clear()
        unknown.clear()
        total = 0
        times.clear()
        last = 0
        linkAt = 0
        telemetryAt = 0
    }

    private fun switchProtocol(proto: String, now: Long) {
        if (recording.active) stopRecording()
        if (proto == "crsf") resetCrsfData() else mav.reset()
        startSession(proto, now)
    }

    private fun routeProtocol(proto: String): Boolean {
        val now = SystemClock.elapsedRealtime()
        if (sessionId == null) {
            startSession(proto, now)
            return true
        }
        if (proto == protocol) {
            sessionLastValid = now
            candidateProtocol = null
            candidateCount = 0
            return true
        }
        val age = (now - sessionLastValid) / 1000.0
        if (age >= ONLINE_TIMEOUT_SEC) {
            switchProtocol(proto, now)
            return true
        }
        if (age < 0.5) return false
        if (candidateProtocol != proto) {
            candidateProtocol = proto
            candidateCount = 1
            candidateSince = now
        } else {
            candidateCount += 1
        }
        if (candidateCount >= 3 || now - candidateSince >= 300L) {
            switchProtocol(proto, now)
            return true
        }
        return false
    }

    fun onDatagram(data: ByteArray, length: Int) {
        val proto = detectProtocol(data, length) ?: return
        synchronized(lock) {
            if (!routeProtocol(proto)) return
            if (proto == "mavlink") {
                mav.ingest(data, length)
                return
            }
            val now = System.currentTimeMillis()
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
        val nowMono = SystemClock.elapsedRealtime()
        when (type) {
            0x14 -> linkAt = nowMono
            in TELEMETRY_TYPES -> telemetryAt = nowMono
        }
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
                val ext = gpsExt?.takeIf { nowMono - gpsExtAt <= GPS_EXT_TTL_MS }
                if (ext == null) gpsExt = null
                // Betaflight sends 1 = No Fix, 2 = 2D, 3 = 3D in 0x06.
                // iNav/ArduPilot do not send 0x06 at all: derive a conservative
                // fallback from satellites (>=4 -> 3D, >=3 -> 2D).
                val computedFixType = when {
                    sats >= 4 -> 3
                    sats >= 3 -> 2
                    else -> 0
                }
                val fixType = ext?.fixType ?: computedFixType
                val fixTypeComputed = ext == null
                val was3d = gps?.fixType == 3
                val fixData = Gps(
                    lat = lat / 1e7,
                    lon = lon / 1e7,
                    speed = speed / 10.0,
                    heading = heading / 100.0,
                    alt = (alt - 1000).toDouble(),
                    sats = sats,
                    fixType = fixType,
                    fixTypeComputed = fixTypeComputed,
                )
                gps = fixData
                if (fixType == 3) gpsLast = fixData
                if (autoRecordOn3d && fixType == 3 && !was3d && !recording.active) {
                    startRecording("crsf")
                }
                if (recording.active) {
                    recording.points.add(
                        TrackPoint(
                            t = (nowMono - recording.startMono).coerceAtLeast(0L) / 1000.0,
                            lat = fixData.lat,
                            lon = fixData.lon,
                            alt = fixData.alt,
                            speed = fixData.speed,
                            heading = fixData.heading,
                            sats = fixData.sats,
                            fixType = fixType,
                            fixTypeComputed = fixTypeComputed,
                            telemetry = buildTrackTelemetry(fixData),
                            protocol = "crsf",
                            sessionId = sessionId,
                        ),
                    )
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
                    speedAcc = s16(data, from + 7) / 100.0,
                    // Betaflight: heading accuracy, tenths of a degree.
                    trackAcc = s16(data, from + 9) / 10.0,
                    // Betaflight: height above the GPS ellipsoid, metres.
                    altEllipsoid = s16(data, from + 11).toDouble(),
                    hAcc = s16(data, from + 13) / 100.0,
                    vAcc = s16(data, from + 15) / 100.0,
                    reserved = u(data, from + 17),
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

    private fun buildRecordJson(): JSONObject = JSONObject()
        .put("active", recording.active)
        .put("id", recording.id ?: JSONObject.NULL)
        .put("started_at", recording.startedAt ?: JSONObject.NULL)
        .put("protocol", recording.protocol ?: JSONObject.NULL)
        .put(
            "duration",
            if (recording.active) (SystemClock.elapsedRealtime() - recording.startMono) / 1000.0 else 0.0,
        )
        .put("point_count", recording.points.size)

    private fun buildSessionJson(): JSONObject = JSONObject()
        .put("id", sessionId ?: JSONObject.NULL)
        .put("protocol", if (sessionId == null) JSONObject.NULL else protocol)
        .put("started_at", sessionStartedAt ?: JSONObject.NULL)
        .put("source", sessionSource ?: JSONObject.NULL)

    fun snapshotJson(): String = synchronized(lock) {
        val record = buildRecordJson()
        val session = buildSessionJson()
        if (protocol == "mavlink") {
            mav.snapshotJson(record, session).toString()
        } else {
            buildSnapshot(record, session).toString()
        }
    }

    private fun buildTrackTelemetry(gpsData: Gps): JSONObject = JSONObject()
        .put("gps", gpsData.toJson())
        .put("gps_ext", gpsExt?.toJson() ?: JSONObject.NULL)
        .put("link", link?.toJson() ?: JSONObject.NULL)
        .put("battery", battery?.toJson() ?: JSONObject.NULL)
        .put("attitude", attitude?.toJson() ?: JSONObject.NULL)
        .put("baro", baro?.toJson() ?: JSONObject.NULL)
        .put("vario", vario ?: JSONObject.NULL)
        .put("flight_mode", flightMode ?: JSONObject.NULL)
        .put("device", device ?: JSONObject.NULL)
        .put("gps_time", gpsTime ?: JSONObject.NULL)

    private fun buildSnapshot(record: JSONObject, session: JSONObject): JSONObject {
        val now = System.currentTimeMillis()
        var pps = 0
        for (t in times) {
            if (now - t <= 1000L) pps += 1
        }
        val age: Any = if (last != 0L) (now - last) / 1000.0 else JSONObject.NULL

        val framesJson = JSONObject()
        for ((key, value) in frames) framesJson.put(key.toString(), value)
        val unknownJson = JSONObject()
        for ((key, value) in unknown) unknownJson.put(key.toString(), value)

        return JSONObject()
            .put("protocol", "crsf")
            .put("session", session)
            .put("capabilities", JSONObject()
                .put("link_stats", true)
                .put("rssi_pct", false)
                .put("gps_ext", true)
                .put("gps_time", true)
                .put("device", true))
            .put("armed", JSONObject.NULL)
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
            .put(
                "stats",
                JSONObject()
                    .put("total", total)
                    .put("pps", pps)
                    .put("age", age)
                    .put("online", onlineLocked())
                    .put("link_up", linkUpLocked())
                    .put(
                        "telemetry_age",
                        if (telemetryAt == 0L) {
                            JSONObject.NULL
                        } else {
                            (SystemClock.elapsedRealtime() - telemetryAt) / 1000.0
                        },
                    )
                    .put(
                        "link_age",
                        if (linkAt == 0L) {
                            JSONObject.NULL
                        } else {
                            (SystemClock.elapsedRealtime() - linkAt) / 1000.0
                        },
                    ),
            )
    }

    fun startRecording(protocolName: String? = null): Pair<Boolean, String> = synchronized(lock) {
        if (recording.active) {
            return@synchronized Pair(false, "already recording")
        }
        recording.active = true
        recording.id = nextTrackId()
        recording.startMono = SystemClock.elapsedRealtime()
        recording.startedAt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(Date())
        recording.protocol = protocolName ?: if (sessionId == null) "crsf" else protocol
        recording.points.clear()
        Pair(true, "")
    }

    fun stopRecording(): Pair<JSONObject?, String> {
        var points: List<TrackPoint>? = null
        var trackId: String? = null
        var startedAt: String? = null
        var targetStore: TrackStore? = null
        var trackProtocol: String? = null
        synchronized(lock) {
            if (!recording.active) return Pair(null, "not recording")
            points = ArrayList(recording.points)
            trackId = recording.id
            startedAt = recording.startedAt
            trackProtocol = recording.protocol
            targetStore = store
            recording.active = false
            recording.id = null
            recording.startedAt = null
            recording.startMono = 0L
            recording.protocol = null
            recording.points.clear()
        }
        val savedPoints = points ?: return Pair(null, "not recording")
        val savedId = trackId ?: return Pair(null, "not recording")
        if (savedPoints.isEmpty()) return Pair(null, "no GPS points recorded")

        val duration = round(savedPoints.last().t * 1000.0) / 1000.0
        val protocols = savedPoints.mapNotNull { it.protocol }.distinct().sorted()
        val meta = JSONObject()
            .put("version", 2)
            .put("id", savedId)
            .put("started_at", startedAt ?: JSONObject.NULL)
            .put("duration", duration)
            .put("point_count", savedPoints.size)
            .put("protocols", JSONArray(protocols.ifEmpty { listOfNotNull(trackProtocol) }))
        val pointsJson = JSONArray()
        for (point in savedPoints) pointsJson.put(point.toJson())
        meta.put("points", pointsJson)

        val storeToUse = targetStore ?: return Pair(null, "not recording")
        if (!storeToUse.write(savedId, meta.toString())) {
            return Pair(null, "failed to save track")
        }
        keepTracks?.let { limit -> trimTracks(storeToUse, savedId, limit) }
        return Pair(meta.toJsonMeta(), "")
    }

    private fun trimTracks(store: TrackStore, savedId: String, limit: Int) {
        val ids = store.listIds()
        if (ids.size <= limit) return
        var total = ids.size
        for (id in ids.filter { it != savedId }.sorted()) {
            if (total <= limit) break
            if (store.delete(id)) total -= 1
        }
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
