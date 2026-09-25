# sweep_arms.py
# Strategy arms for SUMO/HPC sweeps - copied verbatim from
# github_for_aimsun/champion_search.py (BCC113 Phase 1) so SUMO results are
# directly comparable with your Aimsun champion runs.
#
# Each arm's `reward_overrides` are written into run_config.py by the sweep
# runner via run_sumo_hpc.py --set KEY=VALUE lines.

_SAFE_VETO = 3.0

ARMS = [
    {"name": "NO_TSP", "strategy": "NORMAL", "method": "NO_TSP",
     "coordinated": False, "coordination_algo": "KALMAN", "reward_overrides": {}},

    {"name": "CELLQLEARN", "strategy": "GLOBAL_REWARD", "method": "CELLQLEARN",
     "coordinated": True, "coordination_algo": "SHOCKWAVE", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BXT_MODE": True,
        "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "BXT_DT_S": 1.0, "BXT_EPSILON": 0.02, "BXT_ALPHA": 0.2, "BXT_GAMMA": 0.01,
        "BXT_CAR_OCC": 1.2, "BXT_BALANCE_FACTOR": 1.1,
        "DECIDER_COST_VETO_RATIO": 1.3, "BXT_WARMSTART_FROM_SHARED": True,
        "BXT_SOLVER": "golden",
        "TSP_CYCLE_LENGTH_OVERRIDE_S": 135.0, "PHASE_SEQ_MAX_PER_CYCLE": 1}},

    {"name": "DCTSP_ZIG", "strategy": "GLOBAL_REWARD", "method": "DCTSP_ZIG",
     "coordinated": True, "coordination_algo": "SHOCKWAVE", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "DCTSP_ZIG_MODE": True,
        "MP_ECTM_MODE": False, "BXT_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "ZIG_ENABLE_INS": False, "ZIG_ENABLE_SEQ": False, "ZIG_ENABLE_GR": False,
        "ZIG_BALANCE_FACTOR": 0.35, "ZIG_GE_BALANCE_FACTOR": 0.6,
        "ZIG_MIN_GAIN_S": 15.0, "DECIDER_COST_VETO_RATIO": _SAFE_VETO,
        "DCTSP_CONGESTION_GATE": True, "DCTSP_CONGESTION_GATE_FRACTION": 0.65}},

    {"name": "DCTSP_MP_ECTM", "strategy": "GLOBAL_REWARD", "method": "DCTSP_MP_ECTM",
     "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "MP_ECTM_MODE": True,
        "DCTSP_ZIG_MODE": False, "BXT_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "MP_ECTM_DT_S": 1.0, "MP_ECTM_MIN_EXT_S": 5.0, "MP_ECTM_MAX_EXT_S": 10.0,
        "MP_ECTM_CAR_OCC": 1.2, "MP_ECTM_BALANCE_FACTOR": 0.6,
        "SELFORG_MIN_BUS_DELAY_S": 15.0, "DECIDER_COST_VETO_RATIO": _SAFE_VETO}},

    {"name": "DCTSP_BARGAIN_SPM", "strategy": "GLOBAL_REWARD",
     "method": "DCTSP_BARGAIN_SPM",
     "coordinated": True, "coordination_algo": "SHOCKWAVE", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BARGAIN_SPM_MODE": True,
        "DCTSP_ZIG_MODE": False, "MP_ECTM_MODE": False, "BXT_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
        "BG_BUS_W_IMM": 1.6, "BG_BUS_W_NEAR": 1.35, "BG_BUS_W_FAR": 1.10,
        "BG_MIN_BUS_DELAY_S": 5.0, "BG_MIN_GAIN_S": 5.0, "BG_CASCADE_MULT": 2.0,
        "DCTSP_CONGESTION_GATE": True, "DCTSP_CONGESTION_GATE_FRACTION": 0.75,
        "DECIDER_COST_VETO_RATIO": _SAFE_VETO}},

    {"name": "DCTSP_MARL", "strategy": "GLOBAL_REWARD", "method": "DCTSP_MARL",
     "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0, "REWARD_BETA": 1.0,
        "REWARD_GAMMA": 1.0, "DCTSP_GREEN_REALLOC_MODE": True,
        "GREEN_REALLOC_RECOVER_FRACTION": 1.0, "DCTSP_W_H": 0.50,
        "DCTSP_CAR_WEIGHT": 1.00, "DECIDER_COST_VETO_RATIO": _SAFE_VETO,
        "BXT_MODE": False, "DCTSP_ZIG_MODE": False, "MP_ECTM_MODE": False,
        "BARGAIN_SPM_MODE": False, "CENTRALIZED_MODE": False}},

    {"name": "CENTRALISED", "strategy": "GLOBAL_REWARD", "method": "CENTRALISED",
     "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "CENTRALIZED_MODE": True,
        "CENTRALIZED_INTERVAL_S": 1.0,
        "BXT_MODE": False, "DCTSP_ZIG_MODE": False, "MP_ECTM_MODE": False,
        "BARGAIN_SPM_MODE": False, "CELLQLEARN_DP_MODE": False,
        "DECIDER_COST_VETO_RATIO": _SAFE_VETO}},

    {"name": "CELLQLEARN_SAFE", "strategy": "GLOBAL_REWARD", "method": "CELLQLEARN",
     "coordinated": True, "coordination_algo": "SHOCKWAVE", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BXT_MODE": True,
        "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "BXT_DT_S": 1.0, "BXT_EPSILON": 0.02, "BXT_ALPHA": 0.2, "BXT_GAMMA": 0.01,
        "BXT_CAR_OCC": 1.2, "BXT_BALANCE_FACTOR": 1.1,
        "DECIDER_COST_VETO_RATIO": 1.8, "BXT_WARMSTART_FROM_SHARED": True,
        "BXT_SOLVER": "golden",
        "RULE_PERSON_DELAY_WARRANT": True, "PERSON_DELAY_WARRANT_MIN_PAXS": 400.0,
        "CONDITIONAL_PRIORITY_MIN_LATENESS_S": 0.0,
        "TSP_CYCLE_LENGTH_OVERRIDE_S": 135.0, "PHASE_SEQ_MAX_PER_CYCLE": 1}},
]

LEARNING_ARMS = {"CELLQLEARN", "CELLQLEARN_SAFE"}
EVAL_SEEDS = [300, 400, 500, 600, 700]
TRAIN_SEEDS = [800, 900, 1000, 1100]
BXT_TRAIN_EPSILON = 0.30

# controller flags forced off during sweeps (same as champion_search's
# _disable_batch_plotting) - per-run dashboards cost minutes each
PLOT_FLAGS_OFF = {
    "MARK_DETECTION_POINTS": "False",
    "OVERLAY_DETECTIONS_ON_MAP": "False",
    "TRACK_BUS_POSITIONS": "False",
    "STATUS_DASHBOARD_INTERVAL_S": "0.0",
}
