#!/usr/bin/env python3
"""check_sumo_parity.py -- Aimsun-vs-SUMO controller settings parity audit.

Compares, per corridor (kg, logan_road_new):
  1. champion ARMS (names + strategy/coordinated/algo + full overrides)
  2. controller top-level scalar constants
  3. presence of post-August engine features (the fixes that moved behavior)

Usage: python check_sumo_parity.py [--corridor kg|logan_road_new]
Exit 0 when fully in parity, 1 otherwise. Read-only (never touches models).
"""
import ast
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SUMO = r"Z:\tsp\sumo_hpc"
CORR = sys.argv[sys.argv.index("--corridor") + 1] if "--corridor" in sys.argv else None
CORRIDORS = [CORR] if CORR else ["kg", "logan_road_new"]

fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)


def load_arms(path, corridor):
    """Eval the ARMS literal with stubbed names (no Aimsun needed)."""
    tree = ast.parse(io.open(path, encoding="utf-8-sig", errors="ignore").read())
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "ARMS" for t in n.targets))
    is_logan = "logan" in corridor
    ns = {"_SAFE_VETO": 3.0, "BXT_TRAIN_EPSILON": 0.30,
          "CORRIDOR": corridor, "_IS_LOGAN": is_logan,
          "_CORRIDOR": corridor}
    return eval(compile(ast.Expression(node.value), path, "eval"), dict(ns))


# Runner-managed keys: patched per run by the batch (modes, logging, demand
# levers), so file values are transient state, not settings drift. Excluded
# from value comparison (presence still listed in INFO when one-sided).
TRANSIENT_KEYS = {
    "CONTROL_MODE", "GROUP_BASED_BUS_PRIORITY", "TSP_ACTIVE_INTERSECTIONS",
    "COORDINATED_TSP", "COORDINATION_ALGO", "TSP_COOLDOWN_OVERRIDE_S",
    "VERBOSE", "MARK_DETECTION_POINTS", "OVERLAY_DETECTIONS_ON_MAP",
    "TRACK_BUS_POSITIONS", "STATUS_DASHBOARD_INTERVAL_S",
    "LOG_CORRIDOR", "LOG_COST_VETO", "LOG_DELAY", "LOG_DEMAND",
    "LOG_HARMONY", "LOG_HEARTBEAT", "LOG_INIT", "LOG_JUNC_XY",
    "LOG_NODE_ID", "LOG_PT_SCAN", "LOG_REWARD", "LOG_SECTION",
    "LOG_SIDE_DISC", "LOG_STATS", "LOG_TSP_EVT", "LOG_URTSP",
    # Learner train/eval seed lists + exploration are patched PER RUN by the
    # batch (Aimsun: champion_search._set_controller_bxt_seeds; SUMO: passed via
    # env), so the file value is transient runner state, not a settings choice.
    "BXT_TRAIN_SEEDS", "BXT_EVAL_SEEDS", "BXT_TRAIN_EPSILON",
    "CPDQL_TRAIN_SEEDS", "CPDQL_EVAL_SEEDS", "CPDQL_TRAIN_EPSILON",
}


def load_consts(path):
    """Top-level NAME = scalar assignments."""
    out = {}
    for line in io.open(path, encoding="utf-8-sig", errors="ignore"):
        m = re.match(r"^([A-Z][A-Z0-9_]+)\s*=\s*(.+?)\s*(?:#.*)?$", line.rstrip())
        if m:
            try:
                out[m.group(1)] = eval(m.group(2), {})
            except Exception:
                out[m.group(1)] = "<complex>"
    return out


