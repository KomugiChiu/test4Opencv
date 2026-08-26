#!/usr/bin/env bash
# Convenience wrapper for the C++ auto test suite
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/build/opencv_camera_api_test_cpp"

_yaml_val() {
  local cfg="$HERE/../run_config.yaml"
  if [[ -f "$cfg" ]]; then
    python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print(c.get(*sys.argv[2:],'' ))" "$cfg" "${@}" 2>/dev/null | tr -d '\n\r '
  else
    echo ""
  fi
}
CPP_SOURCE="${CPP_OPENCV_SOURCE:-$(python3 -c "import yaml; print(yaml.safe_load(open('$HERE/../run_config.yaml')).get('cpp',{}).get('source','apt'))" 2>/dev/null || echo 'apt')}"
_branch="$(python3 -c "import yaml; print(yaml.safe_load(open('$HERE/../run_config.yaml')).get('cpp',{}).get('branch','latest'))" 2>/dev/null || echo 'latest')"

_resolve_versioned() {
  local base="$1" branch="$2"
  base="${base%/}"
  [[ -z "$base" ]] && base="."
  local last="${base##*/}"
  [[ "$last" == "$branch" ]] && echo "$base" || echo "$base/$branch"
}

if [[ "$CPP_SOURCE" == "selfbuild" ]]; then
  _src_base="$(python3 -c "import yaml; print(yaml.safe_load(open('$HERE/../run_config.yaml')).get('cpp',{}).get('source_dir','./opencv_source_code'))" 2>/dev/null | tr -d '\n\r ')"
  _build_base="$(python3 -c "import yaml; print(yaml.safe_load(open('$HERE/../run_config.yaml')).get('cpp',{}).get('build_dir','./build'))" 2>/dev/null | tr -d '\n\r ')"
  # Strip any existing version suffix
  _src_base="${_src_base%/*}"
  _build_base="${_build_base%/*}"
  [[ -z "$_src_base" || "$_src_base" == "." ]] && _src_base="./opencv_source_code"
  [[ -z "$_build_base" ]] && _build_base="./build"
  OCV_SRC="$(_resolve_versioned "$_src_base" "$_branch")"
  OCV_BUILD="$(_resolve_versioned "$_build_base" "$_branch")"
else
  OCV_BUILD="/usr"
  OCV_SRC="/usr/include/opencv4"
fi
export CPP_OPENCV_SOURCE="$CPP_SOURCE"
export OPENCV_SOURCE_DIR="$OCV_SRC"
export OPENCV_BUILD_DIR="$OCV_BUILD"

FORCE_REBUILD=0
DEVICE="/dev/video0"
ARGS=()
RAW_HAS_DEVICE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--device) DEVICE="$2"; ARGS+=("$1" "$2"); RAW_HAS_DEVICE=1; shift 2 ;;
    --backend|--frames|--width|--height|--fps|--outdir|-o|--json)
      ARGS+=("$1" "$2"); shift 2 ;;
    --list-only|--no-full-sweep|--no-xlsx) ARGS+=("$1"); shift ;;
    --rebuild) FORCE_REBUILD=1; shift ;;
    -h|--help) ARGS+=("$1"); shift ;;
    --) shift; ARGS+=("$@"); break ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

if [[ "$DEVICE" =~ ^[0-9]+$ ]]; then DEVICE_NORM="/dev/video$DEVICE"; else DEVICE_NORM="$DEVICE"; fi

if [[ $RAW_HAS_DEVICE -eq 0 ]]; then
  HAS_DEVICE=0
  for a in "${ARGS[@]:-}"; do [[ "$a" == "--device" || "$a" == "-d" ]] && HAS_DEVICE=1; done
  [[ $HAS_DEVICE -eq 0 ]] && ARGS=(--device "$DEVICE" "${ARGS[@]}")
fi

