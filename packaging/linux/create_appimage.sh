#!/usr/bin/env bash
# Wrap the PyInstaller onedir (dist/PaperMeister) into an AppImage.
# Usage:  packaging/linux/create_appimage.sh <version-suffix>
#   e.g.  packaging/linux/create_appimage.sh v0.1.0-build42
# Needs `appimagetool` on PATH (CI downloads it). Run after `pyinstaller`.
set -euo pipefail

SUFFIX="${1:?usage: create_appimage.sh <version-suffix>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST="$ROOT/dist/PaperMeister"
APPDIR="$ROOT/AppDir"
OUT="$ROOT/build_linux"

[ -d "$DIST" ] || { echo "ERROR: $DIST not found (run pyinstaller first)"; exit 1; }

rm -rf "$APPDIR" "$OUT"
mkdir -p "$APPDIR/usr/lib/PaperMeister" "$OUT"
cp -r "$DIST/." "$APPDIR/usr/lib/PaperMeister/"

# Entry point → launch the frozen executable.
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/PaperMeister/PaperMeister" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/PaperMeister.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=PaperMeister
Exec=PaperMeister
Icon=PaperMeister
Categories=Office;Science;
EOF

# Placeholder icon (Pillow is a runtime dependency). Swap for a real icon later.
python - "$APPDIR/PaperMeister.png" <<'PY'
import sys
from PIL import Image, ImageDraw
img = Image.new("RGB", (256, 256), (24, 26, 31))
ImageDraw.Draw(img).text((104, 116), "PM", fill=(120, 170, 255))
img.save(sys.argv[1])
PY
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp "$APPDIR/PaperMeister.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/PaperMeister.png"

# EXTRACT_AND_RUN avoids needing FUSE on the build runner.
APPIMAGE_EXTRACT_AND_RUN=1 appimagetool "$APPDIR" "$OUT/PaperMeister-Linux-$SUFFIX.AppImage"
echo "Built $OUT/PaperMeister-Linux-$SUFFIX.AppImage"
