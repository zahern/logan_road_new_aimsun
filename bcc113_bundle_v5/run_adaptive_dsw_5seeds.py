"""run_adaptive_dsw_5seeds.py -- CHAMP_ADAPTIVE_AIMSUN_DSW vs NO_TSP, 5 seeds.

For each seed: ONE NO_TSP baseline, then CHAMP_ADAPTIVE_AIMSUN_DSW, on the same
seed / demand / build (so every comparison is same-seed, per AGENTS.md RULE 3).

Default seeds are the 5 champion seeds: 300,400,500,600,700.
Override with ADAPTIVE_SEEDS="400,401,402,403,404".
Override the arm with ADAPTIVE_ARM="CHAMP_ADAPTIVE_AIMSUN_DSW".

Outputs:
    paxwin_adaptive_dsw_5seeds.csv        (raw per-run rows)
    paxwin_adaptive_dsw_5seeds.png        (per-seed objective bars + means)
    <kg>/logs/plan_evolution_<arm>_*_...  (per-run plan figures)

Run in the Aimsun console AFTER A FULL AIMSUN RESTART (RULE 2), with the KG
OR the Logan Road model open (the script auto-detects which corridor is open and
tags the output CSV accordingly):

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_adaptive_dsw_5seeds.py").read())
"""
import csv
import importlib
import os as _os
import statistics as _st
import sys as _sys

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

_SEEDS = _os.environ.get("ADAPTIVE_SEEDS", "300,400,500,600,700").strip() \
    or "300,400,500,600,700"
# Sweep the DSW family by default: base (no hysteresis) + the two switch-margin
# variants, so one 5-seed run shows which is the most CONSISTENT winner.
_ARMS = _os.environ.get(
    "ADAPTIVE_ARMS",
    "CHAMP_ADAPTIVE_AIMSUN_DSW,CHAMP_ADAPTIVE_DSW_H10,CHAMP_ADAPTIVE_DSW_H20,"
    "CHAMP_ADAPTIVE_DSW_TSP,CHAMP_ADAPTIVE_DSW_H10_TSP"
).strip() or "CHAMP_ADAPTIVE_AIMSUN_DSW"
_ARM = _ARMS.split(",")[0].strip()

# ── Fail fast before touching the simulator ────────────────────────────────
# Import champion_search FIRST so it auto-detects the open corridor; only then
# put that corridor's dir on sys.path (inserting the wrong corridor's dir would
# let `import batch_runner` resolve to the other corridor's runner).
if "champion_search" in _sys.modules:
    importlib.reload(_sys.modules["champion_search"])
import champion_search as _cs

_CORR = getattr(_cs, "CORRIDOR", "kg")
_ALLOWED = ("kg", "logan_road_new")
if _CORR not in _ALLOWED:
    raise SystemExit(
        "Unsupported corridor %r (expected one of %s) -- open the KG or Logan "
        "Road Aimsun model and re-run." % (_CORR, _ALLOWED))
_CORR_DIR = _os.path.join(_HERE, _CORR)
if _CORR_DIR not in _sys.path:
    _sys.path.insert(0, _CORR_DIR)
print("corridor detected: %s" % _CORR)

_arm_names = {a["name"] for a in _cs.ARMS}
_missing = [a for a in _ARMS.split(",") if a.strip() and a.strip() not in _arm_names]
if _missing:
    raise SystemExit(
        "arm(s) %r not defined in champion_search.ARMS (have %d arms)"
        % (_missing, len(_arm_names)))

# The DSW arms read the shared DS-dominant seed weights by an ABSOLUTE path in
# kg/ (generic / corridor-agnostic / frozen, so it is fine for Logan too); it
# must exist.
_WEIGHTS = _os.path.join(_HERE, "kg", "adaptive_weights_adaptive_dsw.json")
if not _os.path.isfile(_WEIGHTS):
    raise SystemExit("missing DS-dominant weights file: %s" % _WEIGHTS)