_check_apt_opencv() {
  local pkg="libopencv-dev"
  local yaml_pkg
  yaml_pkg="$(python3 -c "import yaml; print(yaml.safe_load(open('$HERE/../run_config.yaml')).get('cpp',{}).get('apt_package','libopencv-dev'))" 2>/dev/null | tr -d '\n\r ')"
  [[ -n "$yaml_pkg" ]] && pkg="$yaml_pkg"
  if dpkg -s "$pkg" >/dev/null 2>&1; then
    local ver
    ver="$(pkg-config --modversion opencv4 2>/dev/null || echo '?')"
    echo "[auto_cpp] apt source: $pkg $ver (/usr/include/opencv4)" >&2
    return 0
  fi
  echo "[auto_cpp] $pkg not installed, attempting install..." >&2
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y "$pkg" >&2 && return 0
  fi
  echo "[auto_cpp] ERROR: cannot install $pkg. Install manually: sudo apt install $pkg" >&2
  return 1
}

_ensure_selfbuild() {
  if [[ ! -d "$OCV_SRC/.git" ]]; then
    if [[ "$_branch" == "latest" ]]; then
      echo "[auto_cpp] cloning opencv HEAD -> $OCV_SRC" >&2
      git clone --depth 1 https://github.com/opencv/opencv.git "$OCV_SRC" >&2
    else
      echo "[auto_cpp] cloning opencv $_branch -> $OCV_SRC" >&2
      git clone --depth 1 --branch "$_branch" https://github.com/opencv/opencv.git "$OCV_SRC" >&2
    fi
  elif [[ "$_branch" == "latest" && "$FORCE_REBUILD" == 1 ]]; then
    git -C "$OCV_SRC" fetch --depth 1 origin HEAD 2>&1 | tail -n 3 || true
    git -C "$OCV_SRC" reset --hard FETCH_HEAD 2>&1 | tail -n 3 || true
  fi
  if [[ ! -f "$OCV_BUILD/lib/libopencv_core.so" && ! -f "$OCV_BUILD/lib64/libopencv_core.so" ]]; then
    echo "[auto_cpp] cmake $OCV_SRC -> $OCV_BUILD" >&2
    cmake -S "$OCV_SRC" -B "$OCV_BUILD" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=ON -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_LIST=core,imgproc,imgcodecs,videoio,ts >&2
    cmake --build "$OCV_BUILD" -j"$(nproc)" >&2
  fi
}

build() {
  if [[ "$CPP_SOURCE" == "apt" ]]; then
    _check_apt_opencv || return 1
    echo "[build] auto_cpp OpenCV from: apt (/usr)" >&2
    cmake -S "$HERE" -B "$HERE/build" -DCPP_OPENCV_SOURCE=apt >&2
  else
    _ensure_selfbuild
    echo "[build] auto_cpp OpenCV from: selfbuild ($OCV_BUILD)" >&2
    cmake -S "$HERE" -B "$HERE/build" \
      -DCPP_OPENCV_SOURCE=selfbuild \
      -DOPENCV_SOURCE_DIR="$OCV_SRC" \
      -DOPENCV_BUILD_DIR="$OCV_BUILD" >&2
  fi
  cmake --build "$HERE/build" -j"$(nproc)" >&2
}

# Auto-detect stale build
_NEED_REBUILD=0
if [[ -f "$HERE/build/CMakeCache.txt" ]]; then
  _cached_src="$(grep -E "^CPP_OPENCV_SOURCE" "$HERE/build/CMakeCache.txt" 2>/dev/null | cut -d= -f2- | cut -d: -f2 | tr -d ' ')"
  if [[ -n "$_cached_src" && "$_cached_src" != "$CPP_SOURCE" ]]; then
    echo "[auto_cpp] source switch: $_cached_src -> $CPP_SOURCE, rebuilding" >&2
    _NEED_REBUILD=1
  fi
fi
if [[ ! -x "$BIN" || $FORCE_REBUILD -eq 1 || $_NEED_REBUILD -eq 1 ]]; then
  [[ $_NEED_REBUILD -eq 1 ]] && rm -f "$HERE/build/CMakeCache.txt"
  build
fi

echo "[auto_cpp] device=$DEVICE_NORM source=$CPP_SOURCE src_dir=$OCV_SRC build_dir=$OCV_BUILD" >&2
exec "$BIN" --outdir ./report/new "${ARGS[@]:+"${ARGS[@]}"}"
