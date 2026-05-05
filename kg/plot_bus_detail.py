"""
plot_bus_detail.py
==================
Per-bus detailed time-space plot for the Logan Road TSP corridor.

For EACH qualifying TSP bus a separate PNG is produced showing:
  • The full trajectory through all corridor junctions it visited
  • Signal phase bands at every junction
  • Colour-coded stop-line arrival outcome (green / orange=coord / red=missed)
  • For EVERY missed green: a diagnostic annotation explaining WHY
    the bus did not receive a green phase at that junction.

Missed-green reasons (derived from available data):
  ① NOT_DETECTED      — bus not in detection zone when phase-check ran
  ② ETA_TOO_LATE      — bus was already too close (< eta_min_s) when detected
  ③ ETA_TOO_FAR       — bus too far away (> eta_max_s) — TSP window not yet open
  ④ COOLDOWN          — junction was in TSP cooldown from a prior grant
  ⑤ WAVE_BANNED       — wave-ban active; junction waiting for coord pre-arm
  ⑥ PREARM_ETA_ERROR  — coordinator fired pre-arm but bus arrived before green
                          started (ETA prediction was optimistic)
  ⑦ NO_COORD          — COORDINATED_TSP=False; no downstream pre-arm possible
  ⑧ PHASE_MISMATCH    — independent TSP fired but different phase was served
  ⑨ UNKNOWN           — insufficient data to diagnose

Usage
-----
  Standalone:
      python plot_bus_detail.py [detection_csv] [junction_csv] [out_dir]

  From AAPIFinish (intersection_controller.py):
      from plot_bus_detail import run as bus_detail_run
      bus_detail_run()
"""

import os
import sys
import csv
import glob
import math
import textwrap

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# Add Aimsun packages path before importing matplotlib
_AIMSUN_PACKAGES = r"C:\AimsunPackages"
if os.path.isdir(_AIMSUN_PACKAGES) and _AIMSUN_PACKAGES not in sys.path:
    sys.path.insert(0, _AIMSUN_PACKAGES)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe

try:
    from intersection_configs import INTERSECTIONS_CONFIG
except ImportError:
    INTERSECTIONS_CONFIG = {}

try:
    from plot_green_wave import (
        _load_detections, _load_junctions, _junctions_from_detections,
        _find_tsp_vehicles, _phase_at_stopline, _geographic_junction_order,
        _equal_spacing, _signal_windows, ALL_CORRIDOR_JCTS,
        JUNCTION_SPACING_M, FREE_FLOW_MS, _COORD_TIERS,
    )
except ImportError as e:
    raise SystemExit(f"Cannot import plot_green_wave helpers: {e}")


# =============================================================================
# Missed-green diagnosis
# =============================================================================

# Cycle lengths keyed by junction id
def _cycle(jct_id):
    cfg = INTERSECTIONS_CONFIG.get(jct_id, {})
    durs = cfg.get("GreenPhaseDuration", [])
    return sum(durs) if durs else 0.0

def _bus_phase_window(jct_id):
    """Return (green_start_in_cycle, green_dur) for the bus-compatible phase."""
    cfg      = INTERSECTIONS_CONFIG.get(jct_id, {})
    durs     = cfg.get("GreenPhaseDuration", [])
    bus_idx  = max(0, int(cfg.get("BusPhase", 1) or 1) - 1)
    if not durs or bus_idx >= len(durs):
        return 0.0, 0.0
    acc = sum(durs[:bus_idx])
    return acc, durs[bus_idx]


