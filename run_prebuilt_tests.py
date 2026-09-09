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

Settings priority: CLI flags > interactive answers > run_config.prebuilt.yaml
(next to run_test.sh) > built-in defaults. Non-tty (CI/pipe) never asks.

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
    # Promptable per-run options (None = not given on CLI -> ask if tty,
    # else documented default). Fixed infra flags below are CLI-only.
    ap.add_argument("--device", default=None, help="camera (default: /dev/video0)")
    ap.add_argument("--backend", default=None, help="ANY|V4L2|GSTREAMER|FFMPEG (default: V4L2)")
    ap.add_argument("--suites", default=None,
                    help="comma list of auto,manual,official, or all (default: all)")
    ap.add_argument("--outdir", default=None,
                    help="report dir (default: ./report/<timestamp>/)")
    ap.add_argument("--frames", type=int, default=None, help="(default: 30)")
    ap.add_argument("--reconnect-window", type=int, default=None, help="(default: 30s)")
    ap.add_argument("--long-run", default=None, help="(default: 0 min = skip)")
    ap.add_argument("--answer", default=None, choices=["p", "f", "s"],
                    help="non-interactive manual verdict (default: ask at runtime)")
    ap.add_argument("--filter", default=None, help="gtest filter for official (default: all)")
    ap.add_argument("--console-output", dest="console_output",
                    action="store_true", default=None,
                    help="stream official gtest log live")
    ap.add_argument("--no-console-output", dest="console_output",
                    action="store_false",
                    help="suppress live gtest log (log file still written)")
    ap.add_argument("--combined", dest="combined",
                    action="store_true", default=None,
                    help="build combined_report.xlsx at the end")
    ap.add_argument("--no-combined", dest="combined", action="store_false")
    ap.add_argument("--fetch-testdata", default=None,
                    choices=["auto", "full", "slim", "skip"],
                    help="when official is selected but testdata is missing: "
                         "auto/full fetch it via git sparse-checkout "
                         "(auto=full), slim fetches ~33M subset, "
                         "skip errors out instead")
    ap.add_argument("--config", default=None,
                    help="config file (default: <root>/run_config.prebuilt.yaml)")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


EXTRA_URL = "https://github.com/opencv/opencv_extra.git"

# Per-run options that vary (prompted when tty and not given on CLI).
# Everything else (cpp paths, PREBUILT_ROOT, testdata URL, report names,
# console/combined/fetch infra flags) is fixed.
PROMPT_DEFAULTS = {
    "device": "/dev/video0",
    "backend": "V4L2",
    "suites": "all",
    "frames": 30,
    "reconnect_window": 30,
    "long_run": 0,
    "answer": None,
    "filter": None,
    "outdir": None,
}
ALLOWED_BACKENDS = ("ANY", "V4L2", "GSTREAMER", "FFMPEG")
ALLOWED_SUITES = ("auto", "manual", "official")
CONFIG_KEYS = ("device", "backend", "suites", "frames", "reconnect_window",
               "long_run", "answer", "filter", "outdir", "fetch_testdata",
               "console_output", "combined_report")


def load_prebuilt_config(path):
    """Read run_config.prebuilt.yaml (like run_camera_tests.py reads
    run_config.yaml). Missing file or no pyyaml -> {} (built-ins apply)."""
    if not path or not os.path.isfile(path):
        return {}
    try:
        import yaml
    except ImportError:
        print(f"[config] WARN: {path} ignored (pyyaml not installed)")
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[config] WARN: {path} unreadable ({e}), using built-ins")
        return {}
    return {k: cfg[k] for k in CONFIG_KEYS if k in cfg}


