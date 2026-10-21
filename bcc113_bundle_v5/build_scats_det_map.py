"""build_scats_det_map.py -- KG SCATS-channel -> Aimsun-detector map generator.

Authoritative offline source: the model's own wiring.

  * kg/intersection_configs.py  INTERSECTIONS_CONFIG[j]['UpDetList'] / 'BusDet'
    -- the detectors the engine actually reads per junction (the "SCATS
       monitoring groups"); and 'MainSections' / 'SideSections'.
  * kg_aimsun_dump_fresh.json   detector geometry (section/lane/position) and
    section geometry (to_node/length) -- used to (a) place each group at its
    stopline approach and (b) resolve MULTI-direction groups, and to confirm the
    junction<->SCATS-site link via GKNode.name.
  * scats_state_map.py          SCATS class structure per site (channel + the
    SCATS detector-group sizes).

Outputs, per junction:
  * the SCATS channel each Aimsun UpDetList group belongs to (count-match to
    the site's SCATS classes; the BusDet group is the corridor arterial call);
  * a COVERAGE GAP list: SCATS classes at that site with NO Aimsun group
    monitoring them (e.g. side-street / rt-bay / slip / ped channels), which is
    the concrete answer to "are all the SCATS monitoring inputs in place?".

Run locally on Windows (reads JSON + the python config; no Aimsun, no server):
    python build_scats_det_map.py            # report
    python build_scats_det_map.py --emit     # + paste-ready scats_det_map block
"""

import argparse
import importlib.util
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
KG_DIR = os.path.join(HERE, "kg")
MODEL_DUMP = r"Z:\tsp\sumo_hpc\sumo_bridge\kg_aimsun_dump_fresh.json"

