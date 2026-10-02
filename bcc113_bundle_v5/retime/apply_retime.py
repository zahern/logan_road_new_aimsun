#!/usr/bin/env python3
"""apply_retime.py -- load a retime.csv plan into a new SUMO scenario.

Transfers the DESIGN (green shares, bus-green-start fraction), not absolute
seconds: Aimsun cycles (80-300 s) differ from SUMO's (101.5 s). Per junction:
  - main green phase = the phase whose green links carry the through-route
    movements (exact through edge-pairs; fallback: longer base green)
  - green budget split pro-rata by retime shares (yellows untouched, cycle
    conserved), offsets set so bus-green starts at the retimed fraction.
  - sequence: v1 has no swaps (DP-verified degenerate for bus progression);
    stage blocks are NOT reordered (Aimsun 3-5 stages vs SUMO 2 greens would
    need movement-level mapping -- v2).

Usage: python apply_retime.py [--retime FILE] [--out SCEN_DIR]
  Writes a new scenario dir beside logan_scenario + rebuilds the .net.xml
  with the local netconvert. SUMO-side equivalent of the Aimsun init applier
  (ECI splits) + startup OC-walk (offsets) from the retiming scope.
"""
import csv
import heapq
import math
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = r"Z:\tsp\sumo_hpc\sumo_bridge"
SRC = os.path.join(BRIDGE, "logan_scenario")
NETCONVERT = r"C:\Program Files (x86)\Eclipse\Sumo\bin\netconvert.exe"
COPY_FILES = ["nodes.nod.xml", "edges.edg.xml", "connections.con.xml",
              "detectors.add.xml", "demand.add.xml",
              "logan_road_new.sumocfg", "detectors_meta.json", "pt_meta.json"]


def load_retime(path):
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        j = str(r["junction"])
        if (r.get("note", "") or "").strip() == "kept":
            continue  # no measurement basis: leave the base plan alone
        greens = {}
        for part in str(r["stage_greens_s"]).split(";"):
            if "=" in part:
                k, v = part.split("=")
                greens[int(k)] = float(v)
        order = [int(x) for x in str(r["stage_order"]).split(";") if x]
        bus = int(r["bus_stage"])
        tot = sum(greens.values()) or 1.0
        side = tot - greens.get(bus, 0.0)
        out[j] = {
            "cycle": float(r["cycle_s"]),
            "bus_stage": bus,
            "main_share": greens.get(bus, 0.0) / tot,
            "side_share": side / tot,
            "off_frac": (float(r["offset_bus_green_start_s"]) /
                         float(r["cycle_s"])) % 1.0,
        }
    return out


def graph(scen):
    nodes = {}
    for n in ET.parse(os.path.join(scen, "nodes.nod.xml")).getroot().iter(
            "node"):
        nodes[n.get("id")] = (float(n.get("x")), float(n.get("y")))
    adj = {}
    for e in ET.parse(os.path.join(scen, "edges.edg.xml")).getroot().iter(
            "edge"):
        f, t = e.get("from"), e.get("to")
        if f in nodes and t in nodes:
            w = math.hypot(nodes[f][0] - nodes[t][0],
                           nodes[f][1] - nodes[t][1])
            adj.setdefault(f, []).append((t, w, e.get("id")))
    return nodes, adj


def path_edges(adj, src, dst):
    D = {src: (0.0, None, None)}
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == dst:
            break
        if d > D[u][0]:
            continue
        for v, w, eid in adj.get(u, []):
            nd = d + w
            if nd < D.get(v, (1e18,))[0]:
                D[v] = (nd, u, eid)
                heapq.heappush(pq, (nd, v))
    if dst not in D:
        return []
    out, cur = [], dst
    while cur != src:
        _, p, eid = D[cur]
        out.append(eid)
        cur = p
    return out[::-1]


