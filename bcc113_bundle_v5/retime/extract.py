#!/usr/bin/env python3
"""extract.py -- offline retiming inputs from Aimsun logs + SUMO plan.

Reads the newest Aimsun TSP log's [PLAN], [PHASEMAP] and post-warmup
[FLOW_STAGE] lines plus SUMO tls.tll.xml and junction centroids, and writes:
  measurements.json -- per junction: cycle, phases, green stages (with
                       turnings/lanes), measured main_x, side flows, queues
  plan.json         -- SUMO static plan + centroid geometry + travel times

Usage: python extract.py [--log PATH] [--outdir DIR]
"""
import csv
import glob
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE = os.path.join(HERE, "..")
LOGDIR = os.path.join(BUNDLE, "logan_road_new", "logs")
SUMO_SCEN = r"Z:\tsp\sumo_hpc\sumo_bridge\logan_scenario"
WARM_S = 600.0
SAT_PER_LANE = 1800.0


def newest(pattern):
    fs = sorted(glob.glob(pattern), key=os.path.getmtime)
    return fs[-1] if fs else None


def build_schedule(results_dir, back_s=950.0):
    """[(arm, seed, t0_wall, t1_wall)] from result-dir mtimes.

    One Aimsun log spans a whole multi-arm session, but FLOW_STAGE regimes
    are arm-dependent (TSP changes x/queues). Attribute each line by wall
    clock: a run's results dir mtime ~= its end; window back covers the run.
    """
    import datetime as _dt
    sched = []
    if not os.path.isdir(results_dir):
        return sched
    for d in sorted(glob.glob(os.path.join(results_dir, "*_seed*_*"))):
        bn = os.path.basename(d)
        m = re.search(r"^(.+)_seed(\d+)_", bn)
        if not m:
            continue
        arm = m.group(1)
        seed = m.group(2)
        try:
            t1 = os.path.getmtime(d)
        except Exception:
            continue
        sched.append((arm, seed, t1 - back_s, t1))
    return sched


def log_wall_to_epoch(line, file_epoch):
    m = re.match(r"(\d+):(\d+):(\d+)\s*\|", line)
    if not m:
        return None
    import datetime as _dt
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
    base = _dt.datetime.fromtimestamp(file_epoch)
    t = base.replace(hour=h, minute=mi, second=s, microsecond=0)
    if (t - base).total_seconds() < -12 * 3600:
        t += _dt.timedelta(days=1)
    if (t - base).total_seconds() > 12 * 3600:
        t -= _dt.timedelta(days=1)
    return t.timestamp()


def parse_log(path, arm_filter="NO_TSP", sched=None):
    """One log = one run (AAPIInit opens a fresh log per replication).

    FLOW_STAGE regimes are arm-dependent, so aggregate only logs passed for
    this arm (use --log repeatedly). PLAN/PHASEMAP are arm-independent base
    plan data (first tick) and merge across all logs given.
    """
    plans, phasemap, stages = {}, {}, {}
    for line in open(path, encoding="utf-8", errors="replace"):
        if "[PLAN]" in line:
            m = re.search(r"inter=(\d+).*?n_ph=(\d+) durs=(\{[^}]*\})"
                          r".*?cycle_sum=([\d.]+)s cfg_cyc=([\d.]+)s "
                          r"bus_ph=(\d+) bus_dur=([\d.]+)s coord_ph=(\d+)",
                          line)
            if m:
                iid = m.group(1)
                durs = {int(k): float(v) for k, v in
                        re.findall(r"(\d+):\s*([\d.]+)", m.group(3))}
                plans[iid] = {
                    "n_ph": int(m.group(2)), "durs": durs,
                    "cycle_sum": float(m.group(4)),
                    "cfg_cyc": float(m.group(5)),
                    "bus_ph": int(m.group(6)),
                    "bus_dur": float(m.group(7)),
                    "coord_ph": int(m.group(8)),
                }
        elif "[PHASEMAP]" in line:
            m = re.search(r"inter=(\d+)\s+(.*)", line)
            if not m:
                continue
            iid = m.group(1)
            pmap = {}
            for pm in re.finditer(
                    r"ph(\d+)=([\d.]+)s turns=(\d+)\(main(\d+)/side(\d+)\)"
                    r"\s*\[([^\]]*)\]", m.group(2)):
                origins = {}
                for om in re.finditer(r"(\d+):(\d+)ln", pm.group(6)):
                    origins[om.group(1)] = int(om.group(2))
                pmap[int(pm.group(1))] = {
                    "dur_s": float(pm.group(2)),
                    "n_turns": int(pm.group(3)),
                    "n_main": int(pm.group(4)),
                    "n_side": int(pm.group(5)),
                    "origins": origins,
                }
            if pmap:
                phasemap[iid] = pmap
        elif "[FLOW_STAGE]" in line:
            m = re.search(r"inter=(\d+) t=(\d+) stage=(\S+) main_x=([\d.]+) "
                          r"side_max=([\d.]+)vph queue=([\d.]+)", line)
            if m and float(m.group(2)) >= WARM_S:
                s = stages.setdefault(m.group(1), {
                    "x": [], "side": [], "q": [], "stage": []})
                s["x"].append(float(m.group(4)))
                s["side"].append(float(m.group(5)))
                s["q"].append(float(m.group(6)))
                s["stage"].append(m.group(3))
    return plans, phasemap, stages


