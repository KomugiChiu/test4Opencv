#!/usr/bin/env bash
# Prebuilt runtime entry point (sits at package/install root).
# Usage: ./run_test.sh --device /dev/video0 [--suites auto,manual,official] [...]
# The orchestrator lives in scripts/; only this launcher stays at root.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$HERE/scripts/run_prebuilt_tests.py" ]]; then
  exec python3 "$HERE/scripts/run_prebuilt_tests.py" "$@"
else
  # source-tree checkout: script sits beside the launcher.
  exec python3 "$HERE/run_prebuilt_tests.py" "$@"
fi
