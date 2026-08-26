#!/usr/bin/env python3
"""OpenCV camera API coverage test tool.

Probes the OpenCV videoio/camera API surface on a given device and emits a
colored terminal summary plus Markdown/JSON/Excel reports (report.md,
report.json, report.xlsx) suitable for humans, CI pipelines and management.

Coverage is reported in three tiers:
- core : curated planned checks (groups A-F plan)
- full : core + every dir() method of VideoCapture/VideoWriter/registry
         + ALL enumerated CAP_PROP_* constants (group F sweep)
- skipped-by-design: properties belonging to other backend families
         (Ximea/DC1394/Android/...) that cannot apply to the selected backend

Exit codes: 0=all PASS, 1=has FAIL, 2=no camera (camera checks SKIP),
3=OpenCV not importable.
"""

import argparse
import glob
import itertools
import json
import math
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime

try:
    import cv2
    import numpy as np
    CV2_OK = True
except Exception:
    CV2_OK = False

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
BACKEND_CHOICES = ["ANY", "V4L2", "GSTREAMER", "FFMPEG"]
UNIFORM_STD_THRESH = 2.0
FREEZE_DIFF_THRESH = 0.5
OPEN_TIMEOUT_SEC = 10

GROUP_DESC = {
    "A": "Environment",
    "B": "Lifecycle",
    "C": "Properties (curated set/get)",
    "D": "Frame quality",
    "E": "VideoWriter",
    "F": "CAP_PROP full sweep",
    "G": "Driver cross-validation",
}

NEGATIVE_DEVICE = "/dev/video63"

OPEN_ONLY_PROPS = [
    ("CAP_PROP_HW_ACCELERATION", 0),
    ("CAP_PROP_HW_DEVICE", 0),
    ("CAP_PROP_HW_ACCELERATION_USE_OPENCL", 0),
    ("CAP_PROP_OPEN_TIMEOUT_MSEC", 5000),
    ("CAP_PROP_READ_TIMEOUT_MSEC", 5000),
]

PROPERTY_TARGETS = [
    "FRAME_WIDTH", "FRAME_HEIGHT", "FPS", "FOURCC", "BUFFERSIZE",
    "AUTO_EXPOSURE", "EXPOSURE", "GAIN", "FORMAT", "MODE", "CONVERT_RGB",
]

E_WRITER_APIS = [
    "VideoWriter.fourcc()",
    "VideoWriter(path, fourcc, fps, size)",
    "writer.isOpened()",
    "writer.getBackendName()",
    "writer.get(VIDEOWRITER_PROP_*)",
    "writer.set(VIDEOWRITER_PROP_*)",
    "writer.write()",
    "writer.release()",
    "VideoWriter readback",
]

PROP_BACKEND_FAMILIES = [
    ("DC1394", "FireWire/DC1394"),
    ("OPENNI2", "OpenNI2"),
    ("OPENNI", "OpenNI"),
    ("ANDROID", "Android"),
    ("PVAPI", "Pleora PVAPI"),
    ("GIGA", "Basler GigE"),
    ("INTELPERC", "Intel Perceptual"),
    ("XI", "Ximea"),
    ("V4L", "V4L2"),
    ("GSTREAMER", "GStreamer"),
    ("UEYE", "uEye"),
    ("OBSENSOR", "Orbbec"),
    ("ARAVIS", "Aravis"),
    ("WINRT", "Windows RT"),
    ("MSMF", "MSMF"),
    ("AVFOUNDATION", "AVFoundation"),
    ("DSHOW", "DirectShow"),
    ("FIREWIRE", "FireWire"),
    ("GPHOTO2", "gPhoto2"),
    ("IOS_DEVICE", "iOS/AVFoundation"),
]

EXTRA_KNOWN_PROPS = [
    "CAP_PROP_AUDIO_BASE_INDEX", "CAP_PROP_AUDIO_DATA_DEPTH",
    "CAP_PROP_AUDIO_POS", "CAP_PROP_AUDIO_SAMPLES_PER_SECOND",
    "CAP_PROP_AUDIO_SHIFT_NSEC", "CAP_PROP_AUDIO_STREAM",
    "CAP_PROP_AUDIO_SYNCHRONIZE", "CAP_PROP_AUDIO_TOTAL_CHANNELS",
    "CAP_PROP_AUDIO_TOTAL_STREAMS", "CAP_PROP_CODEC_EXTRADATA_INDEX",
    "CAP_PROP_DTS_DELAY", "CAP_PROP_FRAME_TYPE",
    "CAP_PROP_IMAGE_SEQ_START", "CAP_PROP_LRF_HAS_KEY_FRAME",
    "CAP_PROP_N_THREADS", "CAP_PROP_PTS", "CAP_PROP_VIDEO_STREAM",
    "CAP_PROP_VIDEO_TOTAL_CHANNELS", "VIDEOWRITER_PROP_COLOR_SPACE",
    "VIDEOWRITER_PROP_DTS_DELAY", "VIDEOWRITER_PROP_ENABLE_ALPHA",
    "VIDEOWRITER_PROP_KEY_FLAG", "VIDEOWRITER_PROP_KEY_INTERVAL",
    "VIDEOWRITER_PROP_PTS", "VIDEOWRITER_PROP_RAW_VIDEO",
]

NO_SET_BLACKLIST = {
    "SETTINGS", "GUID", "POS_MSEC", "POS_FRAMES", "POS_AVI_RATIO",
    "FRAME_COUNT",
}

EXIT_MEANINGS = {
    0: "all executed checks passed",
    1: "at least one check FAILED",
    2: "no camera available (camera checks skipped)",
    3: "OpenCV (cv2) not installed",
}


class Color:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def _wrap(self, code, text):
        return f"\033[{code}m{text}\033[0m" if self.enabled else str(text)

    def green(self, t):
        return self._wrap("32", t)

    def red(self, t):
        return self._wrap("31", t)

    def yellow(self, t):
        return self._wrap("33", t)

    def dim(self, t):
        return self._wrap("2", t)

    def bold(self, t):
        return self._wrap("1", t)

    def cyan(self, t):
        return self._wrap("36", t)


@dataclass
class Result:
    group: str
    api: str
    status: str
    message: str = ""
    detail: str = ""


class Suite:
    def __init__(self, args, color):
        self.args = args
        self.color = color
        self.results = []
        self.metrics = {}
        self.frames = []
        self.camera_ok = False
        self.cap = None

    def add(self, group, api, status, message="", detail=""):
        result = Result(group, api, status, message, detail)
        self.results.append(result)
        self._progress(result)
        return result

    def _progress(self, r):
        marks = {"PASS": self.color.green, "FAIL": self.color.red,
                 "WARN": self.color.yellow, "SKIP": self.color.dim}
        head = f"[{r.group}] {r.api}"
        dots = "." * max(2, 62 - len(head))
        suffix = f" {r.message}" if r.message else ""
        print(f"{head} {dots} {marks[r.status](r.status)}{suffix}")


class OpenTimeout(Exception):
    pass


class timeout:
    """signal.alarm based timeout for blocking VideoCapture calls (POSIX)."""

    def __init__(self, seconds):
        self.seconds = seconds
        self._old = None

    def __enter__(self):
        if hasattr(signal, "SIGALRM"):
            self._old = signal.signal(signal.SIGALRM, self._raise)
            signal.alarm(max(1, int(self.seconds)))

    def __exit__(self, *exc):
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
            if self._old is not None:
                signal.signal(signal.SIGALRM, self._old)

    @staticmethod
    def _raise(signum, frame):
        raise OpenTimeout("operation timed out")


def call_with_timeout(func, seconds):
    try:
        with timeout(seconds):
            return "ok", func()
    except OpenTimeout:
        return "timeout", f"timed out after {seconds}s"
    except Exception as e:
        return "error", f"raised: {e}"


def resolve_device(raw):
    text = str(raw).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    return text


def backend_id(name):
    return {"ANY": cv2.CAP_ANY, "V4L2": cv2.CAP_V4L2,
            "GSTREAMER": cv2.CAP_GSTREAMER, "FFMPEG": cv2.CAP_FFMPEG}[name]


def fourcc_to_str(value):
    try:
        v = int(value) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return "????"
    return "".join(chr((v >> (8 * i)) & 0xFF)
                   if 0x20 <= ((v >> (8 * i)) & 0xFF) <= 0x7E else "?"
                   for i in range(4))


def safe_get(cap, prop):
    try:
        value = cap.get(prop)
        return None if value != value else value
    except Exception:
        return None


def parse_video_io(build_info):
    section, active = {}, False
    for line in build_info.splitlines():
        stripped = line.strip()
        if stripped.startswith("Video I/O"):
            active = True
            continue
        if active:
            if not stripped:
                break
            m = re.match(r"(.+?):\s*(YES|NO)(?:\s+\(.*?\))?\s*$", stripped)
            if m:
                section[m.group(1)] = m.group(2)
    return section


def dynamic_api_names():
    try:
        return sorted(m for m in dir(cv2.VideoCapture) if not m.startswith("_"))
    except Exception:
        return []


def writer_api_names():
    try:
        return sorted(m for m in dir(cv2.VideoWriter) if not m.startswith("_"))
    except Exception:
        return []


def registry_func_names():
    reg = getattr(cv2, "videoio_registry", None)
    if reg is None:
        return []
    try:
        return sorted(m for m in dir(reg) if not m.startswith("_"))
    except Exception:
        return []


def enumerate_cap_props():
    seen, out = {}, []
    for n in sorted(dir(cv2)):
        if not n.startswith("CAP_PROP_"):
            continue
        try:
            pid = int(getattr(cv2, n))
        except (TypeError, ValueError):
            continue
        short = n[len("CAP_PROP_"):]
        if pid in seen:
            seen[pid]["aliases"].append(short)
            continue
        entry = {"name": short, "pid": pid, "aliases": []}
        seen[pid] = entry
        out.append(entry)
    return out


def prop_family(short_name):
    for token, label in PROP_BACKEND_FAMILIES:
        if short_name.startswith(token):
            return token, label
    return None, None


def family_applicable(token, backend):
    if token == "V4L":
        return backend in ("ANY", "V4L2")
    if token == "GSTREAMER":
        return backend in ("ANY", "GSTREAMER")
    return False


