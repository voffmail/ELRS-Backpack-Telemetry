package com.elrs.backpack

import java.nio.ByteBuffer
import java.nio.ByteOrder

data class MavFrame(
    val version: Int,
    val seq: Int,
    val sysid: Int,
    val compid: Int,
    val msgid: Int,
    val payload: ByteArray,
    val crcOk: Boolean?,
)

object MavlinkProtocol {
    const val MAGIC_V1 = 0xFE
    const val MAGIC_V2 = 0xFD

    private data class Info(val name: String, val crcExtra: Int, val len: Int, val minLen: Int)

    private val info = mapOf(
        0 to Info("HEARTBEAT", 50, 9, 9),
        1 to Info("SYS_STATUS", 124, 43, 31),
        2 to Info("SYSTEM_TIME", 137, 12, 12),
        4 to Info("PING", 237, 14, 14),
        24 to Info("GPS_RAW_INT", 24, 52, 30),
        30 to Info("ATTITUDE", 39, 28, 28),
        33 to Info("GLOBAL_POSITION_INT", 104, 28, 28),
        35 to Info("RC_CHANNELS_RAW", 244, 22, 22),
        49 to Info("GPS_GLOBAL_ORIGIN", 39, 20, 12),
        74 to Info("VFR_HUD", 20, 20, 20),
        76 to Info("COMMAND_LONG", 152, 33, 33),
        77 to Info("COMMAND_ACK", 143, 10, 3),
        109 to Info("RADIO_STATUS", 185, 9, 9),
        111 to Info("TIMESYNC", 34, 18, 16),
        147 to Info("BATTERY_STATUS", 154, 54, 36),
        242 to Info("HOME_POSITION", 104, 60, 52),
        253 to Info("STATUSTEXT", 83, 54, 51),
        300 to Info("PROTOCOL_VERSION", 217, 22, 22),
        435 to Info("AVAILABLE_MODES", 134, 47, 46),
    )

    val names: Map<Int, String> = info.mapValues { it.value.name }
    private val crcExtra: Map<Int, Int> = info.mapValues { it.value.crcExtra }

    val bfFlightModes = mapOf(
        0 to "Acro", 1 to "Angle", 2 to "Horizon", 3 to "Alt Hold",
        4 to "Pos Hold", 5 to "Autopilot", 6 to "RTL", 7 to "Failsafe",
    )

    fun crc16(data: ByteArray, from: Int = 0, until: Int = data.size): Int {
        var crc = 0xFFFF
        for (i in from until until) {
            val b = data[i].toInt() and 0xFF
            var tmp = (b xor (crc and 0xFF)) and 0xFF
            tmp = (tmp xor (tmp shl 4)) and 0xFF
            crc = ((crc ushr 8) xor (tmp shl 8) xor (tmp shl 3) xor (tmp ushr 4)) and 0xFFFF
        }
        return crc
    }

