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
ICON_SOURCE="$SCRIPT_DIR/Assets/AppIcon.png"
SWIFTC="$(xcrun --find swiftc)"
SDK_PATH="$(xcrun --sdk macosx --show-sdk-path)"
SWIFT_RESOURCE_DIR="/Library/Developer/CommandLineTools/usr/lib/swift"
PYTHON_PATH="${AZNOVEL_PYTHON:-$(command -v python3)}"
INSTALL_DIR="${AZNOVEL_INSTALL_DIR:-/Applications}"
BUNDLE_VERSION="$(date +%Y%m%d%H%M%S)"

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
  -sdk "$SDK_PATH" \
  -target arm64-apple-macosx14.0 \
  -resource-dir "$SWIFT_RESOURCE_DIR" \
  -O \
  -framework Cocoa \
  -o "$MACOS_DIR/$APP_NAME"

if [[ -f "$ICON_SOURCE" ]]; then
  ICONSET_DIR="$BUILD_ROOT/AppIcon.iconset"
  rm -rf "$ICONSET_DIR"
  mkdir -p "$ICONSET_DIR"

  sips -z 16 16 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
  sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
  sips -z 64 64 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
  sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
  sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$ICONSET_DIR" -o "$RESOURCES_DIR/AppIcon.icns"
fi

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
  <key>CFBundleIconFile</key>
  <string>AppIcon.icns</string>
  <key>CFBundleIdentifier</key>
  <string>com.aznovel.launcher</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>AZNovel</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.2.0</string>
  <key>CFBundleVersion</key>
  <string>$BUNDLE_VERSION</string>
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
  osascript -e "tell application \"$APP_NAME\" to quit" >/dev/null 2>&1 || true
  pkill -x "$APP_NAME" >/dev/null 2>&1 || true
  pkill -f "$INSTALL_DIR/$APP_NAME.app/Contents/MacOS/$APP_NAME" >/dev/null 2>&1 || true
  sleep 0.5
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && kill "$pid" >/dev/null 2>&1 || true
  done < <(pgrep -f "$INSTALL_DIR/$APP_NAME.app/Contents/MacOS/$APP_NAME" || true)
  sleep 0.5
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && kill -9 "$pid" >/dev/null 2>&1 || true
  done < <(pgrep -f "$INSTALL_DIR/$APP_NAME.app/Contents/MacOS/$APP_NAME" || true)
  rm -rf "$HOME/Library/Saved Application State/com.aznovel.launcher.savedState"
  mkdir -p "$INSTALL_DIR"
  rm -rf "$INSTALL_DIR/$APP_NAME.app"
  ditto "$APP_DIR" "$INSTALL_DIR/$APP_NAME.app"
  codesign --force --deep --sign - "$INSTALL_DIR/$APP_NAME.app" >/dev/null
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
    -f "$INSTALL_DIR/$APP_NAME.app" >/dev/null 2>&1 || true
  echo "Installed $INSTALL_DIR/$APP_NAME.app"
else
  echo "Built $APP_DIR"
fi
