"""
plot_spacetime_wave.py
======================
Space-time green-wave diagram for the Logan Road TSP corridor.

Layout
------
  X axis  — simulation time (seconds)
  Y axis  — corridor distance (metres from southernmost junction)

For each TSP-prioritised bus:
  • A diagonal trajectory line connecting all detection events
  • Detection markers coloured by signal phase:
      green  = bus arrived during bus phase (made the green)
      orange = coord-prearm event fired
      red    = bus arrived on red / wrong phase

For each corridor junction (Y position):
  • Horizontal SIGNAL BANDS reconstructed from the detection event:
      phase_start_t  →  phase_start_t + green_duration_s   = GREEN
      phase_start_t + green_duration_s  →  phase_start_t + cycle_time_s = RED/OTHER
      … tiled across the whole simulation window

  Bands are drawn at the junction's corridor-distance Y coordinate, with a
  vertical thickness proportional to the detection zone (~200 m wide strip).

Extra overlays
  • Dashed "ideal green wave" diagonals at free-flow speed (11 m/s ≈ 40 km/h)
  • Orange triangle  = coord-prearm fired for downstream junction
  • Star marker      = natural green (bus caught green without TSP action)
  • Annotated reason text when bus missed the green (from detection tier)

Usage
-----
  Called automatically from AAPIFinish() in intersection_controller.py.

  Can also be run standalone:
      python plot_spacetime_wave.py   # uses latest CSV files in logs/
      python plot_spacetime_wave.py path/to/detection.csv path/to/junctions.csv
"""

import os
import sys
import csv
import glob
import math
import collections

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Add Aimsun packages path before importing matplotlib
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
_AIMSUN_PACKAGES = r"C:\AimsunPackages"
if os.path.isdir(_AIMSUN_PACKAGES) and _AIMSUN_PACKAGES not in sys.path:
    sys.path.append(_AIMSUN_PACKAGES)

# ---------------------------------------------------------------------------
# Matplotlib import (non-fatal if missing in Aimsun environment)
# ---------------------------------------------------------------------------
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.collections import LineCollection
    from matplotlib.lines import Line2D
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FREE_FLOW_MS   = 11.0          # m/s  ≈ 40 km/h  (ideal wave slope)
BAND_HEIGHT_M  = 180.0         # visual height of signal band strip (m)
SIM_START_S    = 0.0
SIM_END_S      = 5400.0        # 90-minute simulation (updated if data is longer)

# Colours
C_GREEN  = "#00e676"
C_RED    = "#ff5252"
C_ORANGE = "#ffb300"
C_BLUE   = "#29b6f6"
C_PURPLE = "#ab47bc"
C_MUTED  = "#555577"
C_BG     = "#0d0d1e"
C_BG2    = "#13132b"
C_TEXT   = "#cccce8"

PALETTE = [
    "#29b6f6", "#00e676", "#ffb300", "#ab47bc",
    "#ff5252", "#26c6da", "#d4e157", "#ff7043",
]


# ---------------------------------------------------------------------------
# CSV loading helpers
# ---------------------------------------------------------------------------

def _load_detections(path: str) -> list:
    rows = []
    if not path or not os.path.isfile(path):
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "t":             float(row["sim_time_s"]),
                    "jct":           int(row["junction_id"]),
                    "vid":           int(row["veh_id"]),
                    "x":             float(row.get("x") or 0),
                    "y":             float(row.get("y") or 0),
                    "tier":          (row.get("tier") or "").strip(),
                    "signal_phase":  int((row.get("signal_phase") or "-1").strip() or -1),
                    "bus_phase":     int((row.get("bus_phase") or "-1").strip() or -1),
                    "phase_start_t": float(row.get("phase_start_t") or -1),
                    "prearm_status": (row.get("prearm_status") or "").strip().lower(),
                    "prearm_eta_s":  float(row.get("prearm_eta_s") or 0.0),
                    "prearm_note":   (row.get("prearm_note") or "").strip(),
                    "focus_role":    (row.get("focus_role") or "").strip(),
                })
            except (KeyError, ValueError):
                continue
    return rows


def _load_focus_history(path: str) -> list:
    rows = []
    if not path or not os.path.isfile(path):
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "start_t": float(row.get("start_t") or 0.0),
                    "end_t":   float(row.get("end_t") or 0.0),
                    "vid":     int(float(row.get("veh_id") or -1)),
                    "jct":     int(float(row.get("jct_id") or -1)),
                    "outcome": (row.get("outcome") or "").strip(),
                })
            except (TypeError, ValueError):
                continue
    return rows


