"""build_channel_sections.py -- corridor-general SCATS channel -> Aimsun SECTION map.

Generalises build_kg_channel_sections.py to EITHER corridor (kg = North / Kelvin
Grove, logan_road_new = South / Logan Road). Writes <corridor>/scats_channel_sections.py,
which engine._scats_channel_sections() loads at runtime (SCATS_PHASE_ORIGIN_FALLBACK)
to recover the SIDE / RT_BAY / SLIP movement sections the ECI API misses.

Channel derivation (per junction), from <corridor>/intersection_configs.py +
sumo_bridge/<prefix>_aimsun_dump.json:
  ART     UpDetList loop sections (+ config MainSections)
  SIDE    config SideSections when present (AUTHORITATIVE -- KG path, unchanged);
          else INFERRED = non-arterial entry sections with >= 2 downstream
          destinations (a through cross-street movement). The inference triggers
          ONLY when a junction has no config SideSections, so KG (all 12 have
          them) is byte-identical; it fills the 17/23 Logan junctions that don't.
  RT_BAY  non-arterial / non-side entries that serve a SINGLE destination (turn bay)
  SLIP    entries whose section name contains "slip"

Run locally on Windows:
    python build_channel_sections.py kg            # == build_kg_channel_sections.py
    python build_channel_sections.py logan_road_new
"""
import importlib.util
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
# corridor -> aimsun dump basename in ../sumo_bridge/
_DUMP_BY_CORR = {
    "kg": "kg_aimsun_dump.json",
    "logan_road_new": "logan_aimsun_dump.json",
}


