# build_sumo_scenario.py
# Convert an Aimsun dump (export_aimsun_network.py) + corridor configs into a
# runnable SUMO scenario (plain XML -> netconvert -> net.xml + add-ons).
#
#   python build_sumo_scenario.py --corridor kg \
#       [--dump kg_aimsun_dump.json] [--out kg_scenario] [--demand demand.json]
#
# Two-pass netconvert:
#   pass 1 builds the raw network so we can read back netconvert's own
#   traffic-light link ordering; pass 2 injects tlLogic programs written
#   against that exact ordering (avoids linkIndex mismatches).

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
import shutil as _shutil

def _find_netconvert():
    """Windows wheels ship netconvert.exe; Linux ships plain netconvert.
    Try SUMO_HOME/bin first, then PATH.  (The old hardcoded .exe path broke
    every HPC build with FileNotFoundError.)"""
    cands = []
    sh = os.environ.get("SUMO_HOME")
    if sh:
        cands += [os.path.join(sh, "bin", "netconvert"),
                  os.path.join(sh, "bin", "netconvert.exe")]
    w = _shutil.which("netconvert")
    if w:
        cands.append(w)
    for c in cands:
        if os.path.isfile(c):
            return c
    return cands[-1] if cands else "netconvert"

NETCONVERT = _find_netconvert()

STATE_MAP = {0: "r", 1: "G", 2: "y"}   # Aimsun SG state int -> SUMO light char


def load_configs(corridor):
    spec = importlib.util.spec_from_file_location(
        "intersection_configs", os.path.join(corridor, "intersection_configs.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def w(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote %s" % path)


def run_netconvert(indir, out_net, tll=None):
    cmd = [NETCONVERT,
           "-n", os.path.join(indir, "nodes.nod.xml"),
           "-e", os.path.join(indir, "edges.edg.xml"),
           "-x", os.path.join(indir, "connections.con.xml"),
           "-o", out_net,
           "--no-turnarounds", "--tls.default-type", "static",
           "--offset.disable-normalization"]
    if tll:
        cmd += ["-i", tll]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-4000:])
        sys.exit("netconvert failed (%d)" % r.returncode)
    return out_net


