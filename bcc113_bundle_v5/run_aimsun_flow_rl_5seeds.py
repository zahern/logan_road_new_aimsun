"""run_aimsun_flow_rl_5seeds.py -- run ONLY CHAMP_FIXED_FLOW_RL vs NO_TSP.

This is the dedicated Flow-arm job. It does NOT run the other arms.

For every seed it runs:
    1 x NO_TSP baseline
    1 x CHAMP_FIXED_FLOW_RL   (reads <bundle>/kg/flow_policy.json)

Run in the Aimsun console AFTER A FULL AIMSUN RESTART, with the KG model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_aimsun_flow_rl_5seeds.py").read())

Optional overrides (set before the exec):
    import os
    os.environ["FLOW_SEEDS"] = "300,400"
    os.environ["FLOW_OUT"]   = "flow_rl_subset.csv"
    os.environ["FLOW_POLICY"] = r"C:\\...\\kg\\flow_policy.json"

Outputs next to this file:
    paxwin_flow_rl_5seeds.csv
    paxwin_flow_rl_5seeds_summary.csv
"""
import csv
import importlib
import json
import os as _os
import statistics as _st
import sys as _sys

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
for _p in (_HERE, _os.path.join(_HERE, "kg")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

FLOW_ARM = "CHAMP_FIXED_FLOW_RL"
_SEEDS = _os.environ.get("FLOW_SEEDS", "300,400,500,600,700").strip() \
    or "300,400,500,600,700"
_OUT = _os.path.join(
    _HERE,
    _os.environ.get("FLOW_OUT", "paxwin_flow_rl_5seeds.csv").strip()
    or "paxwin_flow_rl_5seeds.csv")
# A throwaway NO_TSP run FIRST so the Aimsun main-section topology is fully
# resolved before the measured baseline. Without it, the first run can resolve
# only 2 main approaches per junction and under-count passenger passages.
_WARMUP = _os.environ.get("FLOW_WARMUP", "1").strip() != "0"

# ---- validate before touching the simulator --------------------------------
if "champion_search" in _sys.modules:
    importlib.reload(_sys.modules["champion_search"])
import champion_search as _cs

_names = {a["name"] for a in _cs.ARMS}
if FLOW_ARM not in _names:
    raise SystemExit("%s is not defined in champion_search.ARMS" % FLOW_ARM)
if getattr(_cs, "CORRIDOR", "kg") != "kg":
    raise SystemExit("wrong corridor open: %r (expected 'kg')" % (_cs.CORRIDOR,))

_policy = _os.environ.get("FLOW_POLICY") or _os.path.join(
    _HERE, "kg", "flow_policy.json")
if not _os.path.isfile(_policy):
    raise SystemExit(
        "missing Flow policy: %s\nRun: python flow_marl\\export_flow_policy.py --example"
        % _policy)
try:
    _pol = json.load(open(_policy, encoding="utf-8"))
    _nrules = len(_pol.get("rules") or [])
except Exception as _e:
    raise SystemExit("cannot read Flow policy %s: %r" % (_policy, _e))

_seed_list = [int(s) for s in _SEEDS.split(",") if s.strip()]
print("=" * 78)
print("FLOW-ONLY JOB: %s vs NO_TSP" % FLOW_ARM)
print("  seeds : %s" % _seed_list)
print("  policy: %s  (%d rules)" % (_policy, _nrules))
print("  out   : %s" % _OUT)
print("  warmup: %s" % ("ON (throwaway NO_TSP first)" if _WARMUP else "OFF"))
if _nrules <= 3:
    print("  NOTE  : this looks like the example rule set; train + export a")
    print("          policy before citing results.")
print("=" * 78)

# PAXWIN_ARMS runs ONE NO_TSP baseline + every listed arm (here: one arm).
_os.environ["PAXWIN_SEEDS"] = _SEEDS
_os.environ["PAXWIN_WARMUP"] = "1" if _WARMUP else "0"
_os.environ["PAXWIN_ARM"] = FLOW_ARM
_os.environ["PAXWIN_ARMS"] = FLOW_ARM
_os.environ["PAXWIN_OUT_CSV"] = _OUT

_MOD = "run_paxwin_game_vs_notsp"
if _MOD in _sys.modules:
    importlib.reload(_sys.modules[_MOD])
else:
    import run_paxwin_game_vs_notsp  # noqa: F401  (executes the run)


# ---- summary ---------------------------------------------------------------
def _f(r, k):
    try:
        return float(r.get(k, "") or 0.0)
    except Exception:
        return 0.0


def _summary():
    if not _os.path.isfile(_OUT):
        print("No results CSV at", _OUT)
        return
    with open(_OUT, newline="", encoding="utf-8-sig", errors="replace") as fh:
        rows = list(csv.DictReader(fh))
    by = {}
    for r in rows:
        by.setdefault(str(r.get("run_experiment", "")), []).append(r)

    def get(arm, key):
        out = {}
        for r in by.get(arm, []):
            try:
                out[int(float(r.get("run_seed")))] = _f(r, key)
            except Exception:
                pass
        return out

    # first-run detector/topology guard
    try:
        import os as _os2
        import pandas as _pd
        r0 = by.get("NO_TSP") or []
        if r0:
            f = _os2.path.join(str(r0[0].get("stats_results_folder", "")),
                               "simulation_results_per_intersection.csv")
            if _os2.path.isfile(f):
                _x = _pd.read_csv(f, encoding="utf-8-sig", engine="python")
                _n = int(_x["N_MainSections"].min())
                print("first NO_TSP run: min N_MainSections = %d" % _n)
                if _n < 3:
                    print("WARNING: main-section topology under-resolved (<3).")
                    print("         Re-run with FLOW_WARMUP=1 or discard this baseline.")
    except Exception:
        pass

    base = get("NO_TSP", "stats_Objective_PaxPerDelayHr")
    flow = get(FLOW_ARM, "stats_Objective_PaxPerDelayHr")
    seeds = sorted(set(base) & set(flow))
    print("\n%-6s %10s %10s %10s %10s %10s %8s" %
          ("seed", "NO_TSP", "FLOW", "% vs base", "FLOW main", "FLOW side",
           "bus d/p"))
    srows = []
    for s in seeds:
        mn = get(FLOW_ARM, "stats_MainPassDelay_hrs").get(s, 0.0)
        sd = get(FLOW_ARM, "stats_SidePassDelay_hrs").get(s, 0.0)
        bd = get(FLOW_ARM, "stats_AvgBusPassDelay_s").get(s, 0.0)
        rel = (100.0 * (flow[s] - base[s]) / base[s]) if base[s] else 0.0
        print("%-6d %10.2f %10.2f %+9.1f%% %10.1f %10.1f %8.2f" %
              (s, base[s], flow[s], rel, mn, sd, bd))
        srows.append({
            "seed": s, "no_tsp_obj": base[s], "flow_obj": flow[s],
            "flow_pct_vs_no_tsp": rel,
            "flow_main_delay_hrs": mn, "flow_side_delay_hrs": sd,
            "flow_bus_delay_per_pax_s": bd,
            "flow_ge": get(FLOW_ARM, "stats_TSP_Extensions").get(s, 0.0),
            "flow_ins": get(FLOW_ARM, "stats_TSP_Insertions").get(s, 0.0),
            "flow_er": get(FLOW_ARM, "stats_TSP_EarlyRed").get(s, 0.0),
        })
    if seeds:
        bm = _st.mean(base[s] for s in seeds)
        fm = _st.mean(flow[s] for s in seeds)
        print("\nmean : NO_TSP %.2f | FLOW %.2f | %+.1f%%" %
              (bm, fm, (100.0 * (fm - bm) / bm) if bm else 0.0))
    out = _os.path.splitext(_OUT)[0] + "_summary.csv"
    if srows:
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(srows[0].keys()))
            w.writeheader()
            w.writerows(srows)
        print("wrote", out)
    print("Next: python flow_marl\\inspect_runs.py  (or open", _OUT, ")")


try:
    _summary()
except Exception as _e:
    print("summary failed:", repr(_e))

print("\nDONE ->", _OUT)
