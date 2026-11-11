#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TC="$ROOT/.toolchain"
VENV="$TC/venv"
PY="$VENV/bin/python"
PIO="$VENV/bin/pio"

mkdir -p "$TC/platformio" "$TC/cache"

if [ ! -x "$PY" ]; then
    if ! command -v python3 >/dev/null 2>&1; then
        echo "python3 is required to create $VENV" >&2
        exit 1
    fi
    python3 -m venv "$VENV"
fi

if [ ! -x "$PIO" ] || ! "$PIO" --version 2>/dev/null | grep -qE 'version 6\.'; then
    "$PY" -m pip install --upgrade pip >/dev/null
    "$PY" -m pip install "platformio==6.2.0"
fi

if ! "$PIO" --version >/dev/null 2>&1; then
    echo "failed to install a working PlatformIO into $VENV" >&2
    exit 1
fi

# Standalone esptool for merging web-flasher images (platform-independent).
if ! "$PY" -c 'import esptool, sys; sys.exit(0 if esptool.__version__ == "5.4.0" else 1)' 2>/dev/null; then
    "$PY" -m pip install "esptool==5.4.0"
fi

cat > "$TC/pio-env.sh" <<EOF
export PLATFORMIO_CORE_DIR="$TC/platformio"
export PLATFORMIO_CACHE_DIR="$TC/cache"
export PLATFORMIO_SETTING_ENABLE_TELEMETRY=false
export PATH="$VENV/bin:\$PATH"
EOF

echo "firmware toolchain: $TC"
echo "platformio: $PIO ($("$PIO" --version 2>/dev/null | tail -1))"
echo "run: source .toolchain/pio-env.sh"
echo "firmware: ./tools/pio run -d firmware -e esp32-c3-usb-otg"
