"""
plot_centralized_coordination.py
=================================
Reads the centralized_steps_*.csv log produced by intersection_controller.py
and generates a two-panel figure:

  Panel 1 — Phase-signal Gantt
    One horizontal row per junction (ordered by corridor position).
    The active phase is a filled band, coloured by phase index.
    Bus-priority phases are hatched.  TRANSITION and RELEASE_BP actions
    are marked with vertical tick-marks on each row.

  Panel 2 — Reward traces
    One subplot per junction.  R_HOLD (blue) and R_TRANSITION (red) as
    time series.  The region where R_TRANSITION > R_HOLD is shaded red
    (favours transition); when the controller actually fires TRANSITION
    a star marker appears.  Bus ETA bars are shown on the x-axis.

Data source
-----------
When CENTRALIZED_MODE=True the CSV is written by _centralized_corridor_step()
— one row per junction per CENTRALIZED_INTERVAL_S call with fresh GPS data.
When CENTRALIZED_MODE=False the CSV is written by the passive sampler
(_centralized_step_log_only) every PHASE_REWARD_LOG_INTERVAL_S seconds;
action_chosen will be "OBSERVE" throughout.

Usage
-----
  python plot_centralized_coordination.py                     # latest CSV
  python plot_centralized_coordination.py path/to/steps.csv  # explicit
  python plot_centralized_coordination.py --out fig.png       # custom output
  python plot_centralized_coordination.py --t_start 3600 --t_end 7200

The script is standalone — no Aimsun libraries required.
"""

import argparse
import csv
import glob
import math
import os
import sys
from collections import defaultdict, OrderedDict

# ---------------------------------------------------------------------------
# Matplotlib bootstrap (matches other repo plot scripts)
# ---------------------------------------------------------------------------
_AIMSUN_PKG = r"C:\AimsunPackages"
if _AIMSUN_PKG not in sys.path:
    sys.path.insert(0, _AIMSUN_PKG)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def _f(v, default=float("nan")):
    try:
        s = str(v).strip()
        return float(s) if s else default
    except Exception:
        return default


def _i(v, default=-1):
    try:
        s = str(v).strip()
        return int(float(s)) if s else default
    except Exception:
        return default


def _latest_csv():
    patterns = [
        os.path.join(LOG_DIR, "centralized_steps_*.csv"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "centralized_steps_*.csv"),
    ]
    best, best_mt = None, -1.0
    for pat in patterns:
        for p in glob.glob(pat):
            if not os.path.isfile(p):
                continue
            mt = os.path.getmtime(p)
            if mt > best_mt:
                best_mt, best = mt, p
    return best


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_csv(path: str):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.append({
                "t":        _f(r.get("sim_time_s")),
                "jct":      _i(r.get("junction_id")),
                "phase":    _i(r.get("current_phase")),
                "n_phases": _i(r.get("n_phases"), 1),
                "is_bus":   _i(r.get("is_bus_phase"), 0),
                "elapsed":  _f(r.get("elapsed_s"), 0.0),
                "cycle":    _f(r.get("cycle_s"), 135.0),
                "n_buses":  _i(r.get("n_buses"), 0),
                "min_eta":  _f(r.get("min_eta_s")),
                "r_hold":   _f(r.get("r_hold"), 0.0),
                "r_trans":  _f(r.get("r_transition"), 0.0),
                "action":   str(r.get("action_chosen", "")).strip(),
            })
    rows = [r for r in rows if not math.isnan(r["t"]) and r["jct"] > 0]
    return rows


def by_junction(rows):
    d = defaultdict(list)
    for r in rows:
        d[r["jct"]].append(r)
    for v in d.values():
        v.sort(key=lambda x: x["t"])
    return d


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
_PHASE_COLS = [
    "#4393C3",   # P1 – blue
    "#F4A582",   # P2 – salmon
    "#74C476",   # P3 – green
    "#DFC27D",   # P4 – khaki
    "#9970AB",   # P5 – purple
    "#D6604D",   # P6 – brick
    "#74ADD1",   # P7 – light blue
    "#ABDDA4",   # P8 – light green
]
_BUS_HATCH   = "////"
_BUS_EDGE    = "#222222"
_TRANS_COL   = "#B2182B"
_RELEASE_COL = "#4DAF4A"


def _pcol(phase_idx):
    return _PHASE_COLS[(max(0, phase_idx) - 1) % len(_PHASE_COLS)]