# Feature markers: (label, aimsun rel(s), sumo rel(s), pattern)
FEATURES = [
    ("MIN durations (GE/BP/ER/GR)", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "MIN_GE_EXTENSION_S"),
    ("OC end trigger", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "OC_END_TRIGGER_S"),
    ("GLOBAL_REWARD chain projector", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "project_chain_delay_paxs"),
    ("GLOBAL_REWARD rescore gate", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "_global_reward_on"),
    ("WOBJ 1.0/1.0/0.1", ["kg/intersection_controller.py"], ["kg/intersection_controller.py"], "WOBJ_GAMMA = 0.1"),
    ("viability gate enforced", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "_viability_update"),
    ("tsp_armed enforcement", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "_tsp_armed"),
    ("upstream chain walk", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "_upstream_chain"),
    ("model-topo fallback", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "_model_topo"),
    ("timetable loader", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "_sched_spacing_load_timetable"),
    ("departure matching", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "_match_departure_dev"),
    ("FLAGS audit", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "[FLAGS] exp="),
    ("SIM_END marker", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "[SIM_END]"),
    ("MP binary core", ["shared_tsp_engine/specialized_modes.py"], ["shared_tsp_engine/specialized_modes.py"], "_mp_binary_decision"),
    # Champion CELLQLEARN_GATED cost model (ported to SUMO 2026-09-19)
    ("net-benefit gate", ["shared_tsp_engine/specialized_modes.py"], ["shared_tsp_engine/specialized_modes.py"], "_bus_benefit_total_paxs"),
    ("downstream CTM cascade", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "_cascade_spillback_paxs"),
    ("CASCADE_COST_MODE hook", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "CASCADE_COST_MODE"),
    ("measured side-cost blend", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "_measured_side_delay_penalty"),
    # Full method parity: every decider present in BOTH (ported to SUMO 2026-09-19)
    ("NASH_BARGAIN decider", ["shared_tsp_engine/specialized_modes.py"], ["shared_tsp_engine/specialized_modes.py"], "def dctsp_nash_bargain"),
    ("NASH corridor best-response", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "def nash_corridor_bestresponse"),
    ("CPDQL decider (DCTSP_MARL_RL)", ["shared_tsp_engine/specialized_modes.py"], ["shared_tsp_engine/specialized_modes.py"], "def dctsp_cpdql"),
    ("CENTRALISED decider", ["shared_tsp_engine/specialized_modes.py"], ["shared_tsp_engine/specialized_modes.py"], "def dctsp_centralised"),
    ("Nash phase-total bps", ["shared_tsp_engine/specialized_modes.py"], ["shared_tsp_engine/specialized_modes.py"], "_nash_phase_total_bps"),
    ("OC_- benefit credit", ["shared_tsp_engine/specialized_modes.py"], ["shared_tsp_engine/specialized_modes.py"], "Was 0.0, so"),
    ("SIDE/MAIN queue zones", ["shared_tsp_engine/engine.py"], ["shared_tsp_engine/engine.py"], "MAIN_QUEUE_ZONE_M"),
    ("PARKED_ARMS", ["champion_search.py"], ["sumo_bridge/sweep_arms.py", "champion_search_sumo.py"], "PARKED_ARMS"),
    ("clone guard (rank)", ["rank_champions.py"], ["final_rank.py"], "PARKED_ARMS"),
    ("sweep resume", ["phase3_sensitivity.py"], ["sumo_bridge/run_sweep_hpc.py"], "--resume"),
    ("sweep sanity gate", ["champion_search.py"], ["sumo_bridge/run_sweep_hpc.py"], "_kpi_sanity|_sanity_problems"),
    ("sweep mode check", ["champion_search.py"], ["sumo_bridge/run_sweep_hpc.py"], "_mode_dispatch_problem|_mode_problem"),
    ("sweep clone tripwire", ["rank_champions.py"], ["sumo_bridge/run_sweep_hpc.py", "final_rank.py"], "clone"),
]

