"""run_paxwin_game_vs_notsp.py -- seed A/B: CHAMP_PAXWIN_GAME vs NO_TSP.

Seeds default to 300/400/500/600/700; set PAXWIN_SEEDS="400" for one seed.

Runs, on the SAME seeds and demand:
    NO_TSP_WARMUP  (throwaway; absorbs model warm-up)
    NO_TSP         (baseline, per seed)
    CHAMP_PAXWIN_GAME  (winner base + generalised-Nash bus TSP)

Writes a corridor-specific CSV and, after the batch:
  * a per-seed objective/delay/pax comparison printed to the console;
  * `paxwin_game_vs_notsp.png` (per-seed objective + means);
  * the per-run `plan_evolution_*_cycle.png`, `_green.png`, `_purdue.png`
    figures (written by the engine at AAPIFinish; this script replots any CSV
    that was produced with plotting skipped).

Usage (with the KG model open, AFTER A FULL AIMSUN RESTART):

    import run_paxwin_game_vs_notsp

The arm defaults to CHAMP_PAXWIN_GAME. Set PAXWIN_ARM=CHAMP_PAXWIN_SCATS_STATE
to run the SCATS full-state startup-solve variant instead.
"""
import os as _os
import sys as _sys

_HERE = None
try:
    _HERE = _os.path.dirname(_os.path.abspath(__file__))
except Exception:
    _HERE = None
if not _HERE or not _os.path.isfile(_os.path.join(_HERE, "champion_search.py")):
    _HERE = _os.path.abspath(_os.getcwd())
if _HERE and _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

import champion_search as _cs

ARM = _os.environ.get("PAXWIN_ARM", "CHAMP_PAXWIN_GAME")
_ARM_BY_NAME = {a["name"]: a for a in _cs.ARMS}
assert ARM in _ARM_BY_NAME, "arm %s is not defined in champion_search.ARMS" % ARM

_NOTSP = _ARM_BY_NAME["NO_TSP"]
_NOTSP_WARMUP = dict(_NOTSP, name="NO_TSP_WARMUP")
# Warm-up run is OFF by default: it is a deterministic fixed-time replica of
# NO_TSP on the same seed, so it carries no extra signal. Set PAXWIN_WARMUP=1
# to re-enable it.
_INCLUDE_WARMUP = _os.environ.get("PAXWIN_WARMUP", "0").strip() == "1"
# PAXWIN_ARMS="ARM_A,ARM_B,..." runs ONE NO_TSP baseline followed by every
# listed arm in a single batch (use for the seed-400 suite).
_arms_env = _os.environ.get("PAXWIN_ARMS", "").strip()
if _arms_env:
    _suite = []
    for _n in [s.strip() for s in _arms_env.split(",") if s.strip()]:
        if _n in ("NO_TSP", "NO_TSP_WARMUP"):
            continue
        if _n not in _ARM_BY_NAME:
            raise SystemExit("Unknown arm in PAXWIN_ARMS: %r" % (_n,))
        _suite.append(_ARM_BY_NAME[_n])
    ARMS = ([_NOTSP_WARMUP] if _INCLUDE_WARMUP else []) + [_NOTSP] + _suite
else:
    ARMS = ([_NOTSP_WARMUP] if _INCLUDE_WARMUP else []) + \
        [_NOTSP, _ARM_BY_NAME[ARM]]

# Accept any KNOWN corridor (KG or Logan Road); the guard only catches an
# unexpected / stale model. Override with PAXWIN_EXPECT_CORRIDOR="kg" to pin one.
_EXPECT = [c.strip() for c in _os.environ.get(
    "PAXWIN_EXPECT_CORRIDOR", "kg,logan_road_new").split(",") if c.strip()]
if _EXPECT and _cs.CORRIDOR not in _EXPECT:
    raise SystemExit(
        "Wrong corridor open: found %r, expected one of %s -- open the right "
        "Aimsun model and re-run." % (_cs.CORRIDOR, _EXPECT))

# Seeds. Override with PAXWIN_SEEDS="400" (or "400,500") for a quick single-
# seed iteration; default is the 5 champion seeds.
_seeds_env = _os.environ.get("PAXWIN_SEEDS", "").strip()
if _seeds_env:
    SEEDS = [int(s) for s in _seeds_env.split(",") if s.strip()]
else:
    SEEDS = [300, 400, 500, 600, 700]
_cs.EVAL_SEEDS = list(SEEDS)
_cs.TRAIN_SEEDS = []
_cs.SCORED_SEEDS = list(SEEDS)
_cs.USE_TOPUP_SEEDS = False
_cs.DEMAND_SCALARS = [1.0]
_cs.PARKED_ARMS = set(_cs.PARKED_ARMS) - set(
    [a["name"] for a in ARMS]) - set([ARM, "NO_TSP", "NO_TSP_WARMUP"])

OUT_CSV = (_os.environ.get("PAXWIN_OUT_CSV")
           or _os.path.join(_cs._ROOT, "paxwin_game_vs_notsp.csv"))

