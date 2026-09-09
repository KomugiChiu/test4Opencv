#!/usr/bin/env bash
# Build all selfbuild artifacts for prebuilt packaging.
# Default native (host arch). Cross: --arch aarch64 (x86_64 -> aarch64 via
# cmake/toolchain-aarch64.cmake + apt multiarch arm64 dev packages).
# Usage:
#   scripts/build_prebuilt.sh [--arch native|aarch64] [--src-dir DIR] [--build-dir DIR] [--jobs N] [--branch B]
# Defaults: --arch native, --src-dir ./opencv_source_code/latest, --build-dir ./build/latest (native)
#           or ./build/aarch64 (cross, unless --build-dir overrides).
# Does NOT delete residue; fails if build dir contains stale Ubuntu20 ABI
# (libavcodec.so.58) — user cleans manually per policy.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RPATH_FRAG="$HERE/cmake/arm64-native.cmake"
CROSS_TC="$HERE/cmake/toolchain-aarch64.cmake"
ARCH="native"
SRC_DIR="$HERE/opencv_source_code/latest"
BUILD_DIR=""
JOBS="$(nproc)"
BRANCH=""
INSTALL_DEPS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch) ARCH="$2"; shift 2 ;;
    --src-dir) SRC_DIR="$2"; shift 2 ;;
    --build-dir) BUILD_DIR="$2"; shift 2 ;;
    --jobs|-j) JOBS="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --install-deps) INSTALL_DEPS=1; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[[ "$ARCH" == "native" || "$ARCH" == "aarch64" ]] || { echo "ERROR: --arch must be native|aarch64" >&2; exit 2; }
if [[ -z "$BUILD_DIR" ]]; then
  [[ "$ARCH" == "aarch64" ]] && BUILD_DIR="$HERE/build/aarch64" || BUILD_DIR="$HERE/build/latest"
fi
TOOLCHAIN_ARGS=(-C "$RPATH_FRAG")
if [[ "$ARCH" == "aarch64" ]]; then
  TOOLCHAIN_ARGS=(-DCMAKE_TOOLCHAIN_FILE="$CROSS_TC")
fi

echo "== prebuild =="
echo "  arch  : $ARCH"
echo "  src   : $SRC_DIR"
echo "  build : $BUILD_DIR"
echo "  jobs  : $JOBS"
echo "  host  : $(uname -m) $(lsb_release -ds 2>/dev/null || cat /etc/os-release | grep PRETTY | cut -d= -f2)"

for t in git cmake g++ python3; do
  command -v "$t" >/dev/null || { echo "ERROR: missing tool: $t" >&2; exit 2; }
done
if [[ "$ARCH" == "aarch64" && $INSTALL_DEPS -eq 1 ]]; then
  # One-shot cross-env bootstrap (needs sudo): multiarch arm64 + ports + toolchain + dev libs.
  echo "[deps] installing aarch64 cross toolchain + arm64 dev libs (sudo required)"
  sudo dpkg --add-architecture arm64
  if [[ ! -f /etc/apt/sources.list.d/ubuntu-ports.sources ]]; then
    printf '%s\n' 'Types: deb' 'URIs: http://ports.ubuntu.com/ubuntu-ports/' \
      'Suites: noble noble-updates noble-backports noble-security' \
      'Components: main restricted universe multiverse' 'Architectures: arm64' \
      'Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg' \
      | sudo tee /etc/apt/sources.list.d/ubuntu-ports.sources >/dev/null
  fi
  # Pin x86 repos to amd64 so apt won't look for arm64 on archive/security mirrors.
  if ! grep -q "Architectures: amd64" /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null; then
    sudo sed -i 's|^Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg$|Architectures: amd64\nSigned-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg|' \
      /etc/apt/sources.list.d/ubuntu.sources
  fi
  sudo apt-get update -qq
  sudo apt-get install -y g++-aarch64-linux-gnu gcc-aarch64-linux-gnu \
    libavcodec-dev:arm64 libavformat-dev:arm64 libavutil-dev:arm64 libswscale-dev:arm64 \
    libtiff-dev:arm64 libopenexr-dev:arm64 libyaml-cpp-dev:arm64
