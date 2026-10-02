#!/usr/bin/env python3
"""plan_to_tls.py -- real Aimsun signal plans into a SUMO scenario.

Fixes the export gap: build_sumo_scenario.py's converted plans fell through to
the 2-phase synthetic fallback because the dump carried empty sg_states and
signal_groups. This converter uses the LIVE plan dump (engine [PLANDUMP],
2026-09-28: per-junction live durations, phase->signal-groups, SG->turning
pairs) captured in-sim, and writes a faithful N-phase tlLogic per junction:
  - green phases -> 'G'/'r' rows from the turning->link map
  - intergreen phases (empty turns) -> yellow rows over the preceding greens
  - pedestrian-only phases (sgs present, zero turnings) -> all-red rows that
    preserve the cycle and the pedestrian interval
  - cycles/offsets: cycles are the real Aimsun values; offsets default 0
    (matches the current synthetic file) so this isolates "the real plan".
Unmatched vehicle links (typically synthesized reverse edges Aimsun never
modeled) are grouped onto the phase that already serves the most turnings
from the same approach; every unmatched link is counted and reported.

Usage: python plan_to_tls.py --dump plan_dump_*.json [--out DIR] [--offset-file retime_v1.csv]
"""
import csv
import json
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

try:
    sys.path.insert(0, r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
                        r"\logan_road_new")
    from intersection_configs import INTERSECTIONS_CONFIG as _IC
    SEC_GROUPS = {str(k): {
        "main": set(int(s) for s in v.get("MainSections", [])),
        "side": set(int(s) for s in v.get("SideSections", []))}
        for k, v in _IC.items() if isinstance(v, dict)}
except Exception:
    SEC_GROUPS = {}


def edges_graph(scen):
    """edge id -> (from_node, to_node); reverse-pair map for synth edges."""
    rev = {}
    pairs = []
    for e in ET.parse(os.path.join(scen, "edges.edg.xml")).getroot().iter(
            "edge"):
        pairs.append((e.get("id"), e.get("from"), e.get("to")))
    for a, fa, ta in pairs:
        for b, fb, tb in pairs:
            if b != a and fb == ta and tb == fa:
                rev[a] = b
                rev[b] = a
                break
    return rev


def conns_from_net(scen):
    conns = {}
    for c in ET.parse(os.path.join(scen, "logan_road_new.net.xml")
                      ).getroot().iter("connection"):
        tl, li = c.get("tl"), c.get("linkIndex")
        if tl is None or li is None:
            continue
        conns.setdefault(tl, {})[int(li)] = (c.get("from"), c.get("to"))
    return conns


def sec(edge_id):
    try:
        return int(str(edge_id).lstrip("s"))
    except ValueError:
        return None


def resolve(edge_id, rev):
    """Synthetic reverse edges (build_sumo_scenario synth ids >= 800000000)
    map back to their real partner; real edges pass through untouched."""
    try:
        if sec(edge_id) is not None and sec(edge_id) >= 800000000:
            return rev.get(edge_id, edge_id)
    except Exception:
        pass
    return edge_id