def planned_check_items():
    items = [
        ("A", "cv2.__version__"),
        ("A", "build: V4L2 support"),
        ("A", "build: GStreamer support"),
        ("A", "videoio_registry.getBackends()"),
        ("A", "videoio_registry.getBackendName()"),
        ("A", "videoio_registry.hasBackend()"),
        ("A", "videoio_registry.getCameraBackends()"),
        ("A", "videoio_registry.getStreamBackends()"),
        ("A", "videoio_registry.getWriterBackends()"),
        ("A", "videoio_registry.isBackendBuiltIn()"),
        ("A", "videoio_registry.getCameraBackendPluginVersion()"),
        ("A", "videoio_registry.getStreamBackendPluginVersion()"),
        ("A", "videoio_registry.getWriterBackendPluginVersion()"),
        ("A", "videoio_registry.getStreamBufferedBackends()"),
        ("A", "videoio_registry.getStreamBufferedBackendPluginVersion()"),
        ("B", "VideoCapture(device, backend)"),
        ("B", "open()"),
        ("B", "isOpened()"),
        ("B", "getBackendName()"),
        ("B", "getExceptionMode()/setExceptionMode()"),
        ("B", "waitAny()"),
        ("B", "isOpened() negative case"),
        ("B", "open_only_props_precheck"),
        ("B", "backend_any_vs_v4l2"),
        ("B", "grab()"),
        ("B", "retrieve()"),
        ("B", "read() loop"),
        ("B", "release()"),
    ]
    items += [("C", f"CAP_PROP_{name} get/set") for name in PROPERTY_TARGETS]
    items += [("D", x) for x in ("frame not None", "frame dimensions",
                                 "pixel variance", "freeze detection")]
    items += [("E", x) for x in E_WRITER_APIS]
    items += [("E", "VIDEOWRITER_PROP_* inventory")]
    items += [("F", "CAP_PROP_* full sweep")]
    items += [("G", "negotiated fmt within v4l2-ctl advertised list")]
    return items


def skip_camera_rest(s, reason, include_open=False):
    opened_apis = ("VideoCapture(device, backend)", "open()", "isOpened()")
    for group, api in planned_check_items():
        if group == "A":
            continue
        if not include_open and group == "B" and api in opened_apis:
            continue
        s.add(group, api, SKIP, reason)


def check_environment(s):
    s.add("A", "cv2.__version__", PASS, cv2.__version__)
    s.metrics["opencv_version"] = cv2.__version__

    build = cv2.getBuildInformation()
    vio = parse_video_io(build)
    s.metrics["video_io_build"] = vio

    want = s.args.backend
    v4l_ok = vio.get("v4l/v4l2", "NO") == "YES"
    gst_ok = vio.get("GStreamer", "NO") == "YES"
    # Relevance follows the requested backend: a backend the suite is not
    # using is skipped instead of polluting results with WARN/FAIL.
    if family_applicable("V4L", want):
        s.add("A", "build: V4L2 support", PASS if v4l_ok else FAIL,
              f"v4l/v4l2={vio.get('v4l/v4l2', 'unknown')}")
    else:
        s.add("A", "build: V4L2 support", SKIP,
              f"not applicable: backend={want} "
              f"(build has v4l/v4l2={vio.get('v4l/v4l2', 'unknown')})")
    if family_applicable("GSTREAMER", want):
        s.add("A", "build: GStreamer support", PASS if gst_ok else FAIL,
              f"GStreamer={vio.get('GStreamer', 'unknown')}")
    else:
        s.add("A", "build: GStreamer support", SKIP,
              f"not applicable: backend={want} "
              f"(build has GStreamer={vio.get('GStreamer', 'unknown')})")

    reg = getattr(cv2, "videoio_registry", None)
    if reg is None or not hasattr(reg, "getBackends"):
        for api in ("videoio_registry.getBackends()",
                    "videoio_registry.getBackendName()",
                    "videoio_registry.hasBackend()",
                    "videoio_registry.getCameraBackends()",
                    "videoio_registry.getStreamBackends()",
                    "videoio_registry.getWriterBackends()",
                    "videoio_registry.isBackendBuiltIn()",
                    "videoio_registry.getCameraBackendPluginVersion()"):
            s.add("A", api, SKIP, "videoio_registry unavailable")
        return
    try:
        backends = list(reg.getBackends())
        names = [reg.getBackendName(b) for b in backends]
    except Exception as e:
        s.add("A", "videoio_registry.getBackends()", FAIL, f"raised: {e}")
        for api in ("videoio_registry.getBackendName()",
                    "videoio_registry.hasBackend()",
                    "videoio_registry.getCameraBackends()",
                    "videoio_registry.getStreamBackends()",
                    "videoio_registry.getWriterBackends()",
                    "videoio_registry.isBackendBuiltIn()",
                    "videoio_registry.getCameraBackendPluginVersion()"):
            s.add("A", api, SKIP, "registry call failed")
        return
    s.add("A", "videoio_registry.getBackends()",
          PASS if names else FAIL, ", ".join(names) if names else "empty")
    s.metrics["registered_backends"] = names

    if names:
        first = names[0]
        try:
            label = reg.getBackendName(backends[0])
            s.add("A", "videoio_registry.getBackendName()", PASS,
                  f"{label} (id={backends[0]})")
        except Exception as e:
            s.add("A", "videoio_registry.getBackendName()", FAIL, f"raised: {e}")
    else:
        s.add("A", "videoio_registry.getBackendName()", SKIP, "no backends registered")

    for fname in ("getCameraBackends", "getStreamBackends", "getWriterBackends"):
        fn = getattr(reg, fname, None)
        api = f"videoio_registry.{fname}()"
        if fn is None:
            s.add("A", api, SKIP, "not available in this cv2")
            continue
        try:
            blist = list(fn())
            bnames = [reg.getBackendName(b) for b in blist]
            s.add("A", api, PASS if bnames else WARN,
                  ", ".join(bnames) or "empty list")
        except Exception as e:
            s.add("A", api, FAIL, f"raised: {e}")

    fn = getattr(reg, "isBackendBuiltIn", None)
    probe_name = want if want != "ANY" else ("V4L2" if sys.platform.startswith("linux") else "ANY")
    if fn is None:
        s.add("A", "videoio_registry.isBackendBuiltIn()", SKIP, "not available in this cv2")
    else:
        try:
            built_in = bool(fn(backend_id(probe_name)))
            s.add("A", "videoio_registry.isBackendBuiltIn()", PASS,
                  f"isBackendBuiltIn({probe_name})={built_in}")
        except Exception as e:
            s.add("A", "videoio_registry.isBackendBuiltIn()", FAIL, f"raised: {e}")

    fn = getattr(reg, "getCameraBackendPluginVersion", None)
    if fn is None:
        s.add("A", "videoio_registry.getCameraBackendPluginVersion()", SKIP,
              "not available in this cv2")
    else:
        st, res = call_with_timeout(lambda: fn(backend_id(probe_name)), 5)
        if st == "ok":
            s.add("A", "videoio_registry.getCameraBackendPluginVersion()",
                  PASS, f"{probe_name} plugin={res}")
        else:
            s.add("A", "videoio_registry.getCameraBackendPluginVersion()",
                  SKIP, f"builtin backend has no plugin version ({res})")

    # stream/writer variants: probe the first NON-builtin backend of the
    # matching mode list (a plugin) instead of the selected device backend.
    # Registered-but-unavailable factories (e.g. GSTREAMER without the
    # runtime libs) are excluded via hasBackend().
    fn_builtin = getattr(reg, "isBackendBuiltIn", None)
    fn_has = getattr(reg, "hasBackend", None)
    for fname, listname, label in (
            ("getStreamBackendPluginVersion", "getStreamBackends",
             "videoio_registry.getStreamBackendPluginVersion()"),
            ("getWriterBackendPluginVersion", "getWriterBackends",
             "videoio_registry.getWriterBackendPluginVersion()")):
        fn = getattr(reg, fname, None)
        lfn = getattr(reg, listname, None)
        if fn is None or lfn is None:
            s.add("A", label, SKIP, "not available in this cv2")
            continue
        try:
            cands = list(lfn())
        except Exception:
            cands = []
        hit = None
        skipped_unavail = 0
        for b in cands:
            try:
                if fn_builtin is not None and not fn_builtin(b):
                    if fn_has is not None and not fn_has(b):
                        skipped_unavail += 1
                        continue
                    hit = b
                    break
            except Exception:
                continue
        if hit is None:
            s.add("A", label, SKIP,
                  f"no available plugin backend in {listname}()"
                  + (f" ({len(cands)} registered, {skipped_unavail} unavailable)"
                     if cands else ""))
            continue
        name = reg.getBackendName(hit)
        st, res = call_with_timeout(lambda fn=fn, hit=hit: fn(hit), 5)
        if st == "ok":
            s.add("A", label, PASS, f"{name} plugin={res}")
        else:
            s.add("A", label, WARN, f"{name} raised: {res}")

    if hasattr(reg, "hasBackend"):
        probe_name = want if want != "ANY" else ("V4L2" if sys.platform.startswith("linux") else "ANY")
        try:
            has = bool(reg.hasBackend(backend_id(probe_name)))
        except Exception:
            has = False
        s.add("A", "videoio_registry.hasBackend()",
              PASS if has else (FAIL if want != "ANY" else WARN),
              f"hasBackend({probe_name})={has}")
    else:
        s.add("A", "videoio_registry.hasBackend()", SKIP, "not available in this cv2")

    # [5.x] memory-buffer capture surface: VideoCapture(buffer) backends.
    # Device-less capability -> not applicable under an explicit device
    # backend such as V4L2.
    if want == "V4L2":
        s.add("A", "videoio_registry.getStreamBufferedBackends()", SKIP,
              "not applicable: backend=V4L2 (memory-buffer capture)")
        s.add("A", "videoio_registry.getStreamBufferedBackendPluginVersion()",
              SKIP, "not applicable: backend=V4L2 (memory-buffer capture)")
        return

    sb_api = "videoio_registry.getStreamBufferedBackends()"
    fn_sb = getattr(reg, "getStreamBufferedBackends", None)
    ids = []
    if fn_sb is None:
        s.add("A", sb_api, SKIP, "not available in this cv2 (<5.x)")
    else:
        try:
            ids = list(fn_sb())
            names = [reg.getBackendName(b) for b in ids]
            s.add("A", sb_api, PASS if names else WARN,
                  ", ".join(names) or "empty list")
        except Exception as e:
            s.add("A", sb_api, FAIL, f"raised: {e}")

    pv_api = "videoio_registry.getStreamBufferedBackendPluginVersion()"
    fn_pv = getattr(reg, "getStreamBufferedBackendPluginVersion", None)
    plugin_hit = None
    fn_builtin = getattr(reg, "isBackendBuiltIn", None)
    for b in ids:
        try:
            if fn_builtin is not None and not fn_builtin(b):
                plugin_hit = b
                break
        except Exception:
            continue
    if fn_pv is None or plugin_hit is None:
        s.add("A", pv_api, SKIP,
              "no plugin backend in buffer-capture list"
              + (f" ({len(ids)} builtin)" if ids else ""))
    else:
        st, res = call_with_timeout(lambda: fn_pv(plugin_hit), 5)
        name = reg.getBackendName(plugin_hit)
        if st == "ok":
            s.add("A", pv_api, PASS, f"{name} plugin={res}")
        else:
            s.add("A", pv_api, WARN, f"{name} raised: {res}")


