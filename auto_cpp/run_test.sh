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

_TOOLKIT_ROOT="$(cd "$HERE/.." && pwd)"
# Anchor relative config paths to the toolkit root so they stay valid
# regardless of caller CWD and inside generated build files.
_to_abs() {
  local p="$1"
  if [[ "$p" == /* ]]; then printf '%s' "$p"; else printf '%s/%s' "$_TOOLKIT_ROOT" "${p#./}"; fi
}

if [[ "$CPP_SOURCE" == "selfbuild" ]]; then
  _src_base="$(python3 -c "import yaml; print(yaml.safe_load(open('$HERE/../run_config.yaml')).get('cpp',{}).get('source_dir','./opencv_source_code'))" 2>/dev/null | tr -d '\n\r ')"
  _build_base="$(python3 -c "import yaml; print(yaml.safe_load(open('$HERE/../run_config.yaml')).get('cpp',{}).get('build_dir','./build'))" 2>/dev/null | tr -d '\n\r ')"
  # Strip any existing version suffix
  _src_base="${_src_base%/*}"
  _build_base="${_build_base%/*}"
  [[ -z "$_src_base" || "$_src_base" == "." ]] && _src_base="./opencv_source_code"
  [[ -z "$_build_base" || "$_build_base" == "." ]] && _build_base="./build"
  OCV_SRC="$(_resolve_versioned "$_src_base" "$_branch")"
  OCV_BUILD="$(_resolve_versioned "$_build_base" "$_branch")"
  OCV_SRC="$(_to_abs "$OCV_SRC")"
  OCV_BUILD="$(_to_abs "$OCV_BUILD")"
else
  OCV_BUILD="/usr"
  OCV_SRC="/usr/include/opencv4"
fi
export CPP_OPENCV_SOURCE="$CPP_SOURCE"
export OPENCV_SOURCE_DIR="$OCV_SRC"
export OPENCV_BUILD_DIR="$OCV_BUILD"

FORCE_REBUILD=0
NO_BUILD=0
PREBUILT_ROOT="${PREBUILT_ROOT:-}"
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
    --no-build) NO_BUILD=1; shift ;;
    --prebuilt-root) PREBUILT_ROOT="$2"; shift 2 ;;
    -h|--help) ARGS+=("$1"); shift ;;
    --) shift; ARGS+=("$@"); break ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
[[ "${SKIP_BUILD:-0}" == "1" ]] && NO_BUILD=1
# Auto-detect packaged layout: <root>/scripts/run_test_auto.sh with <root>/bin/ beside it.
if [[ -z "$PREBUILT_ROOT" && -x "$HERE/../bin/opencv_camera_api_test_cpp" ]]; then
  PREBUILT_ROOT="$HERE/.."
fi
if [[ -n "$PREBUILT_ROOT" ]]; then
  BIN="$PREBUILT_ROOT/bin/opencv_camera_api_test_cpp"
  [[ -d "$PREBUILT_ROOT/lib" ]] && export LD_LIBRARY_PATH="$PREBUILT_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  CPP_SOURCE="selfbuild"
  export CPP_OPENCV_SOURCE="selfbuild"
  NO_BUILD=1
fi

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
if [[ $NO_BUILD -eq 1 ]]; then
  [[ -x "$BIN" ]] || { echo "[auto_cpp] ERROR: --no-build but binary missing: $BIN" >&2; exit 2; }
  if ldd "$BIN" 2>/dev/null | grep -q "not found"; then
    echo "[auto_cpp] ERROR: prebuilt binary has missing .so:" >&2
    ldd "$BIN" | grep "not found" >&2 || true
    exit 2
  fi
  echo "[auto_cpp] prebuilt mode, skip build: $BIN" >&2
elif [[ ! -x "$BIN" || $FORCE_REBUILD -eq 1 || $_NEED_REBUILD -eq 1 ]]; then
  [[ $_NEED_REBUILD -eq 1 ]] && rm -f "$HERE/build/CMakeCache.txt"
  build
fi

echo "[auto_cpp] device=$DEVICE_NORM source=$CPP_SOURCE src_dir=$OCV_SRC build_dir=$OCV_BUILD" >&2

# Effective outdir: default, overridden by the LAST --outdir/-o in ARGS
OUTDIR="./report/new"
_n=${#ARGS[@]}
for ((_i=0; _i<_n; _i++)); do
  if [[ "${ARGS[$_i]}" == "--outdir" || "${ARGS[$_i]}" == "-o" ]]; then
    (( _i + 1 < _n )) && OUTDIR="${ARGS[_i+1]}"
  fi
done

set +e
HAS_OUTDIR=0
for a in "${ARGS[@]:-}"; do [[ "$a" == "--outdir" || "$a" == "-o" ]] && HAS_OUTDIR=1; done
if [[ $HAS_OUTDIR -eq 1 ]]; then
  "$BIN" "${ARGS[@]:+"${ARGS[@]}"}"
else
  "$BIN" --outdir "$OUTDIR" "${ARGS[@]:+"${ARGS[@]}"}"
fi
RC=$?
set -e

# Excel report next to the JSON (best effort)
if [[ -f "$OUTDIR/report_cpp.json" ]]; then
  python3 "$HERE/tools/make_report_xlsx.py" --json "$OUTDIR/report_cpp.json" \
    --out "$OUTDIR/report_cpp.xlsx" >&2 || true
fi
XLSX_NOTE=""
[[ -f "$OUTDIR/report_cpp.xlsx" ]] && XLSX_NOTE=" + report_cpp.xlsx"
echo "[auto_cpp] reports : $OUTDIR/report_cpp.json$XLSX_NOTE" >&2
exit $RC
