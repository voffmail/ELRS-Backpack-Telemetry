#!/usr/bin/env python3
"""Generate a synthetic Betaflight-like MAVLink telemetry stream.

The output uses the same JSONL format as ``tools/udp_capture.py`` so it can be
fed to ``replay.py`` and the desktop/Android viewers.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time

try:
    from tools import mavlink_protocol as mav
except ImportError:  # running this file directly
    import mavlink_protocol as mav

SYSID = 1
COMPID = 1
DEFAULT_LAT = 61.253930
DEFAULT_LON = 73.188795


def _crc(payload: bytes, msgid: int, seq: int) -> int:
    extra = mav.CRC_EXTRA[msgid]
    return mav.crc16_mcrf4xx(
        bytes((len(payload), 0, 0, seq & 0xFF, SYSID, COMPID)) +
        bytes((msgid & 0xFF, (msgid >> 8) & 0xFF, (msgid >> 16) & 0xFF)) +
        payload + bytes((extra,))
    )


def pack_v2(seq: int, msgid: int, payload: bytes) -> bytes:
    header = bytes((
        0xFD,
        len(payload),
        0,
        0,
        seq & 0xFF,
        SYSID,
        COMPID,
        msgid & 0xFF,
        (msgid >> 8) & 0xFF,
        (msgid >> 16) & 0xFF,
    ))
    crc = _crc(payload, msgid, seq)
    return header + payload + struct.pack("<H", crc)


def heartbeat(seq: int, custom_mode: int = 1, armed: bool = False) -> bytes:
    payload = struct.pack(
        "<IBBBBB",
        custom_mode,
        2,      # MAV_TYPE_QUADROTOR
        0,      # MAV_AUTOPILOT_GENERIC (Betaflight 2026.6.2)
        0x80 if armed else 0,
        4 if armed else 3,
        3,
    )
    return pack_v2(seq, 0, payload)


def sys_status(seq: int, voltage_mv: int, current_ca: int, remaining: int) -> bytes:
    payload = struct.pack(
        "<IIIHHhHHHHHHb",
        0x8C03, 0x8C03, 0x8C03,
        0, voltage_mv, current_ca, 0, 0, 0, 0, 0, 0, remaining,
    )
    return pack_v2(seq, 1, payload)


def system_time(seq: int) -> bytes:
    payload = struct.pack("<QI", 0, int(time.monotonic() * 1000) & 0xFFFFFFFF)
    return pack_v2(seq, 2, payload)


def gps_raw_int(
    seq: int,
    lat_e7: int,
    lon_e7: int,
    alt_m: float,
    fix_type: int,
    sats: int,
    speed_cms: int,
    course_cdeg: int,
    hdop: int = 90,
    vdop: int = 120,
) -> bytes:
    payload = struct.pack(
        "<QiiiHHHHBBiiiIIH",
        int(time.monotonic() * 1_000_000) & 0xFFFFFFFFFFFFFFFF,
        lat_e7,
        lon_e7,
        int(alt_m * 1000),
        hdop,
        vdop,
        speed_cms,
        course_cdeg,
        fix_type,
        sats,
        int(alt_m * 1000),
        1500,
        2000,
        300,
        0xFFFFFFFF,
        0,
    )[:52]
    return pack_v2(seq, 24, payload)


def global_position_int(
    seq: int,
    lat_e7: int,
    lon_e7: int,
    alt_m: float,
    rel_alt_m: float,
    vn_cms: int,
    ve_cms: int,
    vd_cms: int,
    heading_cdeg: int,
) -> bytes:
    payload = struct.pack(
        "<IiiiihhhH",
        int(time.monotonic() * 1000) & 0xFFFFFFFF,
        lat_e7,
        lon_e7,
        int(alt_m * 1000),
        int(rel_alt_m * 1000),
        vn_cms,
        ve_cms,
        vd_cms,
        heading_cdeg,
    )
    return pack_v2(seq, 33, payload)


def attitude(seq: int, roll: float, pitch: float, yaw: float) -> bytes:
    payload = struct.pack(
        "<Iffffff",
        int(time.monotonic() * 1000) & 0xFFFFFFFF,
        roll,
        -pitch,
        yaw,
        0.0,
        0.0,
        0.0,
    )
    return pack_v2(seq, 30, payload)


def rc_channels_raw(seq: int, rssi: int) -> bytes:
    payload = struct.pack(
        "<I8HBB",
        int(time.monotonic() * 1000) & 0xFFFFFFFF,
        1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000,
        0,
        max(0, min(254, rssi)),
    )
    return pack_v2(seq, 35, payload)


def vfr_hud(seq: int, groundspeed: float, alt: float, heading: int) -> bytes:
    payload = struct.pack("<ffffhH", 0.0, groundspeed, alt, 0.0, heading, 50)
    return pack_v2(seq, 74, payload)


def battery_status(seq: int, voltage_mv: int, current_ca: int, mah: int, remaining: int) -> bytes:
    payload = struct.pack(
        "<iih10HhBBBBiB4HBI",
        mah, -1, 0,
        voltage_mv, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF,
        0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF,
        current_ca, 0, 0, 0, remaining,
        0, 0, 0, 0, 0, 0, 0, 0,
    )[:54]
    return pack_v2(seq, 147, payload)


def gps_global_origin(seq: int, lat_e7: int, lon_e7: int, alt_m: float) -> bytes:
    payload = struct.pack(
        "<iiiQ",
        lat_e7, lon_e7, int(alt_m * 1000),
        int(time.monotonic() * 1_000_000) & 0xFFFFFFFFFFFFFFFF,
    )
    return pack_v2(seq, 49, payload)


class Simulator:
    def __init__(
        self,
        duration: float = 30.0,
        pos_rate: float = 2.0,
        rates: dict | None = None,
        fix: bool = True,
        lat: float = DEFAULT_LAT,
        lon: float = DEFAULT_LON,
        armed: bool = True,
    ):
        self.duration = duration
        self.pos_rate = pos_rate
        self.rates = rates or {
            "ext": 2.0,
            "rc": 1.0,
            "extra1": 2.0,
            "extra2": 2.0,
            "extra3": 1.0,
        }
        self.fix = fix
        self.lat = lat
        self.lon = lon
        self.armed = armed
        self.seq = 0
        self.voltage_mv = 25200
        self.current_ca = 120
        self.mah = 0
        self.t = 0.0

    def _next_seq(self) -> int:
        seq = self.seq
        self.seq = (self.seq + 1) & 0xFF
        return seq

    def _position(self) -> tuple[int, int, float, int, int, int, int]:
        radius_m = 80.0
        omega = 0.15
        angle = self.t * omega
        dlat = (radius_m * math.cos(angle)) / 111_320.0
        dlon = (radius_m * math.sin(angle)) / (111_320.0 * math.cos(math.radians(self.lat)))
        lat_e7 = int(round((self.lat + dlat) * 1e7))
        lon_e7 = int(round((self.lon + dlon) * 1e7))
        alt = 120.0
        speed_cms = int(radius_m * omega * 100)
        course = int((math.degrees(angle) + 90.0) % 360.0 * 100)
        vn = int(-speed_cms * math.sin(angle))
        ve = int(speed_cms * math.cos(angle))
        return lat_e7, lon_e7, alt, speed_cms, course, vn, ve

    def messages(self, dt: float) -> list[bytes]:
        self.t += dt
        out: list[bytes] = []
        lat_e7, lon_e7, alt, speed, course, vn, ve = self._position()
        fix_type = 3 if self.fix else 1
        sats = 10 if self.fix else 0

        def due(rate: float) -> bool:
            return rate > 0 and int(self.t * rate + 1e-9) != int((self.t - dt) * rate + 1e-9)

        if due(self.rates.get("ext", 2.0)):
            self.mah += max(0, int(self.current_ca * dt / 3.6))
            out.append(sys_status(self._next_seq(), self.voltage_mv, self.current_ca, 72))
            out.append(system_time(self._next_seq()))
        if due(self.rates.get("rc", 1.0)):
            out.append(rc_channels_raw(self._next_seq(), 220))
        if due(self.pos_rate):
            out.append(gps_raw_int(
                self._next_seq(), lat_e7, lon_e7, alt, fix_type, sats,
                speed, course,
            ))
            out.append(global_position_int(
                self._next_seq(), lat_e7, lon_e7, alt, 42.0,
                vn, ve, 0, course,
            ))
            out.append(gps_global_origin(self._next_seq(), lat_e7, lon_e7, alt))
        if due(self.rates.get("extra1", 2.0)):
            out.append(attitude(
                self._next_seq(),
                math.radians(8.0 * math.sin(self.t * 0.5)),
                math.radians(5.0 * math.sin(self.t * 0.3)),
                math.radians(course / 100.0),
            ))
        if due(self.rates.get("extra2", 2.0)):
            out.append(heartbeat(self._next_seq(), 1, self.armed))
            out.append(vfr_hud(self._next_seq(), speed / 100.0, alt, course // 100))
        if due(self.rates.get("extra3", 1.0)):
            out.append(battery_status(
                self._next_seq(), self.voltage_mv, self.current_ca,
                self.mah, 72,
            ))
        return out

    def datagrams(self):
        step = 0.02
        pending: list[bytes] = []
        start = 0.0
        t = 0.0
        while t < self.duration:
            pending.extend(self.messages(step))
            t += step
            if len(pending) >= 8:
                yield t, b"".join(pending)
                pending = []
        if pending:
            yield t, b"".join(pending)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate synthetic Betaflight MAVLink JSONL")
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--pos-rate", type=float, default=2.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-fix", action="store_true")
    ap.add_argument("--src", default="127.0.0.1:14555")
    args = ap.parse_args()

    sim = Simulator(duration=args.duration, pos_rate=args.pos_rate, fix=not args.no_fix)
    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        for t, data in sim.datagrams():
            out.write(json.dumps(
                {"t": round(t, 6), "src": args.src, "data": data.hex()},
                separators=(",", ":"),
            ) + "\n")
    finally:
        if out is not sys.stdout:
            out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
