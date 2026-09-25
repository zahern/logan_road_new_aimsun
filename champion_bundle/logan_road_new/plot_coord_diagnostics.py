"""
plot_coord_diagnostics.py
========================
Summarize corridor coordination queue-stage diagnostics by intersection.

Outputs one PNG that shows, per target intersection:
1) Average shockwave-equation inputs (queue size, queue-clearance, wave-delay)
2) Average prediction/result terms (sigma, ETA delta, ETA to target)
3) Average passenger-delay KPIs (main / side / total) from
   simulation_results_per_intersection.csv
4) EARLY_RED action counts and average cut duration from TSP log

Usage:
  python plot_coord_diagnostics.py [wave_events_csv] [per_intersection_csv] [out_png] [tsp_log]
"""

import os
import sys
import csv
import glob
import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

_MPL_READY = False
plt = None

def _ensure_mpl():
    global _MPL_READY, plt
    if _MPL_READY:
        return
    _aimsun_path = r"C:\AimsunPackages"
    if _aimsun_path not in sys.path:
        sys.path.insert(0, _aimsun_path)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt
    plt = _plt
    _MPL_READY = True


def _to_float(v, default=0.0):
    try:
        if v is None:
            return float(default)
        s = str(v).strip()
        if not s:
            return float(default)
        return float(s)
    except Exception:
        return float(default)


def _latest_matching(patterns):
    best_path = None
    best_mtime = -1.0
    for pat in patterns:
        for p in glob.glob(pat, recursive=True):
            if not os.path.isfile(p):
                continue
            try:
                mt = os.path.getmtime(p)
            except Exception:
                continue
            if mt > best_mtime:
                best_mtime = mt
                best_path = p
    return best_path


