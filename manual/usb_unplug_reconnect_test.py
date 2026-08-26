#!/usr/bin/env python3
"""USB camera unplug/reconnect manual test helper.

Long-running capture loop with automatic reconnection, recording exactly what
the manual test item `real_usb_unplug_reconnect` asks for:

  - time from last good frame to disconnect detection   (detect latency)
  - number of reconnect attempts and time to recover    (downtime)
  - any exceptions raised during the whole session      (crash evidence)

Unplug / replug the camera while this script runs, then press Ctrl+C (or wait
for --max-duration) to get the summary. Outputs:

  <outdir>/events.jsonl   one line per state transition / exception
  <outdir>/summary.json   machine-readable totals
  stdout                  human-readable summary (paste into manual_report.json note)

Exit codes: 0 = clean stop, 1 = ran with failures/exceptions.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

try:
    import cv2
except ImportError:
    print("ERROR: opencv-python is required")
    sys.exit(3)

CONNECTED, LOST, RECONNECTING, RECOVERING = ("CONNECTED", "LOST", "RECONNECTING", "RECOVERING")


class Session:
    def __init__(self):
        self.t0 = time.perf_counter()
        self.events = []
        self.exceptions = []
        self.disconnects = []
        self.frames_ok = 0
        self.current_state = None

    def wall(self):
        return datetime.now().isoformat(timespec="milliseconds")

    def elapsed(self):
        return time.perf_counter() - self.t0

    def log(self, event, **kw):
        entry = {"t": round(self.elapsed(), 3), "wall": self.wall(),
                 "event": event, **kw}
        self.events.append(entry)
        print(f"[{entry['t']:>8.2f}s] {event} " + " ".join(f"{k}={v}" for k, v in kw.items()))

    def set_state(self, state):
        if state != self.current_state:
            self.log("state", from_=self.current_state, to=state)
            self.current_state = state


def open_stream(args):
    bid = {"ANY": cv2.CAP_ANY, "V4L2": cv2.CAP_V4L2,
           "GSTREAMER": cv2.CAP_GSTREAMER}[args.backend]
    dev = int(args.device) if str(args.device).isdigit() else args.device
    cap = cv2.VideoCapture(dev, bid)
    if not cap.isOpened():
        cap.release()
        return None
    if args.width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    if args.height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if args.fps:
        cap.set(cv2.CAP_PROP_FPS, args.fps)
    return cap


def main():
    p = argparse.ArgumentParser(description="USB unplug/reconnect capture test")
    p.add_argument("-d", "--device", default="/dev/video0")
    p.add_argument("--backend", default="V4L2", choices=["ANY", "V4L2", "GSTREAMER"])
    p.add_argument("--width", type=int, default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--fps", type=int, default=None)
    p.add_argument("--fail-threshold", type=int, default=5,
                   help="consecutive read failures before declaring disconnect")
    p.add_argument("--recover-good-frames", type=int, default=3,
                   help="consecutive good frames before declaring recovery")
    p.add_argument("--retry-interval", type=float, default=1.0)
    p.add_argument("--max-duration", type=float, default=None,
                   help="auto-stop after N seconds (otherwise Ctrl+C)")
    p.add_argument("--outdir", default="./reconnect_report")
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    s = Session()
    cap = None
    fails = 0
    good = 0
    attempts = 0
    last_good_t = None
    pending = None

    s.set_state(RECONNECTING)

    def stop_now():
        return args.max_duration is not None and s.elapsed() >= args.max_duration

    try:
        while True:
            if stop_now():
                break

            if s.current_state in (RECONNECTING, LOST):
                s.set_state(RECONNECTING)
                attempts += 1
                s.log("open_attempt", n=attempts)
                try:
                    cap = open_stream(args)
                except Exception as e:
                    s.exceptions.append(f"open: {e}")
                    s.log("open_exception", err=str(e)[:80])
                    cap = None
                if cap is None or not cap.isOpened():
                    s.set_state(LOST)
                    time.sleep(args.retry_interval)
                    continue
                s.set_state(RECOVERING)
                good = 0
                continue

            try:
                ok, frame = cap.read()
            except Exception as e:
                ok, frame = False, None
                s.exceptions.append(f"read: {e}")
                s.log("read_exception", err=str(e)[:80])

            if ok and frame is not None:
                fails = 0
                good += 1
                last_good_t = time.perf_counter()
                if s.current_state == RECOVERING:
                    if good >= args.recover_good_frames:
                        s.set_state(CONNECTED)
                        if pending is not None:
                            detect_lat = pending["detect_latency"]
                            downtime = s.elapsed() - pending["first_fail_t"]
                            rec = {"n": len(s.disconnects) + 1,
                                   "detect_latency_s": round(detect_lat, 3),
                                   "downtime_s": round(downtime, 3),
                                   "attempts": attempts}
                            s.disconnects.append(rec)
                            s.log("recovered", **rec)
                            pending = None
                        else:
                            s.log("stream_established",
                                  size=f"{frame.shape[1]}x{frame.shape[0]}")
                        attempts = 0
                    else:
                        s.log("recovering_frame", good=good)
                else:
                    s.frames_ok += 1
                    if s.frames_ok % 100 == 0:
                        s.log("alive", frames=s.frames_ok,
                              size=f"{frame.shape[1]}x{frame.shape[0]}")
                continue

            if s.current_state in (RECOVERING,):
                s.log("recover_failed_frame")
                cap.release()
                s.set_state(RECONNECTING)
                time.sleep(args.retry_interval)
                continue

            fails += 1
            if s.current_state == CONNECTED and fails >= args.fail_threshold:
                detect_lat = (time.perf_counter() - last_good_t
                              if last_good_t else float("nan"))
                s.log("disconnect_detected",
                      consecutive_fails=fails,
                      detect_latency_s=round(detect_lat, 3))
                pending = {"detect_latency": detect_lat,
                           "first_fail_t": time.perf_counter()}
                s.set_state(RECONNECTING)
            elif s.current_state != CONNECTED:
                s.set_state(LOST)
                time.sleep(args.retry_interval)

    except KeyboardInterrupt:
        s.log("interrupted_by_user")

    try:
        if cap is not None:
            cap.release()
    except Exception:
        pass

    total_downtime = sum(d["downtime_s"] for d in s.disconnects)
    summary = {
        "device": str(args.device),
        "backend": args.backend,
        "duration_s": round(s.elapsed(), 2),
        "frames_captured": s.frames_ok,
        "disconnect_count": len(s.disconnects),
        "disconnects": s.disconnects,
        "exception_count": len(s.exceptions),
        "exceptions": s.exceptions[:20],
        "verdict_hint": (
            "PASS-like: all disconnections detected and recovered"
            if s.disconnects and not s.exceptions
            else ("no-disconnect-tested" if not s.disconnects and not s.exceptions
                  else "check details")),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    with open(os.path.join(args.outdir, "events.jsonl"), "w", encoding="utf-8") as f:
        for e in s.events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(os.path.join(args.outdir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    c = lambda txt, code: f"\033[{code}m{txt}\033[0m" if sys.stdout.isatty() else txt
    print()
    print(c("=" * 60, "1"))
    print(c("UNPLUG/RECONNECT TEST SUMMARY", "1"))
    print(c("=" * 60, "1"))
    print(f"  device            : {summary['device']} ({summary['backend']})")
    print(f"  duration          : {summary['duration_s']}s")
    print(f"  frames captured   : {summary['frames_captured']}")
    print(f"  disconnects       : {summary['disconnect_count']}")
    for d in s.disconnects:
        print(f"    #{d['n']}: detect {d['detect_latency_s']}s | "
              f"downtime {d['downtime_s']}s | attempts {d['attempts']}")
    if total_downtime:
        print(f"  total downtime    : {round(total_downtime, 2)}s")
    print(f"  exceptions        : {summary['exception_count']}")
    for e in s.exceptions[:5]:
        print(f"    - {e[:90]}")
    print(f"  hint              : {summary['verdict_hint']}")
    print(f"  reports           : {args.outdir}/summary.json, {args.outdir}/events.jsonl")

    return 1 if s.exceptions else 0


if __name__ == "__main__":
    sys.exit(main())