for _p in (HERE, KG_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import scats_state_map as ssm


def _load_intersection_configs():
    path = os.path.join(KG_DIR, "intersection_configs.py")
    spec = importlib.util.spec_from_file_location("kg_int_cfgs", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.INTERSECTIONS_CONFIG


def _load_geometry():
    with open(MODEL_DUMP, encoding="utf-8") as f:
        d = json.load(f)
    det = {}
    for x in d["detectors"]:
        det[int(x["id"])] = {
            "section": int(x["section"]), "lane": x.get("lane"),
            "pos": x.get("initial_pos"), "name": (x.get("name") or ""),
        }
    secs = {int(k): v for k, v in d["sections"].items()}
    nodes = {int(k): (v.get("name") or "") for k, v in d["nodes"].items()}
    return det, secs, nodes


def _site_by_junction():
    out = {}
    for site, rec in ssm.SITES.items():
        if rec.get("junction") is not None:
            out[int(rec["junction"])] = int(site)
    return out


def _classes(site):
    return list((ssm.SITES.get(int(site)) or {}).get("classes") or [])


def _count_match(n, site):
    """Same-size, non-COUNT SCATS classes at `site`."""
    return [c for c in _classes(site)
            if len(c[1]) == n and c[3] != "COUNT"]


def _match_channel(n, site, is_bus):
    """(channel, conf, note) for one Aimsun group of n loops at `site`."""
    if is_bus:
        return ("ART_CALL", "H",
                "BusDet / corridor arterial approach (config; runs the main artery)")
    cand = _count_match(n, site)
    if not cand:
        sizes = sorted({len(c[1]) for c in _classes(site) if c[3] != "COUNT"})
        return None, "U", "no same-size class; site class sizes=%s" % sizes
    chans = {c[3] for c in cand}
    names = "; ".join("%s%s" % (c[0], [int(x) for x in c[1]]) for c in cand)
    if len(cand) == 1:
        return cand[0][3], "H", names
    if len(chans) == 1:
        return cand[0][3], "M", "tie, same channel: " + names
    ch = "ART_CALL" if "ART_CALL" in chans else sorted(chans)[0]
    return ch, "M", "tie across {%s}; corridor group -> %s: %s" % (
        ",".join(sorted(chans)), ch, names)


def _approach(dets, geom, secs):
    """(dist_to_stopline_m, bearing_deg, section_label) for a group."""
    d0 = geom.get(int(dets[0]))
    if not d0:
        return None, None, None
    sid = d0["section"]
    s = secs.get(sid) or {}
    length = s.get("length_m")
    pos = d0.get("pos")
    dist = None
    if length and pos is not None:
        dist = round(float(length) - float(pos), 1)
    shape = s.get("shape") or []
    bearing = None
    if len(shape) >= 2:
        import math
        dx = shape[-1][0] - shape[0][0]
        dy = shape[-1][1] - shape[0][1]
        if dx or dy:
            bearing = round((math.degrees(math.atan2(dx, dy)) + 360) % 360, 1)
    return dist, bearing, "%s(%s->%s)" % (sid, s.get("from_node"), s.get("to_node"))


def build():
    cfgs = _load_intersection_configs()
    geom, secs, nodes = _load_geometry()
    site_by_j = _site_by_junction()

    rows = []
    gap = []
    junction_map = {}
    for jid, cfg in sorted(cfgs.items()):
        jid = int(jid)
        site = site_by_j.get(jid)
        if site is None:
            continue
        updet = cfg.get("UpDetList") or []
        busdet = set(cfg.get("BusDet") or [])
        entry = {"site": int(site), "groups": {}}
        for gi, g in enumerate(updet):
            g = [int(x) for x in g]
            is_bus = bool(busdet) and set(g) == busdet
            ch, conf, note = _match_channel(len(g), site, is_bus)
            dist, bearing, seclabel = _approach(g, geom, secs)
            entry["groups"][gi] = {
                "det_ids": g, "n": len(g), "ch": ch, "conf": conf,
                "note": note, "dist_to_stopline_m": dist,
                "bearing_deg": bearing, "section": seclabel,
                "members": {d: (ch, conf, note) for d in g},
            }
            rows.append((jid, site, nodes.get(jid, ""), gi, len(g), ch, conf,
                         dist, bearing))
        junction_map[jid] = entry

        wire_sizes = defaultdict(int)
        for g in updet:
            wire_sizes[len(g)] += 1
        wired_ch = {entry["groups"][gi]["ch"] for gi in entry["groups"]}
        for name, ds, roles, ch, cn in _classes(site):
            if ch == "COUNT" or not ds:
                continue
            if ch not in wired_ch:
                gap.append((jid, site, nodes.get(jid, ""), ch, name,
                            [int(x) for x in ds]))

    print("=== KG SCATS monitoring map (offline: intersection_configs + "
          "scats_state_map + model geometry) ===")
    print("%-9s %-5s %-16s %-3s %-3s %-9s %-2s %-6s %s" %
          ("junction", "site", "node_name", "grp", "n", "channel", "cf",
           "d_stop", "bearing"))
    for jid, site, nm, gi, n, ch, cf, dist, bearing in rows:
        print("%-9s %-5s %-16s %-3s %-3s %-9s %-2s %-6s %s" %
              (jid, site, nm, gi, n, ch, cf,
               "-" if dist is None else dist,
               "-" if bearing is None else bearing))

    print("\n=== COVERAGE GAPS: SCATS classes with NO Aimsun monitoring ===")
    if not gap:
        print("  (none -- every non-COUNT SCATS class is wired)")
    for jid, site, nm, ch, name, ds in gap:
        print("  jct %-9s site %-5s %-16s %-9s %-38s SCATS dets %s"
              % (jid, site, nm, ch, name[:38], ds))
    return junction_map, gap


def build_channel_map(out):
    """Wire SCATS channels to the Aimsun SCATS loops that PHYSICALLY EXIST.

    The KG model's 11137xxx loops sit only on the main-road approaches and the
    main-road departures of each managed junction -- there are NO cross-street /
    turn-bay / slip / ped loops. So ART_CALL (approach loops) and ART_PRES
    (departure loops) are wireable; SIDE / RT_BAY / SLIP / PED are physically
    absent and are emitted EMPTY and listed in MISSING_CHANNELS. Writes
    kg/scats_channel_map.py."""
    cfgs = _load_intersection_configs()
    site_by_j = _site_by_junction()

    channels = {}
    missing = {}
    for jid, cfg in sorted(cfgs.items()):
        jid = int(jid)
        site = site_by_j.get(jid)
        if site is None:
            continue
        approach = sorted({int(d) for g in (cfg.get("UpDetList") or [])
                           for d in (g or [])})
        departure = sorted({int(d) for d in (cfg.get("BusExitDetectors") or [])})
        has = {"ART_CALL": approach, "ART_PRES": departure,
               "RT_BAY": [], "SIDE": [], "SLIP": [], "PED": [], "COUNT": []}
        channels[jid] = {"site": int(site), **has}
        classes = _classes(site)
        miss = sorted({c[3] for c in classes if c[3] != "COUNT"
                       and c[1] and not has.get(c[3])})
        missing[jid] = {"site": int(site), "channels": miss}

    lines = [
        '"""kg/scats_channel_map.py -- GENERATED by build_scats_det_map.py ',
        "--channels. Do not edit by hand.\n",
        "SCATS channel -> Aimsun SCATS-loop (11137xxx) wiring for the KG corridor,",
        "derived from model geometry (kg_aimsun_dump_fresh.json) + the SCATS class",
        "structure (scats_state_map.py).\n",
        "ART_CALL = loops on the junction's INCOMING main approaches.",
        "ART_PRES = loops on the junction's OUTGOING departures (SCATS DEP position).",
        "SIDE / RT_BAY / SLIP / PED are EMPTY: the Aimsun KG model has NO loops on",
        "cross-streets / turn bays / slip lanes / ped kerbs, so those SCATS inputs",
        "cannot be monitored without adding detectors to the model.\n",
        '"""',
        "",
        "SCATS_CHANNELS = {",
    ]
    for jid in sorted(channels):
        e = channels[jid]
        row = ", ".join('"%s": %s' % (k, e[k]) for k in
                        ("ART_CALL", "ART_PRES", "SIDE", "RT_BAY", "SLIP",
                         "PED", "COUNT"))
        lines.append('    %s: {"site": %s, %s},' % (jid, e["site"], row))
    lines.append("}")
    lines.append("")
    lines.append("# site -> SCATS channels present in the personality but with NO "
                 "Aimsun loop")
    lines.append("MISSING_CHANNELS = {")
    for jid in sorted(missing):
        lines.append('    %s: {"site": %s, "missing": %s},'
                     % (jid, missing[jid]["site"], missing[jid]["channels"]))
    lines.append("}")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\n=== SCATS channel wiring -> %s ===" % out)
    print("%-9s %-6s %-8s %-8s %s" %
          ("junction", "site", "ART_CALL", "ART_PRES", "MISSING channels"))
    for jid in sorted(channels):
        print("%-9s %-6s %-8s %-8s %s" %
              (jid, channels[jid]["site"], len(channels[jid]["ART_CALL"]),
               len(channels[jid]["ART_PRES"]),
               missing[jid]["channels"] or "-"))
    return channels, missing


def _compass(bearing):
    if bearing is None:
        return "?"
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int((float(bearing) + 22.5) % 360 // 45)]


def emit_python(junction_map, out=None):
    lines = []
    for jid in sorted(junction_map):
        e = junction_map[jid]
        lines.append('    %s: {"site": %s, "groups": {' % (jid, e["site"]))
        for gi, g in sorted(e["groups"].items()):
            note = g["note"].split(";")[0][:60]
            members = ", ".join("%s: (%r, %r, '')" % (did, mv[0], mv[1])
                                for did, mv in sorted(g["members"].items()))
            lines.append('        %d: {"dir": %r, "ch": %r, "conf": %r, '
                         '"bearing_deg": %r, "note": %r, "members": {%s}},'
                         % (gi, _compass(g["bearing_deg"]), g["ch"], g["conf"],
                            g["bearing_deg"], note, members))
        lines.append("    }},")
    text = "\n".join(lines)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("wrote %s" % out)
    else:
        print("\n# ---- paste into scats_det_map.py JUNCTIONS ----")
        print(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true",
                    help="print a JUNCTIONS block for scats_det_map.py")
    ap.add_argument("--out", default=None,
                    help="write the JUNCTIONS block to this file (with --emit)")
    ap.add_argument("--channels", action="store_true",
                    help="write kg/scats_channel_map.py (channel wiring)")
    args = ap.parse_args()
    if args.channels:
        build_channel_map(os.path.join(KG_DIR, "scats_channel_map.py"))
        return 0
    jm, _gap = build()
    if args.emit:
        emit_python(jm, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