def merge_defaults(cfg):
    """yaml over built-ins, with validation (bad values warn + drop)."""
    defaults = dict(PROMPT_DEFAULTS,
                    fetch_testdata="auto", console_output=True,
                    combined_report=True)
    if not cfg:
        return defaults
    if "backend" in cfg:
        b = str(cfg["backend"]).upper()
        if b in ALLOWED_BACKENDS:
            defaults["backend"] = b
        else:
            print(f"[config] WARN: bad backend '{cfg['backend']}', using "
                  f"{defaults['backend']}")
    for k in ("device", "answer", "filter", "outdir"):
        if cfg.get(k) is not None:
            defaults[k] = cfg[k]
    if cfg.get("answer") not in (None, "p", "f", "s"):
        print(f"[config] WARN: bad answer '{cfg.get('answer')}', asking at runtime")
        defaults["answer"] = None
    if "suites" in cfg and cfg["suites"] is not None:
        s = cfg["suites"]
        seq = s if isinstance(s, list) else [x.strip() for x in str(s).split(",")]
        seq = [x for x in seq if x]
        if not seq:
            print("[config] WARN: empty suites, using all")
        elif all(x in ALLOWED_SUITES for x in seq):
            defaults["suites"] = ",".join(seq)
        elif str(s).strip().lower() == "all":
            defaults["suites"] = "all"
        else:
            print(f"[config] WARN: bad suites '{s}', using all")
    for k in ("frames", "reconnect_window", "long_run"):
        if cfg.get(k) is not None:
            try:
                defaults[k] = int(cfg[k])
            except (TypeError, ValueError):
                print(f"[config] WARN: bad {k} '{cfg[k]}', using "
                      f"{defaults[k]}")
    if cfg.get("fetch_testdata") in ("auto", "full", "slim", "skip"):
        defaults["fetch_testdata"] = cfg["fetch_testdata"]
    elif cfg.get("fetch_testdata") is not None:
        print(f"[config] WARN: bad fetch_testdata "
              f"'{cfg.get('fetch_testdata')}', using auto")
    for k, yaml_k in (("console_output", "console_output"),
                      ("combined", "combined_report")):
        if isinstance(cfg.get(yaml_k), bool):
            defaults[k] = cfg[yaml_k]
    return defaults


def _ask(prompt, default, cast=str, allowed=None):
    disp = "" if default is None else str(default)
    while True:
        try:
            raw = input(f"  {prompt} [{disp}]: ").strip()
        except EOFError:
            return default
        if not raw:
            return default
        try:
            val = cast(raw)
        except ValueError:
            print(f"    invalid value '{raw}'")
            continue
        if allowed and val not in allowed:
            print(f"    allowed: {sorted(allowed) if isinstance(allowed, (tuple, list)) else allowed}")
            continue
        return val


def ask_interactive(args, defaults):
    """Fill None promptable options from defaults: prompt on tty (showing
    yaml/built-in defaults), silent fill otherwise.
    CLI-provided values are never re-asked."""
    given = {k for k in PROMPT_DEFAULTS if getattr(args, k, None) is not None}
    if not sys.stdin.isatty():
        for k in PROMPT_DEFAULTS:
            if getattr(args, k, None) is None:
                setattr(args, k, defaults[k])
        return
    print("\n== Run settings (Enter = default, CLI flags skip asking) ==")
    if "device" not in given:
        args.device = _ask("device", defaults["device"])
    if "backend" not in given:
        args.backend = _ask("backend", defaults["backend"],
                            cast=str.upper, allowed=ALLOWED_BACKENDS)
    if "suites" not in given:
        while True:
            raw = _ask("suites (auto,manual,official / all)",
                       defaults["suites"])
            picked = ["auto", "manual", "official"] \
                if raw.strip().lower() == "all" else \
                [s.strip() for s in raw.split(",") if s.strip()]
            if picked and all(s in ALLOWED_SUITES for s in picked):
                args.suites = ",".join(picked)
                break
            print(f"    allowed: auto,manual,official or all")
    advanced = [k for k in ("frames", "reconnect_window", "long_run",
                            "answer", "filter", "outdir") if k not in given]
    if advanced:
        try:
            more = input("  modify advanced "
                         "(frames/reconnect/long-run/answer/filter/outdir)? [y/N]: "
                         ).strip().lower()
        except EOFError:
            more = ""
        if more in ("y", "yes"):
            if "frames" in advanced:
                args.frames = _ask("frames", defaults["frames"], cast=int)
            if "reconnect_window" in advanced:
                args.reconnect_window = _ask("reconnect-window (sec)",
                                             defaults["reconnect_window"],
                                             cast=int)
            if "long_run" in advanced:
                args.long_run = _ask("long-run (min, 0=skip)",
                                     defaults["long_run"])
            if "answer" in advanced:
                args.answer = _ask("manual verdict p/f/s (empty=ask at runtime)",
                                   defaults["answer"], allowed=("p", "f", "s"))
            if "filter" in advanced:
                args.filter = _ask("gtest filter (empty=all)", defaults["filter"])
            if "outdir" in advanced:
                args.outdir = _ask("outdir (empty=timestamped)", defaults["outdir"])
    for k in PROMPT_DEFAULTS:
        if getattr(args, k, None) is None:
            setattr(args, k, defaults[k])


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