fi
if [[ "$ARCH" == "aarch64" ]]; then
  command -v aarch64-linux-gnu-g++ >/dev/null || { echo "ERROR: aarch64-linux-gnu-g++ missing (apt install g++-aarch64-linux-gnu)" >&2; exit 2; }
  # FFmpeg arm64 dev is mandatory per policy — fail early, no OFF fallback.
  if ! /usr/bin/aarch64-linux-gnu-pkg-config --exists libavcodec 2>/dev/null && \
     ! PKG_CONFIG_LIBDIR=/usr/lib/aarch64-linux-gnu/pkgconfig:/usr/lib/pkgconfig pkg-config --exists libavcodec 2>/dev/null; then
    if [[ ! -f /usr/aarch64-linux-gnu/lib/libavcodec.so && ! -f /usr/lib/aarch64-linux-gnu/libavcodec.so ]]; then
      echo "ERROR: arm64 FFmpeg dev missing (apt install libavcodec-dev:arm64 ...)" >&2
      exit 2
    fi
  fi
  for d in libyaml-cpp-dev:arm64 libtiff-dev:arm64; do :; done
  [[ -f /usr/lib/aarch64-linux-gnu/libyaml-cpp.so || -f /usr/aarch64-linux-gnu/lib/libyaml-cpp.so ]] || \
    echo "WARN: arm64 yaml-cpp dev not found in sysroot (manual_cpp may fail)" >&2
fi

# 0. source checkout (shallow 5.x unless --branch given)
if [[ ! -d "$SRC_DIR/.git" ]]; then
  echo "[src] cloning opencv -> $SRC_DIR"
  args=(git clone --depth 1)
  [[ -n "$BRANCH" && "$BRANCH" != "latest" ]] && args+=(--branch "$BRANCH")
  "${args[@]}" https://github.com/opencv/opencv.git "$SRC_DIR"
else
  echo "[src] keep existing: $SRC_DIR ($(git -C "$SRC_DIR" rev-parse --short HEAD 2>/dev/null || echo ?))"
fi

# 1. Guard: refuse to incremental-build over Ubuntu20 residue (native ldd only)
if [[ "$ARCH" == "native" && -f "$BUILD_DIR/lib/libopencv_videoio.so.5.1.0" ]]; then
  if ldd "$BUILD_DIR/lib/libopencv_videoio.so.5.1.0" 2>/dev/null | grep -q "not found"; then
    echo "ERROR: $BUILD_DIR contains stale binaries (ldd not found)." >&2
    echo "  Policy: user cleans manually, e.g. mv build/latest build/latest.ubuntu20.bak" >&2
    exit 2
  fi
fi

# 2. OpenCV selfbuild (shared with official suite)
echo "[opencv] cmake $SRC_DIR -> $BUILD_DIR (arch=$ARCH)"
# shellcheck disable=SC2089
cmake -S "$SRC_DIR" -B "$BUILD_DIR" \
  "${TOOLCHAIN_ARGS[@]}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_LIST=core,imgproc,imgcodecs,videoio,highgui,ts \
  -DBUILD_TESTS=ON -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_opencv_apps=OFF \
  -DWITH_IPP=OFF -DWITH_ITT=OFF -DWITH_OPENCL=OFF -DWITH_GTK=OFF
cmake --build "$BUILD_DIR" --target opencv_test_videoio -j"$JOBS"

# Cross uses isolated consumer build dirs to avoid clobbering native outputs.
AUTO_B="$HERE/auto_cpp/build"; MANUAL_B="$HERE/manual_cpp/build"
if [[ "$ARCH" == "aarch64" ]]; then
  AUTO_B="$HERE/auto_cpp/build-aarch64"; MANUAL_B="$HERE/manual_cpp/build-aarch64"
fi

# 3. auto_cpp (relocatable $ORIGIN)
echo "[auto_cpp] configure + build -> $AUTO_B"
cmake -S "$HERE/auto_cpp" -B "$AUTO_B" \
  "${TOOLCHAIN_ARGS[@]}" \
  -DCPP_OPENCV_SOURCE=selfbuild \
  -DOPENCV_SOURCE_DIR="$SRC_DIR" \
  -DOPENCV_BUILD_DIR="$BUILD_DIR" \
  -DOpenCV_DIR="$BUILD_DIR"
cmake --build "$AUTO_B" -j"$JOBS"

# 4. manual_cpp (relocatable $ORIGIN)
echo "[manual_cpp] configure + build -> $MANUAL_B"
cmake -S "$HERE/manual_cpp" -B "$MANUAL_B" \
  "${TOOLCHAIN_ARGS[@]}" \
  -DCPP_OPENCV_SOURCE=selfbuild \
  -DOPENCV_SOURCE_DIR="$SRC_DIR" \
  -DOPENCV_BUILD_DIR="$BUILD_DIR" \
  -DOpenCV_DIR="$BUILD_DIR" \
  -DCMAKE_PREFIX_PATH="$BUILD_DIR"
cmake --build "$MANUAL_B" -j"$JOBS"