def _diagnose_miss(row: dict, all_rows: list, vid: int) -> str:
    """
    Return a short human-readable reason string explaining why this bus
    did not pass through jct `row['jct']` on a green phase.
    """
    jct_id  = row["jct"]
    t       = row["t"]
    tier    = row.get("tier", "")
    sp      = row.get("signal_phase", -1)
    bp      = row.get("bus_phase",    -1)
    cfg     = INTERSECTIONS_CONFIG.get(jct_id, {})
    cycle   = _cycle(jct_id)

    # ── Was this a coord-prearm that still arrived red? ────────────────────
    if any(tier.startswith(p) for p in _COORD_TIERS):
        # Pre-arm fired but outcome was red → ETA prediction error
        green_start, green_dur = _bus_phase_window(jct_id)
        if cycle > 0 and sp > 0:
            t_in_cycle   = t % cycle
            wait_for_green = (green_start - t_in_cycle) % cycle
            return (f"⑥ PREARM_ETA_ERROR — coordinator pre-armed this junction "
                    f"but bus arrived {wait_for_green:.0f}s before bus-phase started "
                    f"(prediction was ~{wait_for_green:.0f}s too optimistic). "
                    f"Try increasing PRE_GREEN_LEAD_S or improving Kalman speed estimate.")
        return "⑥ PREARM_ETA_ERROR — coordinator fired pre-arm but bus still hit red."

    # ── Did the bus get detected at ALL? ──────────────────────────────────
    # If signal_phase == -1 the detection had no phase data — likely Tier-3 fallback
    if sp < 0:
        det_dist = (cfg.get("DetDistance") or [[50]])[0]
        det_dist = det_dist[0] if det_dist else 50
        eta_min  = float(cfg.get("eta_min_s", 5) or 5)
        eta_max  = float(cfg.get("eta_max_s", 45) or 45)
        approx_eta = det_dist / FREE_FLOW_MS
        if approx_eta < eta_min:
            return (f"② ETA_TOO_LATE — at {det_dist:.0f} m upstream the bus ETA "
                    f"({approx_eta:.0f} s) was < eta_min ({eta_min:.0f} s). "
                    "Reduce eta_min_s or move detector further upstream.")
        if approx_eta > eta_max:
            return (f"③ ETA_TOO_FAR — at {det_dist:.0f} m the ETA ({approx_eta:.0f} s) "
                    f"exceeded eta_max ({eta_max:.0f} s). "
                    "Increase eta_max_s or move detector closer.")
        return "① NOT_DETECTED — no signal-phase data recorded; bus may have missed the detection zone."

    # ── Bus was detected; phase was wrong ─────────────────────────────────
    if cycle > 0:
        green_start, green_dur = _bus_phase_window(jct_id)
        t_in_cycle  = t % cycle
        # How long until next green phase starts?
        wait = (green_start - t_in_cycle) % cycle
        # How far through the current red was the bus?
        red_elapsed = t_in_cycle - green_start if t_in_cycle > green_start + green_dur else \
                      t_in_cycle + (cycle - green_start - green_dur)

        # Was any coord-prearm fired for this bus at this junction?
        prearm_events = [r for r in all_rows
                         if r["vid"] == vid and r["jct"] == jct_id
                         and any(r.get("tier","").startswith(p) for p in _COORD_TIERS)]

        if not prearm_events:
            # Check if this looks like a cooldown situation
            # (prior TSP event at same or nearby junction very recently)
            prior = [r for r in all_rows
                     if r["vid"] != vid and r["jct"] == jct_id
                     and r["t"] < t and t - r["t"] < 60]
            if prior:
                last_prior = max(prior, key=lambda r: r["t"])
                gap = t - last_prior["t"]
                return (f"④ COOLDOWN — junction served bus {last_prior['vid']} "
                        f"{gap:.0f} s before this bus arrived. "
                        f"TSP cooldown ({gap:.0f} s) blocked re-grant. "
                        "Consider reducing tsp_cycle_cooldown in config.")

            return (f"⑦ NO_COORD — bus reached jct {jct_id} "
                    f"{wait:.0f} s before the bus-phase window (phase 1 lasts {green_dur:.0f} s, "
                    f"cycle = {cycle:.0f} s). No coordinator pre-arm was fired here — "
                    "either COORDINATED_TSP=False or bus was not granted priority at the "
                    "preceding junction to trigger the wave.")

        return (f"⑧ PHASE_MISMATCH — pre-arm WAS fired for this bus but the junction "
                f"was at phase {sp} when it needed phase {bp if bp > 0 else 'N/A (bus phase)'}. "
                f"Phase had {wait:.0f} s until next green window. "
                "Increase PRE_GREEN_LEAD_S to give junction more time to cycle.")

    return "⑨ UNKNOWN — insufficient configuration data to diagnose."


