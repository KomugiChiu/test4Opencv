#!/usr/bin/env python3
"""Setup the environment for OpenCV official videoio tests.

Creates under TARGET DIR:
    opencv/          shallow clone of OpenCV source
    opencv_extra/    sparse checkout of test media (testdata/cv + testdata/highgui)
    build/           CMake build tree with bin/opencv_test_videoio

Usage:
    python3 setup_official_videoio_env.py [-d DIR] [-j N] [-b BRANCH]
                                          [-B EXTRA_BRANCH] [-y]

Existing items trigger an interactive "redo?" prompt; Enter keeps them.
-y answers yes to every prompt.
"""
import argparse
import os
import shutil
import subprocess
import sys

OPENCV_URL = "https://github.com/opencv/opencv.git"
EXTRA_URL = "https://github.com/opencv/opencv_extra.git"
SPARSE_DIRS = ["testdata/cv", "testdata/highgui"]


def run(cmd, cwd=None):
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def ask_redo(label, assume_yes):
    if assume_yes:
        return True
    try:
        ans = input(f"Found existing {label}. Redo it? [y/N] ").strip()
    except EOFError:
        ans = ""
    return ans.lower() == "y"


def tool_check():
    missing = [t for t in ("git", "cmake", "make", "g++") if not shutil.which(t)]
    if missing:
        sys.exit(f"ERROR: required tools not found: {', '.join(missing)}")


def git_clone(url, dest, branch=None, extra_args=()):
    # branch=="latest" means HEAD (no --branch)
    if branch == "latest":
        branch = None
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    args = ["git", "clone", "--depth", "1", *extra_args]
    if branch:
        args += ["--branch", branch]
    args += [url, dest]
    run(args)


