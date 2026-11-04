"""KG corridor scenario + agent list for the multi-agent scaffold."""
import os

SUMO_HOME = os.environ.get(
    "SUMO_HOME", r"C:\Program Files (x86)\Eclipse\Sumo")
SUMO_BINARY = os.path.join(SUMO_HOME, "bin", "sumo.exe")

# The KG scenario used by the HPC sweeps.
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

# Episode / control settings
HORIZON_S = int(os.environ.get("KG_HORIZON_S", "4500"))
WARMUP_S = int(os.environ.get("KG_WARMUP_S", "300"))
ACTION_EVERY_S = int(os.environ.get("KG_ACTION_EVERY_S", "5"))
MAX_APPROACHES = 4
MAX_QUEUE = 40.0
MAX_SPEED = 20.0
SHARED_REWARD = os.environ.get("KG_SHARED_REWARD", "0") == "1"