for corr in CORRIDORS:
    print(f"===== {corr} =====")
    # 1. ARMS
    try:
        a_aim = {a["name"]: a for a in load_arms(
            os.path.join(ROOT, "champion_search.py"), corr)}
    except Exception as e:
        print(f"FAIL load Aimsun ARMS [{e}]")
        fails.append(f"{corr} load-aimsun-arms")
        continue
    try:
        a_sumo = {a["name"]: a for a in load_arms(
            os.path.join(SUMO, "champion_search_sumo.py"), corr)}
    except Exception as e:
        print(f"FAIL load SUMO ARMS [{e}]")
        fails.append(f"{corr} load-sumo-arms")
        continue
    try:
        a_sweep = {a["name"]: a for a in load_arms(
            os.path.join(SUMO, "sumo_bridge", "sweep_arms.py"), corr)}
    except Exception as e:
        print(f"FAIL load SUMO sweep ARMS [{e}]")
        fails.append(f"{corr} load-sweep-arms")
        continue
    check(f"{corr} arm sets equal",
          set(a_aim) == set(a_sumo),
          f"aimsun-only={sorted(set(a_aim) - set(a_sumo))} "
          f"sumo-only={sorted(set(a_sumo) - set(a_aim))}")
    for name in sorted(set(a_aim) & set(a_sumo)):
        A, S = a_aim[name], a_sumo[name]
        same = (A.get("strategy") == S.get("strategy")
                and bool(A.get("coordinated")) == bool(S.get("coordinated"))
                and str(A.get("coordination_algo")) == str(S.get("coordination_algo"))
                and (A.get("reward_overrides") or {}) == (S.get("reward_overrides") or {}))
        if not same:
            keys = set((A.get("reward_overrides") or {})) | set((S.get("reward_overrides") or {}))
            diffs = [k for k in sorted(keys)
                     if (A.get("reward_overrides") or {}).get(k) != (S.get("reward_overrides") or {}).get(k)]
            extra = []
            if A.get("strategy") != S.get("strategy"):
                extra.append(f"strategy {A.get('strategy')}!={S.get('strategy')}")
            if bool(A.get("coordinated")) != bool(S.get("coordinated")):
                extra.append("coordinated differs")
            if str(A.get("coordination_algo")) != str(S.get("coordination_algo")):
                extra.append("algo differs")
            extra += [f"{k}: aim={ (A.get('reward_overrides') or {}).get(k)!r} "
                      f"sumo={(S.get('reward_overrides') or {}).get(k)!r}" for k in diffs]
            check(f"{corr} arm {name} identical", False, "; ".join(extra))
    # sweep_arms.py (the LIVE HPC sweep file) must match too
    check(f"{corr} sweep arm sets equal",
          set(a_aim) == set(a_sweep),
          f"aimsun-only={sorted(set(a_aim) - set(a_sweep))} "
          f"sweep-only={sorted(set(a_sweep) - set(a_aim))}")
    for name in sorted(set(a_aim) & set(a_sweep)):
        A, S = a_aim[name], a_sweep[name]
        same = (A.get("strategy") == S.get("strategy")
                and bool(A.get("coordinated")) == bool(S.get("coordinated"))
                and str(A.get("coordination_algo")) == str(S.get("coordination_algo"))
                and (A.get("reward_overrides") or {}) == (S.get("reward_overrides") or {}))
        if not same:
            keys = set((A.get("reward_overrides") or {})) | set((S.get("reward_overrides") or {}))
            diffs = [k for k in sorted(keys)
                     if (A.get("reward_overrides") or {}).get(k) != (S.get("reward_overrides") or {}).get(k)]
            extra = []
            if A.get("strategy") != S.get("strategy"):
                extra.append(f"strategy {A.get('strategy')}!={S.get('strategy')}")
            if bool(A.get("coordinated")) != bool(S.get("coordinated")):
                extra.append("coordinated differs")
            if str(A.get("coordination_algo")) != str(S.get("coordination_algo")):
                extra.append("algo differs")
            extra += [f"{k}: aim={ (A.get('reward_overrides') or {}).get(k)!r} "
                      f"sweep={(S.get('reward_overrides') or {}).get(k)!r}" for k in diffs]
            check(f"{corr} sweep arm {name} identical", False, "; ".join(extra))
    # 2. controller constants (numeric/bool/str/list only)
    c_aim = load_consts(os.path.join(ROOT, corr, "intersection_controller.py"))
    c_sumo = load_consts(os.path.join(SUMO, corr, "intersection_controller.py"))
    for key in sorted(set(c_aim) & set(c_sumo)):
        if key in TRANSIENT_KEYS:
            continue
        va, vs = c_aim[key], c_sumo[key]
        if isinstance(va, (int, float, str, bool, list)) and va != vs:
            check(f"{corr} const {key}", False, f"aimsun={va!r} sumo={vs!r}")
    only_a = sorted(k for k in c_aim if k not in c_sumo)
    only_s = sorted(k for k in c_sumo if k not in c_aim)
    if only_a:
        print(f"  INFO {corr} constants only in Aimsun ({len(only_a)}): {only_a[:12]}")
    if only_s:
        print(f"  INFO {corr} constants only in SUMO ({len(only_s)}): {only_s[:12]}")

print("===== engine features (both corridors share the engine) =====")
# report-only: presence differs
for label, rels_a, rels_s, pat in FEATURES:
    alts = pat.split("|")
    try:
        ha = any(any(a in io.open(os.path.join(ROOT, rel),
                                  encoding="utf-8-sig", errors="ignore").read()
                     for a in alts)
                 for rel in rels_a)
    except Exception:
        ha = False
    try:
        hs = any(any(a in io.open(os.path.join(SUMO, rel),
                                  encoding="utf-8-sig", errors="ignore").read()
                     for a in alts)
                 for rel in rels_s)
    except Exception:
        hs = False
    if ha != hs:
        check(f"feature '{label}'",
              False, f"aimsun={ha} sumo={hs}")

print("IN PARITY" if not fails else f"{len(fails)} GAPS")
sys.exit(1 if fails else 0)
