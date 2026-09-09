#!/usr/bin/env bash
# Convenience wrapper for the C++ MANUAL test suite (mirror of auto_cpp/run_test.sh)
#
# Usage (run from anywhere, toolkit root recommended):
#   ./manual_cpp/run_test.sh --help
#   ./manual_cpp/run_test.sh                                  # interactive, defaults: -d 0
#   ./manual_cpp/run_test.sh -d 2 --answer p                  # non-interactive CI (all PASS)
#   ./manual_cpp/run_test.sh --item exposure_visual_check -d 0 --answer p
#   ./manual_cpp/run_test.sh --rebuild                        # force rebuild
#   ./manual_cpp/run_test.sh --device 0 --evidence ./report/2026-08-24/manual_evidence_cpp --report ./report/2026-08-24/report_manual_cpp.json
#
# Device handling: -d/--device accepts N or /dev/videoN (N auto -> /dev/videoN, same as Python toolkit)
# The binary is auto-built on first use. OpenCV build tree resolution order:
#   $CAMERA_TOOLKIT_OCV_BUILD > <script_dir>/../build (toolkit source build)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/build/manual_suite"
_yaml_source() {
  local cfg="$HERE/../run_config.yaml"
  if [[ -f "$cfg" ]]; then
    python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print(c.get('cpp',{}).get('source','apt'))" "$cfg" 2>/dev/null | tr -d '\n\r '
  else
    echo "apt"
  fi
}
CPP_SOURCE="${CPP_OPENCV_SOURCE:-$(_yaml_source)}"
_resolve_versioned() {
  local base="$1" branch="$2"
  base="${base%/}"
  [[ -z "$base" ]] && base="."
  local last="${base##*/}"
  [[ "$last" == "$branch" ]] && echo "$base" || echo "$base/$branch"
}
if [[ "$CPP_SOURCE" == "selfbuild" ]]; then
  _cpp_val() { python3 -c "import yaml,sys; c=yaml.safe_load(open(sys.argv[1])); print(c.get('cpp',{}).get(sys.argv[2],''))" "$HERE/../run_config.yaml" "$1" 2>/dev/null | tr -d '\n\r '; }
  _branch="$(_cpp_val branch)"; [[ -z "$_branch" ]] && _branch="latest"
  _src_base="$(_cpp_val source_dir)"
  _build_base="$(_cpp_val build_dir)"
  # Strip any existing version suffix from saved paths
  _src_base="${_src_base%/*}"
  [[ -z "$_src_base" || "$_src_base" == "." ]] && _src_base="./opencv_source_code"
  _build_base="${_build_base%/*}"
  [[ -z "$_build_base" || "$_build_base" == "." ]] && _build_base="./build"
  # Resolve versioned: base/branch
  _src_dir="$(_resolve_versioned "$_src_base" "$_branch")"
  _build_dir="$(_resolve_versioned "$_build_base" "$_branch")"
  [[ "$_src_dir" == ./* ]] && _src_dir="$HERE/../${_src_dir#./}"
  [[ "$_build_dir" == ./* ]] && _build_dir="$HERE/../${_build_dir#./}"
  OCV_BUILD="$_build_dir"
else
  OCV_BUILD="/usr"
fi
export CPP_OPENCV_SOURCE="$CPP_SOURCE"

# Defaults matching Python toolkit
DEVICE="/dev/video0"
EVIDENCE=""
REPORT=""
EXCEL_DIR=""
ANSWER=""
ITEM=""
RECONNECT_WINDOW=""
LONG_RUN=""
NO_EXCEL=0
FORCE_REBUILD=0
NO_BUILD=0
PREBUILT_ROOT="${PREBUILT_ROOT:-}"
EXTRA_ARGS=()

print_help() {
  cat <<'HELP'
manual_cpp/run_test.sh - C++ manual suite runner

Options (mirrors manual/run_manual_suite.py):
  -d, --device PATH|N        camera node, N auto-converted to /dev/videoN (default /dev/video0)
      --backend NAME         V4L2|ANY|GSTREAMER (default V4L2)
      --item NAME            run single item: device_index_physical_mapping|exposure_visual_check|autofocus_visual_check|white_balance_visual_check|real_usb_unplug_reconnect|long_duration_stability
      --answer p|f|s         non-interactive verdict (p=PASS f=FAIL s=SKIP) for every item
      --evidence DIR         evidence image dir (default ./manual_evidence_cpp or <report_dir>/manual_evidence_cpp when --report given)
      --report PATH          report_manual_cpp.json path (default report/new/report_manual_cpp.json) - distinct from Python's report_manual.json to avoid overwrite
      --excel-dir DIR        excel output dir (default report/new) -> report_manual_cpp.xlsx
      --reconnect-window SEC USB reconnect window seconds (default 30)
      --long-run MIN         enable long_duration_stability for MIN minutes
      --no-excel             skip report_manual_cpp.xlsx
      --list                 list 6 items and exit
      --outdir DIR           shorthand: sets --evidence <DIR>/manual_evidence_cpp --report <DIR>/report_manual_cpp.json --excel-dir <DIR>
      --rebuild              force rebuild before run
  -h, --help                 show this help

Examples:
  ./manual_cpp/run_test.sh --list
  ./manual_cpp/run_test.sh -d 0 --answer s
  ./manual_cpp/run_test.sh --item exposure_visual_check -d 0 --answer p --outdir ./report/2026-08-24
  ./manual_cpp/run_test.sh -d /dev/video2 --reconnect-window 60

Helpers (standalone):
  ./manual_cpp/build/exposure_check -d 0 sweep --values 50,100,200 --outdir ./exp_check
  ./manual_cpp/build/autofocus_check -d 0 focus --values 0,80,160,250 --outdir ./focus_check
  ./manual_cpp/build/white_balance_check -d 0 temp --values 2500,4000,5500 --outdir ./wb_check
  ./manual_cpp/build/reconnect_test --device 0 --max-duration 30 --outdir ./reconnect
HELP
}

# ---- parse ----
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--device) DEVICE="$2"; shift 2 ;;
    --backend) EXTRA_ARGS+=("--backend" "$2"); shift 2 ;;
    --item) ITEM="$2"; EXTRA_ARGS+=("--item" "$2"); shift 2 ;;
    --answer) ANSWER="$2"; EXTRA_ARGS+=("--answer" "$2"); shift 2 ;;
    --evidence) EVIDENCE="$2"; EXTRA_ARGS+=("--evidence" "$2"); shift 2 ;;
    --report) REPORT="$2"; EXTRA_ARGS+=("--report" "$2"); shift 2 ;;
    --excel-dir) EXCEL_DIR="$2"; EXTRA_ARGS+=("--excel-dir" "$2"); shift 2 ;;
    --reconnect-window) RECONNECT_WINDOW="$2"; EXTRA_ARGS+=("--reconnect-window" "$2"); shift 2 ;;
    --long-run) LONG_RUN="$2"; EXTRA_ARGS+=("--long-run" "$2"); shift 2 ;;
    --no-excel) NO_EXCEL=1; EXTRA_ARGS+=("--no-excel"); shift ;;
    --list) EXTRA_ARGS+=("--list"); shift ;;
    --outdir|-o)
      # unified outdir like run_camera_tests.py - uses _cpp suffix to avoid collision with Python's manual
      OUTDIR="$2"
      EXTRA_ARGS+=("--evidence" "$OUTDIR/manual_evidence_cpp" "--report" "$OUTDIR/report_manual_cpp.json" "--excel-dir" "$OUTDIR")
      EVIDENCE="$OUTDIR/manual_evidence_cpp"
      REPORT="$OUTDIR/report_manual_cpp.json"
      EXCEL_DIR="$OUTDIR"
      shift 2 ;;
    --rebuild) FORCE_REBUILD=1; shift ;;
    --no-build) NO_BUILD=1; shift ;;
    --prebuilt-root) PREBUILT_ROOT="$2"; shift 2 ;;
    -h|--help) print_help; exit 0 ;;
    --) shift; EXTRA_ARGS+=("$@"); break ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

# Normalize device: N -> /dev/videoN for log clarity (binary also handles it)
if [[ "$DEVICE" =~ ^[0-9]+$ ]]; then
  DEVICE_NORM="/dev/video$DEVICE"
else
  DEVICE_NORM="$DEVICE"
fi

_ensure_selfbuild() {
  local branch
  branch="$(python3 -c "import yaml; print(yaml.safe_load(open('$HERE/../run_config.yaml')).get('cpp',{}).get('branch','4.x'))" 2>/dev/null | tr -d '\n\r ')"
  if [[ "$branch" == "latest" ]]; then
    if [[ ! -d "$OCV_SRC/.git" ]]; then
      echo "[manual_cpp] selfbuild: cloning opencv latest (HEAD) -> $OCV_SRC" >&2
      git clone --depth 1 https://github.com/opencv/opencv.git "$OCV_SRC" >&2
    fi
  else
    if [[ ! -d "$OCV_SRC/.git" ]]; then
      echo "[manual_cpp] selfbuild: cloning opencv $branch -> $OCV_SRC" >&2
      git clone --depth 1 --branch "$branch" https://github.com/opencv/opencv.git "$OCV_SRC" >&2
    fi
  fi
}
build() {
  if [[ "$CPP_SOURCE" == "selfbuild" ]]; then
    OCV_SRC="$_src_dir"
    if [[ ! -f "$OCV_BUILD/lib/libopencv_core.so" && ! -f "$OCV_BUILD/lib64/libopencv_core.so" ]]; then
      _ensure_selfbuild
      echo "[manual_cpp] selfbuild: cmake $OCV_SRC -> $OCV_BUILD (shared with official/auto_cpp if possible)" >&2
      cmake -S "$OCV_SRC" -B "$OCV_BUILD" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF >&2
      cmake --build "$OCV_BUILD" -j"$(nproc)" >&2
    fi
    echo "[build] configuring manual_cpp with OpenCV from: selfbuild ($OCV_BUILD)" >&2
    cmake -S "$HERE" -B "$HERE/build" \
      -DCPP_OPENCV_SOURCE=selfbuild \
      -DOPENCV_SOURCE_DIR="$OCV_SRC" \
      -DOPENCV_BUILD_DIR="$OCV_BUILD" \
      -DOpenCV_DIR="$OCV_BUILD" \
      -DCMAKE_PREFIX_PATH="$OCV_BUILD" >&2
    cmake --build "$HERE/build" -j"$(nproc)" >&2
  else
    echo "[build] configuring manual_cpp with OpenCV from: apt ($CPP_SOURCE)" >&2
    cmake -S "$HERE" -B "$HERE/build" -DCPP_OPENCV_SOURCE=apt >&2
    cmake --build "$HERE/build" -j"$(nproc)" >&2
  fi
}

# Stale detection (source switch / lib version)
_NEED_REBUILD=0
if [[ -f "$HERE/build/CMakeCache.txt" ]]; then
  _cached_src="$(grep -E "^CPP_OPENCV_SOURCE" "$HERE/build/CMakeCache.txt" 2>/dev/null | cut -d= -f2- | cut -d: -f2 | tr -d ' ')"
  if [[ -n "$_cached_src" && "$_cached_src" != "$CPP_SOURCE" ]]; then
    echo "[manual_cpp] detected source switch: $_cached_src -> $CPP_SOURCE, forcing rebuild" >&2
    _NEED_REBUILD=1
  fi
  if ldd "$BIN" 2>/dev/null | grep -q "libopencv_videoio.so.501"; then
    if [[ "$CPP_SOURCE" == "apt" ]]; then _NEED_REBUILD=1; fi
  fi
fi
[[ "${SKIP_BUILD:-0}" == "1" ]] && NO_BUILD=1
# Auto-detect packaged layout: <root>/scripts/run_test_manual.sh with <root>/bin/ beside it.
if [[ -z "$PREBUILT_ROOT" && -x "$HERE/../bin/manual_suite" ]]; then
  PREBUILT_ROOT="$HERE/.."
fi
if [[ -n "$PREBUILT_ROOT" ]]; then
  BIN="$PREBUILT_ROOT/bin/manual_suite"
  [[ -d "$PREBUILT_ROOT/lib" ]] && export LD_LIBRARY_PATH="$PREBUILT_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  CPP_SOURCE="selfbuild"
  export CPP_OPENCV_SOURCE="selfbuild"
  NO_BUILD=1
fi
if [[ $NO_BUILD -eq 1 ]]; then
  [[ -x "$BIN" ]] || { echo "[manual_cpp] ERROR: --no-build but binary missing: $BIN" >&2; exit 2; }
  if ldd "$BIN" 2>/dev/null | grep -q "not found"; then
    echo "[manual_cpp] ERROR: prebuilt binary has missing .so:" >&2
    ldd "$BIN" | grep "not found" >&2 || true
    exit 2
  fi
  echo "[manual_cpp] prebuilt mode, skip build: $BIN" >&2
elif [[ ! -x "$BIN" || $FORCE_REBUILD -eq 1 || $_NEED_REBUILD -eq 1 ]]; then
  [[ $_NEED_REBUILD -eq 1 ]] && rm -f "$HERE/build/CMakeCache.txt"
  build
fi

# Always pass device explicitly (normalized)
# If user didn't pass --device via EXTRA_ARGS, our DEVICE handling above already captured it;
# but if they passed -d directly it is already in EXTRA_ARGS, avoid duplication.
HAS_DEVICE=0
for a in "${EXTRA_ARGS[@]:-}"; do
  if [[ "$a" == "-d" || "$a" == "--device" ]]; then HAS_DEVICE=1; break; fi
done
if [[ $HAS_DEVICE -eq 0 ]]; then
  # prepend device so it can be overridden? actually we want explicit device
  EXTRA_ARGS=("-d" "$DEVICE" "${EXTRA_ARGS[@]}")
fi

echo "[manual_cpp] device=$DEVICE_NORM (raw=$DEVICE)  report=${REPORT:-report/new/report_manual_cpp.json}  evidence=${EVIDENCE:-./manual_evidence_cpp}" >&2
if [[ -n "$ITEM" ]]; then echo "[manual_cpp] single item: $ITEM" >&2; fi
if [[ -n "$ANSWER" ]]; then echo "[manual_cpp] non-interactive answer=$ANSWER" >&2; fi

exec "$BIN" "${EXTRA_ARGS[@]}"
