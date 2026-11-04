"""Extracted adaptive controller logic and online weight learner.

This is the clean form of the loop that was spread across engine.py and
cycle_planner.py:

    measure -> build candidate plans -> score -> select -> apply -> observe
            -> update weights -> repeat

The weights are exponentiated-gradient style: features of the selected plan
are reinforced when the following interval improves realized pax-delay and
decayed when it worsens. Weights are bounded and persisted so learning
continues across cycles and seeds.
"""
import json
import math
import os

BUILD = "2026-10-22T3140-adaptive-weights"

DEFAULT_WEIGHTS = {
    "pressure": 1.00,
    "main_share": 0.20,
    "side_share": 0.10,
    "switch": 0.15,
    "queue": 0.10,
    "ds_max": 0.10,
    "arrival": 0.05,
    "link_pressure": 0.10,
    "service_gap": 1.00,
}


def load(path):
    w = dict(DEFAULT_WEIGHTS)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            got = json.load(fh)
        if isinstance(got, dict):
            for k, v in got.items():
                if k in w:
                    w[k] = float(v)
    except Exception:
        pass
    return w


def save(path, weights):
    try:
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(weights, fh, indent=2, sort_keys=True)
    except Exception:
        pass


def score(features, weights):
    """Lower is better. Features are non-negative, roughly [0, 1]."""
    try:
        return float(sum(float(weights.get(k, 0.0)) * float(v)
                         for k, v in (features or {}).items()))
    except Exception:
        return 1e18


def update(weights, features, reward, lr=0.05, reg=0.02):
    """Exponentiated-gradient update driven by realized improvement.

    reward > 0 means pax-delay fell after the selected plan. Features that were
    high in that plan gain weight; features of a plan that worsened delay lose
    weight. Bounded to [0.02, 5.0] so no single term can dominate.
    """
    try:
        r = max(-1.0, min(1.0, float(reward)))
        if abs(r) < 0.05:
            return dict(weights)
        lr = max(0.0, min(float(lr), 0.5))
        reg = max(0.0, min(float(reg), 0.20))
        out = dict(weights)
        for k, v in (features or {}).items():
            if k not in out:
                continue
            e = math.exp(lr * r * max(0.0, float(v)))
            _w = float(out[k]) * e
            # Pull gently back toward the prior so repeated bad intervals
            # cannot collapse every weight to the lower bound.
            _prior = float(DEFAULT_WEIGHTS.get(k, out[k]))
            _w = (1.0 - reg) * _w + reg * _prior
            out[k] = max(0.02, min(5.0, _w))
        return out
    except Exception:
        return dict(weights)


def choose_plan(candidates, features_by_name, weights):
    """Return (best_name, best_score, all_scores)."""
    best = None
    best_s = None
    scores = {}
    for name, _tgt in (candidates or {}).items():
        s = score(features_by_name.get(name) or {}, weights)
        scores[name] = s
        if best_s is None or s < best_s:
            best, best_s = name, s
    return best, best_s, scores


def default_path():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "kg", "adaptive_weights.json")