def setup_extra(dest, branch, assume_yes):
    marker = os.path.join(dest, ".git")
    if os.path.isdir(marker):
        if not ask_redo("opencv_extra/ clone (test media)", assume_yes):
            print("== opencv_extra/: keep existing")
        else:
            git_clone(EXTRA_URL, dest, branch,
                      ["--filter=blob:none", "--sparse"])
    else:
        git_clone(EXTRA_URL, dest, branch, ["--filter=blob:none", "--sparse"])
    current = ""
    r = subprocess.run(["git", "sparse-checkout", "list"],
                       cwd=dest, capture_output=True, text=True)
    if r.returncode == 0:
        current = r.stdout
    for sub in SPARSE_DIRS:
        if sub not in current.split():
            run(["git", "sparse-checkout", "add", sub], cwd=dest)
    size = subprocess.run(["du", "-sh", os.path.join(dest, "testdata")],
                          capture_output=True, text=True).stdout.split()[0]
    print(f"== testdata size: {size}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-d", "--dir", default=os.getcwd(),
                    help="target directory (default: current directory)")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count(),
                    help="parallel build jobs (default: nproc)")
    ap.add_argument("-b", "--branch", default=None, help="opencv branch")
    ap.add_argument("-B", "--extra-branch", default=None,
                    help="opencv_extra branch")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="answer YES to every redo prompt")
    args = ap.parse_args()

    target = os.path.abspath(args.dir)
    os.makedirs(target, exist_ok=True)
    print(f"== target dir : {target}")
    print(f"== jobs       : {args.jobs}")
    tool_check()

    # Respect yaml cpp.branch when --branch not given: read from run_config.yaml/cpp.branch
    if args.branch is None:
        for base in (target, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")):
            for cand in (os.path.join(base, "run_config.yaml"), os.path.join(base, "run_config.default.yaml")):
                if os.path.isfile(cand):
                    try:
                        import yaml
                        c = yaml.safe_load(open(cand, encoding="utf-8")) or {}
                        yaml_branch = c.get("cpp", {}).get("branch")
                        if yaml_branch:
                            args.branch = yaml_branch
                            print(f"[config] cpp.branch from {cand}: {yaml_branch} (use -b to override)")
                            break
                    except Exception:
                        pass
            if args.branch:
                break
    if args.branch == "latest":
        args.branch = None

    ocv = os.path.join(target, "opencv")
    # If yaml source is selfbuild with custom source_dir, respect it
    yaml_source_dir = None
    for base in (target, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")):
        for cand in (os.path.join(base, "run_config.yaml"), os.path.join(base, "run_config.default.yaml")):
            if os.path.isfile(cand):
                try:
                    import yaml
                    c = yaml.safe_load(open(cand, encoding="utf-8")) or {}
                    cpp = c.get("cpp", {})
                    if cpp.get("source") == "selfbuild" and cpp.get("source_dir"):
                        sd = cpp["source_dir"]
                        yaml_source_dir = sd if os.path.isabs(sd) else os.path.join(os.path.dirname(cand), sd)
                        # Also map build_dir
                        bd = cpp.get("build_dir", "./build")
                        build = bd if os.path.isabs(bd) else os.path.join(os.path.dirname(cand), bd)
                        print(f"[config] cpp selfbuild: source_dir={yaml_source_dir} build_dir={build}")
                        ocv = yaml_source_dir
                        break
                except Exception:
                    pass
        if yaml_source_dir:
            break

    if os.path.isdir(os.path.join(ocv, ".git")):
        if not ask_redo("opencv/ clone", args.yes):
            print("== opencv/: keep existing")
        else:
            git_clone(OPENCV_URL, ocv, args.branch)
    else:
        git_clone(OPENCV_URL, ocv, args.branch)

    extra = os.path.join(target, "opencv_extra")
    setup_extra(extra, args.extra_branch, args.yes)

    # build dir from yaml if selfbuild
    build = os.path.join(target, "build")
    for base in (target, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")):
        for cand in (os.path.join(base, "run_config.yaml"), os.path.join(base, "run_config.default.yaml")):
            if os.path.isfile(cand):
                try:
                    import yaml
                    c = yaml.safe_load(open(cand, encoding="utf-8")) or {}
                    cpp = c.get("cpp", {})
                    if cpp.get("source") == "selfbuild" and cpp.get("build_dir"):
                        bd = cpp["build_dir"]
                        build = bd if os.path.isabs(bd) else os.path.join(os.path.dirname(cand), bd)
                        break
                except Exception:
                    pass
        else:
            continue
        break
    binary = os.path.join(build, "bin", "opencv_test_videoio")
    redo_build = True
    if os.path.isfile(binary):
        if not ask_redo("build tree (reconfigure & recompile)", args.yes):
            print("== build/: keep existing binary")
            redo_build = False
    if redo_build:
        cmake_args = [
            "-DCMAKE_BUILD_TYPE=Release",
            "-DBUILD_LIST=core,imgproc,imgcodecs,videoio,ts",
            "-DBUILD_TESTS=ON", "-DBUILD_PERF_TESTS=OFF",
            "-DBUILD_EXAMPLES=OFF", "-DBUILD_opencv_apps=OFF",
            "-DWITH_IPP=OFF", "-DWITH_ITT=OFF",
            "-DWITH_OPENCL=OFF", "-DWITH_GTK=OFF",
            f"-DOPENCV_TEST_DATA_PATH={os.path.join(extra, 'testdata')}",
        ]
        run(["cmake", "-S", ocv, "-B", build, *cmake_args])
        run(["cmake", "--build", build, "--target",
             "opencv_test_videoio", "-j", str(args.jobs)])

    if not os.path.isfile(binary):
        sys.exit(f"ERROR: test binary not found at {binary}")

    runner = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "run_official_videoio_test.py")
    print(f"""
== setup complete ==
binary      : {binary}
testdata    : {extra}/testdata
run example :
  python3 {runner} -e "{target}" -o "{target}/report"
""")


if __name__ == "__main__":
    main()