# Tag the output by corridor so a KG run and a Logan run do not overwrite each
# other's results.
_OUT = _os.path.join(_HERE, "paxwin_adaptive_dsw_5seeds_%s.csv" % _CORR)

_seed_list = [int(s) for s in _SEEDS.split(",") if s.strip()]

# PAXWIN_ARMS runs ONE NO_TSP baseline followed by the listed arm(s).
_os.environ["PAXWIN_SEEDS"] = _SEEDS
_os.environ["PAXWIN_WARMUP"] = "0"
_os.environ["PAXWIN_ARM"] = _ARM
_os.environ["PAXWIN_ARMS"] = _ARMS
_os.environ["PAXWIN_OUT_CSV"] = _OUT

print("=" * 84)
print("SWEEP: %s vs NO_TSP -- %d seeds %s" % (_ARMS, len(_seed_list), _seed_list))
print("  weights: %s" % _WEIGHTS)
print("  output : %s" % _OUT)
print("=" * 84)

_MOD = "run_paxwin_game_vs_notsp"
if _MOD in _sys.modules:
    importlib.reload(_sys.modules[_MOD])
else:
    import run_paxwin_game_vs_notsp  # noqa: F401  (executes the batch at import)


# ── Per-seed + mean comparison (same-seed pairing, RULE 3) ─────────────────
def _f(r, k):
    try:
        return float(r.get(k, "") or 0.0)
    except Exception:
        return 0.0


def _summary():
    if not _os.path.isfile(_OUT):
        print("No results CSV at", _OUT)
        return
    with open(_OUT, newline="", encoding="utf-8-sig",
              errors="replace") as fh:
        rows = list(csv.DictReader(fh))

    by = {}
    for r in rows:
        by.setdefault(str(r.get("run_experiment", "")), []).append(r)

    def per_seed(arm, key):
        out = {}
        for r in by.get(arm, []):
            try:
                out[int(float(r.get("run_seed")))] = float(r.get(key))
            except Exception:
                continue
        return out

    metrics = [
        ("stats_Objective_PaxPerDelayHr", "objective (pax/delay-hr)", True),
        ("stats_TotalPassDelay_hrs", "total pass delay (h)", False),
        ("stats_Net_MeanQueue_All", "mean queue (veh)", False),
        ("stats_TSP_NaturalGreen", "natural green", True),
    ]

    print("\n" + "=" * 84)
    print("PER-SEED: %s vs NO_TSP" % _ARM)
    print("=" * 84)
    print("%-24s %8s %14s %14s %9s"
          % ("metric", "seed", "NO_TSP", _ARM[:14], "delta"))
    for key, label, _higher in metrics:
        a = per_seed("NO_TSP", key)
        b = per_seed(_ARM, key)
        for s in _seed_list:
            if s in a and s in b:
                d = (100.0 * (b[s] - a[s]) / a[s]) if a[s] else 0.0
                print("%-24s %8d %14.2f %14.2f %+8.1f%%"
                      % (label, s, a[s], b[s], d))

    print("\n" + "=" * 84)
    print("MEAN (n seeds): %s vs NO_TSP" % _ARM)
    print("=" * 84)
    for key, label, higher_better in metrics:
        a = [v for s, v in per_seed("NO_TSP", key).items() if s in _seed_list]
        b = [v for s, v in per_seed(_ARM, key).items() if s in _seed_list]
        if not a or not b:
            continue
        ma, mb = _st.mean(a), _st.mean(b)
        sd_a = _st.pstdev(a) if len(a) > 1 else 0.0
        sd_b = _st.pstdev(b) if len(b) > 1 else 0.0
        rel = (100.0 * (mb - ma) / ma) if ma else 0.0
        verdict = "better" if ((rel > 0) == higher_better) else "worse"
        print("  %-26s NO_TSP %.2f (+-%.2f) | %s %.2f (+-%.2f) | %+.1f%%  %s"
              % (label, ma, sd_a, _ARM, mb, sd_b, rel, verdict))


try:
    _summary()
except Exception as _e:
    print("5-seed summary failed:", repr(_e))

print("\nDONE ->", _OUT)