def _load_junctions(path: str) -> dict:
    """Return {jct_id: {x, y, cycle_time_s, bus_phase, bus_phase_duration_s}}."""
    jcts = {}
    if not path or not os.path.isfile(path):
        return jcts
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                jid = int(row["junction_id"])
                jcts[jid] = {
                    "x":                   float(row["x"]),
                    "y":                   float(row["y"]),
                    "cycle_time_s":        float(row.get("cycle_time_s") or 0),
                    "bus_phase":           int(row.get("bus_phase") or -1),
                    "bus_phase_duration_s": float(row.get("bus_phase_duration_s") or 0),
                }
            except (KeyError, ValueError):
                continue
    return jcts


def _junctions_from_detections(rows: list) -> dict:
    """Derive approximate junction centroids from detection coordinates."""
    sums = collections.defaultdict(lambda: [0.0, 0.0, 0])
    for r in rows:
        if r["x"] == 0 and r["y"] == 0:
            continue
        sums[r["jct"]][0] += r["x"]
        sums[r["jct"]][1] += r["y"]
        sums[r["jct"]][2] += 1
    return {
        jid: {"x": s[0]/s[2], "y": s[1]/s[2],
              "cycle_time_s": 0, "bus_phase": -1, "bus_phase_duration_s": 0}
        for jid, s in sums.items() if s[2] > 0
    }


def _find_tsp_buses(rows: list, max_buses: int = 12) -> set:
    """
    Return vehicle IDs to display.  Priority order:
      1. Buses that received coord-prearm events (definitively TSP-prioritised).
      2. Buses that made at least one green arrival (signal_phase == bus_phase).
      3. Buses that traversed the most corridor junctions.
    Caps at max_buses to keep the diagram readable.
    """
    prearm_vids = {r["vid"] for r in rows if "coord-prearm" in r["tier"].lower()}

    # Buses with at least one green hit
    green_vids = {r["vid"] for r in rows
                  if r["signal_phase"] >= 0
                  and r["bus_phase"] >= 0
                  and r["signal_phase"] == r["bus_phase"]}

    # Rank all buses by junction count (most junctions = most interesting)
    jct_count = collections.Counter(r["vid"] for r in rows)
    ranked    = [vid for vid, _ in jct_count.most_common()]

    # Build priority list: coord-prearm first, then green-catchers, then most junctions
    selected: list = []
    for vid in ranked:
        if vid in prearm_vids:
            selected.insert(0, vid)   # highest priority
        elif vid in green_vids and vid not in selected:
            selected.append(vid)

    # Fill remaining slots with top-junction-count buses
    for vid in ranked:
        if vid not in selected:
            selected.append(vid)

    return set(selected[:max_buses])


def _corridor_distance(jcts: dict) -> dict:
    """
    Map each junction ID to a corridor distance (m) measured from the
    southernmost junction (Y=0).  Uses geographic Y coordinate.
    """
    if not jcts:
        return {}
    y_min = min(v["y"] for v in jcts.values())
    return {jid: jinfo["y"] - y_min for jid, jinfo in jcts.items()}


def _phase_color(signal_phase: int, bus_phase: int, tier: str) -> str:
    if "coord-prearm" in tier.lower():
        return C_ORANGE
    if signal_phase < 0 or bus_phase < 0:
        return C_MUTED
    return C_GREEN if signal_phase == bus_phase else C_RED


def _event_phase(row: dict) -> str:
    status = str(row.get("prearm_status", "") or "").lower()
    if status in ("fired", "queued"):
        return "prearm"
    if status == "success":
        return "success"
    if status == "missed":
        return "red"
    if "coord-prearm" in row.get("tier", "").lower():
        return "prearm"
    sp = row.get("signal_phase", -1)
    bp = row.get("bus_phase", -1)
    if sp == bp and sp >= 0:
        return "green"
    return "red"


def _action_kind(row: dict) -> str:
    tier = str(row.get("tier", "") or "").lower()
    note = str(row.get("prearm_note", "") or "").lower()
    if "harmony-ge" in tier or note.startswith("ge "):
        return "ge"
    if "harmony-ins" in tier or note.startswith("ins "):
        return "ins"
    return ""


