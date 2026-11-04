"""Bridge for a Flow-trained / offline policy to act inside Aimsun.

Flow itself runs SUMO/RLlib, not an Aimsun Next replication. This module is the
portable contract: train in Flow (or distill an RLlib policy), export a small
JSON rule/table policy, then use the ``CYCLE_ACTION_POLICY='flow'`` arm to pick
GE / ER / INS actions on the fixed-time plan.

Example ``kg/flow_policy.json``::

    {
      "type": "rules",
      "default": "NONE",
      "rules": [
        {"when": {"bus_present": 1, "bus_eta_s_lt": 20,
                  "phase_is_main": 0, "queue_main_gt": 3}, "action": "INS"},
        {"when": {"bus_present": 1, "bus_eta_s_lt": 15,
                  "phase_is_main": 1, "queue_main_gt": 3}, "action": "GE"}
      ]
    }

State keys: queue_cur, queue_main, queue_next, ds_cur, ds_main, ds_next,
arrivals_cur, elapsed_s, dur_s, cycle_s, phase, main_phase, phase_is_main,
bus_present, bus_eta_s, bus_late_s, bus_speed_kmh.

The JSON condition keys are ``<state>_gt``, ``_ge``, ``_lt``, ``_le``, or a
plain equality key. No Flow installation is required in Aimsun.
"""
import json
import os

BUILD = "2026-10-25T3121-flow-bus-aware"


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            p = json.load(fh)
        if not isinstance(p, dict):
            return None
        return p
    except Exception:
        return None


def _num(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def _match(state, cond):
    for key, want in (cond or {}).items():
        k = str(key)
        if k.endswith("_gt"):
            if not (_num(state.get(k[:-3])) > _num(want)):
                return False
        elif k.endswith("_ge"):
            if not (_num(state.get(k[:-3])) >= _num(want)):
                return False
        elif k.endswith("_lt"):
            if not (_num(state.get(k[:-3])) < _num(want)):
                return False
        elif k.endswith("_le"):
            if not (_num(state.get(k[:-3])) <= _num(want)):
                return False
        else:
            if state.get(k) != want:
                return False
    return True


def choose(state, policy):
    """Return NONE / GE / ER / INS, or None when the policy is unusable."""
    if not policy:
        return None
    try:
        typ = str(policy.get("type", "rules")).lower()
        if typ == "rules":
            for rule in policy.get("rules") or []:
                if _match(state, rule.get("when") or {}):
                    a = str(rule.get("action", "NONE")).upper()
                    return a if a in ("NONE", "GE", "ER", "INS") else None
            a = str(policy.get("default", "NONE")).upper()
            return a if a in ("NONE", "GE", "ER", "INS") else None
        return None
    except Exception:
        return None


def resolve_path(explicit=None):
    if explicit:
        return str(explicit)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "kg", "flow_policy.json")
