"""
plot_green_wave.py
==================
Dashboard-style time-space diagram for Logan Road bus TSP simulation.

Panels
------
  TOP    : Time-space diagram (one row per corridor junction, Y = geographic order)
  BOTTOM : Per-junction green-pass rate + per-bus summary statistics

Key design decisions
--------------------
â€¢ Only TSP-prioritised buses are shown.  A bus qualifies if it:
    (a) has a coord-prearm event (explicitly wave-coordinated), OR
    (b) was detected at â‰¥ 2 unique corridor junctions (traversed the corridor).
  Side-street buses detected at only one junction are filtered out.

â€¢ Junctions are ordered by their geographic Y coordinate (north at top), NOT
  by the INTERSECTIONS_CONFIG insertion order.  This prevents the visual
  zig-zag that occurs when config order does not match geography.

â€¢ Equal Y-spacing (one slot per junction, constant spacing) avoids overlapping
  junction labels for closely-spaced intersections.

â€¢ An "ideal green-wave" reference line is drawn from every green-window start
  at the southernmost junction, showing the diagonal trajectory a perfectly
  coordinated bus should follow at free-flow speed (11 m/s â‰ˆ 40 km/h).

â€¢ Each trajectory segment between consecutive detection events is coloured
  by the bus's phase state AT STOP-LINE ARRIVAL (not at detection time):
    GREEN   â€“ bus arrived at stop line during its bus-compatible phase
    ORANGE  â€“ was in red when detected but TSP/coord pre-armed â†’ phase changed
    RED     â€“ arrived (or predicted to arrive) during red, no TSP action evident

Usage
-----
  Standalone:
      python plot_green_wave.py [detection_csv] [junction_csv] [out_png]

  From intersection_controller.py at AAPIFinish:
      from plot_green_wave import run as plot_run
      plot_run()
"""

import os
import sys
import csv
import glob
import math
import collections

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

_MPL_LOADED = False
plt = None
mpatches = None
gridspec = None
matplotlib = None  # Keep reference to matplotlib module for _get_cmap

def _ensure_mpl():
    global _MPL_LOADED, plt, mpatches, gridspec, matplotlib
    if _MPL_LOADED:
        return
    # Add Aimsun packages path before importing matplotlib
    import sys as _sys
    _aimsun_path = r"C:\AimsunPackages"
    if _aimsun_path not in _sys.path:
        _sys.path.insert(0, _aimsun_path)
    import matplotlib as _mpl
    _mpl.use("Agg")
    import matplotlib.pyplot as _plt
    import matplotlib.patches as _mp
    import matplotlib.gridspec as _gs
    plt = _plt
    mpatches = _mp
    gridspec = _gs
    matplotlib = _mpl
    _MPL_LOADED = True

try:
    from intersection_configs import INTERSECTIONS_CONFIG   # type: ignore[import]
except ImportError:
    INTERSECTIONS_CONFIG = {}

# â”€â”€ Corridor group definitions (mirrors intersection_controller.py) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
CORRIDOR_GROUPS = {
    "kg_corridor_a": [39606, 39590, 36393, 36385, 39593],
    "kg_corridor_b": [39576, 39578, 39587, 1043762, 39569, 39572, 38339],
}
# All corridor junction IDs in a flat set
ALL_CORRIDOR_JCTS = set(jid for ids in CORRIDOR_GROUPS.values() for jid in ids)

# Equal Y-spacing between junctions on the plot (metres, visual only)
JUNCTION_SPACING_M = 500.0
# Free-flow reference speed for the ideal-wave diagonal (m/s)
FREE_FLOW_MS = 11.0   # â‰ˆ 40 km/h

# Tier prefixes that confirm the bus was explicitly TSP-coordinated
_COORD_TIERS = ("coord-prearm",)


# =============================================================================
# Colour helper
# =============================================================================

def _get_cmap(name: str, n: int):
    try:
        return matplotlib.colormaps[name].resampled(max(n, 2))
    except (AttributeError, KeyError):
        pass
    try:
        return plt.cm.get_cmap(name, max(n, 2))
    except Exception:
        return plt.cm.get_cmap("tab10")


# =============================================================================
# Data loaders
# =============================================================================

