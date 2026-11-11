#!/usr/bin/env python3
"""Assemble the GitHub Pages web flasher from merged ESP32 images."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

TARGETS = {
    "c3": "ESP32-C3",
    "s3": "ESP32-S3",
}


def parse_binary(spec: str) -> tuple[str, Path]:
    """Parse TARGET=PATH; a bare path keeps the old ESP32-C3 behaviour."""
    if "=" in spec:
        target, _, path = spec.partition("=")
        target = target.strip().lower()
        raw = path.strip()
    else:
        target, raw = "c3", spec.strip()
    if target not in TARGETS:
        valid = ", ".join(sorted(TARGETS))
        raise argparse.ArgumentTypeError(
            f"unknown target '{target}' (expected one of: {valid})"
        )
    if not raw:
        raise argparse.ArgumentTypeError(f"empty firmware path for target '{target}'")
    return target, Path(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument(
        "--binary",
        required=True,
        action="append",
        type=parse_binary,
        metavar="TARGET=PATH",
        help="merged image per target; repeat for several targets (c3, s3)",
    )
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--source", type=Path, default=Path("webflasher"))
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    source = (root / args.source) if not args.source.is_absolute() else args.source
    out = args.out if args.out.is_absolute() else (root / args.out)

    index = source / "index.html"
    if not index.is_file():
        raise SystemExit(f"missing page template: {index}")

    images: dict[str, Path] = {}
    for target, path in args.binary:
        if target in images:
            raise SystemExit(f"duplicate target: {target}")
        binary = path if path.is_absolute() else (root / path)
        if not binary.is_file():
            raise SystemExit(f"missing firmware image for {target}: {binary}")
        images[target] = binary

    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(index, out / "index.html")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    builds = []
    sums = []
    for target, binary in images.items():
        filename = f"firmware-merged-{target}.bin"
        shutil.copyfile(binary, out / filename)
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        sums.append(f"{digest}  {filename}")
        builds.append(
            {
                "chipFamily": TARGETS[target],
                "serialType": "cdc",
                "parts": [{"path": filename, "offset": 0}],
            }
        )

    manifest = {
        "name": "ELRS ESP-NOW USB Dongle",
        "version": args.version,
        "new_install_prompt_erase": True,
        "builds": builds,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")

    print(
        f"web flasher: {out} (version {args.version}, "
        f"targets: {', '.join(images)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
