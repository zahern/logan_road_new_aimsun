"""
scats_node_crosscheck.py -- cross-check our Aimsun KG network against the REAL
SCATS site personalities, so we can see per-junction whether we have the right
approaches and enough detectors to drive the DS decisions.

Fully OFFLINE: matches on the fact that the Aimsun node NAMES are the SCATS site
numbers (39606="KGR-Herston Rd"=B0306, 39590="307"=B0307, 36393="308"=B0308, ...).

SCATS side  (parse_scats_personalities): per site -> approaches (label, detectors,
            signal group) + signal-group names.
Aimsun side (sumo_bridge/kg_aimsun_dump.json): per node -> approach sections (the
            distinct from_sections of turnings into the node), the real detectors
            on those sections (id/name/section/lane/pos), and the control-plan
            phase count.

Reports per matched junction:
  SCATS: #approaches  #signal-groups  #detectors
  AIMSUN: #approach-sections  #detectors  #phases
and FLAGS any junction where Aimsun has materially FEWER detectors or approaches
than SCATS -- the "not detecting enough" case. Writes scats_node_crosscheck.txt.

Run locally on Windows:  python scats_node_crosscheck.py
"""
import os
import json
import glob

import parse_scats_personalities as psp

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP = os.path.join(os.path.dirname(HERE), "sumo_bridge", "kg_aimsun_dump.json")


def load_scats():
    """site_number(int) -> {location, n_app, n_sg, n_det, approaches}."""
    out = {}
    if not psp.NORTH:
        return out
    for site in sorted(os.listdir(psp.NORTH)):
        sdir = os.path.join(psp.NORTH, site)
        lst = glob.glob(os.path.join(sdir, "LST*.LST"))
        if not lst:
            continue
        info = psp.parse_lst(psp._read(lst[0]))
        # site number from folder "B0306" -> 306, "B8129" -> 8129
        digits = "".join(c for c in site if c.isdigit())
        if not digits:
            continue
        num = int(digits)
        apps = info["approaches"]
        sgs = set()
        ndet = 0
        for a in apps:
            for s in (a["sg"] if isinstance(a["sg"], list) else [a["sg"]]):
                if isinstance(s, int):
                    sgs.add(s)
            ndet += sum(1 for x in a["dets"] if isinstance(x, int))
        out[num] = {"location": info["name"], "n_app": len(apps),
                    "n_sg": len(sgs), "n_det": ndet, "approaches": apps}
    return out


def node_name_to_site(name):
    """Map an Aimsun node name to a SCATS site number, or None."""
    if not name:
        return None
    nm = str(name)
    if "herston" in nm.lower() or "kgr" in nm.lower():
        return 306
    digits = "".join(c for c in nm if c.isdigit())
    return int(digits) if digits else None


def load_aimsun():
    """node_id -> {name, site, n_app_sec, n_det, n_phases, app_secs}."""
    d = json.load(open(DUMP, encoding="utf-8"))
    nodes = d["nodes"]
    turns = d["turnings"]
    dets = d["detectors"]
    # detectors per section
    det_by_sec = {}
    for de in dets:
        det_by_sec.setdefault(int(de.get("section", 0) or 0), []).append(de)
    # approach sections per node (distinct from_sections of turnings into the node)
    app_by_node = {}
    for t in (turns.values() if isinstance(turns, dict) else turns):
        nid = int(t.get("node", 0) or 0)
        fs = int(t.get("from_section", 0) or 0)
        if nid and fs:
            app_by_node.setdefault(nid, set()).add(fs)
    # phase count per node from any SCATS control plan
    ph_by_node = {}
    for cp in d.get("control_plans", []):
        if "SCATS" not in str(cp.get("name", "")):
            continue
        for _, jj in (cp.get("junctions") or {}).items():
            try:
                jid = int(jj.get("junction_id"))
            except Exception:
                continue
            nph = len(jj.get("phases") or [])
            if nph > ph_by_node.get(jid, 0):
                ph_by_node[jid] = nph
    out = {}
    for nid, n in nodes.items():
        nid = int(nid)
        site = node_name_to_site(n.get("name"))
        secs = app_by_node.get(nid, set())
        ndet = sum(len(det_by_sec.get(s, [])) for s in secs)
        out[nid] = {"name": n.get("name", ""), "site": site,
                    "n_app_sec": len(secs), "n_det": ndet,
                    "n_phases": ph_by_node.get(nid, 0), "app_secs": sorted(secs)}
    return out


def main():
    scats = load_scats()
    aim = load_aimsun()
    lines = ["SCATS <-> Aimsun KG cross-check", "=" * 92,
             "%-9s %-26s | SCATS app/SG/det | AIMSUN appSec/det/ph | verdict"
             % ("node", "location")]
    flagged = []
    for nid, a in sorted(aim.items()):
        site = a["site"]
        if site is None or site not in scats:
            continue
        s = scats[site]
        # verdict: flag if Aimsun approaches or detectors are materially short
        notes = []
        if a["n_app_sec"] < s["n_app"]:
            notes.append("FEWER-APPROACHES(%d<%d)" % (a["n_app_sec"], s["n_app"]))
        if a["n_det"] == 0 and s["n_det"] > 0:
            notes.append("NO-AIMSUN-DETECTORS(scats=%d)" % s["n_det"])
        elif a["n_det"] < max(1, s["n_det"] // 2):
            notes.append("UNDER-DETECTED(%d<<%d)" % (a["n_det"], s["n_det"]))
        verdict = "OK" if not notes else " ".join(notes)
        if notes:
            flagged.append(nid)
        lines.append("%-9s %-26s |   %d / %d / %-3d  |     %d / %-3d / %-3d   | %s"
                     % (nid, (s["location"] or "")[:26],
                        s["n_app"], s["n_sg"], s["n_det"],
                        a["n_app_sec"], a["n_det"], a["n_phases"], verdict))
    lines.append("=" * 92)
    lines.append("matched junctions: %d | flagged: %d %s"
                 % (sum(1 for nid, a in aim.items()
                        if a["site"] in scats),
                    len(flagged), flagged))
    # SCATS sites with no Aimsun match (missing from the model)
    matched_sites = {aim[n]["site"] for n in aim if aim[n]["site"] in scats}
    missing = sorted(set(scats) - matched_sites)
    lines.append("SCATS sites not found in the Aimsun KG model: %s"
                 % [("B%04d" % m, scats[m]["location"]) for m in missing])
    out = "\n".join(lines)
    print(out)
    try:
        with open(os.path.join(HERE, "scats_node_crosscheck.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write(out + "\n")
        print("\n[written] scats_node_crosscheck.txt")
    except Exception as e:
        print("write failed: %r" % e)


if __name__ == "__main__":
    main()
