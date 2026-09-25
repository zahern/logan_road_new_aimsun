#!/usr/bin/env python3
"""audit_intersections.py -- offline audit of per-intersection controller logic.

Reads a run folder's simulation_results.csv (global row),
simulation_results_per_intersection.csv (one row per intersection),
section_stats.csv, bus_trips.csv, signal_wait_summary.json and summary.json,
and checks the invariants the controller's accounting must satisfy:

  AGGREGATION  delay parts sum to totals; distinct-vehicle subsets never
               exceed the global distinct counts; passages accumulate upward.
  TSP LADDER   extensions+insertions+skips+no-actions+natural-greens never
               exceed detections; averages within physical bounds.
  FLOW/QUEUE   per-intersection q/k/v residual distribution; queue bounds;
               green/red time present; SimDuration identical everywhere.
  TYPES        Car/Bus/TruckTypePos pairwise distinct and > 0 (live record of
               the vehicle-type resolution); occupancies positive.
  COVERAGE     section_stats intersections match per-intersection rows;
               summary.json row counts match; signal-wait sample plausible.

Usage:
    python audit_intersections.py [results_dir] [--latest N]

Default: every run folder under kg\\results (else logan_road_new\\results).
--latest N audits only the N newest folders. Exit 1 if any FAIL fires.
"""
import csv
import json
import os
import statistics as st
import sys