def _load_detections(path: str) -> list:
    rows = []
    if not path or not os.path.isfile(path):
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                sp_raw = (row.get("signal_phase") or "-1").strip()
                bp_raw = (row.get("bus_phase")    or "-1").strip()
                rows.append({
                    "t":            float(row["sim_time_s"]),
                    "jct":          int(row["junction_id"]),
                    "vid":          int(row["veh_id"]),
                    "x":            float(row.get("x") or 0),
                    "y":            float(row.get("y") or 0),
                    "tier":         row.get("tier", "").strip(),
                    "signal_phase": int(sp_raw) if sp_raw.lstrip("-").isdigit() else -1,
                    "bus_phase":    int(bp_raw) if bp_raw.lstrip("-").isdigit() else -1,
                    "prearm_status": (row.get("prearm_status") or "").strip().lower(),
                    "prearm_eta_s":  float(row.get("prearm_eta_s") or 0.0),
                    "focus_role":    (row.get("focus_role") or "").strip(),
                })
            except (KeyError, ValueError):
                continue
    return rows


def _load_junctions(path: str) -> dict:
    junctions: dict = {}
    if not path or not os.path.isfile(path):
        return junctions
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                junctions[int(row["junction_id"])] = (
                    float(row["x"]), float(row["y"]))
            except (KeyError, ValueError):
                continue
    return junctions


def _junctions_from_detections(rows: list) -> dict:
    """
    Derive junction centroids from detection event positions.
    Detections occur upstream of the stop line but their mean position gives
    a reliable geographic ordering (same Y ordering, ~50â€“300 m offset).
    """
    sums: dict = {}
    counts: dict = {}
    for r in rows:
        x, y = r["x"], r["y"]
        if x == 0.0 and y == 0.0:
            continue
        jid = r["jct"]
        if jid not in sums:
            sums[jid]   = [0.0, 0.0]
            counts[jid] = 0
        sums[jid][0]   += x
        sums[jid][1]   += y
        counts[jid]    += 1
    return {
        jid: (sums[jid][0] / counts[jid], sums[jid][1] / counts[jid])
        for jid in sums if counts[jid] > 0
    }


# =============================================================================
# TSP bus filter
# =============================================================================

def _find_tsp_vehicles(rows: list) -> set:
    """
    Return the set of vehicle IDs that were TSP-prioritised.

    A vehicle qualifies if:
      (a) It has at least one coord-prearm detection event, OR
      (b) It was detected at 2 or more distinct CORRIDOR junctions.

    Buses seen at only one junction (side-street buses, non-corridor routes,
    or buses that did not receive corridor priority) are excluded so they do
    not bias the green-wave assessment.

    If no vehicles meet the criteria (e.g., a non-coordinated run with many
    single-junction detections), fall back to all vehicles seen at â‰¥ 2
    junctions of any type, and then to all vehicles.
    """
    # (a) explicitly wave-coordinated
    wave_vids: set = set()
    for r in rows:
        if any(r["tier"].startswith(p) for p in _COORD_TIERS):
            wave_vids.add(r["vid"])

    # (b) multi-corridor-junction traversal
    jct_sets: dict = {}
    for r in rows:
        if r["jct"] in ALL_CORRIDOR_JCTS:
            jct_sets.setdefault(r["vid"], set()).add(r["jct"])
    multi_jct = {vid for vid, s in jct_sets.items() if len(s) >= 2}

    tsp_vids = wave_vids | multi_jct
    if tsp_vids:
        return tsp_vids

    # Fallback: any bus seen at â‰¥ 2 junctions
    all_jct: dict = {}
    for r in rows:
        all_jct.setdefault(r["vid"], set()).add(r["jct"])
    fallback = {vid for vid, s in all_jct.items() if len(s) >= 2}
    if fallback:
        print("[plot_green_wave] No coord-prearm or multi-corridor buses â€” "
              "showing all multi-junction buses.")
        return fallback

    print("[plot_green_wave] WARNING: cannot identify TSP buses â€” showing all.")
    return set(r["vid"] for r in rows)


# =============================================================================
# Junction geographic ordering and equal spacing
# =============================================================================

def _geographic_junction_order(junctions: dict, candidate_ids: list) -> list:
    """
    Return candidate_ids sorted by geographic Y coordinate (north = large Y,
    placed at top of plot).  Junctions not in `junctions` are appended last
    in their original order.
    """
    with_y   = [(jid, junctions[jid][1]) for jid in candidate_ids if jid in junctions]
    without_y = [jid for jid in candidate_ids if jid not in junctions]
    # Sort south â†’ north (ascending Y) so index 0 = southernmost
    with_y.sort(key=lambda t: t[1])
    return [jid for jid, _ in with_y] + without_y


def _equal_spacing(ordered_jcts: list, spacing_m: float = JUNCTION_SPACING_M) -> dict:
    """
    Assign plot Y-positions with equal spacing.
    Index 0 (southernmost) â†’ y=0, index n-1 (northernmost) â†’ y=n*spacing.
    """
    return {jid: i * spacing_m for i, jid in enumerate(ordered_jcts)}


# =============================================================================
# Signal timing windows
# =============================================================================

