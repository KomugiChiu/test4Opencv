#!/usr/bin/env python3
"""Helper for the manual test item `exposure_visual_check`.

Measures objective mean brightness (gray std/mean over N frames) under
different AUTO_EXPOSURE / EXPOSURE settings and saves a snapshot per setting,
so the operator can combine numbers with eyeball judgement.

Commands:
  status                     print current exposure-related get() values
  auto                       switch to auto exposure, measure brightness
  manual --value N           switch to manual, set EXPOSURE=N, measure
  sweep --values 5,20,50,100 manual sweep over a list of values
Every measurement saves <outdir>/exp_<mode>_<value>.jpg for visual review.

Typical session (UVC/V4L2 convention: AUTO_EXPOSURE 1=manual, 3=auto):
  python3 exposure_visual_check.py -d /dev/video2 status
  python3 exposure_visual_check.py -d /dev/video2 auto
  python3 exposure_visual_check.py -d /dev/video2 sweep --values 10,50,100,200,400
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np


def open_cam(args):
    bid = {"ANY": cv2.CAP_ANY, "V4L2": cv2.CAP_V4L2}[args.backend]
    dev = int(args.device) if str(args.device).isdigit() else args.device
    cap = cv2.VideoCapture(dev, bid)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {args.device}")
    if args.width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    if args.height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    return cap


def settle(cap, n=8):
    for _ in range(n):
        cap.read()


def measure(cap, frames=12, save=None):
    means = []
    snap = None
    for i in range(frames):
        ok, f = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        means.append(float(gray.mean()))
        if i == frames // 2:
            snap = f.copy()
    if save and snap is not None:
        cv2.imwrite(save, snap)
    return (round(float(np.mean(means)), 1),
            round(float(np.std(means)), 1)) if means else (None, None)


def get_exposure_state(cap):
    ae = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
    ex = cap.get(cv2.CAP_PROP_EXPOSURE)
    return ae, ex


def cmd_status(args, cap):
    ae, ex = get_exposure_state(cap)
    print(f"AUTO_EXPOSURE = {ae}   (UVC/V4L2 convention: 1=manual, 3=auto)")
    print(f"EXPOSURE      = {ex}")
    m, s = measure(cap, frames=6)
    print(f"current brightness: mean={m} (+/-{s}, {args.frames}f avg)")


def apply_and_measure(args, cap, mode_label, value_label, fname_tag):
    settle_cap_frames = args.settle
    settle(cap, settle_cap_frames)
    m, s = measure(cap, frames=args.frames,
                   save=os.path.join(args.outdir, f"{fname_tag}.jpg"))
    ae, ex = get_exposure_state(cap)
    row = {"mode": mode_label, "requested": value_label,
           "brightness_mean": m, "frame_std": s,
           "get_AUTO_EXPOSURE": ae, "get_EXPOSURE": ex}
    print(f"{mode_label:<8} req={value_label:<8} brightness={m} (+/-{s}) "
          f"| get(): AE={ae} EXP={ex}")
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["status", "auto", "manual", "sweep"])
    p.add_argument("-d", "--device", default="/dev/video0")
    p.add_argument("--backend", default="V4L2", choices=["ANY", "V4L2"])
    p.add_argument("--width", type=int, default=None)
    p.add_argument("--height", type=int, default=None)
    p.add_argument("--frames", type=int, default=12, help="frames averaged per measurement")
    p.add_argument("--settle", type=int, default=8, help="discard frames after each set()")
    p.add_argument("--value", type=float, default=None, help="EXPOSURE value for 'manual'")
    p.add_argument("--values", default="10,50,100,200,400",
                   help="comma list of EXPOSURE values for 'sweep'")
    p.add_argument("--outdir", default="./exp_check")
    args = p.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    cap = open_cam(args)
    rows = []

    if args.command == "status":
        cmd_status(args, cap)

    elif args.command == "auto":
        r = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
        print(f"set(AUTO_EXPOSURE=3/auto) -> {r}")
        rows.append(apply_and_measure(args, cap, "AUTO", "-", "exp_auto"))

    elif args.command == "manual":
        r1 = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
        print(f"set(AUTO_EXPOSURE=1/manual) -> {r1}")
        r2 = cap.set(cv2.CAP_PROP_EXPOSURE, args.value if args.value is not None else 100)
        print(f"set(EXPOSURE={args.value}) -> {r2}")
        rows.append(apply_and_measure(args, cap, "MANUAL",
                                      str(args.value), f"exp_manual_{args.value}"))

    elif args.command == "sweep":
        r = cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
        print(f"set(AUTO_EXPOSURE=1/manual) -> {r}")
        vals = [float(x) for x in args.values.split(",")]
        rows.append({"mode": "AUTO(base)", "requested": "-",
                     **dict(zip(("brightness_mean", "frame_std"),
                                measure(cap, frames=args.frames)))})
        for v in vals:
            ok = cap.set(cv2.CAP_PROP_EXPOSURE, v)
            got = cap.get(cv2.CAP_PROP_EXPOSURE)
            print(f"set(EXPOSURE={v}) -> {ok}, get()={got}")
            rows.append(apply_and_measure(
                args, cap, "MANUAL", str(v), f"exp_manual_{int(v)}"))

        # restore auto at the end
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
        print("(restored AUTO_EXPOSURE=3)")

    if rows:
        print("\n== Summary (paste into manual_report note) ==")
        print(json.dumps(rows, ensure_ascii=False))
        print(f"\nsnapshots saved in {args.outdir}/ - open in a viewer and compare brightness")

    cap.release()


if __name__ == "__main__":
    import json
    sys.exit(main())
