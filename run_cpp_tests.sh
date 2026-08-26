#!/usr/bin/env bash
# Unified C++ toolkit runner (auto_cpp + manual_cpp) - C++ analogue of run_camera_tests.py
#
# Usage:
#   ./run_cpp_tests.sh --help
#   ./run_cpp_tests.sh                          # interactive: choose suites + device
#   ./run_cpp_tests.sh -d 0 --all               # auto + manual (non-interactive)
#   ./run_cpp_tests.sh -d 0 --auto --manual     # explicitly select
#   ./run_cpp_tests.sh -d 0 --auto-only         # only auto
#   ./run_cpp_tests.sh -d 2 --manual --answer p # manual with CI verdict
#   ./run_cpp_tests.sh --rebuild                # force rebuild both
#
# Output: <report_root>/<timestamp>/ contains report_cpp.json (auto), report_manual_cpp.json/.xlsx (manual_cpp, distinct from Python's report_manual.json), manual_evidence_cpp/*, writer_test.avi
# Note: manual_cpp uses _cpp suffix to avoid collision with Python manual's report_manual.json / manual_evidence when both toolchains write to same <report_root>/<timestamp>/

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTO_SH="$HERE/auto_cpp/run_test.sh"
MANUAL_SH="$HERE/manual_cpp/run_test.sh"
DEFAULT_DEVICE="/dev/video0"
REPORT_ROOT="report"
BACKEND="V4L2"
ANSWER=""
REBUILD=0
RUN_AUTO=0
RUN_MANUAL=0
DEVICE_SET=0
DEVICE="$DEFAULT_DEVICE"

print_help() {
  cat <<'HELP'
run_cpp_tests.sh - C++ toolkit unified runner (auto_cpp + manual_cpp)

Options:
  -d, --device PATH|N     camera device, N auto -> /dev/videoN (default /dev/video0)
      --backend NAME      V4L2|ANY|GSTREAMER|FFMPEG (default V4L2, auto only)
      --report-root DIR   report root folder (default report) -> <report_root>/<timestamp>/
      --answer p|f|s      non-interactive manual verdict (manual_cpp)
      --auto              run auto_cpp suite
      --manual            run manual_cpp suite
      --all               run both (default when no selector given non-interactively)
      --auto-only         alias for --auto
      --manual-only       alias for --manual
      --rebuild           force rebuild both C++ suites before run
      --list              list manual items and auto inventory
  -h, --help              show this help
HELP
}

# ---- parse ----
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--device) DEVICE="$2"; DEVICE_SET=1; shift 2 ;;
    --backend) BACKEND="$2"; shift 2 ;;
    --report-root) REPORT_ROOT="$2"; shift 2 ;;
    --answer) ANSWER="$2"; shift 2 ;;
    --auto) RUN_AUTO=1; shift ;;
    --manual) RUN_MANUAL=1; shift ;;
    --all) RUN_AUTO=1; RUN_MANUAL=1; shift ;;
    --auto-only) RUN_AUTO=1; shift ;;
    --manual-only) RUN_MANUAL=1; shift ;;
    --rebuild) REBUILD=1; shift ;;
    --list) echo "== auto_cpp inventory =="; "$AUTO_SH" --list-only 2>&1 | head -n 40; echo ""; echo "== manual_cpp items =="; "$MANUAL_SH" --list 2>&1 | tail -n 10; exit 0 ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "unknown arg: $1" >&2; print_help; exit 2 ;;
  esac
done

# Normalize device for display
if [[ "$DEVICE" =~ ^[0-9]+$ ]]; then DEVICE_NORM="/dev/video$DEVICE"; else DEVICE_NORM="$DEVICE"; fi

# Interactive fallback if no selector and stdin is tty
if [[ $RUN_AUTO -eq 0 && $RUN_MANUAL -eq 0 ]]; then
  if [[ -t 0 ]]; then
    echo "== Current settings =="
    echo "  device      : $DEVICE_NORM (raw=$DEVICE)"
    echo "  backend     : $BACKEND"
    echo "  report_root : $REPORT_ROOT"
    echo ""
    echo "Which suites to run?"
    echo "  1) auto_cpp"
    echo "  2) manual_cpp"
    echo "  3) both (all)"
    read -rp "Select [3]: " choice
    choice=${choice:-3}
    case "$choice" in
      1) RUN_AUTO=1 ;;
      2) RUN_MANUAL=1 ;;
      3|*) RUN_AUTO=1; RUN_MANUAL=1 ;;
    esac
    if [[ $DEVICE_SET -eq 0 ]]; then
      read -rp "Modify device? [$DEVICE]: " new_dev
      if [[ -n "$new_dev" ]]; then DEVICE="$new_dev"; if [[ "$DEVICE" =~ ^[0-9]+$ ]]; then DEVICE_NORM="/dev/video$DEVICE"; else DEVICE_NORM="$DEVICE"; fi; fi
    fi
  else
    # non-interactive default: both
    RUN_AUTO=1; RUN_MANUAL=1
  fi