# ---------------------------------------------------------------------------
# Signal band reconstruction
# ---------------------------------------------------------------------------

def _signal_bands(jct_info: dict, t_start: float, t_end: float,
                  phase_start_t: float = -1.0) -> list:
    """
    Return list of (t_from, t_to, color) tuples for signal bands at this
    junction across [t_start, t_end].

    Uses cycle_time_s and bus_phase_duration_s from jct_info.
    phase_start_t anchors the reconstruction if available.
    """
    cycle  = jct_info.get("cycle_time_s", 0.0)
    g_dur  = jct_info.get("bus_phase_duration_s", 0.0)
    if cycle <= 0 or g_dur <= 0:
        return []

    # Anchor: if we know when this phase started, use that to anchor bands.
    # Otherwise assume bus_phase starts at t=0 with zero offset.
    if phase_start_t >= 0:
        # The phase starting at phase_start_t lasts g_dur seconds.
        # Work backward to find the cycle epoch that covers t_start.
        anchor = phase_start_t
    else:
        anchor = 0.0  # assume green starts at t=0

    # Find the first green band that could overlap [t_start, t_end]
    # Green band: [anchor + n*cycle, anchor + n*cycle + g_dur]
    # Find smallest n such that anchor + n*cycle + g_dur >= t_start
    n_first = math.floor((t_start - anchor - g_dur) / cycle)
    bands = []
    n = max(n_first - 1, -200)
    while True:
        t_green_s = anchor + n * cycle
        t_green_e = t_green_s + g_dur
        t_red_e   = t_green_s + cycle  # next green starts here
        if t_green_s > t_end + cycle:
            break
        if t_green_e >= t_start:
            # Green band
            bands.append((max(t_green_s, t_start), min(t_green_e, t_end), C_GREEN))
            # Red/other band follows
            if t_green_e < t_end:
                bands.append((max(t_green_e, t_start), min(t_red_e, t_end), C_RED))
        n += 1
        if n > 200:
            break
    return bands


# ---------------------------------------------------------------------------
# Main plot function
# ---------------------------------------------------------------------------