# ---------------------------------------------------------------------------
# Panel 1 — Phase-signal Gantt
# ---------------------------------------------------------------------------
def plot_phase_gantt(ax, by_jct, jct_order, t_min, t_max):
    row_h = 0.78
    n = len(jct_order)

    for yi, jid in enumerate(jct_order):
        rows = by_jct.get(jid, [])
        if not rows:
            continue

        # Build phase segments
        segs = []
        seg_t0    = rows[0]["t"]
        seg_phase = rows[0]["phase"]
        seg_bus   = rows[0]["is_bus"]
        for r in rows[1:]:
            if r["phase"] != seg_phase:
                segs.append((seg_t0, r["t"], seg_phase, seg_bus))
                seg_t0, seg_phase, seg_bus = r["t"], r["phase"], r["is_bus"]
        segs.append((seg_t0, rows[-1]["t"], seg_phase, seg_bus))

        for (t0, t1, ph, is_bus) in segs:
            t0 = max(t0, t_min); t1 = min(t1, t_max)
            if t1 <= t0:
                continue
            col = _pcol(ph)
            rect = mpatches.FancyBboxPatch(
                (t0, yi - row_h / 2), t1 - t0, row_h,
                boxstyle="square,pad=0",
                facecolor=col,
                edgecolor="white", linewidth=0.3,
                alpha=0.88,
            )
            if is_bus:
                rect.set_hatch(_BUS_HATCH)
                rect.set_edgecolor(_BUS_EDGE)
                rect.set_linewidth(0.5)
            ax.add_patch(rect)
            w = t1 - t0
            span = t_max - t_min
            if w > span * 0.012:
                ax.text((t0 + t1) / 2, yi, f"P{ph}",
                        ha="center", va="center",
                        fontsize=5, color="white" if not is_bus else "#111111",
                        fontweight="bold", clip_on=True)

        # Mark TRANSITION / RELEASE_BP with vertical ticks
        for r in rows:
            if r["t"] < t_min or r["t"] > t_max:
                continue
            if r["action"] == "TRANSITION":
                ax.axvline(r["t"], ymin=(yi - row_h / 2 + 0.5) / n,
                           ymax=(yi + row_h / 2 + 0.5) / n,
                           color=_TRANS_COL, linewidth=1.1, zorder=5)
            elif r["action"] == "RELEASE_BP":
                ax.axvline(r["t"], ymin=(yi - row_h / 2 + 0.5) / n,
                           ymax=(yi + row_h / 2 + 0.5) / n,
                           color=_RELEASE_COL, linewidth=0.9,
                           linestyle="--", zorder=5)

    ax.set_xlim(t_min, t_max)
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_yticks(range(n))
    ax.set_yticklabels([str(j) for j in jct_order], fontsize=7)
    ax.set_ylabel("Junction ID\n(corridor order ↑)", fontsize=8)
    ax.set_xlabel("Simulation time (s)", fontsize=8)
    ax.set_title("Phase signal per junction  —  corridor coordination",
                 fontsize=9, fontweight="bold")
    ax.grid(axis="x", linestyle=":", linewidth=0.35, color="#aaaaaa", zorder=0)
    ax.set_axisbelow(True)

    # Legend
    all_phases = sorted({r["phase"] for rows in by_jct.values() for r in rows
                         if t_min <= r["t"] <= t_max})
    patches = [mpatches.Patch(fc=_pcol(p), ec="white", lw=0.4,
                              label=f"Phase {p}") for p in all_phases]
    patches.append(mpatches.Patch(fc="#888888", hatch=_BUS_HATCH,
                                  ec=_BUS_EDGE, lw=0.5, label="Bus-priority phase"))
    patches.append(mpatches.Patch(fc=_TRANS_COL, label="TRANSITION action"))
    patches.append(mpatches.Patch(fc=_RELEASE_COL, linestyle="--",
                                  label="RELEASE_BP"))
    ax.legend(handles=patches, loc="upper right", fontsize=5.5,
              ncol=min(5, len(patches)), framealpha=0.9, edgecolor="#cccccc")


