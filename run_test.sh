#!/usr/bin/env bash
# Prebuilt runtime entry point (sits at package/install root).
# Usage: ./run_test.sh --device /dev/video0 [--suites auto,manual,official] [...]
# In the source tree this just points at run_prebuilt_tests.py (needs a
# prebuilt layout; use run_camera_tests.py for source-tree runs).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/run_prebuilt_tests.py" "$@"