def agg(v):
    v = [x for x in v if x == x]
    if not v:
        return {"mean": 0.0, "p90": 0.0, "n": 0}
    s = sorted(v)
    return {"mean": sum(s) / len(s), "p90": s[min(len(s) - 1,
              int(len(s) * 0.9))], "n": len(s)}


def load_tls():
    out = {}
    p = os.path.join(SUMO_SCEN, "tls.tll.xml")
    if not os.path.isfile(p):
        return out
    for tl in ET.parse(p).getroot().iter("tlLogic"):
        iid = str(tl.get("id")).lstrip("n")
        out[iid] = {
            "offset": float(tl.get("offset", 0.0)),
            "phases": [{"duration": float(ph.get("duration")),
                        "state": ph.get("state")}
                       for ph in tl.findall("phase")],
        }
    return out


def load_centroids():
    pts = {}
    f = newest(os.path.join(LOGDIR, "junction_centroids_*.csv"))
    if f:
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            extra = {k: r[k] for k in r
                     if k not in ("junction_id", "x", "y")}
            pts[str(r["junction_id"])] = (float(r["x"]), float(r["y"]),
                                          extra)
    return pts


def main(argv):
    logs = []
    outdir = HERE
    it = iter(argv)
    for a in it:
        if a == "--log":
            logs.append(next(it))
        elif a == "--outdir":
            outdir = next(it)
        elif a == "--arm":
            next(it)  # accepted for compatibility; logs are pre-selected
    if not logs:
        logs = [newest(os.path.join(LOGDIR, "Aimsun_TSP_Log_*.txt"))]
    logs = [l for l in logs if l and os.path.isfile(l)]
    if not logs:
        print("no log found")
        return 1
    print(f"logs ({len(logs)}):")
    for l in logs:
        print("  ", l)
    plans, phasemap, stages = {}, {}, {}
    for l in logs:
        p, pm, st = parse_log(l)
        plans.update(p)
        phasemap.update(pm)
        for j, s in st.items():
            d = stages.setdefault(j, {"x": [], "side": [], "q": [],
                                      "stage": []})
            for k in d:
                d[k].extend(s[k])
    print(f"plans={len(plans)} phasemaps={len(phasemap)} "
          f"stage-series={len(stages)}")
    tls = load_tls()
    print(f"tls junctions={len(tls)}")
    pts = load_centroids()
    print(f"centroids={len(pts)}")

    meas = {}
    for iid, pl in plans.items():
        st = stages.get(iid, {"x": [], "side": [], "q": [], "stage": []})
        # green stages: phases with turnings (fallback: two longest phases)
        pm = phasemap.get(iid, {})
        if pm:
            greens = [ph for ph, e in pm.items() if e["n_turns"] > 0]
        else:
            greens = []
        if len(greens) < 2:
            greens = sorted(pl["durs"], key=lambda p: -pl["durs"][p])[:2]
        # main stage = the one holding bus-phase turnings (bus phase itself);
        # side stage = the other green. side flow/lanes from phasemaps.
        side_flow = agg(st["side"])["mean"]
        side_lanes, side_origins = 0, []
        for ph, e in pm.items():
            if e["n_side"] > 0:
                for s, ln in e["origins"].items():
                    if s not in side_origins:
                        side_origins.append(s)
                        side_lanes += ln
        meas[iid] = {
            "cycle_sum": pl["cycle_sum"],
            "bus_ph": pl["bus_ph"],
            "bus_dur": pl["bus_dur"],
            "green_stages": sorted(greens),
            "stage_durs": {str(p): pl["durs"].get(p, 0.0) for p in greens},
            "main_x": agg(st["x"]),
            "side_flow_vph": agg(st["side"]),
            "queue_veh": agg(st["q"]),
            "side_lanes": side_lanes,
            "side_origins": side_origins,
            "phasemap_phases": len(pm),
        }
    with open(os.path.join(outdir, "measurements.json"), "w",
              encoding="utf-8") as f:
        json.dump(meas, f, indent=1, sort_keys=True)

    # geometry: centroid + order along corridor axis (17249 -> 21895)
    def proj(iid):
        p = pts.get(iid)
        a = pts.get("17249")
        b = pts.get("21895")
        if not (p and a and b):
            return 0.0
        vx, vy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(vx, vy) or 1.0
        return ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / n

    # geometry: corridor order from the SUMO graph diameter (through-route),
    # NOT centroid projection (the road curves; projection folds it) and NOT
    # route-group order (bus visit order, not road order). corridor.json is
    # generated by shortest-path chaining (see segs.py provenance); segment
    # lengths are graph shortest-path metres.
    corr = {}
    _cf = os.path.join(outdir, "corridor.json")
    if os.path.isfile(_cf):
        try:
            corr = json.load(open(_cf, encoding="utf-8"))
        except Exception:
            corr = {}
    order = [i for i in corr.get("order", []) if i in meas] + \
            [i for i in meas if i not in corr.get("order", [])]
    dist = dict(corr.get("seg_dist_m", {}))
    plan = {"tls": tls,
            "centroids": {k: {"x": v[0], "y": v[1], **v[2]}
                          for k, v in pts.items()},
            "corridor_order": order,
            "seg_dist_m": dist}
    with open(os.path.join(outdir, "plan.json"), "w",
              encoding="utf-8") as f:
        json.dump(plan, f, indent=1, sort_keys=True)
    print(f"order ({len(order)}): {' '.join(order)}")
    print("wrote measurements.json + plan.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