def device_node_missing(args):
    if args.backend not in ("ANY", "V4L2"):
        return False
    dev = str(args.device).strip()
    if re.fullmatch(r"\d+", dev):
        return not os.path.exists(f"/dev/video{dev}")
    if dev.startswith("/dev/video"):
        return not os.path.exists(dev)
    return len(glob.glob("/dev/video*")) == 0


def open_camera(s):
    print(s.color.bold("\n== [B] Lifecycle =="))
    dev = resolve_device(s.args.device)
    bid = backend_id(s.args.backend)

    if device_node_missing(s.args):
        skip_camera_rest(s, f"camera device '{s.args.device}' not present", include_open=True)
        return

    status, payload = call_with_timeout(lambda: cv2.VideoCapture(dev, bid), OPEN_TIMEOUT_SEC)
    if status != "ok":
        s.add("B", "VideoCapture(device, backend)", FAIL, payload)
        skip_camera_rest(s, "camera failed to construct")
        return
    cap = payload
    s.cap = cap
    s.add("B", "VideoCapture(device, backend)", PASS, f"constructed (backend={s.args.backend})")

    status, result = call_with_timeout(lambda: bool(cap.open(dev, bid)), OPEN_TIMEOUT_SEC)
    if status == "ok":
        s.add("B", "open()", PASS if result else FAIL,
              "returned True" if result else "returned False")
    else:
        s.add("B", "open()", FAIL, result)

    try:
        is_open = bool(cap.isOpened())
    except Exception as e:
        s.add("B", "isOpened()", FAIL, f"raised: {e}")
        is_open = False
    else:
        s.add("B", "isOpened()", PASS if is_open else FAIL,
              "stream ready" if is_open else "device exists but stream cannot open")
    if not is_open:
        skip_camera_rest(s, "camera failed to open")
        return
    s.camera_ok = True
    s.metrics["observed_stream"] = {
        "width": cap.get(cv2.CAP_PROP_FRAME_WIDTH),
        "height": cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "fourcc": fourcc_to_str(cap.get(cv2.CAP_PROP_FOURCC)),
    }


def test_capture_extras(s):
    cap = s.cap
    try:
        name = cap.getBackendName()
        s.add("B", "getBackendName()", PASS, name)
        s.metrics["active_backend"] = name
    except Exception as e:
        s.add("B", "getBackendName()", FAIL, f"raised: {e}")

    api = "getExceptionMode()/setExceptionMode()"
    try:
        old = bool(cap.getExceptionMode())
        cap.setExceptionMode(not old)
        now = bool(cap.getExceptionMode())
        cap.setExceptionMode(old)
        restored = bool(cap.getExceptionMode()) == old
        s.add("B", api, PASS if (now == (not old) and restored) else WARN,
              f"{old} -> {now} -> restored={restored}")
    except Exception as e:
        s.add("B", api, SKIP, f"unavailable: {e}")

    waitany = getattr(cv2.VideoCapture, "waitAny", None)
    if waitany is None:
        s.add("B", "waitAny()", SKIP, "not available in this cv2")
        return
    st, res = call_with_timeout(
        lambda: waitany([cap], 1_500_000_000), 5)  # timeout in ns
    if st != "ok":
        s.add("B", "waitAny()", SKIP, str(res))
        return
    ok_flag = bool(res[0]) if isinstance(res, (tuple, list)) else bool(res)
    s.add("B", "waitAny()", PASS if ok_flag else WARN, f"returned {res!r}")


