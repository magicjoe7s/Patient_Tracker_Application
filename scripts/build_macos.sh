#!/bin/bash

set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

python_bin="${PYTHON_BIN:-python3}"
export MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-13.0}"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "The macOS release must be built on macOS." >&2
    exit 2
fi

pytest_root="$(mktemp -d "${TMPDIR:-/tmp}/icu-patient-tracker-pytest.XXXXXX")"
build_root="$(mktemp -d "${TMPDIR:-/tmp}/icu-patient-tracker-build.XXXXXX")"
smoke_root="$(mktemp -d "${TMPDIR:-/tmp}/icu-patient-tracker-smoke.XXXXXX")"
stage_root="$(mktemp -d "${TMPDIR:-/tmp}/icu-patient-tracker-dmg.XXXXXX")"
cleanup() {
    rm -rf "$pytest_root" "$build_root" "$smoke_root" "$stage_root"
}
trap cleanup EXIT

"$python_bin" -m pip install -e ".[dev,release]"

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
    "$python_bin" -m ruff check src tests
    "$python_bin" -m mypy src/icu_patient_tracker
    "$python_bin" -m pytest -q --basetemp="$pytest_root"
fi

icon_source="$project_root/assets/design/icu-patient-tracker-master.png"
iconset="$build_root/ICUPatientTracker.iconset"
mkdir -p "$iconset"
sips -z 16 16 "$icon_source" --out "$iconset/icon_16x16.png" >/dev/null
sips -z 32 32 "$icon_source" --out "$iconset/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$icon_source" --out "$iconset/icon_32x32.png" >/dev/null
sips -z 64 64 "$icon_source" --out "$iconset/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$icon_source" --out "$iconset/icon_128x128.png" >/dev/null
sips -z 256 256 "$icon_source" --out "$iconset/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$icon_source" --out "$iconset/icon_256x256.png" >/dev/null
sips -z 512 512 "$icon_source" --out "$iconset/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$icon_source" --out "$iconset/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$icon_source" --out "$iconset/icon_512x512@2x.png" >/dev/null
icon_path="$build_root/ICUPatientTracker.icns"
iconutil -c icns "$iconset" -o "$icon_path"

export ICU_MACOS_ICON="$icon_path"
architecture="$(uname -m)"
dist_root="$project_root/dist/macos-$architecture"
rm -rf "$dist_root"
mkdir -p "$dist_root"
"$python_bin" -m PyInstaller \
    --clean \
    --noconfirm \
    --distpath "$dist_root" \
    --workpath "$build_root/pyinstaller" \
    packaging/icu_patient_tracker_macos.spec

app_path="$dist_root/ICU Patient Tracker.app"
if [[ -n "${MACOS_SIGNING_IDENTITY:-}" ]]; then
    codesign --force --deep --options runtime --timestamp \
        --sign "$MACOS_SIGNING_IDENTITY" "$app_path"
    codesign --verify --deep --strict --verbose=2 "$app_path"
else
    echo "Warning: building without Developer ID signing; other Macs may block this app." >&2
fi

"$app_path/Contents/MacOS/ICU Patient Tracker" --smoke-test "$smoke_root"

version="$($python_bin -c "from importlib.metadata import version; print(version('icu-patient-tracker'))")"
artifact_base="icu-patient-tracker-$version-macos-$architecture"
cp -R "$app_path" "$stage_root/"
ln -s /Applications "$stage_root/Applications"
dmg_path="$project_root/dist/$artifact_base.dmg"
rm -f "$dmg_path"
hdiutil create \
    -volname "ICU Patient Tracker" \
    -srcfolder "$stage_root" \
    -ov \
    -format UDZO \
    "$dmg_path" >/dev/null

if [[ -n "${MACOS_SIGNING_IDENTITY:-}" ]]; then
    codesign --force --timestamp --sign "$MACOS_SIGNING_IDENTITY" "$dmg_path"
fi
if [[ -n "${MACOS_NOTARY_PROFILE:-}" ]]; then
    notary_arguments=(--keychain-profile "$MACOS_NOTARY_PROFILE")
    if [[ -n "${MACOS_NOTARY_KEYCHAIN:-}" ]]; then
        notary_arguments+=(--keychain "$MACOS_NOTARY_KEYCHAIN")
    fi
    xcrun notarytool submit "$dmg_path" "${notary_arguments[@]}" --wait
    xcrun stapler staple "$dmg_path"
fi

digest="$(shasum -a 256 "$dmg_path" | awk '{print $1}')"
printf '%s  %s\n' "$digest" "$(basename "$dmg_path")" > "$project_root/dist/SHA256SUMS-macos-$architecture.txt"
echo "macOS release verified: $dmg_path"
echo "SHA-256: $digest"
