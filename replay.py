#!/usr/bin/env python3
import argparse
import json
import socket
import sys
import time


def load_packets(path):
    packets = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "data" in obj and "t" in obj:
                packets.append((float(obj["t"]), bytes.fromhex(obj["data"])))
    return packets


def main():
    parser = argparse.ArgumentParser(description="Replay a captured ELRS telemetry JSONL")
    parser.add_argument("file")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=14550)
    parser.add_argument("--speed", type=float, default=1.0,
                        help="1.0 = real time, 2.0 = twice as fast, 0 = send as fast as possible")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    packets = load_packets(args.file)
    if not packets:
        sys.exit(f"no packets found in {args.file}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    total = 0
    try:
        while True:
            base = packets[0][0]
            started = time.monotonic()
            for t, data in packets:
                if args.speed > 0:
                    target = started + (t - base) / args.speed
                    delay = target - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                sock.sendto(data, (args.host, args.port))
                total += 1
            print(f"sent {len(packets)} packets ({total} total) to {args.host}:{args.port}")
            if not args.loop:
                break
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
