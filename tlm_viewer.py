#!/usr/bin/env python3
import argparse
import copy
import json
import math
import os
import re
import socket
import struct
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from tools import mavlink_protocol as mav

LOCK = threading.RLock()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRACKS_DIR = os.path.join(BASE_DIR, "tracks")
STATIC_DIR = os.path.join(BASE_DIR, "web", "static")
TILES_DIR = os.path.join(BASE_DIR, "tiles")
RECORD = {
    "active": False,
    "id": None,
    "start_mono": 0.0,
    "started_at": None,
    "protocol": None,
    "points": [],
}
STATE = {
    "link": None,
    "battery": None,
    "gps": None,
    "gps_last": None,
    "gps_ext": None,
    "gps_ext_at": 0.0,
    "gps_time": None,
    "attitude": None,
    "baro": None,
    "vario": None,
    "flight_mode": None,
    "device": None,
    "frames": {},
    "unknown": {},
    "link_at": 0.0,
    "telemetry_at": 0.0,
}
STATS = {"total": 0, "times": deque(maxlen=4000), "last": 0.0}
MAV_STATE = {
    "link": None,
    "battery": None,
    "gps": None,
    "gps_last": None,
    "gps_ext": None,
    "gps_time": None,
    "attitude": None,
    "baro": None,
    "vario": None,
    "flight_mode": None,
    "device": None,
    "frames": {},
    "unknown": {},
    "link_at": 0.0,
    "telemetry_at": 0.0,
    "heartbeat": None,
    "armed": None,
}
MAV_STATS = {
    "total": 0,
    "times": deque(maxlen=4000),
    "last": 0.0,
    "messages": 0,
    "message_times": deque(maxlen=8000),
}
TELEMETRY_TYPES = {0x02, 0x03, 0x06, 0x07, 0x08, 0x09, 0x1E, 0x21, 0x29}
MAV_TELEMETRY_TYPES = {1, 2, 24, 30, 33, 49, 74, 147, 242}
ONLINE_TIMEOUT_SEC = 2.0
SWITCH_GAP_SEC = 0.5
SWITCH_CONFIRM_COUNT = 3
SETTINGS = {"auto_record_3d": False, "auto_stop_sec": 10}
SETTINGS_FILE = os.path.join(BASE_DIR, "tlm_viewer_settings.json")
SESSION = {
    "protocol": None,
    "id": None,
    "started_at": None,
    "source": None,
    "last_valid": 0.0,
}
ROUTER = {"candidate": None, "count": 0, "since": 0.0}


def s8(v):
    return v - 256 if v > 127 else v


def crc8(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0xD5) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def iter_frames(data):
    i = 0
    n = len(data)
    while i < n - 2:
        if data[i] in (0xC8, 0xEA, 0xEE):
            length = data[i + 1]
            if 2 <= length <= 62 and i + 2 + length <= n:
                frame = data[i:i + 2 + length]
                if crc8(frame[2:-1]) == frame[-1]:
                    yield frame
                    i += 2 + length
                    continue
        i += 1


def reset_crsf_state():
    STATE.update({
        "link": None, "battery": None, "gps": None, "gps_last": None,
        "gps_ext": None, "gps_ext_at": 0.0, "gps_time": None,
        "attitude": None, "baro": None, "vario": None,
        "flight_mode": None, "device": None, "frames": {}, "unknown": {},
        "link_at": 0.0, "telemetry_at": 0.0,
    })


def reset_mav_state():
    MAV_STATE.update({
        "link": None, "battery": None, "gps": None, "gps_last": None,
        "gps_ext": None, "gps_time": None, "attitude": None, "baro": None,
        "vario": None, "flight_mode": None, "device": None, "frames": {},
        "unknown": {}, "link_at": 0.0, "telemetry_at": 0.0,
        "heartbeat": None, "armed": None,
    })


def reset_stats():
    STATS.update({"total": 0, "times": deque(maxlen=4000), "last": 0.0})
    MAV_STATS.update({
        "total": 0, "times": deque(maxlen=4000), "last": 0.0,
        "messages": 0, "message_times": deque(maxlen=8000),
    })


def new_session_id():
    base = time.strftime("session_%Y%m%d_%H%M%S")
    if SESSION.get("id") == base:
        return base + "_2"
    return base


def start_session(protocol, source, now):
    SESSION.update({
        "protocol": protocol,
        "id": new_session_id(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": source,
        "last_valid": now,
    })
    ROUTER.update({"candidate": None, "count": 0, "since": 0.0})


def switch_protocol(protocol, source, now):
    if RECORD["active"]:
        stop_recording()
    if protocol == "crsf":
        reset_crsf_state()
    else:
        reset_mav_state()
    reset_stats()
    start_session(protocol, source, now)


def route_protocol(protocol, source):
    now = time.monotonic()
    active = SESSION["protocol"]
    if active is None:
        start_session(protocol, source, now)
        return True
    if protocol == active:
        SESSION["last_valid"] = now
        ROUTER.update({"candidate": None, "count": 0, "since": 0.0})
        return True
    active_age = now - (SESSION["last_valid"] or 0.0)
    if active_age >= ONLINE_TIMEOUT_SEC:
        switch_protocol(protocol, source, now)
        return True
    if active_age < SWITCH_GAP_SEC:
        return False
    if ROUTER["candidate"] != protocol:
        ROUTER.update({"candidate": protocol, "count": 1, "since": now})
    else:
        ROUTER["count"] += 1
    if ROUTER["count"] >= SWITCH_CONFIRM_COUNT or (now - ROUTER["since"]) >= 0.3:
        switch_protocol(protocol, source, now)
        return True
    return False


def detect_protocol(data):
    if not data:
        return None
    if data[:3] == b"$X<" or data[0] in (0xC8, 0xEA, 0xEE):
        for _ in iter_frames(data):
            return "crsf"
        return None
    if data[0] in (0xFD, 0xFE):
        return "mavlink" if mav.first_valid_frame(data) is not None else None
    return None


def active_state():
    return MAV_STATE if SESSION["protocol"] == "mavlink" else STATE


def active_stats():
    return MAV_STATS if SESSION["protocol"] == "mavlink" else STATS


def active_protocol():
    return SESSION["protocol"] or "crsf"


def append_record_point(g, protocol, extra=None):
    if not RECORD["active"]:
        return
    point = {
        "t": round(time.monotonic() - RECORD["start_mono"], 3),
        "lat": g["lat"], "lon": g["lon"], "alt": g["alt"],
        "speed": g["speed"], "heading": g["heading"], "sats": g["sats"],
        "protocol": protocol,
        "session_id": SESSION["id"],
    }
    if g.get("fix_type") is not None:
        point["fix_type"] = g["fix_type"]
        point["fix_type_computed"] = False
    if extra:
        point["data"] = extra
    RECORD["points"].append(point)


def maybe_auto_record(fix3d, protocol):
    if SETTINGS["auto_record_3d"] and fix3d and not RECORD["active"]:
        start_recording(protocol)


def parse_mavlink_frame(frame):
    if frame.crc_ok is not True:
        return
    now_mono = time.monotonic()
    MAV_STATS["messages"] += 1
    MAV_STATS["message_times"].append(time.time())
    MAV_STATE["frames"][frame.msgid] = MAV_STATE["frames"].get(frame.msgid, 0) + 1
    if frame.msgid in MAV_TELEMETRY_TYPES:
        MAV_STATE["telemetry_at"] = now_mono
    decoded = mav.decode_message(frame)
    msgid = frame.msgid
    if msgid == 0:
        MAV_STATE["link_at"] = now_mono
        MAV_STATE["heartbeat"] = decoded
        MAV_STATE["armed"] = decoded.get("armed")
        mode = decoded.get("custom_mode", 0)
        MAV_STATE["flight_mode"] = mav.BF_FLIGHT_MODES.get(mode, str(mode))
        MAV_STATE["device"] = "MAVLink"
    elif msgid == 24:
        lat = decoded.get("lat", 0) / 1e7
        lon = decoded.get("lon", 0) / 1e7
        alt = decoded.get("alt", 0) / 1000.0
        speed = decoded.get("vel", 0) * 0.036
        heading = decoded.get("cog", 0) / 100.0
        sats = decoded.get("satellites_visible", 0)
        fix_type = decoded.get("fix_type", 0)
        fix3d = fix_type >= 3
        fix_pos = fix_type >= 2 and sats >= 3
        prev = MAV_STATE["gps"]
        was3d = bool(prev and prev.get("fix3d"))
        gps = {
            "lat": lat, "lon": lon, "speed": speed, "heading": heading,
            "alt": alt, "sats": sats, "fix": fix_pos, "fix3d": fix3d,
            "fix_type": fix_type, "fix_type_computed": False,
        }
        MAV_STATE["gps"] = gps
        if fix_pos:
            MAV_STATE["gps_last"] = dict(gps)
        MAV_STATE["gps_ext"] = {
            "fix_type": fix_type,
            "vn": (MAV_STATE.get("gps_ext") or {}).get("vn", 0.0),
            "ve": (MAV_STATE.get("gps_ext") or {}).get("ve", 0.0),
            "vv": (MAV_STATE.get("gps_ext") or {}).get("vv", 0.0),
            "speed_acc": decoded.get("vel_acc", 0) / 1000.0 if decoded.get("vel_acc") is not None else None,
            "track_acc": None,
            "alt_ellipsoid": decoded.get("alt_ellipsoid", 0) / 1000.0 if decoded.get("alt_ellipsoid") is not None else None,
            "h_acc": decoded.get("h_acc", 0) / 1000.0 if decoded.get("h_acc") is not None else None,
            "v_acc": decoded.get("v_acc", 0) / 1000.0 if decoded.get("v_acc") is not None else None,
            "reserved": None,
            "hdop": decoded.get("eph", 0) / 100.0,
            "vdop": decoded.get("epv", 0) / 100.0,
        }
        if not was3d and fix3d:
            maybe_auto_record(True, "mavlink")
        if RECORD["active"] and fix3d:
            extra = {"mavlink": {
                "fix_type": fix_type,
                "eph": decoded.get("eph"),
                "epv": decoded.get("epv"),
                "vel": decoded.get("vel"),
                "cog": decoded.get("cog"),
                "h_acc": decoded.get("h_acc"),
                "v_acc": decoded.get("v_acc"),
                "vel_acc": decoded.get("vel_acc"),
            }}
            append_record_point(gps, "mavlink", extra)
    elif msgid == 33:
        gps = MAV_STATE["gps"]
        if gps:
            gps["relative_alt"] = decoded.get("relative_alt", 0) / 1000.0
        ext = MAV_STATE.get("gps_ext") or {}
        ext.update({
            "vn": decoded.get("vx", 0) / 100.0,
            "ve": decoded.get("vy", 0) / 100.0,
            "vv": -decoded.get("vz", 0) / 100.0,
        })
        MAV_STATE["gps_ext"] = ext
        MAV_STATE["vario"] = -decoded.get("vz", 0) / 100.0
    elif msgid == 30:
        pitch = -math.degrees(decoded.get("pitch", 0.0))
        roll = math.degrees(decoded.get("roll", 0.0))
        yaw = math.degrees(decoded.get("yaw", 0.0))
        MAV_STATE["attitude"] = {"pitch": pitch, "roll": roll, "yaw": yaw}
    elif msgid == 1:
        voltage = decoded.get("voltage_battery", 0) / 1000.0
        current = decoded.get("current_battery", -1)
        remaining = decoded.get("battery_remaining", -1)
        MAV_STATE["battery"] = {
            "voltage": voltage,
            "current": current / 100.0 if current >= 0 else None,
            "capacity": (MAV_STATE.get("battery") or {}).get("capacity"),
            "remaining": remaining if remaining >= 0 else None,
        }
    elif msgid == 147:
        battery = MAV_STATE.get("battery") or {}
        current = decoded.get("current_battery", -1)
        remaining = decoded.get("battery_remaining", -1)
        consumed = decoded.get("current_consumed", -1)
        battery.update({
            "voltage": battery.get("voltage"),
            "current": current / 100.0 if current >= 0 else battery.get("current"),
            "capacity": consumed if consumed >= 0 else battery.get("capacity"),
            "remaining": remaining if remaining >= 0 else battery.get("remaining"),
        })
        MAV_STATE["battery"] = battery
    elif msgid == 74:
        MAV_STATE["baro"] = {
            "alt": decoded.get("alt", 0.0),
            "vario": MAV_STATE.get("vario") or 0.0,
        }
    elif msgid == 2:
        unix_usec = decoded.get("time_unix_usec", 0)
        if unix_usec:
            MAV_STATE["gps_time"] = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.gmtime(unix_usec / 1_000_000.0)
            )
    elif msgid == 35:
        rssi = decoded.get("rssi", 0)
        MAV_STATE["link"] = {
            "rssi_pct": round(100.0 * min(rssi, 254) / 254.0, 1),
            "lq": None, "lq_d": None, "snr": None, "snr_d": None,
            "rssi1": None, "rssi2": None, "rssi_d": None,
            "active_ant": None, "rf_mode": None, "tx_power": None,
        }
    elif msgid == 253:
        text = decoded.get("text")
        if text:
            MAV_STATE["device"] = MAV_STATE.get("device") or "MAVLink"


def parse_frame(t, p):
    now_mono = time.monotonic()
    if t == 0x14:
        STATE["link_at"] = now_mono
    elif t in TELEMETRY_TYPES:
        STATE["telemetry_at"] = now_mono
    if t == 0x14 and len(p) >= 10:
        a1, a2, lq, snr, ant, rf, txp, dr, dlq, dsnr = struct.unpack(">BBBBBBBBBB", p[:10])
        STATE["link"] = {
            "rssi1": s8(a1), "rssi2": s8(a2), "lq": lq, "snr": s8(snr),
            "active_ant": ant, "rf_mode": rf, "tx_power": txp,
            "rssi_d": s8(dr), "lq_d": dlq, "snr_d": s8(dsnr),
        }
    elif t == 0x1E and len(p) >= 6:
        pitch, roll, yaw = struct.unpack(">hhh", p[:6])
        k = 180.0 / 3.141592653589793 / 10000.0
        STATE["attitude"] = {"pitch": pitch * k, "roll": roll * k, "yaw": yaw * k}
    elif t == 0x02 and len(p) >= 15:
        lat, lon, spd, hdg, alt, sats = struct.unpack(">iiHHHB", p[:15])
        now_mono = time.monotonic()
        ge = STATE["gps_ext"]
        fresh_ext = ge is not None and now_mono - STATE["gps_ext_at"] <= 5.0
        if fresh_ext:
            fix_3d = ge["fix_type"] == 3 and sats >= 4
            fix_pos = ge["fix_type"] in (2, 3) and sats >= 3
        else:
            fix_3d = sats >= 4
            fix_pos = sats >= 3
        fix_type = (ge["fix_type"] if fresh_ext else
                    (3 if fix_3d else 2 if fix_pos else 0))
        prev = STATE["gps"]
        was3d = bool(prev and prev.get("fix3d"))
        STATE["gps"] = {
            "lat": lat / 1e7, "lon": lon / 1e7,
            "speed": spd / 10.0, "heading": hdg / 100.0,
            "alt": float(alt - 1000), "sats": sats,
            "fix": fix_pos, "fix3d": fix_3d,
            "fix_type": fix_type, "fix_type_computed": not fresh_ext,
        }
        if fix_pos:
            STATE["gps_last"] = dict(STATE["gps"])
        if not was3d and fix_3d:
            maybe_auto_record(True, "crsf")
        if fix_3d and RECORD["active"]:
            append_record_point(STATE["gps"], "crsf")
    elif t == 0x08 and len(p) >= 8:
        volt, curr = struct.unpack(">HH", p[:4])
        capacity = int.from_bytes(p[4:7], "big")
        STATE["battery"] = {
            "voltage": volt / 10.0, "current": curr / 10.0,
            "capacity": capacity, "remaining": p[7],
        }
    elif t == 0x07 and len(p) >= 2:
        STATE["vario"] = struct.unpack(">h", p[:2])[0] / 100.0
    elif t == 0x09 and len(p) >= 3:
        raw = struct.unpack(">H", p[:2])[0]
        vs = s8(p[2])
        alt = float(raw & 0x7FFF) if raw & 0x8000 else (raw - 10000) / 10.0
        var = (math.exp(abs(vs) * 0.026) - 1.0) * 100.0
        STATE["baro"] = {"alt": alt, "vario": (var if vs >= 0 else -var) / 100.0}
    elif t == 0x03 and len(p) >= 9:
        year = struct.unpack(">H", p[:2])[0]
        month, day, hour, minute, sec = p[2:7]
        millis = struct.unpack(">H", p[7:9])[0]
        STATE["gps_time"] = f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{sec:02d}.{millis:03d}"
    elif t == 0x06 and len(p) >= 20:
        fix_type = p[0]
        n, e, v, hs, trk, ell, ha, va = struct.unpack(">hhhhhhhh", p[1:17])
        STATE["gps_ext"] = {
            "fix_type": fix_type, "vn": n / 100.0, "ve": e / 100.0, "vv": v / 100.0,
            "h_acc": ha / 100.0, "v_acc": va / 100.0,
            "hdop": p[18] / 10.0, "vdop": p[19] / 10.0,
        }
        STATE["gps_ext_at"] = time.monotonic()
    elif t == 0x21 and p:
        STATE["flight_mode"] = p.split(b"\x00", 1)[0].decode("ascii", "replace")
    elif t == 0x29 and len(p) > 2:
        name = p[2:].split(b"\x00", 1)[0].decode("ascii", "replace")
        if name:
            STATE["device"] = name
    else:
        STATE["unknown"][t] = p.hex()


