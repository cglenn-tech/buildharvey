#!/bin/bash
# BuildHarvey macOS build and sign script.
#
# Ad-hoc signing (no Apple Developer ID required — default):
#   ./build_macos.sh
#   Installation: right-click BuildHarvey → Open → Open (to bypass Gatekeeper)
#
# Developer ID signing (for notarization):
#   APPLE_IDENTITY="Developer ID Application: Your Name (TEAMID)" ./build_macos.sh

set -euo pipefail

VERSION="${BUILD_VERSION:-1.0.0}"
IDENTITY="${APPLE_IDENTITY:-}"

echo "==> Building with PyInstaller (version ${VERSION})"
ICON_ARG=""
if [ -f "assets/icon.icns" ]; then
  ICON_ARG="--icon=assets/icon.icns"
fi
# shellcheck disable=SC2086
pyinstaller --clean --name BuildHarvey --windowed \
  $ICON_ARG \
  --osx-bundle-identifier com.buildharvey.agent \
  --info-plist Info.plist \
  app.py

# ── Code signing ─────────────────────────────────────────────────────────────

if [ -n "$IDENTITY" ]; then
  echo "==> Signing with Developer ID: $IDENTITY"
  SIGN_OPTS="--options runtime"

  find dist/BuildHarvey.app -name "*.so" -o -name "*.dylib" | while read -r f; do
    codesign --force --sign "$IDENTITY" $SIGN_OPTS "$f" 2>/dev/null || true
  done

  if [ -d "dist/BuildHarvey.app/Contents/Frameworks/Python.framework" ]; then
    codesign --force --sign "$IDENTITY" $SIGN_OPTS \
      "dist/BuildHarvey.app/Contents/Frameworks/Python.framework"
  fi

  codesign --force --sign "$IDENTITY" $SIGN_OPTS \
    --entitlements BuildHarvey.entitlements \
    dist/BuildHarvey.app

  echo "==> Verifying Developer ID signature"
  codesign --verify --deep --strict dist/BuildHarvey.app
  spctl --assess --type exec dist/BuildHarvey.app
else
  echo "==> Ad-hoc code signing (no Developer ID required)"
  find dist/BuildHarvey.app -name "*.so" -o -name "*.dylib" | while read -r f; do
    codesign --force --sign - "$f" 2>/dev/null || true
  done
  codesign --force --sign - --deep \
    --entitlements BuildHarvey.entitlements \
    dist/BuildHarvey.app

  echo "==> Verifying ad-hoc signature"
  codesign --verify --deep dist/BuildHarvey.app
  echo "    NOTE: Gatekeeper will warn on first open. Instruct users:"
  echo "    Right-click BuildHarvey → Open → Open"
fi

# ── Package ──────────────────────────────────────────────────────────────────

echo "==> Creating DMG"
hdiutil create -volname BuildHarvey \
  -srcfolder dist/BuildHarvey.app \
  -ov -format UDZO \
  "dist/BuildHarvey-${VERSION}.dmg"

echo "==> Done: dist/BuildHarvey-${VERSION}.dmg"

# ── Notarization (Developer ID only — uncomment and configure) ───────────────
# Requires: xcrun notarytool credentials configured
#
# if [ -n "$IDENTITY" ]; then
#   echo "==> Submitting for notarization"
#   xcrun notarytool submit "dist/BuildHarvey-${VERSION}.dmg" \
#     --apple-id "developer@email.com" \
#     --team-id "TEAMID" \
#     --password "app-specific-password" \
#     --wait
#   echo "==> Stapling notarization ticket"
#   xcrun stapler staple "dist/BuildHarvey-${VERSION}.dmg"
# fi