def _load_wave_rows(path):
    rows = []
    if not path or not os.path.isfile(path):
        return rows
    with open(path, "r", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if str(r.get("event", "")).strip() != "prearm_queued":
                continue
            target = int(_to_float(r.get("target_jct"), -1))
            if target <= 0:
                continue
            rows.append({
                "target_jct": target,
                "queue_len_veh": _to_float(r.get("queue_len_veh")),
                "queue_clearance_s": _to_float(r.get("queue_clearance_s")),
                "wave_delay_s": _to_float(r.get("wave_delay_s")),
                "eta_delta_s": _to_float(r.get("eta_delta_s")),
                "eta_final_s": _to_float(r.get("eta_final_s")),
                "sigma_s": _to_float(r.get("sigma_s")),
                "shockwave_w4_ms": _to_float(r.get("shockwave_w4_ms")),
                "sat_flow_vph": _to_float(r.get("sat_flow_vph")),
            })
    return rows


def _load_delay_map(path):
    out = {}
    if not path or not os.path.isfile(path):
        return out
    with open(path, "r", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            iid = int(_to_float(r.get("IntersectionID"), -1))
            if iid <= 0:
                continue
            out[iid] = {
                "main": _to_float(r.get("AvgMainPassDelay_pax_h_per_sim_h")),
                "side": _to_float(r.get("AvgSidePassDelay_pax_h_per_sim_h")),
                "total": _to_float(r.get("AvgTotalPassDelay_pax_h_per_sim_h")),
            }
    return out


def _load_early_red_events(tsp_log_path):
    """
    Parse a TSP log file for EARLY_RED grant events.

    Looks for log lines of the form:
        [GREEN_GRANT] inter=X ... type=DCTSP_EARLY_RED cut=Y.Zs ...

    Returns dict: {intersection_id: {"count": N, "total_cut_s": F}}
    """
    out = {}
    if not tsp_log_path or not os.path.isfile(tsp_log_path):
        return out
    import re
    _pat = re.compile(
        r'\[GREEN_GRANT\].*?inter=(\d+).*?type=DCTSP_EARLY_RED.*?cut=([\d.]+)s',
        re.IGNORECASE)
    try:
        with open(tsp_log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _pat.search(line)
                if m:
                    iid = int(m.group(1))
                    cut = float(m.group(2))
                    if iid not in out:
                        out[iid] = {"count": 0, "total_cut_s": 0.0}
                    out[iid]["count"] += 1
                    out[iid]["total_cut_s"] += cut
    except Exception:
        pass
    return out


def _aggregate(rows):
    sums = {}
    cnts = {}
    keys = [
        "queue_len_veh", "queue_clearance_s", "wave_delay_s",
        "eta_delta_s", "eta_final_s", "sigma_s",
        "shockwave_w4_ms", "sat_flow_vph",
    ]
    for r in rows:
        j = r["target_jct"]
        if j not in sums:
            sums[j] = {k: 0.0 for k in keys}
            cnts[j] = 0
        cnts[j] += 1
        for k in keys:
            sums[j][k] += float(r.get(k, 0.0) or 0.0)

    agg = {}
    for j, sd in sums.items():
        n = max(cnts.get(j, 0), 1)
        agg[j] = {k: sd[k] / n for k in keys}
        agg[j]["n_events"] = cnts[j]
    return agg


def run(wave_csv=None, per_inter_csv=None, out_png=None, tsp_log=None):
    _ensure_mpl()

    if wave_csv is None:
        wave_csv = _latest_matching([
            os.path.join("logs", "corridor_wave_events_*.csv"),
            os.path.join("**", "corridor_wave_events_*.csv"),
        ])

    if per_inter_csv is None:
        per_inter_csv = _latest_matching([
            os.path.join("Aimsun_Results", "**", "simulation_results_per_intersection.csv"),
            os.path.join("**", "simulation_results_per_intersection.csv"),
        ])

    if tsp_log is None:
        tsp_log = _latest_matching([
            os.path.join("logs", "Aimsun_TSP_Log_*.txt"),
            os.path.join("**", "Aimsun_TSP_Log_*.txt"),
        ])

    if not wave_csv or not os.path.isfile(wave_csv):
        print("[COORD DIAG] No corridor wave events CSV found; skipping plot.")
        return None

    rows = _load_wave_rows(wave_csv)
    if not rows:
        print("[COORD DIAG] No prearm_queued events found; skipping plot.")
        return None

    delay_map = _load_delay_map(per_inter_csv)
    er_map    = _load_early_red_events(tsp_log)
    agg = _aggregate(rows)
    jcts = sorted(agg.keys())
    x = list(range(len(jcts)))

    q_len = [agg[j]["queue_len_veh"] for j in jcts]
    q_clr = [agg[j]["queue_clearance_s"] for j in jcts]
    w_del = [agg[j]["wave_delay_s"] for j in jcts]

    e_del = [agg[j]["eta_delta_s"] for j in jcts]
    e_fin = [agg[j]["eta_final_s"] for j in jcts]
    sigm = [agg[j]["sigma_s"] for j in jcts]
    w4ms = [agg[j]["shockwave_w4_ms"] for j in jcts]

    d_main = [delay_map.get(j, {}).get("main", 0.0) for j in jcts]
    d_side = [delay_map.get(j, {}).get("side", 0.0) for j in jcts]
    d_totl = [delay_map.get(j, {}).get("total", 0.0) for j in jcts]

    # EARLY_RED data per intersection
    er_count = [er_map.get(j, {}).get("count", 0) for j in jcts]
    er_avg_cut = [
        er_map.get(j, {}).get("total_cut_s", 0.0) / max(er_map.get(j, {}).get("count", 1), 1)
        if er_map.get(j, {}).get("count", 0) > 0 else 0.0
        for j in jcts
    ]

    if out_png is None:
        base_dir = os.path.dirname(wave_csv) or "."
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_png = os.path.join(base_dir, f"coord_shockwave_diagnostics_{stamp}.png")

    # Use 4 subplots when any EARLY_RED events were logged, 3 otherwise.
    _has_er = any(c > 0 for c in er_count)
    n_panels = 4 if _has_er else 3
    fig, axes = plt.subplots(n_panels, 1, figsize=(15, 4 * n_panels), sharex=True)

    w = 0.26
    axes[0].bar([i - w for i in x], q_len, width=w, color="#1f77b4", label="Avg queue (veh)")
    axes[0].bar(x, q_clr, width=w, color="#ff7f0e", label="Avg queue-clearance (s)")
    axes[0].bar([i + w for i in x], w_del, width=w, color="#2ca02c", label="Avg wave-delay (s)")
    axes[0].set_ylabel("Shockwave inputs")
    axes[0].grid(True, axis="y", alpha=0.25)
    axes[0].legend(loc="upper left", fontsize=9)

    axes[1].bar([i - w for i in x], e_del, width=w, color="#9467bd", label="Avg ETA delta (s)")
    axes[1].bar(x, sigm, width=w, color="#8c564b", label="Avg sigma (s)")
    axes[1].bar([i + w for i in x], w4ms, width=w, color="#17becf", label="Avg w4 (m/s)")
    axes[1].plot(x, e_fin, color="#d62728", linewidth=1.6, marker="o", label="Avg ETA final (s)")
    axes[1].set_ylabel("Prediction/result")
    axes[1].grid(True, axis="y", alpha=0.25)
    axes[1].legend(loc="upper left", fontsize=9)

    axes[2].bar([i - w for i in x], d_main, width=w, color="#4daf4a", label="Main delay (pax·h/h)")
    axes[2].bar(x, d_side, width=w, color="#377eb8", label="Side delay (pax·h/h)")
    axes[2].bar([i + w for i in x], d_totl, width=w, color="#e41a1c", label="Total delay (pax·h/h)")
    axes[2].set_ylabel("Passenger delay")
    axes[2].grid(True, axis="y", alpha=0.25)
    axes[2].legend(loc="upper left", fontsize=9)

    if _has_er:
        # Panel 4: EARLY_RED action count (bars, left axis) + avg cut s (line, right axis).
        _ax_er = axes[3]
        _ax_er_r = _ax_er.twinx()
        _er_col  = "#b05000"   # orange-brown for early-red actions
        _cut_col = "#e07000"   # lighter orange for avg cut
        _ax_er.bar(x, er_count, width=0.45, color=_er_col, alpha=0.75,
                   label="EARLY_RED count")
        _ax_er_r.plot(x, er_avg_cut, color=_cut_col, linewidth=2.0, marker="^",
                      linestyle="--", label="Avg cut (s)")
        _ax_er.set_ylabel("EARLY_RED actions (count)", color=_er_col)
        _ax_er_r.set_ylabel("Avg cut duration (s)", color=_cut_col)
        _ax_er.tick_params(axis="y", labelcolor=_er_col)
        _ax_er_r.tick_params(axis="y", labelcolor=_cut_col)
        _ax_er.grid(True, axis="y", alpha=0.20)
        # Combined legend
        _h1, _l1 = _ax_er.get_legend_handles_labels()
        _h2, _l2 = _ax_er_r.get_legend_handles_labels()
        _ax_er.legend(_h1 + _h2, _l1 + _l2, loc="upper left", fontsize=9)
        _ax_er.set_ylabel("EARLY_RED count")
        # Annotate count above each bar
        for i, (cnt, avg_c) in enumerate(zip(er_count, er_avg_cut)):
            if cnt > 0:
                _ax_er.text(i, cnt * 1.04, f"n={cnt}\n{avg_c:.1f}s",
                            ha="center", va="bottom", fontsize=8, color=_er_col)
        # x-axis label goes on the bottom panel
        _ax_er.set_xlabel("Target intersection")
        _ax_er.set_xticks(x)
        _ax_er.set_xticklabels([str(j) for j in jcts], rotation=35, ha="right")
        axes[2].set_xlabel("")  # clear xlabel from delay panel
    else:
        axes[2].set_xlabel("Target intersection")

    axes[2].set_xticks(x)
    axes[2].set_xticklabels([str(j) for j in jcts], rotation=35, ha="right")

    for i, j in enumerate(jcts):
        n = int(agg[j].get("n_events", 0) or 0)
        axes[0].text(i, max(q_len[i], q_clr[i], w_del[i]) * 1.02 + 0.05, f"n={n}",
                     ha="center", va="bottom", fontsize=8)

    fig.suptitle(
        "Coordination Diagnostics by Intersection\n"
        "Shockwave/Kalman queue-stage averages + per-intersection main/side delay"
        + (" + EARLY_RED grants" if _has_er else ""),
        fontsize=12,
        fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out_png, dpi=160)
    plt.close(fig)

    print(f"[COORD DIAG] Plot written: {out_png}")
    print(f"[COORD DIAG] Wave CSV: {wave_csv}")
    if per_inter_csv:
        print(f"[COORD DIAG] Delay CSV: {per_inter_csv}")
    if tsp_log:
        print(f"[COORD DIAG] TSP Log: {tsp_log}")
        if _has_er:
            total_er = sum(er_count)
            print(f"[COORD DIAG] EARLY_RED events: {total_er} across {sum(1 for c in er_count if c > 0)} intersections")
    return out_png


if __name__ == "__main__":
    _wave = sys.argv[1] if len(sys.argv) > 1 else None
    _peri = sys.argv[2] if len(sys.argv) > 2 else None
    _out = sys.argv[3] if len(sys.argv) > 3 else None
    _tsp = sys.argv[4] if len(sys.argv) > 4 else None
    run(_wave, _peri, _out, _tsp)
