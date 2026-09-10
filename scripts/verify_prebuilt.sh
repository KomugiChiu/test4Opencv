#!/usr/bin/env bash
# Verify prebuilt artifacts in place (no packaging): RPATH/ldd/smoke.
# Usage: scripts/verify_prebuilt.sh [--opencv-test-build-dir DIR]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENCV_TEST_BUILD_DIR="$HERE/build/latest"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --opencv-test-build-dir) OPENCV_TEST_BUILD_DIR="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
fail=0
echo "== verify $OPENCV_TEST_BUILD_DIR =="
# $ORIGIN-RPATH binaries resolve selfbuild libs via this dir (same as runtime setup_vars.sh).
export LD_LIBRARY_PATH="$OPENCV_TEST_BUILD_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
for f in "$HERE/auto_cpp/build/opencv_camera_api_test_cpp" \
         "$HERE/manual_cpp/build/manual_suite" \
         "$OPENCV_TEST_BUILD_DIR/bin/opencv_test_videoio" \
         "$OPENCV_TEST_BUILD_DIR/lib/libopencv_videoio.so.5.1.0"; do
  [[ -f "$f" ]] || { echo "MISSING: $f"; fail=1; continue; }
  if ldd "$f" 2>/dev/null | grep -q "not found"; then
    echo "BROKEN: $f"; ldd "$f" | grep "not found" || true; fail=1
  else
    echo "OK ldd: $f"
  fi
  if readelf -d "$f" 2>/dev/null | grep -q "/home/"; then
    echo "FLAG relocatable: $f has absolute /home/ RUNPATH (fixed at package time via patchelf)"
  fi
done
if [[ -x "$OPENCV_TEST_BUILD_DIR/bin/opencv_version" ]]; then
LD_LIBRARY_PATH="$OPENCV_TEST_BUILD_DIR/lib:${LD_LIBRARY_PATH:-}" "$OPENCV_TEST_BUILD_DIR/bin/opencv_version"
fi
LD_LIBRARY_PATH="$OPENCV_TEST_BUILD_DIR/lib:${LD_LIBRARY_PATH:-}" "$HERE/auto_cpp/build/opencv_camera_api_test_cpp" --list-only >/dev/null && echo "OK smoke: auto --list-only"
[[ $fail -eq 0 ]] && echo "VERIFY PASS" || { echo "VERIFY FAIL" >&2; exit 1; }
