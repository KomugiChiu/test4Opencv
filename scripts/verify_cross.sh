#!/usr/bin/env bash
# Verify aarch64 cross artifacts on x86_64 host (no native ldd/exec).
# Usage: scripts/verify_cross.sh [--build-dir DIR] [--auto-build DIR] [--manual-build DIR]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$HERE/build/aarch64"
AUTO_B="$HERE/auto_cpp/build-aarch64"
MANUAL_B="$HERE/manual_cpp/build-aarch64"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-dir) BUILD_DIR="$2"; shift 2 ;;
    --auto-build) AUTO_B="$2"; shift 2 ;;
    --manual-build) MANUAL_B="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
fail=0
QEMU="$(command -v qemu-aarch64-static || command -v qemu-aarch64 || echo)"
echo "== verify_cross $BUILD_DIR =="
for f in "$AUTO_B/opencv_camera_api_test_cpp" "$MANUAL_B/manual_suite" \
         "$BUILD_DIR/bin/opencv_test_videoio" "$BUILD_DIR/lib/libopencv_videoio.so.5.1.0"; do
  [[ -f "$f" ]] || { echo "MISSING: $f"; fail=1; continue; }
  if file "$f" | grep -q "ARM aarch64"; then echo "OK arch: $f"; else echo "WRONG ARCH: $f ($(file -b "$f"))"; fail=1; continue; fi
  if readelf -d "$f" 2>/dev/null | grep -q "/home/"; then
    echo "FLAG relocatable: $f has absolute /home/ RUNPATH"
  else
    echo "OK rpath: $f"
  fi
done
if [[ -z "$QEMU" ]]; then
  echo "SKIP qemu smoke (qemu-aarch64-static missing)"
else
  # Guest linker needs the cross-built libs: LD_LIBRARY_PATH is honored by qemu-user.
  export LD_LIBRARY_PATH="$BUILD_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export QEMU_LD_PREFIX="/"
  if [[ -x "$BUILD_DIR/bin/opencv_version" ]]; then
    "$QEMU" -L / "$BUILD_DIR/bin/opencv_version" && echo "OK smoke: opencv_version" || fail=1
  else
    echo "SKIP opencv_version (apps disabled at build)"
  fi
  "$QEMU" -L / "$AUTO_B/opencv_camera_api_test_cpp" --list-only >/dev/null \
    && echo "OK smoke: auto --list-only" || { echo "FAIL smoke: auto --list-only"; fail=1; }
  "$QEMU" -L / "$BUILD_DIR/bin/opencv_test_videoio" --gtest_list_tests 2>/dev/null | head -n 3 || true
fi
[[ $fail -eq 0 ]] && echo "VERIFY_CROSS PASS" || { echo "VERIFY_CROSS FAIL" >&2; exit 1; }