# ---------------------------------------------------------------------------
# Panel 2 — Reward traces
# ---------------------------------------------------------------------------
def plot_rewards(ax_list, by_jct, jct_order, t_min, t_max):
    for ax, jid in zip(ax_list, jct_order):
        rows = [r for r in by_jct.get(jid, []) if t_min <= r["t"] <= t_max]
        if not rows:
            ax.set_visible(False)
            continue

        ts      = np.array([r["t"]       for r in rows])
        r_hold  = np.array([r["r_hold"]  for r in rows])
        r_trans = np.array([r["r_trans"] for r in rows])
        actions = [r["action"] for r in rows]
        n_buses = np.array([r["n_buses"] for r in rows])

        ax.axhline(0, color="#888888", lw=0.5, ls="--", zorder=0)

        ax.plot(ts, r_hold,  color="#2166AC", lw=0.9, label="R_HOLD",       zorder=2)
        ax.plot(ts, r_trans, color="#D6604D", lw=0.9, label="R_TRANSITION",  zorder=2)

        # Shade region where each reward dominates
        ax.fill_between(ts, r_hold, r_trans,
                        where=(r_hold >= r_trans), alpha=0.10,
                        color="#2166AC", label=None)
        ax.fill_between(ts, r_hold, r_trans,
                        where=(r_trans > r_hold),  alpha=0.15,
                        color="#D6604D", label=None)

        # TRANSITION stars
        t_mask = np.array([a == "TRANSITION" for a in actions])
        if t_mask.any():
            ax.scatter(ts[t_mask], r_trans[t_mask],
                       marker="*", s=35, color=_TRANS_COL,
                       zorder=6, label="TRANSITION taken")

        # RELEASE_BP triangles
        rb_mask = np.array([a == "RELEASE_BP" for a in actions])
        if rb_mask.any():
            ax.scatter(ts[rb_mask], r_hold[rb_mask],
                       marker="^", s=20, color=_RELEASE_COL,
                       zorder=6, label="RELEASE_BP")

        # Bus presence ticks at bottom
        b_mask = n_buses > 0
        if b_mask.any():
            ylim_lo = ax.get_ylim()[0]
            ax.scatter(ts[b_mask],
                       np.full(b_mask.sum(), ax.get_ylim()[0]),
                       marker="|", s=8, color="#4DAF4A",
                       zorder=4, alpha=0.6, label="Bus in range")

        ax.set_xlim(t_min, t_max)
        ax.set_ylabel(f"Jct {jid}", fontsize=6.5)
        ax.tick_params(labelsize=6)
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))
        ax.grid(axis="x", linestyle=":", lw=0.35, color="#dddddd")

    if ax_list:
        h, l = ax_list[0].get_legend_handles_labels()
        ax_list[0].legend(h, l, loc="upper right", fontsize=5.5, framealpha=0.88)
        ax_list[0].set_title(
            "Rewards per junction: R_HOLD (blue) vs R_TRANSITION (red)",
            fontsize=9, fontweight="bold")
    if ax_list:
        ax_list[-1].set_xlabel("Simulation time (s)", fontsize=8)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Phase-signal Gantt + reward traces from centralized_steps CSV"
    )
    ap.add_argument("csv_path", nargs="?", default=None)
    ap.add_argument("--out",     default=None,
                    help="Output PNG path (default: same dir as CSV)")
    ap.add_argument("--t_start", type=float, default=None,
                    help="Clip to start at this sim time (s)")
    ap.add_argument("--t_end",   type=float, default=None,
                    help="Clip to end at this sim time (s)")
    args = ap.parse_args()

    csv_path = args.csv_path or _latest_csv()
    if csv_path is None or not os.path.isfile(csv_path):
        print("ERROR: no centralized_steps_*.csv found.\n"
              f"Searched: {LOG_DIR}\n"
              "Run Aimsun with PHASE_REWARD_LOG_INTERVAL_S > 0 (passive mode)\n"
              "or CENTRALIZED_MODE = True (active corridor controller).")
        sys.exit(1)

    print(f"Loading: {csv_path}")
    rows = load_csv(csv_path)
    if not rows:
        print("ERROR: CSV is empty.")
        sys.exit(1)

    bj        = by_junction(rows)
    all_t     = [r["t"] for r in rows]
    t_min     = args.t_start if args.t_start is not None else min(all_t)
    t_max     = args.t_end   if args.t_end   is not None else max(all_t)

    # Order junctions by first-seen sim time (proxy for corridor order)
    jct_first = {jid: min(r["t"] for r in bj[jid]) for jid in bj}
    jct_order = sorted(bj.keys(), key=lambda j: jct_first[j])

    n = len(jct_order)
    print(f"Junctions ({n}): {jct_order}")
    print(f"Time window: {t_min:.0f}s – {t_max:.0f}s "
          f"({(t_max-t_min)/3600:.2f} h)")
    print(f"Rows: {len(rows)}")

    # Check whether this is a CENTRALIZED_MODE run or passive-observer run
    actions_seen = {r["action"] for r in rows}
    is_passive   = actions_seen <= {"OBSERVE"}
    if is_passive:
        print("Note: all actions are OBSERVE — passive mode log "
              "(CENTRALIZED_MODE was False during this run).")

    # ── Layout ────────────────────────────────────────────────────────────────
    gantt_rows = max(2.5, n * 0.5)
    fig, axes = plt.subplots(
        nrows=1 + n, ncols=1,
        figsize=(15, gantt_rows + n * 1.5),
        gridspec_kw={"height_ratios": [gantt_rows] + [1.0] * n},
    )
    fig.subplots_adjust(hspace=0.40, left=0.09, right=0.97,
                        top=0.94, bottom=0.06)

    ax_gantt   = axes[0]
    ax_rewards = list(axes[1:])

    plot_phase_gantt(ax_gantt, bj, jct_order, t_min, t_max)
    plot_rewards(ax_rewards, bj, jct_order, t_min, t_max)

    mode_label = ("CENTRALIZED_MODE=True (GPS/AVL joint optimization)"
                  if not is_passive
                  else "Passive observer (CENTRALIZED_MODE=False)")
    fig.suptitle(
        f"Corridor coordination — {mode_label}\n{os.path.basename(csv_path)}",
        fontsize=8.5, y=0.988,
    )

    out_path = args.out or (os.path.splitext(csv_path)[0] + "_coordination_plot.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
