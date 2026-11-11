"""_arms_section_flow.py -- do the Logan arm differences survive when the
numerator is section flow instead of PaxEquivPassages?

The recorded objective is PaxEquivPassages / TotalPassDelay_hrs, and
PaxEquivPassages counts MAIN approach sections only (and those sets drift
between runs). This recomputes progression directly from each run's
section_timeseries.csv, which is per-section and does not depend on the
main/side classification at all:

    traversals   sum over sections of integral(q dt)      (vehicle passages)
    veh_km       sum over sections of integral(q L dt)
    mean_speed   passage-weighted mean section speed
    queue_h      sum over sections of integral(queue dt) / 3600

Everything is computed on the section set COMMON to every run being compared,
so a missing detector cannot masquerade as a difference.

    python -I _arms_section_flow.py
"""
import csv
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from summarize_overnight import _paired_t  # noqa: E402

CSV = os.path.join(HERE, "game_ladder_logan_lightsim_20261109_124707.csv")
BASE = "NO_TSP"


def load_runs():
    rows = list(csv.DictReader(open(CSV, newline="", encoding="utf-8-sig")))
    out = []
    for r in rows:
        seed = (r.get("run_seed") or "").strip()
        folder = (r.get("stats_results_folder") or "").strip()
        if not seed or not folder or not os.path.isdir(folder):
            continue
        # run_strategy is "GLOBAL_REWARD" for BOTH CHAMP variants, so take the
        # arm from the folder prefix: <ARM>_seed<SEED>_<ids>_<stamp>.
        arm = os.path.basename(folder).split("_seed")[0]
        if not arm:
            arm = (r.get("run_experiment") or r.get("run_strategy") or "").strip()
        out.append({"arm": arm, "seed": seed, "folder": folder, "row": r})
    return out


def section_stats(folder):
    per = {}
    path = os.path.join(folder, "section_timeseries.csv")
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        for r in csv.DictReader(fh):
            try:
                sid = int(r["SectionID"])
                t0 = float(r["t_start_s"])
                t1 = float(r["t_end_s"])
            except (KeyError, TypeError, ValueError):
                continue
            dt = t1 - t0
            if dt <= 0:
                continue
            q = float(r["q_veh_h"] or 0.0)
            L = float(r["Length_km"] or 0.0)
            v = float(r["v_kmh"] or 0.0)
            qq = float(r["queue_veh"] or 0.0)
            d = per.get(sid)
            if d is None:
                d = per[sid] = {"tr": 0.0, "vkm": 0.0, "qs": 0.0,
                                "vq": 0.0, "q": 0.0}
            d["tr"] += q * dt / 3600.0
            d["vkm"] += q * L * dt / 3600.0
            d["qs"] += qq * dt
            if q > 0 and v > 0:
                d["vq"] += q * v
                d["q"] += q
    return per


def metrics(per, common, cars):
    tr = sum(per[s]["tr"] for s in common)
    vkm = sum(per[s]["vkm"] for s in common)
    qs = sum(per[s]["qs"] for s in common)
    vq = sum(per[s]["vq"] for s in common)
    qsum = sum(per[s]["q"] for s in common)
    return {
        "traversals": tr,
        "veh_km": vkm,
        "mean_speed": (vq / qsum) if qsum else float("nan"),
        "queue_h": qs / 3600.0,
        "per_car": (tr / cars) if cars else float("nan"),
    }


def paired(arm_vals, base_vals, seeds, higher_is_better):
    pairs = [(arm_vals[s], base_vals[s]) for s in seeds
             if s in arm_vals and s in base_vals]
    if not pairs:
        return None
    sign = 1.0 if higher_is_better else -1.0
    diffs = [sign * (a - b) for a, b in pairs]
    md = sum(diffs) / len(diffs)
    sd = (sum((x - md) ** 2 for x in diffs) / (len(diffs) - 1)) ** 0.5 \
        if len(diffs) > 1 else 0.0
    dz = (md / sd) if sd else (float("inf") if md > 0 else 0.0)
    _t, p = _paired_t([sign * a for a, _b in pairs],
                      [sign * b for _a, b in pairs])
    av = sum(a for a, _b in pairs) / len(pairs)
    bv = sum(b for _a, b in pairs) / len(pairs)
    return {"n": len(pairs), "md": md, "dz": dz, "p": p,
            "av": av, "bv": bv, "delta": 100.0 * (av - bv) / bv if bv else 0.0}