def property_cases(args):
    width = args.width or 640
    height = args.height or 480
    fps = float(args.fps or 30)
    return [
        ("CAP_PROP_FRAME_WIDTH", cv2.CAP_PROP_FRAME_WIDTH, width, "exact", 0),
        ("CAP_PROP_FRAME_HEIGHT", cv2.CAP_PROP_FRAME_HEIGHT, height, "exact", 0),
        ("CAP_PROP_FPS", cv2.CAP_PROP_FPS, fps, "approx", 1.0),
        ("CAP_PROP_FOURCC", cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"), "fourcc", 0),
        ("CAP_PROP_BUFFERSIZE", cv2.CAP_PROP_BUFFERSIZE, 1, "exact", 0),
        ("CAP_PROP_AUTO_EXPOSURE", cv2.CAP_PROP_AUTO_EXPOSURE, None, "roundtrip", 0),
        ("CAP_PROP_EXPOSURE", cv2.CAP_PROP_EXPOSURE, -6.0, "approx", 0.75),
        ("CAP_PROP_GAIN", cv2.CAP_PROP_GAIN, None, "roundtrip", 0),
        ("CAP_PROP_FORMAT", cv2.CAP_PROP_FORMAT, None, "roundtrip", 0),
        ("CAP_PROP_MODE", cv2.CAP_PROP_MODE, None, "roundtrip", 0),
        ("CAP_PROP_CONVERT_RGB", cv2.CAP_PROP_CONVERT_RGB, 1, "bool", 0),
    ]


def compare_value(mode, expected, actual, tol):
    try:
        if mode == "exact":
            return int(actual) == int(expected), f"expected {expected}, got {actual}"
        if mode == "approx":
            return abs(float(actual) - float(expected)) <= tol, \
                f"expected ~{expected} (+/-{tol}), got {actual}"
        if mode == "bool":
            return bool(actual) == bool(expected), \
                f"expected {bool(expected)}, got {bool(actual)}"
        if mode == "fourcc":
            return fourcc_to_str(actual) == fourcc_to_str(expected), \
                f"expected {fourcc_to_str(expected)!r}, got {fourcc_to_str(actual)!r}"
        if mode == "roundtrip":
            return abs(float(actual) - float(expected)) < 1e-6, \
                f"roundtrip changed value: {expected} -> {actual}"
    except (TypeError, ValueError) as e:
        return False, f"comparison error: {e}"
    return False, "unknown compare mode"


def fmt_val(value, mode):
    return fourcc_to_str(value) if mode == "fourcc" else str(value)


def test_properties(s):
    print(s.color.bold("\n== [C] Properties (set -> get) =="))
    for name, pid, value, mode, tol in property_cases(s.args):
        api = f"{name} get/set"
        original = safe_get(s.cap, pid)
        target = original if mode == "roundtrip" else value
        if target is None:
            s.add("C", api, SKIP, "get() returned nothing; cannot determine value")
            continue
        status, result = call_with_timeout(lambda: s.cap.set(pid, target), OPEN_TIMEOUT_SEC)
        if status == "timeout":
            s.add("C", api, SKIP, result)
            continue
        if status == "error":
            s.add("C", api, SKIP, f"set() raised: {result}")
            continue
        if not result:
            s.add("C", api, SKIP, "set() returned False (unsupported or read-only)")
            continue
        got = safe_get(s.cap, pid)
        if got is None:
            s.add("C", api, WARN, "set() accepted but get() failed")
            continue
        ok, detail = compare_value(mode, target, got, tol)
        shown = fmt_val(target, mode)
        got_shown = fmt_val(got, mode)
        if ok:
            s.add("C", api, PASS, f"set({shown}) -> get({got_shown})")
        else:
            s.add("C", api, WARN, f"set accepted, readback differs: get={got_shown}", detail)
        if mode != "roundtrip" and original is not None:
            try:
                s.cap.set(pid, original)
            except Exception:
                pass


def apply_requested_settings(s):
    cap = s.cap
    applied = {}
    for label, pid, val in [
        ("width", cv2.CAP_PROP_FRAME_WIDTH, s.args.width),
        ("height", cv2.CAP_PROP_FRAME_HEIGHT, s.args.height),
        ("fps", cv2.CAP_PROP_FPS, s.args.fps),
    ]:
        if val:
            cap.set(pid, val)
            applied[label] = {"requested": val, "actual": cap.get(pid)}
    if applied:
        s.metrics["applied_settings"] = applied


def test_lifecycle_reads(s):
    apply_requested_settings(s)
    cap = s.cap

    grabs = min(5, max(1, s.args.frames))
    ok_grab, grab_err = 0, ""
    for _ in range(grabs):
        try:
            ok_grab += 1 if cap.grab() else 0
        except Exception as e:
            grab_err = str(e)
            break
    rate = ok_grab / grabs
    s.add("B", "grab()", PASS if rate >= 0.8 else (WARN if rate > 0 else FAIL),
          f"{ok_grab}/{grabs} successful" + (f"; last error: {grab_err}" if grab_err else ""))

    frame, retrieve_ok, retrieve_err = None, False, ""
    _stream = s.metrics.get("observed_stream", {})
    _w = int(float(_stream.get("width", 0) or 0))
    _h = int(float(_stream.get("height", 0) or 0))
    try:
        if cap.grab():
            out_buf = (np.empty((_h, _w, 3), dtype=np.uint8)
                       if _w > 0 and _h > 0 else None)
            # OpenCV 5.x binding: without an explicit out-buffer, retrieve()
            # may return (True, None); passing one delivers the frame.
            if out_buf is not None:
                retrieve_ok, frame = cap.retrieve(out_buf)
            else:
                retrieve_ok, frame = cap.retrieve()
            if frame is None and out_buf is not None and out_buf.size:
                frame = out_buf
    except Exception as e:
        retrieve_err = str(e)
    if not retrieve_ok:
        try:                       # one retry after heavy property churn
            if cap.grab():
                retrieve_ok, frame = cap.retrieve()
                retrieve_err += " (recovered on retry)"
        except Exception as e:
            retrieve_err = str(e)
    if retrieve_ok and frame is not None:
        s.add("B", "retrieve()", PASS, f"frame shape={frame.shape}")
    else:
        s.add("B", "retrieve()", FAIL, retrieve_err or "retrieve() returned no frame")

    total = max(1, s.args.frames)
    for _ in range(3):
        try:
            cap.read()
        except Exception:
            break
    frames, ok_read, read_err = [], 0, ""
    t0 = time.perf_counter()
    for _ in range(total):
        try:
            ok, img = cap.read()
        except Exception as e:
            read_err = str(e)
            break
        if ok and img is not None:
            ok_read += 1
            frames.append(img)
    elapsed = time.perf_counter() - t0
    fps_measured = ok_read / elapsed if elapsed > 0 else 0.0
    rate = ok_read / total
    s.add("B", "read() loop", PASS if rate == 1.0 else (WARN if rate >= 0.8 else FAIL),
          f"{ok_read}/{total} frames, {fps_measured:.1f} FPS measured"
          + (f"; error: {read_err}" if read_err else ""))
    s.metrics["read_loop"] = {
        "requested_frames": total, "successful_frames": ok_read,
        "success_rate": round(rate, 4), "elapsed_sec": round(elapsed, 3),
        "measured_fps": round(fps_measured, 2),
    }
    s.frames = frames


def test_quality(s):
    print(s.color.bold("\n== [D] Frame quality =="))
    frames = s.frames
    if not frames:
        s.add("D", "frame not None", FAIL, "no frames captured")
        for api in ("frame dimensions", "pixel variance", "freeze detection"):
            s.add("D", api, SKIP, "no frames to inspect")
        return
    s.add("D", "frame not None", PASS, f"{len(frames)} frames captured")

    h, w = frames[0].shape[:2]
    if s.args.width and s.args.height:
        match = all(f.shape[0] == s.args.height and f.shape[1] == s.args.width for f in frames)
        s.add("D", "frame dimensions", PASS if match else FAIL,
              f"observed {w}x{h}, requested {s.args.width}x{s.args.height}")
    else:
        s.add("D", "frame dimensions", PASS, f"observed {w}x{h} (no explicit request)")

    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    n, total_sum, total_sq = 0, 0.0, 0.0
    for g in grays:
        gf = g.astype(np.float32)
        total_sum += float(gf.sum())
        total_sq += float((gf * gf).sum())
        n += gf.size
    mean = total_sum / n
    std = math.sqrt(max(0.0, total_sq / n - mean * mean))
    if std < UNIFORM_STD_THRESH:
        kind = "all black" if mean < 10 else ("all white" if mean > 245 else "uniform")
        s.add("D", "pixel variance", FAIL, f"std={std:.2f} mean={mean:.1f} ({kind} frames?)")
    else:
        s.add("D", "pixel variance", PASS, f"std={std:.2f} mean={mean:.1f}")

    diffs = [float(np.abs(grays[i].astype(np.int16) - grays[i - 1].astype(np.int16)).mean())
             for i in range(1, len(grays))]
    frozen = sum(1 for d in diffs if d < FREEZE_DIFF_THRESH)
    s.metrics["quality"] = {
        "std": round(std, 3), "mean": round(mean, 2),
        "min_pairwise_diff": round(min(diffs), 3) if diffs else None,
        "frozen_pairs": frozen, "pairs": len(diffs),
    }
    if diffs and frozen == len(diffs):
        s.add("D", "freeze detection", WARN,
              f"all {len(diffs)} consecutive pairs nearly identical (frozen stream?)")
    elif diffs:
        s.add("D", "freeze detection", PASS,
              f"{len(diffs) - frozen}/{len(diffs)} pairs show motion "
              f"(min diff {min(diffs):.2f})")
    else:
        s.add("D", "freeze detection", SKIP, "single frame only")


WRITER_CANDIDATES = [("MJPG", "avi"), ("X264", "mp4"), ("MP4V", "mp4")]

WRITER_PROPS = [
    ("VIDEOWRITER_PROP_QUALITY", getattr(cv2, "CAP_PROP_QUALITY", 1) if CV2_OK else 1),
    ("VIDEOWRITER_PROP_FRAMEBYTES", getattr(cv2, "CAP_PROP_FRAMEBYTES", 2) if CV2_OK else 2),
]


def synthetic_frames(count=15):
    xs = np.linspace(0, 255, 320, dtype=np.uint8)
    base = np.tile(xs, (240, 1))
    return [cv2.cvtColor(np.roll(base, i * 5, axis=1), cv2.COLOR_GRAY2BGR)
            for i in range(count)]


def test_writer(s):
    print(s.color.bold("\n== [E] VideoWriter =="))
    outdir = s.args.outdir
    os.makedirs(outdir, exist_ok=True)
    sample = s.frames[: min(len(s.frames), 30)] if s.frames else synthetic_frames()
    h, w = sample[0].shape[:2]
    fps = float(s.args.fps or 30)

    try:
        fval = cv2.VideoWriter.fourcc(*"MJPG")
        s.add("E", "VideoWriter.fourcc()", PASS, f"MJPG={fval}")
    except Exception as e:
        s.add("E", "VideoWriter.fourcc()", FAIL, f"raised: {e}")

    writer, path, used_fcc, last_error = None, None, None, ""
    for fcc, ext in WRITER_CANDIDATES:
        candidate_path = os.path.join(outdir, f"writer_test.{ext}")
        try:
            cand = cv2.VideoWriter(candidate_path,
                                   cv2.VideoWriter_fourcc(*fcc), fps, (w, h))
        except Exception as e:
            last_error = f"{fcc}: raised {e}"
            continue
        if not cand.isOpened():
            last_error = f"{fcc}: writer.isOpened()=False"
            continue
        writer, path, used_fcc = cand, candidate_path, fcc
        break

    if writer is None:
        for api in E_WRITER_APIS[1:]:
            s.add("E", api, SKIP,
                  f"no usable encoder among MJPG/X264/MP4V ({last_error})")
        return

    s.add("E", "VideoWriter(path, fourcc, fps, size)", PASS,
          f"fourcc={used_fcc}, file={path}")
    s.add("E", "writer.isOpened()", PASS if writer.isOpened() else FAIL,
          "writer ready")

    try:
        bn = writer.getBackendName()
        s.add("E", "writer.getBackendName()", PASS, str(bn))
    except Exception as e:
        s.add("E", "writer.getBackendName()", SKIP, f"unavailable: {e}")

    quality_pid = dict(WRITER_PROPS)["VIDEOWRITER_PROP_QUALITY"]
    framebytes_pid = dict(WRITER_PROPS)["VIDEOWRITER_PROP_FRAMEBYTES"]
    get_results = {}
    for label, pid in WRITER_PROPS:
        try:
            val = writer.get(pid)
            get_results[label] = val
            if val is not None and float(val) == -1.0:
                s.add("E", "writer.get(VIDEOWRITER_PROP_*)", SKIP,
                      f"{label}=-1 (not-supported sentinel)")
            else:
                ok = val is not None and float(val) >= 0
                s.add("E", "writer.get(VIDEOWRITER_PROP_*)",
                      PASS if ok else WARN, f"{label}={val}")
        except Exception as e:
            get_results[label] = None
            s.add("E", "writer.get(VIDEOWRITER_PROP_*)", SKIP,
                  f"{label} raised: {e}")

    inv_rows = []
    for nm in sorted(n for n in dir(cv2) if n.startswith("VIDEOWRITER_PROP_")):
        pid = getattr(cv2, nm)
        try:
            val = writer.get(pid)
        except Exception as e:
            s.add("E", f"writer.get({nm})", SKIP, f"raised: {e}")
            continue
        if val is not None and float(val) == -1.0:
            s.add("E", f"writer.get({nm})", SKIP,
                  "unsupported (get()=-1 sentinel)")
        else:
            s.add("E", f"writer.get({nm})", PASS, f"{nm}={val}")
        inv_rows.append(f"{nm}={val}")
    if inv_rows:
        s.add("E", "VIDEOWRITER_PROP_* inventory", PASS,
              f"{len(inv_rows)} constants probed: " + ", ".join(inv_rows))

    st, res = call_with_timeout(lambda: writer.set(quality_pid, 90), 5)
    if st == "ok" and res:
        got_q = safe_get(writer, quality_pid)
        s.add("E", "writer.set(VIDEOWRITER_PROP_*)", PASS,
              f"QUALITY set 90 -> get {got_q}")
    else:
        s.add("E", "writer.set(VIDEOWRITER_PROP_*)", SKIP,
              f"set rejected/unsupported ({res})")

    written = 0
    for img in sample:
        if img.shape[:2] != (h, w):
            img = cv2.resize(img, (w, h))
        try:
            writer.write(img)
            written += 1
        except Exception as e:
            s.add("E", "writer.write()", FAIL, f"raised after {written}: {e}")
            writer.release()
            return
    fb = safe_get(writer, framebytes_pid)
    evidence = f"{written} frames written" + (f", FRAMEBYTES={fb}" if fb else "")
    s.add("E", "writer.write()", PASS if written == len(sample) else FAIL, evidence)

    writer.release()
    closed = not writer.isOpened()
    s.add("E", "writer.release()", PASS if closed else WARN,
          "stream closed" if closed else "isOpened() still True")

    size = os.path.getsize(path) if os.path.exists(path) else 0
    reader = cv2.VideoCapture(path)
    ok, back = reader.read()
    reader.release()
    if ok and back is not None:
        s.add("E", "VideoWriter readback", PASS,
              f"file={path} ({size} bytes), decoded shape={back.shape}")
        s.metrics["writer"] = {"fourcc": used_fcc, "file": path, "bytes": size}
    else:
        s.add("E", "VideoWriter readback", FAIL,
              f"wrote {size} bytes but decode failed")


def test_release(s):
    try:
        s.cap.release()
        released = not s.cap.isOpened()
    except Exception as e:
        s.add("B", "release()", FAIL, f"raised: {e}")
        return
    s.add("B", "release()", PASS if released else WARN,
          "stream closed" if released else "isOpened() still True after release()")


_v4l2_ctrl_cache = {}

CAP_PROP_TO_V4L2 = {
    "BRIGHTNESS": "brightness",
    "CONTRAST": "contrast",
    "SATURATION": "saturation",
    "HUE": "hue",
    "GAIN": "gain",
    "EXPOSURE": "exposure_absolute",
    "AUTO_EXPOSURE": "exposure_auto",
    "SHARPNESS": "sharpness",
    "GAMMA": "gamma",
    "BACKLIGHT": "backlight_compensation",
    "POWERLINE_FREQUENCY": "power_line_frequency",
    "WHITE_BALANCE_TEMPERATURE": "white_balance_temperature",
    "WHITE_BALANCE_BLUE_U": "white_balance_blue_channel",
    "WHITE_BALANCE_RED_V": "white_balance_red_channel",
    "FOCUS": "focus_absolute",
    "AUTOFOCUS": "focus_auto",
    "ZOOM": "zoom_absolute",
    "PAN": "pan_absolute",
    "TILT": "tilt_absolute",
    "ROLL": "roll_absolute",
    "IRIS": "iris_absolute",
    "TEMPERATURE": "white_balance_temperature",
}


def get_v4l2_controls(dev_path):
    """Parse `v4l2-ctl --list-ctrls` into {name: {type,min,max,default,...}}.

    Returns {} when the tool runs but reports nothing, None when unavailable.
    """
    if dev_path in _v4l2_ctrl_cache:
        return _v4l2_ctrl_cache[dev_path]
    if not shutil.which("v4l2-ctl"):
        _v4l2_ctrl_cache[dev_path] = None
        return None
    try:
        proc = subprocess.run(["v4l2-ctl", "-d", dev_path, "--list-ctrls"],
                              capture_output=True, text=True, timeout=8)
        ctrls = {}
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                m = re.match(
                    r"\s*([a-zA-Z0-9_]+)\s+0x[0-9a-fA-F]+\s+\((\w+)\)\s*:(.*)",
                    line)
                if not m:
                    continue
                info = {"type": m.group(2)}
                rest = m.group(3)
                for k in ("min", "max", "step", "default", "value"):
                    mm = re.search(rf"\b{k}=(-?\d+)", rest)
                    if mm:
                        info[k] = int(mm.group(1))
                info["inactive"] = "flags=inactive" in rest
                ctrls[m.group(1).lower()] = info
        _v4l2_ctrl_cache[dev_path] = ctrls
        return ctrls
    except Exception:
        _v4l2_ctrl_cache[dev_path] = None
        return None


def get_v4l2_control_names(dev_path):
    """Return set of v4l2 control names (lowercase), or None if unavailable."""
    ctrls = get_v4l2_controls(dev_path)
    return None if ctrls is None else set(ctrls)


def test_full_sweep(s):
    print(s.color.bold("\n== [F] CAP_PROP full sweep =="))
    if s.cap is None or not s.cap.isOpened():
        s.add("F", "CAP_PROP_* full sweep", SKIP,
              "capture already closed before sweep (ordering bug)")
        return
    props = enumerate_cap_props()
    fam_counts = {}
    for p in props:
        _, label = prop_family(p["name"])
        p["family"] = label
        fam_counts[label] = fam_counts.get(label, 0) + 1
    s.metrics["cap_prop_families"] = fam_counts
    s.metrics["cap_props_enumerated"] = len(props)

    dev_raw = resolve_device(s.args.device)
    dev_path = dev_raw if isinstance(dev_raw, str) else f"/dev/video{dev_raw}"
    v4l2_ctrls = get_v4l2_controls(dev_path)
    v4l2_names = None if v4l2_ctrls is None else set(v4l2_ctrls)

    for p in props:
        api = f"CAP_PROP_{p['name']}"
        token, label = prop_family(p["name"])
        if token and not family_applicable(token, s.args.backend):
            s.add("F", api, SKIP,
                  f"by-design: {label}-only property, backend={s.args.backend}")
            continue
        val = safe_get(s.cap, p["pid"])
        if val is None:
            s.add("F", api, SKIP, "get() raised or NaN")
            continue
        try:
            vnum = float(val)
        except (TypeError, ValueError):
            vnum = None
        if vnum is not None and vnum == -1.0:
            # Distinguish unsupported vs driver bug via v4l2-ctl declaration
            v4l2_key = CAP_PROP_TO_V4L2.get(p["name"])
            names = v4l2_names if not p["name"].startswith(
                ("AUDIO", "ANDROID", "IOS_DEVICE")) else None
            if names is not None and v4l2_key:
                if v4l2_key.lower() in v4l2_names:
                    if not s.cap.isOpened():
                        s.add("F", api, SKIP,
                              "get()=-1 (capture closed mid-sweep)")
                    else:
                        # Driver declares control but get() returns sentinel
                        s.add("F", api, WARN,
                              f"driver declared '{v4l2_key}' but get()=-1 "
                              "(possible driver bug, check dmesg/v4l2-ctl --list-ctrls)")
                    continue
                else:
                    # Not declared -> truly unsupported
                    s.add("F", api, SKIP,
                          f"unsupported (get()=-1, not declared by driver '{v4l2_key}')")
                    continue
            s.add("F", api, SKIP,
                  "unsupported (get()=-1, OpenCV not-supported sentinel)")
            continue
        if p["name"] in NO_SET_BLACKLIST:
            s.add("F", api, PASS, f"get()={val}")
            continue
        st, res = call_with_timeout(lambda pid=p["pid"], v=val: s.cap.set(pid, v),
                                    OPEN_TIMEOUT_SEC)
        if st != "ok" or not res:
            if vnum is not None and abs(vnum) > 1e-9:
                s.add("F", api, PASS, f"get()={val}; set rejected (read-only)")
            else:
                s.add("F", api, SKIP, "unsupported (get=0, set rejected)")
            continue
        got = safe_get(s.cap, p["pid"])
        if got is None:
            s.add("F", api, WARN, "set accepted but get() failed")
            continue
        try:
            drift = abs(float(got) - float(val))
            tol = max(1e-6, abs(float(val)) * 1e-6)
        except (TypeError, ValueError):
            s.add("F", api, WARN, f"non-numeric readback: {got!r}")
            continue
        if drift > tol:
            s.add("F", api, WARN, f"roundtrip drift: {val} -> {got}")
        elif vnum is not None and abs(vnum) <= 1e-9:
            handled = False
            v4l2_key = CAP_PROP_TO_V4L2.get(p["name"])
            info = v4l2_ctrls.get(v4l2_key) if (v4l2_ctrls and v4l2_key) else None
            if info is not None:
                # Control exists but its current/default value is 0: writing
                # 0 back proves nothing.  Probe with a non-zero in-range
                # value, verify readback, then restore.
                lo = info.get("min", 0)
                hi = info.get("max", 0)
                df = info.get("default", 0)
                probe = float(df) if df else float(hi if hi > 0 else lo)
                if probe:
                    stp, _ = call_with_timeout(
                        lambda pid=p["pid"], v=probe: s.cap.set(pid, v),
                        OPEN_TIMEOUT_SEC)
                    got2 = safe_get(s.cap, p["pid"]) if stp == "ok" else None
                    changed = False
                    if got2 is not None:
                        try:
                            ptol = max(1e-6, abs(probe) * 1e-6)
                            changed = abs(float(got2) - probe) <= ptol
                        except (TypeError, ValueError):
                            changed = False
                    call_with_timeout(
                        lambda pid=p["pid"], v=val: s.cap.set(pid, val),
                        OPEN_TIMEOUT_SEC)
                    if changed:
                        s.add("F", api, PASS,
                              f"probe roundtrip 0 -> {probe} (restored)")
                        handled = True
                    else:
                        s.add("F", api, WARN,
                              f"no-op roundtrip (0 -> 0); driver declares "
                              f"'{v4l2_key}' but write has no effect")
                else:
                    s.add("F", api, WARN,
                          f"no-op roundtrip (0 -> 0); '{v4l2_key}' range "
                          "is all-zero")
                handled = True
            elif v4l2_ctrls is not None and v4l2_key:
                s.add("F", api, SKIP,
                      f"unsupported (get=0 set noop, not declared by "
                      f"driver '{v4l2_key}')")
                handled = True
            if not handled:
                s.add("F", api, WARN,
                      "no-op roundtrip (0 -> 0); support unproven")
        else:
            s.add("F", api, PASS, f"roundtrip {val}")

    absent = [n for n in EXTRA_KNOWN_PROPS
              if getattr(cv2, n, None) is None]
    for n in absent:
        s.add("F", n, SKIP,
              "constant absent in this cv2 build (added in newer upstream)")
    s.metrics["known_props_absent"] = len(absent)


def test_negative_open(s):
    api = "isOpened() negative case"
    st, payload = call_with_timeout(
        lambda: cv2.VideoCapture(NEGATIVE_DEVICE, cv2.CAP_V4L2),
        OPEN_TIMEOUT_SEC)
    if st != "ok":
        s.add("B", api, WARN, f"cv2 raised instead of returning closed cap ({payload})")
        return
    cap = payload
    try:
        opened = bool(cap.isOpened())
    except Exception as e:
        s.add("B", api, FAIL, f"isOpened() raised: {e}")
        cap.release()
        return
    cap.release()
    if opened:
        s.add("B", api, FAIL, f"{NEGATIVE_DEVICE} unexpectedly opened")
    else:
        s.add("B", api, PASS, f"{NEGATIVE_DEVICE} correctly refused (isOpened=False)")


def test_open_only_precheck(s):
    api = "open_only_props_precheck"
    dev = resolve_device(s.args.device)
    bid = backend_id(s.args.backend)
    cands, missing = [], []
    for name, value in OPEN_ONLY_PROPS:
        pid = getattr(cv2, name, None)
        if pid is None:
            missing.append(name)
        else:
            cands.append((name, int(pid), value))

    def _try(flat_params):
        """Return 'ok' | 'closed' | ('exc', message)."""
        try:
            cap = cv2.VideoCapture(dev, bid, flat_params)
        except Exception as e:
            return ("exc", str(e))
        try:
            return "ok" if cap.isOpened() else "closed"
        finally:
            cap.release()

    extra = f"; missing constants: {missing}" if missing else ""
    if _try([]) != "ok":
        s.add("B", api, SKIP,
              "baseline open() without params failed; "
              "cannot evaluate open-time params")
        return
    ok_names, bad_names, first_exc = [], [], ""
    for name, pid, value in cands:
        res = _try([pid, value])
        if res == "ok":
            ok_names.append(name)
        else:
            bad_names.append(name)
            if isinstance(res, tuple) and not first_exc:
                first_exc = res[1]
    detail_bits = []
    if bad_names:
        detail_bits.append("breaks open: " + ", ".join(
            f"{n}({getattr(cv2, n)})" for n in bad_names))
    if ok_names:
        detail_bits.append("accepted: " + ", ".join(ok_names))
    if first_exc:
        detail_bits.append(first_exc.splitlines()[0][:100])
    detail = "; ".join(detail_bits)
    if not cands:
        s.add("B", api, SKIP, f"no open-time param constants here{extra}")
    elif ok_names:
        # Verdict follows the API capability: if ANY parameter opens the
        # capture, open-time params are usable -> PASS.  Rejected params
        # stay informational (per-backend capability scope).
        flat = [v for name, pid, value in cands if name in ok_names
                for v in (pid, value)]
        res = _try(flat)
        rej = f"; rejected: {', '.join(bad_names)}" if bad_names else ""
        if res == "ok":
            s.add("B", api, PASS,
                  f"open-time params usable ({len(ok_names)}/{len(cands)}): "
                  f"{', '.join(ok_names)}{rej}{extra}", detail)
        else:
            s.add("B", api, WARN,
                  f"{len(ok_names)} params OK individually but "
                  f"supported-combo rejected{extra}", detail)
    else:
        s.add("B", api, WARN,
              f"backend rejects every open-time param ({len(cands)}){extra}",
              detail)


def test_any_vs_v4l2(s):
    """Compare CAP_ANY resolution against the selected backend.

    Severity follows relevance: under an explicitly requested backend a
    divergence cannot affect this run, so it stays informational (PASS
    with a note); with backend=ANY the ambiguity IS this run's behavior
    and stays a WARN.
    """
    want = s.args.backend
    bid = cv2.CAP_V4L2 if want == "ANY" else backend_id(want)
    other = "V4L2" if want == "ANY" else want
    api = "backend_any_vs_v4l2"
    dev = resolve_device(s.args.device)

    def probe(backend):
        st, payload = call_with_timeout(lambda: cv2.VideoCapture(dev, backend),
                                        OPEN_TIMEOUT_SEC)
        if st != "ok":
            return False, None
        cap = payload
        ok = bool(cap.isOpened())
        name = cap.getBackendName() if ok else None
        cap.release()
        return ok, name

    ok_any, name_any = probe(cv2.CAP_ANY)
    ok_sel, name_sel = probe(bid)
    if not (ok_any and ok_sel):
        s.add("B", api, SKIP,
              f"device must open under both backends "
              f"(ANY={ok_any}, {other}={ok_sel})")
        return
    if name_any == name_sel:
        s.add("B", api, PASS,
              f"consistent backend via ANY and {other}: {name_any}")
    elif want == "ANY":
        s.add("B", api, WARN,
              f"divergence: CAP_ANY resolves to {name_any}, "
              f"CAP_{other} to {name_sel}")
    else:
        s.add("B", api, PASS,
              f"note: CAP_ANY resolves to {name_any}, explicit {other} "
              f"to {name_sel} (run unaffected: explicit backend)")


def test_backend_matrix(s):
    test_negative_open(s)
    test_open_only_precheck(s)
    test_any_vs_v4l2(s)


def parse_v4l2_formats(text):
    formats, cur = {}, None
    for line in text.splitlines():
        m = re.search(r"\[\d+\]:\s*'([A-Za-z0-9]{4})'", line)
        if m:
            cur = m.group(1).upper()
            formats.setdefault(cur, set())
            continue
        m = re.search(r"Size:\s*Discrete\s+(\d+)x(\d+)", line)
        if m and cur is not None:
            formats[cur].add((int(m.group(1)), int(m.group(2))))
    return formats


def parse_v4l2_current_format(text):
    m = re.search(r"Pixel Format\s*:\s*'([A-Za-z0-9]{4})'", text)
    if m:
        return m.group(1).upper()
    return ""


def test_v4l2_crosschk(s):
    api = "negotiated fmt within v4l2-ctl advertised list"
    if not shutil.which("v4l2-ctl"):
        s.add("G", api, SKIP,
              "v4l2-ctl not installed (sudo apt install v4l-utils; check auto-enables)")
        return
    obs = s.metrics.get("observed_stream")
    if not obs or not obs.get("width"):
        s.add("G", api, SKIP, "no negotiated stream info")
        return
    dev = resolve_device(s.args.device)
    dev_path = dev if isinstance(dev, str) else f"/dev/video{dev}"
    try:
        proc = subprocess.run(["v4l2-ctl", "-d", dev_path, "--list-formats-ext"],
                              capture_output=True, text=True, timeout=15)
    except Exception as e:
        s.add("G", api, WARN, f"v4l2-ctl execution failed: {e}")
        return
    formats = parse_v4l2_formats(proc.stdout)
    if not formats:
        s.add("G", api, SKIP, "could not parse v4l2-ctl output")
        return
    s.metrics["v4l2_advertised"] = {
        k: sorted(f"{w}x{h}" for w, h in v) for k, v in formats.items()}
    fcc = (obs.get("fourcc") or "????").rstrip("?").upper()
    # Fallback: cap.get(CAP_PROP_FOURCC) often returns "????" (-1) on V4L2; query driver directly
    if not fcc:
        try:
            proc2 = subprocess.run(["v4l2-ctl", "-d", dev_path, "--get-fmt-video"],
                                   capture_output=True, text=True, timeout=8)
            fb = parse_v4l2_current_format(proc2.stdout)
            if fb:
                fcc = fb
                s.metrics["observed_stream"]["fourcc_fallback"] = fb
                s.metrics["observed_stream"]["fourcc_source"] = "v4l2-ctl --get-fmt-video"
        except Exception:
            pass
    if not fcc:
        s.add("G", api, SKIP,
              "could not read negotiated FOURCC (cap.get()=-1 and v4l2-ctl fallback empty), skip cross-check")
        return
    sizes = formats.get(fcc, set())
    w, h = int(obs.get("width")), int(obs.get("height"))
    if not sizes:
        s.add("G", api, FAIL,
              f"negotiated fourcc {fcc!r} is NOT advertised by the driver")
    elif (w, h) in sizes:
        s.add("G", api, PASS,
              f"{w}x{h}@{fcc} within driver-advertised modes ({len(sizes)} modes)")
    else:
        s.add("G", api, WARN,
              f"{w}x{h}@{fcc} negotiated but missing from advertised list")


def run_suite(s):
    print(s.color.bold("\n== [A] Environment =="))
    check_environment(s)
    open_camera(s)
    if s.camera_ok:
        test_capture_extras(s)
        test_properties(s)
        test_lifecycle_reads(s)
        test_quality(s)
        test_v4l2_crosschk(s)
        test_writer(s)
        if s.args.no_full_sweep:
            s.add("F", "CAP_PROP_* full sweep", SKIP, "--no-full-sweep given")
        else:
            # [F] must run while the capture is still open: every get()/set()
            # on a released cap returns -1 and poisons the whole sweep.
            test_full_sweep(s)
        test_release(s)
        # backend matrix probes need the device free, hence after release()
        test_backend_matrix(s)


def count_statuses(results):
    counts = {PASS: 0, FAIL: 0, WARN: 0, SKIP: 0}
    for r in results:
        counts[r.status] += 1
    return counts


def collect_skip_reasons(results):
    reasons = {}
    for r in results:
        if r.status == SKIP:
            reasons.setdefault(r.message or "(no reason given)", []).append(r.api)
    return reasons


def word_match(api_text, method):
    return re.search(rf"\b{re.escape(method)}\b", api_text) is not None


def build_coverage(results):
    """Pass-rate model (replaces the old fixed-list coverage).

    - planned (core) stays dynamic: distinct (group, api) checks outside
      group [F]; executed = those with at least one PASS or FAIL row.
    - Pass rates are computed on raw rows per scope:
        * pass_rate_all         = PASS / every recorded check
        * pass_rate_excl_skip   = PASS / (checks - SKIP)
      Scopes: overall (all rows), core (excl. [F]), sweep [F].
    """
    counts = count_statuses(results)

    def rate_block(rows):
        c = count_statuses(rows)
        total = len(rows)
        denom = total - c[SKIP]
        return {
            "total": total,
            "PASS": c[PASS], "FAIL": c[FAIL],
            "WARN": c[WARN], "SKIP": c[SKIP],
            "executed": c[PASS] + c[FAIL],
            "pass_rate_all": round(c[PASS] / total, 4) if total else 0.0,
            "pass_rate_excl_skip": round(c[PASS] / denom, 4) if denom else 0.0,
        }

    core_rows = [r for r in results if r.group != "F"]
    f_rows = [r for r in results if r.group == "F"]

    core_keys = {(r.group, r.api) for r in core_rows}
    executed_keys = {(r.group, r.api) for r in core_rows
                     if r.status in (PASS, FAIL)}
    core_total = len(core_keys)
    core_executed = len(executed_keys)

    def method_report(methods):
        covered, uncovered = [], []
        for m in methods:
            hit = any(word_match(r.api, m) and r.status in (PASS, FAIL)
                      for r in results)
            (covered if hit else uncovered).append(m)
        return covered, uncovered

    vc_methods = dynamic_api_names()
    vw_methods = writer_api_names()
    rg_funcs = registry_func_names()

    props = enumerate_cap_props()
    prop_names = [f"CAP_PROP_{p['name']}" for p in props]
    by_design = sum(1 for r in results
                    if r.status == SKIP and r.message.startswith("by-design"))

    methods_all = set(vc_methods) | set(vw_methods) | set(rg_funcs)
    result_apis = {r.api for r in results}
    core_apis = {api for _, api in core_keys}
    full_total = len(result_apis | core_apis | methods_all | set(prop_names))
    full_executed = counts[PASS] + counts[FAIL]

    return {
        "core_total": core_total,
        "core_executed": core_executed,
        "core_coverage": round(core_executed / core_total, 4) if core_total else 0.0,
        "overall_rates": rate_block(results),
        "core_rates": rate_block(core_rows),
        "sweep_f": rate_block(f_rows),
        "methods": {
            "VideoCapture": {"covered": method_report(vc_methods)[0],
                             "uncovered": method_report(vc_methods)[1]},
            "VideoWriter": {"covered": method_report(vw_methods)[0],
                            "uncovered": method_report(vw_methods)[1]},
            "videoio_registry": {"covered": method_report(rg_funcs)[0],
                                 "uncovered": method_report(rg_funcs)[1]},
        },
        "cap_props_enumerated": len(props),
        "cap_props_executed": counts[PASS] + counts[FAIL]
        - len([r for r in core_rows if r.status in (PASS, FAIL)]),
        "skipped_by_design": by_design,
        "full_surface_total": full_total,
        "full_executed": full_executed,
        "full_coverage": round(full_executed / full_total, 4) if full_total else 0.0,
        "passed_ratio": round(counts[PASS] / full_executed, 4) if full_executed else 0.0,
    }


def decide_exit_code(s):
    counts = count_statuses(s.results)
    if counts[FAIL]:
        return 1
    if not s.camera_ok:
        return 2
    return 0


def build_payload(s, exit_code):
    cov = build_coverage(s.results)
    counts = count_statuses(s.results)
    opencv_src = os.environ.get("REPORT_OPENCV_SOURCE") or os.environ.get("CPP_OPENCV_SOURCE") or "pip"
    # For python, source is pip (or system python-opencv), tag as apt/python for consistency
    env = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "hostname": socket.gethostname(),
        "opencv_version": getattr(cv2, "__version__", "unknown"),
        "opencv_source": opencv_src,
        "video_io_build": s.metrics.get("video_io_build", {}),
        "registered_backends": s.metrics.get("registered_backends", []),
    }
    meta = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "tool": "opencv_camera_api_test.py",
        "device": str(s.args.device),
        "backend": s.args.backend,
        "frames": s.args.frames,
        "requested_size": [s.args.width, s.args.height],
        "requested_fps": s.args.fps,
        "exit_code": exit_code,
        "opencv_version": env["opencv_version"],
        "opencv_source": opencv_src,
    }
    summary = dict(counts)
    summary.update({
        "total_checks": len(s.results),
        "core_total": cov["core_total"],
        "core_executed": cov["core_executed"],
        "pass_rate_percent": round(cov["overall_rates"]["pass_rate_all"] * 100, 1),
        "pass_rate_excl_skip_percent":
            round(cov["overall_rates"]["pass_rate_excl_skip"] * 100, 1),
        "core_pass_rate_percent": round(cov["core_rates"]["pass_rate_all"] * 100, 1),
        "core_pass_rate_excl_skip_percent":
            round(cov["core_rates"]["pass_rate_excl_skip"] * 100, 1),
        "core_coverage_percent": round(cov["core_coverage"] * 100, 1),
        "sweep_f_pass_rate_percent":
            round(cov["sweep_f"]["pass_rate_all"] * 100, 1),
        "sweep_f_pass_rate_excl_skip_percent":
            round(cov["sweep_f"]["pass_rate_excl_skip"] * 100, 1),
        "full_coverage_percent": round(cov["full_coverage"] * 100, 1),
        "full_surface_total": cov["full_surface_total"],
        "skipped_by_design": cov["skipped_by_design"],
        "passed_ratio_percent": round(cov["passed_ratio"] * 100, 1),
        "exit_code": exit_code,
        "exit_meaning": EXIT_MEANINGS[exit_code],
    })
    return {
        "meta": meta,
        "environment": env,
        "summary": summary,
        "metrics": s.metrics,
        "coverage": cov,
        "skip_reasons": collect_skip_reasons(s.results),
        "results": [asdict(r) for r in s.results],
    }


