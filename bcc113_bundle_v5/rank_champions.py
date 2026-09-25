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

# Arms parked out of the campaign (mirror of PARKED_ARMS in
# champion_search.py, the source of truth). Parked arms' rows are excluded
# from ranking entirely -- e.g. MILP_MPC, whose solver backend cannot load
# inside Aimsun's interpreter ([WinError 127]) so its rows are NO_TSP clones.
PARKED_ARMS = {"MILP_MPC"}

OBJ = "stats_Objective_PaxPerDelayHr"
WOBJ = "stats_Objective_Weighted"   # weighted Z1+Z2+Z3+Z4 cost (lower=better)
BUS = "stats_AvgBusPassDelay_s"
CAR = "stats_AvgCarPassDelay_s"
# Prefer the weighted multi-objective (negated to a GOODNESS so higher=better,
# consistent with the rest of this ranker). Pass --legacy-obj to force the old
# pax/delay-hr ratio.
USE_WEIGHTED = "--legacy-obj" not in sys.argv


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


def _goodness(r):
    """Objective as GOODNESS (higher=better): -Objective_Weighted when present
    and non-zero, else the legacy pax/delay-hr ratio."""
    if USE_WEIGHTED:
        w = fnum(r, WOBJ)
        if w == w and w != 0.0:
            return -w
    return fnum(r, OBJ)


def load(corr):
    p = os.path.join(ROOT, f"{_PREFIX}{corr}.csv")
    if not os.path.isfile(p):
        return None
    rows = list(csv.DictReader(open(p)))
    by = defaultdict(lambda: {"obj": [], "bus": [], "car": [], "seeds": set(), "failed": 0,
                              "acts": 0})
    # TSP action columns: an arm totalling ZERO actions across its eval rows
    # is a NO_TSP clone (proven 2026-09-09: DCTSP_MARL 0 ext/0 ins/0 GR/0 ER,
    # per-seed metrics bit-identical to NO_TSP). Clones are listed but can
    # never be crowned -- crowning one sends Phase 2 off to sweep a baseline.
    _ACT_COLS = ("stats_TSP_Extensions", "stats_TSP_Insertions",
                 "stats_TSP_GreenRealloc", "stats_TSP_EarlyRed",
                 "stats_TSP_OffsetCorr", "stats_TSP_PhaseSkip",
                 "stats_TSP_PhaseRot")
    for r in rows:
        if str(r.get("run_seed", "")).split(".")[0] not in EVAL_SEEDS:
            continue                              # skip learners' training-seed rows
        # Respect the truncated-run guard: rows explicitly marked
        # run_success=False (e.g. 10-minute aborted sims) must never rank.
        # Only the explicit-false spellings drop; legacy rows without the
        # column (or True/1) always count.
        if str(r.get("run_success", "")).strip().lower() in (
                "false", "0", "no", "f", "failed"):
            by[r.get("run_experiment", "?")]["failed"] += 1
            continue
        a = r.get("run_experiment", "?")
        if a in PARKED_ARMS:
            continue                              # parked: broken arm, never rank
        try:
            by[a]["acts"] += sum(int(float(r.get(_c) or 0)) for _c in _ACT_COLS)
        except Exception:
            pass
        o = _goodness(r)
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
        (both % vs NO_TSP). NO_TSP itself scores 0 by construction.
        NOTE: goodness is NEGATED cost (negative numbers, higher=better), so
        the improvement denominator must be |base| -- a plain (o-base)/base
        flips the sign and crowns the highest-COST arm (seen 2026-09-05)."""
        o = mean(d["obj"]); b = mean(d["bus"])
        _od = abs(base) if base == base and base else float("nan")
        _bd = abs(base_bus) if base_bus == base_bus and base_bus else float("nan")
        obj_imp = (o - base) / _od * 100 if _od == _od and _od else float("nan")
        bus_imp = (base_bus - b) / _bd * 100 if _bd == _bd and _bd else float("nan")
        s = obj_imp + BUS_RANK_WEIGHT * bus_imp
        return s, obj_imp, bus_imp

    print("\n" + "=" * 78)
    _obj_desc = ("-Objective_Weighted (Z1+Z2+Z3+Z4 cost, HIGHER better)"
                 if USE_WEIGHTED else "pax-throughput / delay-hr, HIGHER better")
    print(f"CORRIDOR: {corr}      (objective = {_obj_desc})")
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
        if a != "NO_TSP" and (champ is None) and d.get("acts", 1) > 0:
            champ = (a, o, imp); star = "  <== CHAMPION"
        elif a != "NO_TSP" and not d.get("acts", 1):
            star = "  [clone: 0 actions]"
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
