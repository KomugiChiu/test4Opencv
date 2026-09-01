#!/usr/bin/env python3
"""Interactive orchestrator for the camera toolkit test suites.

Flow:
  1. Load settings from YAML (default: run_config.yaml next to this script;
     created with defaults on first run).
  2. Display current settings; optionally modify interactively.
  3. Ask which suites to run: auto / manual / official.
  4. Create a per-run report folder: <report_dir>/<YYYY-MM-DD-HHMMSS>/
  5. Execute selected suites, streaming their output live.
  6. Optionally generate combined_report.xlsx via generate_combined_report.py.

Usage:
  python3 run_camera_tests.py [--config PATH] [--dry-run]

Exit codes: 0 = all selected suites passed, 1 = at least one suite failed,
            2 = configuration error.
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(HERE, "run_config.yaml")
DEFAULT_CONFIG_DEFAULT = os.path.join(HERE, "run_config.default.yaml")
USER_CONFIG = os.path.join(HERE, "run_config.yaml")  # alias for DEFAULT_CONFIG


def do_clear(cfg):
    """Interactive cleanup: report / auto_cpp build / manual_cpp build / selfbuild."""
    cpp = cfg.get("cpp", {})
    ocpp = cfg.get("official_cpp", {})
    branch = cpp.get("branch", "latest")

    def _abs(p):
        if p.startswith("./"):
            return os.path.join(HERE, p[2:])
        if not os.path.isabs(p):
            return os.path.join(HERE, p)
        return p

    targets = [
        ("1", "report",              [os.path.join(HERE, cfg.get("report_dir", "report"))]),
        ("2", "auto_cpp build",      [os.path.join(HERE, "auto_cpp", "build")]),
        ("3", "manual_cpp build",    [os.path.join(HERE, "manual_cpp", "build")]),
        ("4", "opencv selfbuild source",
         [_abs(cpp.get("_source_dir_base") or ocpp.get("_source_dir_base") or "./opencv_source_code"),
          ]),
        ("5", "opencv selfbuild build",
         [_abs(cpp.get("_build_dir_base") or "./build"),
          _abs(ocpp.get("_build_dir_base") or ocpp.get("build_dir", "./build_official")),
          ]),
    ]

    print("\n== What to clear? ==")
    print("  1) report           : ./report/ (all timestamped results)")
    print("  2) auto_cpp build   : auto_cpp/build/")
    print("  3) manual_cpp build : manual_cpp/build/")
    print(f"  4) opencv selfbuild source : opencv_source_code/{branch}/")
    print(f"  5) opencv selfbuild build  : build/{branch}/ + build_official/{branch}/")
    print("  Enter numbers separated by comma (e.g. 1,2), 'a' for all, Enter=cancel")

    try:
        raw = input("Select: ").strip().lower()
    except EOFError:
        print("[clear] cancelled")
        return

    if not raw:
        print("[clear] nothing selected, cancelled")
        return

    if raw in ("a", "all"):
        selected = [t[1] for t in targets]
        dirs_to_clear = []
        for _, _, dirs in targets:
            dirs_to_clear.extend(dirs)
    else:
        picked = [x.strip() for x in raw.split(",") if x.strip()]
        num_map = {t[0]: t for t in targets}
        selected = []
        dirs_to_clear = []
        for p in picked:
            if p in num_map:
                selected.append(num_map[p][1])
                dirs_to_clear.extend(num_map[p][2])
            else:
                print(f"  unknown: {p}")

    if not dirs_to_clear:
        print("[clear] nothing to clear")
        return

    # Confirm
    print("\n  Will delete:")
    total = 0
    for d in dirs_to_clear:
        ad = os.path.abspath(d)
        exists = os.path.isdir(ad)
        size = ""
        if exists:
            try:
                r = subprocess.run(["du", "-sh", ad], capture_output=True,
                                   text=True, timeout=5)
                size = f" ({r.stdout.split()[0]})" if r.stdout else ""
            except Exception:
                pass
            total += 1
        print(f"    {'[DIR]' if exists else '[N/A]':>5}  {ad}{size}")
    if total == 0:
        print("  Nothing exists to clear.")
        return

    confirm = input(f"\n  Confirm deletion of {total} dir(s)? [y/N]: ").strip().lower()
    if confirm not in ("y", "yes"):
        print("[clear] cancelled")
        return

    for d in dirs_to_clear:
        ad = os.path.abspath(d)
        if os.path.isdir(ad):
            shutil.rmtree(ad, ignore_errors=True)
            print(f"  cleared: {ad}")
        elif os.path.isfile(ad):
            os.remove(ad)
            print(f"  cleared: {ad}")
    print("[clear] done.")

def _save_user_config(cfg):
    """Persist user-modified cfg to run_config.yaml (not the default).
    Always saves BASE paths (without version suffix) to avoid double-appending."""
    def _base_of(path, branch):
        # Strip version suffix if present
        if path and os.path.basename(path.rstrip("/")) == branch:
            return os.path.dirname(path.rstrip("/"))
        return path

    cpp = dict(cfg.get("cpp", {}))
    branch = cpp.get("branch", "latest")
    if "source_dir" in cpp:
        cpp["source_dir"] = _base_of(cpp["source_dir"], branch)
    if "build_dir" in cpp:
        cpp["build_dir"] = _base_of(cpp["build_dir"], branch)

    data = {
        "device": cfg["device"],
        "backend": cfg["backend"],
        "report_dir": cfg["report_dir"],
        "opencv_extra_dir": cfg["opencv_extra_dir"],
        "auto_impl": cfg["auto_impl"],
        "manual_impl": cfg["manual_impl"],
        "combined_report": cfg["combined_report"],
        "official_console_output": bool(cfg.get("official_console_output", False)),
        "manual_reconnect_window": cfg.get("manual_reconnect_window", 30),
        "manual_long_run": cfg.get("manual_long_run", 0),
        "cpp": cpp,
    }
    if "official_cpp" in cfg and isinstance(cfg["official_cpp"], dict):
        oc = dict(cfg["official_cpp"])
        oc.pop("source", None)
        ob = oc.get("branch", "latest")
        if "source_dir" in oc:
            oc["source_dir"] = _base_of(oc["source_dir"], ob)
        if "build_dir" in oc:
            oc["build_dir"] = _base_of(oc["build_dir"], ob)
        data["official_cpp"] = oc
    with open(USER_CONFIG, "w", encoding="utf-8") as f:
        f.write("# Camera Toolkit run configuration (user)\n")
        f.write("# Generated from interactive settings; original defaults in run_config.default.yaml\n")
        import yaml as _yaml
        _yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    print(f"[config] saved to {USER_CONFIG}")


def _resolve_versioned_path(base_dir, branch):
    """Append branch name to path: ./foo + latest -> ./foo/latest
    Skip if branch is already the last component."""
    base = base_dir.rstrip("/")
    if not base or os.path.basename(base) == branch:
        return base_dir
    return f"{base}/{branch}"


SUITE_ORDER = ["auto", "official", "manual"]   # unattended first, human last
ALLOWED_BACKENDS = {"ANY", "V4L2", "GSTREAMER", "FFMPEG"}


def load_config(path):
    # Priority: explicit --config > run_config.yaml (user) > run_config.default.yaml
    candidates = []
    if path == DEFAULT_CONFIG:
        if os.path.isfile(USER_CONFIG):
            candidates.append(USER_CONFIG)
        elif os.path.isfile(DEFAULT_CONFIG_DEFAULT):
            candidates.append(DEFAULT_CONFIG_DEFAULT)
        else:
            candidates.append(path)
    else:
        candidates.append(path)

    actual = candidates[0]
    created = not os.path.isfile(actual)
    if created:
        if os.path.isfile(DEFAULT_CONFIG_DEFAULT):
            import shutil
            shutil.copy(DEFAULT_CONFIG_DEFAULT, USER_CONFIG)
            print(f"[config] {USER_CONFIG} created from {DEFAULT_CONFIG_DEFAULT}")
            actual = USER_CONFIG
        else:
            with open(USER_CONFIG, "w", encoding="utf-8") as f:
                f.write(
                    "# Camera Toolkit run configuration (auto-generated)\n"
                    "device: /dev/video0\n"
                    "backend: V4L2\n"
                    "report_dir: report\n"
                    "opencv_extra_dir: .\n"
                    "combined_report: true\n"
                    "auto_impl: both\n"
                    "manual_impl: both\n"
                    "# C++ OpenCV source selection\n"
                    "cpp:\n"
                    "  source: apt                # apt | selfbuild\n"
                    "  apt_package: libopencv-dev\n"
                    "  source_dir: ./opencv_source_code   # clone -> <source_dir>/<branch>\n"
                    "  build_dir: ./build                  # build -> <build_dir>/<branch>\n"
                    "  branch: latest              # 4.x | 5.x | latest\n"
                    "official_cpp:\n"
                    "  source_dir: ./opencv_source_code   # always selfbuild\n"
                    "  build_dir: ./build_official         # separate from auto_cpp\n"
                    "  branch: latest\n")
            print(f"[config] {USER_CONFIG} not found -> created with defaults")
            actual = USER_CONFIG
        if actual == USER_CONFIG and os.path.isfile(DEFAULT_CONFIG_DEFAULT):
            print(f"[config] defaults in {DEFAULT_CONFIG_DEFAULT}, user overrides in {USER_CONFIG}")
    path = actual
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cpp_raw = cfg.get("cpp", {}) if isinstance(cfg.get("cpp"), dict) else {}
    off_raw = cfg.get("official_cpp", None)
    if not isinstance(off_raw, dict):
        off_raw = dict(cpp_raw) if isinstance(cpp_raw, dict) else {}
    use_off = "official_cpp" in cfg

    cpp_branch = str(cpp_raw.get("branch", "latest"))
    off_branch = str(off_raw.get("branch", "latest"))

    cpp_src_base = str(cpp_raw.get("source_dir", "./opencv_source_code"))
    cpp_build_base = str(cpp_raw.get("build_dir", "./build"))
    off_src_base = str(off_raw.get("source_dir", "./opencv_source_code"))
    off_build_base = str(off_raw.get("build_dir", "./build_official"))

    merged = {
        "device": str(cfg.get("device", "/dev/video0")),
        "backend": str(cfg.get("backend", "V4L2")).upper(),
        "report_dir": str(cfg.get("report_dir", "report")),
        "opencv_extra_dir": str(cfg.get("opencv_extra_dir", ".")),
        "combined_report": bool(cfg.get("combined_report", True)),
        "official_console_output": bool(cfg.get("official_console_output", False)),
        "auto_impl": str(cfg.get("auto_impl", "both")).lower(),
        "manual_impl": str(cfg.get("manual_impl", "both")).lower(),
        "manual_reconnect_window": int(cfg.get("manual_reconnect_window", 30)),
        "manual_long_run": int(cfg.get("manual_long_run", 0)),
        "cpp": {
            "source": str(cpp_raw.get("source", "apt")).lower(),
            "apt_package": str(cpp_raw.get("apt_package", "libopencv-dev")),
            "source_dir": _resolve_versioned_path(cpp_src_base, cpp_branch),
            "build_dir": _resolve_versioned_path(cpp_build_base, cpp_branch),
            "branch": cpp_branch,
        },
    }
    # official_cpp is ALWAYS selfbuild; no source field needed
    merged["official_cpp"] = {
        "source": "selfbuild",
        "source_dir": _resolve_versioned_path(off_src_base, off_branch),
        "build_dir": _resolve_versioned_path(off_build_base, off_branch),
        "branch": off_branch,
    }
    if merged["auto_impl"] not in ("python", "cpp", "both"):
        merged["auto_impl"] = "both"
    if merged["manual_impl"] not in ("python", "cpp", "both"):
        merged["manual_impl"] = "both"
    if merged["cpp"]["source"] not in ("apt", "selfbuild"):
        merged["cpp"]["source"] = "apt"
    return merged, created


def _cpp_label(cpp):
    src = cpp.get("source", "apt")
    if src == "apt":
        return f"apt ({cpp.get('apt_package','libopencv-dev')})"
    return f"selfbuild {cpp.get('branch','')} -> src: {cpp.get('source_dir','')} | build: {cpp.get('build_dir','')}"

def _official_cpp_label(cfg):
    ocpp = cfg.get("official_cpp", cfg.get("cpp", {}))
    branch = ocpp.get("branch", "latest")
    sd = ocpp.get("source_dir", "./opencv_source_code")
    bd = ocpp.get("build_dir", "./build_official")
    return f"selfbuild (always) {branch} -> src: {sd} | build: {bd}"

def show_settings(cfg):
    print("\n== Current settings ==")
    for line in _settings_lines(cfg):
        print(line)

def _cpp_source_label(cpp):
    if cpp.get("source") == "apt":
        return f"apt ({cpp.get('apt_package', '')})"
    branch = cpp.get("branch", "latest")
    sd = cpp.get("source_dir", f"./opencv_source_code/{branch}")
    bd = cpp.get("build_dir", f"./build/{branch}")
    return f"selfbuild {branch} -> src: {sd} | build: {bd}"


def _settings_lines(cfg):
    cpp = cfg.get("cpp", {})
    ocpp = cfg.get("official_cpp", {})
    rr = cfg.get("report_dir", "report")
    if not rr.startswith("./") and not os.path.isabs(rr):
        rr = f"./{rr}"
    oed = cfg.get("opencv_extra_dir", ".")
    lines = [
        f"  device           : {cfg['device']}",
        f"  backend          : {cfg['backend']}",
        f"  report_dir      : {rr}",
        f"  auto_impl        : {cfg['auto_impl']}   (python | cpp | both)",
        f"  manual_impl      : {cfg['manual_impl']}   (python | cpp | both)",
        f"  combined_report  : {'yes' if cfg['combined_report'] else 'no'}",
        f"  official_console : {'yes' if cfg.get('official_console_output') else 'no'}",
    ]
    # manual block
    lines.append("  manual:")
    lines.append(f"    reconnect_window : {cfg.get('manual_reconnect_window', 30)}s")
    lines.append(f"    long_run         : {cfg.get('manual_long_run', 0)} min")
    # cpp block (auto_cpp / manual_cpp)
    src = cpp.get("source", "apt")
    branch = cpp.get("branch", "latest")
    lines.append("  cpp:")
    lines.append(f"    source      : {src}")
    if src == "apt":
        lines.append(f"    apt_package : {cpp.get('apt_package', 'libopencv-dev')}")
    else:
        sd_base = cpp.get("_source_dir_base") or "./opencv_source_code"
        bd_base = cpp.get("_build_dir_base") or "./build"
        lines.append(f"    source_dir  : {sd_base}/{branch}")
        lines.append(f"    build_dir   : {bd_base}/{branch}")
        lines.append(f"    branch      : {branch}")
    # official_cpp block (always selfbuild)
    ob = ocpp.get("branch", "latest")
    osd = ocpp.get("_source_dir_base") or "./opencv_source_code"
    obd = ocpp.get("_build_dir_base") or "./build_official"
    td = cfg.get("opencv_extra_dir", ".")
    lines.append("  official_cpp:")
    lines.append(f"    source_dir  : {osd}/{ob}")
    lines.append(f"    build_dir   : {obd}/{ob}")
    lines.append(f"    branch      : {ob}")
    lines.append(f"    testdata_dir: {td}/opencv_extra/testdata")
    return lines


def ask_modify(cfg):
    # Numbered menu loop: show all settings, pick number to edit, re-display, ask continue
    def _menu():
        print("\n== Current settings ==")
        items = [
            ("1", "device", cfg["device"]),
            ("2", "backend", cfg["backend"]),
            ("3", "report_dir", cfg["report_dir"]),
            ("4", "opencv_extra_dir", cfg["opencv_extra_dir"]),
            ("5", "auto_impl", cfg["auto_impl"]),
            ("6", "manual_impl", cfg["manual_impl"]),
            ("7", "cpp.source (auto_cpp/manual_cpp)", _cpp_label(cfg.get("cpp",{}))),
            ("8", "manual.reconnect_window", f"{cfg.get('manual_reconnect_window', 30)}s"),
            ("9", "manual.long_run", f"{cfg.get('manual_long_run', 0)} min"),
            ("10", "combined_report", "yes" if cfg["combined_report"] else "no"),
        ]
        for num, key, val in items:
            print(f"  {num}) {key:<38}: {val}")
        print("  Enter number to modify, 'a' for all prompts, Enter=done")

    # First ask if want to modify at all (handle non-interactive / piped)
    try:
        ans = input("\nModify settings? [y/N]: ").strip().lower()
    except EOFError:
        return cfg
    if ans not in ("y", "yes", "a", "all"):
        return cfg

    # If 'all' go classic prompts, else numbered loop
    if ans in ("a", "all", "yes", "y") and False:
        pass

    while True:
        _menu()
        choice = input("Select [Enter=done]: ").strip().lower()
        if not choice:
            break
        if choice in ("a", "all"):
            # Fall through to classic prompts
            val = input(f"  device [{cfg['device']}]: ").strip()
            if val:
                cfg["device"] = val
            while True:
                val = input(f"  backend [{cfg['backend']}]: ").strip().upper()
                if not val:
                    break
                if val in ALLOWED_BACKENDS:
                    cfg["backend"] = val
                    break
                print(f"    invalid backend '{val}', allowed: {sorted(ALLOWED_BACKENDS)}")
            val = input(f"  report_dir [{cfg['report_dir']}]: ").strip()
            if val:
                cfg["report_dir"] = val.rstrip("/")
            for key in ("auto_impl", "manual_impl"):
                while True:
                    val = input(f"  {key} [{cfg[key]}] (python/cpp/both): ").strip().lower()
                    if not val:
                        break
                    if val in ("python", "cpp", "both"):
                        cfg[key] = val
                        break
                    print("    allowed: python | cpp | both")
            # cpp section
            _edit_cpp(cfg)
            val = input(f"  opencv_extra_dir [{cfg['opencv_extra_dir']}]: ").strip()
            if val:
                cfg["opencv_extra_dir"] = val
            while True:
                val = input(f"  combined_report [{'yes' if cfg['combined_report'] else 'no'}] (yes/no): ").strip().lower()
                if not val:
                    break
                if val in ("y", "yes", "true", "1"):
                    cfg["combined_report"] = True
                    break
                if val in ("n", "no", "false", "0"):
                    cfg["combined_report"] = False
                    break
                print("    please answer yes/no")
            # Re-display latest
            print("\n== Updated settings ==")
            for line in _settings_lines(cfg):
                print(line)
            more = input("\nContinue modifying? [y/N]: ").strip().lower()
            if more not in ("y", "yes"):
                break
            continue

        if choice == "1":
            val = input(f"  device [{cfg['device']}]: ").strip()
            if val:
                cfg["device"] = val
        elif choice == "2":
            while True:
                val = input(f"  backend [{cfg['backend']}]: ").strip().upper()
                if not val:
                    break
                if val in ALLOWED_BACKENDS:
                    cfg["backend"] = val
                    break
                print(f"    invalid backend '{val}', allowed: {sorted(ALLOWED_BACKENDS)}")
        elif choice == "3":
            val = input(f"  report_dir [{cfg['report_dir']}]: ").strip()
            if val:
                cfg["report_dir"] = val.rstrip("/")
        elif choice == "4":
            val = input(f"  opencv_extra_dir [{cfg['opencv_extra_dir']}]: ").strip()
            if val:
                cfg["opencv_extra_dir"] = val
        elif choice == "5":
            while True:
                val = input(f"  auto_impl [{cfg['auto_impl']}] (python/cpp/both): ").strip().lower()
                if not val:
                    break
                if val in ("python", "cpp", "both"):
                    cfg["auto_impl"] = val
                    break
                print("    allowed: python | cpp | both")
        elif choice == "6":
            while True:
                val = input(f"  manual_impl [{cfg['manual_impl']}] (python/cpp/both): ").strip().lower()
                if not val:
                    break
                if val in ("python", "cpp", "both"):
                    cfg["manual_impl"] = val
                    break
                print("    allowed: python | cpp | both")
        elif choice == "7":
            _edit_cpp(cfg)
        elif choice == "8":
            while True:
                val = input(f"  manual.reconnect_window [{cfg.get('manual_reconnect_window', 30)}] seconds: ").strip()
                if not val:
                    break
                try:
                    cfg["manual_reconnect_window"] = int(val)
                    break
                except ValueError:
                    print("    please enter an integer")
        elif choice == "9":
            while True:
                val = input(f"  manual.long_run [{cfg.get('manual_long_run', 0)}] minutes (0=skip): ").strip()
                if not val:
                    break
                try:
                    cfg["manual_long_run"] = int(float(val))
                    break
                except ValueError:
                    print("    please enter a number")
        elif choice == "10":
            while True:
                val = input(f"  combined_report [{'yes' if cfg['combined_report'] else 'no'}] (yes/no): ").strip().lower()
                if not val:
                    break
                if val in ("y", "yes", "true", "1"):
                    cfg["combined_report"] = True
                    break
                if val in ("n", "no", "false", "0"):
                    cfg["combined_report"] = False
                    break
                print("    please answer yes/no")
        else:
            print(f"  invalid choice '{choice}', use 1-10 or Enter")
            continue

        # Re-display updated settings after each edit
        print("\n== Updated settings ==")
        for line in _settings_lines(cfg):
            print(line)
        more = input("\nModify another? [y/N]: ").strip().lower()
        if more not in ("y", "yes"):
            break
    return cfg


def _edit_cpp(cfg):
    which = input("  Edit which? [1=auto_cpp/manual_cpp 2=official]: ").strip().lower()
    if not which or which in ("3", "both"):
        print("  Please edit one at a time: 1=auto_cpp/manual_cpp, 2=official")
        return

    if which in ("1", "auto", "auto_cpp", "manual"):
        key = "cpp"
        cpp = cfg.get("cpp", {})
        print(f"  -- editing {key} (auto_cpp / manual_cpp) --")
        # source selection
        val = input(f"    source [{cpp.get('source', 'apt')}] (apt/selfbuild): ").strip().lower()
        if val in ("apt", "selfbuild"):
            cpp["source"] = val
        if cpp.get("source") == "apt":
            val = input(f"    apt_package [{cpp.get('apt_package','libopencv-dev')}]: ").strip()
            if val:
                cpp["apt_package"] = val
            return
        branch = cpp.get("branch", "latest")
    else:
        key = "official_cpp"
        if key not in cfg or not isinstance(cfg[key], dict):
            cfg[key] = dict(cfg.get("cpp", {}))
        cpp = cfg[key]
        cpp["source"] = "selfbuild"  # official always selfbuild
        branch = cpp.get("branch", "latest")

    # selfbuild path editing - show base dirs without version suffix
    src_base = cpp.get("_source_dir_base") or "./opencv_source_code"
    build_base = cpp.get("_build_dir_base") or "./build_official" if key == "official_cpp" else "./build"

    val = input(f"    source_dir [{src_base}]: ").strip()
    if val:
        src_base = val.rstrip("/")
    else:
        src_base = src_base.rstrip("/")

    val = input(f"    build_dir [{build_base}]: ").strip()
    if val:
        build_base = val.rstrip("/")
    else:
        build_base = build_base.rstrip("/")

    val = input(f"    branch/version [{branch}]: ").strip()
    if val:
        branch = val

    cpp["_source_dir_base"] = src_base
    cpp["_build_dir_base"] = build_base
    cpp["branch"] = branch
    # Resolve versioned paths: base/branch
    cpp["source_dir"] = _resolve_versioned_path(src_base, branch)
    cpp["build_dir"] = _resolve_versioned_path(build_base, branch)


def ask_tests(cfg):
    print("\nWhich tests to run?")
    print("  1) auto")
    print("  2) manual")
    print("  3) official")
    print("  4) all")
    by_num = {"1": ["auto"], "2": ["manual"], "3": ["official"],
              "4": list(SUITE_ORDER)}
    while True:
        try:
            raw = input("Select [4]: ").strip().lower()
        except EOFError:
            return list(SUITE_ORDER)
        if not raw:
            raw = "4"
        if raw in by_num:
            return by_num[raw]
        picked = [t.strip() for t in raw.split(",") if t.strip()]
        if picked and all(t in SUITE_ORDER for t in picked):
            return [t for t in SUITE_ORDER if t in set(picked)]
        print("  invalid choice; enter 1-4 (or suite names like 'auto,manual')")


def check_official_env(env_dir, cpp=None):
    """Return list of missing prerequisites for the official suite.

    official_cpp is always selfbuild; uses versioned paths.
    """
    ocpp = cpp if isinstance(cpp, dict) else {}
    branch = ocpp.get("branch", "latest")
    src_base = ocpp.get("source_dir_base", "./opencv_source_code")
    build_base = ocpp.get("build_dir_base", "./build_official")

    # If source_dir already contains the branch, don't append again
    sd = ocpp.get("source_dir", _resolve_versioned_path(src_base, branch))
    bd = ocpp.get("build_dir", _resolve_versioned_path(build_base, branch))

    if not os.path.isabs(sd):
        sd = os.path.join(HERE, sd)
    if not os.path.isabs(bd):
        bd = os.path.join(HERE, bd)

    missing = []
    if not os.path.isdir(sd):
        missing.append(f"selfbuild source repo -> {sd}")
    # testdata is still needed under opencv_extra_dir/opencv_extra
    root = os.path.abspath(env_dir)
    for sub in ("testdata/cv", "testdata/highgui"):
        if not os.path.isdir(os.path.join(root, "opencv_extra", sub)):
            missing.append(f"opencv_extra/{sub}  -> {root}/opencv_extra")
    bin_ = os.path.join(bd, "bin", "opencv_test_videoio")
    if not os.path.isfile(bin_):
        missing.append(f"built test binary     -> {bin_}")
    return missing


def auto_setup_official(cfg, dry_run=False):
    """Auto-setup missing official prerequisites (testdata, test binary).
    For selfbuild: source/build shared with auto_cpp/manual_cpp.
    Only needs to fetch opencv_extra/testdata and build opencv_test_videoio."""
    ocpp = cfg.get("official_cpp", cfg.get("cpp", {}))
    branch = ocpp.get("branch", "latest")
    env_root = os.path.abspath(cfg.get("opencv_extra_dir", "."))

    # Check what's missing
    need_testdata = not os.path.isdir(
        os.path.join(env_root, "opencv_extra", "testdata"))
    src_base = ocpp.get("_source_dir_base") or "./opencv_source_code"
    build_base = ocpp.get("_build_dir_base") or "./build"
    sd = _resolve_versioned_path(src_base, branch)
    bd = _resolve_versioned_path(build_base, branch)
    if not os.path.isabs(sd):
        sd = os.path.join(HERE, sd)
    if not os.path.isabs(bd):
        bd = os.path.join(HERE, bd)
    need_binary = not os.path.isfile(os.path.join(bd, "bin", "opencv_test_videoio"))

    print("\n== Auto-setup official environment ==")

    # Step 1: fetch opencv_extra/testdata
    if need_testdata:
        extra_dir = os.path.join(env_root, "opencv_extra")
        print(f"  [testdata] fetching opencv_extra -> {extra_dir}")
        if dry_run:
            print("  [dry-run] skip")
            return True
        try:
            if os.path.isdir(extra_dir):
                shutil.rmtree(extra_dir)
            subprocess.run(
                ["git", "clone", "--depth", "1",
                 "--filter=blob:none", "--sparse",
                 "https://github.com/opencv/opencv_extra.git", extra_dir],
                check=True, timeout=300)
            for sub in ("testdata/cv", "testdata/highgui"):
                print(f"    sparse-checkout add {sub} (may take a few minutes)...")
                subprocess.run(["git", "sparse-checkout", "add", sub],
                               cwd=extra_dir, check=True, timeout=1800)
            r = subprocess.run(["du", "-sh", os.path.join(extra_dir, "testdata")],
                               capture_output=True, text=True, timeout=30)
            size = r.stdout.split()[0] if r.stdout else "?"
            print(f"  OK: testdata fetched ({size})")
        except Exception as e:
            print(f"  FAIL: {e}")
            return False
    else:
        print("  testdata already present")

    # Step 1.5: clone opencv source if missing
    need_source = not os.path.isdir(os.path.join(sd, ".git"))
    if need_source:
        print(f"  [source] cloning opencv -> {sd}")
        if dry_run:
            print("  [dry-run] skip")
        else:
            try:
                clone_args = ["git", "clone", "--depth", "1"]
                if branch and branch != "latest":
                    clone_args += ["--branch", branch]
                clone_args += ["https://github.com/opencv/opencv.git", sd]
                subprocess.run(clone_args, check=True, timeout=600)
                print(f"  OK: opencv source cloned")
            except Exception as e:
                print(f"  FAIL: {e}")
                return False
    else:
        print("  opencv source already present")

    # Step 2: build opencv_test_videoio (shares selfbuild source/build)
    if need_binary:
        print(f"  [build] cmake {sd} -> {bd} (target=opencv_test_videoio)")
        if dry_run:
            print("  [dry-run] skip")
            return True
        try:
            subprocess.run(["cmake", "-S", sd, "-B", bd,
                            "-DCMAKE_BUILD_TYPE=Release",
                            "-DBUILD_TESTS=ON", "-DBUILD_PERF_TESTS=OFF",
                            "-DBUILD_EXAMPLES=OFF",
                            "-DBUILD_LIST=core,imgproc,imgcodecs,videoio,ts"],
                           check=True, timeout=300)
            subprocess.run(["cmake", "--build", bd, "--target",
                            "opencv_test_videoio", "-j", str(os.cpu_count())],
                           check=True, timeout=1800)
            binary = os.path.join(bd, "bin", "opencv_test_videoio")
            if os.path.isfile(binary):
                print(f"  OK: {binary}")
                return True
            print("  FAIL: binary not found after build")
            return False
        except Exception as e:
            print(f"  FAIL: {e}")
            return False
    else:
        print("  test binary already present")

    return True


def expand_suites(categories, impl, manual_impl):
    cats = ["auto", "official", "manual"] \
        if categories == ["all"] else list(categories)
    out = []
    for c in cats:
        if c == "auto":
            if impl in ("python", "both"):
                out.append("auto")
            if impl in ("cpp", "both"):
                out.append("auto-cpp")
        elif c == "manual":
            if manual_impl in ("python", "both"):
                out.append("manual")
            if manual_impl in ("cpp", "both"):
                out.append("manual-cpp")
        else:
            out.append(c)
    return out


def _cpp_env(cfg, for_suite="auto-cpp"):
    # auto/manual share cpp; official may have override
    if for_suite == "official" and "official_cpp" in cfg:
        cpp = cfg["official_cpp"]
    else:
        cpp = cfg.get("cpp", {"source": "apt", "source_dir": "./opencv_source_code", "build_dir": "./build"})
    src = cpp.get("source", "apt")
    env = dict(os.environ, PYTHONUNBUFFERED="1", CPP_OPENCV_SOURCE=src)
    for k in ("source_dir", "build_dir"):
        v = cpp.get(k, "")
        if v.startswith("./"):
            v = os.path.join(HERE, v[2:])
        env["OPENCV_" + k.upper()] = v
    env["OPENCV_SOURCE_DIR"] = env.get("OPENCV_SOURCE_DIR", "")
    env["OPENCV_BUILD_DIR"] = env.get("OPENCV_BUILD_DIR", "")
    env["REPORT_OPENCV_SOURCE"] = src
    # Per-suite env name for clarity
    env["CPP_SOURCE"] = src
    return env


def build_command(suite, cfg, report_dir):
    py = sys.executable
    dev = cfg["device"]
    backend = cfg["backend"]
    if suite == "auto":
        return [py, "-u", os.path.join(HERE, "auto", "opencv_camera_api_test.py"),
                "--device", dev, "--backend", backend, "--outdir", report_dir]
    if suite == "auto-cpp":
        return ["stdbuf", "-oL", "bash",
                os.path.join(HERE, "auto_cpp", "run_test.sh"),
                "--device", dev, "--backend", backend,
                "--frames", str(cfg.get("frames", 30)),
                "--outdir", report_dir]
    if suite == "manual":
        return [py, "-u", os.path.join(HERE, "manual", "run_manual_suite.py"),
                "--device", dev,
                "--reconnect-window", str(cfg.get("manual_reconnect_window", 30)),
                "--long-run", str(cfg.get("manual_long_run", 0)),
                "--report", os.path.join(report_dir, "report_manual.json"),
                "--excel-dir", report_dir,
                "--evidence", os.path.join(report_dir, "manual_evidence")]
    if suite == "manual-cpp":
        cmd = ["stdbuf", "-oL", "bash",
               os.path.join(HERE, "manual_cpp", "run_test.sh"),
               "-d", dev,
               "--reconnect-window", str(cfg.get("manual_reconnect_window", 30)),
               "--outdir", report_dir]
        lr = cfg.get("manual_long_run", 0)
        if lr and float(lr) > 0:
            cmd += ["--long-run", str(lr)]
        return cmd
    if suite == "official":
        ocpp = cfg.get("official_cpp", {})
        bd = ocpp.get("build_dir", "")
        cmd = [py, "-u",
               os.path.join(HERE, "official", "run_official_videoio_test.py"),
               "-e", cfg["opencv_extra_dir"], "-d", dev, "-o", report_dir]
        if bd:
            if bd.startswith("./"):
                bd = os.path.join(HERE, bd[2:])
            cmd += ["-b", bd]
        if cfg.get("official_console_output"):
            cmd += ["--console-output"]
        return cmd
    raise ValueError(suite)


def stream_run(cmd, tag, extra_env=None):
    """Stream child output live, including partial lines (input prompts).

    Char-level passthrough: prompts written without a newline (e.g.
    input("your verdict? ")) become visible immediately instead of being
    held until the child exits. The [tag] prefix is printed at line starts.
    """
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            bufsize=1, env=env)
    at_line_start = True
    while True:
        ch = proc.stdout.read(1)
        if ch == "":
            break
        if at_line_start:
            sys.stdout.write(f"[{tag}] ")
            at_line_start = False
        sys.stdout.write(ch)
        sys.stdout.flush()
        if ch == "\n":
            at_line_start = True
    proc.wait()
    return proc.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the planned commands and exit without running")
    ap.add_argument("command", nargs="?", default=None,
                    help="optional: 'clear' to clean up builds/reports")
    args = ap.parse_args()

    cfg, _ = load_config(args.config)

    # Handle 'clear' sub-command
    if args.command == "clear":
        do_clear(cfg)
        return 0

    show_settings(cfg)
    cfg = ask_modify(cfg)
    categories = ask_tests(cfg)
    suites = expand_suites(categories, cfg["auto_impl"],
                           cfg.get("manual_impl", "both"))

    if "official" in suites:
        print("\n== Official environment preflight ==")
        ocpp = cfg.get("official_cpp") or cfg.get("cpp", {})
        miss = check_official_env(cfg["opencv_extra_dir"], cpp=ocpp)
        env_root = os.path.abspath(cfg["opencv_extra_dir"])
        if not miss:
            print(f"  OK: official environment complete at {env_root}")
        else:
            print("  INCOMPLETE - missing prerequisites:")
            for m_item in miss:
                print(f"    - {m_item}")
            if args.dry_run:
                print("\n[dry-run] would auto-setup, continuing without execution.")
            else:
                # Ask user to auto-setup
                confirm = input("\n  Auto-setup now? [Y/n]: ").strip().lower()
                if confirm in ("n", "no"):
                    print("\nAborted: run setup manually, then re-run.")
                    return 2
                ok = auto_setup_official(cfg, dry_run=False)
                if not ok:
                    print("\nAuto-setup failed. Fix the issue and re-run.")
                    return 2
                # Re-check
                miss2 = check_official_env(cfg["opencv_extra_dir"], cpp=ocpp)
                if miss2:
                    print("  Still incomplete after auto-setup:")
                    for m_item in miss2:
                        print(f"    - {m_item}")
                    return 2
                print("  OK: official environment ready.")

    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    report_dir = os.path.join(cfg["report_dir"], stamp)

    print("\n== Execution plan ==")
    print(f"  report folder : {report_dir}/")
    planned = []
    for s in suites:
        cmd = build_command(s, cfg, report_dir)
        planned.append((s, cmd))
        print(f"  [{s:<8}] {' '.join(cmd)}")
    if cfg["combined_report"]:
        cmd = [sys.executable, "-u",
               os.path.join(HERE, "generate_combined_report.py"),
               "--auto", os.path.join(report_dir, "report_auto.json"),
               "--auto-cpp", os.path.join(report_dir, "report_cpp.json"),
               "--manual", os.path.join(report_dir, "report_manual.json"),
            "--manual-cpp", os.path.join(report_dir, "report_manual_cpp.json"),
               "--official-log", os.path.join(report_dir, "videoio_gtest.log"),
               "--outdir", report_dir]
        planned.append(("combined", cmd))
        print(f"  [{'combined':<8}] {' '.join(cmd)}")

    # Persist user config after interactive modify (unless dry-run with no modify)
    # Only save if stdin was interactive and cfg may have been updated
    if not args.dry_run:
        try:
            _save_user_config(cfg)
        except Exception as e:
            print(f"[config] warning: could not save {USER_CONFIG}: {e}")
    else:
        # dry-run: also save if config differs from file (so --dry-run can preview save)
        try:
            _save_user_config(cfg)
            print(f"[dry-run] config saved to {USER_CONFIG}")
        except Exception:
            pass

    if args.dry_run:
        print("\n[dry-run] no commands executed.")
        return 0

    os.makedirs(report_dir, exist_ok=True)
    # Persist report-side opencv source provenance
    try:
        prov = {
            "cpp_source": cfg.get("cpp", {}).get("source", "apt"),
            "cpp_branch": cfg.get("cpp", {}).get("branch", ""),
            "opencv_version": __import__("subprocess").check_output(
                ["pkg-config", "--modversion", "opencv4"], text=True
            ).strip() if cfg.get("cpp", {}).get("source") == "apt" else "selfbuild:" + cfg.get("cpp", {}).get("branch", ""),
        }
        with open(os.path.join(report_dir, "build_provenance.json"), "w", encoding="utf-8") as f:
            import json
            json.dump(prov, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    failed = []
    cpp_env = _cpp_env(cfg)
    for name, cmd in planned:
        print(f"\n>>>> running {name} " + "=" * 40)
        rc = stream_run(cmd, name, extra_env=cpp_env if name in ("auto-cpp", "manual-cpp", "official") else None)
        if rc != 0 and name != "combined":
            failed.append((name, rc))
            print(f"\n[{name}] finished with exit code {rc}")

    print("\n" + "=" * 60)
    print("ALL SELECTED SUITES FINISHED")
    print("=" * 60)
    for name, rc in failed:
        print(f"  FAILED: {name} (exit {rc})")
    if not failed:
        print("  all selected suites returned exit code 0")
    print(f"  reports : {os.path.abspath(report_dir)}{os.sep}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