def render_markdown(p):
    meta, env, summ = p["meta"], p["environment"], p["summary"]
    cov, results = p["coverage"], p["results"]
    L = []
    L.append("# OpenCV Camera API Test Report")
    L.append("")
    L.append(f"- Generated: {meta['timestamp']}")
    L.append(f"- Host: `{env['hostname']}` ({env['machine']}, {env['platform']})")
    L.append(f"- Python: {env['python']}, OpenCV: {env['opencv_version']}")
    L.append(f"- Device: `{meta['device']}`, Backend: {meta['backend']}, Frames: {meta['frames']}")
    L.append(f"- Exit code: **{summ['exit_code']}** ({summ['exit_meaning']})")
    L.append("")
    L.append("## Summary")
    L.append("")
    L.append("| Status | Count |")
    L.append("|---|---|")
    for st in (PASS, FAIL, WARN, SKIP):
        L.append(f"| {st} | {summ[st]} |")
    L.append(f"| Total checks | {summ['total_checks']} |")
    L.append("")
    L.append(f"- **Pass rate (all)** = PASS / total = **{summ['pass_rate_percent']}%** "
             f"({cov['overall_rates']['PASS']}/{cov['overall_rates']['total']})")
    L.append(f"- **Pass rate (excl. SKIP)** = PASS / (total - SKIP) = "
             f"**{summ['pass_rate_excl_skip_percent']}%** "
             f"({cov['overall_rates']['PASS']}/{cov['overall_rates']['total'] - cov['overall_rates']['SKIP']})")
    L.append("")
    L.append("## Pass Rate by Scope")
    L.append("")
    L.append("| Scope | PASS | Total | Denominator (excl. SKIP) | Pass rate (all) | Pass rate (excl. SKIP) |")
    L.append("|---|---|---|---|---|---|")
    ov, co, f = cov["overall_rates"], cov["core_rates"], cov["sweep_f"]
    L.append(f"| Overall | {ov['PASS']} | {ov['total']} | {ov['total'] - ov['SKIP']} "
             f"| **{summ['pass_rate_percent']}%** | **{summ['pass_rate_excl_skip_percent']}%** |")
    L.append(f"| Core (excl. [F]) | {co['PASS']} | {co['total']} | {co['total'] - co['SKIP']} "
             f"| **{summ['core_pass_rate_percent']}%** | **{summ['core_pass_rate_excl_skip_percent']}%** |")
    L.append(f"| Full sweep [F] | {f['PASS']} | {f['total']} | {f['total'] - f['SKIP']} "
             f"| **{summ['sweep_f_pass_rate_percent']}%** | **{summ['sweep_f_pass_rate_excl_skip_percent']}%** |")
    L.append("")
    L.append(f"| Full surface (+methods +all CAP_PROP_*) | {cov['full_executed']} "
             f"| {cov['full_surface_total']} | **{summ['full_coverage_percent']}%** |")
    L.append("")
    L.append(f"- CAP_PROP_* constants enumerated: {cov['cap_props_enumerated']} "
             f"(executed {cov['cap_props_executed']}, "
             f"skipped-by-design {cov['skipped_by_design']})")
    for cls, data in cov["methods"].items():
        unc = data["uncovered"]
        L.append(f"- `{cls}` methods covered: {len(data['covered'])}"
                 + (f", uncovered ({len(unc)}): "
                    + ", ".join(f"`{m}`" for m in unc) if unc else ""))
    L.append("")
    L.append("## Results")
    ordered = sorted(results, key=lambda r: r["group"])
    for group, rows in itertools.groupby(ordered, key=lambda r: r["group"]):
        L.append("")
        L.append(f"### [{group}] {GROUP_DESC[group]}")
        L.append("")
        L.append("| API | Status | Message |")
        L.append("|---|---|---|")
        for r in rows:
            msg = r["message"].replace("|", "\\|")
            L.append(f"| `{r['api']}` | {r['status']} | {msg} |")
    L.append("")
    skips = p["skip_reasons"]
    if skips:
        L.append("## Skip reasons")
        L.append("")
        for reason, apis in skips.items():
            L.append(f"- {reason}: {', '.join(f'`{a}`' for a in apis)}")
        L.append("")
    problems = [r for r in results if r["status"] in (FAIL, WARN)]
    if problems:
        L.append("## Failure / warning details")
        L.append("")
        for r in problems:
            text = r["detail"] or r["message"]
            L.append(f"- **[{r['group']}] `{r['api']}` ({r['status']})**: {text}")
        L.append("")
    L.append("## Environment")
    L.append("")
    L.append("- Registered videoio backends: "
             + (", ".join(env["registered_backends"]) or "(none)"))
    vio = env.get("video_io_build") or {}
    if vio:
        L.append("")
        L.append("| Build: Video I/O | Enabled |")
        L.append("|---|---|")
        for k, v in vio.items():
            L.append(f"| {k} | {v} |")
    L.append("")
    L.append("## Coverage detail (legacy union view)")
    L.append("")
    L.append(f"- Planned explicit checks: {cov['core_total']}")
    L.append(f"- CAP_PROP_* constants enumerated: {cov['cap_props_enumerated']}")
    L.append(f"- Full surface total: {cov['full_surface_total']}")
    L.append(f"- Executed (PASS+FAIL): {cov['full_executed']}")
    L.append("")
    metrics = p.get("metrics") or {}
    if metrics:
        L.append("## Metrics")
        L.append("")
        L.append("```json")
        L.append(json.dumps(metrics, indent=2, ensure_ascii=False))
        L.append("```")
        L.append("")
    return "\n".join(L) + "\n"