def _signal_windows(jct_id: int, t_start: float, t_end: float) -> list:
    """
    Return [(t_on, t_off, 'green'|'red'), ...] covering [t_start, t_end].
    Cycle = sum(GreenPhaseDuration); bus-compatible phase = BusPhase.
    """
    cfg        = INTERSECTIONS_CONFIG.get(jct_id, {})
    green_durs = cfg.get("GreenPhaseDuration", [])
    bus_phase  = int(cfg.get("BusPhase", 1) or 1)

    if not green_durs:
        return []
    cycle = sum(green_durs)
    if cycle <= 0:
        return []

    phase_starts = []
    acc = 0.0
    for d in green_durs:
        phase_starts.append(acc)
        acc += d

    bus_idx = max(0, min(bus_phase - 1, len(green_durs) - 1))
    bus_green_start = phase_starts[bus_idx]
    bus_green_dur   = green_durs[bus_idx]

    windows = []
    cycle_start = math.floor(max(0.0, t_start) / cycle) * cycle
    while cycle_start < t_end:
        cycle_end = cycle_start + cycle
        green_on  = cycle_start + bus_green_start
        green_off = green_on + bus_green_dur

        if green_on > cycle_start:
            a, b = max(cycle_start, t_start), min(green_on, t_end)
            if b > a:
                windows.append((a, b, "red"))

        if green_on < t_end and green_off > t_start:
            a, b = max(green_on, t_start), min(green_off, t_end)
            if b > a:
                windows.append((a, b, "green"))

        if green_off < cycle_end:
            a, b = max(green_off, t_start), min(cycle_end, t_end)
            if b > a:
                windows.append((a, b, "red"))

        cycle_start = cycle_end
    return windows


# =============================================================================
# Phase assessment at stop line
# =============================================================================

def _phase_at_stopline(row: dict) -> str:
    """
    Estimate whether the bus arrived at the stop line in the green phase.

    Priority:
      1. Use recorded signal_phase / bus_phase columns if present.
      2. Estimate stop-line arrival time from detection time + det_dist/speed,
         then check against the planned cycle.

    Returns 'green', 'orange' (TSP coord-prearm â†’ should be green), or 'red'.
    """
    tier = row.get("tier", "")
    prearm_status = str(row.get("prearm_status", "") or "").lower()
    if prearm_status in ("fired", "queued"):
        return "prearm"
    if prearm_status == "missed":
        return "red"
    if prearm_status == "success":
        return "orange"
    if any(tier.startswith(p) for p in _COORD_TIERS):
        return "prearm"

    sp = row.get("signal_phase", -1)
    bp = row.get("bus_phase", -1)
    jct_id = row.get("jct", 0)
    cfg = INTERSECTIONS_CONFIG.get(jct_id, {})

    # Recorded phase columns take priority
    if sp > 0:
        bp_eff = bp if bp > 0 else int(cfg.get("BusPhase", -1) or -1)
        if bp_eff > 0:
            return "green" if sp == bp_eff else "red"

    # Fall back to planned cycle estimate
    green_durs = cfg.get("GreenPhaseDuration", [])
    bus_phase  = int(cfg.get("BusPhase", 1) or 1)
    if not green_durs:
        return "unknown"

    cycle = sum(green_durs)
    bus_idx = max(0, min(bus_phase - 1, len(green_durs) - 1))
    phase_starts = []
    acc = 0.0
    for d in green_durs:
        phase_starts.append(acc)
        acc += d

    green_start = phase_starts[bus_idx]
    green_dur   = green_durs[bus_idx]

    # Estimate stop-line arrival: detection_time + det_dist / bus_speed
    det_dists = cfg.get("DetDistance", [[50.0]])
    det_dist  = float(det_dists[0][0]) if (det_dists and det_dists[0]) else 50.0
    t_stopline = row["t"] + det_dist / FREE_FLOW_MS
    t_in_cycle = t_stopline % cycle

    if green_start <= t_in_cycle < green_start + green_dur:
        return "green"
    return "red"


# =============================================================================
# Main corridor time-space panel
# =============================================================================

