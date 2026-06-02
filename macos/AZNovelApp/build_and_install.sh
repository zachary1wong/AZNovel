#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APP_NAME="AZNovel"
BUILD_ROOT="$REPO_ROOT/build/macos"
APP_DIR="$BUILD_ROOT/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"
SOURCE_FILE="$SCRIPT_DIR/Sources/AZNovelApp.swift"
SWIFTC="$(xcrun --find swiftc)"
SDK_PATH="$(xcrun --sdk macosx --show-sdk-path)"
SWIFT_RESOURCE_DIR="/Library/Developer/CommandLineTools/usr/lib/swift"
PYTHON_PATH="${AZNOVEL_PYTHON:-$(command -v python3)}"
INSTALL_DIR="${AZNOVEL_INSTALL_DIR:-/Applications}"

xml_escape() {
  local value="$1"
  value="${value//&/&amp;}"
  value="${value//</&lt;}"
  value="${value//>/&gt;}"
  value="${value//\"/&quot;}"
  printf '%s' "$value"
}

REPO_ROOT_XML="$(xml_escape "$REPO_ROOT")"
PYTHON_PATH_XML="$(xml_escape "$PYTHON_PATH")"

mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

"$SWIFTC" \
  "$SOURCE_FILE" \
  -parse-as-library \
  -sdk "$SDK_PATH" \
  -target arm64-apple-macosx14.0 \
  -resource-dir "$SWIFT_RESOURCE_DIR" \
  -O \
  -framework Cocoa \
  -o "$MACOS_DIR/$APP_NAME"

cat > "$CONTENTS_DIR/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleDisplayName</key>
  <string>AZNovel</string>
  <key>CFBundleExecutable</key>
  <string>AZNovel</string>
  <key>CFBundleIdentifier</key>
  <string>com.aznovel.launcher</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>AZNovel</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
EOF

cat > "$RESOURCES_DIR/AZNovelCLI.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>SourceRoot</key>
  <string>$REPO_ROOT_XML</string>
  <key>PythonPath</key>
  <string>$PYTHON_PATH_XML</string>
</dict>
</plist>
EOF

codesign --force --deep --sign - "$APP_DIR" >/dev/null

if [[ "${1:-}" != "--no-install" ]]; then
  mkdir -p "$INSTALL_DIR"
  rm -rf "$INSTALL_DIR/$APP_NAME.app"
  ditto "$APP_DIR" "$INSTALL_DIR/$APP_NAME.app"
  codesign --force --deep --sign - "$INSTALL_DIR/$APP_NAME.app" >/dev/null
  echo "Installed $INSTALL_DIR/$APP_NAME.app"
else
  echo "Built $APP_DIR"
fi