def render_excel(payload, path):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        return None

    illegal_re = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")

    def safe(v):
        if isinstance(v, str):
            cleaned = illegal_re.sub("?", v)
            return cleaned if cleaned.strip() else "(empty)"
        return v

    meta, env = payload["meta"], payload["environment"]
    summ, cov, metrics = payload["summary"], payload["coverage"], payload.get("metrics") or {}
    results = payload["results"]

    hdr_fill, hdr_font = PatternFill("solid", fgColor="1F4E78"), Font(bold=True, color="FFFFFF")
    fills = {"PASS": PatternFill("solid", fgColor="C6EFCE"),
             "FAIL": PatternFill("solid", fgColor="FFC7CE"),
             "WARN": PatternFill("solid", fgColor="FFEB9C"),
             "SKIP": PatternFill("solid", fgColor="D9D9D9")}
    fonts = {"PASS": Font(color="006100"), "FAIL": Font(color="9C0006", bold=True),
             "WARN": Font(color="9C6500"), "SKIP": Font(color="404040")}
    thin = Border(*[Side(style="thin", color="BFBFBF")] * 4)

    def style_header(ws):
        for c in ws[1]:
            c.fill, c.font = hdr_fill, hdr_font
            c.alignment = Alignment(vertical="center")
            c.border = thin

    def set_widths(ws, widths):
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    wb = Workbook()

    ws = wb.active
    ws.title = "Summary"
    vio = env.get("video_io_build") or {}
    rows = [
        ["OpenCV Camera API Test Report", ""],
        ["", ""],
        ["timestamp", meta["timestamp"]],
        ["device", str(meta["device"])],
        ["backend", meta["backend"]],
        ["frames", meta["frames"]],
        ["host", f"{env['hostname']} ({env['machine']}, {env['platform']})"],
        ["python / opencv", f"{env['python']} / {env['opencv_version']} ({env.get('opencv_source','')})"],
        ["opencv_source", env.get("opencv_source", "")],
        ["registered backends", ", ".join(env.get("registered_backends") or [])],
        ["build: V4L2", vio.get("v4l/v4l2", "-")],
        ["build: GStreamer", vio.get("GStreamer", "-")],
        ["", ""],
        ["== summary ==", ""],
        ["PASS", summ["PASS"]], ["FAIL", summ["FAIL"]],
        ["WARN", summ["WARN"]], ["SKIP", summ["SKIP"]],
        ["total checks", summ["total_checks"]],
        ["", ""],
        ["pass rate (all)", f"{summ['pass_rate_percent']}% "
         f"({cov['overall_rates']['PASS']}/{cov['overall_rates']['total']})"],
        ["pass rate (excl. SKIP)", f"{summ['pass_rate_excl_skip_percent']}% "
         f"({cov['overall_rates']['PASS']}/"
         f"{cov['overall_rates']['total'] - cov['overall_rates']['SKIP']})"],
        ["core pass rate (excl. [F], all / excl SKIP)",
         f"{summ['core_pass_rate_percent']}% / "
         f"{summ['core_pass_rate_excl_skip_percent']}%"],
        ["full sweep [F] pass rate (all / excl SKIP)",
         f"{summ['sweep_f_pass_rate_percent']}% / "
         f"{summ['sweep_f_pass_rate_excl_skip_percent']}% "
         f"(WARN {cov['sweep_f']['WARN']}, SKIP {cov['sweep_f']['SKIP']}, "
         f"total {cov['sweep_f']['total']})"],
        ["skipped-by-design", cov["skipped_by_design"]],
        ["passed ratio", f"{summ['passed_ratio_percent']}%"],
        ["exit code", f"{summ['exit_code']} ({summ['exit_meaning']})"],
    ]
    for r in rows:
        ws.append([safe(x) for x in r])
    ws["A1"].font = Font(bold=True, size=14)
    for i in range(3, len(rows) + 1):
        a = ws.cell(row=i, column=1)
        if a.value and not str(a.value).startswith("=="):
            a.font = Font(bold=True)
            a.border = thin
            ws.cell(row=i, column=2).border = thin
    set_widths(ws, [34, 95])

    ws2 = wb.create_sheet("All Results")
    ws2.append(["Group", "Group name", "Test item / API", "Status",
                "Message (SKIP column = reason)", "Detail"])
    for r in sorted(results, key=lambda x: (x["group"], x["api"])):
        ws2.append([safe(r["group"]), safe(GROUP_DESC.get(r["group"], "")), safe(r["api"]),
                    safe(r["status"]), safe(r["message"]), safe(r["detail"])])
    style_header(ws2)
    for row in ws2.iter_rows(min_row=2, max_col=6):
        st = row[3].value
        if st in fills:
            row[3].fill, row[3].font = fills[st], fonts[st]
        for c in row:
            c.border = thin
            c.alignment = Alignment(vertical="top")
    ws2.freeze_panes = "A2"
    ws2.auto_filter.ref = ws2.dimensions
    set_widths(ws2, [7, 20, 42, 9, 62, 45])

    ws3 = wb.create_sheet("Skip Reasons")
    ws3.append(["Reason", "Count", "Affected test items"])
    reasons = {}
    for r in results:
        if r["status"] == SKIP:
            reasons.setdefault(r["message"] or "(no reason given)",
                               []).append(f"[{r['group']}] {r['api']}")
    for reason in sorted(reasons, key=lambda k: -len(reasons[k])):
        ws3.append([safe(reason), len(reasons[reason]), safe("\n".join(reasons[reason]))])
    style_header(ws3)
    for row in ws3.iter_rows(min_row=2, max_col=3):
        row[0].font = Font(bold=True)
        for c in row:
            c.border = thin
            c.alignment = Alignment(vertical="top",
                                    wrap_text=(c.column == 3))
    set_widths(ws3, [58, 8, 80])

    ws4 = wb.create_sheet("Metrics")
    ws4.append(["Category", "Metric", "Value"])
    obs = metrics.get("observed_stream", {})
    rl = metrics.get("read_loop", {})
    q = metrics.get("quality", {})
    wr = metrics.get("writer", {})
    mrows = [
        ("stream", "negotiated format",
         f"{obs.get('width')}x{obs.get('height')} @ {obs.get('fps')} fps ({obs.get('fourcc')})"),
        ("read loop", "success rate",
         f"{rl.get('successful_frames')}/{rl.get('requested_frames')} = {rl.get('success_rate')}"),
        ("read loop", "measured FPS", rl.get("measured_fps")),
        ("read loop", "elapsed (s)", rl.get("elapsed_sec")),
        ("quality", "gray std / mean", f"{q.get('std')} / {q.get('mean')}"),
        ("quality", "min pairwise diff", q.get("min_pairwise_diff")),
        ("quality", "frozen pairs", f"{q.get('frozen_pairs')}/{q.get('pairs')}"),
        ("VideoWriter", "fourcc / file", f"{wr.get('fourcc')} / {wr.get('file')}"),
        ("VideoWriter", "file size", f"{wr.get('bytes')} bytes"),
        ("CAP_PROP sweep", "unique ids enumerated", cov["cap_props_enumerated"]),
        ("CAP_PROP sweep", "executed (PASS+FAIL)", cov["cap_props_executed"]),
        ("CAP_PROP sweep", "skipped by design", cov["skipped_by_design"]),
    ]
    for cat, k, v in mrows:
        ws4.append([safe(cat), safe(k), safe(v)])
    style_header(ws4)
    for row in ws4.iter_rows(min_row=2, max_col=3):
        row[1].font = Font(bold=True)
        for c in row:
            c.border = thin
    set_widths(ws4, [16, 24, 70])

    wb.save(path)
    return path