def _load_cfg(corr_dir):
    spec = importlib.util.spec_from_file_location(
        "corr_int_cfgs", os.path.join(corr_dir, "intersection_configs.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.INTERSECTIONS_CONFIG


def _load_dump(dump_path):
    d = json.load(open(dump_path, encoding="utf-8"))
    det2sec = {int(x["id"]): int(x["section"]) for x in d["detectors"]}
    turns = list(d["turnings"].values()) if isinstance(d["turnings"], dict) \
        else d["turnings"]
    entry = defaultdict(set)                          # node -> {from_section}
    dests = defaultdict(lambda: defaultdict(set))     # node -> from_sec -> {to_sec}
    for t in turns:
        nid = int(t.get("node", 0) or 0)
        fs = int(t.get("from_section", 0) or 0)
        ts = int(t.get("to_section", 0) or 0)
        if nid and fs:
            entry[nid].add(fs)
            if ts:
                dests[nid][fs].add(ts)
    sec_name = {int(k): (v.get("name") or "") for k, v in d["sections"].items()}
    # Approach bearing: direction of the LAST shape segment (toward the node the
    # section feeds), in degrees. Lets us tell an arterial approach (parallel to the
    # corridor axis) from a cross-street (roughly perpendicular) for junctions whose
    # config has no SideSections to copy.
    sec_bearing = {}
    for k, v in d["sections"].items():
        sh = v.get("shape") or []
        if len(sh) >= 2:
            (x0, y0), (x1, y1) = sh[-2][:2], sh[-1][:2]
            sec_bearing[int(k)] = math.degrees(math.atan2(y1 - y0, x1 - x0))
    return det2sec, entry, dests, sec_name, sec_bearing


def _axis_delta(b1, b2):
    """Smallest angle (0..90 deg) between two UNDIRECTED lines given their bearings."""
    d = abs((b1 - b2) % 180.0)
    return min(d, 180.0 - d)


def build(corridor="kg"):
    corr_dir = os.path.join(HERE, corridor)
    dump_name = _DUMP_BY_CORR.get(corridor)
    if not dump_name:
        raise SystemExit("unknown corridor %r (known: %s)"
                         % (corridor, list(_DUMP_BY_CORR)))
    dump_path = os.path.join(os.path.dirname(HERE), "sumo_bridge", dump_name)
    if not os.path.isfile(dump_path):
        raise SystemExit("missing Aimsun dump: %s" % dump_path)
    out_path = os.path.join(corr_dir, "scats_channel_sections.py")

    cfg = _load_cfg(corr_dir)
    det2sec, entry, dests, sec_name, sec_bearing = _load_dump(dump_path)
    out = {}
    report = []
    for jid, c in sorted(cfg.items()):
        jid = int(jid)
        art = set()
        for g in (c.get("UpDetList") or []):
            for dd in (g or []):
                s = det2sec.get(int(dd))
                if s:
                    art.add(int(s))
        art |= {int(s) for s in (c.get("MainSections") or [])}
        side = {int(s) for s in (c.get("SideSections") or [])}
        _side_inferred = not side          # only infer when config has none
        ent = {int(s) for s in entry.get(jid, set())}
        # Arterial AXIS bearing (undirected) = mean of the ART entry bearings, so a
        # cross-street can be told apart by angle. Only used in the inference branch.
        _art_b = [sec_bearing[s] for s in (art & ent) if s in sec_bearing]
        _axis = None
        if _art_b:
            # circular mean on the doubled angle (undirected lines, period 180)
            _sx = sum(math.sin(math.radians(2 * b)) for b in _art_b)
            _cx = sum(math.cos(math.radians(2 * b)) for b in _art_b)
            if _sx or _cx:
                _axis = math.degrees(math.atan2(_sx, _cx)) / 2.0
        rt, slip = set(), set()
        for s in ent - art - side:
            nm = (sec_name.get(s, "") or "").lower()
            dset = dests.get(jid, {}).get(s, set())
            if "slip" in nm:
                slip.add(s)
            elif len(dset) == 1:
                rt.add(s)                  # single-destination entry = pure turn bay
            elif _side_inferred and len(dset) >= 2:
                # BEARING REFINEMENT: an entry roughly PARALLEL to the arterial axis
                # is an un-detected arterial approach (add to ART), not a side
                # street; a roughly PERPENDICULAR one is the real cross-street SIDE.
                # Falls back to "treat multi-dest as SIDE" when no axis is known.
                _b = sec_bearing.get(s)
                if _axis is not None and _b is not None \
                        and _axis_delta(_b, _axis) <= 30.0:
                    art.add(s)             # parallel = arterial approach we missed
                else:
                    side.add(s)            # perpendicular = cross-street
        out[jid] = {"ART": sorted(art), "SIDE": sorted(side),
                    "RT_BAY": sorted(rt), "SLIP": sorted(slip),
                    "UNMONITORED": sorted(ent - art - side - rt - slip),
                    "_side_inferred": _side_inferred}
        report.append((jid, len(art), len(side), len(rt), len(slip),
                       len(out[jid]["UNMONITORED"]),
                       "infer" if _side_inferred else "config"))

    lines = [
        '"""%s/scats_channel_sections.py -- GENERATED by ' % corridor,
        'build_channel_sections.py. Do not edit by hand.\n',
        "SCATS channel -> Aimsun SECTION ids for the %s corridor, monitored by the"
        % corridor,
        "VIRTUAL inductive loop (engine._virtual_loop_flow_vph, any section).",
        "SIDE is from config SideSections where present, else inferred from the",
        "network geometry (non-arterial entries with >=2 destinations).\n",
        '"""',
        "",
        "SCATS_CHANNEL_SECTIONS = {",
    ]
    for jid in sorted(out):
        e = out[jid]
        lines.append(
            '    %d: {"ART": %s, "SIDE": %s, "RT_BAY": %s, "SLIP": %s},'
            % (jid, e["ART"], e["SIDE"], e["RT_BAY"], e["SLIP"]))
    lines.append("}")
    lines.append("")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("=== %s SCATS channel -> section map ===" % corridor)
    print("%-9s %5s %6s %7s %6s %12s %7s" %
          ("junction", "ART", "SIDE", "RT_BAY", "SLIP", "UNMONITORED", "side"))
    for r in report:
        print("%-9s %5d %6d %7d %6d %12d %7s" % r)
    _ninfer = sum(1 for r in report if r[6] == "infer")
    print("\n%d/%d junctions used INFERRED side (no config SideSections)"
          % (_ninfer, len(report)))
    print("[written] %s" % out_path)
    return out


if __name__ == "__main__":
    _corr = sys.argv[1] if len(sys.argv) > 1 else "kg"
    build(_corr)