# =============================================================================
# Individual bus plot
# =============================================================================

def _annotation_color(reason: str) -> str:
    if reason.startswith("①") or reason.startswith("⑦"):
        return "#ff8800"   # amber — no detection / no coord
    if reason.startswith("②") or reason.startswith("③"):
        return "#ff4444"   # red — detection window mismatch
    if reason.startswith("④"):
        return "#cc44cc"   # purple — cooldown
    if reason.startswith("⑤"):
        return "#4488ff"   # blue — wave ban
    if reason.startswith("⑥") or reason.startswith("⑧"):
        return "#ff6600"   # orange — ETA / timing error
    return "#aaaaaa"


def plot_bus(vid: int, vid_rows: list, all_rows: list,
             ordered_jcts: list, plot_pos: dict,
             t_global_min: float, t_global_max: float,
             out_path: str) -> None:
    """
    Draw a single-bus time-space diagram with missed-green annotations.
    """
    if not vid_rows:
        return

    vid_rows = sorted(vid_rows, key=lambda r: r["t"])

    fig, ax = plt.subplots(figsize=(20, 10))
    fig.patch.set_facecolor("#0e0e20")
    ax.set_facecolor("#14142a")

    t_min = max(0, min(r["t"] for r in vid_rows) - 120)
    t_max = max(r["t"] for r in vid_rows) + 120
    t_pad = 60.0

    y_min = min(plot_pos.values())
    y_max = max(plot_pos.values())
    bar_h = JUNCTION_SPACING_M * 0.28

    # ── Signal phase bands ────────────────────────────────────────────────────
    for jct_id in ordered_jcts:
        if jct_id not in plot_pos:
            continue
        y = plot_pos[jct_id]
        for t_on, t_off, state in _signal_windows(jct_id, t_min - 60, t_max + 60):
            col   = "#00c853" if state == "green" else "#c62828"
            alpha = 0.35     if state == "green" else 0.18
            ax.barh(y, t_off - t_on, left=t_on, height=bar_h * 2,
                    color=col, alpha=alpha, zorder=1, linewidth=0)
        ax.axhline(y, color="#1e1e44", lw=0.8, alpha=0.7, zorder=0)
        cfg    = INTERSECTIONS_CONFIG.get(jct_id, {})
        cycle  = _cycle(jct_id)
        gstart, gdur = _bus_phase_window(jct_id)
        label = (f"jct {jct_id}\n"
                 f"cycle={cycle:.0f}s  green={gdur:.0f}s")
        ax.text(t_min - t_pad * 0.4, y, label,
                va="center", ha="right", fontsize=7,
                color="#9090cc", fontweight="bold", clip_on=False)

    # ── Ideal wave reference ───────────────────────────────────────────────────
    if len(ordered_jcts) >= 2 and all(j in plot_pos for j in ordered_jcts):
        y_first = plot_pos[ordered_jcts[0]]
        y_last  = plot_pos[ordered_jcts[-1]]
        travel  = (y_last - y_first) / FREE_FLOW_MS
        for t_on, _, state in _signal_windows(ordered_jcts[0], t_min, t_max):
            if state != "green":
                continue
            ax.plot([t_on, t_on + travel], [y_first, y_last],
                    "--", color="#ffeb3b", alpha=0.18, lw=1.2, zorder=2)

    # ── Trajectory line ───────────────────────────────────────────────────────
    pts_t = [r["t"]              for r in vid_rows if r["jct"] in plot_pos]
    pts_y = [plot_pos[r["jct"]] for r in vid_rows if r["jct"] in plot_pos]
    if len(pts_t) > 1:
        ax.plot(pts_t, pts_y, "-", color="#29b6f6", lw=2.5, alpha=0.85,
                zorder=4, solid_capstyle="round",
                path_effects=[pe.withStroke(linewidth=4, foreground="#001e30")])

    # ── Detection markers and missed-green annotations ────────────────────────
    annotation_y_offsets: dict = {}   # {jct_id: used_y_offset} to avoid overlap

    for r in vid_rows:
        if r["jct"] not in plot_pos:
            continue
        phase = _phase_at_stopline(r)
        y     = plot_pos[r["jct"]]

        if phase == "green":
            mk, fc, ec, ms = "o", "#69f0ae", "#ffffff", 12
        elif phase == "orange":
            mk, fc, ec, ms = "^", "#ffb300", "#ffffff", 12
        else:   # red
            mk, fc, ec, ms = "X", "#ff5252", "#ffffff", 13

        ax.plot(r["t"], y, mk, color=fc,
                markeredgecolor=ec, markeredgewidth=1.0,
                markersize=ms, zorder=7,
                path_effects=[pe.withStroke(linewidth=2, foreground="#000020")])

        # Missed-green annotation
        if phase not in ("green", "orange"):
            reason = _diagnose_miss(r, all_rows, vid)
            col    = _annotation_color(reason)

            # Stagger annotations vertically if same junction appears twice
            base_off = annotation_y_offsets.get(r["jct"], 0)
            annotation_y_offsets[r["jct"]] = base_off + JUNCTION_SPACING_M * 0.18

            wrapped = "\n".join(textwrap.wrap(reason, width=62))

            # Arrow from detection point to text box
            text_y = y + JUNCTION_SPACING_M * 0.42 + base_off
            ax.annotate(
                wrapped,
                xy=(r["t"], y),
                xytext=(r["t"] + 30, text_y),
                fontsize=6.8,
                color=col,
                arrowprops=dict(arrowstyle="->", color=col, lw=1.2,
                                connectionstyle="arc3,rad=-0.2"),
                bbox=dict(boxstyle="round,pad=0.35", fc="#0a0a1e",
                          ec=col, lw=1.0, alpha=0.88),
                zorder=10,
                clip_on=True,
            )

    # ── Axes ──────────────────────────────────────────────────────────────────
    ax.set_xlim(t_min - t_pad, t_max + t_pad)
    y_margin = JUNCTION_SPACING_M * 0.55
    ax.set_ylim(y_min - y_margin, y_max + y_margin + JUNCTION_SPACING_M * 0.5)

    ax.set_yticks([plot_pos[j] for j in ordered_jcts if j in plot_pos])
    ax.set_yticklabels([f"jct {j}" for j in ordered_jcts if j in plot_pos],
                       fontsize=8, color="#9090cc")
    ax.set_xlabel("Simulation time (s)", fontsize=11, color="#ccccee", labelpad=8)
    ax.set_ylabel("Corridor (South → North)", fontsize=11, color="#ccccee", labelpad=8)

    jcts_visited = sorted(set(r["jct"] for r in vid_rows if r["jct"] in plot_pos))
    phases_all   = [_phase_at_stopline(r) for r in vid_rows if r["jct"] in plot_pos]
    n_green  = sum(1 for p in phases_all if p in ("green","orange"))
    n_total  = len(phases_all)
    pct      = 100 * n_green / n_total if n_total else 0
    has_coord = any(r.get("tier","").startswith(_COORD_TIERS[0]) for r in vid_rows)

    ax.set_title(
        f"Bus {vid}  —  {n_green}/{n_total} junctions on green ({pct:.0f}%)  "
        f"|  {'Corridor-coordinated' if has_coord else 'Independent TSP only'}  "
        f"|  {len(jcts_visited)} junctions visited",
        fontsize=12, color="#e8e8ff", pad=12,
    )

    ax.tick_params(colors="#9090cc", labelsize=8.5)
    for sp in ax.spines.values():
        sp.set_color("#1e1e44")
    ax.grid(axis="x", color="#1e1e40", lw=0.5, alpha=0.6, zorder=0)

    # ── Legend ────────────────────────────────────────────────────────────────
    legend_handles = [
        plt.Line2D([0],[0], marker="o", color="w",
                   markerfacecolor="#69f0ae", ms=10, label="● Green on arrival"),
        plt.Line2D([0],[0], marker="^", color="w",
                   markerfacecolor="#ffb300", ms=10, label="▲ Coord pre-arm (arrives green)"),
        plt.Line2D([0],[0], marker="X", color="w",
                   markerfacecolor="#ff5252", ms=11, label="✕ Missed green (see annotations)"),
        plt.Line2D([0],[0], linestyle="--", color="#ffeb3b", alpha=0.55, lw=1.5,
                   label=f"Ideal wave @ {FREE_FLOW_MS*3.6:.0f} km/h"),
        mpatches.Patch(color="#00c853", alpha=0.5, label="Bus-compatible phase (green)"),
        mpatches.Patch(color="#c62828", alpha=0.35, label="Other phases (red)"),
    ]
    ax.legend(handles=legend_handles, loc="lower right", fontsize=7.5,
              framealpha=0.88, facecolor="#0a0a1e",
              labelcolor="#ccccee", edgecolor="#2a2a50")

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[bus_detail] Bus {vid}: saved {out_path}")


