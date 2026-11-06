#!/usr/bin/env bash
# Idempotent toolchain bootstrap for this project (Linux x86_64).
# Everything is kept in .toolchain/ so reruns do not download it again.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TC="${TOOLCHAIN_DIR:-$ROOT/.toolchain}"

JDK_DIR="$TC/jdk21"
GRADLE_DIR="$TC/gradle-8.9"
SDK_DIR="$TC/android-sdk"
GRADLE_HOME_DIR="${GRADLE_USER_HOME:-$TC/gradle-home}"

JDK_URL="https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse"
GRADLE_URL="https://services.gradle.org/distributions/gradle-8.9-bin.zip"
CMDLINE_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
    echo "This bootstrap supports Linux x86_64 only." >&2
    echo "Use Android Studio or the manual setup in DEVELOP.md on other systems." >&2
    exit 1
fi

for tool in curl tar unzip; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "Missing required tool: $tool" >&2
        exit 1
    fi
done

mkdir -p "$TC"

if [ ! -x "$JDK_DIR/bin/java" ]; then
    echo "==> Downloading JDK 21 (Temurin)"
    tmp="$TC/jdk-download.tar.gz"
    curl -fL --retry 3 -o "$tmp" "$JDK_URL"
    rm -rf "$TC/jdk-tmp"
    mkdir -p "$TC/jdk-tmp"
    tar -xzf "$tmp" -C "$TC/jdk-tmp"
    rm -rf "$JDK_DIR"
    mv "$TC"/jdk-tmp/jdk-21* "$JDK_DIR"
    rm -rf "$TC/jdk-tmp" "$tmp"
else
    echo "==> JDK already present: $JDK_DIR"
fi

if [ ! -x "$GRADLE_DIR/bin/gradle" ]; then
    echo "==> Downloading Gradle 8.9"
    tmp="$TC/gradle-download.zip"
    curl -fL --retry 3 -o "$tmp" "$GRADLE_URL"
    unzip -q -o "$tmp" -d "$TC"
    rm -f "$tmp"
else
    echo "==> Gradle already present: $GRADLE_DIR"
fi

if [ ! -x "$SDK_DIR/cmdline-tools/latest/bin/sdkmanager" ]; then
    echo "==> Downloading Android command-line tools"
    tmp="$TC/cmdline-tools-download.zip"
    curl -fL --retry 3 -o "$tmp" "$CMDLINE_URL"
    rm -rf "$TC/sdk-tmp"
    unzip -q "$tmp" -d "$TC/sdk-tmp"
    mkdir -p "$SDK_DIR/cmdline-tools"
    rm -rf "$SDK_DIR/cmdline-tools/latest"
    mv "$TC/sdk-tmp/cmdline-tools" "$SDK_DIR/cmdline-tools/latest"
    rm -rf "$TC/sdk-tmp" "$tmp"
else
    echo "==> Android command-line tools already present: $SDK_DIR"
fi

export JAVA_HOME="$JDK_DIR"
export ANDROID_HOME="$SDK_DIR"
export ANDROID_SDK_ROOT="$SDK_DIR"
export GRADLE_USER_HOME="$GRADLE_HOME_DIR"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"

echo "==> Accepting Android SDK licenses"
yes | sdkmanager --sdk_root="$ANDROID_HOME" --licenses >/dev/null 2>&1 || true

echo "==> Installing Android SDK packages"
sdkmanager --sdk_root="$ANDROID_HOME" \
    "platform-tools" \
    "platforms;android-35" \
    "build-tools;35.0.0" \
    "build-tools;34.0.0"

mkdir -p "$ROOT/android"
printf 'sdk.dir=%s\n' "$ANDROID_HOME" > "$ROOT/android/local.properties"

cat > "$TC/env.sh" <<EOF
export JAVA_HOME="$JDK_DIR"
export ANDROID_HOME="$SDK_DIR"
export ANDROID_SDK_ROOT="$SDK_DIR"
export GRADLE_USER_HOME="$GRADLE_HOME_DIR"
export PATH="\$JAVA_HOME/bin:\$ANDROID_HOME/cmdline-tools/latest/bin:\$ANDROID_HOME/platform-tools:\$PATH"
EOF

mkdir -p "$GRADLE_HOME_DIR"

echo
echo "Toolchain ready: $TC"
echo "  source .toolchain/env.sh"
echo "  cd android && ./gradlew assembleDebug"