fi

STAMP="$(date +%Y-%m-%d-%H%M%S)"
REPORT_DIR="$REPORT_ROOT/$STAMP"
mkdir -p "$REPORT_DIR"

echo ""
echo "== Execution plan =="
echo "  device      : $DEVICE_NORM (raw=$DEVICE) backend=$BACKEND"
echo "  report_dir  : $REPORT_DIR/"
[[ $REBUILD -eq 1 ]] && echo "  rebuild     : yes" || echo "  rebuild     : no"
[[ $RUN_AUTO -eq 1 ]] && echo "  [auto]   $AUTO_SH -d $DEVICE --backend $BACKEND --outdir $REPORT_DIR"
[[ $RUN_MANUAL -eq 1 ]] && echo "  [manual] $MANUAL_SH -d $DEVICE --outdir $REPORT_DIR ${ANSWER:+--answer $ANSWER}"
if [[ $RUN_AUTO -eq 1 && $RUN_MANUAL -eq 1 ]]; then
  echo "  [combined] python3 $HERE/generate_combined_report.py --auto $REPORT_DIR/report_cpp.json --manual $REPORT_DIR/report_manual_cpp.json --outdir $REPORT_DIR (fallback: --auto $REPORT_DIR/report_auto.json, --manual $REPORT_DIR/report_manual.json)"
fi

FAILED=0

if [[ $RUN_AUTO -eq 1 ]]; then
  echo ""
  echo ">>>> running auto_cpp $(printf '=%.0s' {1..40})"
  REBUILD_FLAG=""; [[ $REBUILD -eq 1 ]] && REBUILD_FLAG="--rebuild"
  # auto_cpp binary outputs report_cpp.json; also symlink/copy to report_auto.json for combined report compat
  set +e
  "$AUTO_SH" $REBUILD_FLAG --device "$DEVICE" --backend "$BACKEND" --outdir "$REPORT_DIR"
  RC=$?
  set -e
  if [[ $RC -ne 0 ]]; then echo "[auto_cpp] exit $RC"; FAILED=1; fi
  # compat: combined report expects report_auto.json (Python name); link cpp output if needed
  if [[ -f "$REPORT_DIR/report_cpp.json" && ! -f "$REPORT_DIR/report_auto.json" ]]; then
    ln -sf report_cpp.json "$REPORT_DIR/report_auto.json" 2>/dev/null || cp "$REPORT_DIR/report_cpp.json" "$REPORT_DIR/report_auto.json"
  fi
fi

if [[ $RUN_MANUAL -eq 1 ]]; then
  echo ""
  echo ">>>> running manual_cpp $(printf '=%.0s' {1..40})"
  REBUILD_FLAG=""; [[ $REBUILD -eq 1 ]] && REBUILD_FLAG="--rebuild"
  set +e
  if [[ -n "$ANSWER" ]]; then
    "$MANUAL_SH" $REBUILD_FLAG -d "$DEVICE" --outdir "$REPORT_DIR" --answer "$ANSWER"
  else
    "$MANUAL_SH" $REBUILD_FLAG -d "$DEVICE" --outdir "$REPORT_DIR"
  fi
  RC=$?
  set -e
  if [[ $RC -ne 0 ]]; then echo "[manual_cpp] exit $RC"; FAILED=1; fi
fi

# Combined report (best effort) - supports both Python and C++ reports
if [[ $RUN_AUTO -eq 1 && $RUN_MANUAL -eq 1 ]]; then
  echo ""
  echo ">>>> generating combined_report.xlsx $(printf '=%.0s' {1..30})"
  AUTO_JSON="$REPORT_DIR/report_auto.json"
  [[ ! -f "$AUTO_JSON" && -f "$REPORT_DIR/report_cpp.json" ]] && AUTO_JSON="$REPORT_DIR/report_cpp.json"
  MANUAL_JSON="$REPORT_DIR/report_manual_cpp.json"
  [[ ! -f "$MANUAL_JSON" && -f "$REPORT_DIR/report_manual.json" ]] && MANUAL_JSON="$REPORT_DIR/report_manual.json"
  set +e
  python3 "$HERE/generate_combined_report.py" --auto "$AUTO_JSON" --manual "$MANUAL_JSON" --official-log "$REPORT_DIR/videoio_gtest.log" --outdir "$REPORT_DIR" 2>&1 | sed 's/^/[combined] /'
  set -e
fi

echo ""
echo "============================================================"
echo "ALL SELECTED C++ SUITES FINISHED"
echo "============================================================"
echo "  reports : $REPORT_DIR/"
ls -lh "$REPORT_DIR" 2>&1 | sed 's/^/  /'
exit $FAILED
