#!/usr/bin/env python3
"""compare_champions.py -- Aimsun vs SUMO paper-method champion results.

Reads the Aimsun per-run result dirs (logan_road_new/results/<ARM>_seed*_*/)
and the SUMO champion CSVs (Z:/tsp/sumo_hpc/champ_*.csv) and renders one
HTML table: per-arm obj vs NO_TSP on each platform, the per-seed spread
(sensitivity), and the guarded verdict (totDelay%, served%, VQ).

Usage: python compare_champions.py [-o out.html]
"""
import csv
import glob
import html
import json
import os
import statistics as st
import sys

ROOT = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
AIMSUN_RES = os.path.join(ROOT, "logan_road_new", "results")
SUMO_BASE = r"Z:\tsp\sumo_hpc"

ARMS = [
    ("NO_TSP", "champ_notsp", "notsp"),
    ("MARL_CONT", "champ_marl_cont", "marl_cont"),
    ("MARL_CONT_EASE", "champ_marl_ease", "marl_ease"),
    ("MARL_CONT_EXACT", "champ_marl_exact", "marl_exact"),
    ("CELLQ_CONT_DE", "champ_cellq_de", "cellq_de"),
    ("CELLQ_CONT_DE_NOPOG", "champ_cellq_nopog", "cellq_nopog"),
    ("CELLQ_CONT_DE_STIFF", "champ_cellq_stiff", "cellq_stiff"),
    ("NASH_CONT", "champ_nash_cont", "nash_cont"),
    ("NASH_CONT_GATED", "champ_nash_gated", "nash_gated"),
    ("NASH_CONT_INTDUR", "champ_nash_intdur", "nash_intdur"),
]
SEEDS = ["300", "400", "500"]


def aimsun_arm(name, seed):
    ds = sorted(glob.glob(os.path.join(AIMSUN_RES, f"{name}_seed{seed}_*")),
                key=os.path.getmtime)
    if not ds:
        return None
    p = os.path.join(ds[-1], "simulation_results.csv")
    if not os.path.isfile(p):
        return None
    try:
        return list(csv.DictReader(open(p, encoding="utf-8-sig")))[-1]
    except Exception:
        return None


def sumo_rows(name):
    p = os.path.join(SUMO_BASE, f"{name}.csv")
    if not os.path.isfile(p):
        return []
    return [r for r in csv.DictReader(open(p, encoding="utf-8"))
            if str(r.get("phase", "eval")).lower() == "eval"
            and str(r.get("ok", "")).lower() in ("true", "1")]


def mean(rows, k):
    v = [float(r.get(k)) for r in rows if r.get(k)]
    return st.mean(v) if v else float("nan")


def spread(vals):
    vals = [v for v in vals if v == v]
    if len(vals) < 2:
        return 0.0
    return max(vals) - min(vals)


def verdict(arm_rows, base_rows):
    """(totDelay%, served%, vq) vs NO_TSP same seed; None when unavailable."""
    if not arm_rows or not base_rows:
        return None
    td = sv = ok = 0
    for r in arm_rows:
        bb = base_rows.get(str(r.get("seed")))
        if bb and float(bb.get("TotalPassDelay_hrs", 0) or 0) > 0:
            td += (float(r["TotalPassDelay_hrs"])
                   - float(bb["TotalPassDelay_hrs"])) \
                  / float(bb["TotalPassDelay_hrs"]) * 100
            sv += float(r["PaxEquivPassages"]) \
                  / float(bb["PaxEquivPassages"]) * 100
            ok += 1
    if not ok:
        return None
    return td / ok, sv / ok, mean(arm_rows, "Net_VQVeh_All")


