"""run_aimsun_game_train_5seeds.py -- train the saturation-game weights, then evaluate frozen.

Two arms, same adaptive base (``_ADAPTIVE_DSW_RO``):
  1. CHAMP_ADAPTIVE_DSW_GAME_TRAIN  ADAPTIVE_WEIGHT_LR=0.05 / REG=0.02
  2. CHAMP_ADAPTIVE_DSW_GAME        LR=REG=0 (frozen, loads the trained file)

The cycle planner writes every update to
``kg/adaptive_weights_adaptive_game.json`` (see cycle_planner.py:637-643), so the
frozen arm evaluates the weights learned by the train arm. The file is seeded
from ``kg/adaptive_weights_adaptive_dsw.json`` on the first run; set
``GAME_RESET=1`` to restart from the seed.

Run in the Aimsun console AFTER A FULL AIMSUN RESTART, with the KG model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_aimsun_game_train_5seeds.py").read())

Overrides (set before the exec):
    import os
    os.environ["GAME_SEEDS"] = "300,400"
    os.environ["GAME_OUT"]   = "game_train_subset.csv"
    os.environ["GAME_RESET"] = "1"

Outputs (next to this file):
    paxwin_game_train_5seeds.csv / _summary.csv / .png
    kg/adaptive_weights_adaptive_game.json   (trained)
"""
import os
import runpy
import shutil

HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
WEIGHTS = os.path.join(HERE, "kg", "adaptive_weights_adaptive_game.json")
SEED = os.path.join(HERE, "kg", "adaptive_weights_adaptive_dsw.json")

_seeds = os.environ.get("GAME_SEEDS", "300,400,500,600,700").strip() \
    or "300,400,500,600,700"
_out = (os.environ.get("GAME_OUT", "paxwin_game_train_5seeds.csv").strip()
        or "paxwin_game_train_5seeds.csv")
_reset = os.environ.get("GAME_RESET", "0").strip() == "1"

if _reset or not os.path.isfile(WEIGHTS):
    if not os.path.isfile(SEED):
        raise SystemExit("missing seed weights: %s" % SEED)
    shutil.copyfile(SEED, WEIGHTS)
    print("GAME TRAIN: seeded %s from %s" % (WEIGHTS, SEED))
else:
    print("GAME TRAIN: resuming from %s" % WEIGHTS)

os.environ["ARM_SUITE_SEEDS"] = _seeds
os.environ["ARM_SUITE_ARMS"] = (
    "CHAMP_ADAPTIVE_DSW_GAME_TRAIN,CHAMP_ADAPTIVE_DSW_GAME")
os.environ["ARM_SUITE_OUT"] = _out

print("GAME TRAIN: %s -> %s" % (_seeds, _out))
print("  weights: %s" % WEIGHTS)
runpy.run_path(os.path.join(HERE, "run_aimsun_arm_suite_5seeds.py"),
               run_name="__main__")
