#!/usr/bin/env bash
# Install prebuilt tarball on target (arm64) + optionally fetch testdata.
# Usage:
#   sudo scripts/install_prebuilt.sh --tarball dist/*.tar.gz --prefix /opt/camera-toolkit [--fetch-testdata full|slim|skip] [--yes]
set -euo pipefail

TARBALL=""
PREFIX="/opt/camera-toolkit"
FETCH="skip"
YES=0
NO_APT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tarball) TARBALL="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --fetch-testdata) FETCH="$2"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    --no-apt) NO_APT=1; shift ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$TARBALL" ]] || { echo "ERROR: --tarball required" >&2; exit 2; }
[[ -f "$TARBALL" ]] || { echo "ERROR: tarball not found: $TARBALL" >&2; exit 2; }

echo "== install =="
echo "  tarball : $TARBALL"
echo "  prefix  : $PREFIX"
echo "  testdata: $FETCH"

# 1. system deps (target installs them per policy; --no-apt for local install/ run)
if [[ $NO_APT -eq 1 ]]; then
  echo "[deps] skipped (--no-apt; for running straight from install/ folder)"
elif command -v apt-get >/dev/null 2>&1; then
  echo "[deps] apt install"
  DEPS="libavcodec60 libavformat60 libavutil58 libswscale7 libtiff6 libopenexr-3-1-30 libyaml-cpp0.8 python3-yaml python3-pip v4l-utils"
  if [[ $YES -eq 1 ]]; then
    apt-get update -qq && apt-get install -y $DEPS
  else
    echo "  will install: $DEPS"
    read -rp "  apt install now? [Y/n]: " ans; ans=${ans:-Y}
    [[ "$ans" =~ ^[Yy]$ ]] && { apt-get update -qq && apt-get install -y $DEPS; } || echo "  skip apt (may fail ldd later)"
  fi
  python3 -c "import openpyxl" 2>/dev/null || pip3 install --break-system-packages -q openpyxl || pip3 install -q openpyxl || echo "WARN: openpyxl install failed (xlsx disabled, json/log still work)"
else
  echo "[deps] no apt-get, skipping"
fi

# 2. unpack (robust for relative or absolute prefix, with or without top-level dir)
mkdir -p "$PREFIX"
echo "[unpack] $TARBALL -> $PREFIX"
_TMPD="$(mktemp -d)"
tar -xzf "$TARBALL" -C "$_TMPD"
# collapse single top-level dir (our camera-toolkit/ tarballs) into PREFIX
if [[ $(ls -A "$_TMPD" | wc -l) -eq 1 && -d "$_TMPD/$(ls -A "$_TMPD")" ]]; then
  cp -a "$_TMPD/$(ls -A "$_TMPD")/." "$PREFIX/"
else
  cp -a "$_TMPD/." "$PREFIX/"
fi
rm -rf "$_TMPD"
chmod +x "$PREFIX"/bin/* "$PREFIX"/scripts/* 2>/dev/null || true

# shellcheck disable=SC1091
source "$PREFIX/setup_vars.sh"

# 2b. arch gate: refuse x86 pkg on arm64 and vice versa
PKG_ARCH="$(file "$PREFIX/bin/opencv_camera_api_test_cpp" | grep -o -E "ARM aarch64|x86-64" || echo ?)"
HOST_ARCH="$(uname -m)"
if [[ "$PKG_ARCH" == *"aarch64"* && "$HOST_ARCH" != "aarch64" ]]; then
  echo "ERROR: aarch64 package on $HOST_ARCH host (use qemu or arm64 board)" >&2; exit 2
fi
if [[ "$PKG_ARCH" == "x86-64" && "$HOST_ARCH" == "aarch64" ]]; then
  echo "ERROR: x86-64 package on arm64 host" >&2; exit 2
fi
echo "[arch] pkg=$PKG_ARCH host=$HOST_ARCH"

# 3. ldd gate
echo "[check] ldd"
fail=0
for f in "$PREFIX"/bin/* "$PREFIX"/lib/libopencv_videoio.so*; do
  [[ -f "$f" ]] || continue
  if file "$f" | grep -q ELF; then
    if ldd "$f" 2>/dev/null | grep -q "not found"; then
      echo "  BROKEN: $f"; ldd "$f" | grep "not found" || true; fail=1
    fi
  fi
done
[[ $fail -eq 0 ]] && echo "  all ELF OK" || { echo "ERROR: fix apt deps above then re-run" >&2; exit 1; }

# 4. testdata fetch on target (full per decision; slim keeps stub for preflight)
if [[ "$FETCH" != "skip" ]]; then
  EXTRA="$PREFIX/opencv_extra"
  mkdir -p "$EXTRA"
  if [[ ! -d "$EXTRA/.git" ]]; then
    echo "[testdata] clone opencv_extra -> $EXTRA ($FETCH)"
    git clone --depth 1 --filter=blob:none --sparse https://github.com/opencv/opencv_extra.git "$EXTRA"
  fi
  if [[ "$FETCH" == "full" ]]; then
    git -C "$EXTRA" sparse-checkout add testdata/cv testdata/highgui 2>/dev/null || \
      git -C "$EXTRA" sparse-checkout set testdata/cv testdata/highgui
  else
    # slim: only what videoio actually reads (~33M) + stub cv/ for check_official_env
    git -C "$EXTRA" sparse-checkout add testdata/highgui testdata/cv/video testdata/cv/tracking 2>/dev/null || \
      git -C "$EXTRA" sparse-checkout set testdata/highgui testdata/cv/video testdata/cv/tracking
  fi
  du -sh "$EXTRA/testdata" 2>/dev/null || true
fi

# 5. smoke (no camera needed; qemu for cross pkg on x86 host)
echo "[smoke]"
if [[ "$PKG_ARCH" == *"aarch64"* && "$HOST_ARCH" != "aarch64" ]]; then
  _QEMU="$(command -v qemu-aarch64-static || command -v qemu-aarch64 || echo)"
  if [[ -n "$_QEMU" ]]; then
    export LD_LIBRARY_PATH="$PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    "$_QEMU" -L / "$PREFIX/bin/opencv_camera_api_test_cpp" --list-only >/dev/null && echo "  auto --list-only OK (qemu)"
    "$_QEMU" -L / "$PREFIX/bin/opencv_test_videoio" --gtest_list_tests 2>/dev/null | head -n 3 || true
  else
    echo "  SKIP smoke (aarch64 pkg on $HOST_ARCH without qemu; run on target board)"
  fi
else
if [[ -x "$PREFIX/bin/opencv_version" ]]; then
  "$PREFIX/bin/opencv_version"
else
  grep -oE '"opencv_version": "[^"]*"' "$PREFIX/VERSION.json" 2>/dev/null || echo "  (opencv_version app not packaged)"
fi
"$PREFIX/bin/opencv_camera_api_test_cpp" --list-only >/dev/null && echo "  auto --list-only OK"
"$PREFIX/bin/manual_suite" --list >/dev/null 2>&1 && echo "  manual --list OK" || echo "  manual --list (check flag)"
"$PREFIX/bin/opencv_test_videoio" --gtest_list_tests 2>/dev/null | head -n 3 || true
fi
echo "[done] prefix=$PREFIX  run: PREBUILT_ROOT=$PREFIX $PREFIX/scripts/run_test_auto.sh -d /dev/video0 --no-build"