def main(argv):
    retime = os.path.join(HERE, "retime_v1.csv")
    outdir = os.path.join(BRIDGE, "logan_scenario_retimev1")
    offsets_only = False
    it = iter(argv)
    for a in it:
        if a == "--retime":
            retime = next(it)
        elif a == "--out":
            outdir = next(it)
        elif a == "--offsets-only":
            offsets_only = True
    rt = load_retime(retime)
    print(f"retime rows: {len(rt)}")
    _, adj = graph(SRC)
    order = json_order()
    # through edges between consecutive tls along the corridor order --
    # BOTH traversal directions (two-way corridor; pairing needs either).
    thru = set()
    for a, b in zip(order, order[1:]):
        for eid in path_edges(adj, "n" + a, "n" + b):
            thru.add(eid)
        for eid in path_edges(adj, "n" + b, "n" + a):
            thru.add(eid)
    print(f"through edges: {len(thru)}")

    # connections: (tl, linkIndex) -> (fromEdge, toEdge) from the BUILT net
    # (connections.con.xml carries no tl linkage; net.xml does).
    conns = {}
    _net = ET.parse(os.path.join(SRC, "logan_road_new.net.xml")).getroot()
    for c in _net.iter("connection"):
        tl = c.get("tl")
        li = c.get("linkIndex")
        if tl is None or li is None:
            continue
        conns.setdefault(tl, {})[int(li)] = (c.get("from"), c.get("to"))

    os.makedirs(outdir, exist_ok=True)
    for f in COPY_FILES:
        s = os.path.join(SRC, f)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(outdir, f))
    tls = ET.parse(os.path.join(SRC, "tls.tll.xml")).getroot()
    n_main_found, n_fallback = 0, 0
    for tl in tls.iter("tlLogic"):
        tid = tl.get("id")
        j = tid.lstrip("n")
        if j not in rt:
            continue
        phases = tl.findall("phase")
        greens = [i for i, p in enumerate(phases)
                  if "G" in (p.get("state") or "")
                  or "g" in (p.get("state") or "")]
        if len(greens) != 2:
            print(f"  SKIP {tid}: {len(greens)} green phases (v1: 2 only)")
            continue
        # main green = phase whose green links run the through route
        cmap = conns.get(tid, {})
        best, bestscore = greens[0], -1
        for gi in greens:
            st = phases[gi].get("state") or ""
            score = 0
            for li, ch in enumerate(st):
                if ch not in ("G", "g"):
                    continue
                if li in cmap:
                    fe, te = cmap[li]
                    if fe in thru and te in thru:
                        score += 2
            if score > bestscore:
                best, bestscore = gi, score
        if bestscore <= 0:
            # fallback: longer base green
            best = max(greens,
                       key=lambda i: float(phases[i].get("duration")))
            n_fallback += 1
        else:
            n_main_found += 1
        side = [g for g in greens if g != best][0]
        gsum = sum(float(phases[i].get("duration")) for i in greens)
        if not offsets_only:
            # Splits are the REFUTED half: A/B 2026-09-28 (Aimsun -46%,
            # SUMO obj +0.1..+10.8% with per-vehicle delay DOWN 7-9% and
            # throughput down 5-7%) showed automated Webster shares starve a
            # main-saturated corridor. Offsets-only keeps the hand-tuned
            # SCATS greens and moves only the stagger.
            g_main = round(gsum * rt[j]["main_share"], 1)
            g_side = round(gsum - g_main, 1)
            phases[best].set("duration", str(g_main))
            phases[side].set("duration", str(g_side))
        # offset: current main-green start -> retimed fraction
        cyc = sum(float(p.get("duration")) for p in phases)
        s0 = sum(float(phases[i].get("duration")) for i in range(best))
        s1 = rt[j]["off_frac"] * cyc
        tl.set("offset", str(int(round((s1 - s0) % cyc))))
    print(f"main-by-through: {n_main_found}, fallback-longest: {n_fallback}")
    tll_out = os.path.join(outdir, "tls.tll.xml")
    ET.ElementTree(tls).write(tll_out, encoding="utf-8",
                              xml_declaration=True)
    # rebuild net
    cmd = [NETCONVERT, "-n", os.path.join(outdir, "nodes.nod.xml"),
           "-e", os.path.join(outdir, "edges.edg.xml"),
           "-x", os.path.join(outdir, "connections.con.xml"),
           "-o", os.path.join(outdir, "logan_road_new.net.xml"),
           "--no-turnarounds", "--tls.default-type", "static",
           "--offset.disable-normalization",
           "-i", tll_out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-4000:])
        return 1
    print("net rebuilt:", os.path.getsize(
        os.path.join(outdir, "logan_road_new.net.xml")) // 1024, "KB")
    # verify: offsets + greens landed in the built net
    import re as _re
    net = open(os.path.join(outdir, "logan_road_new.net.xml"),
               encoding="utf-8", errors="replace").read()
    offs = sorted(set(_re.findall(r'offset="(\d+)"', net)))
    print("distinct offsets in built net:", offs[:8],
          f"({len(offs)} total)")
    return 0


def json_order():
    import json as _j
    cf = os.path.join(HERE, "corridor.json")
    return _j.load(open(cf, encoding="utf-8"))["order"]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