def ensure_openpyxl():
    """Best-effort openpyxl for xlsx reports (json/log work without it)."""
    try:
        import openpyxl  # noqa: F401
        print("[deps] openpyxl present")
        return True
    except ImportError:
        pass
    print("[deps] openpyxl missing, installing...")
    pip = [sys.executable, "-m", "pip", "install", "-q", "openpyxl"]
    # noble is EXTERNALLY-MANAGED: --break-system-packages first, then
    # plain (venv/pipx), then --user.
    for extra in (["--break-system-packages"], [], ["--user"]):
        try:
            subprocess.run(pip + extra, check=True, timeout=180,
                           capture_output=True)
            import openpyxl  # noqa: F401
            print(f"[deps] openpyxl installed "
                  f"({' '.join(extra) if extra else 'default flags'})")
            return True
        except Exception as e:
            print(f"[deps] pip install {' '.join(extra) or '(default)'} "
                  f"failed: {e}")
            continue
    print("[deps] WARN: openpyxl unavailable "
          "(xlsx skipped, json/log still work)")
    return False


def main():
    args = parse_args()
    # Config file first (root unknown yet only when --config is relative and
    # PREBUILT_ROOT unset; reloaded after root detection if needed).
    cfg_path = args.config
    if cfg_path and not os.path.isabs(cfg_path) and not os.path.isfile(cfg_path):
        cfg_path = None  # resolve against prebuilt root below

    root = detect_root()
    if not root:
        print("ERROR: not a prebuilt layout (bin/ not found).")
        print("  Run from an unpacked prebuilt package, or set PREBUILT_ROOT,")
        print("  or use run_camera_tests.py in the source tree.")
        return 2
    if not cfg_path:
        cfg_path = os.path.join(root, "run_config.prebuilt.yaml")
    defaults = merge_defaults(load_prebuilt_config(cfg_path))
    if cfg_path and os.path.isfile(cfg_path):
        print(f"[config] {cfg_path}")
    ask_interactive(args, defaults)   # CLI > interactive > yaml > built-ins
    # Non-prompted infra flags resolve CLI > yaml > built-in.
    if args.fetch_testdata is None:
        args.fetch_testdata = defaults["fetch_testdata"]
    if args.console_output is None:
        args.console_output = defaults["console_output"]
    if args.combined is None:
        args.combined = defaults["combined"]
    if isinstance(args.suites, str):
        if args.suites.strip().lower() == "all":
            args.suites = ["auto", "manual", "official"]
        else:
            args.suites = [s.strip() for s in args.suites.split(",") if s.strip()]
    bad = [s for s in args.suites if s not in ("auto", "manual", "official")]
    if bad:
        print(f"ERROR: unknown suites: {bad}")
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
    if not args.dry_run:
        ensure_openpyxl()
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