def _draw_corridor_panel(ax, rows: list, tsp_vids: set,
                          ordered_jcts: list, plot_pos: dict,
                          t_min: float, t_max: float) -> dict:
    """
    Draw signal bands, bus trajectories, and ideal wave lines on `ax`.
    Returns per-junction stats: {jct_id: {"green": n, "red": n, "orange": n}}.
    """
    if not ordered_jcts:
        return {}

    t_pad  = max((t_max - t_min) * 0.05, 60.0)
    y_vals = list(plot_pos.values())
    y_min  = min(y_vals)
    y_max  = max(y_vals)
    bar_h  = JUNCTION_SPACING_M * 0.30   # height of signal band (visual)

    # â”€â”€ Signal timing bands â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    t_band_start = max(0.0, t_min - 180.0)
    t_band_end   = t_max + 180.0
    for jct_id in ordered_jcts:
        y = plot_pos[jct_id]
        for t_on, t_off, state in _signal_windows(jct_id, t_band_start, t_band_end):
            if state == "green":
                ax.barh(y, t_off - t_on, left=t_on, height=bar_h * 2,
                        color="#00c853", alpha=0.30, zorder=1, linewidth=0)
            else:
                ax.barh(y, t_off - t_on, left=t_on, height=bar_h * 2,
                        color="#d50000", alpha=0.15, zorder=1, linewidth=0)
        ax.axhline(y, color="#2a2a50", lw=0.6, alpha=0.5, zorder=0)
        # Junction label on left
        ax.text(t_min - t_pad * 0.5, y,
                f"jct {jct_id}",
                va="center", ha="right", fontsize=8.0,
                color="#aaaadd", fontweight="bold", clip_on=False)

    # â”€â”€ Ideal green-wave reference lines â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Draw from each green-window start at the southernmost junction upward
    # at FREE_FLOW_MS.  Clipped to the axis so they don't dominate.
    if len(ordered_jcts) >= 2:
        first_jct  = ordered_jcts[0]   # southernmost
        y_first    = plot_pos[first_jct]
        y_last     = plot_pos[ordered_jcts[-1]]
        travel_max = (y_last - y_first) / max(FREE_FLOW_MS, 1.0)
        for t_on, t_off, state in _signal_windows(
                first_jct, t_band_start, t_band_end):
            if state != "green":
                continue
            t_ideal_end = t_on + travel_max
            if t_ideal_end < t_min - t_pad or t_on > t_max + t_pad:
                continue
            ax.plot([t_on, t_ideal_end], [y_first, y_last],
                    "--", color="#ffea00", alpha=0.20, lw=1.0, zorder=2)

    # â”€â”€ Bus trajectories â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    tsp_rows  = [r for r in rows if r["vid"] in tsp_vids and r["jct"] in plot_pos]
    all_vids  = sorted(set(r["vid"] for r in tsp_rows))
    n_buses   = max(len(all_vids), 1)
    cmap      = _get_cmap("tab10", n_buses)

    phase_stats: dict = {jct: {"green": 0, "red": 0, "orange": 0}
                         for jct in ordered_jcts}

    for v_idx, vid in enumerate(all_vids):
        vcol  = cmap(v_idx / max(n_buses - 1, 1))
        vrows = sorted([r for r in tsp_rows if r["vid"] == vid],
                       key=lambda r: r["t"])

        # Draw trajectory through observed arrivals only. Pre-arm-fired rows are
        # request evidence at the target junction, not proof that the bus arrived.
        traj_rows = [r for r in vrows if _phase_at_stopline(r) != "prearm"]
        pts_t = [r["t"]              for r in traj_rows]
        pts_y = [plot_pos[r["jct"]] for r in traj_rows]
        if len(pts_t) > 1:
            ax.plot(pts_t, pts_y, "-", color=vcol, lw=1.8, alpha=0.55,
                    zorder=3, solid_capstyle="round")

        # Junction detection markers
        for i, r in enumerate(vrows):
            phase = _phase_at_stopline(r)
            # Collect stats per junction
            if r["jct"] in phase_stats and phase in ("green", "red", "orange"):
                phase_stats[r["jct"]][phase] += 1

            if phase == "green":
                mk, fc, ec, ms = "o", vcol, "#ffffff", 10
            elif phase == "orange":
                mk, fc, ec, ms = "^", "#ffaa00", "#ffffff", 10
            elif phase == "red":
                mk, fc, ec, ms = "X", "#ff3030", "#ffffff", 10
            elif phase == "prearm":
                mk, fc, ec, ms = "v", "#8e24aa", "#ffffff", 9
            else:
                mk, fc, ec, ms = "D", "#aaaaaa", "#ffffff", 8

            ax.plot(r["t"], plot_pos[r["jct"]], mk,
                    color=fc, markeredgecolor=ec, markeredgewidth=0.9,
                    markersize=ms, zorder=6,
                    label=f"Bus {vid}" if i == 0 else "")

    # â”€â”€ Axes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    ax.set_xlim(t_min - t_pad, t_max + t_pad)
    y_margin = JUNCTION_SPACING_M * 0.5
    ax.set_ylim(y_min - y_margin, y_max + y_margin)
    ax.set_ylabel("â† South   |   Corridor (Nâ†‘)   |   North â†’",
                  fontsize=9, color="#aaaadd", labelpad=10)
    ax.set_xlabel("Simulation time (s)", fontsize=10, color="#ccccee", labelpad=8)

    y_ticks   = [plot_pos[j] for j in ordered_jcts]
    y_labels  = [f"jct {j}" for j in ordered_jcts]
    ax.set_yticks(y_ticks)
    ax.set_yticklabels(y_labels, fontsize=7.5, color="#9090cc")

    ax.tick_params(colors="#9090cc", labelsize=8.0)
    for spine in ax.spines.values():
        spine.set_color("#2a2a50")
    ax.grid(axis="x", color="#2a2a44", lw=0.5, alpha=0.5, zorder=0)

    # â”€â”€ Legend â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    handles = [
        mpatches.Patch(color="#00c853", alpha=0.55,
                       label="Green phase (bus-compatible)"),
        mpatches.Patch(color="#d50000", alpha=0.35,
                       label="Red / other phase"),
        plt.Line2D([0],[0], marker="o", color="w", markerfacecolor="#66bb6a",
                   markersize=9, label="â— Green on arrival"),
        plt.Line2D([0],[0], marker="^", color="w", markerfacecolor="#ffaa00",
                   markersize=9, label="â–² Coord pre-arm (orange)"),
        plt.Line2D([0],[0], marker="v", color="w", markerfacecolor="#8e24aa",
                   markersize=9, label="Pre-arm fired/requested"),
        plt.Line2D([0],[0], marker="X", color="w", markerfacecolor="#ff3030",
                   markersize=9, label="âœ• Red on arrival"),
        plt.Line2D([0],[0], linestyle="--", color="#ffea00", alpha=0.55,
                   lw=1.5, label=f"Ideal wave ({FREE_FLOW_MS*3.6:.0f} km/h)"),
    ]
    for v_idx, vid in enumerate(all_vids):
        handles.append(plt.Line2D(
            [0],[0], color=cmap(v_idx / max(n_buses-1, 1)),
            lw=2, label=f"Bus {vid} (TSP)"))

    ax.legend(handles=handles, loc="upper right", fontsize=7.0,
              framealpha=0.85, facecolor="#11112a",
              labelcolor="#ccccee", edgecolor="#333355",
              ncol=2 if n_buses > 4 else 1)

    return phase_stats


