#!/usr/bin/env python3
"""Helper for the manual test item `autofocus_visual_check`.

Objective metrics per setting:
  - focus sharpness : variance of Laplacian on the center ROI (higher = sharper,
                      the classic focus-peaking metric)
  - frame delta     : mean abs diff vs reference frame (detects pan/tilt/zoom
                      image shift that sharpness cannot see)
Snapshots are saved per setting for eyeball confirmation.

Commands:
  status                        print AUTOFOCUS/FOCUS/ZOOM/PAN/TILT get() values
  autofocus --state 1|0         switch auto focus on/off
  focus  --values 0,60,150,250  manual focus sweep (UVC unit: diopter*100,
                                0=infinity ... large=near)
  zoom   --values 100,150,250   digital zoom sweep (UVC percent-ish, 100=wide)
  pantilt --pan -50,0,50 --tilt 0,30
All sweeps restore the initial state afterwards.
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np

CENTER = 0.5


def open_cam(args):
    bid = {"ANY": cv2.CAP_ANY, "V4L2": cv2.CAP_V4L2}[args.backend]
    dev = int(args.device) if str(args.device).isdigit() else args.device
    cap = cv2.VideoCapture(dev, bid)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {args.device}")
    return cap


def settle(cap, n=8):
    for _ in range(n):
        cap.read()


def sharpness(frame):
    h, w = frame.shape[:2]
    roi = frame[int(h * CENTER / 2):int(h * (1 - CENTER / 2)),
                int(w * CENTER / 2):int(w * (1 - CENTER / 2))]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def measure(cap, ref_gray, frames=10, save=None):
    laps, diffs, snap = [], [], None
    for i in range(frames):
        ok, f = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        laps.append(sharpness(f))
        if ref_gray is not None:
            diffs.append(float(np.abs(g.astype(np.int16)
                                      - ref_gray.astype(np.int16)).mean()))
        if i == frames // 2:
            snap = f.copy()
    if save and snap is not None:
        cv2.imwrite(save, snap)
    return (round(float(np.mean(laps)), 1) if laps else None,
            round(float(np.mean(diffs)), 2) if diffs else None,
            snap)


def props(cap, names):
    ids = {"AUTOFOCUS": cv2.CAP_PROP_AUTOFOCUS, "FOCUS": cv2.CAP_PROP_FOCUS,
           "ZOOM": cv2.CAP_PROP_ZOOM, "PAN": cv2.CAP_PROP_PAN,
           "TILT": cv2.CAP_PROP_TILT}
    return {n: cap.get(ids[n]) for n in names}


def sweep(args, cap, prop_id, values, label):
    rows = []
    settle_ok, ref = cap.read()
    ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY) if settle_ok else None
    initial = cap.get(prop_id)
    for v in values:
        ok = cap.set(prop_id, float(v))
        got = cap.get(prop_id)
        settle(cap, args.settle)
        lap, diff, snap = measure(cap, ref_gray, frames=args.frames,
                                  save=os.path.join(
                                      args.outdir, f"{label}_{int(v)}.jpg"))
        print(f"set({label}={v}) -> {ok}, get()={got} | "
              f"sharpness={lap}, delta_vs_ref={diff}")
        rows.append({label: v, "set_returned": bool(ok), "get_readback": got,
                     "sharpness_lapvar": lap, "delta_vs_ref": diff})
    cap.set(prop_id, initial)
    print(f"(restored {label}={initial})")
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["status", "autofocus", "focus",
                                       "zoom", "pantilt"])
    p.add_argument("-d", "--device", default="/dev/video0")
    p.add_argument("--backend", default="V4L2", choices=["ANY", "V4L2"])
    p.add_argument("--values", default="0,80,160,250")
    p.add_argument("--pan", default="0")
    p.add_argument("--tilt", default="0")
    p.add_argument("--frames", type=int, default=10)
    p.add_argument("--settle", type=int, default=6)
    p.add_argument("--outdir", default="./focus_check")
    args = p.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    cap = open_cam(args)
    rows = []

    if args.command == "status":
        st = props(cap, ["AUTOFOCUS", "FOCUS", "ZOOM", "PAN", "TILT"])
        for k, v in st.items():
            print(f"{k:<10}= {v}")
        settle(cap, args.settle)
        lap, _, _ = measure(cap, None, frames=args.frames)
        print(f"current center sharpness (Laplacian var): {lap}")

    elif args.command == "autofocus":
        st = int(getattr(args, "state", 1)) if hasattr(args, "state") else 1
        r = cap.set(cv2.CAP_PROP_AUTOFOCUS, float(st))
        print(f"set(AUTOFOCUS={st}) -> {r}, get()={cap.get(cv2.CAP_PROP_AUTOFOCUS)}")

    elif args.command == "focus":
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 0.0)
        print("AUTOFOCUS -> 0 (manual)")
        rows += sweep(args, cap, cv2.CAP_PROP_FOCUS,
                      [float(x) for x in args.values.split(",")], "FOCUS")
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 1.0)
        print("(restored AUTOFOCUS=1)")

    elif args.command == "zoom":
        rows += sweep(args, cap, cv2.CAP_PROP_ZOOM,
                      [float(x) for x in args.values.split(",")], "ZOOM")

    elif args.command == "pantilt":
        rows += sweep(args, cap, cv2.CAP_PROP_PAN,
                      [float(x) for x in args.pan.split(",")], "PAN")
        rows += sweep(args, cap, cv2.CAP_PROP_TILT,
                      [float(x) for x in args.tilt.split(",")], "TILT")

    if rows:
        print("\n== Summary (paste into manual_report note) ==")
        print(json.dumps(rows, ensure_ascii=False))
        print(f"\nsnapshots saved in {args.outdir}/ - compare sharpness/FoV visually")

    cap.release()


if __name__ == "__main__":
    main()