# 5. sanity
if [[ "$ARCH" == "aarch64" ]]; then
  echo "[check] cross arch (file, no ldd)"
  for f in "$AUTO_B/opencv_camera_api_test_cpp" "$MANUAL_B/manual_suite" \
           "$BUILD_DIR/bin/opencv_test_videoio"; do
    file "$f" | grep -q "ARM aarch64" && echo "  OK arch: $f" || { echo "  WRONG ARCH: $f"; file "$f"; exit 1; }
    if readelf -d "$f" 2>/dev/null | grep -q "not found"; then echo "  BROKEN: $f"; exit 1; fi
  done
  echo "  run: bash scripts/verify_cross.sh --build-dir $BUILD_DIR --auto-build $AUTO_B --manual-build $MANUAL_B"
else
echo "[check] ldd"
missing=0
for f in "$HERE/auto_cpp/build/opencv_camera_api_test_cpp" \
         "$HERE/manual_cpp/build/manual_suite" \
         "$BUILD_DIR/bin/opencv_test_videoio" \
         "$BUILD_DIR/lib/libopencv_videoio.so.5.1.0"; do
  if ldd "$f" 2>/dev/null | grep -q "not found"; then
    echo "  BROKEN: $f"; ldd "$f" | grep "not found" || true; missing=1
  else
    echo "  OK: $f"
  fi
done
[[ $missing -eq 0 ]] || { echo "ERROR: ldd failures above" >&2; exit 1; }
fi

# 6. VERSION.json provenance
_ocv_version_from_header() {
  local hdr="$SRC_DIR/modules/core/include/opencv2/core/version.hpp"
  local maj min rev status
  maj=$(grep -E "#define CV_VERSION_MAJOR" "$hdr" 2>/dev/null | awk '{print $NF}')
  min=$(grep -E "#define CV_VERSION_MINOR" "$hdr" 2>/dev/null | awk '{print $NF}')
  rev=$(grep -E "#define CV_VERSION_REVISION" "$hdr" 2>/dev/null | awk '{print $NF}')
  status=$(grep -E "#define CV_VERSION_STATUS" "$hdr" 2>/dev/null | sed 's/.*CV_VERSION_STATUS *"\(.*\)".*/\1/')
  if [[ -n "$maj" && -n "$min" ]]; then
    # CV_VERSION_STATUS already carries its leading dash (e.g. "-dev")
    echo "${maj}.${min}.${rev:-0}${status:-}"
  else
    grep -m1 -oE 'set\(OpenCV_VERSION "?[0-9][^" )]*' "$BUILD_DIR/OpenCVConfig.cmake" 2>/dev/null | grep -oE '[0-9].*' || echo "?"
  fi
}
if [[ "$ARCH" == "aarch64" ]]; then
  _QEMU="$(command -v qemu-aarch64-static || command -v qemu-aarch64 || echo)"
  if [[ -n "$_QEMU" && -x "$BUILD_DIR/bin/opencv_version" ]]; then
    OCV_VER="$($_QEMU -L / "$BUILD_DIR/bin/opencv_version" 2>/dev/null || _ocv_version_from_header)"
  else
    OCV_VER="$(_ocv_version_from_header)"
  fi
else
if [[ -x "$BUILD_DIR/bin/opencv_version" ]]; then
OCV_VER="$("$BUILD_DIR/bin/opencv_version" 2>/dev/null || _ocv_version_from_header)"
else
OCV_VER="$(_ocv_version_from_header)"
fi
fi
OCV_COMMIT="$(git -C "$SRC_DIR" rev-parse --short HEAD 2>/dev/null || echo ?)"
FFMPEG_VER="$(ffmpeg -version 2>/dev/null | head -n1 || echo ?)"
EFFECTIVE_ARCH="$ARCH"
[[ "$ARCH" == "aarch64" ]] && EFFECTIVE_ARCH="aarch64" || EFFECTIVE_ARCH="$(uname -m)"
cat > "$BUILD_DIR/VERSION.json" <<EOF
{
  "opencv_version": "$OCV_VER",
  "opencv_commit": "$OCV_COMMIT",
  "ffmpeg": "$FFMPEG_VER",
  "arch": "$EFFECTIVE_ARCH",
  "cross": $([[ "$ARCH" == "aarch64" ]] && echo true || echo false),
  "os": "$(lsb_release -ds 2>/dev/null || grep PRETTY_NAME /etc/os-release | cut -d= -f2)",
  "built_at": "$(date -u +%FT%TZ)"
}
EOF
echo "[done] $BUILD_DIR/VERSION.json"
cat "$BUILD_DIR/VERSION.json"