# =============================================================================
# Statistics panel
# =============================================================================

def _draw_stats_panel(ax_left, ax_right,
                      rows: list, tsp_vids: set,
                      ordered_jcts: list, phase_stats: dict) -> None:
    """
    Left:  green-pass rate bar chart per junction (south â†’ north, bottomâ†’top).
    Right: per-bus corridor statistics (journey time, # junctions hit, green%).
    """
    # â”€â”€ Left: green pass rate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if ordered_jcts and phase_stats:
        labels   = [f"jct {j}" for j in ordered_jcts]
        greens   = [phase_stats.get(j, {}).get("green",  0) for j in ordered_jcts]
        oranges  = [phase_stats.get(j, {}).get("orange", 0) for j in ordered_jcts]
        reds     = [phase_stats.get(j, {}).get("red",    0) for j in ordered_jcts]
        totals   = [g + o + r for g, o, r in zip(greens, oranges, reds)]
        pct_g    = [100 * g / t if t else 0 for g, t in zip(greens,  totals)]
        pct_o    = [100 * o / t if t else 0 for o, t in zip(oranges, totals)]

        ys = list(range(len(ordered_jcts)))
        h  = 0.6
        ax_left.barh(ys, pct_g, h,
                     color="#00c853", alpha=0.75, label="Green")
        ax_left.barh(ys, pct_o, h, left=pct_g,
                     color="#ffaa00", alpha=0.75, label="Coord-prearm")
        for i, (g, o, r, tot) in enumerate(zip(pct_g, pct_o, reds, totals)):
            pct_red = 100 * r / tot if tot else 0
            ax_left.text(g + o + pct_red + 1, i,
                         f"{g+o:.0f}%", va="center", fontsize=7, color="#ccccee")
        ax_left.set_yticks(ys)
        ax_left.set_yticklabels(labels, fontsize=7.5, color="#9090cc")
        ax_left.set_xlim(0, 110)
        ax_left.set_xlabel("Green / coord-prearm arrival (%)", fontsize=8,
                           color="#ccccee")
        ax_left.set_title("Junction green-pass rate", fontsize=9,
                          color="#e8e8ff", pad=6)
        ax_left.axvline(50, color="#555577", lw=0.8, ls="--")
        ax_left.legend(fontsize=7, facecolor="#1a1a30",
                       labelcolor="#ccccee", edgecolor="#333355")

    ax_left.set_facecolor("#1a1a30")
    ax_left.tick_params(colors="#9090cc")
    for sp in ax_left.spines.values():
        sp.set_color("#2a2a50")

    # â”€â”€ Right: per-bus journey stats â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    tsp_rows = [r for r in rows if r["vid"] in tsp_vids]
    by_vid: dict = {}
    for r in tsp_rows:
        by_vid.setdefault(r["vid"], []).append(r)

    bus_labels, bus_green_pct, bus_jct_count = [], [], []
    for vid in sorted(by_vid.keys()):
        vrows = sorted(by_vid[vid], key=lambda r: r["t"])
        n_jct  = len(set(r["jct"] for r in vrows))
        phases = [p for p in (_phase_at_stopline(r) for r in vrows) if p != "prearm"]
        n_green = sum(1 for p in phases if p in ("green", "orange"))
        pct     = 100 * n_green / len(phases) if phases else 0
        bus_labels.append(f"Bus {vid}")
        bus_green_pct.append(pct)
        bus_jct_count.append(n_jct)

    if bus_labels:
        xs = list(range(len(bus_labels)))
        bars = ax_right.bar(xs, bus_green_pct, 0.6,
                            color="#42a5f5", alpha=0.75)
        ax_right.set_xticks(xs)
        ax_right.set_xticklabels(bus_labels, fontsize=7, rotation=45,
                                  ha="right", color="#9090cc")
        ax_right.set_ylim(0, 110)
        ax_right.set_ylabel("Green arrival rate (%)", fontsize=8, color="#ccccee")
        ax_right.set_title("Per-bus TSP performance", fontsize=9,
                           color="#e8e8ff", pad=6)
        ax_right.axhline(50, color="#555577", lw=0.8, ls="--")
        for bar, jct_n in zip(bars, bus_jct_count):
            ax_right.text(bar.get_x() + bar.get_width() / 2,
                          bar.get_height() + 2,
                          f"{bar.get_height():.0f}%\n({jct_n}j)",
                          ha="center", fontsize=6.5, color="#ccccee")

    ax_right.set_facecolor("#1a1a30")
    ax_right.tick_params(colors="#9090cc")
    for sp in ax_right.spines.values():
        sp.set_color("#2a2a50")


