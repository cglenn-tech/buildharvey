#!/bin/bash
# Developer tool: upload a built release to Supabase Storage and register it.
# NEVER bundled in the app. SUPABASE_SERVICE_KEY stays on the developer's machine.
#
# Usage:
#   ./publish.sh macos 1.0.0 dist/BuildHarvey-1.0.0.dmg
#   ./publish.sh windows 1.0.0 Output/BuildHarveySetup-1.0.0.exe

set -euo pipefail

PLATFORM="${1:?Usage: publish.sh <macos|windows> <version> <file>}"
VERSION="${2:?}"
FILE="${3:?}"

if [ ! -f "$FILE" ]; then
  echo "ERROR: File not found: $FILE"
  exit 1
fi

if [ "$PLATFORM" = "macos" ]; then
  EXT="dmg"
elif [ "$PLATFORM" = "windows" ]; then
  EXT="exe"
else
  echo "ERROR: Platform must be 'macos' or 'windows'"
  exit 1
fi

STORAGE_PATH="${PLATFORM}/BuildHarvey-${VERSION}.${EXT}"

# Load environment from .env (requires SUPABASE_URL and SUPABASE_SERVICE_KEY)
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${SUPABASE_URL:?SUPABASE_URL must be set in .env}"
: "${SUPABASE_SERVICE_KEY:?SUPABASE_SERVICE_KEY must be set in .env}"

echo "==> Computing SHA-256"
SHA256=$(shasum -a 256 "$FILE" | awk '{print $1}')
echo "    $SHA256  $FILE"

echo "==> Uploading to releases/${STORAGE_PATH}"
curl -sf -X POST \
  "${SUPABASE_URL}/storage/v1/object/releases/${STORAGE_PATH}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_KEY}" \
  -H "Content-Type: application/octet-stream" \
  --data-binary "@${FILE}"

echo "==> Deactivating previous active release for platform: ${PLATFORM}"
curl -sf -X PATCH \
  "${SUPABASE_URL}/rest/v1/app_releases?platform=eq.${PLATFORM}&active=eq.true" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_KEY}" \
  -H "apikey: ${SUPABASE_SERVICE_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"active":false}'

echo "==> Registering new release"
curl -sf -X POST \
  "${SUPABASE_URL}/rest/v1/app_releases" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_KEY}" \
  -H "apikey: ${SUPABASE_SERVICE_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"platform\":\"${PLATFORM}\",\"version\":\"${VERSION}\",\"storage_path\":\"${STORAGE_PATH}\",\"sha256\":\"${SHA256}\",\"active\":true}"

echo "==> Published ${PLATFORM} v${VERSION}"