def build(args):
    here = os.path.dirname(os.path.abspath(__file__))
    corridor_dir = os.path.abspath(os.path.join(here, "..", args.corridor))
    outdir = os.path.abspath(os.path.join(here, args.out))
    os.makedirs(outdir, exist_ok=True)

    dump = {}
    if args.dump:
        with open(os.path.abspath(os.path.join(here, args.dump)),
                  encoding="utf-8") as f:
            dump = json.load(f)

    icfg = load_configs(corridor_dir)
    # JSON keys are strings -> normalise to int ids
    sections = {int(k): v for k, v in dump.get("sections", {}).items()}
    nodes_d = dump.get("nodes", {})
    turnings = {int(k): v for k, v in dump.get("turnings", {}).items()}
    managed = set(int(i) for i in icfg.INTERSECTIONS_CONFIG.keys())

    # --- Synthesize missing reverse direction for managed corridor links ---
    # Aimsun KG/ Logan corridor is two-way but the dump often contains only one
    # GKSection per road (Aimsun models the opposite direction via lane direction
    # flags, not a separate section).  SUMO needs two directed edges.  For every
    # managed-junction pair that has an edge a->b but no b->a, synthesize the
    # reverse as a new section with swapped nodes, reversed shape and same lanes.
    # This fixes the "cars going only one way / frozen intersection" GUI reports.
    _managed_pairs = set()
    for sec in sections.values():
        f, t = sec.get("from_node"), sec.get("to_node")
        if f is not None and t is not None:
            _managed_pairs.add((int(f), int(t)))
    _next_syn_id = 800000000
    _rev_map = {}  # orig sid -> rev sid
    _added_rev = 0
    for (a, b) in list(_managed_pairs):
        if (b, a) not in _managed_pairs and (a in managed or b in managed):
            src = next((s for s in sections.values()
                        if s.get("from_node") == a and s.get("to_node") == b), None)
            if not src:
                continue
            _next_syn_id += 1
            rev = dict(src)
            rev["id"] = _next_syn_id
            rev["from_node"], rev["to_node"] = b, a
            sh = src.get("shape") or []
            if len(sh) >= 2:
                rev["shape"] = list(reversed(sh))
            rev["name"] = (src.get("name") or str(src.get("id"))) + "_rev"
            sections[_next_syn_id] = rev
            _rev_map[int(src["id"])] = _next_syn_id
            _added_rev += 1
    # Mirror turnings for the synthesized reverse edges so routing works both ways
    _added_rev_turns = 0
    if _rev_map:
        _orig_turns = list(turnings.values())
        _next_tid = 900000000
        for t in _orig_turns:
            fs, ts = int(t["from_section"]), int(t["to_section"])
            rfs, rts = _rev_map.get(ts), _rev_map.get(fs)
            # reverse movement: ts_rev -> fs_rev through same node
            if rfs is not None and rts is not None:
                _next_tid += 1
                turnings[_next_tid] = {"id": _next_tid, "node": t["node"],
                                        "from_section": rfs, "to_section": rts,
                                        "n_lanes": t.get("n_lanes", 1)}
                _added_rev_turns += 1
    if _added_rev:
        print("synthesized %d reverse-direction sections + %d reverse turnings for two-way corridor"
              % (_added_rev, _added_rev_turns))

    # ------------------------------------------------------------- nodes
    node_ids = set()
    for s in sections.values():
        for key in ("from_node", "to_node"):
            if s.get(key) is not None:
                node_ids.add(int(s[key]))
    node_ids |= managed
    node_lines = []
    for nid in sorted(node_ids):
        nd = nodes_d.get(str(nid)) or {}
        xy = nd.get("xy")
        if not xy:
            for s in sections.values():
                if s.get("from_node") == nid or s.get("to_node") == nid:
                    sh = s.get("shape") or []
                    if sh:
                        xy = sh[0]
                        break
        if not xy:
            print("WARN: no position for node %s, using 0,0" % nid)
            xy = [0.0, 0.0]
        ntype = "traffic_light" if nid in managed else "priority"
        node_lines.append('    <node id="n%d" x="%.3f" y="%.3f" type="%s"/>'
                          % (nid, xy[0], xy[1], ntype))
    w(os.path.join(outdir, "nodes.nod.xml"),
      '<nodes>\n%s\n</nodes>\n' % "\n".join(node_lines))

    # ------------------------------------------------------------- edges
    # Stubs (centroid connectors) get a synthetic boundary node on their
    # dangling side so corridor entries/exits survive as real edges.
    edge_lines, edge_ids = [], set()
    synth_nodes = []                       # (id, x, y)
    edge_lanes_map, edge_len_map = {}, {}
    skipped_edges = 0
    for sid, s in sorted(sections.items()):
        eid = "s%d" % sid
        frm, to = s.get("from_node"), s.get("to_node")
        sh = s.get("shape") or []
        if eid in edge_ids:
            skipped_edges += 1
            continue
        try:
            if frm is not None and to is not None and int(frm) == int(to):
                skipped_edges += 1
                continue                  # true self-loop
        except (TypeError, ValueError):
            pass
        if frm is None or to is None:
            if not sh:
                skipped_edges += 1
                continue
            if frm is None and to is None:
                # fully external stub: synthesize both endpoints from shape
                x0, y0 = sh[0]
                x1, y1 = sh[-1]
                frm = "x%d" % sid
                to = "y%d" % sid
                synth_nodes.append((frm, x0, y0))
                synth_nodes.append((to, x1, y1))
            elif frm is None:
                xy = sh[0]
                frm = "x%d" % sid
                synth_nodes.append((("x%d" % sid), xy[0], xy[1]))
            else:
                xy = sh[-1]
                to = "x%d" % sid
                synth_nodes.append((("x%d" % sid), xy[0], xy[1]))
        nl = s.get("n_lanes") or len(s.get("lanes") or []) or 1
        speed_ms = float(s.get("speed_kmh", 50.0)) / 3.6
        shape_attr = ""
        if len(sh) > 1:
            shape_attr = ' shape="%s"' % " ".join("%.2f,%.2f" % (p[0], p[1])
                                                  for p in sh)
        prio = 6 if any(sid in (c.get("MainSections") or [])
                        for c in icfg.INTERSECTIONS_CONFIG.values()
                        if isinstance(c, dict)) else 3
        frm_s = frm if isinstance(frm, str) else "n%d" % int(frm)
        to_s = to if isinstance(to, str) else "n%d" % int(to)
        edge_lines.append(
            '    <edge id="%s" from="%s" to="%s" numLanes="%d" speed="%.2f" '
            'priority="%d"%s/>' % (eid, frm_s, to_s, nl, speed_ms,
                                   prio, shape_attr))
        edge_ids.add(eid)
        edge_lanes_map[eid] = int(nl)
        edge_len_map[eid] = float(s.get("length_m") or 100.0)
    # synthetic boundary nodes must exist before nodes.nod.xml is written;
    # they were collected above, so prepend them to node_lines
    for xsid, xx, yy in synth_nodes:
        node_lines.append('    <node id="%s" x="%.3f" y="%.3f" type="priority"/>'
                          % (xsid, xx, yy))
    w(os.path.join(outdir, "nodes.nod.xml"),
      '<nodes>\n%s\n</nodes>\n' % "\n".join(node_lines))
    w(os.path.join(outdir, "edges.edg.xml"),
      '<edges>\n%s\n</edges>\n' % "\n".join(edge_lines))
    print("edges: %d emitted (%d synthetic-boundary), %d skipped"
          % (len(edge_lines), len(synth_nodes), skipped_edges))

    # ------------------------------------------------------- connections
    con_lines = []
    for tid, t in sorted(turnings.items()):
        fs, ts = int(t["from_section"]), int(t["to_section"])
        fe, te = "s%d" % fs, "s%d" % ts
        if fe not in edge_ids or te not in edge_ids:
            continue
        fe_s, te_s = sections.get(fs, {}), sections.get(ts, {})
        nid = fe_s.get("to_node")
        if nid is None or nid != te_s.get("from_node"):
            continue
        nfl = edge_lanes_map.get(fe, 1)
        ntl = edge_lanes_map.get(te, 1)
        tn = max(1, min(int(t.get("n_lanes", 1)), nfl, ntl))
        for k in range(tn):
            fl = min(k, nfl - 1)
            tl = min(k, ntl - 1)
            con_lines.append('    <connection from="%s" to="%s" fromLane="%d" '
                             'toLane="%d"/>' % (fe, te, fl, tl))
    w(os.path.join(outdir, "connections.con.xml"),
      '<connections>\n%s\n</connections>\n' % "\n".join(con_lines))

    # ------------------------------------------- PASS 1: raw netconvert
    tmp_net = os.path.join(outdir, "_pass1.net.xml")
    run_netconvert(outdir, tmp_net)
    links_by_tls = {}
    root = ET.parse(tmp_net).getroot()
    for c in root.iter("connection"):
        tl = c.get("tl")
        if tl:
            links_by_tls.setdefault(tl, []).append(
                (int(c.get("linkIndex", "0")), c.get("from"), c.get("to")))
    for tl in links_by_tls:
        links_by_tls[tl].sort()
    os.remove(tmp_net)
    print("pass 1 OK - %d traffic-lighted junctions found" % len(links_by_tls))

    # ------------------------------------------------------------ tlLogic
    cp_by_junction = {}
    for plan in dump.get("control_plans", []):
        for jid, jrec in (plan.get("junctions") or {}).items():
            try:
                cp_by_junction[int(jid)] = jrec
            except (TypeError, ValueError):
                pass

    tll_lines = []
    for tl, links in sorted(links_by_tls.items()):
        try:
            nid = int(str(tl).lstrip("n"))
        except ValueError:
            continue
        phases_out = []

        jrec = cp_by_junction.get(nid)
        cyc_phases = []
        if jrec:
            for cyc in jrec.get("cycles", []):
                cyc_phases.extend(cyc.get("phases", []))

        sg_turn_map = {}
        if jrec:
            m = {}
            for sg in jrec.get("signal_groups", []):
                for tid in sg.get("turnings", []):
                    m[int(tid)] = sg.get("id")
            sg_turn_map = m

        sec2turn = {(int(t["from_section"]), int(t["to_section"])): int(tid)
                    for tid, t in turnings.items()}

        if cyc_phases and sg_turn_map:
            for ph in cyc_phases:
                dur = float(ph.get("duration", 30.0))
                chars = []
                for (_i, fe, te) in links:
                    key = (int(fe[1:]), int(te[1:]))
                    sgi = sg_turn_map.get(sec2turn.get(key, -1))
                    stv = ph.get("sg_states", {}).get(str(sgi))
                    chars.append(STATE_MAP.get(stv if stv is not None else 0, "r"))
                state = "".join(chars)
                if set(state) == {"r"}:
                    continue
                phases_out.append((dur, state))

        if not phases_out:
            # synthesize program from intersection_configs.py
            cfgs = [c for c in icfg.INTERSECTIONS_CONFIG.values()
                    if isinstance(c, dict) and
                    int(c.get("IntersectionID", -1)) == nid]
            if cfgs:
                c = cfgs[0]
                g = c.get("GroupBasedConfig", {})
                ig = float(g.get("intergreen_duration", 4.0))
                nlinks = len(links)

                def state_for(green_set, yellow=False):
                    ch = "y" if yellow else "g"
                    return "".join(ch if i in green_set else "r"
                                   for i in range(nlinks))

                main_secs = set(c.get("MainSections") or [])
                if main_secs:
                    maxg = g.get("max_green", {})
                    bus_sg = int(g.get("bus_sg", 1))
                    side_sgs = [s for s in g.get("sg_list", []) if s != bus_sg]
                    main_g = float(maxg.get(bus_sg, 45.0))
                    side_g = float(max([maxg[s] for s in side_sgs if s in maxg],
                                       default=25.0))
                    main_idx = [i for i, (_k, fe, _te) in enumerate(links)
                                if int(fe[1:]) in main_secs]
                    side_idx = [i for i in range(nlinks) if i not in main_idx]
                    phases_out = [(main_g, state_for(main_idx)),
                                  (ig, state_for(main_idx, True)),
                                  (side_g, state_for(side_idx)),
                                  (ig, state_for(side_idx, True))]
                else:
                    # minimal config: arterial = highest-capacity approach
                    by_edge = {}
                    for i, (_k, fe, _te) in enumerate(links):
                        by_edge.setdefault(fe, []).append(i)
                    capf = lambda e: (edge_lanes_map.get(e, 1) *
                                      edge_len_map.get(e, 100.0))
                    approaches = sorted(by_edge, key=capf, reverse=True)
                    arterial = set(by_edge[approaches[0]]) if approaches else []
                    rest = [i for i in range(nlinks) if i not in arterial]
                    cyc = float(g.get("cycle_length", 110.0))
                    phases_out = [(cyc * 0.55, state_for(arterial)),
                                  (ig, state_for(arterial, True)),
                                  (max(cyc * 0.30, 15.0), state_for(rest)),
                                  (ig, state_for(rest, True))]
        if not phases_out:
            continue
        tll_lines.append('    <tlLogic id="%s" programID="0" type="static" '
                         'offset="0">' % tl)
        for dur, st in phases_out:
            tll_lines.append('        <phase duration="%.1f" state="%s"/>'
                             % (dur, st))
        tll_lines.append('    </tlLogic>')
    w(os.path.join(outdir, "tls.tll.xml"),
      ('<tlLogics>\n%s\n</tlLogics>\n' % "\n".join(tll_lines))
      if tll_lines else "<tlLogics/>\n")

    # ------------------------------------------- PASS 2: net + programs
    net_file = os.path.join(outdir, "%s.net.xml" % args.corridor)
    run_netconvert(outdir, net_file, tll=os.path.join(outdir, "tls.tll.xml"))
    print("OK -> %s" % net_file)

    # ---------------------------------------------------------- detectors
    det_meta, dets = {}, []
    all_det_cfg = []
    for iid, c in icfg.INTERSECTIONS_CONFIG.items():
        if not isinstance(c, dict):
            continue
        for did in c.get("BusCallDetectors", []) + c.get("BusExitDetectors", []):
            all_det_cfg.append(int(did))
    dump_det = {int(d["id"]): d for d in dump.get("detectors", [])
                if d.get("section") is not None}
    all_det_cfg += list(dump_det.keys())
    for did in sorted(set(all_det_cfg)):
        d = dump_det.get(did)
        if d:
            eid = "s%d" % int(d["section"])
            pos = float(d.get("initial_pos") or 0.0)
            ln = max(0.5, float(d.get("final_pos") or pos) - pos)
            lane = int(d.get("lane") or 0)
            src = "aimsun"
        else:
            host = None
            for iid, c in icfg.INTERSECTIONS_CONFIG.items():
                if not isinstance(c, dict):
                    continue
                if did in [int(x) for x in c.get("BusCallDetectors", [])] or \
                   did in [int(x) for x in c.get("BusExitDetectors", [])]:
                    host = c
                    break
            if not host or not host.get("MainSections"):
                continue
            cand = [ms for ms in host["MainSections"] if "s%d" % int(ms) in edge_ids]
            if not cand:
                continue
            eid = "s%d" % int(cand[0])
            pos, ln, lane, src = 40.0, 2.0, 0, "fallback"
        if eid not in edge_ids:
            print("WARN: detector %d references unknown edge %s - skipped"
                  % (did, eid))
            continue
        det_id = "det%d" % did
        dets.append('    <e1Detector id="%s" lane="%s_%d" pos="%.2f" period="1.00" '
                    'file="detector_output.xml" friendlyPos="true"/>'
                    % (det_id, eid, lane, pos))
        det_meta[str(did)] = {"sumo_id": det_id, "edge": eid, "lane": lane,
                              "pos": pos, "length": ln, "source": src}
    w(os.path.join(outdir, "detectors.add.xml"),
      '<additional>\n%s\n</additional>\n' % "\n".join(dets))
    with open(os.path.join(outdir, "detectors_meta.json"), "w",
              encoding="utf-8") as f:
        json.dump(det_meta, f, indent=1)

    # ------------------------------------------------------------- demand
    dem_path = args.demand
    if dem_path:
        dem_path = os.path.abspath(os.path.join(here, dem_path))
    if args.use_centroids and dump.get("centroids"):
        # ── True centroid-based OD (od2trips-equivalent) ─────────────────────
        # Match entry/exit stub sections to the nearest Aimsun centroid by
        # geometry, attach each MISECT-calibrated entry flow to its origin
        # centroid, then split demand across destination centroids weighted
        # by their exit counts.  Emits real centroid→centroid flows grounded
        # in what Aimsun actually simulated.
        import math as _math
        cents = dump.get("centroids", {})
        stub_e, stub_x = {}, {}
        for sid2, s2 in sections.items():
            fn, tn = s2.get("from_node"), s2.get("to_node")
            sh = s2.get("shape") or []
            if len(sh) < 2 or ("s%d" % sid2) not in edge_ids:
                continue
            if fn is None and tn is not None:
                stub_e[(sh[0][0], sh[0][1])] = "s%d" % sid2
            elif tn is None and fn is not None:
                stub_x[(sh[-1][0], sh[-1][1])] = "s%d" % sid2

        def _near_cen(xy):
            best, bd = None, 1e18
            for cid2, c2 in cents.items():
                cxy = c2.get("xy")
                if not cxy:
                    continue
                dd = _math.dist(xy, cxy)
                if dd < bd:
                    bd, best = dd, cid2
            return best, bd

        cen_entry_edge, cen_exit_edge, cen_exit_cnt = {}, {}, {}
        for (x0, y0), eid in stub_e.items():
            cid2, dd = _near_cen((x0, y0))
            if cid2 and dd < 400.0:      # reject implausible matches
                cen_entry_edge[cid2] = eid
        for (x0, y0), eid in stub_x.items():
            cid2, dd = _near_cen((x0, y0))
            if cid2 and dd < 400.0:
                cen_exit_edge[cid2] = eid
                cen_exit_cnt[cid2] = cen_exit_cnt.get(cid2, 0) + 1
        print("centroid TAZs: %d entries matched, %d exits matched"
              % (len(cen_entry_edge), len(cen_exit_edge)))

        # ── True OD-matrix demand: pick matrix by window/class name ──────────
        od_matrices = [m for m in dump.get("od_matrices", []) if m.get("trips")]
        od_used = None
        od_flows = []
        if args.od_name:
            # COMMA-SEPARATED names are MERGED (summed) — e.g.
            #   --od-name "SEAM 2023 AM,cordon prior 2023AM"
            # loads the network-wide background AND the corridor cordon as one
            # demand set, matching how Aimsun simulates all active matrices
            # simultaneously.
            wanted = [s.strip() for s in args.od_name.split(",") if s.strip()]
            sel = []
            for m in od_matrices:
                mname_l = (m.get("name") or "").lower()
                if any(w.lower() in mname_l for w in wanted):
                    if args.od_class:
                        cls_l = ((m.get("user_class") or "") + " "
                                 + mname_l).lower()
                        if args.od_class.lower() not in cls_l:
                            continue
                    sel.append(m)
            if sel:
                # merge trips across selected matrices (same window assumed)
                merged_trips = {}
                win_h = 1.0
                import re as _re
                m_name = sel[0].get("name", "")
                mw = _re.search(r"(\d{1,2}):(\d{2})", m_name.split("-")[-1]
                                if "-" in m_name else m_name)
                if mw:
                    win_h = int(mw.group(1)) + int(mw.group(2)) / 60.0
                win_h = max(win_h, 0.25)
                tot_cells = 0
                for m in sel:
                    tot_cells += len(m["trips"])
                    for k2, v2 in m["trips"].items():
                        merged_trips[k2] = merged_trips.get(k2, 0.0) + float(v2)
                od_used = {"name": " + ".join((m.get("name") or "")
                                              for m in sel)[:80],
                           "trips": merged_trips}
                tot_trips = sum(merged_trips.values())
                print("OD matrices merged: %d | %d cells | %.0f trips | "
                      "window %.2fh" % (len(sel), tot_cells, tot_trips, win_h))
                for key, trips in merged_trips.items():
                    oc, dc = key.split("->")
                    fe = cen_entry_edge.get(oc)
                    te = cen_exit_edge.get(dc)
                    if fe is None or te is None or fe == te:
                        continue
                    vph = float(trips) / win_h
                    if vph < 5.0:
                        continue
                    # Map Aimsun class names onto defined SUMO vTypes
                    # ("Car"->car; Truck/HOV/etc have no dedicated vType here
                    #  -> ride as cars so their demand is not silently lost)
                    _vt = "bus" if "bus" in (args.od_class or "").lower() else "car"
                    od_flows.append({"from": fe, "to": te,
                                     "vehs_per_hour": round(vph, 1),
                                     "vtype": _vt})
                print("OD flows: %d emitted (%.0f veh/h total)"
                      % (len(od_flows),
                         sum(f["vehs_per_hour"] for f in od_flows)))
        # Bus demand: Bus-class OD matrix if present, else corridor fallback
        bus_sel = [m for m in od_matrices
                   if "bus" in ((m.get("user_class") or "")
                                + " " + (m.get("name") or "")).lower()]
        if bus_sel and args.od_class != "Bus":
            bm = bus_sel[0]
            for key, trips in bm["trips"].items():
                oc, dc = key.split("->")
                fe = cen_entry_edge.get(oc)
                te = cen_exit_edge.get(dc)
                if fe is None or te is None or fe == te:
                    continue
                vph = float(trips) / max(win_h, 0.25) if 'win_h' in dir() else float(trips)
                if vph >= 1.0:
                    od_flows.append({"from": fe, "to": te,
                                     "vehs_per_hour": round(vph, 2),
                                     "vtype": "bus"})
        base_flows = []
        if dem_path and os.path.exists(dem_path):
            with open(dem_path, encoding="utf-8") as f:
                base_flows = json.load(f).get("flows", [])
        edge2cen_entry = {v: k for k, v in cen_entry_edge.items()}
        if not od_flows:
            # Fallback: distribute calibrated entry flows across exit centroids
            for fl in base_flows:
                ocen = edge2cen_entry.get(fl["from"])
                if ocen is None or not cen_exit_edge or fl["vtype"] == "bus":
                    continue
                tot_w = float(sum(cen_exit_cnt.values())) or 1.0
                for dcen, wgt in cen_exit_cnt.items():
                    share = wgt / tot_w
                    vph = float(fl["vehs_per_hour"]) * share
                    if vph < 5.0:
                        continue
                    od_flows.append({"from": cen_entry_edge[ocen],
                                     "to": cen_exit_edge[dcen],
                                     "vehs_per_hour": round(vph, 1),
                                     "vtype": fl["vtype"]})
        # Buses: keep original corridor bus flow (12/h) on the mainline
        for fl in base_flows:
            if fl["vtype"] == "bus":
                od_flows.append(dict(fl))
        # Buses: keep original corridor bus flow (12/h) on the mainline
        _has_bus = any(f.get("vtype") == "bus" for f in od_flows)
        if not _has_bus:
            # No Bus-class OD matrix — inject corridor mainline bus flow
            # at the observed Aimsun frequency (12/h = every 300 s).
            # Route: first → last managed junction via their entry/exit edges.
            _managed_jcts = list(icfg.INTERSECTIONS_CONFIG.keys())
            if _managed_jcts:
                _first_cfg = icfg.INTERSECTIONS_CONFIG[_managed_jcts[0]]
                _last_cfg = icfg.INTERSECTIONS_CONFIG[_managed_jcts[-1]]
                _bus_entry = None
                _bus_exit = None
                for ms in (_first_cfg.get("MainSections") or []):
                    eid = "s%d" % int(ms)
                    if eid in edge_ids:
                        _bus_entry = eid
                        break
                for ms in reversed(_last_cfg.get("MainSections") or []):
                    eid = "s%d" % int(ms)
                    if eid in edge_ids:
                        _bus_exit = eid
                        break
                if _bus_entry and _bus_exit and _snet is not None:
                    _be = _snet.getEdge(_bus_entry)
                    _bx = _snet.getEdge(_bus_exit)
                    if _be is not None and _bx is not None:
                        _path, _ = _snet.getShortestPath(_be, _bx)
                        if _path:
                            od_flows.append({"from": _bus_entry,
                                             "to": _bus_exit,
                                             "vehs_per_hour": 12,
                                             "vtype": "bus"})
                            print("bus corridor flow injected: %s -> %s "
                                  "(%d edges)"
                                  % (_bus_entry, _bus_exit, len(_path)))
        demand = {"vtypes": [
            {"id": "car", "length": 4.5, "maxSpeed": 16.7},
            {"id": "bus", "length": 12.0, "maxSpeed": 13.9}],
            "flows": od_flows}
        print("centroid OD: %d flows generated from %d entries"
              % (len(od_flows), len({f['from'] for f in od_flows})))
    elif dem_path and os.path.exists(dem_path):
        with open(dem_path, encoding="utf-8") as f:
            demand = json.load(f)
    else:
        print("NOTE: no --demand given, writing PLACEHOLDER corridor demand "
              "(calibrate against Aimsun results sqlite before comparing KPIs)")
        flows = []
        for _gname, iids in icfg.INTERSECTION_GROUPS.items():
            secs = []
            for iid in iids:
                c = icfg.INTERSECTIONS_CONFIG.get(iid, {})
                if isinstance(c, dict):
                    secs += [int(x) for x in (c.get("MainSections") or [])]
            chain, seen = [], set()
            for s0 in secs:
                if s0 not in seen and "s%d" % s0 in edge_ids:
                    seen.add(s0)
                    chain.append(s0)
            if not chain:
                group_nodes = {int(i) for i in iids}
                managed_in = [("s%d" % sid) for sid, s in sections.items()
                              if s.get("to_node") in group_nodes
                              and ("s%d" % sid) in edge_ids]

                def capf(e):
                    return edge_lanes_map.get(e, 1) * edge_len_map.get(e, 100.0)
                if not managed_in:
                    continue
                entry_sid = int(max(managed_in, key=capf)[1:])
                nxt, walked = entry_sid, []
                guard = 0
                while nxt is not None and nxt not in walked and guard < 60:
                    walked.append(nxt)
                    guard += 1
                    cur = sections.get(nxt, {})
                    outs = []
                    for t2 in turnings.values():
                        if int(t2["from_section"]) == nxt:
                            tsid = int(t2["to_section"])
                            te2 = sections.get(tsid, {})
                            if te2.get("from_node") == cur.get("to_node") \
                                    and ("s%d" % tsid) in edge_ids:
                                outs.append((capf("s%d" % tsid), tsid))
                    nxt = max(outs)[1] if outs else None
                chain = walked
            if not chain:
                continue
            entry, exit_ = "s%d" % chain[0], "s%d" % chain[-1]
            flows.append({"from": entry, "to": exit_, "vehs_per_hour": 500,
                          "vtype": "car"})
            flows.append({"from": entry, "to": exit_, "vehs_per_hour": 12,
                          "vtype": "bus"})
        demand = {"vtypes": [
            {"id": "car", "length": 4.5, "maxSpeed": 16.7},
            {"id": "bus", "length": 12.0, "maxSpeed": 13.9}],
            "flows": flows}
    dl = ['<additional>']
    # validate routes against the real net; drop unreachable pairs
    try:
        tools_dir = os.path.abspath(os.path.join(os.path.dirname(NETCONVERT),
                                                 "..", "tools"))
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import sumolib
        _snet = sumolib.net.readNet(net_file)
    except Exception as _e:
        print("WARN: sumolib unavailable (%r) - skipping route validation" % _e)
        _snet = None
    kept_flows, dropped = [], 0
    for fl in demand.get("flows", []):
        ok = True
        if _snet is not None:
            ef = _snet.getEdge(fl["from"])
            et = _snet.getEdge(fl["to"])
            if ef is None or et is None:
                ok = False
            else:
                path, _c = _snet.getShortestPath(ef, et)
                ok = bool(path)
        if ok:
            kept_flows.append(fl)
        else:
            dropped += 1
            print("WARN: flow %s->%s has no valid route - dropped"
                  % (fl["from"], fl["to"]))
    if dropped:
        print("demand: %d flows kept, %d dropped (unroutable)"
              % (len(kept_flows), dropped))
    # ── Inject corridor bus flow when no Bus-class OD matrix exists ────────
    if not any(fl.get("vtype") == "bus" for fl in kept_flows) and _snet is not None \
            and len(kept_flows) > 1:
        # Pick the two most distant routable edges as the bus corridor
        _best_pair, _best_hops = None, 0
        _entries = sorted(set(fl["from"] for fl in kept_flows))
        _exits   = sorted(set(fl["to"] for fl in kept_flows))
        for fe in _entries[:10]:
            ef = _snet.getEdge(fe)
            if ef is None: continue
            for te in _exits[:10]:
                et = _snet.getEdge(te)
                if et is None or et == ef: continue
                path, _ = _snet.getShortestPath(ef, et)
                if path and len(path) > _best_hops:
                    _best_hops = len(path)
                    _best_pair = (fe, te)
        if _best_pair and _best_hops > 2:
            kept_flows.append({"from": _best_pair[0], "to": _best_pair[1],
                               "vehs_per_hour": 12, "vtype": "bus"})
            print("bus corridor flow injected: %s -> %s (%d hops)"
                  % (_best_pair[0], _best_pair[1], _best_hops))
    # Distinct GUI colours: cars cool grey, buses loud orange with bus shape
    _VT_COLORS = {"car": ' color="0.60,0.65,0.85"',
                  "bus": ' color="1.00,0.35,0.00" guiShape="bus"'}

    # ── Synthetic bus stops ────────────────────────────────────────────────
    # Use REAL Aimsun GKBusStop positions when available; fall back to
    # synthetic spacing along the shortest path.
    BUS_DWELL_S = 20.0
    _bus_stops_xml = []       # <busStop> definitions
    _bus_flow_stops = {}      # flow index -> [(lane, pos, duration), ...]
    if _snet is not None:
        _bus_stop_id = 0
        _edge_stop_cache = {}
        # ── Real Aimsun stops first ──
        for bs in dump.get("bus_stops", []):
            sec_id = bs.get("section")
            if sec_id is None:
                continue
            eid = "s%d" % int(sec_id)
            if eid not in edge_ids or eid in _edge_stop_cache:
                continue
            lane_len = edge_len_map.get(eid, 100.0)
            n_lanes = edge_lanes_map.get(eid, 1)
            pos = max(5.0, float(bs.get("pos") or lane_len * 0.3))
            if pos >= lane_len - 1.0:
                pos = lane_len * 0.5
            _bus_stop_id += 1
            sid_str = "busStop_%d" % _bus_stop_id
            lane_0 = "%s_%d" % (eid, min(n_lanes - 1, 0))
            _edge_stop_cache[eid] = (sid_str, lane_0, pos)
            _bus_stops_xml.append(
                '    <busStop id="%s" lane="%s" startPos="%.1f" '
                'endPos="%.1f" friendlyPos="true"/>'
                % (sid_str, lane_0, pos, min(lane_len - 1.0, pos + 15.0)))
        print("real Aimsun bus stops placed: %d" % len(_edge_stop_cache))
        # ── Synthetic spacing for remaining bus flows ──
        for fi, fl in enumerate(kept_flows):
            if fl.get("vtype") != "bus":
                continue
            ef = _snet.getEdge(fl["from"])
            et = _snet.getEdge(fl["to"])
            if ef is None or et is None:
                continue
            path, _c = _snet.getShortestPath(ef, et)
            if not path or len(path) < 2:
                continue
            _stops_for_this_flow = []
            _dist_since_last = 0.0
            for edge in path:
                eid = edge.getID()
                lane_len = edge.getLength()
                n_lanes = edge.getLaneNumber()
                if eid not in _edge_stop_cache:
                    _dist_since_last += lane_len
                    if _dist_since_last >= 400.0:
                        _bus_stop_id += 1
                        sid_str = "busStop_%d" % _bus_stop_id
                        lane_0 = "%s_%d" % (eid, min(n_lanes - 1, 0))
                        _edge_stop_cache[eid] = (sid_str, lane_0,
                                                 max(5.0, lane_len * 0.15))
                        _bus_stops_xml.append(
                            '    <busStop id="%s" lane="%s" '
                            'startPos="%.1f" endPos="%.1f" '
                            'friendlyPos="true"/>'
                            % (sid_str, lane_0,
                               max(5.0, lane_len * 0.15),
                               min(lane_len - 1.0,
                                   max(5.0, lane_len * 0.15) + 15.0)))
                if eid in _edge_stop_cache:
                    sid_str, lane_ref, pos = _edge_stop_cache[eid]
                    _stops_for_this_flow.append((sid_str, lane_ref, pos))
                    _dist_since_last = 0.0
            _bus_flow_stops[fi] = _stops_for_this_flow
        print("total bus stops: %d (real + synthetic)" % len(_edge_stop_cache))
    for vt in demand.get("vtypes", [{"id": "car"}, {"id": "bus"}]):
        dl.append('    <vType id="%s" length="%s" maxSpeed="%s"%s/>'
                  % (vt["id"], vt.get("length", 5.0),
                     vt.get("maxSpeed", 16.7),
                     _VT_COLORS.get(vt["id"], "")))
    # Emit busStop definitions BEFORE flows (SUMO cannot resolve forward refs)
    dl.extend(_bus_stops_xml)
    for i, fl in enumerate(kept_flows):
        begin, end = fl.get("begin", 0), fl.get("end", 3600)
        if fl.get("vtype") == "bus" and i in _bus_flow_stops \
                and _bus_flow_stops[i]:
            # Bus flow with stops: emit as explicit vehicles with route+stops
            ef = _snet.getEdge(fl["from"])
            et = _snet.getEdge(fl["to"])
            path, _c = _snet.getShortestPath(ef, et)
            edge_ids_str = " ".join(e.getID() for e in path)
            n_bus = int(fl.get("vehs_per_hour", 12) * (end - begin) / 3600.0)
            dl.append('    <flow id="f%d_%s" type="bus" begin="%s" end="%s" '
                      'number="%d" departLane="best" departSpeed="max">'
                      % (i, fl["from"], begin, end, n_bus))
            dl.append('        <route edges="%s"/>' % edge_ids_str)
            for (sid_str, lane_ref, pos) in _bus_flow_stops[i]:
                dl.append('        <stop busStop="%s" duration="%.0f"/>'
                          % (sid_str, BUS_DWELL_S))
            dl.append('    </flow>')
        else:
            dl.append('    <flow id="f%d_%s_%s" type="%s" from="%s" to="%s" '
                      'begin="%s" end="%s" number="%d" departLane="best" '
                      'departSpeed="max"/>'
                      % (i, fl.get("vtype", "car"), fl["from"],
                         fl.get("vtype", "car"), fl["from"], fl["to"], begin, end,
                         int(fl.get("vehs_per_hour", 400) * (end - begin) / 3600.0)))
    # Emit bus stop definitions (already emitted above, before flows)
    dl.append('</additional>')
    w(os.path.join(outdir, "demand.add.xml"), "\n".join(dl) + "\n")

    # --------------------------------------------------------------- PT meta
    pt = {}
    if dump.get("pt_lines"):
        for ln2 in dump["pt_lines"]:
            lid = str(ln2.get("id"))
            if lid:
                pt[lid] = {"name": ln2.get("name", ""),
                           "sections": [int(s0)
                                        for s0 in ln2.get("route_sections", [])]}
    else:
        pt["1"] = {"name": "corridor_bus",
                   "sections": sorted({int(s0)
                                       for c in icfg.INTERSECTIONS_CONFIG.values()
                                       if isinstance(c, dict)
                                       for s0 in (c.get("MainSections") or [])})}
    with open(os.path.join(outdir, "pt_meta.json"), "w", encoding="utf-8") as f:
        json.dump(pt, f, indent=1)
    print("wrote pt_meta.json (%d lines)" % len(pt))

    # -------------------------------------------------------------- sumocfg
    w(os.path.join(outdir, "%s.sumocfg" % args.corridor),
      """<configuration>
    <input>
        <net-file value="{net}"/>
        <additional-files value="detectors.add.xml,demand.add.xml"/>
    </input>
    <time><begin value="0"/><end value="4500"/><step-length value="1.0"/></time>
    <processing><time-to-teleport value="-1"/></processing>
    <output><summary-output value="summary.xml"/><tripinfo-output value="tripinfo.xml"/></output>
</configuration>
""".format(net="%s.net.xml" % args.corridor))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--corridor", required=True, choices=["kg", "logan_road_new"])
    ap.add_argument("--dump", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--demand", default=None)
    ap.add_argument("--use-centroids", action="store_true",
                    help="build true centroid-based OD: match stub sections to "
                         "Aimsun centroids geometrically, attach MISECT-calibrated "
                         "entry flows, distribute across destination centroids")
    ap.add_argument("--od-name", default=None,
                    help="with --use-centroids: select OD matrix by name substring "
                         "(e.g. 'AM' or '07.30-08.30') and emit its trips as flows")
    ap.add_argument("--od-class", default="Car",
                    help="vehicle-class filter for the OD matrix (default Car)")
    a = ap.parse_args()
    if not a.out:
        a.out = "%s_scenario" % a.corridor
    build(a)