def plot_spacetime_wave(det_csv: str, junc_csv: str = None,
                        out_path: str = None) -> str:
    """
    Generate the space-time green-wave diagram.

    Parameters
    ----------
    det_csv  : path to detection_points_*.csv
    junc_csv : path to junction_centroids_*.csv (optional; improves signal bands)
    out_path : output PNG path (auto-named alongside det_csv if None)

    Returns the output path.
    """
    if not HAS_MPL:
        print("[SPACETIME] matplotlib not available — skipping plot")
        return None

    rows = _load_detections(det_csv)
    if not rows:
        print("[SPACETIME] No detection data — skipping")
        return None

    # Junction geometry
    jcts = _load_junctions(junc_csv) if junc_csv else {}
    if not jcts:
        jcts = _junctions_from_detections(rows)

    # Corridor distances
    dist_map = _corridor_distance(jcts)
    if not dist_map:
        print("[SPACETIME] No junction geometry — cannot build Y axis")
        return None

    # TSP buses only
    tsp_vids = _find_tsp_buses(rows)
    tsp_rows = [r for r in rows if r["vid"] in tsp_vids]
    if not tsp_rows:
        tsp_rows = rows[:200]   # fallback: show first 200 detections

    focus_csv = det_csv.replace("detection_points_", "focus_history_")
    focus_rows = _load_focus_history(focus_csv)

    # Time extent
    t_min = min(r["t"] for r in tsp_rows)
    t_max = max(r["t"] for r in tsp_rows) + 60.0
    t_min = max(0.0, t_min - 30.0)

    # Ordered junctions (south → north)
    known_jcts = sorted(
        [j for j in dist_map if j in {r["jct"] for r in tsp_rows}],
        key=lambda j: dist_map[j]
    )
    if not known_jcts:
        print("[SPACETIME] No matching junctions in detection data")
        return None

    # ── Figure setup ──────────────────────────────────────────────────────────
    fig_h = max(8, len(known_jcts) * 1.6 + 3)
    fig, ax = plt.subplots(figsize=(18, fig_h), facecolor=C_BG)
    ax.set_facecolor(C_BG2)
    for spine in ax.spines.values():
        spine.set_edgecolor("#2a2a50")

    # ── Signal bands for each junction ────────────────────────────────────────
    # Collect the most recent phase_start_t per junction from detection CSV.
    # phase_start_t is recorded from ECIGetStartingTimePhase — available only
    # in runs where intersection_controller.py has been updated.
    jct_phase_anchor: dict = {}
    for r in tsp_rows:
        if r["phase_start_t"] >= 0 and r["signal_phase"] == r["bus_phase"]:
            jct_phase_anchor[r["jct"]] = r["phase_start_t"]

    has_band_data = any(
        jcts.get(j, {}).get("cycle_time_s", 0) > 0 for j in known_jcts
    )
    if not has_band_data:
        ax.text(
            0.5, 0.97,
            "Signal phase bands not yet available — will appear after next simulation run\n"
            "(requires updated junction_centroids CSV with cycle_time_s column)",
            transform=ax.transAxes, ha="center", va="top",
            color=C_ORANGE, fontsize=8.5, alpha=0.8,
            bbox=dict(boxstyle="round,pad=0.3", facecolor=C_BG2, edgecolor=C_ORANGE, alpha=0.7)
        )

    for jid in known_jcts:
        d = dist_map[jid]
        jinfo = jcts.get(jid, {})
        anchor = jct_phase_anchor.get(jid, -1.0)
        bands = _signal_bands(jinfo, t_min, t_max, anchor)
        for tb_s, tb_e, col in bands:
            alpha = 0.22 if col == C_GREEN else 0.10
            ax.axhspan(
                d - BAND_HEIGHT_M / 2, d + BAND_HEIGHT_M / 2,
                xmin=(tb_s - t_min) / (t_max - t_min),
                xmax=(tb_e - t_min) / (t_max - t_min),
                color=col, alpha=alpha, zorder=1
            )
        # Junction label line
        ax.axhline(d, color="#2a2a50", linewidth=0.6, zorder=2)

    # Focus-bus windows show when the corridor was deliberately holding
    # decision authority for one bus. These are drawn before trajectories so the
    # bus lines and pre-arm evidence sit on top.
    for fr in focus_rows:
        if fr["jct"] not in dist_map:
            continue
        if fr["vid"] not in tsp_vids:
            continue
        y = dist_map[fr["jct"]]
        ax.plot([fr["start_t"], fr["end_t"]], [y, y],
                color="#00e5ff", linewidth=6.0, alpha=0.28,
                solid_capstyle="butt", zorder=3)
        ax.annotate(
            f"focused bus {fr['vid']}",
            (fr["start_t"], y),
            xytext=(4, 10), textcoords="offset points",
            color="#80f4ff", fontsize=7.2, zorder=8,
        )

    # ── Ideal green-wave diagonals ────────────────────────────────────────────
    # Draw lines at free-flow speed passing through each junction.
    # Each detection event spawns one "ideal" diagonal showing the wave timing.
    ideal_plotted = set()
    for r in tsp_rows:
        jid = r["jct"]
        if jid in ideal_plotted or jid not in dist_map:
            continue
        ideal_plotted.add(jid)
        d0 = dist_map[jid]
        t0 = r["t"]
        # Two directions (forward/backward along corridor)
        for sign in (+1, -1):
            t_vals = [t0 + sign * (d - d0) / FREE_FLOW_MS
                      for d in [dist_map[j] for j in known_jcts]]
            d_vals = [dist_map[j] for j in known_jcts]
            ax.plot(t_vals, d_vals,
                    color=C_GREEN, alpha=0.08, linewidth=0.8,
                    linestyle="--", zorder=2)

    # ── Bus trajectories ──────────────────────────────────────────────────────
    buses_by_id = collections.defaultdict(list)
    for r in tsp_rows:
        if r["jct"] in dist_map:
            buses_by_id[r["vid"]].append(r)

    legend_handles = []
    for bi, (vid, vrows) in enumerate(sorted(buses_by_id.items())):
        color = PALETTE[bi % len(PALETTE)]
        vrows_sorted = sorted(vrows, key=lambda r: r["t"])
        is_focused = any(
            str(r.get("focus_role", "")).lower() in ("focused_bus", "focus_acquire")
            for r in vrows_sorted
        )

        # Collect observed arrivals only. Pre-arm-fired rows are request
        # evidence at the target junction, not proof that the bus arrived there.
        pts = [(r["t"], dist_map[r["jct"]]) for r in vrows_sorted
               if r["jct"] in dist_map and _event_phase(r) != "prearm"]
        if len(pts) >= 2:
            ts, ds = zip(*pts)
            ax.plot(
                ts, ds,
                color=color,
                linewidth=2.6 if is_focused else 1.6,
                alpha=0.9 if is_focused else 0.62,
                linestyle="-" if is_focused else "--",
                zorder=4,
                solid_capstyle="round",
            )

        # Detection markers at each junction
        for r in vrows_sorted:
            if r["jct"] not in dist_map:
                continue
            t_ev = r["t"]
            d_ev = dist_map[r["jct"]]
            tier = r["tier"]
            sp   = r["signal_phase"]
            bp   = r["bus_phase"]
            phase = _event_phase(r)

            if phase == "prearm":
                ax.plot(t_ev, d_ev, marker="v", color=C_PURPLE,
                        markersize=10, zorder=6,
                        markeredgecolor="white", markeredgewidth=0.6)
                eta_s = float(r.get("prearm_eta_s", 0.0) or 0.0)
                label = "pre-arm"
                if eta_s > 0.0:
                    label += f" {eta_s:.0f}s"
                ax.annotate(label, (t_ev, d_ev),
                            xytext=(6, 6), textcoords="offset points",
                            color=C_PURPLE, fontsize=7.2, zorder=7)
            elif phase == "success":
                ax.plot(t_ev, d_ev, marker="^", color=C_ORANGE,
                        markersize=11, zorder=6,
                        markeredgecolor="white", markeredgewidth=0.6)
                ax.annotate("pre-arm success", (t_ev, d_ev),
                            xytext=(6, 6), textcoords="offset points",
                            color=C_ORANGE, fontsize=7.5, zorder=7)
            elif phase == "green":
                # Green circle — made the green
                ax.plot(t_ev, d_ev, marker="o", color=C_GREEN,
                        markersize=9, zorder=6,
                        markeredgecolor="white", markeredgewidth=0.5)
            else:
                # Red X — arrived on wrong phase
                ax.plot(t_ev, d_ev, marker="X", color=C_RED,
                        markersize=10, zorder=6,
                        markeredgecolor="#cc2222", markeredgewidth=0.4)
                if sp >= 0:
                    ax.annotate(f"ph{sp}≠{bp}", (t_ev, d_ev),
                                xytext=(6, -12), textcoords="offset points",
                                color=C_RED, fontsize=7, zorder=7)

            action_kind = _action_kind(r)
            if action_kind:
                is_ge = (action_kind == "ge")
                a_col = "#ffd54f" if is_ge else "#4fc3f7"
                a_mrk = "P" if is_ge else "D"
                ax.plot(t_ev, d_ev, marker=a_mrk, color=a_col,
                        markersize=8.5, zorder=7,
                        markeredgecolor="white", markeredgewidth=0.6)
                eta_s = float(r.get("prearm_eta_s", 0.0) or 0.0)
                note = str(r.get("prearm_note", "") or "")
                lbl = ("GE" if is_ge else "INS")
                if note:
                    lbl += f" {note}"
                if eta_s > 0.0:
                    lbl += f" | eta {eta_s:.0f}s"
                ax.annotate(lbl, (t_ev, d_ev),
                            xytext=(8, -2 if is_ge else -16), textcoords="offset points",
                            color=a_col, fontsize=7.1, zorder=8)

            focus_role = str(r.get("focus_role", "") or "").lower()
            if focus_role in ("blocked_by_focus", "focus_suppress"):
                ax.plot(t_ev, d_ev, marker="s", color="#b0bec5",
                        markersize=6.2, zorder=7,
                        markeredgecolor="#37474f", markeredgewidth=0.5)
                ax.annotate("not focused", (t_ev, d_ev),
                            xytext=(5, 9), textcoords="offset points",
                            color="#b0bec5", fontsize=6.8, zorder=8)

        _lbl = f"Bus {vid} (focused)" if is_focused else f"Bus {vid} (other)"
        handle = Line2D(
            [0], [0], color=color,
            linewidth=2.6 if is_focused else 1.6,
            linestyle="-" if is_focused else "--",
            label=_lbl,
        )
        legend_handles.append(handle)

    # ── Y axis labels (junction IDs) ──────────────────────────────────────────
    yticks = [dist_map[j] for j in known_jcts]
    ylabels = [f"jct {j}\n({dist_map[j]:.0f}m)" for j in known_jcts]
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, color=C_TEXT, fontsize=8.5)

    # ── X axis ────────────────────────────────────────────────────────────────
    def _fmt_time(t, _):
        m, s = divmod(int(t), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    import matplotlib.ticker as mticker
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(_fmt_time))
    ax.xaxis.set_major_locator(mticker.MultipleLocator(300))   # every 5 min
    ax.tick_params(axis="x", colors=C_TEXT, labelsize=8)
    ax.set_xlim(t_min, t_max)
    y_margin = 300
    ax.set_ylim(min(yticks) - y_margin, max(yticks) + y_margin)

    # ── Legend ────────────────────────────────────────────────────────────────
    legend_handles += [
        mpatches.Patch(color=C_GREEN, alpha=0.7,  label="Signal: bus phase (green)"),
        mpatches.Patch(color=C_RED,   alpha=0.4,  label="Signal: other phase (red/other)"),
        Line2D([0],[0], color=C_GREEN, alpha=0.3, linewidth=1.5,
               linestyle="--", label=f"Ideal wave ({FREE_FLOW_MS*3.6:.0f} km/h)"),
        Line2D([0],[0], color=C_PURPLE, marker="v", linestyle="None",
               markersize=9, label="Pre-arm fired/requested"),
        Line2D([0],[0], color=C_ORANGE, marker="^", linestyle="None",
               markersize=9, label="Pre-arm success"),
        Line2D([0],[0], color="#00e5ff", alpha=0.5, linewidth=5,
               label="Focused bus window"),
         Line2D([0],[0], color="#ffd54f", marker="P", linestyle="None",
             markersize=8, label="Green extension action"),
         Line2D([0],[0], color="#4fc3f7", marker="D", linestyle="None",
             markersize=8, label="Phase insertion action"),
         Line2D([0],[0], color="#b0bec5", marker="s", linestyle="None",
             markersize=7, label="Suppressed (not focused)"),
        Line2D([0],[0], color=C_GREEN, marker="o", linestyle="None",
               markersize=9, label="Made the green"),
        Line2D([0],[0], color=C_RED, marker="X", linestyle="None",
               markersize=9, label="Missed the green"),
    ]
    ax.legend(handles=legend_handles, loc="upper right",
              facecolor=C_BG, edgecolor="#2a2a50",
              labelcolor=C_TEXT, fontsize=8.5,
              ncol=2, framealpha=0.85)

    # ── Titles ────────────────────────────────────────────────────────────────
    exp_tag = os.path.splitext(os.path.basename(det_csv))[0].replace("detection_points_", "")
    ax.set_title(f"Logan Road TSP — Space-Time Green Wave Diagram\n{exp_tag}",
                 color=C_TEXT, fontsize=12, pad=10)
    ax.set_xlabel("Simulation Time", color=C_TEXT, fontsize=10)
    ax.set_ylabel("Corridor Distance from South (m)", color=C_TEXT, fontsize=10)
    ax.tick_params(axis="y", colors=C_TEXT, labelsize=8)

    plt.tight_layout(pad=1.5)

    if out_path is None:
        stem = os.path.splitext(det_csv)[0]
        out_path = stem + "_spacetime.png"

    fig.savefig(out_path, dpi=130, bbox_inches="tight",
                facecolor=C_BG, edgecolor="none")
    plt.close(fig)
    print(f"[SPACETIME] Space-time diagram -> {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Entry point — called from AAPIFinish or standalone
# ---------------------------------------------------------------------------

def run(csv_path: str = None, junc_csv: str = None) -> str:
    """Called from AAPIFinish.  Auto-discovers files if not passed explicitly."""
    if csv_path is None:
        log_dir = os.path.join(_SCRIPT_DIR, "logs")
        candidates = sorted(
            glob.glob(os.path.join(log_dir, "detection_points_*.csv")),
            key=os.path.getmtime)
        if not candidates:
            print("[SPACETIME] No detection CSV found")
            return None
        csv_path = candidates[-1]

    if junc_csv is None:
        log_dir = os.path.dirname(csv_path)
        candidates = sorted(
            glob.glob(os.path.join(log_dir, "junction_centroids_*.csv")),
            key=os.path.getmtime)
        junc_csv = candidates[-1] if candidates else None

    return plot_spacetime_wave(csv_path, junc_csv)


if __name__ == "__main__":
    det  = sys.argv[1] if len(sys.argv) > 1 else None
    junc = sys.argv[2] if len(sys.argv) > 2 else None
    run(det, junc)