def listener(udp_port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    except OSError:
        pass
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    try:
        sock.bind(("0.0.0.0", udp_port))
    except OSError as exc:
        raise SystemExit(f"Не удалось слушать UDP {udp_port}: {exc}") from exc
    while True:
        data, addr = sock.recvfrom(65535)
        ingest_datagram(data, f"{addr[0]}:{addr[1]}")


def ingest_datagram(data, source="network"):
    protocol = detect_protocol(data)
    if protocol is None:
        return False
    with LOCK:
        if not route_protocol(protocol, source):
            return False
        now = time.time()
        if protocol == "crsf":
            STATS["total"] += 1
            STATS["times"].append(now)
            STATS["last"] = now
            for frame in iter_frames(data):
                t = frame[2]
                STATE["frames"][t] = STATE["frames"].get(t, 0) + 1
                parse_frame(t, frame[3:-1])
        else:
            MAV_STATS["total"] += 1
            MAV_STATS["times"].append(now)
            MAV_STATS["last"] = now
            for frame in mav.iter_frames(data):
                if frame.crc_ok is True:
                    parse_mavlink_frame(frame)
    return True


def snapshot():
    now = time.time()
    with LOCK:
        now_mono = time.monotonic()
        protocol = active_protocol()
        state = active_state()
        stats = active_stats()
        pps = sum(1 for t in stats["times"] if now - t <= 1.0)
        age = (now - stats["last"]) if stats["last"] else None
        telemetry_age = ((now_mono - state["telemetry_at"])
                         if state["telemetry_at"] else None)
        link_age = (now_mono - state["link_at"]) if state["link_at"] else None
        link = state["link"]
        if protocol == "mavlink":
            link_up = bool(link_age is not None and link_age <= ONLINE_TIMEOUT_SEC)
            messages_pps = sum(
                1 for t in stats.get("message_times", ()) if now - t <= 1.0
            )
        else:
            link_up = bool(
                link and link_age is not None and link_age <= ONLINE_TIMEOUT_SEC
                and link["lq"] > 0 and link["lq_d"] > 0
            )
            messages_pps = None
        online = link_up or (telemetry_age is not None
                             and telemetry_age <= ONLINE_TIMEOUT_SEC)
        record = {
            "active": RECORD["active"],
            "id": RECORD["id"],
            "started_at": RECORD["started_at"],
            "protocol": RECORD["protocol"],
            "duration": (time.monotonic() - RECORD["start_mono"]) if RECORD["active"] else 0.0,
            "point_count": len(RECORD["points"]),
        }
        session = {
            "id": SESSION["id"],
            "protocol": SESSION["protocol"],
            "started_at": SESSION["started_at"],
            "source": SESSION["source"],
        }
        stats_json = {
            "total": stats["total"], "pps": pps, "age": age,
            "online": online, "link_up": link_up,
            "telemetry_age": telemetry_age, "link_age": link_age,
        }
        if protocol == "mavlink":
            stats_json["messages"] = stats.get("messages", 0)
            stats_json["messages_pps"] = messages_pps
        return {
            "protocol": protocol,
            "session": session,
            "capabilities": {
                "link_stats": protocol == "crsf",
                "rssi_pct": protocol == "mavlink",
                "gps_ext": True,
                "gps_time": True,
                "device": protocol == "crsf",
            },
            "link": copy.deepcopy(state["link"]),
            "battery": copy.deepcopy(state["battery"]),
            "gps": copy.deepcopy(state["gps"]),
            "gps_last": copy.deepcopy(state["gps_last"]),
            "gps_ext": copy.deepcopy(state["gps_ext"]),
            "gps_time": state["gps_time"],
            "attitude": copy.deepcopy(state["attitude"]),
            "baro": copy.deepcopy(state["baro"]),
            "vario": state["vario"],
            "flight_mode": state["flight_mode"],
            "device": state["device"],
            "armed": state.get("armed"),
            "frames": dict(state["frames"]),
            "unknown": dict(state["unknown"]),
            "record": record,
            "stats": stats_json,
        }

def track_id_valid(track_id):
    return bool(track_id and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", track_id))


def next_track_id():
    base = time.strftime("track_%Y%m%d_%H%M%S")
    candidate = base
    n = 2
    while os.path.exists(os.path.join(TRACKS_DIR, candidate + ".json")):
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def start_recording(protocol=None):
    with LOCK:
        if RECORD["active"]:
            return False, "already recording"
        os.makedirs(TRACKS_DIR, exist_ok=True)
        RECORD["active"] = True
        RECORD["id"] = next_track_id()
        RECORD["start_mono"] = time.monotonic()
        RECORD["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        RECORD["protocol"] = protocol or SESSION["protocol"] or "crsf"
        RECORD["points"] = []
        return True, ""


def stop_recording():
    with LOCK:
        if not RECORD["active"]:
            return None, "not recording"
        points = list(RECORD["points"])
        track_id = RECORD["id"]
        started_at = RECORD["started_at"]
        protocol = RECORD["protocol"]
        RECORD["active"] = False
        RECORD["id"] = None
        RECORD["started_at"] = None
        RECORD["start_mono"] = 0.0
        RECORD["protocol"] = None
        RECORD["points"] = []
    if not points:
        return None, "no GPS points recorded"
    protocols = sorted({p.get("protocol") for p in points if p.get("protocol")})
    meta = {
        "version": 2,
        "id": track_id,
        "started_at": started_at,
        "duration": round(points[-1]["t"], 3),
        "point_count": len(points),
        "protocols": protocols or ([protocol] if protocol else []),
    }
    os.makedirs(TRACKS_DIR, exist_ok=True)
    with open(os.path.join(TRACKS_DIR, track_id + ".json"), "w", encoding="utf-8") as f:
        json.dump({**meta, "points": points}, f, ensure_ascii=False)
    return meta, ""


def record_snapshot(since=0):
    with LOCK:
        points = RECORD["points"]
        total = len(points)
        try:
            start = max(0, min(int(since), total))
        except (TypeError, ValueError):
            start = 0
        return {
            "active": RECORD["active"],
            "id": RECORD["id"],
            "started_at": RECORD["started_at"],
            "protocol": RECORD["protocol"],
            "duration": (time.monotonic() - RECORD["start_mono"]) if RECORD["active"] else 0.0,
            "total": total,
            "points": copy.deepcopy(points[start:]),
        }


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key in ("auto_record_3d", "auto_stop_sec"):
                if key in data:
                    SETTINGS[key] = data[key]
    except (OSError, ValueError):
        pass


def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(SETTINGS, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def settings_snapshot():
    return {
        "auto_record_3d": bool(SETTINGS.get("auto_record_3d")),
        "auto_stop_recording_sec": int(SETTINGS.get("auto_stop_sec", 10)),
        "source": "network",
        "udp_port": None,
        "recording": RECORD["active"],
    }


def auto_stop_loop():
    while True:
        time.sleep(0.5)
        with LOCK:
            if not RECORD["active"]:
                continue
            seconds = int(SETTINGS.get("auto_stop_sec", 0) or 0)
            if seconds <= 0:
                continue
            state = active_state()
            if not state["telemetry_at"]:
                continue
            age = time.monotonic() - state["telemetry_at"]
            if age > seconds:
                stop_recording()


def list_tracks():
    os.makedirs(TRACKS_DIR, exist_ok=True)
    result = []
    for name in os.listdir(TRACKS_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(TRACKS_DIR, name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        result.append({
            "id": data.get("id", name[:-5]),
            "started_at": data.get("started_at"),
            "duration": data.get("duration", 0),
            "point_count": data.get("point_count", len(data.get("points", []))),
        })
    result.sort(key=lambda item: item.get("started_at") or "", reverse=True)
    return result


def load_track(track_id):
    if not track_id_valid(track_id):
        return None
    try:
        with open(os.path.join(TRACKS_DIR, track_id + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def delete_track(track_id):
    if not track_id_valid(track_id):
        return False
    try:
        os.remove(os.path.join(TRACKS_DIR, track_id + ".json"))
        return True
    except OSError:
        return False


PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ELRS Backpack Telemetry</title>
<link rel="stylesheet" href="/static/maplibre-gl.css?v=4">
<script src="/static/maplibre-gl.js?v=4"></script>
<script src="/static/pmtiles.js?v=4"></script>
<script src="/static/elrs-map.js?v=9"></script>
<script defer src="https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js"></script>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         background: #0b0f14; color: #e6edf3; }
  header { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap;
           padding: 7px 16px; border-bottom: 1px solid #1f2630; position: sticky; top: 0;
           background: rgba(11,15,20,.92); backdrop-filter: blur(8px); z-index: 2; }
  .brand { display: flex; flex-direction: column; gap: 1px; font-size: 15px;
           letter-spacing: .2px; line-height: 1.1; }
  .brand b { color: #3fb950; }
  .brandName { white-space: nowrap; }
  .brandSub { color: #f0883e; font-size: inherit; letter-spacing: .2px; white-space: nowrap;
              text-decoration: none; align-self: flex-start; }
  .brandSub:hover { text-decoration: underline; }
  .pill { font-size: 11px; padding: 3px 8px; border-radius: 999px; border: 1px solid #30363d;
          color: #7d8590; white-space: nowrap; }
  .pill.on { color: #3fb950; border-color: #238636; background: rgba(63,185,80,.1); }
  .pill.off { color: #f85149; border-color: #6e2c2c; background: rgba(248,81,73,.08); }
  .headRight { display: flex; align-items: center; gap: 8px; flex-wrap: nowrap; flex: 0 0 auto; }
  .lang { background: #11161d; color: #e6edf3; border: 1px solid #30363d; border-radius: 6px;
          padding: 3px 6px; font-size: 11px; outline: none; }
  .lang:focus { border-color: #3fb950; }
  main { display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
         gap: 14px; padding: 16px 20px 40px; max-width: 1200px; margin: 0 auto; }
  .card { background: #11161d; border: 1px solid #1f2630; border-radius: 14px; padding: 16px;
          min-width: 0; }
  .card.wide { grid-column: 1 / -1; }
  h2 { margin: 0 0 14px; font-size: 12px; font-weight: 600; text-transform: uppercase;
       letter-spacing: .12em; color: #7d8590; }
  .row { display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
         margin-top: 10px; font-size: 13px; }
  .row:first-of-type { margin-top: 0; }
  .lq { font-variant-numeric: tabular-nums; font-weight: 600; }
  .track { height: 7px; border-radius: 4px; background: #1f2630; overflow: hidden; margin-top: 6px; }
  .fill { height: 100%; width: 0; border-radius: 4px; background: #3fb950; transition: width .2s linear; }
  .fill.mid { background: #d29922; }
  .fill.low { background: #f85149; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
  .grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 12px; }
  .grid4 { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 12px; }
  small { display: block; color: #7d8590; font-size: 11px; text-transform: uppercase;
          letter-spacing: .06em; }
  .val { font-size: 17px; font-variant-numeric: tabular-nums; margin-top: 3px; }
  .big { font-size: 34px; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.1; }
  .big small { display: inline; font-size: 14px; color: #7d8590; text-transform: none; letter-spacing: 0; }
  .muted { color: #7d8590; }
  .modeRow { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
  .modeNote { font-size: 12px; color: #7d8590; }
  .horizon { position: relative; height: 150px; border-radius: 12px; overflow: hidden;
             background: #0b0f14; border: 1px solid #1f2630; }
  .horizon .inner { position: absolute; left: -60%; right: -60%; top: -60%; bottom: -60%;
                    background: linear-gradient(to bottom, #1f4e79 0 50%, #6b4a1f 50% 100%);
                    transition: transform .12s linear; }
  .horizon .cross { position: absolute; inset: 0; }
  .horizon .cross:before, .horizon .cross:after { content: ""; position: absolute; background: #e6edf3;
                    opacity: .8; }
  .horizon .cross:before { left: 50%; top: 50%; width: 46px; height: 2px; transform: translate(-50%,-50%); }
  .horizon .cross:after { left: 50%; top: 50%; width: 2px; height: 46px; transform: translate(-50%,-50%); }
  a { color: #58a6ff; font-size: 13px; }
  details { margin-top: 14px; }
  summary { cursor: pointer; color: #7d8590; font-size: 12px; }
  pre { margin: 10px 0 0; padding: 10px; background: #0b0f14; border: 1px solid #1f2630;
        border-radius: 8px; overflow: auto; font-size: 12px; color: #9da7b3; }
  table.frames { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }
  table.frames th { text-align: left; color: #7d8590; font-weight: 600; padding: 6px 8px;
                    border-bottom: 1px solid #1f2630; white-space: nowrap; }
  table.frames td { padding: 6px 8px; border-bottom: 1px solid #171d26; vertical-align: top; }
  table.frames tr:last-child td { border-bottom: none; }
  table.frames td:first-child, table.frames td:nth-child(3) {
                    font-variant-numeric: tabular-nums; white-space: nowrap; }
  table.frames td:last-child { color: #9da7b3; }
  table.frames tr.unknown td:last-child { color: #d29922; }
  [hidden] { display: none !important; }
  .tabs { display: flex; flex: 1; justify-content: center; gap: 6px; padding: 0; margin: 0; }
  .tab { background: transparent; color: #7d8590; border: 1px solid transparent; border-radius: 12px;
         padding: 6px 15px; font-size: 18px; line-height: 1.2; font-family: inherit; cursor: pointer; }
  .tab:hover { color: #e6edf3; }
  .tab.active { color: #e6edf3; background: #11161d; border-color: #30363d; }
  #mapPage { padding: 16px 20px 40px; max-width: 1200px; margin: 0 auto; }
  .mapWrap { position: relative; height: calc(100vh - 110px); min-height: 360px;
             border: 1px solid #1f2630; border-radius: 14px; overflow: hidden; background: #0b0f14; }
  #map { position: absolute; inset: 0; }
  .droneMarker { width: 48px; height: 48px; pointer-events: none; }
  .droneMarker svg { display: block; filter: drop-shadow(0 2px 4px rgba(0,0,0,.5)); }
  .droneMarker.stale { opacity: .55; }
  .gpsHead { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
  .gpsSats { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
  .gpsSats #sats { font-size: 28px; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.1; }
  .qrBox { margin: 0; flex: 0 0 auto; cursor: pointer; outline: none; }
  .qrBox:focus-visible .qrCode { outline: 2px solid #3fb950; outline-offset: 2px; }
  .qrCode { width: 96px; height: 96px; padding: 4px; border-radius: 8px; background: #fff;
            color: #0b0f14; font-size: 9px; line-height: 1.15; word-break: break-all;
            display: flex; align-items: center; justify-content: center; }
  .qrCode svg { display: block; width: 100%; height: 100%; }
  .gpsGrid, .gpsGrid3 { margin-top: 8px; }
  .trackPanel { position: absolute; left: 12px; right: 12px; bottom: 12px; z-index: 7;
                padding: 0; border: 1px solid #30363d; border-radius: 12px;
                background: rgba(11,15,20,.88); backdrop-filter: blur(6px); }
  .trackHead { display: flex; align-items: center; gap: 8px; padding: 8px 10px; flex-wrap: wrap; }
  .trackHeader { display: flex; align-items: center; gap: 6px; padding: 0;
                 background: transparent; border: 0; color: #e6edf3; font: inherit; font-size: 12px;
                 text-align: left; cursor: pointer; white-space: nowrap; }
  .trackChevron { width: 14px; color: #7d8590; }
  .trackBody { display: flex; flex-direction: column; gap: 6px; padding: 0 10px 8px; }
  .trackPanel.collapsed .trackBody { display: none; }
  .trackPanel:not(.collapsed) .trackHead { border-bottom: 1px solid #1f2630; border-radius: 12px 12px 0 0; }
  .trackRow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  #playRow { flex-wrap: nowrap; }
  .trackActions { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .trackSelect { background: #11161d; color: #e6edf3; border: 1px solid #30363d; border-radius: 8px;
                 padding: 5px 8px; font-size: 12px; max-width: 220px; }
  #trackSelect { min-width: 0; flex: 1 1 auto; }
  .trackRange { flex: 1; min-width: 60px; accent-color: #3fb950; }
  .trackStatus { color: #9da7b3; font-size: 12px; font-variant-numeric: tabular-nums; margin-left: auto; }
  .trackTime { color: #9da7b3; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  #recordBtn { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
  .recIcon { width: 12px; height: 12px; fill: currentColor; flex: 0 0 auto; }
  #recordBtn.recording { border-color: #f85149; color: #f85149; animation: recBlink 1.2s ease-in-out infinite; }
  @keyframes recBlink { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
  .playbackMarker { width: 22px; height: 22px; pointer-events: none; }
  .playbackMarker svg { display: block; filter: drop-shadow(0 1px 3px rgba(0,0,0,.6)); }

  #settingsCard, .guideCard { grid-column: 1 / -1; }
  .settingsGroup { margin-bottom: 12px; }
  .settingsGroup:last-child { margin-bottom: 0; }
  .settingsLabel { font-size: 12px; color: #9da7b3; margin-bottom: 4px; }
  .settingsRow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .settingsRow input[type=number] { width: 110px; padding: 6px 8px; border-radius: 8px;
      border: 1px solid #30363d; background: #0b0f14; color: #e6edf3; font: inherit; font-size: 13px; }
  .settingsValue { color: #e6edf3; font-size: 13px; word-break: break-all; margin-bottom: 6px; }
  .settingsMsg { font-size: 12px; color: #3fb950; }
  .settingsMsg.err { color: #f85149; }
  .permList { list-style: none; margin: 6px 0 8px; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  .permList li { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; }
  .permList .permName { flex: 1 1 160px; }
  .permState { font-size: 11px; padding: 2px 8px; border-radius: 999px; border: 1px solid #30363d; white-space: nowrap; }
  .permState.ok { color: #3fb950; border-color: #238636; background: rgba(63,185,80,.1); }
  .permState.bad { color: #f85149; border-color: #6e2c2c; background: rgba(248,81,73,.08); }
  .permBtn { padding: 3px 8px !important; font-size: 11px !important; }
  .guideCard summary, .settingsCard summary { cursor: pointer; font-size: 15px; font-weight: 600; color: #e6edf3; }
  .guideBody, .settingsBody { margin-top: 10px; }
  .guideBody b { display: block; margin: 10px 0 4px; font-size: 13px; color: #e6edf3; }
  .guideList { margin: 0 0 0 18px; padding: 0; color: #c9d1d9; font-size: 13px; line-height: 1.5; }
  .guideList li { margin-bottom: 5px; }
  .guideNote { color: #9da7b3; font-size: 12px; line-height: 1.45; margin-top: 6px; }
  .guideDetails { margin-top: 10px; padding: 8px 10px; border: 1px solid #1f2630;
                  border-radius: 10px; background: #0b0f14; }
  .guideDetails summary { cursor: pointer; font-size: 13px; font-weight: 600; color: #e6edf3; }
  .guideDetails .guideList { margin-top: 8px; }
  .guideDetails .guideLink { display: inline-block; margin-top: 8px; }
  .supportCard { grid-column: 1 / -1; padding: 0; }
  .supportLink { display: block; padding: 14px 16px; color: #c9d1d9; text-decoration: none;
                 font-size: 13px; line-height: 1.45; border-radius: 14px; }
  .supportLink:hover { background: rgba(63,185,80,.06); color: #e6edf3; }
  .supportChannel { color: #3fb950; font-weight: 600; }
  #mapInfo { bottom: 56px; }
  .mapBar { position: absolute; left: 12px; top: 12px; z-index: 5; display: flex; flex-wrap: wrap;
            align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid #30363d;
            border-radius: 10px; background: rgba(11,15,20,.82); backdrop-filter: blur(6px); }
  .mapToggle { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #c9d1d9; }
  .mapBtn { background: #11161d; color: #e6edf3; border: 1px solid #30363d; border-radius: 8px;
            padding: 5px 10px; font-size: 12px; font-family: inherit; cursor: pointer; }
  .mapBtn:hover { border-color: #3fb950; }
  .closeCard { grid-column: 1 / -1; padding: 10px; }
  .closeCard .closeBtn { width: 100%; padding: 12px; font-size: 14px; color: #f85149;
                         border-color: #6e2c2c; background: rgba(248,81,73,.06); }
  .closeCard .closeBtn:hover { border-color: #f85149; background: rgba(248,81,73,.12); }
  #mapStatus { position: absolute; left: 50%; top: 16px; transform: translateX(-50%); z-index: 6;
               padding: 6px 12px; border-radius: 999px; border: 1px solid #6e2c2c;
               background: rgba(11,15,20,.9); color: #f85149; font-size: 12px; white-space: nowrap; }
  #mapInfo { position: absolute; left: 12px; bottom: 12px; z-index: 5; padding: 6px 10px;
             border: 1px solid #30363d; border-radius: 10px; background: rgba(11,15,20,.82);
             color: #9da7b3; font-size: 12px; font-variant-numeric: tabular-nums; }
  @media (max-width: 520px) { header { padding: 5px 8px; gap: 2px; } .brand { font-size: 12px; } .pill { font-size: 9px; padding: 2px 5px; } .lang { font-size: 9px; padding: 2px 3px; border-radius: 5px; } .headRight { gap: 3px; } main { padding: 12px; } .big { font-size: 28px; } .tabs { justify-content: center; gap: 2px; padding: 0; min-width: 0; } .tab { padding: 4px 7px; font-size: 14px; border-radius: 9px; } #mapPage { padding: 12px; } .qrCode { width: 84px; height: 84px; } .gpsSats #sats { font-size: 24px; } .trackPanel { left: 8px; right: 8px; bottom: 8px; } .trackSelect { max-width: 150px; } #mapInfo { display: none; } }
  @media (max-width: 330px) { .tabs { order: 3; flex-basis: 100%; justify-content: flex-start; padding-top: 2px; } }

  #telemetryPage .card { background: #151c25; border-color: #2d3742; }
  #telemetryPage h2 { color: #b1bac4; }
  #telemetryPage small { color: #b1bac4; }
  #telemetryPage .val, #telemetryPage .lq, #telemetryPage .big,
  #telemetryPage .gpsSats #sats { color: #56d364; font-weight: 600; }
  #telemetryPage .val { font-size: 18px; color: #56d364; }
  #telemetryPage .val, #telemetryPage .lq { text-shadow: 0 0 10px rgba(86,211,100,.18); }
  #telemetryPage .lq.mid { color: #d29922; text-shadow: 0 0 10px rgba(210,153,34,.2); }
  #telemetryPage .lq.low { color: #f85149; text-shadow: 0 0 10px rgba(248,81,73,.22); }
  #telemetryPage .big { text-shadow: 0 0 14px rgba(86,211,100,.22); }
  #telemetryPage .big small { color: #b1bac4; font-weight: 400; text-shadow: none; }
  #telemetryPage .track { background: #26303c; }
  #telemetryPage .modeNote, #telemetryPage .muted { color: #b1bac4; }
  #telemetryPage table.frames th { color: #b1bac4; }
  #telemetryPage table.frames td { color: #e6edf3; }
  #telemetryPage table.frames td:last-child { color: #b1bac4; }
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="brandName"><b>ELRS</b> Backpack</div>
    <a class="brandSub" href="https://github.com/voffmail/ELRS-Backpack-Telemetry" target="_blank" rel="noopener noreferrer">Telemetry</a>
  </div>
  <nav class="tabs">
    <button class="tab active" data-tab="telemetry" data-i18n="tab_telemetry">Telemetry</button>
    <button class="tab" data-tab="map" data-i18n="tab_map">Map</button>
  </nav>
  <div class="headRight">
    <div id="protocol" class="pill proto" hidden>—</div>
    <div id="status" class="pill" data-i18n="status_wait">waiting for data</div>
    <select id="lang" class="lang" aria-label="Language">
      <option value="en">EN</option>
      <option value="ru">RU</option>
      <option value="zh">中文</option>
    </select>
  </div>
</header>
<main id="telemetryPage">
  <div id="crsfCards">
  <section class="card">
    <h2 data-i18n="card_link">Link</h2>
    <div class="row"><span data-i18n="lq_uplink">Uplink LQ</span><span class="lq" id="lqUp">—</span></div>
    <div class="track"><div class="fill" id="barUp"></div></div>
    <div class="grid2">
      <div><small data-i18n="rssi">RSSI</small><div class="val" id="rssiUp">—</div></div>
      <div><small data-i18n="snr">SNR</small><div class="val" id="snrUp">—</div></div>
    </div>
    <div class="row"><span data-i18n="lq_downlink">Downlink LQ</span><span class="lq" id="lqDn">—</span></div>
    <div class="track"><div class="fill" id="barDn"></div></div>
    <div class="grid2">
      <div><small data-i18n="rssi">RSSI</small><div class="val" id="rssiDn">—</div></div>
      <div><small data-i18n="snr">SNR</small><div class="val" id="snrDn">—</div></div>
    </div>
    <div class="grid2">
      <div><small data-i18n="tx_power">TX power</small><div class="val" id="txp">—</div></div>
      <div><small data-i18n="antenna">Antenna</small><div class="val" id="ant">—</div></div>
    </div>
    <div class="grid2">
      <div><small data-i18n="band">Band</small><div class="val" id="band">—</div></div>
      <div><small data-i18n="packet_rate">Packet rate</small><div class="val" id="pktRate">—</div></div>
    </div>
    <div class="row"><span data-i18n="range">Range</span><span class="lq" id="rangePct">—</span></div>
    <div class="track"><div class="fill" id="barRange"></div></div>
  </section>

  <section class="card">
    <h2 data-i18n="card_battery">Battery</h2>
    <div class="big"><span id="volt">—</span> <small data-i18n="u_v">V</small></div>
    <div class="grid2">
      <div><small data-i18n="current">Current</small><div class="val" id="curr">—</div></div>
      <div><small data-i18n="capacity">Capacity</small><div class="val" id="cap">—</div></div>
    </div>
    <div class="row"><span data-i18n="remaining">Remaining</span><span class="lq" id="remTxt">—</span></div>
    <div class="track"><div class="fill" id="barRem"></div></div>
  </section>

  <section class="card">
    <h2 data-i18n="card_gps">GPS</h2>
    <div class="gpsHead">
      <div class="gpsSats"><span id="sats">—</span><small data-i18n="satellites">satellites</small></div>
      <div id="gpsQrWrap" class="qrBox" hidden role="button" tabindex="0"><div id="gpsQr" class="qrCode"></div></div>
    </div>
    <div class="grid2 gpsGrid">
      <div><small data-i18n="latitude">Latitude</small><div class="val" id="lat">—</div></div>
      <div><small data-i18n="longitude">Longitude</small><div class="val" id="lon">—</div></div>
      <div><small data-i18n="altitude">Altitude</small><div class="val" id="alt">—</div></div>
      <div><small data-i18n="speed">Speed</small><div class="val" id="spd">—</div></div>
    </div>
    <div class="grid3 gpsGrid3">
      <div><small data-i18n="heading">Heading</small><div class="val" id="hdg">—</div></div>
      <div><small data-i18n="fix">Fix</small><div class="val" id="fixType">—</div></div>
      <div><small data-i18n="hdop">HDOP</small><div class="val" id="hdop">—</div></div>
    </div>
    <div class="row"><button id="showMap" class="mapBtn" style="display:none" data-i18n="show_on_map">Show on map</button></div>
  </section>

  <section class="card">
    <h2 data-i18n="card_flight">Flight</h2>
    <div class="modeRow">
      <div class="big" id="flightMode">—</div>
      <div class="modeNote" id="flightNote"></div>
    </div>
    <div class="grid2">
      <div><small data-i18n="baro_alt">Baro altitude</small><div class="val" id="baroAlt">—</div></div>
      <div><small data-i18n="vario">Vario</small><div class="val" id="vario">—</div></div>
    </div>
    <div class="grid2">
      <div><small data-i18n="gps_time">GPS time</small><div class="val" id="gpsTime">—</div></div>
      <div><small data-i18n="device">Device</small><div class="val" id="device">—</div></div>
    </div>
  </section>

  <section class="card">
    <h2 data-i18n="card_attitude">Attitude</h2>
    <div class="horizon"><div class="inner" id="horizon"></div><div class="cross"></div></div>
    <div class="grid3">
      <div><small data-i18n="pitch">Pitch</small><div class="val" id="pitch">—</div></div>
      <div><small data-i18n="roll">Roll</small><div class="val" id="roll">—</div></div>
      <div><small data-i18n="yaw">Yaw</small><div class="val" id="yaw">—</div></div>
    </div>
  </section>

  <section class="card wide">
    <h2 data-i18n="card_rx">Reception</h2>
    <div class="grid4">
      <div><small data-i18n="packets_per_sec">Packets/s</small><div class="val" id="pps">—</div></div>
      <div><small data-i18n="packets_total">Total packets</small><div class="val" id="total">—</div></div>
      <div><small data-i18n="data_age">Data age</small><div class="val" id="age">—</div></div>
      <div><small data-i18n="frame_types">Frame types</small><div class="val" id="typesCount">—</div></div>
    </div>
    <details><summary data-i18n="crsf_frame_types">CRSF frame types</summary>
      <table class="frames">
        <thead><tr><th data-i18n="th_type">Type</th><th data-i18n="th_frame">Frame</th><th data-i18n="th_packets">Packets</th><th data-i18n="th_contains">Contains</th></tr></thead>
        <tbody id="framesBody"><tr><td colspan="4" class="muted" data-i18n="no_frames">no frames yet</td></tr></tbody>
      </table>
    </details>
  </section>
  </div>
  <div id="mavCards" hidden>
  <section class="card">
    <h2 data-i18n="card_link">Link</h2>
    <div class="row"><span data-i18n="rssi">RSSI</span><span class="lq" id="mavRssi">—</span></div>
    <div class="grid2">
      <div><small data-i18n="mav_heartbeat">Heartbeat</small><div class="val" id="mavHeartbeat">—</div></div>
      <div><small data-i18n="mav_armed">Armed</small><div class="val" id="mavArmed">—</div></div>
    </div>
    <div class="grid2">
      <div><small data-i18n="mav_messages_per_sec">Messages/s</small><div class="val" id="mavMsgRate">—</div></div>
      <div><small data-i18n="mav_messages_total">Messages</small><div class="val" id="mavMsgTotal">—</div></div>
    </div>
    <div class="row"><span data-i18n="mavlink_loss">MAVLink loss</span><span class="val" id="mavLoss">—</span></div>
  </section>

  <section class="card">
    <h2 data-i18n="card_gps">GPS</h2>
    <div class="gpsHead">
      <div class="gpsSats"><span id="mavSats">—</span><small data-i18n="satellites">satellites</small></div>
      <div id="mavGpsQrWrap" class="qrBox" hidden role="button" tabindex="0"><div id="mavGpsQr" class="qrCode"></div></div>
    </div>
    <div class="grid2 gpsGrid">
      <div><small data-i18n="latitude">Latitude</small><div class="val" id="mavLat">—</div></div>
      <div><small data-i18n="longitude">Longitude</small><div class="val" id="mavLon">—</div></div>
      <div><small data-i18n="altitude">Altitude</small><div class="val" id="mavAlt">—</div></div>
      <div><small data-i18n="speed">Speed</small><div class="val" id="mavSpd">—</div></div>
    </div>
    <div class="grid3 gpsGrid3">
      <div><small data-i18n="heading">Heading</small><div class="val" id="mavHdg">—</div></div>
      <div><small data-i18n="fix">Fix</small><div class="val" id="mavFix">—</div></div>
      <div><small data-i18n="hdop">HDOP</small><div class="val" id="mavHdop">—</div></div>
    </div>
    <div class="grid2">
      <div><small data-i18n="vdop">VDOP</small><div class="val" id="mavVdop">—</div></div>
      <div><small data-i18n="mav_h_acc">H accuracy</small><div class="val" id="mavHAcc">—</div></div>
    </div>
  </section>

  <section class="card">
    <h2 data-i18n="card_flight">Flight</h2>
    <div class="modeRow">
      <div class="big" id="mavFlightMode">—</div>
      <div class="modeNote" id="mavFlightNote"></div>
    </div>
    <div class="grid2">
      <div><small data-i18n="altitude">Altitude</small><div class="val" id="mavBaroAlt">—</div></div>
      <div><small data-i18n="vario">Vario</small><div class="val" id="mavVario">—</div></div>
    </div>
    <div class="grid2">
      <div><small data-i18n="gps_time">GPS time</small><div class="val" id="mavGpsTime">—</div></div>
      <div><small data-i18n="device">Device</small><div class="val" id="mavDevice">—</div></div>
    </div>
  </section>

  <section class="card">
    <h2 data-i18n="card_attitude">Attitude</h2>
    <div class="horizon"><div class="inner" id="mavHorizon"></div><div class="cross"></div></div>
    <div class="grid3">
      <div><small data-i18n="pitch">Pitch</small><div class="val" id="mavPitch">—</div></div>
      <div><small data-i18n="roll">Roll</small><div class="val" id="mavRoll">—</div></div>
      <div><small data-i18n="yaw">Yaw</small><div class="val" id="mavYaw">—</div></div>
    </div>
  </section>

  <section class="card">
    <h2 data-i18n="card_battery">Battery</h2>
    <div class="big"><span id="mavVolt">—</span> <small data-i18n="u_v">V</small></div>
    <div class="grid2">
      <div><small data-i18n="current">Current</small><div class="val" id="mavCurr">—</div></div>
      <div><small data-i18n="capacity">Capacity</small><div class="val" id="mavCap">—</div></div>
    </div>
    <div class="row"><span data-i18n="remaining">Remaining</span><span class="lq" id="mavRemTxt">—</span></div>
    <div class="track"><div class="fill" id="mavBarRem"></div></div>
  </section>

  <section class="card wide">
    <h2 data-i18n="card_rx">Reception</h2>
    <div class="grid4">
      <div><small data-i18n="mav_messages_per_sec">Messages/s</small><div class="val" id="mavPps">—</div></div>
      <div><small data-i18n="mav_messages_total">Messages</small><div class="val" id="mavTotal">—</div></div>
      <div><small data-i18n="data_age">Data age</small><div class="val" id="mavAge">—</div></div>
      <div><small data-i18n="frame_types">Message types</small><div class="val" id="mavTypesCount">—</div></div>
    </div>
    <details><summary data-i18n="mavlink_messages">MAVLink messages</summary>
      <table class="frames">
        <thead><tr><th data-i18n="th_type">Type</th><th data-i18n="th_frame">Message</th><th data-i18n="th_packets">Count</th><th data-i18n="th_contains">Contains</th></tr></thead>
        <tbody id="mavFramesBody"><tr><td colspan="4" class="muted" data-i18n="no_frames">no messages yet</td></tr></tbody>
      </table>
    </details>
  </section>
  </div>

  <details class="card settingsCard" id="settingsCard" hidden>
    <summary data-i18n="settings">Settings</summary>
    <div class="settingsBody">
    <div class="settingsGroup">
      <div class="settingsLabel" data-i18n="udp_port">UDP listen port</div>
      <div class="settingsRow">
        <input id="udpPortInput" type="number" min="1" max="65535" inputmode="numeric">
        <button id="udpPortSave" class="mapBtn" data-i18n="apply">Apply</button>
        <span id="udpPortMsg" class="settingsMsg"></span>
      </div>
      <div class="guideNote" data-i18n="udp_port_note">The backpack must send telemetry to this port.</div>
    </div>
    <div class="settingsGroup">
      <div class="settingsLabel" data-i18n="idle_release">Release locks when no data (min)</div>
      <div class="settingsRow">
        <input id="idleReleaseMin" type="number" min="0" max="1440" inputmode="numeric" placeholder="5">
        <button id="idleReleaseSave" class="mapBtn" data-i18n="apply">Apply</button>
        <span id="idleReleaseMsg" class="settingsMsg"></span>
      </div>
      <div class="guideNote" data-i18n="idle_release_note">0 or empty — never release locks.</div>
    </div>
    <div class="settingsGroup">
      <div class="settingsLabel" data-i18n="tracks_location">Track storage</div>
      <div id="tracksLocation" class="settingsValue">—</div>
      <div class="settingsRow">
        <button id="chooseTracksFolder" class="mapBtn" data-i18n="choose_folder">Choose folder</button>
        <button id="resetTracksFolder" class="mapBtn" data-i18n="reset_folder">Reset</button>
        <span id="tracksMsg" class="settingsMsg"></span>
      </div>
      <div class="guideNote" data-i18n="tracks_note">Existing tracks are copied to the new folder.</div>
    </div>
    <div class="settingsGroup">
      <div class="settingsLabel" data-i18n="permissions">Permissions</div>
      <ul id="permissionList" class="permList"></ul>
      <div class="settingsRow">
        <button id="refreshPermissions" class="mapBtn" data-i18n="check_again">Check again</button>
        <button id="openAppSettings" class="mapBtn" data-i18n="app_settings">App settings</button>
      </div>
      <div class="guideNote" data-i18n="permissions_note">Install-time permissions are granted automatically; notifications and battery exemption are requested on first launch.</div>
    </div>
    </div>
  </details>

  <details class="card settingsCard" id="desktopSettingsCard" hidden>
    <summary data-i18n="settings">Settings</summary>
    <div class="settingsBody">
      <div class="settingsGroup">
        <label class="settingsRow" for="desktopAutoRecord3d">
          <input id="desktopAutoRecord3d" type="checkbox">
          <span data-i18n="auto_record_3d">Auto-record on 3D fix</span>
        </label>
        <div class="guideNote" data-i18n="auto_record_3d_note">Start a new track when a 3D fix appears. Off by default.</div>
      </div>
      <div class="settingsGroup">
        <div class="settingsLabel" data-i18n="auto_stop_recording">Stop recording when telemetry is lost (s)</div>
        <div class="settingsRow">
          <input id="desktopAutoStop" type="number" min="0" max="3600" inputmode="numeric">
          <button id="desktopAutoStopSave" class="mapBtn" data-i18n="apply">Apply</button>
          <span id="desktopSettingsMsg" class="settingsMsg"></span>
        </div>
        <div class="guideNote" data-i18n="auto_stop_recording_note">0 — never stop automatically.</div>
      </div>
    </div>
  </details>

  <details class="card guideCard">
    <summary data-i18n="guide_title">Quick setup guide</summary>
    <div class="guideBody">
      <b data-i18n="guide_methods">Two ways to receive telemetry</b>
      <ul class="guideList">
        <li data-i18n="guide_method_wifi">Wi-Fi — default. No extra hardware: the backpack starts an access point or joins your network.</li>
        <li data-i18n="guide_method_usb">ESP-NOW via USB — recommended. Less RF pollution. Needs an ESP32-C3/ESP32-S3 native-USB dongle and the serial bridge.</li>
      </ul>

      <b data-i18n="guide_wifi">Wi-Fi setup</b>
      <ol class="guideList">
        <li data-i18n="guide_wifi_1">In EdgeTX open ELRS Lua → Backpack → Telemetry and select “WiFi”. Do not use “WiFi Connectivity” — it configures the transmitter.</li>
        <li data-i18n="guide_wifi_2">Connect the computer to the “ExpressLRS TX Backpack XXXXXX” access point (password expresslrs) or to the same network as the backpack.</li>
        <li data-i18n="guide_wifi_3">Start the viewer: python3 tlm_viewer.py</li>
        <li data-i18n="guide_wifi_4">Open http://localhost:8080 and wait for the green online status and growing packet counters.</li>
      </ol>

      <b data-i18n="guide_espnow">ESP-NOW via USB setup</b>
      <ol class="guideList">
        <li data-i18n-html="guide_espnow_1">Flash the ESP32-C3/ESP32-S3 native-USB dongle with esp32-c3-usb-otg or esp32-s3-usb-otg via the Web Flasher or PlatformIO.</li>
        <li data-i18n="guide_espnow_2">In EdgeTX set: ELRS Lua → Backpack → Telemetry → ESP-NOW.</li>
        <li data-i18n="guide_espnow_3">Connect the dongle to the computer and find its serial port (/dev/ttyACM0, COMx, …).</li>
        <li data-i18n="guide_espnow_4">Start the viewer and the bridge: python3 tools/serial_bridge.py --serial /dev/ttyACM0 --udp 127.0.0.1:14550</li>
        <li data-i18n="guide_espnow_5">For phrase/UID, stop the bridge and use tools/dongle_config.py --port &lt;port&gt; --show or --phrase/--uid.</li>
      </ol>

      <b data-i18n="guide_problems">Possible problems</b>
      <ul class="guideList">
        <li data-i18n="guide_problem_nodata_python">No Wi-Fi data? Check Telemetry → WiFi, the shared network, the firewall, and UDP port 14550.</li>
        <li data-i18n="guide_problem_port_python">Port 14550 busy? Start the viewer with --udp-port &lt;port&gt; and the bridge with --udp 127.0.0.1:&lt;port&gt;.</li>
        <li data-i18n="guide_problem_usb_python">No USB data? Check the serial port, data cable, permissions, and that tools/serial_bridge.py is running.</li>
        <li data-i18n="guide_problem_bridge_port">Bridge and viewer ports must match; only one process can open the serial port.</li>
        <li data-i18n="guide_problem_vendor">Some vendors' access point does not start; a backpack firmware from master may help.</li>
      </ul>

      <details class="guideDetails">
        <summary data-i18n="guide_flash_title">Backpack flashing</summary>
        <ul class="guideList">
          <li data-i18n="guide_flash_1">Flashing is needed if the backpack does not start Wi-Fi/ESP-NOW or the menu item is missing. Flash via ExpressLRS Configurator → Backpack.</li>
          <li data-i18n="guide_flash_2">Binding phrase is optional for Wi-Fi telemetry: the viewer does not check the UID.</li>
          <li data-i18n="guide_flash_3">For ESP-NOW the phrase produces the UID and ESP-NOW group address; use the same phrase as your ELRS link or set a manual UID in the dongle settings.</li>
          <li data-i18n="guide_flash_4">Without a phrase the backpack uses the EEPROM group address (after binding) or leaves it zero; Wi-Fi telemetry still works. The AP password is always expresslrs.</li>
          <li data-i18n="guide_flash_5">Changing the phrase changes the UID and SSID — reflash all devices in the group with the same phrase.</li>
        </ul>
        <a class="guideLink" data-i18n="guide_flash_link" href="https://www.expresslrs.org/hardware/backpack/backpack-tx-setup/" target="_blank" rel="noopener noreferrer">Tx Backpack Setup — ExpressLRS</a>
      </details>

      <b data-i18n="guide_viewer">Viewer</b>
      <ol class="guideList">
        <li data-i18n="guide_viewer_1">Open http://localhost:8080 (or the computer IP) in a browser.</li>
        <li data-i18n="guide_viewer_2">Stop the viewer and the bridge with Ctrl+C in their terminals.</li>
        <li data-i18n="guide_viewer_3">The map requires internet access. Map tiles come from OpenStreetMap, OpenFreeMap, Esri and Sentinel-2; no API key is needed.</li>
      </ol>
    </div>
  </details>

  <section class="card supportCard">
    <a class="supportLink" href="https://rutube.ru/channel/36225989/" target="_blank" rel="noopener noreferrer">
      <span data-i18n="support_text">Вы можете отблагодарить автора за потраченные токены и время на Rutube-канале</span>
      <span class="supportChannel">Рассказы ветра</span>
    </a>
  </section>

  <section class="card closeCard" data-platform="android">
    <button id="closeApp" class="mapBtn closeBtn" data-i18n="close_app">Close app</button>
  </section>
</main>
<section id="mapPage" hidden>
  <div class="mapWrap">
    <div id="map"></div>
    <div class="mapBar">
      <label class="mapToggle"><input type="checkbox" id="followDrone" checked> <span data-i18n="follow">Follow</span></label>
      <button id="centerMap" class="mapBtn" data-i18n="center">Center</button>
    </div>
    <div id="mapStatus" hidden data-i18n="no_gps">No GPS fix</div>
    <div id="mapInfo">—</div>
    <div id="trackPanel" class="trackPanel collapsed">
      <div class="trackHead">
        <button id="trackToggle" class="trackHeader" aria-expanded="false">
          <span id="trackChevron" class="trackChevron">▸</span>
          <span data-i18n="track">Track</span>
        </button>
        <button id="recordBtn" class="mapBtn">
          <svg class="recIcon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7"/></svg>
          <span id="recordLabel" data-i18n="record">Record</span>
        </button>
        <select id="trackSelect" class="trackSelect"></select>
        <span id="recordStatus" class="trackStatus"></span>
      </div>
      <div id="trackBody" class="trackBody">
        <span id="trackActions" class="trackActions" hidden>
          <button id="deleteTrack" class="mapBtn" data-i18n="delete">Delete</button>
          <button id="exportGpx" class="mapBtn" disabled>GPX</button>
          <button id="exportKml" class="mapBtn" disabled>KML</button>
        </span>
        <div class="trackRow" id="playRow" hidden>
          <button id="playBtn" class="mapBtn"><span id="playLabel" data-i18n="play">Play</span></button>
          <input id="trackProgress" class="trackRange" type="range" min="0" max="0" value="0" step="0.1">
          <span id="trackTime" class="trackTime">0:00 / 0:00</span>
          <select id="playSpeed" class="trackSelect">
            <option value="1">1×</option>
            <option value="2">2×</option>
            <option value="5">5×</option>
            <option value="10">10×</option>
          </select>
        </div>
      </div>
    </div>
  </div>
</section>
<script>
const $ = (id) => document.getElementById(id);
const val = (v, unit = "", digits = 0) => v === null || v === undefined ? "—" : Number(v).toFixed(digits) + unit;
const setText = (id, text) => { const e = $(id); if (e) e.textContent = text; };
const setLevel = (e, level) => {
  if (!e) return;
  e.classList.toggle("mid", level === "mid");
  e.classList.toggle("low", level === "low");
};
const bar = (id, pct, textId) => {
  const e = $(id); if (!e) return;
  const has = pct !== null && pct !== undefined && isFinite(pct);
  pct = has ? Math.max(0, Math.min(100, pct)) : 0;
  e.style.width = pct + "%";
  const level = !has ? "" : pct < 35 ? "low" : pct < 70 ? "mid" : "";
  setLevel(e, level);
  if (textId) setLevel($(textId), level);
};
const rangeBar = (id, pct, textId) => {
  const e = $(id); if (!e) return;
  const has = pct !== null && pct !== undefined && isFinite(pct);
  pct = has ? Math.max(0, Math.min(100, pct)) : 0;
  e.style.width = pct + "%";
  const level = !has ? "" : pct > 80 ? "low" : pct > 40 ? "mid" : "";
  setLevel(e, level);
  if (textId) setLevel($(textId), level);
};
function rssi(v) { return v === null || v === undefined || v === 0 ? "—" : v + " dBm"; }
function snr(v) { return v === null || v === undefined ? "—" : v + " dB"; }


const ANDROID_SETTINGS = !!(window.AndroidSettings && window.AndroidSettings.getPermissions);

let currentSettings = null;

function applySettingsData(data) {
  if (!data) return;
  currentSettings = data;
  const port = $("udpPortInput");
  if (port) port.value = data.udp_port ?? "";
  const location = $("tracksLocation");
  if (location) {
    location.textContent = data.tracks_location || "—";
    location.title = data.tracks_uri || data.tracks_location || "";
  }
  const idle = $("idleReleaseMin");
  if (idle) idle.value = data.idle_release_min ?? "";
}

function setSettingsMsg(id, text, isError) {
  const el = $(id);
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("err", !!isError);
}

function applyDesktopSettings(data) {
  const rec = $("desktopAutoRecord3d");
  const stop = $("desktopAutoStop");
  if (rec) rec.checked = !!data.auto_record_3d;
  if (stop) stop.value = data.auto_stop_recording_sec ?? 10;
}

async function loadSettings() {
  const card = $("settingsCard");
  const desktop = $("desktopSettingsCard");
  if (!ANDROID_SETTINGS) {
    if (card) card.hidden = true;
    if (desktop) {
      desktop.hidden = false;
      try {
        const res = await fetch("/api/settings", { cache: "no-store" });
        if (res.ok) applyDesktopSettings(await res.json());
      } catch (e) {
      }
    }
    return;
  }
  if (!card) return;
  card.hidden = false;
  try {
    const res = await fetch("/api/settings", { cache: "no-store" });
    if (res.ok) applySettingsData(await res.json());
  } catch (e) {
  }
  await loadPermissions();
}

async function loadPermissions() {
  if (!ANDROID_SETTINGS) return;
  let data = {};
  try {
    data = JSON.parse(AndroidSettings.getPermissions());
  } catch (e) {
    data = {};
  }
  const list = $("permissionList");
  if (!list) return;
  list.innerHTML = "";
  const items = [
    { key: "notifications", label: t("permission_notifications"), action: "notifications" },
    { key: "battery", label: t("permission_battery"), action: "battery" },
    { key: "wifi", label: t("permission_wifi"), install: true },
    { key: "foreground", label: t("permission_foreground"), install: true },
  ];
  for (const item of items) {
    const ok = !!data[item.key];
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.className = "permName";
    name.textContent = item.label;
    const state = document.createElement("span");
    state.className = "permState " + (ok ? "ok" : "bad");
    state.textContent = ok ? (item.install ? t("perm_install") : t("perm_granted")) : t("perm_denied");
    li.appendChild(name);
    li.appendChild(state);
    if (!ok && !item.install) {
      const btn = document.createElement("button");
      btn.className = "mapBtn permBtn";
      btn.textContent = t("allow");
      btn.addEventListener("click", () => {
        if (item.action === "notifications") AndroidSettings.requestNotifications();
        else AndroidSettings.requestBatteryOptimization();
      });
      li.appendChild(btn);
    }
    list.appendChild(li);
  }
}

window.onNativeSettingsChanged = function () {
  loadSettings();
  if (typeof refreshTracks === "function") refreshTracks();
};

const I18N = {
  en: {
    page_title: "ELRS Backpack Telemetry",
    brand_sub: "Wi-Fi telemetry",
    status_wait: "waiting for data",
    status_online: "online · {pps} pkt/s",
    status_online_short: "{pps} pkt/s",
    status_link_down: "link down · {pps} pkt/s",
    status_link_down_short: "link down",
    status_no_data: "no data",
    status_no_data_short: "—",
    status_stale: "no data · {age} s",
    status_stale_short: "{age} s",
    status_no_server: "no connection to server",
    open_in_maps: "Open in the Maps app",
    card_link: "Link",
    lq_uplink: "Uplink LQ",
    lq_downlink: "Downlink LQ",
    rssi: "RSSI",
    snr: "SNR",
    tx_power: "TX power",
    antenna: "Antenna",
    band: "Band",
    packet_rate: "Packet rate",
    range: "Range",
    band_dual: "Dual",
    tab_telemetry: "Telemetry",
    tab_map: "Map",
    follow: "Follow",
    track: "Track",
    record: "Record",
    stop: "Stop",
    recording: "Recording",
    load: "Load",
    delete: "Delete",
    play: "Play",
    pause: "Pause",
    points: "pts",
    no_tracks: "No tracks",
    delete_confirm: "Delete this track?",
    center: "Center",
    no_gps: "No GPS fix",
    map_load_error: "Failed to load map",

    settings: "Settings",
    udp_port: "UDP listen port",
    apply: "Apply",
    settings_saved: "Saved",
    auto_stop_recording_error: "Enter 0..3600 seconds",
    mav_heartbeat: "Heartbeat",
    mav_armed: "Armed",
    mav_messages_per_sec: "Messages/s",
    mav_messages_total: "Messages",
    mavlink_loss: "MAVLink loss",
    mavlink_messages: "MAVLink messages",
    mav_h_acc: "H accuracy",
    mav_armed_yes: "yes",
    mav_armed_no: "no",
    mav_alive: "alive",
    udp_port_note: "The backpack must send telemetry to this port.",
    idle_release: "Release locks when no data (min)",
    idle_release_note: "0 or empty — never release locks.",
    idle_release_saved: "Power saving timeout updated",
    idle_release_error: "Could not update timeout",
    tracks_location: "Track storage",
    choose_folder: "Choose folder",
    reset_folder: "Reset",
    tracks_note: "Existing tracks are copied to the new folder.",
    permissions: "Permissions",
    check_again: "Check again",
    app_settings: "App settings",
    permissions_note: "Install-time permissions are granted automatically; notifications and battery exemption are requested on first launch.",
    support_text: "You can thank the author for the tokens and time spent on the Rutube channel",
    close_app: "Close app",
    close_recording_confirm: "Track recording is in progress. If you close the app, recording will be interrupted and will not be saved. Close?",
    permission_notifications: "Notifications",
    permission_battery: "Unrestricted background (battery)",
    permission_wifi: "Wi-Fi / multicast / wake lock",
    permission_foreground: "Foreground service",
    perm_granted: "granted",
    perm_denied: "not granted",
    perm_install: "granted at install",
    allow: "Allow",
    permissions_refreshed: "Updated",
    udp_port_saved: "Port updated",
    udp_port_error: "Could not change port",
    guide_title: "Quick setup guide",
    guide_methods: "Two ways to receive telemetry",
    guide_method_wifi: "Wi-Fi — default. No extra hardware: the backpack starts an access point or joins your network.",
    guide_method_usb: "ESP-NOW via USB — recommended. Less RF pollution. Needs an ESP32-C3/ESP32-S3 native-USB dongle and the serial bridge.",
    guide_wifi: "Wi-Fi setup",
    guide_wifi_1: "In EdgeTX open ELRS Lua → Backpack → Telemetry and select “WiFi”. Do not use “WiFi Connectivity” — it configures the transmitter.",
    guide_wifi_2: "Connect the computer to the “ExpressLRS TX Backpack XXXXXX” access point (password expresslrs) or to the same network as the backpack.",
    guide_wifi_3: "Start the viewer: python3 tlm_viewer.py",
    guide_wifi_4: "Open http://localhost:8080 and wait for the green online status and growing packet counters.",
    guide_espnow: "ESP-NOW via USB setup",
    guide_espnow_1: 'Flash the <a href="https://github.com/voffmail/ELRS-Backpack-Telemetry#dongle-firmware-and-web-flasher" target="_blank" rel="noopener noreferrer">ESP32-C3/ESP32-S3</a> native-USB dongle with esp32-c3-usb-otg or esp32-s3-usb-otg via the <a href="https://voffmail.github.io/ELRS-Backpack-Telemetry/" target="_blank" rel="noopener noreferrer">Web Flasher</a> or PlatformIO.',
    guide_espnow_2: "In EdgeTX set: ELRS Lua → Backpack → Telemetry → ESP-NOW.",
    guide_espnow_3: "Connect the dongle to the computer and find its serial port (/dev/ttyACM0, COMx, …).",
    guide_espnow_4: "Start the viewer and the bridge: python3 tools/serial_bridge.py --serial /dev/ttyACM0 --udp 127.0.0.1:14550",
    guide_espnow_5: "For phrase/UID, stop the bridge and use tools/dongle_config.py --port <port> --show or --phrase/--uid.",
    guide_problems: "Possible problems",
    guide_problem_nodata_python: "No Wi-Fi data? Check Telemetry → WiFi, the shared network, the firewall, and UDP port 14550.",
    guide_problem_port_python: "Port 14550 busy? Start the viewer with --udp-port <port> and the bridge with --udp 127.0.0.1:<port>.",
    guide_problem_usb_python: "No USB data? Check the serial port, data cable, permissions, and that tools/serial_bridge.py is running.",
    guide_problem_bridge_port: "Bridge and viewer ports must match; only one process can open the serial port.",
    guide_problem_vendor: "Some vendors' access point does not start; a backpack firmware from master may help.",
    guide_flash_title: "Backpack flashing",
    guide_flash_1: "Flashing is needed if the backpack does not start Wi-Fi/ESP-NOW or the menu item is missing. Flash via ExpressLRS Configurator → Backpack.",
    guide_flash_2: "Binding phrase is optional for Wi-Fi telemetry: the viewer does not check the UID.",
    guide_flash_3: "For ESP-NOW the phrase produces the UID and ESP-NOW group address; use the same phrase as your ELRS link or set a manual UID in the dongle settings.",
    guide_flash_4: "Without a phrase the backpack uses the EEPROM group address (after binding) or leaves it zero; Wi-Fi telemetry still works. The AP password is always expresslrs.",
    guide_flash_5: "Changing the phrase changes the UID and SSID — reflash all devices in the group with the same phrase.",
    guide_flash_link: "Tx Backpack Setup — ExpressLRS",
    guide_viewer: "Viewer",
    guide_viewer_1: "Open http://localhost:8080 (or the computer IP) in a browser.",
    guide_viewer_2: "Stop the viewer and the bridge with Ctrl+C in their terminals.",
    guide_viewer_3: "The map requires internet access. Map tiles come from OpenStreetMap, OpenFreeMap, Esri and Sentinel-2; no API key is needed.",
    save: "Save",
    card_battery: "Battery",
    current: "Current",
    capacity: "Capacity",
    remaining: "Remaining",
    card_gps: "GPS",
    satellites: "satellites",
    latitude: "Latitude",
    longitude: "Longitude",
    altitude: "Altitude",
    speed: "Speed",
    heading: "Heading",
    fix: "Fix",
    hdop: "HDOP",
    show_on_map: "Show on map",
    fix_none: "none",
    fix_type: "type {n}",
    card_flight: "Flight",
    baro_alt: "Baro altitude",
    vario: "Vario",
    gps_time: "GPS time",
    device: "Device",
    card_attitude: "Attitude",
    pitch: "Pitch",
    roll: "Roll",
    yaw: "Yaw",
    card_rx: "Reception",
    packets_per_sec: "Packets/s",
    packets_total: "Total packets",
    data_age: "Data age",
    frame_types: "Frame types",
    crsf_frame_types: "CRSF frame types",
    th_type: "Type",
    th_frame: "Frame",
    th_packets: "Packets",
    th_contains: "Contains",
    no_frames: "no frames yet",
    unknown_frame: "Unknown",
    not_described: "frame not described in the viewer",
    no_data: "no data",
    last_known: "last known",
    mode_failsafe: "failsafe",
    mode_blocked: "arming blocked",
    mode_gps_rescue_off: "arming possible, but GPS Rescue is disabled",
    mode_ready: "ready to arm",
    mode_armed: "armed",
    u_v: "V",
    u_a: "A",
    u_mah: "mAh",
    u_m: "m",
    u_kmh: "km/h",
    u_ms: "m/s",
    u_mw: "mW",
    u_s: "s",
    frames: {
      0x02: ["GPS", "Coordinates, speed, heading, altitude and satellites"],
      0x03: ["GPS Time", "Date and time from GPS"],
      0x06: ["GPS Extended", "Fix type, N/E/V speeds, accuracy and DOP"],
      0x07: ["Vario", "Vertical speed (variometer)"],
      0x08: ["Battery", "Voltage, current, consumed capacity, remaining %"],
      0x09: ["Baro Altitude", "Barometric altitude and vario"],
      0x0B: ["Heartbeat", "Device heartbeat"],
      0x11: ["Baro", "Raw pressure and temperature"],
      0x12: ["Mag", "Magnetometer (compass) data"],
      0x13: ["AccGyro", "Raw accelerometer and gyroscope data"],
      0x14: ["Link Statistics", "Link quality: LQ, RSSI, SNR, TX power"],
      0x16: ["RC Channels", "RC channels packet"],
      0x17: ["Subset RC Channels", "Reduced RC channels packet"],
      0x1C: ["Link Statistics RX", "Link statistics from the receiver side"],
      0x1D: ["Link Statistics TX", "Link statistics from the transmitter side"],
      0x1E: ["Attitude", "Orientation: pitch, roll, yaw"],
      0x21: ["Flight Mode", "Text flight mode"],
      0x29: ["Device Info", "Device name, versions and parameters"],
      0x2B: ["Parameter Settings Entry", "Device parameter description"],
      0x2C: ["Parameter Read", "Read parameter"],
      0x2D: ["Parameter Write", "Write parameter"],
      0x32: ["Command", "Command to device"],
      0x7A: ["MSP Request", "MSP request"],
      0x7B: ["MSP Response", "MSP response"],
      0x7C: ["MSP Write", "MSP write"],
      0x7D: ["DisplayPort", "OSD/DisplayPort exchange"]
    }
  },
  ru: {
    page_title: "ELRS Backpack Telemetry",
    brand_sub: "телеметрия по Wi-Fi",
    status_wait: "нет данных",
    status_online: "онлайн · {pps} пак/с",
    status_online_short: "{pps} пак/с",
    status_link_down: "нет связи · {pps} пак/с",
    status_link_down_short: "нет связи",
    status_no_data: "нет данных",
    status_no_data_short: "—",
    status_stale: "нет данных · {age} с",
    status_stale_short: "{age} с",
    status_no_server: "нет связи с сервером",
    open_in_maps: "Открыть в приложении навигации",
    card_link: "Линк",
    lq_uplink: "LQ up",
    lq_downlink: "LQ down",
    rssi: "RSSI",
    snr: "SNR",
    tx_power: "Мощность TX",
    antenna: "Антенна",
    band: "Диапазон",
    packet_rate: "Пакетрейт",
    range: "Дальность",
    band_dual: "Dual",
    tab_telemetry: "Телеметрия",
    tab_map: "Карта",
    follow: "Следовать",
    track: "Трек",
    record: "Запись",
    stop: "Стоп",
    recording: "Запись",
    load: "Загрузить",
    delete: "Удалить",
    play: "Играть",
    pause: "Пауза",
    points: "точек",
    no_tracks: "Нет треков",
    delete_confirm: "Удалить этот трек?",
    center: "Центрировать",
    no_gps: "Нет GPS-фикса",
    map_load_error: "Не удалось загрузить карту",

    settings: "Настройки",
    udp_port: "UDP-порт прослушивания",
    apply: "Применить",
    settings_saved: "Сохранено",
    auto_stop_recording_error: "Введите 0..3600 секунд",
    mav_heartbeat: "Heartbeat",
    mav_armed: "Armed",
    mav_messages_per_sec: "Сообщений/с",
    mav_messages_total: "Сообщений",
    mavlink_loss: "Потери MAVLink",
    mavlink_messages: "Сообщения MAVLink",
    mav_h_acc: "Точность H",
    mav_armed_yes: "да",
    mav_armed_no: "нет",
    mav_alive: "жив",
    udp_port_note: "Бэкпак должен отправлять телеметрию на этот порт.",
    idle_release: "Отпускать блокировки при отсутствии данных, мин",
    idle_release_note: "0 или пусто — никогда не отпускать блокировки.",
    idle_release_saved: "Таймаут энергосбережения обновлён",
    idle_release_error: "Не удалось изменить таймаут",
    tracks_location: "Расположение треков",
    choose_folder: "Выбрать папку",
    reset_folder: "Сбросить",
    tracks_note: "Существующие треки копируются в новую папку.",
    permissions: "Разрешения",
    check_again: "Проверить снова",
    app_settings: "Настройки приложения",
    permissions_note: "Разрешения уровня установки выдаются автоматически; уведомления и исключение из оптимизации батареи запрашиваются при первом запуске.",
    support_text: "Вы можете отблагодарить автора за потраченные токены и время на Rutube-канале",
    close_app: "Закрыть приложение",
    close_recording_confirm: "Идёт запись трека. Если закрыть приложение, запись будет прервана и не сохранится. Закрыть?",
    permission_notifications: "Уведомления",
    permission_battery: "Работа в фоне без ограничений (батарея)",
    permission_wifi: "Wi-Fi / multicast / wake lock",
    permission_foreground: "Foreground-сервис",
    perm_granted: "разрешено",
    perm_denied: "не разрешено",
    perm_install: "разрешено при установке",
    allow: "Разрешить",
    permissions_refreshed: "Обновлено",
    udp_port_saved: "Порт обновлён",
    udp_port_error: "Не удалось изменить порт",
    guide_title: "Краткое руководство",
    guide_methods: "Два способа получения телеметрии",
    guide_method_wifi: "Wi-Fi — по умолчанию. Дополнительное железо не нужно: бэкпак поднимает точку доступа или подключается к вашей сети.",
    guide_method_usb: "ESP-NOW по USB — рекомендуется. Меньше засорения эфира. Нужен приемник ESP-NOW на ESP32-C3/ESP32-S3 с native USB и serial-мост.",
    guide_wifi: "Настройка Wi-Fi",
    guide_wifi_1: "В EdgeTX откройте ELRS Lua → Backpack → Telemetry и выберите «WiFi». Не используйте «WiFi Connectivity» — это режим настройки передатчика.",
    guide_wifi_2: "Подключите компьютер к точке «ExpressLRS TX Backpack XXXXXX» (пароль expresslrs) или к той же сети, что и бэкпак.",
    guide_wifi_3: "Запустите вьюер: python3 tlm_viewer.py",
    guide_wifi_4: "Откройте http://localhost:8080 и дождитесь зелёного статуса «онлайн» и роста пакетов.",
    guide_espnow: "Настройка ESP-NOW по USB",
    guide_espnow_1: 'Прошейте <a href="https://github.com/voffmail/ELRS-Backpack-Telemetry#прошивка-usb-приемника-esp-now-и-web-flasher" target="_blank" rel="noopener noreferrer">ESP32-C3/ESP32-S3</a> с native USB прошивкой esp32-c3-usb-otg или esp32-s3-usb-otg через <a href="https://voffmail.github.io/ELRS-Backpack-Telemetry/" target="_blank" rel="noopener noreferrer">Web Flasher</a> или PlatformIO.',
    guide_espnow_2: "В EdgeTX задайте: ELRS Lua → Backpack → Telemetry → ESP-NOW.",
    guide_espnow_3: "Подключите приемник ESP-NOW к компьютеру и найдите его serial-порт (/dev/ttyACM0, COMx, …).",
    guide_espnow_4: "Запустите вьюер и мост: python3 tools/serial_bridge.py --serial /dev/ttyACM0 --udp 127.0.0.1:14550",
    guide_espnow_5: "Для phrase/UID остановите мост и используйте tools/dongle_config.py --port <port> --show или --phrase/--uid.",
    guide_problems: "Возможные проблемы",
    guide_problem_nodata_python: "Нет данных по Wi-Fi? Проверьте Telemetry → WiFi, общую сеть, firewall и UDP-порт 14550.",
    guide_problem_port_python: "Порт 14550 занят? Запустите вьюер с --udp-port <port>, а мост с --udp 127.0.0.1:<port>.",
    guide_problem_usb_python: "Нет данных по USB? Проверьте serial-порт, data-кабель, права доступа и что tools/serial_bridge.py запущен.",
    guide_problem_bridge_port: "Порты моста и вьюера должны совпадать; serial-порт может занимать только один процесс.",
    guide_problem_vendor: "У некоторых вендоров не стартует точка доступа; может помочь прошивка бэкпака из master.",
    guide_flash_title: "Прошивка бэкпака",
    guide_flash_1: "Прошивка нужна, если бэкпак не поднимает Wi-Fi/ESP-NOW или в меню нет нужного пункта. Прошивать через ExpressLRS Configurator → Backpack.",
    guide_flash_2: "Для Wi-Fi-телеметрии binding phrase не обязательна: вьюер не проверяет UID.",
    guide_flash_3: "Для ESP-NOW фраза задаёт UID и адрес ESP-NOW-группы; используйте ту же фразу, что в ELRS-линии, либо задайте UID вручную в настройках приемника ESP-NOW.",
    guide_flash_4: "Без фразы бэкпак возьмёт адрес из EEPROM (после бинда) или оставит нулевым; Wi-Fi-телеметрия всё равно работает. Пароль точки доступа всегда expresslrs.",
    guide_flash_5: "При смене фразы меняются UID и SSID — перепрошейте с той же фразой все устройства группы.",
    guide_flash_link: "Прошивка TX Backpack — ExpressLRS",
    guide_viewer: "Вьюер",
    guide_viewer_1: "Откройте http://localhost:8080 (или IP компьютера) в браузере.",
    guide_viewer_2: "Остановите вьюер и мост через Ctrl+C в их терминалах.",
    guide_viewer_3: "Для карты нужен интернет. Тайлы берутся из OpenStreetMap, OpenFreeMap, Esri и Sentinel-2; ключ не нужен.",
    save: "Сохранить",
    card_battery: "Батарея",
    current: "Ток",
    capacity: "Ёмкость",
    remaining: "Остаток",
    card_gps: "GPS",
    satellites: "спутников",
    latitude: "Широта",
    longitude: "Долгота",
    altitude: "Высота",
    speed: "Скорость",
    heading: "Курс",
    fix: "Фикс",
    hdop: "HDOP",
    show_on_map: "Показать на карте",
    fix_none: "нет",
    fix_type: "тип {n}",
    card_flight: "Полёт",
    baro_alt: "Барo высота",
    vario: "Варио",
    gps_time: "GPS время",
    device: "Устройство",
    card_attitude: "Ориентация",
    pitch: "Тангаж",
    roll: "Крен",
    yaw: "Рыскание",
    card_rx: "Приём",
    packets_per_sec: "Пакетов/с",
    packets_total: "Всего пакетов",
    data_age: "Возраст данных",
    frame_types: "Типы кадров",
    crsf_frame_types: "Типы CRSF-кадров",
    th_type: "Тип",
    th_frame: "Кадр",
    th_packets: "Пакетов",
    th_contains: "Что содержит",
    no_frames: "кадров пока нет",
    unknown_frame: "Неизвестный",
    not_described: "кадр не описан в просмотрщике",
    no_data: "нет данных",
    last_known: "последняя известная",
    mode_failsafe: "failsafe",
    mode_blocked: "арминг заблокирован",
    mode_gps_rescue_off: "арминг возможен, но GPS Rescue отключён",
    mode_ready: "готов к армингу",
    mode_armed: "взведён",
    u_v: "В",
    u_a: "А",
    u_mah: "мА·ч",
    u_m: "м",
    u_kmh: "км/ч",
    u_ms: "м/с",
    u_mw: "мВт",
    u_s: "с",
    frames: {
      0x02: ["GPS", "Координаты, скорость, курс, высота и число спутников"],
      0x03: ["GPS Time", "Дата и время от GPS"],
      0x06: ["GPS Extended", "Тип фикса, скорости N/E/V, точность и DOP"],
      0x07: ["Vario", "Вертикальная скорость (вариометр)"],
      0x08: ["Battery", "Напряжение, ток, израсходованная ёмкость, остаток %"],
      0x09: ["Baro Altitude", "Барометрическая высота и варио"],
      0x0B: ["Heartbeat", "Признак жизни устройства"],
      0x11: ["Baro", "Сырое давление и температура барометра"],
      0x12: ["Mag", "Данные магнитометра (компас)"],
      0x13: ["AccGyro", "Сырые данные акселерометра и гироскопа"],
      0x14: ["Link Statistics", "Качество линка: LQ, RSSI, SNR, мощность TX"],
      0x16: ["RC Channels", "Пакет каналов управления"],
      0x17: ["Subset RC Channels", "Сокращённый пакет каналов управления"],
      0x1C: ["Link Statistics RX", "Статистика линка со стороны приёмника"],
      0x1D: ["Link Statistics TX", "Статистика линка со стороны передатчика"],
      0x1E: ["Attitude", "Ориентация: тангаж, крен, рыскание"],
      0x21: ["Flight Mode", "Текстовый режим полёта"],
      0x29: ["Device Info", "Имя, версии и параметры устройства"],
      0x2B: ["Parameter Settings Entry", "Описание параметра устройства"],
      0x2C: ["Parameter Read", "Чтение параметра"],
      0x2D: ["Parameter Write", "Запись параметра"],
      0x32: ["Command", "Команда устройству"],
      0x7A: ["MSP Request", "MSP-запрос"],
      0x7B: ["MSP Response", "MSP-ответ"],
      0x7C: ["MSP Write", "MSP-запись"],
      0x7D: ["DisplayPort", "Обмен с OSD/DisplayPort"]
    }
  },
  zh: {
    page_title: "ELRS Backpack Telemetry",
    brand_sub: "Wi-Fi 遥测",
    status_wait: "等待数据",
    status_online: "在线 · {pps} 包/秒",
    status_online_short: "{pps} 包/秒",
    status_link_down: "链路断开 · {pps} 包/秒",
    status_link_down_short: "链路断开",
    status_no_data: "无数据",
    status_no_data_short: "—",
    status_stale: "无数据 · {age} 秒",
    status_stale_short: "{age} 秒",
    status_no_server: "无法连接到服务器",
    open_in_maps: "在地图应用中打开",
    card_link: "链路",
    lq_uplink: "上行 LQ",
    lq_downlink: "下行 LQ",
    rssi: "RSSI",
    snr: "SNR",
    tx_power: "发射功率",
    antenna: "天线",
    band: "频段",
    packet_rate: "包速率",
    range: "距离",
    band_dual: "双频",
    tab_telemetry: "遥测",
    tab_map: "地图",
    follow: "跟随",
    track: "轨迹",
    record: "录制",
    stop: "停止",
    recording: "录制中",
    load: "加载",
    delete: "删除",
    play: "播放",
    pause: "暂停",
    points: "点",
    no_tracks: "暂无轨迹",
    delete_confirm: "删除此轨迹？",
    center: "居中",
    no_gps: "无 GPS 定位",
    map_load_error: "地图加载失败",

    settings: "设置",
    udp_port: "UDP 监听端口",
    apply: "应用",
    settings_saved: "已保存",
    auto_stop_recording_error: "请输入 0..3600 秒",
    mav_heartbeat: "心跳",
    mav_armed: "已解锁",
    mav_messages_per_sec: "消息/秒",
    mav_messages_total: "消息数",
    mavlink_loss: "MAVLink 丢包",
    mavlink_messages: "MAVLink 消息",
    mav_h_acc: "水平精度",
    mav_armed_yes: "是",
    mav_armed_no: "否",
    mav_alive: "正常",
    udp_port_note: "背包必须将遥测发送到此端口。",
    idle_release: "无数据时释放锁（分钟）",
    idle_release_note: "0 或留空 — 永不释放锁。",
    idle_release_saved: "节能超时已更新",
    idle_release_error: "无法更新超时",
    tracks_location: "轨迹存储",
    choose_folder: "选择文件夹",
    reset_folder: "重置",
    tracks_note: "现有轨迹会复制到新文件夹。",
    permissions: "权限",
    check_again: "重新检查",
    app_settings: "应用设置",
    permissions_note: "安装时权限会自动授予；通知和电池优化豁免会在首次启动时请求。",
    support_text: "感谢作者为此花费的 token 和时间，欢迎访问 Rutube 频道",
    close_app: "关闭应用",
    close_recording_confirm: "正在录制轨迹。关闭应用将中断录制且不会保存。是否关闭？",
    permission_notifications: "通知",
    permission_battery: "后台无限制（电池）",
    permission_wifi: "Wi-Fi / 多播 / 唤醒锁",
    permission_foreground: "前台服务",
    perm_granted: "已授予",
    perm_denied: "未授予",
    perm_install: "安装时已授予",
    allow: "允许",
    permissions_refreshed: "已更新",
    udp_port_saved: "端口已更新",
    udp_port_error: "无法更改端口",
    guide_title: "快速设置指南",
    guide_methods: "两种获取遥测的方式",
    guide_method_wifi: "Wi-Fi — 默认。无需额外硬件：背包会创建热点或加入你的网络。",
    guide_method_usb: "USB ESP-NOW — 推荐。减少无线电污染。需要带 native USB 的 ESP32-C3/ESP32-S3 适配器和串口桥。",
    guide_wifi: "Wi-Fi 设置",
    guide_wifi_1: "在 EdgeTX 中打开 ELRS Lua → Backpack → Telemetry，选择“WiFi”。不要使用“WiFi Connectivity”——那是配置遥控器。",
    guide_wifi_2: "将电脑连接到“ExpressLRS TX Backpack XXXXXX”热点（密码 expresslrs），或连接到与背包相同的网络。",
    guide_wifi_3: "启动查看器：python3 tlm_viewer.py",
    guide_wifi_4: "打开 http://localhost:8080，等待绿色“在线”状态和不断增长的包计数。",
    guide_espnow: "USB ESP-NOW 设置",
    guide_espnow_1: '通过 <a href="https://voffmail.github.io/ELRS-Backpack-Telemetry/" target="_blank" rel="noopener noreferrer">Web Flasher</a> 或 PlatformIO 为带 native USB 的 <a href="https://github.com/voffmail/ELRS-Backpack-Telemetry#dongle-firmware-and-web-flasher" target="_blank" rel="noopener noreferrer">ESP32-C3/ESP32-S3</a> 刷写 esp32-c3-usb-otg 或 esp32-s3-usb-otg。',
    guide_espnow_2: "在 EdgeTX 中设置：ELRS Lua → Backpack → Telemetry → ESP-NOW。",
    guide_espnow_3: "将适配器连接到电脑，并找到其串口（/dev/ttyACM0、COMx 等）。",
    guide_espnow_4: "启动查看器和桥接：python3 tools/serial_bridge.py --serial /dev/ttyACM0 --udp 127.0.0.1:14550",
    guide_espnow_5: "设置 phrase/UID 时，先停止桥接，再使用 tools/dongle_config.py --port <port> --show 或 --phrase/--uid。",
    guide_problems: "可能的问题",
    guide_problem_nodata_python: "Wi-Fi 没有数据？检查 Telemetry → WiFi、同一网络、防火墙，以及 UDP 端口 14550。",
    guide_problem_port_python: "端口 14550 被占用？查看器使用 --udp-port <port> 启动，桥接使用 --udp 127.0.0.1:<port>。",
    guide_problem_usb_python: "USB 没有数据？检查串口、数据线、权限，以及 tools/serial_bridge.py 是否在运行。",
    guide_problem_bridge_port: "桥接和查看器的端口必须一致；串口只能被一个进程占用。",
    guide_problem_vendor: "部分厂商的热点无法启动；可尝试 master 分支的背包固件。",
    guide_flash_title: "背包刷写",
    guide_flash_1: "如果背包无法启动 Wi-Fi/ESP-NOW 或菜单中没有相应项目，则需要刷写。通过 ExpressLRS Configurator → Backpack 刷写。",
    guide_flash_2: "Wi-Fi 遥测不要求绑定短语：查看器不校验 UID。",
    guide_flash_3: "ESP-NOW 使用该短语生成 UID 和 ESP-NOW 组地址；请使用与 ELRS 链路相同的短语，或在适配器设置中手动设置 UID。",
    guide_flash_4: "如果不设置短语，背包会使用 EEPROM 中的组地址（绑定后）或保持为零；Wi-Fi 遥测仍然可用。热点密码始终是 expresslrs。",
    guide_flash_5: "更改短语会改变 UID 和 SSID——请用相同短语重新刷写组内所有设备。",
    guide_flash_link: "TX Backpack 刷写 — ExpressLRS",
    guide_viewer: "查看器",
    guide_viewer_1: "在浏览器中打开 http://localhost:8080（或电脑 IP）。",
    guide_viewer_2: "在各自终端中按 Ctrl+C 停止查看器和桥接。",
    guide_viewer_3: "地图需要互联网。瓦片来自 OpenStreetMap、OpenFreeMap、Esri 和 Sentinel-2，无需密钥。",
    save: "保存",
    card_battery: "电池",
    current: "电流",
    capacity: "容量",
    remaining: "剩余",
    card_gps: "GPS",
    satellites: "卫星",
    latitude: "纬度",
    longitude: "经度",
    altitude: "高度",
    speed: "速度",
    heading: "航向",
    fix: "定位",
    hdop: "HDOP",
    show_on_map: "在地图上显示",
    fix_none: "无",
    fix_type: "类型 {n}",
    card_flight: "飞行",
    baro_alt: "气压高度",
    vario: "升降速度",
    gps_time: "GPS 时间",
    device: "设备",
    card_attitude: "姿态",
    pitch: "俯仰",
    roll: "横滚",
    yaw: "偏航",
    card_rx: "接收",
    packets_per_sec: "包/秒",
    packets_total: "总包数",
    data_age: "数据延迟",
    frame_types: "帧类型",
    crsf_frame_types: "CRSF 帧类型",
    th_type: "类型",
    th_frame: "帧",
    th_packets: "包数",
    th_contains: "内容",
    no_frames: "暂无帧",
    unknown_frame: "未知",
    not_described: "查看器未描述该帧",
    no_data: "无数据",
    last_known: "最后已知",
    mode_failsafe: "失控保护",
    mode_blocked: "解锁被阻止",
    mode_gps_rescue_off: "可以解锁，但 GPS 救援已禁用",
    mode_ready: "可以解锁",
    mode_armed: "已解锁",
    u_v: "伏",
    u_a: "安",
    u_mah: "毫安时",
    u_m: "米",
    u_kmh: "公里/小时",
    u_ms: "米/秒",
    u_mw: "毫瓦",
    u_s: "秒",
    frames: {
      0x02: ["GPS", "坐标、速度、航向、高度和卫星数量"],
      0x03: ["GPS Time", "GPS 日期和时间"],
      0x06: ["GPS Extended", "定位类型、N/E/V 速度、精度和 DOP"],
      0x07: ["Vario", "垂直速度（升降计）"],
      0x08: ["Battery", "电压、电流、已用电量和剩余 %"],
      0x09: ["Baro Altitude", "气压高度和升降速度"],
      0x0B: ["Heartbeat", "设备心跳"],
      0x11: ["Baro", "原始气压和温度"],
      0x12: ["Mag", "磁力计（指南针）数据"],
      0x13: ["AccGyro", "原始加速度计和陀螺仪数据"],
      0x14: ["Link Statistics", "链路质量：LQ、RSSI、SNR、发射功率"],
      0x16: ["RC Channels", "遥控通道数据包"],
      0x17: ["Subset RC Channels", "精简遥控通道数据包"],
      0x1C: ["Link Statistics RX", "接收端链路统计"],
      0x1D: ["Link Statistics TX", "发射端链路统计"],
      0x1E: ["Attitude", "姿态：俯仰、横滚、偏航"],
      0x21: ["Flight Mode", "文本飞行模式"],
      0x29: ["Device Info", "设备名称、版本和参数"],
      0x2B: ["Parameter Settings Entry", "设备参数说明"],
      0x2C: ["Parameter Read", "读取参数"],
      0x2D: ["Parameter Write", "写入参数"],
      0x32: ["Command", "设备命令"],
      0x7A: ["MSP Request", "MSP 请求"],
      0x7B: ["MSP Response", "MSP 响应"],
      0x7C: ["MSP Write", "MSP 写入"],
      0x7D: ["DisplayPort", "OSD/DisplayPort 交换"]
    }
  }
};

let LANG = "en";

function t(key, vars) {
  const table = I18N[LANG] || I18N.en;
  let text = table[key];
  if (text === undefined) text = I18N.en[key];
  if (text === undefined) text = key;
  if (vars) {
    for (const name in vars) text = text.split("{" + name + "}").join(vars[name]);
  }
  return text;
}

function frameInfo(type) {
  const table = (I18N[LANG] && I18N[LANG].frames) || {};
  return table[type] || I18N.en.frames[type];
}

const TX_POWER_MW = {0: 0, 1: 10, 2: 25, 3: 100, 4: 500, 5: 1000, 6: 2000, 7: 250, 8: 50};

const RF_MODES = {
  0: ["900", "25 Hz", -123],
  1: ["900", "50 Hz", -120],
  2: ["900", "100 Hz", -117],
  3: ["900", "100 Hz/8ch", -112],
  4: ["900", "150 Hz", null],
  5: ["900", "200 Hz", -112],
  6: ["900", "200 Hz/8ch", -111],
  7: ["900", "250 Hz", -111],
  8: ["900", "333 Hz/8ch", null],
  9: ["900", "500 Hz", null],
  10: ["900", "50 Hz DVDA", -112],
  11: ["900", "FSK 1000 Hz/8ch", -101],
  20: ["24", "25 Hz", null],
  21: ["24", "50 Hz", -115],
  22: ["24", "100 Hz", null],
  23: ["24", "100 Hz/8ch", -112],
  24: ["24", "150 Hz", -112],
  25: ["24", "200 Hz", null],
  26: ["24", "200 Hz/8ch", null],
  27: ["24", "250 Hz", -108],
  28: ["24", "333 Hz/8ch", -105],
  29: ["24", "500 Hz", -105],
  30: ["24", "FLRC 250 DVDA", -104],
  31: ["24", "FLRC 500 DVDA", -104],
  32: ["24", "FLRC 500", -104],
  33: ["24", "FLRC 1000", -104],
  34: ["24", "FSK 250 DVDA", -103],
  35: ["24", "FSK 500 DVDA", -103],
  36: ["24", "FSK 1000", -103],
  100: ["dual", "100 Hz/8ch", -112],
  101: ["dual", "150 Hz", -112]
};

let rangeSmooth = null;
let rangeMode = null;

function bandText(band) {
  if (band === "dual") return t("band_dual");
  return band === "900" ? "900 MHz" : "2.4 GHz";
}

function pickLang() {
  const query = new URLSearchParams(location.search).get("lang");
  if (query && I18N[query]) return query;
  const saved = localStorage.getItem("tlm_lang");
  if (saved && I18N[saved]) return saved;
  const nav = (navigator.language || "en").toLowerCase();
  if (nav.indexOf("ru") === 0) return "ru";
  if (nav.indexOf("zh") === 0) return "zh";
  return "en";
}

function applyPlatformUi() {
  document.querySelectorAll("[data-platform]").forEach(el => {
    el.hidden = (el.getAttribute("data-platform") === "android") !== ANDROID_SETTINGS;
  });
}

function applyI18n() {
  document.documentElement.lang = LANG;
  document.title = t("page_title");
  document.querySelectorAll("[data-i18n]").forEach(el => {
    el.textContent = t(el.getAttribute("data-i18n"));
  });
  document.querySelectorAll("[data-i18n-html]").forEach(el => {
    el.innerHTML = t(el.getAttribute("data-i18n-html"));
  });
  $("lang").value = LANG;
  applyPlatformUi();
}

let mapObj = null;
let mapPlacemark = null;
let mapReady = false;
let mapLoading = false;
let mapResizeObserver = null;
let mapLastPos = null;
let mapLastGps = null;
let mapFollow = true;
let mapGpsLive = false;
let lastState = null;

let tracks = [];
let recordState = {};
let recordPointTotal = 0;
let lastRecordFetch = 0;
let currentTrack = null;
let currentTrackPoints = [];
let playbackMarker = null;
let lastPlaybackPos = null;
let playback = { playing: false, time: 0, speed: 1, last: 0, raf: 0 };

const PLAYBACK_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">' +
  '<circle cx="11" cy="11" r="8" fill="#58a6ff" stroke="#0b0f14" stroke-width="3"/></svg>';

const DRONE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">' +
  '<circle cx="24" cy="24" r="22" fill="rgba(63,185,80,0.18)"/>' +
  '<g stroke="#3fb950" stroke-width="3" stroke-linecap="round">' +
  '<path d="M24 24 13 13M24 24 35 13M24 24 13 35M24 24 35 35"/></g>' +
  '<g fill="#0b0f14" stroke="#3fb950" stroke-width="3">' +
  '<circle cx="12" cy="12" r="4.5"/><circle cx="36" cy="12" r="4.5"/>' +
  '<circle cx="12" cy="36" r="4.5"/><circle cx="36" cy="36" r="4.5"/></g>' +
  '<circle cx="24" cy="24" r="5" fill="#3fb950"/></svg>';

function mapVisible() {
  return !$("mapPage").hidden;
}

function showMapFailure() {
  const el = $("mapStatus");
  el.hidden = false;
  el.textContent = t("map_load_error");
}

function ensureMap() {
  if (mapObj) {
    setTimeout(refreshMapLayout, 30);
    return;
  }
  if (mapLoading) return;
  if (!window.maplibregl || !window.ELRS_MAP) {
    showMapFailure();
    return;
  }
  mapLoading = true;
  initMap();
}

function firstSymbolLayerId() {
  if (!mapObj) return undefined;
  const layers = mapObj.getStyle().layers || [];
  const symbol = layers.find(layer => layer.type === "symbol");
  return symbol ? symbol.id : undefined;
}

async function initMap() {
  if (mapObj) {
    mapLoading = false;
    return;
  }
  if (!window.maplibregl || !window.ELRS_MAP) {
    mapLoading = false;
    showMapFailure();
    return;
  }
  const g = mapLastGps && mapLastGps.fix ? mapLastGps : null;
  const center = g ? [g.lon, g.lat] : [37.618423, 55.751244];
  let style;
  try {
    style = await window.ELRS_MAP.loadStyle(LANG);
  } catch (e) {
    mapLoading = false;
    showMapFailure();
    return;
  }
  try {
    mapObj = new maplibregl.Map({
      container: "map",
      style: style,
      center: center,
      zoom: g ? 15 : 4
    });
  } catch (e) {
    mapLoading = false;
    showMapFailure();
    return;
  }
  mapObj.on("load", () => {
    try {
      mapObj.addSource("track", {
        type: "geojson",
        data: { type: "Feature", geometry: { type: "LineString", coordinates: [] } }
      });
      mapObj.addLayer({
        id: "track-line",
        type: "line",
        source: "track",
        paint: { "line-color": "#58a6ff", "line-width": 3, "line-opacity": 0.9 }
      }, firstSymbolLayerId());
    } catch (e) {
    }
    updateTrackLine();
    if (currentTrackPoints.length) {
      showPlaybackMarker();
      positionPlaybackMarker(playback.time);
    }
  });
  const icon = document.createElement("div");
  icon.className = "droneMarker";
  icon.innerHTML = DRONE_SVG;
  icon.style.display = g ? "block" : "none";
  mapPlacemark = new maplibregl.Marker({ element: icon, anchor: "center" })
    .setLngLat(g ? [g.lon, g.lat] : center)
    .addTo(mapObj);
  const pIcon = document.createElement("div");
  pIcon.className = "playbackMarker";
  pIcon.innerHTML = PLAYBACK_SVG;
  pIcon.style.display = "none";
  playbackMarker = new maplibregl.Marker({ element: pIcon, anchor: "center" })
    .setLngLat(center)
    .addTo(mapObj);
  mapReady = true;
  mapLoading = false;
  updateMap(mapLastGps, true);
  if (window.ResizeObserver && !mapResizeObserver) {
    mapResizeObserver = new ResizeObserver(() => {
      if (mapObj) mapObj.resize();
    });
    mapResizeObserver.observe($("map"));
  }
  [0, 100, 400, 1000].forEach(ms => setTimeout(refreshMapLayout, ms));
}

function fitMapHeight() {
  const mapPage = $("mapPage");
  if (!mapPage || mapPage.hidden) return;
  const wrap = document.querySelector(".mapWrap");
  if (!wrap) return;
  const style = getComputedStyle(mapPage);
  const padTop = parseFloat(style.paddingTop) || 0;
  const padBottom = parseFloat(style.paddingBottom) || 0;
  const pageTop = mapPage.getBoundingClientRect().top + window.scrollY + padTop;
  const available = Math.floor(window.innerHeight - pageTop - padBottom);
  if (available > 0) wrap.style.height = available + "px";
}

function refreshMapLayout() {
  fitMapHeight();
  if (!mapObj) return;
  try {
    mapObj.resize();
  } catch (e) {
  }
}

function updateMap(gps, force) {
  if (gps && gps.fix) mapLastGps = gps;
  const g = mapLastGps;
  const hasFix = !!(g && g.fix && Number.isFinite(g.lat) && Number.isFinite(g.lon));
  const stale = hasFix && !(mapGpsLive && gps && gps.fix);
  if (mapPlacemark) {
    const el = mapPlacemark.getElement();
    el.style.display = (hasFix && !currentTrack) ? "block" : "none";
    el.classList.toggle("stale", stale);
  }
  if (!mapReady) {
    setText("mapInfo", hasFix ? g.lat.toFixed(6) + ", " + g.lon.toFixed(6) + (stale ? " · " + t("last_known") : "") : "—");
    return;
  }
  if (hasFix) {
    const pos = [g.lat, g.lon];
    if (force || !mapLastPos || Math.abs(pos[0] - mapLastPos[0]) > 1e-7 || Math.abs(pos[1] - mapLastPos[1]) > 1e-7) {
      mapPlacemark.setLngLat([g.lon, g.lat]);
      mapLastPos = pos;
      if (mapFollow && mapVisible() && !currentTrack) {
        mapObj.easeTo({ center: [g.lon, g.lat], duration: 300 });
      }
    }
    $("mapStatus").hidden = !stale;
    if (stale) setText("mapStatus", t("last_known"));
    setText("mapInfo", g.lat.toFixed(6) + ", " + g.lon.toFixed(6) + " · " + g.sats + " " + t("satellites") + " · " + Number(g.speed || 0).toFixed(1) + " " + t("u_kmh") + (stale ? " · " + t("last_known") : ""));
  } else {
    $("mapStatus").hidden = false;
    setText("mapStatus", t("no_gps"));
    setText("mapInfo", "—");
  }
}

let lastQrData = null;
let lastQrGps = null;

function updateQr(g, last, wrapId = "gpsQrWrap", boxId = "gpsQr") {
  const wrap = $(wrapId);
  const box = $(boxId);
  if (!wrap || !box) return;
  if (g && g.fix && Number.isFinite(g.lat) && Number.isFinite(g.lon)) {
    lastQrGps = { lat: g.lat, lon: g.lon };
  }
  const src = (g && g.fix && Number.isFinite(g.lat) && Number.isFinite(g.lon)) ? g : (last || lastQrGps);
  if (!src) {
    wrap.hidden = true;
    return;
  }
  const data = "geo:0,0?q=" + src.lat.toFixed(6) + "," + src.lon.toFixed(6);
  if (typeof window.qrcode === "function") {
    if (data !== box.dataset.qrData) {
      const qr = qrcode(0, "M");
      qr.addData(data);
      qr.make();
      box.innerHTML = qr.createSvgTag({ cellSize: 3, margin: 1 });
      box.dataset.qrData = data;
    }
  } else {
    box.textContent = data;
    box.dataset.qrData = "";
  }
  wrap.title = t("open_in_maps");
  wrap.setAttribute("aria-label", t("open_in_maps"));
  wrap.hidden = false;
}

function openGpsInMaps() {
  if (!lastQrGps) return;
  const data = "geo:0,0?q=" + lastQrGps.lat.toFixed(6) + "," + lastQrGps.lon.toFixed(6);
  const a = document.createElement("a");
  a.href = data;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function fmtDur(sec) {
  sec = Math.max(0, Math.floor(Number(sec) || 0));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m + ":" + String(s).padStart(2, "0");
}

function updateTrackLine() {
  if (!mapObj || !mapObj.getSource("track")) return;
  try {
    mapObj.getSource("track").setData({
      type: "Feature",
      geometry: { type: "LineString", coordinates: currentTrackPoints.map(p => [p.lon, p.lat]) }
    });
  } catch (e) {
  }
}

function showPlaybackMarker() {
  if (playbackMarker) playbackMarker.getElement().style.display = "block";
}

function hidePlaybackMarker() {
  if (playbackMarker) playbackMarker.getElement().style.display = "none";
}

function pointAtTime(time) {
  const pts = currentTrackPoints;
  if (!pts.length) return null;
  if (time <= pts[0].t) return pts[0];
  if (time >= pts[pts.length - 1].t) return pts[pts.length - 1];
  let lo = 0;
  let hi = pts.length - 1;
  while (lo + 1 < hi) {
    const mid = (lo + hi) >> 1;
    if (pts[mid].t <= time) lo = mid; else hi = mid;
  }
  const a = pts[lo];
  const b = pts[hi];
  const span = b.t - a.t;
  const f = span > 0 ? (time - a.t) / span : 0;
  return { lat: a.lat + (b.lat - a.lat) * f, lon: a.lon + (b.lon - a.lon) * f };
}

function positionPlaybackMarker(time, follow) {
  const p = pointAtTime(time);
  if (!p || !playbackMarker) return;
  playbackMarker.setLngLat([p.lon, p.lat]);
  lastPlaybackPos = p;
  if (follow && mapFollow && mapVisible()) {
    mapObj.setCenter([p.lon, p.lat]);
  }
}

function updatePlaybackUI() {
  const dur = currentTrack ? Number(currentTrack.duration || 0) : 0;
  const loaded = !!currentTrack;
  const selected = !!$("trackSelect").value;
  const active = !!(recordState && recordState.active);
  $("trackActions").hidden = !selected;
  $("playRow").hidden = !loaded;
  $("deleteTrack").disabled = active || !selected;
  $("exportGpx").disabled = active || !loaded;
  $("exportKml").disabled = active || !loaded;
  const progress = $("trackProgress");
  progress.max = dur;
  progress.value = Math.min(playback.time, dur);
  progress.disabled = !loaded;
  $("trackTime").textContent = fmtDur(playback.time) + " / " + fmtDur(dur);
  $("playLabel").textContent = playback.playing ? t("pause") : t("play");
  $("playBtn").disabled = active || !loaded;
  $("playSpeed").disabled = !loaded;
}

function stopPlayback() {
  playback.playing = false;
  if (playback.raf) cancelAnimationFrame(playback.raf);
  playback.raf = 0;
  updatePlaybackUI();
}

function playbackStep(ts) {
  if (!playback.playing || !currentTrack) return;
  const dt = Math.max(0, (ts - playback.last) / 1000) * playback.speed;
  playback.last = ts;
  playback.time += dt;
  const dur = Number(currentTrack.duration || 0);
  if (playback.time >= dur) {
    playback.time = dur;
    playback.playing = false;
  }
  positionPlaybackMarker(playback.time, true);
  updatePlaybackUI();
  if (playback.playing) playback.raf = requestAnimationFrame(playbackStep);
}

function startPlayback() {
  if (!currentTrack || (recordState && recordState.active)) return;
  const dur = Number(currentTrack.duration || 0);
  if (playback.time >= dur) playback.time = 0;
  playback.playing = true;
  playback.last = performance.now();
  showPlaybackMarker();
  positionPlaybackMarker(playback.time, true);
  updatePlaybackUI();
  playback.raf = requestAnimationFrame(playbackStep);
}

async function fetchRecording(reset) {
  if (reset) {
    currentTrackPoints = [];
    recordPointTotal = 0;
    updateTrackLine();
  }
  let res;
  try {
    res = await fetch("/api/record?since=" + recordPointTotal);
  } catch (e) {
    return;
  }
  if (!res.ok) return;
  const data = await res.json();
  if (data.active) {
    currentTrackPoints = currentTrackPoints.concat(data.points || []);
    recordPointTotal = data.total || currentTrackPoints.length;
    updateTrackLine();
  }
}

async function refreshTracks() {
  let res;
  try {
    res = await fetch("/api/tracks");
  } catch (e) {
    return;
  }
  if (!res.ok) return;
  const data = await res.json();
  tracks = data.tracks || [];
  const sel = $("trackSelect");
  const prev = sel.value;
  sel.innerHTML = "";
  if (!tracks.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = t("no_tracks");
    opt.disabled = true;
    sel.appendChild(opt);
  } else {
    for (const tr of tracks) {
      const opt = document.createElement("option");
      opt.value = tr.id;
      opt.textContent = (tr.started_at || tr.id) + " · " + fmtDur(tr.duration) + " · " + tr.point_count + " " + t("points");
      sel.appendChild(opt);
    }
    if (currentTrack && tracks.some(tr => tr.id === currentTrack.id)) sel.value = currentTrack.id;
    else if (prev && tracks.some(tr => tr.id === prev)) sel.value = prev;
  }
  updateRecordUi();
  updatePlaybackUI();
  if (!currentTrack && sel.value && !(recordState && recordState.active)) {
    await loadSelectedTrack();
  }
}

async function loadSelectedTrack() {
  const id = $("trackSelect").value;
  if (!id) return;
  let res;
  try {
    res = await fetch("/api/tracks/" + encodeURIComponent(id));
  } catch (e) {
    return;
  }
  if (!res.ok) return;
  const track = await res.json();
  currentTrack = track;
  currentTrackPoints = track.points || [];
  stopPlayback();
  playback.time = 0;
  updateTrackLine();
  showPlaybackMarker();
  positionPlaybackMarker(0, false);
  updatePlaybackUI();
}

async function toggleRecord() {
  const active = !!(recordState && recordState.active);
  if (!active && !(lastState && lastState.gps && lastState.gps.fix)) {
    setText("recordStatus", t("no_gps"));
    return;
  }
  const action = active ? "stop" : "start";
  let res;
  try {
    res = await fetch("/api/record/" + action, { method: "POST" });
  } catch (e) {
    return;
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    setText("recordStatus", data.error || "record error");
    return;
  }
  if (action === "start") {
    stopPlayback();
    currentTrack = null;
    currentTrackPoints = [];
    recordPointTotal = 0;
    lastRecordFetch = 0;
    updateTrackLine();
    hidePlaybackMarker();
    fetchRecording(true);
  } else {
    await refreshTracks();
    const id = data.track && data.track.id;
    if (id) {
      $("trackSelect").value = id;
      await loadSelectedTrack();
    }
    setText("recordStatus", "");
  }
  recordState = { active: action === "start", point_count: 0, duration: 0 };
  updateRecordUi();
}

function updateRecordUi() {
  const active = !!(recordState && recordState.active);
  const canStart = !!(lastState && lastState.gps && lastState.gps.fix);
  const btn = $("recordBtn");
  btn.classList.toggle("recording", active);
  btn.disabled = !active && !canStart;
  btn.title = (!active && !canStart) ? t("no_gps") : "";
  $("recordLabel").textContent = active ? t("stop") : t("record");
  if (active) {
    setText("recordStatus", t("recording") + " · " + fmtDur(recordState.duration) + " · " + Number(recordState.point_count || 0) + " " + t("points"));
  } else if (!canStart) {
    setText("recordStatus", t("no_gps"));
  } else {
    setText("recordStatus", "");
  }
  $("trackSelect").disabled = active;
  updatePlaybackUI();
}

let trackCollapsed = true;

function setTrackCollapsed(collapsed) {
  trackCollapsed = collapsed;
  $("trackPanel").classList.toggle("collapsed", collapsed);
  $("trackToggle").setAttribute("aria-expanded", collapsed ? "false" : "true");
  $("trackChevron").textContent = collapsed ? "▸" : "▾";
  if (!window.matchMedia("(max-width: 520px)").matches) {
    $("mapInfo").style.bottom = collapsed ? "56px" : "126px";
  }
}

function xmlEscape(value) {
  return String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" }[c]));
}

function exportTrack(format) {
  if (!currentTrack) return;
  const name = currentTrack.started_at || currentTrack.id || "track";
  const points = currentTrack.points || [];
  let text;
  if (format === "gpx") {
    text = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="ELRS Backpack Telemetry" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>${xmlEscape(name)}</name><trkseg>
`;
    for (const p of points) {
      text += `<trkpt lat="${Number(p.lat).toFixed(7)}" lon="${Number(p.lon).toFixed(7)}">`;
      if (Number.isFinite(Number(p.alt))) text += `<ele>${Number(p.alt).toFixed(1)}</ele>`;
      text += `</trkpt>\n`;
    }
    text += `</trkseg></trk></gpx>\n`;
    downloadText((currentTrack.id || "track") + ".gpx", text, "application/gpx+xml");
  } else {
    text = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>${xmlEscape(name)}</name><Placemark><name>${xmlEscape(name)}</name><LineString><altitudeMode>absolute</altitudeMode><coordinates>
`;
    for (const p of points) {
      text += `${Number(p.lon).toFixed(7)},${Number(p.lat).toFixed(7)},${Number.isFinite(Number(p.alt)) ? Number(p.alt).toFixed(1) : "0"}\n`;
    }
    text += `</coordinates></LineString></Placemark></Document></kml>\n`;
    downloadText((currentTrack.id || "track") + ".kml", text, "application/vnd.google-earth.kml+xml");
  }
}

function downloadText(filename, text, mime) {
  if (window.AndroidExport && typeof window.AndroidExport.saveFile === "function") {
    try {
      window.AndroidExport.saveFile(filename, mime, text);
      return;
    } catch (e) {
    }
  }
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach(btn => btn.classList.toggle("active", btn.dataset.tab === name));
  $("telemetryPage").hidden = name !== "telemetry";
  $("mapPage").hidden = name !== "map";
  if (name === "map") {
    window.scrollTo(0, 0);
    ensureMap();
    refreshTracks();
    if (recordState && recordState.active) fetchRecording(false);
    updateRecordUi();
    updatePlaybackUI();
    setTimeout(() => { refreshMapLayout(); updateMap(mapLastGps, true); }, 60);
  }
}

function mavFrameInfo(id) {
  const map = {
    0: ["HEARTBEAT", "Autopilot state and armed flag"],
    1: ["SYS_STATUS", "Battery voltage, current and remaining"],
    2: ["SYSTEM_TIME", "UTC time when RTC is available"],
    24: ["GPS_RAW_INT", "GPS fix, coordinates, altitude, accuracy"],
    30: ["ATTITUDE", "Roll, pitch and yaw"],
    33: ["GLOBAL_POSITION_INT", "Relative altitude, NED velocity and heading"],
    35: ["RC_CHANNELS_RAW", "RC channels and RSSI"],
    49: ["GPS_GLOBAL_ORIGIN", "Home coordinates"],
    74: ["VFR_HUD", "Ground speed, altitude and heading"],
    147: ["BATTERY_STATUS", "Consumed capacity and remaining"],
    242: ["HOME_POSITION", "Home position"],
    253: ["STATUSTEXT", "Autopilot status text"],
  };
  return map[id] || null;
}

function mavNum(v, digits, unit) {
  return v === null || v === undefined ? "—" : Number(v).toFixed(digits) + (unit || "");
}

function renderMavlink(s, st) {
  const l = s.link || {};
  setText("mavRssi", l.rssi_pct != null ? Number(l.rssi_pct).toFixed(1) + " %" : "—");
  setText("mavHeartbeat", st.link_age != null
    ? (st.link_age <= 2 ? t("mav_alive") : st.link_age.toFixed(1) + " " + t("u_s"))
    : "—");
  setText("mavArmed", s.armed === true ? t("mav_armed_yes")
    : s.armed === false ? t("mav_armed_no") : "—");
  setText("mavMsgRate", st.messages_pps != null ? st.messages_pps : "—");
  setText("mavMsgTotal", st.messages != null ? st.messages : "—");
  setText("mavLoss", "—");

  const g = s.gps;
  const gp = (g && g.fix) ? g : s.gps_last;
  setText("mavSats", gp ? gp.sats : "—");
  if (gp) {
    setText("mavLat", Number(gp.lat).toFixed(7));
    setText("mavLon", Number(gp.lon).toFixed(7));
    setText("mavAlt", Number(gp.alt).toFixed(1) + " " + t("u_m"));
    setText("mavSpd", Number(gp.speed).toFixed(1) + " " + t("u_kmh"));
    setText("mavHdg", Number(gp.heading).toFixed(0) + "°");
  } else {
    ["mavLat", "mavLon", "mavAlt", "mavSpd", "mavHdg"].forEach(id => setText(id, "—"));
  }
  updateQr(g, s.gps_last, "mavGpsQrWrap", "mavGpsQr");
  const ge = s.gps_ext || {};
  setText("mavFix", g ? (g.fix3d ? "3D" : (g.fix ? "2D" : t("fix_none"))) : "—");
  setText("mavHdop", mavNum(ge.hdop, 1));
  setText("mavVdop", mavNum(ge.vdop, 1));
  setText("mavHAcc", ge.h_acc != null ? mavNum(ge.h_acc, 2, " " + t("u_m")) : "—");

  setText("mavFlightMode", s.flight_mode || "—");
  setText("mavFlightNote", s.armed === true ? t("mode_armed")
    : s.armed === false ? t("mode_ready") : "");
  setText("mavBaroAlt", s.baro ? Number(s.baro.alt).toFixed(1) + " " + t("u_m") : "—");
  const vario = s.vario != null ? s.vario : (s.baro ? s.baro.vario : null);
  setText("mavVario", vario != null
    ? (vario >= 0 ? "+" : "") + Number(vario).toFixed(1) + " " + t("u_ms") : "—");
  setText("mavGpsTime", s.gps_time || "—");
  setText("mavDevice", s.device || "—");

  const a = s.attitude;
  if (a) {
    setText("mavPitch", Number(a.pitch).toFixed(1) + "°");
    setText("mavRoll", Number(a.roll).toFixed(1) + "°");
    setText("mavYaw", Number(a.yaw).toFixed(1) + "°");
    $("mavHorizon").style.transform = "rotate(" + (-a.roll).toFixed(1) + "deg) translateY(" + (a.pitch * 3).toFixed(1) + "px)";
  } else {
    ["mavPitch", "mavRoll", "mavYaw"].forEach(id => setText(id, "—"));
  }

  const b = s.battery;
  const hasBattery = b && (b.voltage != null || b.current != null || b.capacity != null);
  if (hasBattery) {
    setText("mavVolt", b.voltage != null ? Number(b.voltage).toFixed(1) : "—");
    setText("mavCurr", b.current != null ? Number(b.current).toFixed(1) + " " + t("u_a") : "—");
    setText("mavCap", b.capacity != null ? b.capacity + " " + t("u_mah") : "—");
    setText("mavRemTxt", b.remaining != null ? b.remaining + "%" : "—");
    bar("mavBarRem", b.remaining, "mavRemTxt");
  } else {
    setText("mavVolt", "—"); setText("mavCurr", "—"); setText("mavCap", "—");
    setText("mavRemTxt", t("no_data")); bar("mavBarRem", 0, "mavRemTxt");
  }

  setText("mavPps", st.messages_pps != null ? st.messages_pps : "—");
  setText("mavTotal", st.messages != null ? st.messages : "—");
  setText("mavAge", st.age != null ? st.age.toFixed(2) + " " + t("u_s") : "—");
  const f = s.frames || {};
  const keys = Object.keys(f).sort((x, y) => Number(x) - Number(y));
  setText("mavTypesCount", keys.length);
  const rows = keys.map(k => {
    const id = Number(k);
    const info = mavFrameInfo(id);
    return "<tr" + (info ? "" : ' class="unknown"') + ">" +
      "<td>" + id + "</td>" +
      "<td>" + (info ? info[0] : t("unknown_frame")) + "</td>" +
      "<td>" + f[k] + "</td>" +
      "<td>" + (info ? info[1] : t("not_described")) + "</td></tr>";
  });
  $("mavFramesBody").innerHTML = rows.length
    ? rows.join("")
    : '<tr><td colspan="4" class="muted">' + t("no_frames") + "</td></tr>";
}

function render(s) {
  const st = s.stats || {};
  const protocol = s.protocol || "crsf";
  const crsfCards = $("crsfCards");
  const mavCards = $("mavCards");
  if (crsfCards) crsfCards.hidden = protocol === "mavlink";
  if (mavCards) mavCards.hidden = protocol !== "mavlink";
  const protoBadge = $("protocol");
  if (protoBadge) {
    protoBadge.hidden = false;
    protoBadge.textContent = protocol === "mavlink" ? "MAVLink" : "CRSF";
  }
  const online = st.online === true;
  const transportFresh = st.age !== null && st.age !== undefined && st.age < 2 && st.total > 0;
  const pill = $("status");
  const mobile = window.matchMedia("(max-width: 520px)").matches;
  if (online) {
    pill.className = "pill on";
    pill.textContent = t(mobile ? "status_online_short" : "status_online", { pps: st.pps });
  } else if (transportFresh) {
    pill.className = "pill off";
    pill.textContent = t(mobile ? "status_link_down_short" : "status_link_down", { pps: st.pps });
  } else {
    pill.className = "pill off";
    pill.textContent = st.total
      ? t(mobile ? "status_stale_short" : "status_stale", { age: st.age != null ? st.age.toFixed(1) : "?" })
      : t(mobile ? "status_no_data_short" : "status_no_data");
  }

  if (protocol === "mavlink") {
    renderMavlink(s, st);
  } else {
  const l = s.link;
  if (l) {
    setText("lqUp", l.lq + "%");   bar("barUp", l.lq, "lqUp");
    setText("lqDn", l.lq_d + "%"); bar("barDn", l.lq_d, "lqDn");
    setText("rssiUp", rssi(l.rssi1)); setText("rssiDn", rssi(l.rssi_d));
    setText("snrUp", snr(l.snr));     setText("snrDn", snr(l.snr_d));
    setText("txp", TX_POWER_MW[l.tx_power] !== undefined ? TX_POWER_MW[l.tx_power] + " " + t("u_mw") : "—");
    setText("ant", l.active_ant === 0 ? "1" : l.active_ant === 1 ? "2" : "—");
    const rf = RF_MODES[l.rf_mode] || null;
    if (rf) {
      setText("band", bandText(rf[0]));
      setText("pktRate", rf[1]);
      let rssi = (l.active_ant === 1) ? l.rssi2 : l.rssi1;
      if ((rssi === null || rssi === undefined || rssi === 0) && l.active_ant === 1) rssi = l.rssi1;
      if (rf[2] !== null && rssi !== null && rssi !== undefined && rssi !== 0) {
        const clamped = Math.min(-50, rssi);
        const target = Math.round(100 * (clamped + 50) / (rf[2] + 50));
        if (rangeMode !== l.rf_mode || rangeSmooth === null) {
          rangeSmooth = target;
          rangeMode = l.rf_mode;
        } else {
          rangeSmooth = Math.round(rangeSmooth * 0.6 + target * 0.4);
        }
        setText("rangePct", rangeSmooth + "%");
        rangeBar("barRange", rangeSmooth, "rangePct");
      } else {
        setText("rangePct", "—");
        rangeBar("barRange", null, "rangePct");
      }
    } else {
      setText("band", "—"); setText("pktRate", "—");
      setText("rangePct", "—"); rangeBar("barRange", null, "rangePct");
      rangeSmooth = null; rangeMode = null;
    }
  } else {
    ["lqUp","lqDn","rssiUp","rssiDn","snrUp","snrDn","txp","ant","band","pktRate","rangePct"].forEach(id => setText(id, "—"));
    bar("barUp", null, "lqUp"); bar("barDn", null, "lqDn"); rangeBar("barRange", null, "rangePct");
    rangeSmooth = null; rangeMode = null;
  }

  const b = s.battery;
  if (b && (b.voltage || b.current || b.capacity)) {
    setText("volt", b.voltage.toFixed(1));
    setText("curr", b.current.toFixed(1) + " " + t("u_a"));
    setText("cap", b.capacity + " " + t("u_mah"));
    setText("remTxt", b.remaining + "%"); bar("barRem", b.remaining);
  } else {
    setText("volt", "—"); setText("curr", "—"); setText("cap", "—");
    setText("remTxt", t("no_data")); bar("barRem", 0);
  }

  const g = s.gps;
  const gp = (g && g.fix) ? g : s.gps_last;
  setText("sats", g ? g.sats : "—");
  if (gp) {
    setText("lat", gp.lat.toFixed(7));
    setText("lon", gp.lon.toFixed(7));
    setText("alt", gp.alt.toFixed(1) + " " + t("u_m"));
    setText("spd", gp.speed.toFixed(1) + " " + t("u_kmh"));
    setText("hdg", gp.heading.toFixed(0) + "°");
    $("showMap").style.display = "inline-block";
  } else {
    ["lat","lon","alt","spd","hdg"].forEach(id => setText(id, "—"));
    $("showMap").style.display = "none";
  }
  updateQr(g, s.gps_last);
  const ge = s.gps_ext;
  setText("fixType", g ? (g.fix3d ? "3D" : (g.fix ? "2D" : t("fix_none"))) : "—");
  setText("hdop", ge ? ge.hdop.toFixed(1) : "—");

  setText("flightMode", s.flight_mode || "—");
  const mode = s.flight_mode || "";
  let modeNote = "";
  if (mode === "!FS!") modeNote = t("mode_failsafe");
  else if (mode.endsWith("!")) modeNote = t("mode_blocked");
  else if (mode.endsWith("?")) modeNote = t("mode_gps_rescue_off");
  else if (mode.endsWith("*")) modeNote = t("mode_ready");
  else if (mode) modeNote = t("mode_armed");
  setText("flightNote", modeNote);
  const br = s.baro;
  setText("baroAlt", br ? br.alt.toFixed(1) + " " + t("u_m") : "—");
  const vario = s.vario != null ? s.vario : (br ? br.vario : null);
  setText("vario", vario != null ? (vario >= 0 ? "+" : "") + vario.toFixed(1) + " " + t("u_ms") : "—");
  setText("gpsTime", s.gps_time || "—");
  setText("device", s.device || "—");

  const a = s.attitude;
  if (a) {
    setText("pitch", a.pitch.toFixed(1) + "°");
    setText("roll", a.roll.toFixed(1) + "°");
    setText("yaw", a.yaw.toFixed(1) + "°");
    $("horizon").style.transform = "rotate(" + (-a.roll).toFixed(1) + "deg) translateY(" + (a.pitch * 3).toFixed(1) + "px)";
  } else {
    ["pitch","roll","yaw"].forEach(id => setText(id, "—"));
  }

  setText("pps", st.pps ?? "—");
  setText("total", st.total ?? "—");
  setText("age", st.age != null ? st.age.toFixed(2) + " " + t("u_s") : "—");

  const f = s.frames || {};
  const keys = Object.keys(f).sort((x, y) => Number(x) - Number(y));
  setText("typesCount", keys.length);
  const rows = keys.map(k => {
    const type = Number(k);
    const info = frameInfo(type);
    const name = info ? info[0] : t("unknown_frame");
    const desc = info ? info[1] : t("not_described");
    return "<tr" + (info ? "" : ' class="unknown"') + ">" +
      "<td>0x" + type.toString(16).toUpperCase().padStart(2, "0") + "</td>" +
      "<td>" + name + "</td>" +
      "<td>" + f[k] + "</td>" +
      "<td>" + desc + "</td></tr>";
  });
  $("framesBody").innerHTML = rows.length
    ? rows.join("")
    : '<tr><td colspan="4" class="muted">' + t("no_frames") + "</td></tr>";
  }

  const currentGps = (s.gps && s.gps.fix) ? s.gps : null;
  mapGpsLive = !!currentGps;
  if (currentGps) mapLastGps = currentGps;
  else if (!mapLastGps && s.gps_last && s.gps_last.fix) mapLastGps = s.gps_last;
  updateMap(currentGps, false);
  const rec = s.record || {};
  if (rec.active && !(recordState && recordState.active)) {
    currentTrackPoints = [];
    recordPointTotal = 0;
    updateTrackLine();
  }
  recordState = rec;
  updateRecordUi();
}

async function tick() {
  try {
    const res = await fetch("/api/state", { cache: "no-store" });
    lastState = await res.json();
    render(lastState);
    if (lastState.record && lastState.record.active) {
      const now = performance.now();
      if (now - lastRecordFetch > 1000 && lastState.record.point_count > recordPointTotal) {
        lastRecordFetch = now;
        fetchRecording(false);
      }
    }
  } catch (e) {
    const pill = $("status");
    pill.className = "pill off";
    pill.textContent = t("status_no_server");
  }
  setTimeout(tick, 250);
}

LANG = pickLang();
applyI18n();
$("lang").addEventListener("change", e => {
  LANG = e.target.value;
  localStorage.setItem("tlm_lang", LANG);
  applyI18n();
  if (ANDROID_SETTINGS) loadPermissions();
  if (lastState) render(lastState);
});
document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});
$("showMap").addEventListener("click", () => switchTab("map"));
window.addEventListener("resize", () => setTimeout(refreshMapLayout, 50));
window.addEventListener("orientationchange", () => setTimeout(refreshMapLayout, 200));
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) setTimeout(refreshMapLayout, 100);
});
if (window.ResizeObserver) {
  new ResizeObserver(() => {
    if (!$("mapPage").hidden) refreshMapLayout();
  }).observe(document.querySelector("header"));
}
$("gpsQrWrap").addEventListener("click", openGpsInMaps);
$("gpsQrWrap").addEventListener("keydown", e => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    openGpsInMaps();
  }
});
if ($("mavGpsQrWrap")) {
  $("mavGpsQrWrap").addEventListener("click", openGpsInMaps);
  $("mavGpsQrWrap").addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openGpsInMaps();
    }
  });
}
$("followDrone").addEventListener("change", e => {
  mapFollow = e.target.checked;
  if (mapFollow) updateMap(mapLastGps, true);
});
$("centerMap").addEventListener("click", () => {
  if (!mapReady) return;
  const p = (currentTrack && lastPlaybackPos) ? lastPlaybackPos : (mapLastGps && mapLastGps.fix ? { lon: mapLastGps.lon, lat: mapLastGps.lat } : null);
  if (!p) return;
  mapObj.easeTo({ center: [p.lon, p.lat], zoom: Math.max(mapObj.getZoom(), 15), duration: 300 });
});
$("trackToggle").addEventListener("click", () => setTrackCollapsed(!trackCollapsed));
$("exportGpx").addEventListener("click", () => exportTrack("gpx"));
$("exportKml").addEventListener("click", () => exportTrack("kml"));
$("recordBtn").addEventListener("click", () => toggleRecord());
$("trackSelect").addEventListener("change", async () => {
  currentTrack = null;
  currentTrackPoints = [];
  stopPlayback();
  updateTrackLine();
  hidePlaybackMarker();
  updatePlaybackUI();
  await loadSelectedTrack();
});
$("deleteTrack").addEventListener("click", async () => {
  const id = $("trackSelect").value;
  if (!id || !confirm(t("delete_confirm"))) return;
  await fetch("/api/tracks/" + encodeURIComponent(id), { method: "DELETE" }).catch(() => {});
  if (currentTrack && currentTrack.id === id) {
    currentTrack = null;
    currentTrackPoints = [];
    stopPlayback();
    updateTrackLine();
    hidePlaybackMarker();
    updatePlaybackUI();
  }
  await refreshTracks();
});
$("playBtn").addEventListener("click", () => {
  if (playback.playing) stopPlayback(); else startPlayback();
});
$("trackProgress").addEventListener("input", e => {
  playback.time = parseFloat(e.target.value) || 0;
  playback.last = performance.now();
  positionPlaybackMarker(playback.time, false);
  updatePlaybackUI();
});
$("playSpeed").addEventListener("change", e => {
  playback.speed = parseFloat(e.target.value) || 1;
});

$("udpPortSave").addEventListener("click", async () => {
  const port = parseInt($("udpPortInput").value, 10);
  if (!Number.isFinite(port) || port < 1 || port > 65535) {
    setSettingsMsg("udpPortMsg", t("udp_port_error"), true);
    return;
  }
  setSettingsMsg("udpPortMsg", "");
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ udp_port: port }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      setSettingsMsg("udpPortMsg", t("udp_port_saved"));
      if (data.settings) applySettingsData(data.settings);
    } else {
      setSettingsMsg("udpPortMsg", data.error || t("udp_port_error"), true);
    }
  } catch (e) {
    setSettingsMsg("udpPortMsg", t("udp_port_error"), true);
  }
});
$("idleReleaseSave").addEventListener("click", async () => {
  const raw = $("idleReleaseMin").value.trim();
  const minutes = raw === "" ? 0 : parseInt(raw, 10);
  if (!Number.isFinite(minutes) || minutes < 0 || minutes > 1440) {
    setSettingsMsg("idleReleaseMsg", t("idle_release_error"), true);
    return;
  }
  setSettingsMsg("idleReleaseMsg", "");
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idle_release_min: minutes }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      setSettingsMsg("idleReleaseMsg", t("idle_release_saved"));
      if (data.settings) applySettingsData(data.settings);
    } else {
      setSettingsMsg("idleReleaseMsg", data.error || t("idle_release_error"), true);
    }
  } catch (e) {
    setSettingsMsg("idleReleaseMsg", t("idle_release_error"), true);
  }
});
$("chooseTracksFolder").addEventListener("click", () => {
  if (ANDROID_SETTINGS) AndroidSettings.chooseTracksFolder();
});
$("resetTracksFolder").addEventListener("click", () => {
  if (ANDROID_SETTINGS) AndroidSettings.resetTracksFolder();
});
$("refreshPermissions").addEventListener("click", () => loadPermissions());
$("openAppSettings").addEventListener("click", () => {
  if (ANDROID_SETTINGS) AndroidSettings.openAppSettings();
});
$("closeApp").addEventListener("click", () => {
  if (!ANDROID_SETTINGS || typeof AndroidSettings.closeApp !== "function") return;
  const recording = !!(lastState && lastState.record && lastState.record.active);
  if (recording && !confirm(t("close_recording_confirm"))) return;
  AndroidSettings.closeApp();
});

$("desktopAutoRecord3d").addEventListener("change", async (e) => {
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_record_3d: e.target.checked }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "error");
    applyDesktopSettings(data.settings || {});
    setSettingsMsg("desktopSettingsMsg", t("settings_saved"));
  } catch (err) {
    setSettingsMsg("desktopSettingsMsg", String(err.message || err), true);
  }
});
$("desktopAutoStopSave").addEventListener("click", async () => {
  const raw = $("desktopAutoStop").value.trim();
  const seconds = raw === "" ? 0 : parseInt(raw, 10);
  if (!Number.isFinite(seconds) || seconds < 0 || seconds > 3600) {
    setSettingsMsg("desktopSettingsMsg", t("auto_stop_recording_error"), true);
    return;
  }
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_stop_recording_sec: seconds }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "error");
    applyDesktopSettings(data.settings || {});
    setSettingsMsg("desktopSettingsMsg", t("settings_saved"));
  } catch (err) {
    setSettingsMsg("desktopSettingsMsg", String(err.message || err), true);
  }
});

setTrackCollapsed(true);
const initialTab = new URLSearchParams(location.search).get("tab") === "map" ? "map" : "telemetry";
switchTab(initialTab);
tick();
loadSettings();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _content_type(name):
        if name.endswith(".js"):
            return "application/javascript; charset=utf-8"
        if name.endswith(".css"):
            return "text/css; charset=utf-8"
        if name.endswith(".json"):
            return "application/json; charset=utf-8"
        if name.endswith(".pbf"):
            return "application/x-protobuf"
        if name.endswith(".pmtiles"):
            return "application/vnd.pmtiles"
        if name.endswith(".png"):
            return "image/png"
        if name.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        if name.endswith(".svg"):
            return "image/svg+xml"
        if name.endswith(".woff2"):
            return "font/woff2"
        return "application/octet-stream"

    @staticmethod
    def _parse_range(header, size):
        if size <= 0:
            return None
        value = (header or "").strip()
        if not value.lower().startswith("bytes="):
            return None
        spec = value.split("=", 1)[1].split(",", 1)[0].strip()
        if "-" not in spec:
            return None
        start_text, end_text = spec.split("-", 1)
        try:
            if not start_text:
                suffix = int(end_text)
                if suffix <= 0:
                    return None
                start = max(0, size - suffix)
                end = size - 1
            else:
                start = int(start_text)
                end = int(end_text) if end_text else size - 1
        except ValueError:
            return None
        if start < 0 or start >= size or end < start:
            return None
        return start, min(end, size - 1)

    def _serve_file(self, root, relative, cache_control):
        name = unquote(relative)
        if not name or name.startswith("/") or ".." in name.split("/"):
            self.send_error(404)
            return
        root_real = os.path.realpath(root)
        full = os.path.realpath(os.path.join(root_real, name))
        if not full.startswith(root_real + os.sep) or not os.path.isfile(full):
            self.send_error(404)
            return
        size = os.path.getsize(full)
        status = 200
        start, end = 0, size - 1
        range_header = self.headers.get("Range")
        if range_header:
            parsed = self._parse_range(range_header, size)
            if parsed is None:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */" + str(size))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            start, end = parsed
            status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", self._content_type(name))
        self.send_header("Cache-Control", cache_control)
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Content-Length", str(length))
        self.end_headers()
        with open(full, "rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith("/static/"):
            self._serve_file(STATIC_DIR, path[len("/static/"):], "no-store")
        elif path.startswith("/tiles/"):
            self._serve_file(TILES_DIR, path[len("/tiles/"):], "public, max-age=3600")
        elif path == "/api/state":
            self._json(snapshot())
        elif path == "/api/settings":
            self._json(settings_snapshot())
        elif path == "/api/record":
            try:
                since = int(parse_qs(parsed.query).get("since", ["0"])[0])
            except (TypeError, ValueError):
                since = 0
            self._json(record_snapshot(since))
        elif path == "/api/tracks":
            self._json({"tracks": list_tracks()})
        elif path.startswith("/api/tracks/"):
            track = load_track(unquote(path[len("/api/tracks/"):]))
            if track is None:
                self._json({"error": "not found"}, 404)
            else:
                self._json(track)
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/settings":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("object expected")
                if "auto_record_3d" in body:
                    SETTINGS["auto_record_3d"] = bool(body["auto_record_3d"])
                if "auto_stop_recording_sec" in body:
                    value = int(body["auto_stop_recording_sec"])
                    if value < 0 or value > 3600:
                        raise ValueError("auto_stop_recording_sec must be 0..3600")
                    SETTINGS["auto_stop_sec"] = value
                save_settings()
                self._json({"ok": True, "settings": settings_snapshot()})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
        elif path == "/api/record/start":
            ok, error = start_recording()
            if ok:
                self._json({"ok": True, "record": record_snapshot(0)}, 200)
            else:
                self._json({"ok": False, "error": error}, 409)
        elif path == "/api/record/stop":
            meta, error = stop_recording()
            if meta is None:
                self._json({"ok": False, "error": error}, 400)
            else:
                self._json({"ok": True, "track": meta}, 200)
        else:
            self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/tracks/"):
            if delete_track(unquote(path[len("/api/tracks/"):])):
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="ELRS Backpack Telemetry Wi-Fi viewer")
    parser.add_argument("--udp-port", type=int, default=14550)
    parser.add_argument("--http-host", default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=8080)
    args = parser.parse_args()

    load_settings()
    threading.Thread(target=listener, args=(args.udp_port,), daemon=True).start()
    threading.Thread(target=auto_stop_loop, daemon=True).start()
    server = ThreadingHTTPServer((args.http_host, args.http_port), Handler)
    print(f"UDP  : 0.0.0.0:{args.udp_port}")
    print(f"HTTP : http://localhost:{args.http_port}")
    print("Ctrl+C для выхода")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
