#!/usr/bin/env python3
"""Combine the three camera-toolkit test results into one Excel report.

Sources (all optional; missing ones are marked MISSING):
  - auto    : report/new/report_auto.json     (opencv_camera_api_test.py)
  - manual  : report/new/report_manual.json   (run_manual_suite.py)
  - official: report/new/videoio_gtest.log    (opencv_test_videoio via
              run_official_videoio_test.py)

Output: <outdir>/combined_report.xlsx
  Sheet Summary   : side-by-side stats, overall verdict, action hints
  Sheet Auto      : every check row (group/api/status/message)
  Sheet Manual    : 6 manual items (verdicts + evidence notes)
  Sheet Official  : every gtest case (status/duration), failures first

Exit codes: 0 = report written, no FAIL anywhere;
            1 = report written but some suites contain FAIL;
            2 = none of the source files were found.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def parse_gtest_log(path):
    tests, cur = [], None
    totals = {"ran": None, "cases": None, "passed": None, "failed": None,
              "skipped": None}
    err_lines = 0
    pat_run = re.compile(r"^\[\s*RUN\s*\]\s*(\S+)")
    pat_ok = re.compile(r"^\[\s*OK\s*\]\s*(\S+)(?:\s+\((\d+)\s*ms\))?")
    pat_fail = re.compile(r"^\[\s*FAILED\s*\]\s*(\S+)(?:\s+\((\d+)\s*ms\))?")
    for line in open(path, encoding="utf-8", errors="replace"):
        if "[ ERROR:" in line or "[ WARN:" in line:
            err_lines += 1
        m = pat_run.match(line)
        if m:
            cur = m.group(1)
            continue
        m = pat_ok.match(line)
        if m:
            tests.append({"name": m.group(1), "status": "PASS",
                          "ms": int(m.group(2)) if m.group(2) else None})
            cur = None
            continue
        m = re.match(r"^\[\s*FAILED\s*\]\s*(\d+)\s+tests?,", line)
        if m:
            totals["failed"] = int(m.group(1))
            continue
        m = pat_fail.match(line)
        if m:
            if cur is None:
                continue          # trailing gtest failed-list repeat, not a real case
            tests.append({"name": m.group(1), "status": "FAIL",
                          "ms": int(m.group(2)) if m.group(2) else None})
            cur = None
            continue
        m = re.search(r"\[\s*=+\s*\]\s*(\d+) tests? from (\d+) test cases? ran",
                      line)
        if m:
            totals["ran"], totals["cases"] = int(m.group(1)), int(m.group(2))
        m = re.search(r"\[\s*PASSED\s*\]\s*(\d+) tests?", line)
        if m:
            totals["passed"] = int(m.group(1))
        m = re.search(r"\[\s*FAILED\s*\]\s*(\d+) tests?", line)
        if m:
            totals["failed"] = int(m.group(1))
        m = re.search(r"\[\s*SKIPPED\s*\]\s*(\d+) tests?", line)
        if m:
            totals["skipped"] = int(m.group(1))
    return {"tests": tests, "totals": totals, "log_error_lines": err_lines}


def load_auto(path):
    d = json.load(open(path, encoding="utf-8"))
    s = d.get("summary", {})
    cov = d.get("coverage", {})
    env = d.get("environment", {})
    ver = env.get("opencv_version", d.get("meta", {}).get("opencv_version", ""))
    src = env.get("opencv_source", d.get("meta", {}).get("opencv_source", ""))
    src_tag = f"opencv {ver} ({src})" if src else f"opencv {ver}"
    return {
        "counts": {"PASS": s.get("PASS", 0), "FAIL": s.get("FAIL", 0),
                   "WARN": s.get("WARN", 0), "SKIP": s.get("SKIP", 0)},
        "total": s.get("total_checks"),
        "metric_lines": [
            f"pass rate {s.get('pass_rate_percent')}% "
            f"(excl skip {s.get('pass_rate_excl_skip_percent')}%)",
            f"sweep [F] pass {s.get('sweep_f_pass_rate_percent')}%",
            f"by-design skips {cov.get('skipped_by_design')}",
            src_tag,
        ],
        "rows": [[r["group"], r["api"], r["status"],
                  f"{r['message']}{' | ' + r['detail'] if r['detail'] else ''}"]
                 for r in d.get("results", [])],
        "headers": ["Group", "API", "Status", "Message / Detail"],
        "fails": [r["api"] for r in d.get("results", [])
                  if r["status"] == "FAIL"],
        "env": src_tag,
    }


def load_auto_cpp(path):
    d = json.load(open(path, encoding="utf-8"))
    s = d.get("summary", {})
    counts = {"PASS": s.get("PASS", 0), "FAIL": s.get("FAIL", 0),
              "WARN": s.get("WARN", 0), "SKIP": s.get("SKIP", 0)}
    meta = d.get("meta", {})
    env = d.get("environment", {})
    ver = env.get("opencv_version", meta.get("opencv_version", ""))
    src = env.get("opencv_source", meta.get("opencv_source", ""))
    src_tag = f"opencv {ver} ({src})" if src else f"opencv {ver}"
    rows = [[r["group"], r["api"], r["status"], r.get("message", "")]
            for r in d.get("results", [])]
    fails = [r["api"] for r in d.get("results", []) if r["status"] == "FAIL"]
    return {
        "counts": counts,
        "total": s.get("total_checks"),
        "metric_lines": [
            f"planned {s.get('core_total')}, executed {s.get('executed')}",
            f"device={meta.get('device')} backend={meta.get('backend')}",
            src_tag,
        ],
        "rows": rows,
        "headers": ["Group", "API", "Status", "Message"],
        "fails": fails,
        "note": "",
        "env": src_tag,
    }


def load_manual(path):
    d = json.load(open(path, encoding="utf-8"))
    counts = {}
    rows = []
    for r in d.get("results", []):
        st = r["status"]
        counts[st] = counts.get(st, 0) + 1
        rows.append([r["test_ref"], st,
                     (r.get("note") or "")[:500],
                     (r.get("checked_at") or "-")[:19]])
    env = d.get("environment", {})
    ver = env.get("opencv_version", d.get("opencv_version", ""))
    src = env.get("opencv_source", d.get("opencv_source", ""))
    src_tag = f"opencv {ver} ({src})" if src and ver else (f"opencv {ver}" if ver else "")
    metrics = [f"{k}={v}" for k, v in sorted(counts.items())]
    if src_tag:
        metrics.append(src_tag)
    return {
        "counts": counts, "total": len(rows),
        "metric_lines": metrics,
        "rows": rows,
        "headers": ["Test ref", "Status", "Note / Evidence", "Checked at"],
        "fails": [r["test_ref"] for r in d.get("results", [])
                  if r["status"] == "FAIL"],
        "env": src_tag,
    }


def load_manual_cpp(path):
    d = json.load(open(path, encoding="utf-8"))
    counts = {}
    rows = []
    fails = []
    for r in d.get("results", []):
        st = r.get("status", "?")
        ref = r.get("test_ref", r.get("group", "?"))
        counts[st] = counts.get(st, 0) + 1
        rows.append([ref, "operator verdict", st,
                     (r.get("note") or "")[:500]])
        if st == "FAIL":
            fails.append(ref)
    meta = d.get("meta", {})
    env = d.get("environment", {})
    ver = env.get("opencv_version", d.get("opencv_version", meta.get("opencv_version", "")))
    src = env.get("opencv_source", d.get("opencv_source", meta.get("opencv_source", "")))
    src_tag = f"opencv {ver} ({src})" if src and ver else (f"opencv {ver}" if ver else "")
    metric_lines = [f"{k}={v}" for k, v in sorted(counts.items())]
    if src_tag:
        metric_lines.append(src_tag)
    return {
        "counts": counts,
        "total": len(rows),
        "metric_lines": metric_lines,
        "rows": rows,
        "headers": ["Test ref", "Verdict", "Status", "Note"],
        "fails": fails,
        "note": "",
        "env": src_tag,
    }


def load_official(path):
    d = parse_gtest_log(path)
    t = d["totals"]
    n_pass = sum(1 for x in d["tests"] if x["status"] == "PASS")
    n_fail = sum(1 for x in d["tests"] if x["status"] == "FAIL")
    failed_total = t.get("failed") if t.get("failed") is not None else n_fail
    cap_fail = sum(1 for x in d["tests"] if x["status"] == "FAIL"
                   and x["name"].startswith("videoio_v4l2.formats"))
    known_latent = sum(1 for x in d["tests"] if x["status"] == "FAIL"
                       and x["name"] == "videoio_ffmpeg.camera_index")
    parts = []
    if cap_fail:
        parts.append(f"{cap_fail} = videoio_v4l2.formats/* camera format "
                     "capability boundary (expected on real hardware)")
    if known_latent:
        parts.append("1 = videoio_ffmpeg.camera_index latent upstream issue "
                     "(FFMPEG backend cannot open cameras by index; exposed "
                     "only because the VIVID env var un-skips it)")
    other = failed_total - cap_fail - known_latent
    if other > 0:
        parts.append(f"{other} need manual triage")
    note = "; ".join(parts)
    metric = [f"gtest ran={t.get('ran')}", f"pass={n_pass}",
              f"fail={failed_total}"]
    return {
        "counts": {"PASS": n_pass, "FAIL": n_fail},
        "total": t.get("ran") or n_pass + n_fail,
        "metric_lines": metric + ([f"log ERROR/WARN lines={d['log_error_lines']}"]
                                  if d["log_error_lines"] else []),
        "rows": [[x["name"], x["status"], x["ms"] if x["ms"] is not None else "-"]
                 for x in d["tests"]],
        "headers": ["gtest case", "Status", "Duration(ms)"],
        "fails": [x["name"] for x in d["tests"] if x["status"] == "FAIL"],
        "note": note, "env": "",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--auto", default=os.path.join("report", "new",
                                                   "report_auto.json"))
    ap.add_argument("--auto-cpp", default=os.path.join(
        "report", "new", "report_cpp.json"),
        help="C++ suite result (report_cpp.json)")
    ap.add_argument("--manual", default=os.path.join("report", "new",
                                                     "report_manual.json"))
    ap.add_argument("--manual-cpp", default=os.path.join(
        "report", "new", "report_manual_cpp.json"),
        help="C++ manual suite result (report_manual_cpp.json)")
    ap.add_argument("--official-log",
                    default=os.path.join("report", "new", "videoio_gtest.log"))
    ap.add_argument("--outdir", default=os.path.join("report", "new"))
    ap.add_argument("--name", default="combined_report.xlsx")
    args = ap.parse_args()

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("openpyxl not installed (pip install openpyxl); cannot build combined report")
        return 2

    sources = [("auto", args.auto, ".json", load_auto),
               ("auto-cpp", args.auto_cpp, ".json", load_auto_cpp),
               ("manual", args.manual, ".json", load_manual),
               ("manual-cpp", args.manual_cpp, ".json", load_manual_cpp),
               ("official", args.official_log, "log", load_official)]
    suites, missing = {}, []
    for name, path, ext, loader in sources:
        if os.path.isfile(path):
            try:
                suites[name] = loader(path)
                suites[name]["source"] = path
            except Exception as e:
                missing.append(f"{name}: parse error ({e})")
        else:
            missing.append(name)

    if not suites:
        print("No result files found; aborting.")
        return 2

    hdr_fill = PatternFill("solid", fgColor="1F4E78")
    hdr_font = Font(bold=True, color="FFFFFF")
    thin = Border(*[Side(style="thin", color="BFBFBF")] * 4)
    st_fill = {"PASS": (PatternFill("solid", fgColor="C6EFCE"), Font(color="006100")),
               "FAIL": (PatternFill("solid", fgColor="FFC7CE"), Font(color="9C0006", bold=True)),
               "WARN": (PatternFill("solid", fgColor="FFEB9C"), Font(color="9C6500")),
               "SKIP": (PatternFill("solid", fgColor="D9D9D9"), Font(color="404040")),
               "NOT_RUN": (PatternFill("solid", fgColor="F2F2F2"), Font(color="808080"))}

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"

    def put(row_idx, cells, bold_first=True):
        for j, v in enumerate(cells, 1):
            c = ws.cell(row=row_idx, column=j, value=v)
            c.border = thin
            if j == 1 and bold_first:
                c.font = Font(bold=True)

    ri = 1
    ws.cell(row=ri, column=1,
            value="Camera Toolkit - Combined Test Report (auto/manual/official)").font = Font(bold=True, size=14)
    ri += 2
    put(ri, ["Suite", "Source file", "Total", "PASS", "FAIL", "WARN", "SKIP/Other", "Key metrics"]); ri += 1

    def fmt_counts(counts):
        order = ["PASS", "FAIL", "WARN"]
        vals = [counts.get(k, 0) for k in order]
        other = sum(v for k, v in counts.items() if k not in order)
        return vals + [other]

    total_fail = 0
    suite_meta = {}
    for name in ("auto", "auto-cpp", "manual", "manual-cpp",
                 "official"):
        if name not in suites:
            put(ri, [name.upper(), "MISSING: " + (missing.pop(0) if missing else ""), "-", "-", "-", "-", "-", "-"])
            ri += 1
            continue
        d = suites[name]
        c = d["counts"]
        p, f, w, o = fmt_counts(c)
        total_fail += f
        put(ri, [name.upper(), d["source"], d["total"], p, f, w, o,
                 "; ".join(d["metric_lines"])])
        suite_meta[name] = d
        ri += 1

    ri += 1
    put(ri, ["== Overall verdict =="]); ri += 1
    if total_fail == 0:
        verdict = "No FAIL in any suite."
    else:
        verdict = f"{total_fail} FAIL total; see detail sheets."
    hints = []
    if "auto" in suite_meta and suite_meta["auto"]["fails"]:
        hints.append("auto failing checks: " + ", ".join(suite_meta["auto"]["fails"]))
    if "official" in suite_meta and suite_meta["official"].get("note"):
        hints.append("official attribution: " + suite_meta["official"]["note"])
    put(ri, ["Verdict", verdict]); ri += 1
    for h in hints:
        put(ri, ["Hint", h]); ri += 1
    put(ri, ["Generated", datetime.now().isoformat(timespec="seconds")])

    for col, w in (("A", 14), ("B", 52), ("C", 10), ("D", 9), ("E", 9),
                   ("F", 9), ("G", 11), ("H", 70)):
        ws.column_dimensions[col].width = w

    detail_fill = hdr_fill
    sheets = [("auto", "Auto"), ("auto-cpp", "Auto-CPP"),
              ("manual", "Manual"), ("manual-cpp", "Manual-CPP"),
              ("official", "Official")]
    for name, title in sheets:
        if name not in suites:
            continue
        d = suites[name]
        ws2 = wb.create_sheet(title)
        ws2.append(d["headers"])
        for c in ws2[1]:
            c.fill, c.font = detail_fill, hdr_font
            c.border = thin
        st_col = 3 if name != "official" else 2
        for row in d["rows"]:
            ws2.append(row)
            r2 = ws2.max_row
            stv = ws2.cell(row=r2, column=st_col).value
            if stv in st_fill:
                cell = ws2.cell(row=r2, column=st_col)
                cell.fill, cell.font = st_fill[stv]
            for c in ws2[r2]:
                c.border = thin
                c.alignment = Alignment(vertical="top",
                                        wrap_text=(name == "manual" and c.column == 3))
        widths = {"Auto": (8, 40, 9, 80), "Auto-CPP": (10, 40, 9, 70),
                  "Manual": (34, 10, 90, 22),
                  "Manual-CPP": (34, 18, 12, 80),
                  "Official": (64, 10, 14)}[title]
        for i, w in enumerate(widths, 1):
            ws2.column_dimensions[get_column_letter(i)].width = w
        ws2.freeze_panes = "A2"
        ws2.auto_filter.ref = ws2.dimensions

    out = os.path.join(args.outdir, args.name)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    wb.save(out)

    print("=" * 60)
    print("COMBINED REPORT")
    print("=" * 60)
    for name in ("auto", "auto-cpp", "manual", "manual-cpp",
                 "official"):
        if name in suites:
            d = suites[name]
            c = d["counts"]
            print(f"  {name:<9}: PASS={c.get('PASS',0)} FAIL={c.get('FAIL',0)} "
                  f"WARN={c.get('WARN',0)} SKIP/other={sum(v for k,v in c.items() if k not in ('PASS','FAIL','WARN'))}")
        else:
            print(f"  {name:<9}: MISSING")
    print(f"  verdict : {verdict}")
    for h in hints:
        print(f"  hint    : {h}")
    print(f"  saved   : {out}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