def main(argv):
    dump = None
    outdir = os.path.join(BRIDGE, "logan_scenario_realtls")
    offset_file = None
    it = iter(argv)
    for a in it:
        if a == "--dump":
            dump = next(it)
        elif a == "--out":
            outdir = next(it)
        elif a == "--offset-file":
            offset_file = next(it)
    if not dump or not os.path.isfile(dump):
        print("need --dump plan_dump_*.json")
        return 1
    plan = json.load(open(dump, encoding="utf-8"))
    junctions = plan["junctions"]
    print(f"build: {plan.get('engine_build')} junctions={len(junctions)}")
    rev = edges_graph(SRC)
    conns = conns_from_net(SRC)
    offsets = {}
    if offset_file and os.path.isfile(offset_file):
        for r in csv.DictReader(open(offset_file, encoding="utf-8")):
            try:
                offsets[str(r["junction"])] = int(round(
                    float(r["offset_bus_green_start_s"])))
            except Exception:
                pass

    os.makedirs(outdir, exist_ok=True)
    for f in COPY_FILES:
        s = os.path.join(SRC, f)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(outdir, f))
    tls_root = ET.Element("tlLogics")
    total_unmatched = 0
    n_tl = 0
    for j, rec in sorted(junctions.items(), key=lambda kv: int(kv[0])):
        tid = "n" + j
        cl = conns.get(tid)
        if not cl:
            print(f"  SKIP {tid}: no connections in net")
            continue
        # link movement -> (from_sec, to_sec), with synth reverse resolved
        links = []
        for li in sorted(cl):
            fe, te = cl[li]
            fr = resolve(fe, rev)
            tr = resolve(te, rev)
            links.append((li, sec(fr), sec(tr), fe, te))
        phases = rec.get("phases") or {}
        # green sets per phase + intergreen list
        ordered = sorted(phases, key=lambda p: int(p))
        green_of = {}
        for p in ordered:
            green_of[p] = set(tuple(t) for t in phases[p].get("turns", []))
        # unmatched links -> approach-group fallback
        matched = set()
        for (li, fs, ts, fe, te) in links:
            if fs is None or ts is None:
                continue
            for p in ordered:
                if (fs, ts) in green_of[p]:
                    matched.add(li)
                    break
        def matched_count(p):
            return sum(1 for (li, fs, ts, fe, te) in links
                       if (fs, ts) in green_of[p])
        # Capture-gap fill (config Main/Side sections): some main-through and
        # side SGs expose zero usable turnings in Aimsun (20270/19185/20280),
        # so their phases match nothing. Fill by configured sections,
        # exclusivity-first, testing EFFECTIVE emptiness (a dump turning that
        # matches no SUMO link is useless and must not block the fill):
        #   - bus phase   -> still-unmatched links from MainSections
        #   - side phases -> still-unmatched links from SideSections,
        #     balanced across the empty side phases by duration share
        _g = SEC_GROUPS.get(str(j), {})
        _ms, _ss = _g.get("main", set()), _g.get("side", set())
        _bphase = str(rec.get("bus_phase"))
        if _ms and _bphase in green_of and matched_count(_bphase) == 0:
            for (li, fs, ts, fe, te) in links:
                if li in matched or fs is None:
                    continue
                if fs in _ms:
                    green_of[_bphase].add((fs, ts))
                    matched.add(li)
        if _ss:
            _side_cands = [p for p in ordered
                           if p != _bphase and matched_count(p) == 0
                           and len(phases[p].get("sgs", [])) > 0]
            _side_links = [(li, fs, ts, fe, te) for (li, fs, ts, fe, te)
                           in links
                           if li not in matched and fs in _ss]
            if _side_cands and _side_links:
                _dur = {p: float(phases[p].get("dur_s", 0)) for p in
                        _side_cands}
                _cnt = {p: 0.0 for p in _side_cands}
                for (li, fs, ts, fe, te) in _side_links:
                    _pick = min(_side_cands,
                                key=lambda p: _cnt[p] / max(_dur[p], 1.0))
                    green_of[_pick].add((fs, ts))
                    _cnt[_pick] += 1.0
                    matched.add(li)
        for (li, fs, ts, fe, te) in links:
            if li in matched or fs is None or ts is None:
                continue
            # approach grouping: phase with most green turnings from fs
            best, best_n = None, -1
            for p in ordered:
                n = sum(1 for (a, b) in green_of[p] if a == fs)
                if n > best_n:
                    best, best_n = p, n
            if best is not None:
                green_of[best].add((fs, ts))
                matched.add(li)
        n_unmatched = sum(1 for (li, *_r) in links if li not in matched)
        # build states
        total_unmatched += n_unmatched
        # build states
        states = {}
        kinds = {}  # 'green' | 'ped' | 'inter'
        for p in ordered:
            n_turns = len(phases[p].get("turns", []))
            n_sgs = len(phases[p].get("sgs", []))
            # vehicle-green iff it carries greens (dump turnings OR config
            # Main/Side fills -- the fills land in phases whose SGs expose no
            # turnings, so test the resolved green set, not the raw count)
            if green_of.get(p):
                states[p] = "".join(
                    "G" if (fs, ts) in green_of[p] else "r"
                    for (li, fs, ts, fe, te) in links)
                kinds[p] = "green"
            elif n_sgs > 0:
                # pedestrian-only phase: vehicles see red, cycle preserved
                states[p] = "r" * len(links)
                kinds[p] = "ped"
            else:
                states[p] = None
                kinds[p] = "inter"
        # intergreen rows: yellow over the preceding vehicle-green phase
        state_rows = []
        prev_green = None
        for p in ordered:
            dur = float(phases[p]["dur_s"] or 0.0)
            st = states[p]
            if st is not None:
                state_rows.append((dur, st))
                if kinds[p] == "green":
                    prev_green = st
            else:
                if prev_green is not None:
                    yel = "".join("y" if c == "G" else "r" for c in prev_green)
                    state_rows.append((dur, yel))
                else:
                    state_rows.append((dur, "r" * len(links)))
        if not state_rows:
            print(f"  SKIP {tid}: no green phases")
            continue
        cyc = sum(d for d, _ in state_rows)
        if n_unmatched:
            print(f"  {tid}: {len(links)} links, {n_unmatched} unmatched "
                  f"(approach-grouped), cyc={cyc:.0f}s")
        else:
            print(f"  {tid}: {len(links)} links, cyc={cyc:.0f}s")
        tl = ET.SubElement(tls_root, "tlLogic", id=tid, programID="0",
                           type="static",
                           offset=str(offsets.get(j, 0)))
        for d, st in state_rows:
            ET.SubElement(tl, "phase", duration=str(round(d, 1)),
                          state=st)
        n_tl += 1
    tll_out = os.path.join(outdir, "tls.tll.xml")
    tree = ET.ElementTree(tls_root)
    tree.write(tll_out, encoding="utf-8", xml_declaration=True)
    print(f"\nwrote {tll_out}: {n_tl} tlLogic, total unmatched links "
          f"{total_unmatched}")
    cmd = [NETCONVERT, "-n", os.path.join(outdir, "nodes.nod.xml"),
           "-e", os.path.join(outdir, "edges.edg.xml"),
           "-x", os.path.join(outdir, "connections.con.xml"),
           "-o", os.path.join(outdir, "logan_road_new.net.xml"),
           "--no-turnarounds", "--tls.default-type", "static",
           "--offset.disable-normalization", "-i", tll_out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-4000:])
        return 1
    print("net rebuilt:", os.path.getsize(
        os.path.join(outdir, "logan_road_new.net.xml")) // 1024, "KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))