#!/bin/bash
# BuildHarvey macOS build, sign, and notarize script.
# Prerequisites:
#   - Active Apple Developer Program membership
#   - "Developer ID Application" certificate installed in Keychain
#   - pyinstaller installed in the virtual environment
#
# Usage: ./build_macos.sh
#   Set APPLE_IDENTITY before running, e.g.:
#   APPLE_IDENTITY="Developer ID Application: Your Name (TEAMID)" ./build_macos.sh

set -euo pipefail

IDENTITY="${APPLE_IDENTITY:-Developer ID Application: Your Name (TEAMID)}"

echo "==> Building with PyInstaller"
pyinstaller --name BuildHarvey --windowed \
  --icon=assets/icon.icns \
  --osx-bundle-identifier com.buildharvey.agent \
  --info-plist Info.plist \
  app.py

# ── Sign nested binaries (innermost first) ──────────────────────────────────

echo "==> Signing .so and .dylib files"
find dist/BuildHarvey.app -name "*.so" -o -name "*.dylib" | while read -r f; do
  codesign --force --sign "$IDENTITY" --options runtime "$f"
done

echo "==> Signing Python framework (if present)"
if [ -d "dist/BuildHarvey.app/Contents/Frameworks/Python.framework" ]; then
  codesign --force --sign "$IDENTITY" --options runtime \
    "dist/BuildHarvey.app/Contents/Frameworks/Python.framework"
fi

echo "==> Signing main executable"
codesign --force --sign "$IDENTITY" --options runtime \
  --entitlements BuildHarvey.entitlements \
  "dist/BuildHarvey.app/Contents/MacOS/BuildHarvey"

echo "==> Signing app bundle (must be last)"
codesign --force --sign "$IDENTITY" --options runtime \
  --entitlements BuildHarvey.entitlements \
  "dist/BuildHarvey.app"

# ── Verify ───────────────────────────────────────────────────────────────────

echo "==> Verifying signature"
codesign --verify --deep --strict dist/BuildHarvey.app
spctl --assess --type exec dist/BuildHarvey.app

# ── Package ──────────────────────────────────────────────────────────────────

echo "==> Creating DMG"
hdiutil create -volname BuildHarvey -srcfolder dist/BuildHarvey.app \
  -ov -format UDZO dist/BuildHarvey.dmg

echo "==> Build complete: dist/BuildHarvey.dmg"

# ── Notarization (uncomment and configure before release) ───────────────────
# Requires: xcrun notarytool credentials configured
#
# echo "==> Submitting for notarization"
# xcrun notarytool submit dist/BuildHarvey.dmg \
#   --apple-id "developer@email.com" \
#   --team-id "TEAMID" \
#   --password "app-specific-password" \
#   --wait
#
# echo "==> Stapling notarization ticket"
# xcrun stapler staple dist/BuildHarvey.dmg
#
# echo "==> Upload dist/BuildHarvey.dmg to Supabase Storage 'releases' bucket"
# echo "==> Then insert a row in app_releases with active=true"