print("=" * 72)
print("A/B: %s vs NO_TSP -- %d seeds %s" % (ARM, len(SEEDS), SEEDS))
print("  -> %s" % OUT_CSV)
print("  plan-evolution figures: <kg>/logs/plan_evolution_%s_*_{cycle,green,purdue}.png"
      % ARM)
print("=" * 72)

_cs.main(arms=ARMS, results_csv=OUT_CSV, resume=False)


# ── Post-run comparison ───────────────────────────────────────────────────────
def _aggregate_and_plot():
    import csv as _csv
    import glob as _glob
    import statistics as _st

    if not _os.path.isfile(OUT_CSV):
        print("No results CSV at", OUT_CSV)
        return
    rows = list(_csv.DictReader(open(OUT_CSV, encoding="utf-8", errors="replace")))

    def _num(r, k):
        try:
            return float(r.get(k))
        except Exception:
            return None

    by = {}
    for r in rows:
        by.setdefault(r.get("run_experiment"), []).append(r)

    def _vals(arm, key):
        return [_num(r, key) for r in by.get(arm, []) if _num(r, key) is not None]

    metrics = [
        ("stats_Objective_PaxPerDelayHr", "objective (pax/delay-hr)", True),
        ("stats_TotalPassDelay_hrs", "total pass delay (h)", False),
        ("stats_PaxEquivPassages", "pax-equiv passages", True),
        ("stats_Net_MeanQueue_All", "mean queue (veh)", False),
        ("stats_TSP_Detections", "TSP detections", True),
    ]
    print("\n=== %s vs NO_TSP ===" % ARM)
    for key, label, higher_better in metrics:
        a = _vals("NO_TSP", key)
        b = _vals(ARM, key)
        if not a or not b:
            continue
        ma, mb = _st.mean(a), _st.mean(b)
        rel = (100.0 * (mb - ma) / ma) if ma else 0.0
        sa = _st.pstdev(a) if len(a) > 1 else 0.0
        sb = _st.pstdev(b) if len(b) > 1 else 0.0
        print("  %-26s NO_TSP %.2f (+-%.2f) | %s %.2f (+-%.2f) | %+.1f%%  %s"
              % (label, ma, sa, ARM, mb, sb, rel,
                 "better" if ((rel > 0) == higher_better) else "worse"))

    # per-seed objective plot
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        seed_col = "run_seed"
        seeds = sorted({int(float(r.get(seed_col)))
                        for r in rows if r.get(seed_col) not in (None, "")})
        def _per_seed(arm):
            out = {}
            for r in by.get(arm, []):
                try:
                    out[int(float(r.get(seed_col)))] = float(
                        r.get("stats_Objective_PaxPerDelayHr"))
                except Exception:
                    continue
            return out
        a = _per_seed("NO_TSP")
        b = _per_seed(ARM)
        xs = [s for s in seeds if s in a and s in b]
        if xs:
            import numpy as _np
            fig, ax = plt.subplots(figsize=(max(7.5, len(xs) * 1.4), 4.6))
            w = 0.38
            ax.bar([i - w / 2 for i in range(len(xs))], [a[s] for s in xs], w,
                   label="NO_TSP", color="#90a4ae")
            ax.bar([i + w / 2 for i in range(len(xs))], [b[s] for s in xs], w,
                   label=ARM, color="#1e88e5")
            ax.axhline(_st.mean([a[s] for s in xs]), color="#607d8b", ls="--",
                       lw=1, label="NO_TSP mean")
            ax.axhline(_st.mean([b[s] for s in xs]), color="#1565c0", ls="--",
                       lw=1, label="%s mean" % ARM)
            ax.set_xticks(list(range(len(xs))))
            ax.set_xticklabels([str(s) for s in xs])
            ax.set_xlabel("seed")
            ax.set_ylabel("objective (pax per delay-hour)")
            ax.set_title("Objective per seed: %s vs NO_TSP" % ARM)
            ax.legend(fontsize=8)
            ax.grid(axis="y", alpha=0.3)
            fig.tight_layout()
            out_png = _os.path.splitext(OUT_CSV)[0] + ".png"
            fig.savefig(out_png, dpi=140)
            plt.close(fig)
            print("\n  per-seed objective figure ->", out_png)
    except Exception as _e:
        print("  per-seed plot skipped:", _e)

    # Replot any plan-evolution CSV whose figures were skipped.
    try:
        _kg = _os.path.join(_cs._ROOT, "kg")
        if _kg not in _sys.path:
            _sys.path.insert(0, _kg)
        import plot_plan_evolution as _ppe
        for _p in sorted(_glob.glob(_os.path.join(
                _kg, "logs", "plan_evolution_%s_*.csv" % ARM)),
                key=_os.path.getmtime)[-len(SEEDS):]:
            try:
                _outs = _ppe.run(csv_path=_p)
                if _outs:
                    print("  plan evolution figures:", ", ".join(
                        _os.path.basename(x) for x in _outs))
            except Exception as _ee:
                print("  plan evolution plot failed for %s: %r"
                      % (_os.path.basename(_p), _ee))
    except Exception as _e:
        print("  plan-evolution replot skipped:", _e)


_aggregate_and_plot()
print("DONE ->", OUT_CSV)
