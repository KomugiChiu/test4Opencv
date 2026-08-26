#!/usr/bin/env python3
"""Helper for the manual test item `white_balance_visual_check`.

Objective metrics per setting:
  - R/G/B channel means : for a neutral scene, balanced WB means R~G~B
  - warm/cast indicator : (R-B); positive = reddish/warm, negative = bluish/cool
Snapshots are saved per setting for eyeball confirmation.

UVC/V4L2 conventions (driver-dependent, verify with 'status'):
  AUTO_WB          = 44, 1=on / 0=off
  WB_TEMPERATURE   = 45, kelvin-ish absolute value (C920 range ~2000-6500)
  WHITE_BALANCE_BLUE_U / RED_V = 17 / 26, raw channel gains (often unsupported)

Commands:
  status                       print WB-related get() values + current RGB means
  auto --state 1|0             switch AUTO_WB
  temp  --values 2500,4500,6500  turn AUTO_WB off, sweep WB_TEMPERATURE
All sweeps restore AUTO_WB=1 afterwards.
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np


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


def rgb_means(frame):
    b, g, r = [float(x) for x in cv2.mean(frame)[:3]]
    return r, g, b


def measure(cap, frames=12, save=None):
    rs, gs, bs, snap = [], [], [], None
    for i in range(frames):
        ok, f = cap.read()
        if not ok:
            continue
        r, g, b = rgb_means(f)
        rs.append(r)
        gs.append(g)
        bs.append(b)
        if i == frames // 2:
            snap = f.copy()
    if not rs:
        return None
    rm, gm, bm = (float(np.mean(x)) for x in (rs, gs, bs))
    if save and snap is not None:
        cv2.imwrite(save, snap)
    return {"R": round(rm, 1), "G": round(gm, 1), "B": round(bm, 1),
            "cast(R-B)": round(rm - bm, 1),
            "snapshot": os.path.basename(save) if save else None}


def show(cap, label):
    ids = {"AUTO_WB": cv2.CAP_PROP_AUTO_WB,
           "WB_TEMPERATURE": cv2.CAP_PROP_WB_TEMPERATURE,
           "WHITE_BALANCE_BLUE_U": cv2.CAP_PROP_WHITE_BALANCE_BLUE_U,
           "WHITE_BALANCE_RED_V": cv2.CAP_PROP_WHITE_BALANCE_RED_V}
    print(f"-- {label} --")
    for k, pid in ids.items():
        print(f"  {k:<22}= {cap.get(pid)}")


def sweep(args, cap, prop_id, values, label):
    rows = []
    initial = cap.get(prop_id)
    for v in values:
        ok = cap.set(prop_id, float(v))
        got = cap.get(prop_id)
        settle(cap, args.settle)
        m = measure(cap, frames=args.frames,
                    save=os.path.join(args.outdir, f"{label}_{int(v)}.jpg"))
        row = {label: v, "set_returned": bool(ok), "get_readback": got, **m}
        print(f"set({label}={v}) -> {ok}, get()={got} | "
              f"R={m['R']} G={m['G']} B={m['B']} cast(R-B)={m['cast(R-B)']}")
        rows.append(row)
    cap.set(prop_id, initial)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["status", "auto", "temp"])
    p.add_argument("-d", "--device", default="/dev/video0")
    p.add_argument("--backend", default="V4L2", choices=["ANY", "V4L2"])
    p.add_argument("--state", type=int, default=1, help="AUTO_WB 1=on 0=off")
    p.add_argument("--values", default="2500,4000,5500,6500")
    p.add_argument("--frames", type=int, default=12)
    p.add_argument("--settle", type=int, default=6)
    p.add_argument("--outdir", default="./wb_check")
    args = p.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    cap = open_cam(args)
    rows = []

    if args.command == "status":
        show(cap, "current state")
        settle(cap, args.settle)
        m = measure(cap, frames=args.frames,
                    save=os.path.join(args.outdir, "wb_current.jpg"))
        print(f"  brightness RGB: {m}")

    elif args.command == "auto":
        ok = cap.set(cv2.CAP_PROP_AUTO_WB, float(args.state))
        print(f"set(AUTO_WB={args.state}) -> {ok}, "
              f"get()={cap.get(cv2.CAP_PROP_AUTO_WB)}")
        settle(cap, args.settle)
        m = measure(cap, frames=args.frames,
                    save=os.path.join(args.outdir, f"wb_auto_{args.state}.jpg"))
        print(f"RGB: {m}")
        rows.append({"AUTO_WB": args.state, **m})

    elif args.command == "temp":
        r = cap.set(cv2.CAP_PROP_AUTO_WB, 0.0)
        print(f"AUTO_WB -> 0 ({r})")
        rows += sweep(args, cap, cv2.CAP_PROP_WB_TEMPERATURE,
                      [float(x) for x in args.values.split(",")],
                      "WB_TEMP")
        cap.set(cv2.CAP_PROP_AUTO_WB, 1.0)
        print("(restored AUTO_WB=1)")

    if rows:
        print("\n== Summary (paste into manual_report note) ==")
        print(json.dumps(rows, ensure_ascii=False))
        print(f"\nsnapshots saved in {args.outdir}/ - visually compare warm/cool shift")

    cap.release()


if __name__ == "__main__":
    main()