def write_reports(args, payload):
    os.makedirs(args.outdir, exist_ok=True)
    md_path = os.path.join(args.outdir, "report_auto.md")
    json_path = os.path.join(args.outdir, "report_auto.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(payload))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    paths = [md_path, json_path]
    if not getattr(args, "no_xlsx", False):
        xlsx_path = os.path.join(args.outdir, "report_auto.xlsx")
        try:
            xlsx_result = render_excel(payload, xlsx_path)
        except Exception as e:
            xlsx_result = None
            print(f"(Excel report failed: {e}; report_auto.md / .json unaffected)")
        if xlsx_result is None:
            print("(openpyxl not installed; skipping Excel report - auto-enabled after pip install openpyxl)")
        else:
            paths.append(xlsx_path)
    if args.json:
        parent = os.path.dirname(os.path.abspath(args.json))
        os.makedirs(parent, exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        paths.append(args.json)
    return paths


def print_summary(s, payload, paths):
    c = s.color
    summ, cov = payload["summary"], payload["coverage"]
    marks = {"PASS": c.green, "FAIL": c.red, "WARN": c.yellow, "SKIP": c.dim}
    print()
    print(c.bold("=" * 64))
    print(c.bold("SUMMARY"))
    print(c.bold("=" * 64))
    for st in (PASS, FAIL, WARN, SKIP):
        label = f"{st:<5}"
        print(f"  {marks[st](label)} : {summ[st]}")
    print(f"  total : {summ['total_checks']}")
    print()
    ov = cov["overall_rates"]
    co, f = cov["core_rates"], cov["sweep_f"]
    pra = f"{summ['pass_rate_percent']}%"
    pre = f"{summ['pass_rate_excl_skip_percent']}%"
    print(f"  pass rate (all)       : {c.bold(pra)} "
          f"(PASS {ov['PASS']} / total {ov['total']})")
    print(f"  pass rate (excl SKIP) : {c.bold(pre)} "
          f"(PASS {ov['PASS']} / {ov['total'] - ov['SKIP']})")
    print(f"  core (excl [F])       : "
          f"{c.bold(str(summ['core_pass_rate_percent']) + '%')} all | "
          f"{c.bold(str(summ['core_pass_rate_excl_skip_percent']) + '%')} excl SKIP "
          f"(planned {cov['core_total']}, executed {cov['core_executed']})")
    print(f"  sweep [F]             : "
          f"{c.bold(str(summ['sweep_f_pass_rate_percent']) + '%')} all | "
          f"{c.bold(str(summ['sweep_f_pass_rate_excl_skip_percent']) + '%')} excl SKIP "
          f"(WARN {f['WARN']}, SKIP {f['SKIP']}, total {f['total']})")
    print(f"  exit code    : {summ['exit_code']} ({summ['exit_meaning']})")
    print("  reports      : " + ", ".join(paths))


def cmd_list_only(color, backend="ANY"):
    print(color.bold("OpenCV Camera API Test -- inventory (--list-only)"))
    print()
    if not CV2_OK:
        print(color.red("opencv (cv2) NOT installed -- static inventory only"))
    else:
        print(f"opencv   : {cv2.__version__}")
        print(f"python   : {sys.version.split()[0]} ({platform.machine()})")
        reg = getattr(cv2, "videoio_registry", None)
        if reg is not None and hasattr(reg, "getBackends"):
            try:
                names = [reg.getBackendName(b) for b in reg.getBackends()]
                print(f"backends : {', '.join(names)}")
            except Exception:
                pass
    print()
    by_group = {}
    for g, api in planned_check_items():
        by_group.setdefault(g, []).append(api)
    for g in sorted(by_group):
        print(color.cyan(f"[{g}] {GROUP_DESC[g]} ({len(by_group[g])})"))
        for api in by_group[g]:
            print(f"    - {api}")
    if CV2_OK:
        dyn = dynamic_api_names()
        print()
        print(color.cyan(f"dir(cv2.VideoCapture) -- {len(dyn)} public members"))
        for i in range(0, len(dyn), 4):
            print("    " + "".join(f"{n:<26}" for n in dyn[i:i + 4]))
        vw = writer_api_names()
        print()
        print(color.cyan(f"dir(cv2.VideoWriter) -- {len(vw)} public members"))
        for i in range(0, len(vw), 4):
            print("    " + "".join(f"{n:<26}" for n in vw[i:i + 4]))
        rg = registry_func_names()
        print()
        print(color.cyan(f"cv2.videoio_registry -- {len(rg)} functions"))
        for i in range(0, len(rg), 3):
            print("    " + "".join(f"{n:<38}" for n in rg[i:i + 3]))
        props = enumerate_cap_props()
        generic = [p for p in props if prop_family(p["name"])[0] is None]
        applicable = [p for p in props
                      if prop_family(p["name"])[0] is None
                      or family_applicable(prop_family(p["name"])[0], backend)]
        fam_counts = {}
        for p in props:
            label = prop_family(p["name"])[1]
            fam_counts[label] = fam_counts.get(label, 0) + 1
        print()
        print(color.cyan(f"CAP_PROP_* constants -- {len(props)} unique ids "
                         f"(generic {len(generic)}, applicable to backend={backend}: "
                         f"{len(applicable)})"))
        for label in sorted(k for k in fam_counts if k):
            print(f"    {label:<20} x{fam_counts[label]}")
    return 0


def positive_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int: {text!r}")
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Test OpenCV camera/videoio API availability, functionality and coverage.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-d", "--device", default="/dev/video0",
                        help="camera index or /dev/videoN path (or URL for FFMPEG/GSTREAMER) "
                             "- supports numeric N auto-converted to /dev/videoN")
    parser.add_argument("--backend", default="ANY", choices=BACKEND_CHOICES,
                        help="VideoCapture backend")
    parser.add_argument("--outdir", default="./report/new",
                        help="directory for report_auto.md / .json / .xlsx")
    parser.add_argument("--frames", type=positive_int, default=30,
                        help="number of frames for the read() loop")
    parser.add_argument("--width", type=int, default=None,
                        help="requested frame width (CAP_PROP_FRAME_WIDTH)")
    parser.add_argument("--height", type=int, default=None,
                        help="requested frame height (CAP_PROP_FRAME_HEIGHT)")
    parser.add_argument("--fps", type=int, default=None,
                        help="requested FPS (CAP_PROP_FPS)")
    parser.add_argument("--list-only", action="store_true",
                        help="only print the API inventory, run no tests")
    parser.add_argument("--no-full-sweep", action="store_true",
                        help="skip the [F] CAP_PROP_* full enumeration sweep")
    parser.add_argument("--json", metavar="PATH", default=None,
                        help="additional JSON report output path")
    parser.add_argument("--no-xlsx", action="store_true",
                        help="skip the Excel report (report.xlsx, needs openpyxl)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    color = Color(sys.stdout.isatty() and not os.environ.get("NO_COLOR"))
    if args.list_only:
        return cmd_list_only(color, args.backend)
    if not CV2_OK:
        print(color.red("ERROR: cv2 (opencv-python) is not installed; cannot run camera tests."))
        print("Install with: pip install opencv-python-headless")
        return 3
    suite = Suite(args, color)
    sweep = "off" if args.no_full_sweep else f"on (backend={args.backend})"
    print(color.bold("OpenCV Camera API Test"))
    print(f"  device={args.device} backend={args.backend} frames={args.frames} "
          f"outdir={args.outdir}")
    print(f"  opencv={cv2.__version__} python={sys.version.split()[0]} "
          f"machine={platform.machine()} full-sweep={sweep}")
    run_suite(suite)
    exit_code = decide_exit_code(suite)
    payload = build_payload(suite, exit_code)
    paths = write_reports(args, payload)
    print_summary(suite, payload, paths)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
