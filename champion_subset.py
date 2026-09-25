"""
champion_subset.py -- a FAST subset of the champion search: just the CellQLearn
variants (+ NO_TSP as reference) so you can see how CELLQLEARN performs after the
v5 changes (golden-section timing solver, veto 1.3, and the more-selective
CELLQLEARN_SAFE) WITHOUT waiting on all 8 arms.

Reuses everything from champion_search.py (same arm configs, same fair
train-then-freeze machinery, same collection-race retry) so results are directly
comparable -- it just runs fewer arms and writes to champion_subset_<corridor>.csv.

RUN (inside Aimsun, model open):   champion_subset.py
RANK (normal terminal):            python rank_champions.py --subset
   (or just read champion_subset_<corridor>.csv; NO_TSP is the reference row)

Runs: NO_TSP (5 eval) + CELLQLEARN (4 train + 5 eval) + CELLQLEARN_SAFE (4+5)
      = 5 + 9 + 9 = 23 runs.
"""
import os as _os
import champion_search as _cs

# Which arms to include (names from champion_search.ARMS).
SUBSET = {"NO_TSP", "CELLQLEARN", "CELLQLEARN_SAFE"}

# ── SMOKE mode: a FAST confirm that the deficit fix works before the full run ──
# Set SMOKE=True to run only the two seeds that GRIDLOCKED under the golden solver
# (400, 500) with minimal training. If CELLQLEARN's car delay on 400/500 is now
# sane (~18-25s, not 48-56s), the deficit fix worked. ~9 runs instead of 23, and
# it targets exactly the failure -- so a license crash costs little.
SMOKE = False    # full 23-run subset (3 arms x 5 eval + learners' 4 train seeds).
                 #     Set True for the fast 9-run gridlock-seed smoke check.
if SMOKE:
    _cs.TRAIN_SEEDS = [800, 900]      # minimal warm-up
    _cs.EVAL_SEEDS = [400, 500]       # the seeds golden gridlocked on

_subset_arms = [a for a in _cs.ARMS if a["name"] in SUBSET]
_tag = "smoke_" if SMOKE else ""
_subset_csv = _os.path.join(_cs._ROOT, f"champion_subset_{_tag}{_cs.CORRIDOR}.csv")


if __name__ == "__main__":
    _cs._br.log("=" * 70)
    _cs._br.log(f"CHAMPION SUBSET -- corridor={_cs.CORRIDOR} | arms={sorted(SUBSET)}")
    _cs._br.log(f"  -> {_subset_csv}")
    _cs._br.log("=" * 70)
    _cs.main(arms=_subset_arms, results_csv=_subset_csv)