def main():
    runs = load_runs()
    if not runs:
        print("no readable run folders in %s" % os.path.basename(CSV))
        return 1

    print("computing section integrals for %d run(s)..." % len(runs))
    per_run = {}
    for r in runs:
        per_run[(r["arm"], r["seed"])] = section_stats(r["folder"])

    common = set(next(iter(per_run.values())))
    for per in per_run.values():
        common &= set(per)
    common = sorted(common)
    print("common sections across every run: %d" % len(common))
    print("")

    vals = defaultdict(dict)
    raw = {}
    for r in runs:
        key = (r["arm"], r["seed"])
        cars = None
        for col in ("stats_N_DistinctCars", "stats_DistinctCars"):
            try:
                cars = float(r["row"][col])
                break
            except (KeyError, TypeError, ValueError):
                continue
        m = metrics(per_run[key], common, cars)
        obj = r["row"].get("stats_Objective_PaxPerDelayHr")
        pax = r["row"].get("stats_PaxEquivPassages")
        try:
            m["objective"] = float(obj)
        except (TypeError, ValueError):
            m["objective"] = float("nan")
        try:
            m["pax"] = float(pax)
            m["pax_per_car"] = float(pax) / cars if cars else float("nan")
        except (TypeError, ValueError):
            m["pax"] = float("nan")
            m["pax_per_car"] = float("nan")
        raw[key] = m
        for k, v in m.items():
            vals[k].setdefault(r["arm"], {})[r["seed"]] = v

    seeds = sorted({s for (_a, s) in raw}, key=lambda s: (len(s), s))
    arms = sorted({a for (a, _s) in raw} - {BASE})

    for arm in arms:
        print("=" * 78)
        print("ARM %s  vs  %s" % (arm, BASE))
        print("=" * 78)
        print("  %-9s %-14s %10s %10s %8s %8s %8s" %
              ("seed", "metric", BASE, arm, "delta%", "dz", "p"))
        show = ("objective", "pax_per_car", "traversals", "per_car",
                "veh_km", "mean_speed", "queue_h")
        higher = {"objective": True, "pax_per_car": True, "traversals": True,
                  "per_car": True, "veh_km": True, "mean_speed": True,
                  "queue_h": False}
        for seed in seeds:
            if seed not in vals["objective"].get(arm, {}):
                continue
            for k in show:
                av = vals[k].get(arm, {}).get(seed)
                bv = vals[k].get(BASE, {}).get(seed)
                if av is None or bv is None:
                    continue
                print("  %-9s %-14s %10.4f %10.4f %+8.2f" %
                      (seed, k, bv, av, 100.0 * (av - bv) / bv if bv else 0.0))
        n_paired = len([s for s in seeds
                        if s in vals["objective"].get(arm, {})
                        and s in vals["objective"].get(BASE, {})])
        print("")
        print("  paired across seeds (%d):" % n_paired)
        print("  %-14s %10s %10s %9s %7s %9s  %s" %
              ("metric", BASE, arm, "delta%", "dz", "p", "verdict"))
        for k in show:
            res = paired(vals[k].get(arm, {}), vals[k].get(BASE, {}),
                         seeds, higher[k])
            if not res:
                continue
            if res["n"] < 2:
                verdict = "untestable (n=1)"
            elif res["p"] == res["p"] and res["p"] < 0.05:
                verdict = "distinguishable"
            else:
                verdict = "noise"
            dz = "inf" if res["dz"] == float("inf") else "%.2f" % res["dz"]
            print("  %-14s %10.4f %10.4f %+8.2f%% %7s %9s  %s" %
                  (k, res["bv"], res["av"], res["delta"], dz,
                   "n/a" if res["p"] != res["p"] else "%.3f" % res["p"],
                   verdict))
        # Does the objective's per-seed delta track the clean per-vehicle flow
        # delta? If the numerator is empty accounting, these will not agree.
        od, pd = [], []
        for seed in seeds:
            oa = vals["objective"].get(arm, {}).get(seed)
            ob = vals["objective"].get(BASE, {}).get(seed)
            ca = vals["per_car"].get(arm, {}).get(seed)
            cb = vals["per_car"].get(BASE, {}).get(seed)
            if None in (oa, ob, ca, cb) or not ob or not cb:
                continue
            od.append(100.0 * (oa - ob) / ob)
            pd.append(100.0 * (ca - cb) / cb)
        if len(od) >= 3:
            mo = sum(od) / len(od)
            mp = sum(pd) / len(pd)
            num = sum((x - mo) * (y - mp) for x, y in zip(od, pd))
            den = (sum((x - mo) ** 2 for x in od) *
                   sum((y - mp) ** 2 for y in pd)) ** 0.5
            print("  across seeds, objective delta vs per-car flow delta: r = %s"
                  % ("n/a" if not den else "%.2f" % (num / den)))
        print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
