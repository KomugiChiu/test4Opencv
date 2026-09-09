#!/usr/bin/env bash
# Package prebuilt binaries into a relocatable tarball (no testdata, no source).
# Usage: scripts/package_prebuilt.sh [--arch native|aarch64] [--build-dir DIR] [--auto-build DIR] [--manual-build DIR] [--out dist/NAME.tar.gz]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH_ARG=""
BUILD_DIR=""
AUTO_B=""
MANUAL_B=""
OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch) ARCH_ARG="$2"; shift 2 ;;
    --build-dir) BUILD_DIR="$2"; shift 2 ;;
    --auto-build) AUTO_B="$2"; shift 2 ;;
    --manual-build) MANUAL_B="$2"; shift 2 ;;
    --out|-o) OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
# Defaults follow build_prebuilt.sh layout.
if [[ -z "$BUILD_DIR" ]]; then
  [[ "$ARCH_ARG" == "aarch64" ]] && BUILD_DIR="$HERE/build/aarch64" || BUILD_DIR="$HERE/build/latest"
fi
if [[ -z "$AUTO_B" ]]; then
  [[ "$BUILD_DIR" == *aarch64* ]] && AUTO_B="$HERE/auto_cpp/build-aarch64" || AUTO_B="$HERE/auto_cpp/build"
fi
if [[ -z "$MANUAL_B" ]]; then
  [[ "$BUILD_DIR" == *aarch64* ]] && MANUAL_B="$HERE/manual_cpp/build-aarch64" || MANUAL_B="$HERE/manual_cpp/build"
fi

OCV_VER="$("$BUILD_DIR/bin/opencv_version" 2>/dev/null || echo 5.1.0-dev)"
ARCH="$(uname -m)"
[[ -z "$OUT" ]] && OUT="$HERE/dist/camera-toolkit-${ARCH}-ocv${OCV_VER}.tar.gz"

STAGE="$(mktemp -d)"
ROOT="$STAGE/camera-toolkit"
mkdir -p "$ROOT/bin" "$ROOT/lib" "$ROOT/scripts" "$ROOT/manual_cpp"

echo "== package =="
echo "  build : $BUILD_DIR"
echo "  out   : $OUT"

# 1. binaries
cp -a "$AUTO_B/opencv_camera_api_test_cpp" "$ROOT/bin/"
cp -a "$MANUAL_B/manual_suite" "$MANUAL_B/manual_cpp" \
      "$MANUAL_B/exposure_check" "$MANUAL_B/autofocus_check" \
      "$MANUAL_B/white_balance_check" "$MANUAL_B/reconnect_test" "$ROOT/bin/"
cp -a "$BUILD_DIR/bin/opencv_test_videoio" "$ROOT/bin/"
[[ -f "$BUILD_DIR/bin/opencv_version" ]] && cp -a "$BUILD_DIR/bin/opencv_version" "$ROOT/bin/" || true

# 2. selfbuild libs (versioned .so chain only, no .a / cmake junk)
for f in "$BUILD_DIR"/lib/libopencv_*.so*; do
  case "$f" in *.a) continue;; *) cp -a "$f" "$ROOT/lib/";; esac
done

# 3. test scripts (run without rebuild via --no-build / PREBUILT_ROOT)
cp -a "$HERE/auto_cpp/run_test.sh" "$ROOT/scripts/run_test_auto.sh"
cp -a "$HERE/manual_cpp/run_test.sh" "$ROOT/scripts/run_test_manual.sh"
cp -a "$HERE/official/run_official_videoio_test.py" "$ROOT/scripts/"
cp -a "$HERE/auto_cpp/tools/make_report_xlsx.py" "$ROOT/scripts/"
cp -a "$HERE/generate_combined_report.py" "$ROOT/scripts/"
cp -a "$HERE/run_cpp_tests.sh" "$ROOT/scripts/" 2>/dev/null || true
cp -a "$HERE/manual_cpp/manifest_manual.yaml" "$ROOT/manual_cpp/" 2>/dev/null || \
  cp -a "$HERE/manual/manifest_manual.yaml" "$ROOT/manual_cpp/" 2>/dev/null || true
[[ -f "$BUILD_DIR/VERSION.json" ]] && cp -a "$BUILD_DIR/VERSION.json" "$ROOT/"
cp -a "$HERE/run_config.default.yaml" "$ROOT/run_config.prebuilt.yaml"

cat > "$ROOT/setup_vars.sh" <<'EOF'
# shellcheck disable=SC2148
# Relocatable env: prefer $ORIGIN RPATH; LD_LIBRARY_PATH is a fallback.
_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LD_LIBRARY_PATH="$_ROOT/lib${LD_LIBRARY_PATH:+:$_ROOT/lib:$LD_LIBRARY_PATH}"
export PREBUILT_ROOT="$_ROOT"
export CPP_OPENCV_SOURCE=selfbuild
export OPENCV_BUILD_DIR="$_ROOT"
EOF

# 4. RPATH fix -> $ORIGIN (best effort; build already uses cmake/arm64-native.cmake)
if command -v patchelf >/dev/null 2>&1; then
  echo "[rpath] patchelf -> \$ORIGIN"
  for f in "$ROOT"/bin/* "$ROOT"/lib/*.so.*; do
    [[ -f "$f" ]] || continue
    if file "$f" | grep -q ELF; then
      patchelf --set-rpath '$ORIGIN:$ORIGIN/../lib' "$f" 2>/dev/null || true
    fi
  done
else
  echo "[rpath] patchelf not found, keeping build-time RPATH (needs LD_LIBRARY_PATH fallback)"
fi

# 5. guards: arch-aware (native ldd vs cross file/readelf)
STAGED_BIN="$ROOT/bin/opencv_camera_api_test_cpp"
if file "$STAGED_BIN" | grep -q "ARM aarch64"; then
  echo "[guard] cross artifact (aarch64), skipping host ldd"
else
if ldd "$STAGED_BIN" 2>/dev/null | grep -q "not found"; then
  echo "ERROR: staged binary has missing .so (builder/target OS mismatch?)" >&2
  ldd "$STAGED_BIN" | grep "not found" || true
  exit 1
fi
fi

# 6. tarball
mkdir -p "$(dirname "$OUT")"
tar -C "$STAGE" -czf "$OUT" camera-toolkit
sha256sum "$OUT" | tee "$OUT.sha256"
rm -rf "$STAGE"
echo "[done] $OUT ($(du -sh "$OUT" | cut -f1))"
echo "  NOTE: testdata excluded by design; target runs install_prebuilt.sh --fetch-testdata full"
