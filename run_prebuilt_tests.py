#!/usr/bin/env python3
"""Runtime-only test orchestrator for the prebuilt package (execute-only).

Unlike run_camera_tests.py (source-tree, interactive, build-capable), this
script assumes everything is already compiled and only runs tests:

  Fixed layout (no cpp source/build/branch choices):
    <root>/bin/      opencv_camera_api_test_cpp, manual_suite (+helpers),
                     opencv_test_videoio
    <root>/lib/      selfbuild libopencv_*.so (LD_LIBRARY_PATH fallback)
    <root>/scripts/  run_test_auto.sh, run_test_manual.sh,
                     run_official_videoio_test.py, generate_combined_report.py
    <root>/opencv_extra/testdata   (fetched at install time, full)

Usage:
  ./run_test.sh --device /dev/video0 [--suites auto,manual,official]
  python3 run_prebuilt_tests.py --dry-run   # show planned commands only

Exit codes: 0 = all selected suites passed, 1 = at least one suite failed,
            2 = environment/config error (missing binary, testdata, ...).
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def detect_root():
    """Prebuilt root: env wins, else own dir if bin/ sits beside it."""
    env = os.environ.get("PREBUILT_ROOT", "")
    if env and os.path.isfile(os.path.join(env, "bin", "opencv_camera_api_test_cpp")):
        return os.path.abspath(env)
    if os.path.isfile(os.path.join(HERE, "bin", "opencv_camera_api_test_cpp")):
        return HERE
    return ""


def check_env(root):
    """Return list of missing prerequisites (empty = ready)."""
    missing = []
    for rel in ("bin/opencv_camera_api_test_cpp",
                "bin/manual_suite",
                "bin/opencv_test_videoio"):
        if not os.path.isfile(os.path.join(root, rel)):
            missing.append(rel)
    for sub in ("testdata/cv", "testdata/highgui"):
        if not os.path.isdir(os.path.join(root, "opencv_extra", sub)):
            missing.append(f"opencv_extra/{sub}")
    return missing


def stream_run(cmd, tag, env):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            bufsize=1, env=env)
    at_start = True
    assert proc.stdout is not None
    while True:
        ch = proc.stdout.read(1)
        if ch == "":
            break
        if at_start:
            sys.stdout.write(f"[{tag}] ")
            at_start = False
        sys.stdout.write(ch)
        sys.stdout.flush()
        if ch == "\n":
            at_start = True
    proc.wait()
    return proc.returncode


def build_plan(args, root, report_dir):
    py = sys.executable
    plan = []
    if "auto" in args.suites:
        plan.append(("auto", ["bash", os.path.join(root, "scripts", "run_test_auto.sh"),
                              "--device", args.device, "--backend", args.backend,
                              "--frames", str(args.frames),
                              "--outdir", report_dir, "--no-build"]))
    if "manual" in args.suites:
        cmd = ["bash", os.path.join(root, "scripts", "run_test_manual.sh"),
               "-d", args.device,
               "--reconnect-window", str(args.reconnect_window),
               "--outdir", report_dir, "--no-build"]
        if args.long_run and float(args.long_run) > 0:
            cmd += ["--long-run", str(args.long_run)]
        if args.answer:
            cmd += ["--answer", args.answer]
        plan.append(("manual", cmd))
    if "official" in args.suites:
        cmd = [py, "-u", os.path.join(root, "scripts", "run_official_videoio_test.py"),
               "-e", root, "-b", root, "-d", args.device, "-o", report_dir]
        if args.filter:
            cmd += ["-f", args.filter]
        if args.console_output:
            cmd += ["--console-output"]
        plan.append(("official", cmd))
    if args.combined:
        plan.append(("combined",
                     [py, "-u", os.path.join(root, "scripts", "generate_combined_report.py"),
                      "--auto-cpp", os.path.join(report_dir, "report_cpp.json"),
                      "--manual-cpp", os.path.join(report_dir, "report_manual_cpp.json"),
                      "--official-log", os.path.join(report_dir, "videoio_gtest.log"),
                      "--outdir", report_dir]))
    return plan


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="/dev/video0")
    ap.add_argument("--backend", default="V4L2")
    ap.add_argument("--suites", default="all",
                    help="comma list of auto,manual,official, or all (default)")
    ap.add_argument("--outdir", default=None,
                    help="report dir (default: ./report/<timestamp>/)")
    ap.add_argument("--frames", type=int, default=30)
    ap.add_argument("--reconnect-window", type=int, default=30)
    ap.add_argument("--long-run", default=0)
    ap.add_argument("--answer", default=None, choices=["p", "f", "s"],
                    help="non-interactive manual verdict")
    ap.add_argument("--filter", default=None, help="gtest filter for official")
    ap.add_argument("--console-output", action="store_true")
    ap.add_argument("--no-combined", dest="combined", action="store_false",
                    default=True)
    ap.add_argument("--fetch-testdata", default="auto",
                    choices=["auto", "full", "slim", "skip"],
                    help="when official is selected but testdata is missing: "
                         "auto/full fetch it via git sparse-checkout "
                         "(default: auto=full), slim fetches ~33M subset, "
                         "skip errors out instead")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


EXTRA_URL = "https://github.com/opencv/opencv_extra.git"


def fetch_testdata(root, mode):
    """Sparse-checkout opencv_extra testdata into <root>/opencv_extra.

    mode full: testdata/cv + testdata/highgui (~389M).
    mode slim: highgui + cv/video + cv/tracking (~33M, what videoio reads).
    Returns True on success.
    """
    extra = os.path.join(root, "opencv_extra")
    if mode == "slim":
        wants = ["testdata/highgui", "testdata/cv/video", "testdata/cv/tracking"]
    else:
        wants = ["testdata/cv", "testdata/highgui"]
    try:
        if not os.path.isdir(os.path.join(extra, ".git")):
            print(f"[testdata] cloning opencv_extra -> {extra} ({mode})")
            subprocess.run(["git", "clone", "--depth", "1",
                            "--filter=blob:none", "--sparse",
                            EXTRA_URL, extra], check=True)
        else:
            print(f"[testdata] using existing clone at {extra} ({mode})")
        # sparse-checkout set (modern git) with fallback to add
        r = subprocess.run(["git", "-C", extra, "sparse-checkout", "set",
                            *wants], capture_output=True, text=True)
        if r.returncode != 0:
            for w in wants:
                subprocess.run(["git", "-C", extra, "sparse-checkout",
                                "add", w], check=True)
        ok = all(os.path.isdir(os.path.join(extra, p)) for p in
                 (["testdata/highgui", "testdata/cv"] if mode == "slim"
                  else ["testdata/cv", "testdata/highgui"]))
        if ok:
            try:
                size = subprocess.run(["du", "-sh", os.path.join(extra, "testdata")],
                                      capture_output=True, text=True).stdout.split()[0]
                print(f"[testdata] ready ({size})")
            except Exception:
                print("[testdata] ready")
        return ok
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"[testdata] fetch failed: {e}")
        return False


def main():
    args = parse_args()
    if args.suites.strip().lower() == "all":
        args.suites = ["auto", "manual", "official"]
    else:
        args.suites = [s.strip() for s in args.suites.split(",") if s.strip()]
        bad = [s for s in args.suites if s not in ("auto", "manual", "official")]
        if bad:
            print(f"ERROR: unknown suites: {bad}") 
            return 2

    root = detect_root()
    if not root:
        print("ERROR: not a prebuilt layout (bin/ not found).") 
        print("  Run from an unpacked prebuilt package, or set PREBUILT_ROOT,")
        print("  or use run_camera_tests.py in the source tree.")
        return 2

    missing = check_env(root)
    # official testdata only matters when official suite selected
    if "official" not in args.suites:
        missing = [m for m in missing if not m.startswith("opencv_extra/")]
    needs_testdata = any(m.startswith("opencv_extra/") for m in missing)
    if needs_testdata and not args.dry_run:
        mode = args.fetch_testdata
        if mode == "auto":
            mode = "full"
        if mode == "skip":
            print("ERROR: missing prerequisites in", root)
            for m in missing:
                print(f"  - {m}")
            print("  Fetch testdata: bash install_prebuilt.sh --tarball <pkg> "
                  "--prefix <this dir> --fetch-testdata full")
            return 2
        print(f"[testdata] missing, auto-fetching ({mode})...")
        if fetch_testdata(root, mode):
            missing = [m for m in missing
                       if not (m.startswith("opencv_extra/") and
                               os.path.isdir(os.path.join(root, m)))]
        else:
            print("  Fallback: bash install_prebuilt.sh --tarball <pkg> "
                  "--prefix <this dir> --fetch-testdata full")
    if missing and not (args.dry_run and
                        all(m.startswith("opencv_extra/") for m in missing)):
        print("ERROR: missing prerequisites in", root)
        for m in missing:
            print(f"  - {m}")
        return 2

    report_dir = args.outdir or os.path.join(
        os.getcwd(), "report", datetime.now().strftime("%Y-%m-%d-%H%M%S"))
    plan = build_plan(args, root, os.path.abspath(report_dir))

    print(f"== prebuilt test run (root={root}) ==")
    print(f"  device  : {args.device} backend={args.backend}")
    print(f"  suites  : {', '.join(s for s, _ in plan if s != 'combined')}")
    print(f"  outdir  : {report_dir}/")
    for name, cmd in plan:
        print(f"  [{name:<8}] {' '.join(cmd)}")
    if args.dry_run:
        print("[dry-run] no commands executed.")
        return 0

    os.makedirs(report_dir, exist_ok=True)
    env = dict(os.environ, PREBUILT_ROOT=root,
               LD_LIBRARY_PATH=os.path.join(root, "lib") +
               (":" + os.environ["LD_LIBRARY_PATH"] if os.environ.get("LD_LIBRARY_PATH") else ""))
    failed = []
    for name, cmd in plan:
        print(f"\n>>>> running {name} " + "=" * 40)
        rc = stream_run(cmd, name, env)
        if rc != 0 and name != "combined":
            failed.append((name, rc))
            print(f"\n[{name}] exit code {rc}")

    print("\n" + "=" * 60)
    print("ALL SELECTED SUITES FINISHED")
    for name, rc in failed:
        print(f"  FAILED: {name} (exit {rc})")
    if not failed:
        print("  all selected suites returned exit code 0")
    print(f"  reports : {os.path.abspath(report_dir)}{os.sep}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