    fun iterFrames(data: ByteArray, length: Int = data.size): List<MavFrame> {
        val out = ArrayList<MavFrame>()
        var i = 0
        while (i < length) {
            val magic = data[i].toInt() and 0xFF
            val headerLen: Int
            val payloadLen: Int
            val seq: Int
            val sysid: Int
            val compid: Int
            val msgid: Int
            val payloadStart: Int
            val crcStart: Int
            val total: Int
            val version: Int
            if (magic == MAGIC_V1) {
                if (i + 6 > length) break
                payloadLen = data[i + 1].toInt() and 0xFF
                seq = data[i + 2].toInt() and 0xFF
                sysid = data[i + 3].toInt() and 0xFF
                compid = data[i + 4].toInt() and 0xFF
                msgid = data[i + 5].toInt() and 0xFF
                payloadStart = i + 6
                crcStart = payloadStart + payloadLen
                total = 6 + payloadLen + 2
                version = 1
                headerLen = 6
            } else if (magic == MAGIC_V2) {
                if (i + 10 > length) break
                payloadLen = data[i + 1].toInt() and 0xFF
                val incompat = data[i + 2].toInt() and 0xFF
                seq = data[i + 4].toInt() and 0xFF
                sysid = data[i + 5].toInt() and 0xFF
                compid = data[i + 6].toInt() and 0xFF
                msgid = (data[i + 7].toInt() and 0xFF) or
                    ((data[i + 8].toInt() and 0xFF) shl 8) or
                    ((data[i + 9].toInt() and 0xFF) shl 16)
                payloadStart = i + 10
                crcStart = payloadStart + payloadLen
                total = 10 + payloadLen + 2 + if ((incompat and 0x01) != 0) 13 else 0
                version = 2
                headerLen = 10
            } else {
                i++
                continue
            }
            if (i + total > length) break
            val payload = data.copyOfRange(payloadStart, crcStart)
            val crcRead = (data[crcStart].toInt() and 0xFF) or
                ((data[crcStart + 1].toInt() and 0xFF) shl 8)
            val extra = crcExtra[msgid]
            val ok = if (extra == null) null else {
                var crc = 0xFFFF
                for (j in i + 1 until crcStart) {
                    val b = data[j].toInt() and 0xFF
                    var tmp = (b xor (crc and 0xFF)) and 0xFF
                    tmp = (tmp xor (tmp shl 4)) and 0xFF
                    crc = ((crc ushr 8) xor (tmp shl 8) xor (tmp shl 3) xor (tmp ushr 4)) and 0xFFFF
                }
                var tmp = (extra xor (crc and 0xFF)) and 0xFF
                tmp = (tmp xor (tmp shl 4)) and 0xFF
                crc = ((crc ushr 8) xor (tmp shl 8) xor (tmp shl 3) xor (tmp ushr 4)) and 0xFFFF
                crc == crcRead
            }
            out.add(MavFrame(version, seq, sysid, compid, msgid, payload, ok))
            i += if (ok == false) 1 else total
            @Suppress("UNUSED_VARIABLE")
            val unusedHeader = headerLen
        }
        return out
    }

    fun firstValidFrame(data: ByteArray, length: Int = data.size): MavFrame? =
        iterFrames(data, length).firstOrNull { it.crcOk == true }

