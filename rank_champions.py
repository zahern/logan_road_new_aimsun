"""
rank_champions.py -- read the Phase-1 champion-search results for both corridors
and declare each corridor's champion strategy.

    python rank_champions.py [--bus-weight W] [--rank-by {score,obj,bus}]

Reads champion_kg.csv and champion_logan_road_new.csv (whichever exist), averages
each arm's objective over its 5 seeds, ranks them, and names the champion per
corridor. Objective = stats_Objective_PaxPerDelayHr, HIGHER is better. Also shows
bus / car passenger delay and the % improvement vs NO_TSP.

v7 BUS-AWARE RANKING: TSP exists to serve buses, so the champion score combines
the network objective with bus passenger delay:

    score = obj_imp% + BUS_RANK_WEIGHT * bus_imp%

where obj_imp%  = objective improvement vs NO_TSP (higher better) and
      bus_imp%  = bus-delay REDUCTION vs NO_TSP (positive = faster buses).
Default weight 1.0 gives network and bus equal say; `--bus-weight 2` tilts
toward buses. `--rank-by obj` restores the old pure-objective ranking.
"""
import os, sys, csv, statistics as st
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
CORRIDORS = ["kg", "logan_road_new"]
# `python rank_champions.py --subset` ranks the champion_subset_*.csv files
# (CellQLearn-only fast test) instead of the full champion_*.csv.
# `--smoke` ranks the SMOKE subset (champion_subset_smoke_<corr>.csv) instead --
# the fast gridlock-seed check written by champion_subset.py when SMOKE=True.
_PREFIX = ("champion_subset_smoke_" if "--smoke" in sys.argv
           else "champion_subset_" if "--subset" in sys.argv else "champion_")
# Only these seeds count toward the ranking. Learning arms also run TRAIN_SEEDS
# (800-1100) which must be ignored here -- every arm is compared on EVAL_SEEDS.
EVAL_SEEDS = {"300", "400", "500", "600", "700"}

OBJ = "stats_Objective_PaxPerDelayHr"
BUS = "stats_AvgBusPassDelay_s"
CAR = "stats_AvgCarPassDelay_s"


def _cli_float(flag, default):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        try:
            return float(sys.argv[i + 1])
        except (IndexError, ValueError):
            pass
    return default


BUS_RANK_WEIGHT = _cli_float("--bus-weight", 1.0)
RANK_BY = "obj" if "--rank-by" in sys.argv else "score"


def fnum(r, k):
    try:
        return float(r[k])
    except Exception:
        return float("nan")


def load(corr):
    p = os.path.join(ROOT, f"{_PREFIX}{corr}.csv")
    if not os.path.isfile(p):
        return None
    rows = list(csv.DictReader(open(p)))
    by = defaultdict(lambda: {"obj": [], "bus": [], "car": [], "seeds": set(), "failed": 0})
    for r in rows:
        if str(r.get("run_seed", "")).split(".")[0] not in EVAL_SEEDS:
            continue                              # skip learners' training-seed rows
        a = r.get("run_experiment", "?")
        o = fnum(r, OBJ)
        # Drop failed runs (objective 0 / NaN) from the means; count them instead.
        if not (o == o) or o == 0.0:
            by[a]["failed"] += 1
            continue
        by[a]["obj"].append(o)
        by[a]["bus"].append(fnum(r, BUS))
        by[a]["car"].append(fnum(r, CAR))
        by[a]["seeds"].add(r.get("run_seed", "?"))
    return by


def mean(xs):
    xs = [x for x in xs if x == x]           # drop NaN
    return st.mean(xs) if xs else float("nan")


any_found = False
overall = {}
for corr in CORRIDORS:
    by = load(corr)
    if by is None:
        _script = "champion_subset.py" if _PREFIX.startswith("champion_subset") else "champion_search.py"
        print(f"[skip] {_PREFIX}{corr}.csv not found -- run {_script} with the "
              f"{corr} model open.")
        continue
    any_found = True
    base = mean(by.get("NO_TSP", {"obj": []})["obj"])
    base_bus = mean(by.get("NO_TSP", {"bus": []})["bus"])

    def score_of(a, d):
        """v7 bus-aware champion score: obj improvement + w x bus-delay reduction
        (both % vs NO_TSP). NO_TSP itself scores 0 by construction."""
        o = mean(d["obj"]); b = mean(d["bus"])
        obj_imp = (o - base) / base * 100 if base == base and base else float("nan")
        bus_imp = (base_bus - b) / base_bus * 100 if base_bus == base_bus and base_bus else float("nan")
        s = obj_imp + BUS_RANK_WEIGHT * bus_imp
        return s, obj_imp, bus_imp

    print("\n" + "=" * 78)
    print(f"CORRIDOR: {corr}      (objective = pax-throughput / delay-hr, HIGHER better)")
    print(f"  ranking by: {RANK_BY} | bus weight = {BUS_RANK_WEIGHT:g}")
    print("=" * 78)
    print("  %-20s %9s %9s %9s %10s %10s %8s %6s" %
          ("arm", "obj", "busDelay", "carDelay", "vsNO_TSP%", "busImp%", "score", "seeds"))
    ranked = sorted(by.items(), key=lambda kv: -(mean(kv[1]["obj"]) if RANK_BY == "obj"
                                                 else score_of(*kv)[0]))
    champ = None
    for a, d in ranked:
        o = mean(d["obj"]); b = mean(d["bus"]); c = mean(d["car"])
        s, imp, busimp = score_of(a, d)
        star = ""
        if a != "NO_TSP" and (champ is None):
            champ = (a, o, imp); star = "  <== CHAMPION"
        nseed = len(d["seeds"]); fl = d.get("failed", 0)
        seedtag = ("%d" % nseed) + (" (%dfail)" % fl if fl else "")
        print("  %-20s %9.1f %9.2f %9.2f %+9.1f%% %+9.1f%% %+7.1f %8s%s" %
              (a, o, b, c, imp, busimp, s, seedtag, star))
    if champ:
        overall[corr] = champ
        verdict = "beats NO_TSP" if champ[2] == champ[2] and champ[2] > 0 else "does NOT beat NO_TSP"
        print(f"\n  -> {corr} champion: {champ[0]}  (obj {champ[1]:.1f}, "
              f"{champ[2]:+.1f}% vs NO_TSP -- {verdict})")

if any_found and overall:
    print("\n" + "=" * 78)
    print("CHAMPIONS")
    print("=" * 78)
    for corr, (a, o, imp) in overall.items():
        print(f"  {corr:18s} -> {a:20s} ({imp:+.1f}% vs NO_TSP)")
    print("=" * 78)
    print("Next (matrix Phase 2): run each corridor's champion + NO_TSP across the")
    print("6 demand levels x 5 seeds.")
elif not any_found:
    print("\nNo champion_*.csv found. Run champion_search.py inside Aimsun (once per")
    print("corridor, with that corridor's model open) first.")
