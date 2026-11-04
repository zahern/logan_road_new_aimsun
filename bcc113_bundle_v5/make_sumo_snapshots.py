"""make_sumo_snapshots.py -- intersection "what is happening" figures from SUMO.

The paper needs to SHOW a junction, not just report its delay. This renders one
panel per requested time: the junction geometry from the corridor net, every
approach shaded by its measured queue, the active signal phase with its
remaining green, and the position of every bus in the network.

Two modes, one command:

    # run SUMO once, capture state, and draw (default)
    python make_sumo_snapshots.py

    # re-draw from a previous capture (no simulation)
    python make_sumo_snapshots.py --state-in _sumo_snaps/state.json

WHY NOT sumo-gui:
  `--screenshot` from sumo-gui gives a raster grab whose fonts, aspect ratio and
  colour map are fixed by the GUI -- unusable at print resolution and not
  reproducible. Everything here is read through TraCI and drawn with matplotlib,
  so the figures are vector PDF, deterministic, and restyleable to the paper's
  fonts. It also runs headless, which is what the cluster needs.

WHAT THE PANEL SHOWS (and what it does not):
  - the base signal plan of the scenario as loaded (NO_TSP). This is a fixed-time
    SCATS export; it is NOT an adaptive run. Use it to show the physical problem
    (storage, blocking, queue spillback), not to evidence a TSP arm's gain.
  - queue = SUMO's last-step halting count per lane (speed < 0.1 m/s). That is
    the same quantity the engine's detector feed is meant to approximate, so the
    figure and the metric are on one basis.

Usage:
    python make_sumo_snapshots.py --junctions n39576 n39593 --times 600 1200 1800
    python make_sumo_snapshots.py --scenario _sumo_snaps/kg.sumocfg --seed 300
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                       # noqa: E402
from matplotlib.collections import LineCollection     # noqa: E402

SUMO_HOME = os.environ.get("SUMO_HOME",
                           r"C:\Program Files (x86)\Eclipse\Sumo")
TOOLS = os.path.join(SUMO_HOME, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import sumolib                                        # noqa: E402
import traci                                          # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
# kg.net.xml has a malformed junction-internal topology that makes SUMO
# non-reproducible (see _sumo_snaps/rebuild_kg_net.py). Prefer the rebuilt
# scenario when it exists -- a snapshot from a run that cannot be repeated is
# not evidence of anything.
_SNAPS_DIR = os.path.join(HERE, "_sumo_snaps")
DEFAULT_SCEN = os.path.join(
    _SNAPS_DIR, "kg_rebuilt.sumocfg"
    if os.path.exists(os.path.join(_SNAPS_DIR, "kg_rebuilt.sumocfg"))
    else "kg.sumocfg")
DEFAULT_OUT = os.path.join(HERE, "_sumo_snaps", "figs")
# Kelvin Grove SCATS sites named in the corridor audit. Used only as defaults;
# unknown ids are reported rather than silently skipped.
DEFAULT_JUNCTIONS = ["n39576", "n39593", "n39572"]


# --------------------------------------------------------------------------
# capture
# --------------------------------------------------------------------------
def _is_bus(veh_id, cache):
    if veh_id in cache:
        return cache[veh_id]
    ok = False
    try:
        vclass = traci.vehicle.getVehicleClass(veh_id) or ""
        vtype = traci.vehicle.getTypeID(veh_id) or ""
        ok = ("bus" in vclass.lower()) or ("bus" in vtype.lower())
    except Exception:
        ok = False
    cache[veh_id] = ok
    return ok


def capture(scenario, times, junctions, seed, end, state_out):
    binary = os.path.join(SUMO_HOME, "bin", "sumo.exe")
    if not os.path.exists(binary):
        binary = "sumo"
    cmd = [binary, "-c", scenario, "--seed", str(seed), "--no-step-log",
           "true", "--duration-log.statistics", "false"]
    if end:
        cmd += ["--end", str(end)]

    traci.start(cmd, label="snap")
    conn = traci.getConnection("snap")
    net = sumolib.net.readNet(os.path.join(os.path.dirname(scenario),
                                           _net_file(scenario)))

    want = sorted(set(int(t) for t in times))
    state = {"scenario": os.path.relpath(scenario, HERE), "seed": seed,
             "junctions": {}, "times": want}
    for jid in junctions:
        if not net.hasNode(jid):
            print("[SNAP] junction %s not in net -- skipped" % jid)
            continue
        node = net.getNode(jid)
        tls = node.getTLSID() if hasattr(node, "getTLSID") else None
        lanes = []
        for edge in net.getEdges():
            if edge.getID().startswith(":"):
                continue
            if edge.getToNode().getID() != jid:
                continue
            for lane in edge.getLanes():
                lanes.append({"lane": lane.getID(), "edge": edge.getID(),
                              "from": edge.getFromNode().getID()})
        state["junctions"][jid] = {"tls": tls, "lanes": lanes,
                                   "panel": {}}
        print("[SNAP] %s: %d approach lanes, tls=%s" % (jid, len(lanes), tls))

    if not state["junctions"]:
        conn.close()
        raise SystemExit("no requested junction exists in this net")

    bus_cache = {}
    t = 0
    reached = []
    for target in want:
        while t < target:
            conn.simulationStep()
            t += 1
        reached.append(target)
        buses = []
        for vid in conn.vehicle.getIDList():
            if not _is_bus(vid, bus_cache):
                continue
            try:
                x, y = conn.vehicle.getPosition(vid)
                buses.append([round(x, 1), round(y, 1)])
            except Exception:
                pass
        for jid, rec in state["junctions"].items():
            q = {}
            for lane in rec["lanes"]:
                try:
                    q[lane["lane"]] = int(
                        conn.lane.getLastStepHaltingNumber(lane["lane"]))
                except Exception:
                    q[lane["lane"]] = 0
            panel = {"t": target, "queue": q, "buses": buses}
            if rec["tls"]:
                try:
                    panel["phase"] = int(conn.trafficlight.getPhase(rec["tls"]))
                    panel["phase_s"] = conn.trafficlight.getRedYellowGreenState(
                        rec["tls"])
                    panel["remaining"] = round(
                        conn.trafficlight.getNextSwitch(rec["tls"]) - t, 1)
                except Exception:
                    pass
            rec["panel"][str(target)] = panel
    print("[SNAP] captured t=%s over %d steps" % (reached, t))
    conn.close()

    with open(state_out, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    print("[SNAP] state -> %s" % state_out)
    return state


def _net_file(scenario):
    """Resolve <net-file> out of the .sumocfg without a config parser."""
    import re
    txt = open(scenario, encoding="utf-8", errors="replace").read()
    m = re.search(r'<net-file\s+value="([^"]+)"', txt)
    if not m:
        raise SystemExit("no <net-file> in %s" % scenario)
    return m.group(1)


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------
def _shade(q, qmax):
    """0 -> pale grey, qmax -> saturated red. One hue only: the eye should read
    queue LENGTH, not compare colours across panels. A lane with q=0 must not
    look busy, so the low end is a neutral grey, not the pale end of the ramp."""
    if q <= 0:
        return None
    return min(1.0, 0.25 + 0.75 * (q / qmax if qmax else 0.0))


def render(state, net, junction, out_pdf, dpi=200):
    rec = state["junctions"][junction]
    panels = [rec["panel"][k] for k in sorted(rec["panel"], key=lambda s: int(s))]
    if not panels:
        return None

    qmax = max([max(p["queue"].values()) for p in panels] + [1])
    lane_by_id = {}
    for edge in net.getEdges():
        if edge.getID().startswith(":"):
            continue
        for lane in edge.getLanes():
            lane_by_id[lane.getID()] = lane
    # one label per APPROACH (edge), not per lane: 18 lane labels is noise
    edge_of = {l["lane"]: l["edge"] for l in rec["lanes"]}

    fig, axes = plt.subplots(1, len(panels),
                             figsize=(4.4 * len(panels), 4.6),
                             squeeze=False)
    for ax, panel in zip(axes[0], panels):
        R = 90.0                      # metres of approach the panel shows
        node = net.getNode(junction)
        cx, cy = node.getCoord()

        # context: the whole corridor, faint, so the reader sees where this is
        ctx = []
        for lane in lane_by_id.values():
            shp = lane.getShape()
            if len(shp) >= 2:
                ctx.append(shp)
        ax.add_collection(LineCollection(ctx, colors="#d9d9d9",
                                         linewidths=0.4, zorder=0))

        # every bus in the network
        if panel["buses"]:
            bx = [b[0] for b in panel["buses"]]
            by = [b[1] for b in panel["buses"]]
            ax.scatter(bx, by, s=6, c="#c0392b", alpha=0.55, zorder=2,
                       label="bus (%d)" % len(bx))

        # approach lanes, weighted by queue
        edge_q = {}
        for lane in rec["lanes"]:
            lid = lane["lane"]
            L = lane_by_id.get(lid)
            if L is None:
                continue
            shp = L.getShape()
            if len(shp) < 2:
                continue
            q = panel["queue"].get(lid, 0)
            edge_q[lane["edge"]] = edge_q.get(lane["edge"], 0) + q
            s = _shade(q, qmax)
            ax.plot([p[0] for p in shp], [p[1] for p in shp],
                    color="#e9e9e9" if s is None else plt.cm.YlOrRd(s),
                    lw=1.6 + 6.0 * (L.getWidth() / 3.5) * (0.35 if s is None else 1.0),
                    solid_capstyle="butt", zorder=3)

        # one label per approach, placed where the approach leaves the frame
        placed = []
        for edge_id, q in edge_q.items():
            best, bestd = None, -1.0
            for lane in rec["lanes"]:
                if lane["edge"] != edge_id:
                    continue
                L = lane_by_id.get(lane["lane"])
                if L is None:
                    continue
                for (x, y) in L.getShape():
                    d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                    if R * 0.55 <= d <= R and d > bestd:
                        bestd, best = d, (x, y)
            if best is None:
                continue
            # push the label outside the frame along its own bearing, so two
            # approaches that are close in angle cannot print on top of one
            # another
            dx, dy = best[0] - cx, best[1] - cy
            n = max((dx * dx + dy * dy) ** 0.5, 1e-6)
            lx, ly = cx + dx / n * R * 1.10, cy + dy / n * R * 1.10
            # two approaches can share a bearing (dual carriageway); stack them
            # instead of printing one label through the other
            # label boxes are ~15-20 m wide at this scale, so the threshold has
            # to be generous or two stacked labels still print through each other
            while any((lx - px) ** 2 + (ly - py) ** 2 < (0.50 * R) ** 2
                      for px, py in placed):
                ly += 0.32 * R
            placed.append((lx, ly))
            ax.annotate("%s: %d veh" % (edge_id, q), (lx, ly), fontsize=7.5,
                        color="#222222", ha="center", va="center", zorder=5,
                        bbox=dict(boxstyle="round,pad=0.18", fc="white",
                                  ec="#bbbbbb", lw=0.5, alpha=0.9))

        ax.plot([cx], [cy], marker="s", ms=4, color="#1f3b73", zorder=6)
        ax.annotate(junction, (cx, cy), textcoords="offset points",
                    xytext=(5, 5), fontsize=8, weight="bold", color="#1f3b73",
                    zorder=7)

        head = "t = %d s" % panel["t"]
        if "phase" in panel:
            head += "   phase %d, %.1f s left" % (panel["phase"],
                                                  panel["remaining"])
        ax.set_title(head, fontsize=9)
        if "phase_s" in panel:
            ax.set_xlabel("green string %s" % panel["phase_s"], fontsize=6.5)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        # square crop around the junction: every panel same scale, so panels
        # can be compared by eye
        ax.set_xlim(cx - R * 1.18, cx + R * 1.18)
        ax.set_ylim(cy - R * 1.18, cy + R * 1.18)

    fig.suptitle("%s -- fixed-time plan; queue in vehicles per approach"
                 % junction, fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_pdf, dpi=dpi)
    plt.close(fig)
    return out_pdf


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default=DEFAULT_SCEN)
    ap.add_argument("--junctions", nargs="+", default=DEFAULT_JUNCTIONS)
    ap.add_argument("--times", nargs="+", type=int, default=[600, 1200, 1800])
    ap.add_argument("--seed", type=int, default=300)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--state-in", default=None,
                    help="re-render from a previous capture instead of running")
    ap.add_argument("--state-out", default=None)
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    state_out = args.state_out or os.path.join(args.out, "state.json")

    if args.state_in:
        state = json.load(open(args.state_in, encoding="utf-8"))
        print("[SNAP] state <- %s" % args.state_in)
    else:
        state = capture(args.scenario, args.times, args.junctions,
                        args.seed, args.end, state_out)

    net = sumolib.net.readNet(os.path.join(os.path.dirname(args.scenario),
                                           _net_file(args.scenario)))
    made = []
    for jid in state["junctions"]:
        pdf = os.path.join(args.out, "snapshot_%s.pdf" % jid)
        png = os.path.join(args.out, "snapshot_%s.png" % jid)
        render(state, net, jid, pdf)
        # a PNG twin so the figure can be glanced at without opening the PDF
        # (matplotlib picks the format from the suffix)
        render(state, net, jid, png)
        made.append((jid, pdf, os.path.getsize(png)))
        print("[SNAP] %s -> %s (%.0f kB png)" % (jid, pdf,
                                                 os.path.getsize(png) / 1e3))
    if not made:
        raise SystemExit("nothing rendered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
