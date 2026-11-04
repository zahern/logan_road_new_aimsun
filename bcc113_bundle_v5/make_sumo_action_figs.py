"""make_sumo_action_figs.py -- what the system DOES at a junction, and what it buys.

`make_sumo_snapshots.py` shows the plan's problem (a bus sits in a queue). This
shows the other half the paper needs: the decision, the action it produces, and
the measured consequence.

It runs the same KG scenario twice on the same seed:

  base  -- the exported fixed-time plan exactly as loaded (NO_TSP)
  tsp   -- the same plan with the engine's two priority actions applied live via
           TraCI: green extension (EXT) for a bus on the serving phase, early red
           (ER) to truncate a serving phase that has no demand while a bus waits
           on a cross approach.

WHAT THIS IS NOT
----------------
This is NOT `shared_tsp_engine` running. It is a replay of the engine's decision
rule at one junction, so the figure isolates the mechanism. The SUMO engine tree
on Z: is the 2026-10-28 build, which predates the side-ratio gate fix and refuses
most candidates; treat the `tsp` row as an upper bound on the action's worth, not
as an arm result.

METRICS
-------
  junction bus delay : (time on approach) - (approach length / free-flow speed)
  network time loss  : SUMO tripinfo `timeLoss`, summed by vehicle class
  pax*s              : time loss x 40 (bus) and x 1.2 (car), the engine's weights

Usage:
    python make_sumo_action_figs.py
    python make_sumo_action_figs.py --junction n39576 --seed 300
    python make_sumo_action_figs.py --state-in _sumo_snaps/figs/action_states.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                         # noqa: E402
from matplotlib.collections import LineCollection       # noqa: E402

SUMO_HOME = os.environ.get("SUMO_HOME",
                           r"C:\Program Files (x86)\Eclipse\Sumo")
TOOLS = os.path.join(SUMO_HOME, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import sumolib                                          # noqa: E402
import traci                                            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
_SNAPS = os.path.join(HERE, "_sumo_snaps")
# The published kg.net.xml carries a malformed junction-internal topology (119
# internal junctions where a correct build has 16) and SUMO's right-of-way
# bookkeeping over it is not evaluated in a stable order, so every run of the
# original scenario disagrees with itself. `_sumo_snaps/rebuild_kg_net.py` fixes
# that; prefer its output whenever it exists.
SCEN = os.path.join(_SNAPS, "kg_rebuilt.sumocfg"
                    if os.path.exists(os.path.join(_SNAPS, "kg_rebuilt.sumocfg"))
                    else "kg.sumocfg")
NET_FILE = os.path.join(_SNAPS, "kg_rebuilt.net.xml"
                        if os.path.exists(os.path.join(_SNAPS, "kg_rebuilt.net.xml"))
                        else "kg.net.xml")
OUT = os.path.join(HERE, "_sumo_snaps", "figs")

PAX_BUS = 40.0          # engine default (specialized_modes.py)
PAX_CAR = 1.2

TRIGGER_DIST = 140.0    # m from stop line at which a bus is a candidate
MAX_EXT = 15.0          # s of green extension a candidate may earn
MIN_REMAIN = 2.0        # never truncate below this much green
Q_SKIP = 14             # veh on the serving approach above which we do not extend
ER_LOOKAHEAD = 180.0    # m of "no demand" on the serving approach for early red
MAX_ER_CUT = 20.0       # s of green early red may take back (priority, not a replan)
NEAR_R = 320.0          # m: buses this close to the junction are recorded


# --------------------------------------------------------------------------
# net helpers
# --------------------------------------------------------------------------
def link_map(jid):
    """linkIndex -> from-edge, and the tlLogic phase state strings."""
    root = ET.parse(NET_FILE).getroot()
    tl = None
    for e in root.findall("tlLogic"):
        if e.get("id") == jid:
            tl = e
            break
    if tl is None:
        raise SystemExit("no tlLogic for %s" % jid)
    phases = [p.get("state") for p in tl.findall("phase")]
    link_edge = {}
    for c in root.findall("connection"):
        if c.get("tl") != jid:
            continue
        link_edge[int(c.get("linkIndex"))] = c.get("from")
    return link_edge, phases


def green_edges(link_edge, phases, phase_idx):
    if phase_idx is None or phase_idx >= len(phases):
        return set()
    st = phases[phase_idx]
    return {link_edge[li] for li, ch in enumerate(st)
            if ch in ("G", "g") and li in link_edge}


def is_bus(conn, vid, cache):
    if vid in cache:
        return cache[vid]
    try:
        cls = (conn.vehicle.getVehicleClass(vid) or "").lower()
        vtype = (conn.vehicle.getTypeID(vid) or "").lower()
        ok = ("bus" in cls) or ("bus" in vtype)
    except Exception:
        ok = False
    cache[vid] = ok
    return ok


# --------------------------------------------------------------------------
# one run
# --------------------------------------------------------------------------
def run(policy, jid, seed, end, tag):
    binary = os.path.join(SUMO_HOME, "bin", "sumo.exe")
    if not os.path.exists(binary):
        binary = "sumo"
    trip = os.path.join(OUT, "tripinfo_%s.xml" % tag)
    cmd = [binary, "-c", SCEN, "--seed", str(seed), "--no-step-log", "true",
           "--duration-log.statistics", "false", "--tripinfo-output", trip]
    if end:
        cmd += ["--end", str(end)]

    net = sumolib.net.readNet(NET_FILE)
    node = net.getNode(jid)
    tls = node.getTLSID()
    inc_edges = [e.getID() for e in node.getIncoming()]
    edge_len = {e.getID(): e.getLength() for e in node.getIncoming()}
    edge_free = {e.getID(): max(e.getSpeed(), 5.0) for e in node.getIncoming()}
    cx, cy = node.getCoord()
    link_edge, phases = link_map(jid)

    traci.start(cmd, label=tag)
    conn = traci.getConnection(tag)

    series, actions, tracking, done, bus_cache = [], [], {}, {}, {}
    # one action per phase INSTANCE. Keying on (t - remaining) does not work:
    # setPhaseDuration moves `remaining`, so the key changes the moment the
    # action is applied and the rule re-fires every step.
    latch = {"ph": None, "start": None, "acted": False}
    last_action_t = -1e9
    t = 0
    while t < (end or 4500):
        # ---- priority rule (before the step: act on the state we can see) --
        if policy == "tsp":
            try:
                ph = int(conn.trafficlight.getPhase(tls))
                rem = float(conn.trafficlight.getNextSwitch(tls)) - t
            except Exception:
                ph, rem = None, None
            if ph is not None and ph != latch["ph"]:
                latch = {"ph": ph, "start": t, "acted": False}
            if ph is not None:
                green = green_edges(link_edge, phases, ph)
                serving, waiting = [], []
                for ed in inc_edges:
                    try:
                        vids = conn.edge.getLastStepVehicleIDs(ed)
                    except Exception:
                        vids = []
                    for vid in vids:
                        if not is_bus(conn, vid, bus_cache):
                            continue
                        try:
                            pos = conn.vehicle.getLanePosition(vid)
                        except Exception:
                            continue
                        rec = (ed, max(edge_len.get(ed, 0.0) - pos, 0.0), vid)
                        (serving if ed in green else waiting).append(rec)

                q_of = {}
                for ed in inc_edges:
                    q_of[ed] = 0
                    for ln in net.getEdge(ed).getLanes():
                        try:
                            q_of[ed] += int(conn.lane.getLastStepHaltingNumber(ln.getID()))
                        except Exception:
                            pass

                # 1. EXT: a bus is on a green approach and the phase is ending
                if serving and not latch["acted"]:
                    ed, dist, vid = min(serving, key=lambda r: r[1])
                    if (dist <= TRIGGER_DIST and rem > MIN_REMAIN
                            and q_of.get(ed, 0) <= Q_SKIP):
                        ext = min(MAX_EXT, max(6.0, 0.5 * rem))
                        try:
                            conn.trafficlight.setPhaseDuration(tls, rem + ext)
                            actions.append({"t": t, "type": "EXT", "phase": ph,
                                            "req": round(ext, 1), "bus": vid,
                                            "edge": ed, "dist": round(dist, 1),
                                            "queue": q_of.get(ed, 0),
                                            "remaining": round(rem, 1),
                                            "serving_q": q_of.get(ed, 0)})
                            latch["acted"] = True
                        except Exception:
                            pass
                # 2. ER: a bus waits, and the serving approaches carry NO demand
                elif waiting and not latch["acted"]:
                    ed, dist, vid = min(waiting, key=lambda r: r[1])
                    served_q = sum(q_of.get(e, 0) for e in green)
                    # "empty" must mean empty of ARRIVING traffic too. A halting
                    # count of 0 only says nothing has stopped yet; a platoon 40 m
                    # out would be cut off by the truncation.
                    served_approach = 0
                    if served_q == 0 and rem > 6.0:
                        for ge in green:
                            try:
                                for v in conn.edge.getLastStepVehicleIDs(ge):
                                    p = conn.vehicle.getLanePosition(v)
                                    if edge_len.get(ge, 0.0) - p <= 90.0:
                                        served_approach += 1
                            except Exception:
                                pass
                    if (served_q == 0 and served_approach == 0
                            and dist <= ER_LOOKAHEAD and rem > 6.0
                            and (t - (latch["start"] or t)) >= 8
                            and (t - last_action_t) > 20):
                        # truncate by a PRIORITY-sized amount, not to a minimum
                        # green: cutting 126 s of a 144 s phase is a plan rewrite,
                        # which is not what a TSP action is.
                        cut = min(rem - 3.0, MAX_ER_CUT)
                        try:
                            conn.trafficlight.setPhaseDuration(tls, rem - cut)
                            actions.append({"t": t, "type": "ER", "phase": ph,
                                            "req": round(cut, 1), "bus": vid,
                                            "edge": ed, "dist": round(dist, 1),
                                            "queue": 0, "serving_q": 0,
                                            "remaining": round(rem, 1)})
                            last_action_t = t
                            latch["acted"] = True
                        except Exception:
                            pass

        conn.simulationStep()
        t += 1

        # ---- record ------------------------------------------------------
        try:
            ph = int(conn.trafficlight.getPhase(tls))
            rem = round(float(conn.trafficlight.getNextSwitch(tls)) - t, 1)
        except Exception:
            ph, rem = None, None
        q = {}
        for ed in inc_edges:
            q[ed] = 0
            for ln in net.getEdge(ed).getLanes():
                try:
                    q[ed] += int(conn.lane.getLastStepHaltingNumber(ln.getID()))
                except Exception:
                    pass
        near = []
        for vid in conn.vehicle.getIDList():
            if not is_bus(conn, vid, bus_cache):
                continue
            try:
                x, y = conn.vehicle.getPosition(vid)
                spd = conn.vehicle.getSpeed(vid)
                road = conn.vehicle.getRoadID(vid)
            except Exception:
                continue
            if (x - cx) ** 2 + (y - cy) ** 2 <= NEAR_R ** 2:
                near.append([round(x, 1), round(y, 1)])
            if road in inc_edges and vid not in tracking:
                try:
                    pos = conn.vehicle.getLanePosition(vid)
                except Exception:
                    pos = 0.0
                tracking[vid] = {"enter": t, "edge": road, "enter_pos": pos}
        series.append({"t": t, "phase": ph, "rem": rem,
                       "q": q, "near": near})

        for vid, rec in list(tracking.items()):
            try:
                here = conn.vehicle.getRoadID(vid)
            except Exception:
                here = None
            if here is None or here not in inc_edges:
                ff = max(edge_len[rec["edge"]] - rec["enter_pos"], 0.0) / \
                    edge_free[rec["edge"]]
                done[vid] = {"enter": rec["enter"], "exit": t,
                             "edge": rec["edge"],
                             "delay": round((t - rec["enter"]) - ff, 1)}
                tracking.pop(vid, None)

    conn.close()
    print("[ACT] %-4s done: %d actions, %d bus passages at %s"
          % (policy, len(actions), len(done), jid))
    return {"policy": policy, "junction": jid, "tls": tls, "seed": seed,
            "incoming": inc_edges, "series": series, "actions": actions,
            "bus_delay": done, "tripinfo": trip, "phases_seen": phases}


def _tripinfo(path):
    out = {}
    if not os.path.exists(path):
        return out
    for tr in ET.parse(path).getroot().findall("tripinfo"):
        out[tr.get("id")] = {
            "bus": "bus" in (tr.get("vType", "") or "").lower(),
            "timeLoss": float(tr.get("timeLoss", 0.0)),
            "waiting": float(tr.get("waitingTime", 0.0))}
    return out


def pax_trip_mean(paths):
    """Pax-weighted mean time loss per COMPLETED trip, one value per replicate.

    Aggregating over completed trips instead of summing avoids the trap that a
    run which unblocks traffic completes more trips and therefore has a larger
    total. It still ignores vehicles stranded at the horizon, which matters here
    because this scenario can gridlock; the replicate range below makes that
    visible rather than hiding it.
    """
    out = []
    for p in paths:
        d = _tripinfo(p)
        num = den = 0.0
        for rec in d.values():
            w = PAX_BUS if rec["bus"] else PAX_CAR
            num += rec["timeLoss"] * w
            den += w
        out.append(num / den if den else 0.0)
    return out


def summarise(vals):
    if not vals:
        return None
    s = sorted(vals)
    return {"median": round(s[len(s) // 2], 1), "min": round(min(s), 1),
            "max": round(max(s), 1), "n": len(s)}


def paired_stats(base_path, tsp_path):
    """Pair trips BY VEHICLE ID.

    Summing time loss over each run's completed trips is invalid here: the sim
    ends at a fixed time, so a run that unblocks buses completes more of them and
    its total rises even though every trip got faster. On this scenario that
    artifact turned a -11% pax*s result into a +8% one. Pair on the vehicles both
    runs completed and compare per-trip means.
    """
    b, v = _tripinfo(base_path), _tripinfo(tsp_path)
    common = set(b) & set(v)
    out = {"completed_base": len(b), "completed_tsp": len(v),
           "paired": len(common)}
    pax_b = pax_v = 0.0
    for cls in ("bus", "car"):
        ids = [i for i in common if b[i]["bus"] == (cls == "bus")]
        if not ids:
            continue
        mb = sum(b[i]["timeLoss"] for i in ids) / len(ids)
        mv = sum(v[i]["timeLoss"] for i in ids) / len(ids)
        w = PAX_BUS if cls == "bus" else PAX_CAR
        out[cls] = {"n": len(ids), "base": round(mb, 1), "tsp": round(mv, 1),
                    "delta_pct": round(100.0 * (mv - mb) / mb, 2) if mb else 0.0,
                    "better": sum(1 for i in ids if b[i]["timeLoss"] - v[i]["timeLoss"] > 1),
                    "worse": sum(1 for i in ids if b[i]["timeLoss"] - v[i]["timeLoss"] < -1)}
        pax_b += sum(b[i]["timeLoss"] for i in ids) * w
        pax_v += sum(v[i]["timeLoss"] for i in ids) * w
    out["pax_s_base"] = round(pax_b, 0)
    out["pax_s_tsp"] = round(pax_v, 0)
    out["pax_s_delta_pct"] = round(100.0 * (pax_v - pax_b) / pax_b, 2) if pax_b else 0.0
    return out


def pick_event(base, tsp=None):
    """The bus the action helped most -- that is the mechanism worth drawing.

    Picking the WORST base-case bus instead would select one the rule cannot
    help (early red needs an empty serving phase, which rarely coincides with
    the moment the bus arrives), and the figure would show no effect.
    """
    if not base["bus_delay"]:
        return None
    if tsp is not None:
        shared = set(base["bus_delay"]) & set(tsp["bus_delay"])
        if shared:
            vid = max(shared, key=lambda k: base["bus_delay"][k]["delay"] -
                      tsp["bus_delay"][k]["delay"])
        else:
            vid = max(base["bus_delay"], key=lambda k: base["bus_delay"][k]["delay"])
    else:
        vid = max(base["bus_delay"], key=lambda k: base["bus_delay"][k]["delay"])
    rec = base["bus_delay"][vid]
    return {"vid": vid, "enter": rec["enter"], "exit": rec["exit"],
            "delay": rec["delay"], "edge": rec["edge"],
            "delay_after": tsp["bus_delay"].get(vid, {}).get("delay") if tsp else None}


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------
def render(base, tsp, jid, out_path, event, stats):
    net = sumolib.net.readNet(NET_FILE)
    node = net.getNode(jid)
    cx, cy = node.getCoord()
    lane_by_id, edge_lanes = {}, {}
    for e in net.getEdges():
        if e.getID().startswith(":"):
            continue
        for ln in e.getLanes():
            lane_by_id[ln.getID()] = ln
    for ed in base["incoming"]:
        edge_lanes[ed] = [ln.getID() for ln in net.getEdge(ed).getLanes()]

    t0 = event["enter"]
    # every action taken while this bus was on the approach -- usually TWO: an
    # early red to end the opposing green, then an extension of the new green.
    acts = [a for a in tsp["actions"]
            if event["enter"] - 60 <= a["t"] <= event["enter"] + 400]
    acts.sort(key=lambda a: a["t"])
    act_at = acts[0] if acts else None
    # anchor the panels on the ACTION, not on the bus's arrival: the two rows are
    # identical before the action fires, so a panel placed there shows nothing.
    if act_at is not None:
        ta = act_at["t"]
        pts = [max(ta - 55, 1), ta + 2, ta + 70]
    else:
        pts = [max(t0 - 8, 1), t0 + 35, t0 + 150]
    lookup = {}
    for st in (base, tsp):
        lookup[st["policy"]] = {r["t"]: r for r in st["series"]}

    qmax = 1
    for st in (base, tsp):
        for tt in pts:
            r = lookup[st["policy"]].get(tt)
            if r:
                qmax = max(qmax, max(r["q"].values() or [0]))

    fig = plt.figure(figsize=(13.4, 9.3))
    gs = fig.add_gridspec(3, 3, height_ratios=[1.0, 1.0, 1.42],
                          hspace=0.30, wspace=0.07)

    for row, (st, label) in enumerate(((base, "fixed-time plan\n(no action)"),
                                       (tsp, "with the priority\naction"))):
        for col, tt in enumerate(pts):
            ax = fig.add_subplot(gs[row, col])
            ax.add_collection(LineCollection(
                [ln.getShape() for ln in lane_by_id.values() if len(ln.getShape()) >= 2],
                colors="#dcdcdc", linewidths=0.4, zorder=0))
            r = lookup[st["policy"]].get(tt)
            if r is None:
                ax.set_axis_off()
                continue
            for ed, lns in edge_lanes.items():
                qe = r["q"].get(ed, 0)
                share = qe / float(len(lns)) if lns else 0.0
                col_ = "#ededed" if qe <= 0 else plt.cm.YlOrRd(
                    min(1.0, 0.25 + 0.75 * share / qmax))
                for lid in lns:
                    L = lane_by_id.get(lid)
                    if L is None:
                        continue
                    shp = L.getShape()
                    ax.plot([a[0] for a in shp], [a[1] for a in shp], color=col_,
                            lw=1.6 + 6.0 * (L.getWidth() / 3.5) *
                            (0.35 if qe <= 0 else 1.0),
                            solid_capstyle="butt", zorder=3)
                if qe > 0:
                    best, bd = None, -1.0
                    for lid in lns:
                        L = lane_by_id.get(lid)
                        if L is None:
                            continue
                        for (x, y) in L.getShape():
                            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                            if 55.0 <= d <= 130.0 and d > bd:
                                bd, best = d, (x, y)
                    if best is not None:
                        dx, dy = best[0] - cx, best[1] - cy
                        n = max((dx * dx + dy * dy) ** 0.5, 1e-6)
                        ax.annotate("%s: %d" % (ed, qe),
                                    (cx + dx / n * 118.0, cy + dy / n * 118.0),
                                    fontsize=6.6, color="#222222", ha="center",
                                    va="center", zorder=5, clip_on=False,
                                    bbox=dict(boxstyle="round,pad=0.16", fc="white",
                                              ec="#c8c8c8", lw=0.4, alpha=0.92))
            if r["near"]:
                ax.scatter([b[0] for b in r["near"]], [b[1] for b in r["near"]],
                           s=16, marker="s", c="#c0392b", edgecolors="white",
                           linewidths=0.4, zorder=7)
            ax.plot([cx], [cy], marker="s", ms=4, color="#1f3b73", zorder=6)
            head = "t = %d s" % tt
            if r.get("phase") is not None:
                head += "   phase %d, %.0f s left" % (r["phase"], r["rem"])
            ax.set_title(head, fontsize=8.5)
            ax.set_aspect("equal")
            ax.set_xticks([])
            ax.set_yticks([])
            for s in ax.spines.values():
                s.set_visible(False)
            R = 108.0
            ax.set_xlim(cx - R * 1.18, cx + R * 1.18)
            ax.set_ylim(cy - R * 1.18, cy + R * 1.18)
            if col == 0:
                ax.set_ylabel(label, fontsize=8.5, labelpad=4)
        # end col

    if acts:
        ax = fig.axes[4] if len(fig.axes) > 4 else fig.axes[-1]
        txt = "  |  ".join("%s %+.0f s @ t=%d (phase %d)"
                          % (a["type"], a["req"], a["t"], a["phase"])
                          for a in acts[:2])
        ax.annotate("%s\nbus %s, %.0f m from the stop line"
                    % (txt, acts[0]["bus"].split(".")[0], acts[0]["dist"]),
                    xy=(0.5, -0.03), xycoords="axes fraction", ha="center",
                    va="top", fontsize=7.0, color="#8e2b20")
    if len(fig.axes) > 1:
        fig.axes[1].annotate("same bus, same junction: waits out the opposing green",
                             xy=(0.5, -0.03), xycoords="axes fraction",
                             ha="center", va="top", fontsize=7.2, color="#555555")

    # The scenario is deterministic (see _sumo_snaps/rebuild_kg_net.py), so the
    # two rows are identical until the first action: the left panel matches in
    # both signal state and queue. Everything after that is the action's doing.
    fig.text(0.01, 0.005,
             "Same seed, deterministic scenario: the two rows are identical up to the "
             "decision, so the divergence drawn here is caused by the action. The "
             "numbers at right are paired over all %d trips."
             % ((stats or {}).get("paired") or {}).get("paired", 0),
             fontsize=6.6, color="#666666", ha="left", va="bottom")

    # --- time series: EVERY approach, so the trade-off is visible ---------
    # Plotting only the bus's street shows the gain and hides who paid for it.
    # Group the approaches by signal phase: the bus's own green, the other
    # movements that share it, and the opposing green that gets truncated.
    link_edge, phases = link_map(jid)
    inc = list(base["incoming"])
    bus_edge = event["edge"]
    serv = [i for i in range(len(phases))
            if bus_edge in green_edges(link_edge, phases, i)]
    serv = serv[0] if serv else None
    g_bus = [bus_edge]
    g_same = [e for e in inc if e != bus_edge and serv is not None
              and e in green_edges(link_edge, phases, serv)]
    g_opp = [e for e in inc if e not in g_bus and e not in g_same]
    groups = [(g_bus, "bus approach", "the bus approach"),
              (g_same, "same green", "same green as the bus"),
              (g_opp, "opposing green", "the opposing green it truncates")]
    # a negative left edge (t0 < 100) would show empty space before the run
    lo, hi = max(t0 - 100, 1), t0 + 260

    def series_of(st, edges):
        rows = [r for r in st["series"] if lo <= r["t"] <= hi]
        return ([r["t"] for r in rows],
                [sum(r["q"].get(e, 0) for e in edges) for r in rows])

    # an approach group that never queues carries no information -- drawing it
    # as a flat line on a +/-0.05 axis is worse than omitting it
    live = []
    for edges, short, lab in groups:
        peak = max([max(series_of(st, edges)[1] or [0]) for st in (base, tsp)] + [0])
        if edges and peak > 0:
            live.append((edges, short, lab, peak))

    n_q = max(len(live), 1)
    # one extra row: the cumulative view, so a level that looks harmless per
    # cycle still shows up as area once it is integrated over the run. Two
    # panels side by side (one per run) with a shared y axis, because the
    # junction TOTAL barely moves -- what moves is who carries it.
    sub = gs[2, :2].subgridspec(n_q + 1, 2, hspace=0.46, wspace=0.10,
                                height_ratios=[1.0] * n_q + [1.55])
    axq_all = [fig.add_subplot(sub[i, :]) for i in range(n_q)]
    axcum_b = fig.add_subplot(sub[n_q, 0])
    axcum_t = fig.add_subplot(sub[n_q, 1], sharey=axcum_b)
    for k, (axq, (edges, short, lab, peak)) in enumerate(zip(axq_all, live)):
        # The two runs are IDENTICAL before the action, so a thin line pair just
        # hides the red one. Draw the fixed-time plan as a wide translucent band
        # and the action run as a thin line on top: coincidence reads as a grey
        # band, divergence reads as the red line leaving it.
        for st, colour, rlab, lw, al, z in (
                (base, "#7f8c8d", "fixed-time plan", 3.0, 0.55, 1),
                (tsp, "#c0392b", "with action", 1.4, 1.0, 3)):
            tt, qq = series_of(st, edges)
            if tt:
                axq.step(tt, qq, where="post", color=colour, lw=lw,
                         alpha=al, zorder=z, label=rlab if k == 0 else None)
        for a in (acts[:2] if acts else []):
            axq.axvline(a["t"], color="#8e2b20", ls="--", lw=0.9)
        axq.set_xlim(lo, hi)
        axq.set_ylim(-0.3, max(peak, 1) * 1.14 + 0.6)
        axq.tick_params(labelsize=7)
        axq.set_ylabel("%s%s" % (short, "\nvehicles" if k == 0 else ""),
                       fontsize=6.9)
        if k == 0:
            axq.legend(fontsize=6.8, frameon=False, loc="upper right")
            if acts:
                axq.annotate("action t = %d s" % acts[0]["t"],
                             (acts[0]["t"], 0.42),
                             xycoords=("data", "axes fraction"),
                             fontsize=7, color="#8e2b20", ha="right",
                             va="bottom", annotation_clip=False)
        if k < len(live) - 1:
            axq.set_xticklabels([])
        for s in ("top", "right"):
            axq.spines[s].set_visible(False)
    axq_all[0].set_title(
        "queue on every approach at %s  (%s)"
        % (jid, ", ".join(sorted({e for edges, _s, _l, _p in live for e in edges}))),
        fontsize=7.6, loc="left")
    axq_all[-1].set_xticklabels([])

    # --- cumulative queue ------------------------------------------------
    # Integrate each group's queue over time: veh*s of standing queue. The two
    # runs are identical before the action, so any vertical gap is the queue
    # burden the decision moved -- and the stack shows whether it moved it OFF
    # the bus street or merely ONTO the one it truncated.
    def cum_of(st, edges):
        rows = [r for r in st["series"] if r["t"] <= hi]
        ts, cs, acc = [], [], 0.0
        for i, r in enumerate(rows):
            if r["t"] < lo:
                continue
            ts.append(r["t"])
            cs.append(acc)
            dt = (rows[i + 1]["t"] - r["t"]) if i + 1 < len(rows) else 1
            acc += sum(r["q"].get(e, 0) for e in edges) * dt
        return ts, cs

    cum_col = ["#1f3f8f", "#4a9b6e", "#d95f0e"]
    totals = {}
    for st, axc, head in ((base, axcum_b, "fixed-time plan"),
                          (tsp, axcum_t, "with the action")):
        ts, ys = None, []
        for edges, _s, _l, _p in live:
            ts, c_ = cum_of(st, edges)
            ys.append(c_)
        if not ts:
            axc.set_axis_off()
            continue
        axc.stackplot(ts, *ys, colors=cum_col[:len(ys)], alpha=0.85, lw=0.4,
                      edgecolor="white", labels=[s for _e, s, _l, _p in live])
        tot = [sum(v) for v in zip(*ys)]
        totals[head] = tot[-1]
        axc.plot(ts, tot, color="#222222", lw=0.9)
        for a in (acts[:2] if acts else []):
            axc.axvline(a["t"], color="#8e2b20", ls="--", lw=0.9)
        axc.set_xlim(lo, hi)
        axc.tick_params(labelsize=7)
        axc.set_title("%s   total %.0f veh$\\cdot$s" % (head, tot[-1]),
                      fontsize=7.4, loc="left")
        for s in ("top", "right"):
            axc.spines[s].set_visible(False)
    axcum_b.set_ylabel("cumulative queue\nveh$\\cdot$s (stacked)", fontsize=6.9)
    # shared y axis: the right panel's ticks would land on the left panel's fill
    axcum_t.tick_params(labelleft=False)
    d_tot = totals.get("with the action", 0.0) - totals.get("fixed-time plan", 0.0)
    if len(live) > 1:
        axcum_b.legend(fontsize=6.4, frameon=False, loc="upper left")
    if totals:
        axcum_t.set_title(
            "with the action   total %.0f veh$\\cdot$s  (%+.0f than the plan)"
            % (totals.get("with the action", 0.0), d_tot),
            fontsize=7.4, loc="left", color="#8e2b20")
    axcum_b.set_xlabel("simulation time (s)", fontsize=8)
    axcum_t.set_xlabel("simulation time (s)", fontsize=8)

    # --- verdict ----------------------------------------------------------
    axt = fig.add_subplot(gs[2, 2])
    axt.set_axis_off()
    L = ["bus %s at %s" % (event["vid"].split(".")[0], jid),
         "  fixed-time  %+.0f s delay" % event["delay"]]
    d_t = tsp["bus_delay"].get(event["vid"], {}).get("delay")
    if d_t is not None:
        L.append("  with action %+.0f s" % d_t)
        L.append("  saved       %+.0f s" % (event["delay"] - d_t))
    else:
        L.append("  with action  not detected")
    arms = (stats or {}).get("arms", {})
    if arms.get("base") and arms.get("tsp"):
        b, v = arms["base"], arms["tsp"]
        L += ["", "pax-weighted s/trip  (%d reps)" % b["n"],
              "  fixed   %6.1f  [%.1f-%.1f]" % (b["median"], b["min"], b["max"]),
              "  action  %6.1f  [%.1f-%.1f]" % (v["median"], v["min"], v["max"])]
        chg = 100.0 * (v["median"] - b["median"]) / b["median"] if b["median"] else 0.0
        # is the effect larger than the replicate spread?
        spread = 100.0 * max(b["max"] - b["min"], v["max"] - v["min"]) / b["median"]
        verdict = ("within noise" if abs(chg) < spread else "exceeds noise")
        L += ["  change  %+.1f%%   rep spread %.1f%%  -> %s"
              % (chg, spread, verdict)]
        pr = (stats or {}).get("paired") or {}
        for cls, lab in (("bus", "bus"), ("car", "car")):
            d = pr.get(cls)
            if d:
                L.append("  %-6s %6.1f -> %6.1f s %+.1f%%"
                         % (lab, d["base"], d["tsp"], d["delta_pct"]))
    elif stats:
        L += ["", "paired by vehicle id (n=%d)" % stats.get("paired", 0)]
        for cls, lab in (("bus", "bus  s/trip"), ("car", "car  s/trip")):
            d = stats.get(cls)
            if d:
                L.append("%-12s %6.1f  %6.1f  %+.1f%%"
                         % (lab, d["base"], d["tsp"], d["delta_pct"]))
    axt.text(0.0, 1.0, "\n".join(L), va="top", ha="left", fontsize=7.1,
             family="monospace", transform=axt.transAxes)

    fig.suptitle("%s -- the decision and what it changes (seed %d)"
                 % (jid, base.get("seed", 300)), fontsize=10)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--junction", default="n39576")
    ap.add_argument("--seed", type=int, default=300)
    ap.add_argument("--end", type=int, default=4500)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--reps", type=int, default=3,
                    help="replicates per arm; this scenario is NOT reproducible "
                         "on a fixed seed, so one run per arm cannot separate an "
                         "effect from the noise")
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--net", default=None)
    ap.add_argument("--state-in", default=None)
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    global SCEN, NET_FILE
    if args.scenario:
        SCEN = args.scenario
    if args.net:
        NET_FILE = args.net
    print("[ACT] scenario: %s" % os.path.basename(SCEN))

    if args.state_in:
        blob = json.load(open(args.state_in, encoding="utf-8"))
        base, tsp, event, stats = (blob["base"], blob["tsp"],
                                   blob["event"], blob["stats"])
        if not stats.get("paired"):
            b0 = os.path.join(args.out, "tripinfo_base0.xml")
            t0 = os.path.join(args.out, "tripinfo_tsp0.xml")
            if os.path.exists(b0) and os.path.exists(t0):
                stats["paired"] = paired_stats(b0, t0)
    else:
        evals = {"base": [], "tsp": []}
        base = tsp = None
        for i in range(args.reps):
            print("[ACT] replicate %d/%d: fixed-time plan ..." % (i + 1, args.reps))
            b = run("base", args.junction, args.seed, args.end, "base%d" % i)
            print("[ACT] replicate %d/%d: with the priority action ..."
                  % (i + 1, args.reps))
            t = run("tsp", args.junction, args.seed, args.end, "tsp%d" % i)
            evals["base"].append(b)
            evals["tsp"].append(t)
            if base is None:
                base, tsp = b, t

        event = pick_event(base, tsp)
        if event is None:
            raise SystemExit("no bus reached %s" % args.junction)
        stats = {"arms": {"base": summarise(pax_trip_mean([r["tripinfo"] for r in evals["base"]])),
                          "tsp": summarise(pax_trip_mean([r["tripinfo"] for r in evals["tsp"]]))},
                 "paired": paired_stats(base["tripinfo"], tsp["tripinfo"])}
        path = os.path.join(args.out, "action_states.json")
        json.dump({"base": base, "tsp": tsp, "event": event, "stats": stats},
                  open(path, "w", encoding="utf-8"), indent=1)
        print("[ACT] event: %s on %s, %.0f s -> %s s"
              % (event["vid"], event["edge"], event["delay"],
                 event.get("delay_after")))
        for arm in ("base", "tsp"):
            s = stats["arms"][arm]
            print("[ACT] %-4s pax-weighted s/trip: median %.1f  [%.1f-%.1f] over %d reps"
                  % (arm, s["median"], s["min"], s["max"], s["n"]))
        print("[ACT] states -> %s" % path)

    print("[ACT] %d actions fired" % len(tsp["actions"]))
    for a in tsp["actions"][:12]:
        print("      t=%-5d %-3s phase %d +%.0f s  bus %s  %s %.0f m"
              % (a["t"], a["type"], a["phase"], a["req"],
                 a["bus"].split(".")[0], a["edge"], a["dist"]))

    for fmt in ("pdf", "png"):
        p = os.path.join(args.out, "action_%s.%s" % (args.junction, fmt))
        render(base, tsp, args.junction, p, event, stats)
        print("[ACT] -> %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