def main(argv):
    out = "compare_champions.html"
    if len(argv) > 1 and argv[1] == "-o":
        out = argv[2]
    # Aimsun baselines
    a_base = {s: aimsun_arm("NO_TSP", s) for s in SEEDS}
    # SUMO baselines
    s_base = {r.get("seed"): r for r in sumo_rows("champ_notsp")}

    rows_html = []
    for name, sumo_file, tag in ARMS:
        a_per, s_per = {}, {}
        a_td = a_sv = a_vq = s_td = s_sv = s_vq = None
        a_act = s_act = 0.0
        # Aimsun
        a_rows = [aimsun_arm(name, s) for s in SEEDS]
        a_rows = [r for r in a_rows if r]
        if a_rows:
            for s in SEEDS:
                r = aimsun_arm(name, s)
                bb = a_base.get(s)
                if r and bb:
                    a_per[s] = (float(r["Objective_PaxPerDelayHr"])
                                - float(bb["Objective_PaxPerDelayHr"])) \
                               / float(bb["Objective_PaxPerDelayHr"]) * 100
            vd = verdict(a_rows, {s: bb for s, bb in a_base.items()})
            if vd:
                a_td, a_sv, a_vq = vd
            a_act = mean(a_rows, "TSP_Extensions") + mean(a_rows,
                                                          "TSP_Insertions")
        # SUMO
        s_rows = sumo_rows(sumo_file)
        if s_rows:
            for s in SEEDS:
                r = next((x for x in s_rows if x.get("seed") == s), None)
                bb = s_base.get(s)
                if r and bb:
                    s_per[s] = (float(r["obj_pax_per_delay_hr"])
                                - float(bb["obj_pax_per_delay_hr"])) \
                               / float(bb["obj_pax_per_delay_hr"]) * 100
            vd = verdict(s_rows, s_base)
            if vd:
                s_td, s_sv, s_vq = vd
            s_act = mean(s_rows, "n_tsp_extensions") + mean(
                s_rows, "n_tsp_insertions")

        def fmt(d, platform):
            if d is None:
                return "-"
            return f"{d:+.1f}%"

        a_med = st.median([v for v in a_per.values()]) if a_per else float(
            "nan")
        s_med = st.median([v for v in s_per.values()]) if s_per else float(
            "nan")
        a_spr = spread(list(a_per.values()))
        s_spr = spread(list(s_per.values()))
        rows_html.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td class='{'win' if a_med == a_med and a_med < 0 else ''}'>{fmt(a_med, 'a')}</td>"
            f"<td>{a_spr if a_per else '-'}</td>"
            f"<td>{a_td if a_td is not None else '-'}</td>"
            f"<td>{a_sv if a_sv is not None else '-'}</td>"
            f"<td>{a_act if a_rows else '-'}</td>"
            f"<td class='{'win' if s_med == s_med and s_med < 0 else ''}'>{fmt(s_med, 's')}</td>"
            f"<td>{s_spr if s_per else '-'}</td>"
            f"<td>{s_td if s_td is not None else '-'}</td>"
            f"<td>{s_sv if s_sv is not None else '-'}</td>"
            f"<td>{s_act if s_rows else '-'}</td>"
            "</tr>")
    doc = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>"
        "Champion comparison (Aimsun vs SUMO)</title><style>"
        "body{font-family:sans-serif;margin:20px;background:#f7f7f7}"
        "table{border-collapse:collapse;background:#fff;font-size:14px}"
        "th,td{border:1px solid #ccc;padding:6px 10px;text-align:right}"
        "th:first-child,td:first-child{text-align:left}"
        "th{background:#eee}.win{color:#1a7f37;font-weight:700}"
        ".lose{color:#cf222e}"
        ".small{color:#666;font-size:12px}"
        "</style></head><body>"
        "<h2>Paper-method champion search - Aimsun vs SUMO (real plan)</h2>"
        "<p class=\"small\">Columns: obj vs NO_TSP = median of per-seed "
        "percent (negative = WIN, green). spread = max-min of the three "
        "per-seed percent. totDelay percent / served percent = guarded "
        "verdict vs NO_TSP same seed. act = extensions+insertions. "
        "Sensitivity is the spread: tight cluster = least sensitive.</p>"
        "<table><tr><th>arm</th><th>Aim obj</th><th>Aim spr</th>"
        "<th>Aim totD</th><th>Aim svd</th><th>Aim act</th>"
        "<th>Sum obj</th><th>Sum spr</th><th>Sum totD</th>"
        "<th>Sum svd</th><th>Sum act</th></tr>"
        + "\n".join(rows_html)
        + "</table></body></html>")
    open(out, "w", encoding="utf-8").write(doc)
    print(f"wrote {out} ({os.path.getsize(out) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))