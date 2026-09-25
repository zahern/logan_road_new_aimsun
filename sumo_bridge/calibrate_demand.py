# calibrate_demand.py
# Build a SUMO demand file calibrated to Aimsun's observed section counts.
#
# Reads:
#   --dump   kg_aimsun_dump.json  (sections/nodes/turnings)
#   --sqlite TEG_KGER_T2_2025Base_QUT_AITAN1.sqlite  (MISECT count per section)
#   --corridor kg|logan_road_new  (for MainSections chains & groups)
#
# Writes demand JSON + SUMO additional validation step via builder path.
#
#   python calibrate_demand.py --corridor kg \
#       --dump kg_aimsun_dump.json \
#       --sqlite TEG_KGER_T2_2025Base_QUT_AITAN1.sqlite \
#       --out kg_demand_calibrated.json
#
# Then:
#   python build_sumo_scenario.py --corridor kg --dump kg_aimsun_dump.json \
#       --out kg_scenario --demand kg_demand_calibrated.json
#
# Calibration source: MISECT count = vehicles that entered a section during
# the replication (duration=3600s + 900s warmup in this model). We treat it
# as demand over [begin,end) (default 0-3600, warmup not simulated in SUMO).

import argparse
import json
import os
import sqlite3
import sys


def load_configs(corridor):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "intersection_configs", os.path.join(corridor, "intersection_configs.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pick_did(cur):
    # most recent SIM_INFO.did (latest replication in this sqlite - often the
    # only one, e.g. 11129240)
    try:
        cur.execute("SELECT MAX(did) FROM SIM_INFO")
        did = cur.fetchone()[0]
        if did is not None:
            return int(did)
    except Exception:
        pass
    # fallback: max did in MISECT
    cur.execute("SELECT MAX(did) FROM MISECT")
    return int(cur.fetchone()[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corridor", required=True, choices=["kg", "logan_road_new"])
    ap.add_argument("--dump", required=True)
    ap.add_argument("--sqlite", required=True)
    ap.add_argument("--out", required=True, help="demand JSON to write")
    ap.add_argument("--did", type=int, default=None, help="replication did; default latest")
    ap.add_argument("--begin", type=int, default=0)
    ap.add_argument("--end", type=int, default=3600)
    ap.add_argument("--bus-per-hour", type=float, default=12,
                    help="buses per hour per PT line when timetable unavailable")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="extra global scaling (applied after sqlite match)")
    ap.add_argument("--all-entries", action="store_true",
                    help="ALSO generate one flow per boundary entry section "
                         "(in-degree-0 sections with MISECT counts), routed to "
                         "their farthest reachable exit. Fills cross streets "
                         "and corridor_b so SUMO sees network-wide demand "
                         "instead of a single mainline OD pair.")
    ap.add_argument("--max-flow-vph", type=float, default=2200,
                    help="per-flow veh/h cap for --all-entries flows")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    corridor_dir = os.path.abspath(os.path.join(here, "..", args.corridor))
    dump_path = os.path.abspath(os.path.join(here, args.dump))
    sqlite_path = os.path.abspath(os.path.join(here, args.sqlite)) \
        if not os.path.isabs(args.sqlite) else args.sqlite
    out_path = os.path.abspath(os.path.join(here, args.out)) \
        if not os.path.isabs(args.out) else args.out

    icfg = load_configs(corridor_dir)
    dump = json.load(open(dump_path, encoding="utf-8"))
    sections = {int(k): v for k, v in dump.get("sections", {}).items()}
    pt_lines = dump.get("pt_lines", [])

    #robust open (Aimsun results DB is WAL-mode; direct copy appears malformed)
    def open_robust(p):
        import tempfile
        dst = os.path.join(tempfile.gettempdir(), f"aimsun_{os.path.basename(p)}_backup.sqlite")
        # try SQLite backup API (handles WAL) -> clean copy
        try:
            src = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            trg = sqlite3.connect(dst)
            src.backup(trg)
            trg.close(); src.close()
            c = sqlite3.connect(dst)
            c.execute("SELECT 1 FROM sqlite_master LIMIT 1")
            return c
        except Exception:
            pass
        # fallback direct
        return sqlite3.connect(p)

    con = open_robust(sqlite_path)
    cur = con.cursor()
    did = args.did or pick_did(cur)
    print(f"sqlite: {sqlite_path}")
    print(f"using did={did}")

    # MISECT count per oid - total vehicles entered during rep
    # main sqlite has a corrupted index on did, so WHERE may raise malformed;
    # MISECT also stores per-interval (sid) & per-vehicle-type (ent) rows, so
    # we sum over sid for ent==target_ent (default 1 = cars, see inspection).
    target_ent = 1
    try:
        cur.execute("SELECT oid, ent, count, flow FROM MISECT WHERE did=?", (did,))
        rows = cur.fetchall()
        it = [(oid, ent, cnt, flow) for oid, ent, cnt, flow in rows]
    except sqlite3.DatabaseError:
        # fallback: full scan then filter (avoids corrupted index)
        cur.execute("SELECT did, oid, ent, count, flow FROM MISECT")
        it = [(oid, ent, cnt, flow) for d2, oid, ent, cnt, flow in cur.fetchall() if int(d2) == int(did)]
    sect_count = {}
    sect_flow = {}
    for oid, ent, cnt, flow in it:
        if int(ent) != target_ent:
            continue
        try:
            oid = int(oid); cnt = int(cnt) if cnt is not None else 0; fl = float(flow) if flow is not None else 0.0
            sect_count[oid] = sect_count.get(oid, 0) + cnt
            sect_flow[oid] = sect_flow.get(oid, 0.0) + fl
        except (TypeError, ValueError):
            pass
    con.close()
    print(f"MISECT rows for did {did}: {len(sect_count)} sections with counts")

    # Vehicle types for SUMO
    vtypes = [
        {"id": "car", "length": 4.5, "maxSpeed": 16.7},
        {"id": "bus", "length": 12.0, "maxSpeed": 13.9},
    ]

    flows = []
    # ---- car demand: one flow per corridor-group entry->exit ----
    # Resolve edge existence (sections with both nodes; synthetic-boundary edges
    # count as existing since builder synthesizes their nodes)
    def edge_exists(sid):
        s = sections.get(int(sid))
        if not s:
            return False
        # builder emits edge when at least one node present and not self-loop;
        # with synthetic boundary it emits even for centroid stubs (one None).
        sh = s.get("shape") or []
        if not sh:
            return False
        frm, to = s.get("from_node"), s.get("to_node")
        if frm is None or to is None:
            return True  # synthetic edge will be created
        return int(frm) != int(to)

    # build turning graph for routability (dump turnings -> edge adjacency)
    turn_adj = {}
    for t in dump.get("turnings", {}).values():
        fs, ts = int(t["from_section"]), int(t["to_section"])
        if edge_exists(fs) and edge_exists(ts):
            turn_adj.setdefault(fs, set()).add(ts)

    for gname, iids in icfg.INTERSECTION_GROUPS.items():
        secs = []
        for iid in iids:
            c = icfg.INTERSECTIONS_CONFIG.get(iid, {})
            if isinstance(c, dict):
                secs += [int(x) for x in (c.get("MainSections") or [])]
        # unique, keep order, only edges that will exist
        seen, chain = set(), []
        for s in secs:
            if s not in seen and edge_exists(s):
                seen.add(s)
                chain.append(s)
        # Logan fallback: no MainSections -> walk synthesis already handles,
        # but for calibration we need at least one entry. Use first managed
        # sections that exist.
        if not chain:
            managed = {int(x) for x in iids}
            cands = [sid for sid, s in sections.items()
                     if s.get("to_node") in managed and edge_exists(sid)]
            if cands:
                chain = [min(cands, key=lambda sid: sections[sid].get("length_m", 1e9))]

        if not chain:
            print(f"WARN: group {gname}: no chainable entry sections - skipped")
            continue
        entry = chain[0]
        # pick farthest chain member reachable from entry via turn graph
        # (MainSections are not necessarily contiguous; intermediate non-Main
        # sections bridge them, so entry->last may be disconnected)
        reachable = set()
        stack = [entry]
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            for nxt in turn_adj.get(cur, ()):
                if nxt not in reachable:
                    stack.append(nxt)
        # exit = last chain element that's reachable; fallback to any reachable
        exit_ = None
        for cand in reversed(chain):
            if cand in reachable:
                exit_ = cand
                break
        if exit_ is None or entry == exit_:
            # no chain member reachable beyond entry -> pick farthest reachable
            # that's still on the corridor (heuristic: max graph distance)
            # for now just keep entry->entry as loop is invalid, skip group
            if len(reachable) > 1:
                # farthest by BFS depth
                from collections import deque
                dist = {entry: 0}
                q = deque([entry])
                while q:
                    cur = q.popleft()
                    for nxt in turn_adj.get(cur, ()):
                        if nxt not in dist:
                            dist[nxt] = dist[cur] + 1
                            q.append(nxt)
                # farthest chain member else farthest overall
                cands = [c for c in chain if c in dist]
                exit_ = max(cands, key=lambda c: dist[c]) if cands else max(dist, key=lambda c: dist[c])
            else:
                print(f"WARN: group {gname}: entry {entry} has no outgoing turnings - skipped")
                continue
        if entry == exit_:
            print(f"WARN: group {gname}: entry==exit {entry} - skipped")
            continue
        # target = sum of observed counts on the chain's entry sections
        # (typically just the first one is the true entry; the rest are interior)
        target = sect_count.get(entry, 500)  # fallback placeholder
        # interior sections' counts are flow-through, not entry - don't sum
        n_car = max(1, int(round(target * args.scale)))
        # cap to avoid insane rates when sqlite row is e.g. warmup-inclusive count
        # duration is 3600; observed counts already over ~3600
        flows.append({"from": f"s{entry}", "to": f"s{exit_}",
                      "vehs_per_hour": round(n_car * 3600 / max(args.end - args.begin, 1), 1),
                      "vtype": "car", "begin": args.begin, "end": args.end,
                      "_src": f"MISECT oid {entry} count={target} ({gname})"})

    # ---- bus demand: one flow per PT line with a routable corridor ----
    # If PT routes are empty (export before fix), synthesize one bus flow per
    # corridor group as before, so scenario stays runnable.
    pt_with_route = [pl for pl in pt_lines if len(pl.get("route_sections", [])) >= 2]
    if pt_with_route:
        for pl in pt_with_route:
            route = [int(s) for s in pl["route_sections"] if edge_exists(int(s))]
            if len(route) < 2:
                continue
            flows.append({"from": f"s{route[0]}", "to": f"s{route[-1]}",
                          "vehs_per_hour": args.bus_per_hour,
                          "vtype": "bus", "begin": args.begin, "end": args.end,
                          "_src": f"PT line {pl.get('id')}"})
    else:
        # fallback: one bus flow per car flow's route
        car_flows = [f for f in flows if f["vtype"] == "car"]
        for cf in car_flows:
            flows.append({"from": cf["from"], "to": cf["to"],
                          "vehs_per_hour": args.bus_per_hour,
                          "vtype": "bus", "begin": args.begin, "end": args.end,
                          "_src": f"bus fallback for {cf['from']}->{cf['to']}"})

    # ---- optional: network-wide entry->exit flows from MISECT counts ----
    if args.all_entries:
        from collections import deque
        win_s = max(args.end - args.begin, 1)
        added = 0
        # entries = sections vehicles can enter the network through: no
        # incoming turning edge, observed count > 0, edge will exist
        has_incoming = set()
        for fs, tos in turn_adj.items():
            for ts in tos:
                has_incoming.add(ts)
        for sid, cnt in sorted(sect_count.items()):
            if sid in has_incoming or not edge_exists(sid):
                continue
            vph = cnt * 3600.0 / win_s * args.scale
            if vph < 30.0:            # noise floor: skip near-empty boundaries
                continue
            vph = min(vph, args.max_flow_vph)
            # farthest reachable exit via BFS depth over turning graph
            dist = {sid: 0}
            q = deque([sid])
            while q:
                cur = q.popleft()
                for nxt in turn_adj.get(cur, ()):
                    if nxt not in dist:
                        dist[nxt] = dist[cur] + 1
                        q.append(nxt)
            exits = [c for c in dist if c != sid]
            if not exits:
                continue
            exit_ = max(exits, key=lambda c: dist[c])
            flows.append({"from": f"s{sid}", "to": f"s{exit_}",
                          "vehs_per_hour": round(vph, 1),
                          "vtype": "car", "begin": args.begin, "end": args.end,
                          "_src": f"MISECT boundary oid {sid} count={cnt}"})
            added += 1
        print(f"--all-entries: added {added} boundary entry flows")

    # strip helper key before writing for cleanliness, but keep in log
    for f in flows:
        src = f.pop("_src", "")
        print(f"  flow {f['from']}->{f['to']} {f['vtype']} "
              f"{f['vehs_per_hour']:.1f}/h  [{src}]")

    demand = {"vtypes": vtypes, "flows": flows,
              "_meta": {"did": did, "sqlite": os.path.basename(sqlite_path),
                        "scale": args.scale, "begin": args.begin, "end": args.end}}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(demand, f, indent=2)
    print(f"wrote {out_path} ({len(flows)} flows)")


if __name__ == "__main__":
    main()