# =============================================================================
# Main dashboard function
# =============================================================================

def plot_green_wave(rows: list, junctions: dict, out_path: str,
                    title: str = "Green Wave Dashboard") -> None:
    """
    Create the full green-wave dashboard and save to out_path.

    Parameters
    ----------
    rows      : list of detection-event dicts (from _load_detections)
    junctions : {jct_id: (x, y)} geographic centroids (may be empty)
    out_path  : PNG output path
    title     : figure title
    """
    _ensure_mpl()
    if not rows:
        print("[plot_green_wave] No detection rows â€” nothing to plot")
        return

    # â”€â”€ Identify TSP-prioritised vehicles â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    tsp_vids = _find_tsp_vehicles(rows)
    print(f"[plot_green_wave] TSP vehicles: {sorted(tsp_vids)} "
          f"({len(tsp_vids)} of {len(set(r['vid'] for r in rows))} detected)")

    tsp_rows = [r for r in rows if r["vid"] in tsp_vids]
    if not tsp_rows:
        print("[plot_green_wave] No TSP rows after filtering â€” nothing to plot")
        return

    # â”€â”€ Determine corridor junctions present in data â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    jcts_in_data = set(r["jct"] for r in tsp_rows)
    # Prefer junctions that appear in INTERSECTIONS_CONFIG
    cfg_jcts  = set(INTERSECTIONS_CONFIG.keys())
    plot_jcts = list(jcts_in_data & (cfg_jcts | ALL_CORRIDOR_JCTS))
    if not plot_jcts:
        plot_jcts = list(jcts_in_data)

    # â”€â”€ Derive geographic positions if not provided â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if not junctions:
        junctions = _junctions_from_detections(rows)
        if junctions:
            print(f"[plot_green_wave] Using {len(junctions)} derived junction "
                  "positions from detection coordinates")

    # â”€â”€ Geographic ordering (south â†’ north, bottom â†’ top of Y-axis) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    ordered_jcts = _geographic_junction_order(junctions, plot_jcts)
    plot_pos     = _equal_spacing(ordered_jcts)

    tsp_rows_jct = [r for r in tsp_rows if r["jct"] in plot_pos]
    if not tsp_rows_jct:
        print("[plot_green_wave] No TSP rows match plotted junctions")
        return

    t_min = min(r["t"] for r in tsp_rows_jct)
    t_max = max(r["t"] for r in tsp_rows_jct)

    # â”€â”€ Figure layout (GridSpec) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    fig = plt.figure(figsize=(24, 14))
    fig.patch.set_facecolor("#12122a")
    gs  = gridspec.GridSpec(
        2, 2,
        height_ratios=[2.8, 1.0],
        width_ratios=[1, 1],
        hspace=0.35, wspace=0.30,
        left=0.10, right=0.98, top=0.93, bottom=0.07,
    )
    ax_main   = fig.add_subplot(gs[0, :])   # spans both columns
    ax_stats_l = fig.add_subplot(gs[1, 0])
    ax_stats_r = fig.add_subplot(gs[1, 1])

    ax_main.set_facecolor("#1a1a30")

    # â”€â”€ Draw panels â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    phase_stats = _draw_corridor_panel(
        ax_main, rows, tsp_vids, ordered_jcts, plot_pos, t_min, t_max)
    _draw_stats_panel(
        ax_stats_l, ax_stats_r, rows, tsp_vids, ordered_jcts, phase_stats)

    # â”€â”€ Title and meta info â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    n_tsp   = len(tsp_vids)
    n_total = len(set(r["vid"] for r in rows))
    has_sig = any(r["signal_phase"] > 0 for r in rows)
    subtitle = (f"{n_tsp} TSP bus(es) of {n_total} detected  |  "
                f"{len(tsp_rows_jct)} events  |  "
                f"{len(ordered_jcts)} junctions  |  "
                f"{'phase recorded' if has_sig else 'phase from planned cycle'}")
    fig.suptitle(f"{title}\n{subtitle}",
                 fontsize=12, color="#e8e8ff", y=0.97)

    plt.savefig(out_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[plot_green_wave] Dashboard saved: {out_path}")


# =============================================================================
# Comparison dashboard (multiple runs side-by-side)
# =============================================================================

def plot_green_wave_compare(run_specs: list, out_path: str) -> None:
    """
    Compare green-wave performance across multiple simulation runs.

    Parameters
    ----------
    run_specs : list of (label, csv_path) pairs.
                csv_path can be None if a pre-loaded rows list is preferred â€”
                pass (label, rows_list) to use raw data.
    out_path  : PNG output path

    Key metrics shown per run:
      â€¢ Green arrival rate (%) per junction
      â€¢ Mean green arrival rate across all corridor junctions
      â€¢ Number of TSP buses
      â€¢ (if available) passenger delay, bus delay, main delay, side delay
    """
    _ensure_mpl()
    if not run_specs:
        print("[plot_compare] No run specs provided")
        return

    all_data = []
    for spec in run_specs:
        label, src = spec[0], spec[1]
        if isinstance(src, str):
            rows = _load_detections(src)
        else:
            rows = list(src)  # already a list of dicts
        tsp_vids = _find_tsp_vehicles(rows)
        tsp_rows = [r for r in rows if r["vid"] in tsp_vids]
        # Per-junction green rate
        stats: dict = {}
        for r in tsp_rows:
            jid = r["jct"]
            if jid not in stats:
                stats[jid] = {"green": 0, "orange": 0, "red": 0}
            p = _phase_at_stopline(r)
            stats[jid]["green"  if p == "green"  else
                        "orange" if p == "orange" else "red"] += 1
        jcts = sorted(stats.keys())
        green_pct = {}
        for jid in jcts:
            tot = sum(stats[jid].values())
            green_pct[jid] = 100 * (stats[jid]["green"] + stats[jid]["orange"]) / tot if tot else 0
        all_data.append({
            "label":      label,
            "tsp_vids":   tsp_vids,
            "jcts":       jcts,
            "green_pct":  green_pct,
            "n_tsp":      len(tsp_vids),
            "mean_green": sum(green_pct.values()) / len(green_pct) if green_pct else 0,
        })

    # â”€â”€ All corridor junctions across all runs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    all_jcts = sorted(set(j for d in all_data for j in d["jcts"]))

    fig, axes = plt.subplots(
        1, 2,
        figsize=(max(14, 6 * len(run_specs)), 7),
        gridspec_kw={"width_ratios": [3, 1]}
    )
    fig.patch.set_facecolor("#12122a")

    ax_bar   = axes[0]
    ax_summ  = axes[1]

    # â”€â”€ Left: grouped bar chart â€” green rate per junction per run â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    n_runs = len(all_data)
    width  = 0.75 / max(n_runs, 1)
    colors = [_get_cmap("tab10", max(n_runs, 2))(i / max(n_runs - 1, 1))
              for i in range(n_runs)]

    xs = list(range(len(all_jcts)))
    for i, d in enumerate(all_data):
        vals = [d["green_pct"].get(j, 0) for j in all_jcts]
        offset = (i - n_runs / 2 + 0.5) * width
        ax_bar.bar([x + offset for x in xs], vals, width,
                   color=colors[i], alpha=0.80, label=d["label"])

    ax_bar.set_xticks(xs)
    ax_bar.set_xticklabels([f"jct {j}" for j in all_jcts],
                           rotation=45, ha="right", fontsize=8, color="#9090cc")
    ax_bar.set_ylim(0, 110)
    ax_bar.axhline(50, color="#555577", lw=0.8, ls="--")
    ax_bar.set_ylabel("Green / coord arrival rate (%)", fontsize=9, color="#ccccee")
    ax_bar.set_title("Green-pass rate by junction (all runs)", fontsize=10,
                     color="#e8e8ff")
    ax_bar.legend(fontsize=8, facecolor="#1a1a30",
                  labelcolor="#ccccee", edgecolor="#333355")
    ax_bar.set_facecolor("#1a1a30")
    ax_bar.tick_params(colors="#9090cc")

    # â”€â”€ Right: summary table (mean green%, TSP bus count) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    row_labels  = [d["label"]              for d in all_data]
    mean_greens = [f"{d['mean_green']:.1f}%" for d in all_data]
    n_tsps      = [str(d["n_tsp"])         for d in all_data]

    ax_summ.axis("off")
    table_data = [["Run", "Avg green%", "#TSP buses"]] + \
                 list(zip(row_labels, mean_greens, n_tsps))
    tbl = ax_summ.table(
        cellText=table_data[1:],
        colLabels=table_data[0],
        loc="center",
        cellLoc="center",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1.2, 1.6)
    for (row, col), cell in tbl.get_celld().items():
        cell.set_facecolor("#1a1a35" if row % 2 == 0 else "#12122a")
        cell.set_text_props(color="#ccccee")
        cell.set_edgecolor("#333355")

    ax_summ.set_facecolor("#12122a")
    ax_summ.set_title("Summary", fontsize=10, color="#e8e8ff")

    for ax in axes:
        for sp in ax.spines.values():
            sp.set_color("#2a2a50")

    fig.suptitle("Green-Wave Comparison Dashboard", fontsize=13,
                 color="#e8e8ff", y=1.01)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[plot_compare] Comparison dashboard saved: {out_path}")


# =============================================================================
# Auto-discovery entry point
# =============================================================================

def _find_latest(log_dir: str, pattern: str):
    files = sorted(glob.glob(os.path.join(log_dir, pattern)))
    return files[-1] if files else None


def run(csv_path: str = None, junc_csv: str = None, out_png: str = None) -> None:
    log_dir = os.path.join(_SCRIPT_DIR, "logs")

    if csv_path is None:
        csv_path = _find_latest(log_dir, "detection_points_*.csv")
    if csv_path is None:
        print("[plot_green_wave] No detection_points CSV found in", log_dir)
        return

    rows = _load_detections(csv_path)
    if not rows:
        print(f"[plot_green_wave] CSV empty or unreadable: {csv_path}")
        return

    n_veh = len(set(r["vid"] for r in rows))
    n_jct = len(set(r["jct"] for r in rows))
    print(f"[plot_green_wave] {len(rows)} detection events | "
          f"{n_veh} vehicle(s) | {n_jct} junction(s)")

    if junc_csv is None:
        stem      = os.path.basename(csv_path)
        ts        = stem.replace("detection_points_", "").replace(".csv", "")
        candidate = os.path.join(log_dir, f"junction_centroids_{ts}.csv")
        junc_csv  = candidate if os.path.isfile(candidate) else \
                    _find_latest(log_dir, "junction_centroids_*.csv")

    junctions = _load_junctions(junc_csv)
    if junctions:
        print(f"[plot_green_wave] {len(junctions)} junction centroids loaded")
    else:
        junctions = _junctions_from_detections(rows)
        if junctions:
            print(f"[plot_green_wave] {len(junctions)} junction positions "
                  "derived from detection coordinates")

    out_png = out_png or os.path.splitext(csv_path)[0] + "_green_wave.png"

    has_sig = any(r["signal_phase"] > 0 for r in rows)
    title   = (
        f"Logan Road TSP Green Wave  |  "
        f"{'signal_phase recorded' if has_sig else 'phase from planned cycle'}"
    )
    plot_green_wave(rows, junctions, out_png, title)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="Green-wave dashboard for Logan Road TSP simulation")
    ap.add_argument("csv_path", nargs="?", help="detection_points CSV")
    ap.add_argument("junc_csv", nargs="?", help="junction_centroids CSV (optional)")
    ap.add_argument("out_png",  nargs="?", help="output PNG path")
    args = ap.parse_args()
    run(args.csv_path, args.junc_csv, args.out_png)
