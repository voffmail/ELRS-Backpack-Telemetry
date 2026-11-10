"""Minimal MAVLink v1/v2 parser for the Betaflight telemetry stream.

Only the messages used by the ELRS backpack viewer are decoded. Unknown
messages are still framed so they can be counted, but they are not validated
because their CRC_EXTRA value is not known here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable, Optional

# msgid -> (name, crc_extra, length, min_length)
MESSAGE_INFO = {
    0: ("HEARTBEAT", 50, 9, 9),
    1: ("SYS_STATUS", 124, 43, 31),
    2: ("SYSTEM_TIME", 137, 12, 12),
    4: ("PING", 237, 14, 14),
    24: ("GPS_RAW_INT", 24, 52, 30),
    30: ("ATTITUDE", 39, 28, 28),
    33: ("GLOBAL_POSITION_INT", 104, 28, 28),
    35: ("RC_CHANNELS_RAW", 244, 22, 22),
    49: ("GPS_GLOBAL_ORIGIN", 39, 20, 12),
    74: ("VFR_HUD", 20, 20, 20),
    76: ("COMMAND_LONG", 152, 33, 33),
    77: ("COMMAND_ACK", 143, 10, 3),
    109: ("RADIO_STATUS", 185, 9, 9),
    111: ("TIMESYNC", 34, 18, 16),
    147: ("BATTERY_STATUS", 154, 54, 36),
    242: ("HOME_POSITION", 104, 60, 52),
    253: ("STATUSTEXT", 83, 54, 51),
    300: ("PROTOCOL_VERSION", 217, 22, 22),
    435: ("AVAILABLE_MODES", 134, 47, 46),
}

CRC_EXTRA = {msgid: info[1] for msgid, info in MESSAGE_INFO.items()}
MESSAGE_NAME = {msgid: info[0] for msgid, info in MESSAGE_INFO.items()}

MAVLINK1_MAGIC = 0xFE
MAVLINK2_MAGIC = 0xFD

# Betaflight HEARTBEAT.custom_mode values.
BF_FLIGHT_MODES = {
    0: "Acro",
    1: "Angle",
    2: "Horizon",
    3: "Alt Hold",
    4: "Pos Hold",
    5: "Autopilot",
    6: "RTL",
    7: "Failsafe",
}

MAV_MODE_FLAG_SAFETY_ARMED = 0x80


def crc16_mcrf4xx(data: bytes, crc: int = 0xFFFF) -> int:
    for byte in data:
        tmp = (byte ^ (crc & 0xFF)) & 0xFF
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    return crc


def _u8(p: bytes, o: int) -> int:
    return p[o]


def _i8(p: bytes, o: int) -> int:
    return struct.unpack_from("<b", p, o)[0]


def _u16(p: bytes, o: int) -> int:
    return struct.unpack_from("<H", p, o)[0]


def _i16(p: bytes, o: int) -> int:
    return struct.unpack_from("<h", p, o)[0]


def _u32(p: bytes, o: int) -> int:
    return struct.unpack_from("<I", p, o)[0]


def _i32(p: bytes, o: int) -> int:
    return struct.unpack_from("<i", p, o)[0]


def _u64(p: bytes, o: int) -> int:
    return struct.unpack_from("<Q", p, o)[0]


def _f32(p: bytes, o: int) -> float:
    return struct.unpack_from("<f", p, o)[0]


@dataclass
class MavFrame:
    version: int
    seq: int
    sysid: int
    compid: int
    msgid: int
    payload: bytes
    crc_ok: Optional[bool]

    @property
    def name(self) -> str:
        return MESSAGE_NAME.get(self.msgid, f"MSG_{self.msgid}")


def iter_frames(data: bytes) -> Iterable[MavFrame]:
    """Yield MAVLink frames found in a datagram or byte stream."""
    i = 0
    n = len(data)
    while i < n:
        magic = data[i]
        if magic == MAVLINK1_MAGIC:
            header_len = 6
            if i + header_len > n:
                break
            payload_len = data[i + 1]
            msgid = data[i + 5]
            seq = data[i + 2]
            sysid = data[i + 3]
            compid = data[i + 4]
            payload_start = i + 6
            crc_start = payload_start + payload_len
            total = 6 + payload_len + 2
            version = 1
        elif magic == MAVLINK2_MAGIC:
            header_len = 10
            if i + header_len > n:
                break
            payload_len = data[i + 1]
            incompat = data[i + 2]
            seq = data[i + 4]
            sysid = data[i + 5]
            compid = data[i + 6]
            msgid = data[i + 7] | (data[i + 8] << 8) | (data[i + 9] << 16)
            payload_start = i + 10
            crc_start = payload_start + payload_len
            signature = 13 if (incompat & 0x01) else 0
            total = 10 + payload_len + 2 + signature
            version = 2
        else:
            i += 1
            continue

        if i + total > n:
            break

        payload = data[payload_start:crc_start]
        crc_read = struct.unpack_from("<H", data, crc_start)[0]
        extra = CRC_EXTRA.get(msgid)
        if extra is None:
            crc_ok = None
        else:
            crc_ok = crc16_mcrf4xx(data[i + 1:crc_start] + bytes((extra,))) == crc_read

        yield MavFrame(
            version=version,
            seq=seq,
            sysid=sysid,
            compid=compid,
            msgid=msgid,
            payload=payload,
            crc_ok=crc_ok,
        )
        if crc_ok is False:
            i += 1
        else:
            i += total


def first_valid_frame(data: bytes) -> Optional[MavFrame]:
    for frame in iter_frames(data):
        if frame.crc_ok is True:
            return frame
    return None


def decode_message(frame: MavFrame) -> dict:
    p = frame.payload
    msgid = frame.msgid
    out = {"msgid": msgid, "name": frame.name}
    try:
        if msgid == 0 and len(p) >= 9:
            out.update(
                custom_mode=_u32(p, 0),
                type=_u8(p, 4),
                autopilot=_u8(p, 5),
                base_mode=_u8(p, 6),
                system_status=_u8(p, 7),
                armed=bool(_u8(p, 6) & MAV_MODE_FLAG_SAFETY_ARMED),
            )
        elif msgid == 1 and len(p) >= 31:
            out.update(
                voltage_battery=_u16(p, 14),
                current_battery=_i16(p, 16),
                battery_remaining=_i8(p, 30),
            )
        elif msgid == 2 and len(p) >= 12:
            out.update(
                time_unix_usec=_u64(p, 0),
                time_boot_ms=_u32(p, 8),
            )
        elif msgid == 24 and len(p) >= 30:
            out.update(
                time_usec=_u64(p, 0),
                lat=_i32(p, 8),
                lon=_i32(p, 12),
                alt=_i32(p, 16),
                eph=_u16(p, 20),
                epv=_u16(p, 22),
                vel=_u16(p, 24),
                cog=_u16(p, 26),
                fix_type=_u8(p, 28),
                satellites_visible=_u8(p, 29),
            )
            if len(p) >= 46:
                out.update(
                    alt_ellipsoid=_i32(p, 30),
                    h_acc=_u32(p, 34),
                    v_acc=_u32(p, 38),
                    vel_acc=_u32(p, 42),
                )
        elif msgid == 30 and len(p) >= 28:
            out.update(
                time_boot_ms=_u32(p, 0),
                roll=_f32(p, 4),
                pitch=_f32(p, 8),
                yaw=_f32(p, 12),
                rollspeed=_f32(p, 16),
                pitchspeed=_f32(p, 20),
                yawspeed=_f32(p, 24),
            )
        elif msgid == 33 and len(p) >= 28:
            out.update(
                time_boot_ms=_u32(p, 0),
                lat=_i32(p, 4),
                lon=_i32(p, 8),
                alt=_i32(p, 12),
                relative_alt=_i32(p, 16),
                vx=_i16(p, 20),
                vy=_i16(p, 22),
                vz=_i16(p, 24),
                hdg=_u16(p, 26),
            )
        elif msgid == 35 and len(p) >= 22:
            out.update(
                time_boot_ms=_u32(p, 0),
                chan1_raw=_u16(p, 4),
                chan2_raw=_u16(p, 6),
                chan3_raw=_u16(p, 8),
                chan4_raw=_u16(p, 10),
                chan5_raw=_u16(p, 12),
                chan6_raw=_u16(p, 14),
                chan7_raw=_u16(p, 16),
                chan8_raw=_u16(p, 18),
                port=_u8(p, 20),
                rssi=_u8(p, 21),
            )
        elif msgid == 49 and len(p) >= 12:
            out.update(
                latitude=_i32(p, 0),
                longitude=_i32(p, 4),
                altitude=_i32(p, 8),
            )
        elif msgid == 74 and len(p) >= 20:
            out.update(
                airspeed=_f32(p, 0),
                groundspeed=_f32(p, 4),
                alt=_f32(p, 8),
                climb=_f32(p, 12),
                heading=_i16(p, 16),
                throttle=_u16(p, 18),
            )
        elif msgid == 109 and len(p) >= 9:
            out.update(
                rssi=_u8(p, 0),
                remrssi=_u8(p, 1),
                txbuf=_u8(p, 2),
                noise=_u8(p, 3),
                remnoise=_u8(p, 4),
                rxerrors=_u16(p, 5),
                fixed=_u16(p, 7),
            )
        elif msgid == 147 and len(p) >= 36:
            out.update(
                current_consumed=_i32(p, 0),
                energy_consumed=_i32(p, 4),
                temperature=_i16(p, 8),
                voltages=list(struct.unpack_from("<10H", p, 10)),
                current_battery=_i16(p, 30),
                id=_u8(p, 32),
                battery_function=_u8(p, 33),
                type=_u8(p, 34),
                battery_remaining=_i8(p, 35),
            )
        elif msgid == 242 and len(p) >= 52:
            out.update(
                latitude=_i32(p, 0),
                longitude=_i32(p, 4),
                altitude=_i32(p, 8),
            )
        elif msgid == 253 and len(p) >= 51:
            out.update(
                severity=_u8(p, 0),
                text=p[1:51].split(b"\x00", 1)[0].decode("utf-8", "replace"),
            )
    except struct.error:
        pass
    return out


def frame_summary(frame: MavFrame) -> str:
    decoded = decode_message(frame)
    if frame.msgid == 24:
        return (
            f"lat={decoded.get('lat', 0) / 1e7:.7f} "
            f"lon={decoded.get('lon', 0) / 1e7:.7f} "
            f"fix={decoded.get('fix_type', 0)}"
        )
    return frame.name