# =============================================================================
# Entry point
# =============================================================================

def _find_latest(log_dir: str, pattern: str):
    files = sorted(glob.glob(os.path.join(log_dir, pattern)))
    return files[-1] if files else None


def run(csv_path: str = None, junc_csv: str = None,
        out_dir: str = None) -> list:
    """
    Generate per-bus detail plots for all TSP-qualified buses.
    Returns list of output PNG paths.
    """
    log_dir = os.path.join(_SCRIPT_DIR, "logs")

    if csv_path is None:
        csv_path = _find_latest(log_dir, "detection_points_*.csv")
    if csv_path is None:
        print("[bus_detail] No detection_points CSV found in", log_dir)
        return []

    rows = _load_detections(csv_path)
    if not rows:
        print(f"[bus_detail] CSV empty or unreadable: {csv_path}")
        return []

    if junc_csv is None:
        stem      = os.path.basename(csv_path)
        ts        = stem.replace("detection_points_", "").replace(".csv", "")
        candidate = os.path.join(log_dir, f"junction_centroids_{ts}.csv")
        junc_csv  = candidate if os.path.isfile(candidate) else \
                    _find_latest(log_dir, "junction_centroids_*.csv")

    junctions = _load_junctions(junc_csv)
    if not junctions:
        junctions = _junctions_from_detections(rows)

    tsp_vids  = _find_tsp_vehicles(rows)
    all_jcts  = list(ALL_CORRIDOR_JCTS | set(r["jct"] for r in rows))
    ordered   = _geographic_junction_order(junctions, all_jcts)
    plot_pos  = _equal_spacing(ordered)

    t_global_min = min(r["t"] for r in rows)
    t_global_max = max(r["t"] for r in rows)

    if out_dir is None:
        stem    = os.path.splitext(csv_path)[0]
        out_dir = stem + "_bus_detail"
    os.makedirs(out_dir, exist_ok=True)

    out_paths = []
    for vid in sorted(tsp_vids):
        vid_rows = [r for r in rows if r["vid"] == vid]
        out_png  = os.path.join(out_dir, f"bus_{vid}_green_wave.png")
        plot_bus(vid, vid_rows, rows, ordered, plot_pos,
                 t_global_min, t_global_max, out_png)
        out_paths.append(out_png)

    print(f"[bus_detail] {len(out_paths)} bus plot(s) → {out_dir}")
    return out_paths


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="Per-bus green-wave detail plots with missed-green diagnostics")
    ap.add_argument("csv_path", nargs="?")
    ap.add_argument("junc_csv", nargs="?")
    ap.add_argument("out_dir",  nargs="?")
    args = ap.parse_args()
    run(args.csv_path, args.junc_csv, args.out_dir)
