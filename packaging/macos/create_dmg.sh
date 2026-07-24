#!/usr/bin/env bash
# Wrap the PyInstaller onedir (dist/PaperMeister) into a .app and a .dmg.
# Usage:  packaging/macos/create_dmg.sh <version-suffix> [<bare-version>]
#   e.g.  packaging/macos/create_dmg.sh v0.1.0-build42 0.1.0
# Uses `hdiutil` (ships with macOS) — robust on a headless CI runner, unlike
# create-dmg's AppleScript window layout. NOT code-signed: Gatekeeper will warn
# ("unidentified developer"); right-click → Open, or `xattr -dr com.apple.quarantine`.
set -euo pipefail

SUFFIX="${1:?usage: create_dmg.sh <version-suffix> [bare-version]}"
VER="${2:-0.0.0}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST="$ROOT/dist/PaperMeister"
APP="$ROOT/dist/PaperMeister.app"

[ -d "$DIST" ] || { echo "ERROR: $DIST not found (run pyinstaller first)"; exit 1; }

# Hand-build a .app from the onedir (exe + _internal live together in MacOS/).
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -R "$DIST/." "$APP/Contents/MacOS/"
chmod +x "$APP/Contents/MacOS/PaperMeister"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>PaperMeister</string>
  <key>CFBundleDisplayName</key><string>PaperMeister</string>
  <key>CFBundleExecutable</key><string>PaperMeister</string>
  <key>CFBundleIdentifier</key><string>com.jikhanjung.papermeister</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VER}</string>
  <key>CFBundleVersion</key><string>${VER}</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
</dict></plist>
PLIST

OUT="$ROOT/PaperMeister-macOS-$SUFFIX.dmg"
rm -f "$OUT"
hdiutil create -volname "PaperMeister" -srcfolder "$APP" -ov -format UDZO "$OUT"
echo "Built $OUT"
