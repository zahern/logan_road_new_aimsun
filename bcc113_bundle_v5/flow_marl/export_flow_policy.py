"""Export a rules policy to <bundle>/kg/flow_policy.json for Aimsun.

The Aimsun component `shared_tsp_engine/flow_policy.py` (arm
`CHAMP_FIXED_FLOW_RL`) only reads the JSON rule contract:

    {"type": "rules", "default": "NONE",
     "rules": [{"when": {...}, "action": "GE"}, ...]}

State keys: queue_cur, queue_main, queue_next, ds_cur, ds_main, ds_next,
arrivals_cur, elapsed_s, dur_s, cycle_s, phase, main_phase, phase_is_main.
Condition suffixes: _gt, _ge, _lt, _le.

Modes
-----
--example           copy kg/flow_policy.example.json -> kg/flow_policy.json
--from-rules PATH   validate + copy a hand-written rules file
--from-checkpoint   distill a trained RLlib checkpoint to a shallow decision
                    tree and emit rules (scaffold; needs ray + scikit-learn)
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(BUNDLE, "kg", "flow_policy.json")
EXAMPLE = os.path.join(BUNDLE, "kg", "flow_policy.example.json")

ACTIONS = {"NONE", "GE", "ER", "INS"}


def _validate(p):
    if not isinstance(p, dict) or str(p.get("type", "")).lower() != "rules":
        raise SystemExit("policy must be a dict with type='rules'")
    if str(p.get("default", "NONE")).upper() not in ACTIONS:
        raise SystemExit("default must be one of %s" % sorted(ACTIONS))
    for r in p.get("rules") or []:
        if str(r.get("action", "NONE")).upper() not in ACTIONS:
            raise SystemExit("bad rule action: %r" % (r.get("action"),))
    return p


def _write(p, out):
    _validate(p)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(p, fh, indent=2)
    print("wrote", out, "(%d rules)" % len(p.get("rules") or []))


# --------------------------------------------------------------- distillation
BRIDGE_KEYS = ["phase_is_main", "queue_cur", "queue_next",
               "ds_cur", "ds_next", "elapsed_s"]


def _state_to_obs(st):
    """Heuristic bridge-state -> env observation (11 values).

    The deployed Aimsun state is mapped onto the SUMO env's observation layout
    so the trained policy can be queried for distillation. This is approximate:
    the Aimsun bridge exposes DS directly, the SUMO env exposes queue+speed.
    """
    import numpy as np
    q_cur = min(1.0, float(st["queue_cur"]) / 40.0)
    q_nxt = min(1.0, float(st["queue_next"]) / 40.0)
    v_cur = 1.0 - min(1.0, float(st["ds_cur"]) / 1.5)
    v_nxt = 1.0 - min(1.0, float(st["ds_next"]) / 1.5)
    phase = 0.0 if int(st["phase_is_main"]) else 0.5
    tts = min(1.0, float(st["elapsed_s"]) / 60.0)
    return np.asarray([q_cur, v_cur, q_nxt, v_nxt, 0.0, 0.0, 0.0, 0.0,
                       phase, tts, 0.4], dtype=np.float32)


def _tree_to_rules(tree, feature_names, class_names):
    rules = []
    t = tree.tree_

    def walk(node, conds):
        left = int(t.children_left[node])
        right = int(t.children_right[node])
        if left == right:
            cls = class_names[int(t.value[node][0].argmax())]
            if cls != "NONE":
                rules.append({"when": dict(conds), "action": cls})
            return
        feat = feature_names[int(t.feature[node])]
        thr = round(float(t.threshold[node]), 3)
        walk(left, {**conds, feat + "_le": thr})
        walk(right, {**conds, feat + "_gt": thr})

    walk(0, {})
    return rules


def _distill(path):
    import itertools
    import numpy as np
    from sklearn.tree import DecisionTreeClassifier
    from ray.rllib.algorithms.algorithm import Algorithm

    algo = Algorithm.from_checkpoint(path)
    policy = algo.get_policy()
    grid = list(itertools.product(
        [0, 1], [0, 2, 5, 10], [0, 2, 5, 10],
        [0.3, 0.6, 0.9, 1.2], [0.3, 0.6, 0.9, 1.2], [5, 15, 30]))
    X, y = [], []
    for vals in grid:
        st = dict(zip(BRIDGE_KEYS, vals))
        obs = _state_to_obs(st)
        act, _, _ = policy.compute_single_action(obs, explore=False)
        X.append([st[k] for k in BRIDGE_KEYS])
        y.append(int(act))
    clf = DecisionTreeClassifier(max_depth=3, min_samples_leaf=8, random_state=0)
    clf.fit(np.asarray(X, dtype=np.float32), np.asarray(y))
    names = ["NONE", "GE", "ER", "INS"]
    rules = _tree_to_rules(clf, BRIDGE_KEYS, names)
    return {"type": "rules", "default": "NONE", "rules": rules}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--example", action="store_true")
    ap.add_argument("--from-rules")
    ap.add_argument("--from-checkpoint")
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()

    if a.example:
        if not os.path.isfile(EXAMPLE):
            raise SystemExit("missing example: %s" % EXAMPLE)
        _write(json.load(open(EXAMPLE, encoding="utf-8")), a.out)
    elif a.from_rules:
        _write(json.load(open(a.from_rules, encoding="utf-8")), a.out)
    elif a.from_checkpoint:
        _write(_distill(a.from_checkpoint), a.out)
    else:
        ap.error("pass --example, --from-rules, or --from-checkpoint")


if __name__ == "__main__":
    main()