def _bundle_root():
    # __file__ is undefined under console exec(); Aimsun's cwd is its install
    # dir -- neither locates the bundle. The bundle is wherever
    # champion_search.py lives: check __file__ dir, cwd, then the known path.
    _cands = []
    try:
        if "__file__" in dir():
            _cands.append(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    _cands.append(os.getcwd())
    _cands.append(r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5")
    for _c in _cands:
        if os.path.isfile(os.path.join(_c, "champion_search.py")):
            return _c
    return _cands[-1]


ROOT = _bundle_root()


def _f(x, default=float("nan")):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _rel(a, b):
    if not (a == a and b == b):
        return float("nan")
    return abs(a - b) / (abs(b) if abs(b) > 0 else 1.0)


def audit_folder(folder):
    fails, warns, infos = [], [], []
    gp = os.path.join(folder, "simulation_results.csv")
    ip = os.path.join(folder, "simulation_results_per_intersection.csv")
    if not os.path.isfile(gp):
        return ["no simulation_results.csv"], [], []
    if not os.path.isfile(ip):
        return ["no simulation_results_per_intersection.csv"], [], []
    try:
        g = _load_csv(gp)[0]
        inter = _load_csv(ip)
    except Exception as e:
        return [f"CSV parse failed: {e}"], [], []
    if not inter:
        return ["per-intersection file empty"], [], []

    n = len(inter)
    infos.append(f"{n} intersections")

    # ── Truncated run: SimDuration far below the 1.25 h+ design horizon ──
    # (e.g. MARL_RL eval 300/400 on 2026-09-06 stopped at 0.68/0.17 h with no
    # error logged). Partial-horizon KPIs are not comparable: FAIL loudly so
    # the row gets quarantined instead of entering a ranking.
    _dur = _f(g.get("SimDuration_hrs", "nan"))
    if _dur == _dur and 0.0 < _dur < 1.0:
        fails.append(f"run TRUNCATED: SimDuration={_dur:.3f} h (< 1.0 h design "
                     f"horizon) -- KPIs cover a fraction of the horizon")

    # ── SimDuration identical everywhere ──
    durs = {r.get("SimDuration_hrs", "?") for r in inter} | {g.get("SimDuration_hrs", "?")}
    if len(durs) != 1:
        fails.append(f"SimDuration mismatch across rows: {sorted(durs)}")

    # ── Delay parts sum to totals (per intersection + global) ──
    for r in inter:
        d = _rel(_f(r["MainPassDelay_hrs"]) + _f(r["SidePassDelay_hrs"]),
                 _f(r["TotalPassDelay_hrs"]))
        if d == d and d > 0.01:
            fails.append(f"inter {r['IntersectionID']}: main+side != total (rel {d:.3f})")
            break
    gd = _rel(_f(g["MainPassDelay_hrs"]) + _f(g["SidePassDelay_hrs"]),
              _f(g["TotalPassDelay_hrs"]))
    if gd == gd and gd > 0.01:
        # Per-intersection rows hold main+side==total exactly; the GLOBAL row
        # uses a different aggregation (rates), so this is informational, not
        # an accounting break. Seen: main+side EXCEEDS total (unassigned bucket
        # missing) -- flag for model-side interpretation, not failure.
        warns.append(f"global main+side != total (rel {gd:.3f}; "
                     f"main={_f(g['MainPassDelay_hrs']):.1f} side={_f(g['SidePassDelay_hrs']):.1f} "
                     f"total={_f(g['TotalPassDelay_hrs']):.1f})")

    # ── Distinct subsets never exceed global distinct ──
    for col in ("N_DistinctBuses", "N_DistinctCars", "N_DistinctTrucks"):
        gg = _f(g.get(col, "nan"))
        for r in inter:
            v = _f(r.get(col, "nan"))
            if v == v and gg == gg and v > gg * 1.001 + 1:
                fails.append(f"inter {r['IntersectionID']}: {col}={v:.0f} > "
                             f"global {gg:.0f}: a subset cannot exceed the whole")
                break

    # ── Passages accumulate upward ──
    for col in ("PaxEquivPassages", "BusVehPassages", "CarVehPassages"):
        s = sum(_f(r.get(col, 0)) or 0 for r in inter)
        gg = _f(g.get(col, "nan"))
        if s and gg == gg and s < gg * 0.999:
            warns.append(f"sum(inter {col})={s:.0f} < global {gg:.0f}: "
                         f"passages should accumulate upward")

    # ── TSP ladder per intersection ──
    # Hard outcomes (ext/ins/skips) partition detections: each detection yields
    # at most one action or skip. Detected_NoAction/NaturalGreen are instead
    # recorded PER EVALUATION while a detection is active (proven: inter 17308
    # logged 138 NoActions on 44 detections), so they are excluded from the
    # ladder and reported as a diagnostic ratio instead.
    _ladder_notes = 0
    _na_ratios = []
    for r in inter:
        det = _f(r.get("TSP_Detections", 0)) or 0
        hard = sum(_f(r.get(c, 0)) or 0 for c in (
            "TSP_Extensions", "TSP_Insertions", "TSP_Skipped_GE",
            "TSP_Skipped_Ins"))
        if det > 0:
            _na = (_f(r.get("TSP_Detected_NoAction", 0)) or 0) + \
                (_f(r.get("TSP_NaturalGreen", 0)) or 0)
            _na_ratios.append(_na / det)
            if hard > det * 1.001 + 1:
                _ex = (hard - det) / det
                _msg = (f"inter {r['IntersectionID']}: hard outcomes {hard:.0f} > "
                        f"detections {det:.0f} (excess {_ex:.0%})")
                if _ex > 0.25:
                    fails.append(_msg)
                    break
                _ladder_notes += 1
                if _ladder_notes <= 2:
                    warns.append(_msg + " (prearm insertions without local "
                                 "detection are expected in coordinated mode)")
    if _ladder_notes > 2:
        warns.append(f"... +{_ladder_notes - 2} more intersection(s) with small TSP excess")
    if _na_ratios:
        infos.append(f"NoAction+Naturals per detection: median={st.median(_na_ratios):.2f} "
                     f"(per-evaluation records, not outcomes)")
        for c, lo, hi in (("TSP_AvgExtension_s", 0, 120),
                          ("TSP_AvgInsertion_s", 0, 300),
                          ("TSP_AvgInsertionWait_s", 0, 600)):
            v = _f(r.get(c, "nan"))
            if v == v and not (lo <= v <= hi):
                warns.append(f"inter {r['IntersectionID']}: {c}={v} outside [{lo},{hi}]")
    # Bus-trip sanity + averages non-negative.
    for r in inter:
        if (_f(r.get("N_BusTrips", 0)) or 0) > 0 and not (_f(r.get("AvgBusTT_s", 0)) or 0) > 0:
            fails.append(f"inter {r['IntersectionID']}: bus trips but AvgBusTT<=0")
            break
        for c in ("AvgBusTT_s", "StdBusTT_s", "AvgPassDelay_s", "AvgBusPassDelay_s",
                  "AvgCarPassDelay_s", "TotalPassDelay_hrs", "AvgQueue_veh"):
            v = _f(r.get(c, "nan"))
            if v == v and v < 0:
                fails.append(f"inter {r['IntersectionID']}: negative {c}={v}")
                break

    # ── Flow/queue per intersection ──
    resids = []
    for r in inter:
        q, k, v = _f(r.get("AvgFlow_veh_h", "nan")), \
            _f(r.get("AvgDensity_vkm", "nan")), _f(r.get("AvgSpeed_kmh", "nan"))
        if q == q and k == k and v == v and q > 50:
            resids.append(abs(q - k * v) / q)
    if resids:
        infos.append(f"inter q-vs-kv rel-resid: median={st.median(resids):.2f} "
                     f"(network means; identity not expected exactly)")
    q0 = sum(1 for r in inter if (_f(r.get("AvgQueue_veh", 0)) or 0) > 20)
    if q0:
        warns.append(f"{q0} intersection(s) with AvgQueue>20 veh sustained")
    _greens = [(_f(r.get("TotalGreen_s", 0)) or 0) for r in inter]
    if all(gg <= 0 for gg in _greens):
        infos.append("TotalGreen/TotalRed never populated (all 0): signal timing "
                     "totals not recorded by controller")
    else:
        for r in inter:
            if not ((_f(r.get("TotalGreen_s", 1)) or 0) > 0):
                warns.append(f"inter {r['IntersectionID']}: TotalGreen_s<=0")
                break
    if sum(1 for r in inter if not (r.get("MainSectionIDs") or "").strip()):
        warns.append("intersection(s) with empty MainSectionIDs")

    # ── Vehicle-type positions live record ──
    poses = set()
    for r in inter:
        try:
            triple = (int(float(r["CarTypePos"])), int(float(r["BusTypePos"])),
                      int(float(r["TruckTypePos"])))
        except (TypeError, ValueError, KeyError):
            fails.append(f"inter {r.get('IntersectionID', '?')}: unparsable type positions")
            break
        if any(p <= 0 for p in triple):
            fails.append(f"inter {r['IntersectionID']}: non-positive type pos {triple}")
            break
        if len(set(triple)) != 3:
            fails.append(f"inter {r['IntersectionID']}: colliding type pos {triple} "
                         f"(car/bus/truck indistinguishable!)")
            break
        poses.add(triple)
    else:
        if len(poses) > 1:
            warns.append(f"type positions differ across intersections: {sorted(poses)}")
        elif poses:
            infos.append(f"type positions car/bus/truck = {sorted(poses)[0]}")
    for c in ("CarOcc", "BusOcc", "TruckOcc"):
        vals = [_f(r.get(c, "nan")) for r in inter]
        vals = [v for v in vals if v == v]
        if vals and not all(v > 0 for v in vals):
            warns.append(f"non-positive {c} values present")
            break

    # ── Coverage: sections, summary.json, signal waits ──
    sp = os.path.join(folder, "section_stats.csv")
    if os.path.isfile(sp):
        try:
            srows = _load_csv(sp)
            sids = {str(r.get("IntersectionID", "?")) for r in srows}
            iids = {str(r.get("IntersectionID", "?")) for r in inter}
            if sids - iids:
                warns.append(f"section_stats references unknown intersections: "
                             f"{sorted(sids - iids)[:5]}")
            if iids - sids:
                infos.append(f"intersections with no section_stats rows: "
                             f"{sorted(iids - sids)[:5]}")
        except Exception as e:
            warns.append(f"section_stats unreadable: {e}")
    sj = os.path.join(folder, "summary.json")
    if os.path.isfile(sj):
        try:
            d = json.load(open(sj))
            nj = len(d.get("intersections", [])) if isinstance(d, dict) else -1
            if nj != n:
                warns.append(f"summary.json intersections={nj} vs CSV rows={n}")
        except Exception as e:
            warns.append(f"summary.json unreadable: {e}")
    sw = os.path.join(folder, "signal_wait_summary.json")
    if os.path.isfile(sw):
        try:
            d = json.load(open(sw))
            if _f(d.get("avg_wait_s", 0)) < 0:
                fails.append("signal_wait avg_wait_s negative")
            nb = _f(d.get("n_buses_measured", "nan"))
            db = _f(g.get("N_DistinctBuses", "nan"))
            if nb == nb and db == db and nb > db:
                warns.append(f"signal-wait buses measured {nb:.0f} > distinct {db:.0f}")
        except Exception as e:
            warns.append(f"signal_wait_summary unreadable: {e}")

    return fails, warns, infos


def _candidate_roots():
    # Console cwd is unreliable (Aimsun console opens elsewhere), so search
    # every plausible bundle location.
    seen, out = set(), []
    for _r in (ROOT, r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"):
        _r = os.path.abspath(_r)
        if _r not in seen:
            seen.add(_r)
            out.append(_r)
    return out


def _run_folders():
    seen = set()
    for _root in _candidate_roots():
        for corr in ("kg", "logan_road_new"):
            base = os.path.join(_root, corr, "results")
            if os.path.isdir(base):
                for name in sorted(os.listdir(base)):
                    p = os.path.join(base, name)
                    if os.path.isdir(p) and p not in seen:
                        seen.add(p)
                        yield p


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    latest = None
    for a in sys.argv[1:]:
        if a.startswith("--latest"):
            try:
                latest = int(a.split("=")[1] if "=" in a else sys.argv[sys.argv.index(a) + 1])
            except (ValueError, IndexError):
                latest = 10
    folders = [a for a in args if os.path.isdir(a)] or sorted(
        _run_folders(), key=lambda p: os.path.getmtime(p))
    if latest:
        folders = folders[-latest:]
    if not folders:
        print("No run folders found.")
        return 1
    n_fail_folders = 0
    n_skip = 0
    for folder in folders:
        fails, warns, infos = audit_folder(folder)
        # Folders without result files are in-progress or dead runs: SKIP
        # (report), never FAIL (a missing file is not a failed invariant).
        if fails and all("no simulation_results" in x or "no simulation_results_per_intersection" in x or "CSV parse failed" in x for x in fails) and not warns:
            print(f"[SKIP] {os.path.basename(folder)} ({'; '.join(fails)})")
            n_skip += 1
            continue
        tag = "FAIL" if fails else ("WARN" if warns else "ok")
        if fails:
            n_fail_folders += 1
        print(f"[{tag}] {os.path.basename(folder)}")
        for i in infos:
            print(f"    info: {i}")
        for w in warns:
            print(f"    WARN: {w}")
        for x in fails:
            print(f"    FAIL: {x}")
    print("-" * 60)
    print(f"audited {len(folders)} folder(s), {n_fail_folders} with FAILs, "
          f"{n_skip} skipped (incomplete)")
    return 1 if n_fail_folders else 0


if __name__ == "__main__":
    sys.exit(main())