    fun decode(frame: MavFrame): Map<String, Any?> {
        val p = frame.payload
        val out = LinkedHashMap<String, Any?>()
        out["msgid"] = frame.msgid
        out["name"] = names[frame.msgid] ?: "MSG_${frame.msgid}"
        try {
            when (frame.msgid) {
                0 -> if (p.size >= 9) {
                    out["custom_mode"] = u32(p, 0)
                    out["type"] = u8(p, 4)
                    out["autopilot"] = u8(p, 5)
                    out["base_mode"] = u8(p, 6)
                    out["system_status"] = u8(p, 7)
                    out["armed"] = (u8(p, 6) and 0x80) != 0
                }
                1 -> if (p.size >= 31) {
                    out["voltage_battery"] = u16(p, 14)
                    out["current_battery"] = i16(p, 16)
                    out["battery_remaining"] = i8(p, 30)
                }
                2 -> if (p.size >= 12) {
                    out["time_unix_usec"] = u64(p, 0)
                    out["time_boot_ms"] = u32(p, 8)
                }
                24 -> if (p.size >= 30) {
                    out["time_usec"] = u64(p, 0)
                    out["lat"] = i32(p, 8)
                    out["lon"] = i32(p, 12)
                    out["alt"] = i32(p, 16)
                    out["eph"] = u16(p, 20)
                    out["epv"] = u16(p, 22)
                    out["vel"] = u16(p, 24)
                    out["cog"] = u16(p, 26)
                    out["fix_type"] = u8(p, 28)
                    out["satellites_visible"] = u8(p, 29)
                    if (p.size >= 46) {
                        out["alt_ellipsoid"] = i32(p, 30)
                        out["h_acc"] = u32(p, 34)
                        out["v_acc"] = u32(p, 38)
                        out["vel_acc"] = u32(p, 42)
                    }
                }
                30 -> if (p.size >= 28) {
                    out["time_boot_ms"] = u32(p, 0)
                    out["roll"] = f32(p, 4)
                    out["pitch"] = f32(p, 8)
                    out["yaw"] = f32(p, 12)
                }
                33 -> if (p.size >= 28) {
                    out["time_boot_ms"] = u32(p, 0)
                    out["lat"] = i32(p, 4)
                    out["lon"] = i32(p, 8)
                    out["alt"] = i32(p, 12)
                    out["relative_alt"] = i32(p, 16)
                    out["vx"] = i16(p, 20)
                    out["vy"] = i16(p, 22)
                    out["vz"] = i16(p, 24)
                    out["hdg"] = u16(p, 26)
                }
                35 -> if (p.size >= 22) {
                    out["time_boot_ms"] = u32(p, 0)
                    out["chan1_raw"] = u16(p, 4)
                    out["chan2_raw"] = u16(p, 6)
                    out["chan3_raw"] = u16(p, 8)
                    out["chan4_raw"] = u16(p, 10)
                    out["chan5_raw"] = u16(p, 12)
                    out["chan6_raw"] = u16(p, 14)
                    out["chan7_raw"] = u16(p, 16)
                    out["chan8_raw"] = u16(p, 18)
                    out["port"] = u8(p, 20)
                    out["rssi"] = u8(p, 21)
                }
                49 -> if (p.size >= 12) {
                    out["latitude"] = i32(p, 0)
                    out["longitude"] = i32(p, 4)
                    out["altitude"] = i32(p, 8)
                }
                74 -> if (p.size >= 20) {
                    out["airspeed"] = f32(p, 0)
                    out["groundspeed"] = f32(p, 4)
                    out["alt"] = f32(p, 8)
                    out["climb"] = f32(p, 12)
                    out["heading"] = i16(p, 16)
                    out["throttle"] = u16(p, 18)
                }
                109 -> if (p.size >= 9) {
                    out["rssi"] = u8(p, 0)
                    out["remrssi"] = u8(p, 1)
                    out["txbuf"] = u8(p, 2)
                    out["noise"] = u8(p, 3)
                    out["remnoise"] = u8(p, 4)
                    out["rxerrors"] = u16(p, 5)
                    out["fixed"] = u16(p, 7)
                }
                147 -> if (p.size >= 36) {
                    out["current_consumed"] = i32(p, 0)
                    out["energy_consumed"] = i32(p, 4)
                    out["temperature"] = i16(p, 8)
                    out["current_battery"] = i16(p, 30)
                    out["id"] = u8(p, 32)
                    out["battery_function"] = u8(p, 33)
                    out["type"] = u8(p, 34)
                    out["battery_remaining"] = i8(p, 35)
                }
                242 -> if (p.size >= 52) {
                    out["latitude"] = i32(p, 0)
                    out["longitude"] = i32(p, 4)
                    out["altitude"] = i32(p, 8)
                }
                253 -> if (p.size >= 51) {
                    out["severity"] = u8(p, 0)
                    out["text"] = String(p, 1, 50, Charsets.UTF_8).substringBefore('\u0000')
                }
            }
        } catch (_: Exception) {
        }
        return out
    }

    private fun u8(p: ByteArray, o: Int): Int = p[o].toInt() and 0xFF
    private fun i8(p: ByteArray, o: Int): Int = p[o].toInt()
    private fun u16(p: ByteArray, o: Int): Int = ByteBuffer.wrap(p, o, 2).order(ByteOrder.LITTLE_ENDIAN).short.toInt() and 0xFFFF
    private fun i16(p: ByteArray, o: Int): Int = ByteBuffer.wrap(p, o, 2).order(ByteOrder.LITTLE_ENDIAN).short.toInt()
    private fun u32(p: ByteArray, o: Int): Long = ByteBuffer.wrap(p, o, 4).order(ByteOrder.LITTLE_ENDIAN).int.toLong() and 0xFFFFFFFFL
    private fun i32(p: ByteArray, o: Int): Int = ByteBuffer.wrap(p, o, 4).order(ByteOrder.LITTLE_ENDIAN).int
    private fun u64(p: ByteArray, o: Int): Long = ByteBuffer.wrap(p, o, 8).order(ByteOrder.LITTLE_ENDIAN).long
    private fun f32(p: ByteArray, o: Int): Float = ByteBuffer.wrap(p, o, 4).order(ByteOrder.LITTLE_ENDIAN).float
}
