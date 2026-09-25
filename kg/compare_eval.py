"""compare_eval.py -- leakage-free comparison of EVERY strategy vs NO_TSP.

Reads batch_results_quicktest.csv (all experiment rows) and no_tsp_baseline.csv
(cached NO_TSP), and reports ONLY the eval seeds (BXT_EVAL_SEEDS) -- the seeds
the learner was NOT trained on.  Every non-NO_TSP experiment present in the CSV
is compared and then ranked by mean objective delta.  Run after a batch:

    python compare_eval.py
"""
import csv, os, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
# Held-out eval seeds from the controller.  Empty => per_seed ONLINE mode (no
# train/eval split): report whatever seeds are actually present in the results.
EVAL = [300, 400, 500]
try:
    _txt = open(os.path.join(HERE, "intersection_controller.py")).read()
    for _line in _txt.splitlines():
        if _line.strip().startswith("BXT_EVAL_SEEDS"):
            EVAL = [int(x) for x in eval(_line.split("=", 1)[1].split("#")[0])]
            break
except Exception:
    pass


def load(path):
    return list(csv.DictReader(open(path))) if os.path.isfile(path) else []


def f(r, k):
    try:
        return float(r[k])
    except Exception:
        return 0.0


res = load(os.path.join(HERE, "batch_results_quicktest.csv"))
base = {int(float(r["run_seed"])): r for r in load(os.path.join(HERE, "no_tsp_baseline.csv"))}

# Every experiment in the results except the baseline, in first-seen order.
experiments = []
for r in res:
    e = r["run_experiment"]
    if e != "NO_TSP" and e not in experiments:
        experiments.append(e)

# per_seed ONLINE mode (no held-out eval seeds): report every seed present in the
# results that also has a cached NO_TSP baseline.  NOTE: online = the model
# learned on the same run it is scored on, so this is a fast directional
# smoke-test, NOT a leakage-free evaluation.
_online = not EVAL
if _online:
    _present = sorted({int(float(r["run_seed"])) for r in res})
    EVAL = [s for s in _present if s in base]

cols = [("stats_Objective_PaxPerDelayHr", "obj", True),
        ("stats_AvgBusPassDelay_s", "busDelay", False),
        ("stats_AvgCarPassDelay_s", "carDelay", False),
        ("stats_TotalPassDelay_hrs", "totDelay", False),
        ("stats_AvgBusTT_s", "busTT", False)]

print("=" * 78)
print("ONLINE SMOKE-TEST (learned on the same run -- directional only)" if _online
      else "LEAKAGE-FREE EVALUATION  (eval seeds only -- never trained on)")
print("seeds:", EVAL, "| experiments:", ", ".join(experiments) or "(none)")
print("=" * 78)

summary = []   # (exp, wins, n, mean_dobj)
for exp in experiments:
    rows = {int(float(r["run_seed"])): r for r in res if r["run_experiment"] == exp}
    wins = n = 0
    dobj = []
    print("\n" + "#" * 78 + "\n### %s\n" % exp + "#" * 78)
    for seed in EVAL:
        if seed not in rows or seed not in base:
            print("seed %s: MISSING (%s absent)" % (
                seed, exp if seed not in rows else "baseline"))
            continue
        n += 1
        print("\n-- seed %s --" % seed)
        print("   %-12s %10s %11s %9s" % ("metric", "NO_TSP", exp[:11], "delta"))
        for key, lab, higher in cols:
            b, c = f(base[seed], key), f(rows[seed], key)
            d = (c - b) / b * 100 if b else 0.0
            better = (d > 0) if higher else (d < 0)
            print("   %-12s %10.2f %11.2f %+8.1f%%%s" % (
                lab, b, c, d, "  ok" if better else ""))
        ob, oc = f(base[seed], cols[0][0]), f(rows[seed], cols[0][0])
        dobj.append((oc - ob) / ob * 100 if ob else 0.0)
        if oc > ob:
            wins += 1
    if n:
        m = st.mean(dobj)
        print("\n  -> %s beats NO_TSP on %d/%d eval seeds; mean obj delta %+.1f%%" % (
            exp, wins, n, m))
        summary.append((exp, wins, n, m))

if summary:
    print("\n" + "=" * 78)
    print("RANKING (by mean objective delta vs NO_TSP; higher = better)")
    print("=" * 78)
    for exp, wins, n, m in sorted(summary, key=lambda x: -x[3]):
        print("   %-22s %+7.1f%%   (%d/%d seeds beat NO_TSP)" % (exp, m, wins, n))
    print("=" * 78)
