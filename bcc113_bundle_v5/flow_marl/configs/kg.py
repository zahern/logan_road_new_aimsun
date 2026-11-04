"""KG corridor scenario + agent/action settings for the MARL component."""
import os

SUMO_HOME = os.environ.get(
    "SUMO_HOME", r"C:\Program Files (x86)\Eclipse\Sumo")
SUMO_BINARY = os.path.join(SUMO_HOME, "bin", "sumo.exe")

SCENARIO_DIR = os.environ.get(
    "KG_SCENARIO_DIR",
    r"Z:\tsp\sumo_hpc\sumo_bridge\kg_scenario")
SUMOCFG = os.path.join(SCENARIO_DIR, "kg.sumocfg")

# The 12 signalised corridor junctions (tlLogic ids in kg.net.xml).
AGENTS = [
    "n1043762", "n36385", "n36393", "n38339",
    "n39569", "n39572", "n39576", "n39578",
    "n39587", "n39590", "n39593", "n39606",
]

# ---------------------------------------------------------------- actions
# MUST match shared_tsp_engine/flow_policy.py: NONE / GE / ER / INS.
ACTION_NAMES = ["NONE", "GE", "ER", "INS"]
GE_EXTEND_S = float(os.environ.get("KG_GE_EXTEND_S", "5.0"))
ER_TRUNC_S = float(os.environ.get("KG_ER_TRUNC_S", "5.0"))
MIN_GREEN_S = float(os.environ.get("KG_MIN_GREEN_S", "6.0"))

# ---------------------------------------------------------------- episode
HORIZON_S = int(os.environ.get("KG_HORIZON_S", "4500"))
WARMUP_S = int(os.environ.get("KG_WARMUP_S", "300"))
ACTION_EVERY_S = int(os.environ.get("KG_ACTION_EVERY_S", "5"))
MAX_APPROACHES = 4
MAX_QUEUE = 40.0
MAX_SPEED = 20.0
SHARED_REWARD = os.environ.get("KG_SHARED_REWARD", "0") == "1"

# ---- reward weights (passenger-equivalent seconds) -------------------------
# The crucial event is a bus making the green vs stopping at red, so the
# reward is in pax-equivalent delay: bus occupants 40, car/truck 1.5.
BUS_OCC = float(os.environ.get("KG_BUS_OCC", "40.0"))
CAR_OCC = float(os.environ.get("KG_CAR_OCC", "1.5"))
# Per action step: a bus sitting still on the approach is expensive...
BUS_STOP_PENALTY = float(os.environ.get("KG_BUS_STOP_PENALTY", "400.0"))
# ...and a bus that clears the approach is rewarded.
BUS_CLEAR_BONUS = float(os.environ.get("KG_BUS_CLEAR_BONUS", "400.0"))
REWARD_SCALE = 1.0 / 1000.0
