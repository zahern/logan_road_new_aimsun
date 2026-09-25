#!/usr/bin/env python3
"""test_zone_chain.py -- offline logic test for _upstream_chain/_zone_queue_count.

Topology: 30 (100 m) -> 20 (100 m) -> 10 (7 m, stop-line section),
          25 (80 m) ---------------^  (merge at node 5).
Vehicles: sec10: 1 @pos 2 | sec20: 3 @pos 10/50/90 | sec30: 2 @pos 5/95
          sec25: 2 @pos 10/70.
Zone 120 m, distances from stop line:
  sec10: 7-2=5 | sec20: 7+(100-p) = 97/57/17 | sec30: 107+(100-p) = 202/112
  sec25: 7+(80-p) = 77/17.
In-zone (<=120): 1 + 3 + 1 (sec30 @95) + 2 = 7.
In-zone lane-m: 7 + 100 + 13 + 80 = 200.
"""
import sys
import types

sys.path.insert(0, "shared_tsp_engine")
import engine as _eng

_SECS = {10: (7.0, 5), 20: (100.0, 4), 30: (100.0, 3), 25: (80.0, 5)}
# node -> [(origin, dest)]; node 5 merges 20 and 25 into 10
_TURNS = {5: [(20, 10), (25, 10)], 4: [(30, 20)]}
_VEHS = {10: [2.0], 20: [10.0, 50.0, 90.0], 30: [5.0, 95.0],
         25: [10.0, 70.0]}


class _Inf:
    def __init__(self, **kw):
        self.__dict__.update(kw)


_eng.AKIInfNetGetSectionANGInf = lambda s: _Inf(
    report=0, length=_SECS[int(s)][0], idNodeOrigin=_SECS[int(s)][1],
    nbCentralLanes=1, nbSideLanes=0)
_eng.AKIInfNetGetNbTurnsInNode = lambda n: len(_TURNS.get(int(n), []))
_eng.AKIInfNetGetDestinationSectionInTurn = lambda n, ti: _TURNS[int(n)][ti][1]
_eng.AKIInfNetGetOriginSectionInTurn = lambda n, ti: _TURNS[int(n)][ti][0]
_eng.AKIVehStateGetNbVehiclesSection = lambda s, _: len(_VEHS.get(int(s), []))
_eng.AKIVehStateGetVehicleInfSection = lambda s, i: _Inf(
    CurrentPos=_VEHS[int(s)][i])
_eng.SIDE_QUEUE_ZONE_M = 120.0

_self = types.SimpleNamespace(config={"MainSections": []})
_cls = _eng.IntersectionController
_self._upstream_chain = types.MethodType(_cls._upstream_chain, _self)

fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)


segs, why = _cls._upstream_chain(_self, 10, 120.0)
got = sorted(s for s, _, _ in segs)
check("tree sections", got == [10, 20, 25, 30], f"{got}")
_bases = {s: db for s, db, _ in segs}
check("branch dist bases", _bases.get(20) == 7.0 and _bases.get(25) == 7.0
      and _bases.get(30) == 107.0, f"{_bases}")
check("zone reached", why == "zone", f"{why}")

cnt, lane_m, why_c = _cls._zone_queue_count(_self, 10)
check("merge count 7", cnt == 7, f"{cnt}")
check("in-zone lane-m 200", lane_m is not None and abs(lane_m - 200.0) < 1e-9,
      f"{lane_m}")

# zone_m override (main-approach use): zone 60 cuts the far vehicles
cnt60, _, _ = _cls._zone_queue_count(_self, 10, 60.0)
check("zone override count 4", cnt60 == 4, f"{cnt60}")

# single-section behaviour preserved when no upstream exists
_del = _TURNS.pop(4)
_TURNS[5] = [(20, 10)]
segs2, why2 = _cls._upstream_chain(_self, 20, 120.0)
check("dead-end stops", [s for s, _, _ in segs2] == [20],
      f"{[s for s, _, _ in segs2]}")
check("dead-end reason", why2 == "dead", f"{why2}")
_TURNS[4] = _del
_TURNS[5] = [(20, 10), (25, 10)]

# main-section boundary stops the walk
_self2 = types.SimpleNamespace(config={"MainSections": [30]})
_self2._upstream_chain = types.MethodType(_cls._upstream_chain, _self2)
segs3, why3 = _cls._upstream_chain(_self2, 10, 120.0)
check("main boundary", sorted(s for s, _, _ in segs3) == [10, 20, 25],
      f"{sorted(s for s, _, _ in segs3)}")
check("main reason present", "main" in why3, f"{why3}")

# managed-junction boundary: node 4 signalised -> 30 excluded, but the
# node-5 merge branch (25) still counts
_prev_ctrls = getattr(_eng, "controllers", None)
_eng.controllers = {99: types.SimpleNamespace(node_id=4)}
try:
    segs4, why4 = _cls._upstream_chain(_self, 10, 120.0)
finally:
    if _prev_ctrls is None:
        try:
            del _eng.controllers
        except Exception:
            pass
    else:
        _eng.controllers = _prev_ctrls
check("junction boundary", sorted(s for s, _, _ in segs4) == [10, 20, 25],
      f"{sorted(s for s, _, _ in segs4)}")
check("managed reason present", "managed" in why4, f"{why4}")

# API failure is distinct from a verified dead-end
_prev_turns = _eng.AKIInfNetGetNbTurnsInNode


def _boom(_n):
    raise RuntimeError("api down")


_eng.AKIInfNetGetNbTurnsInNode = _boom
try:
    segs5, why5 = _cls._upstream_chain(_self, 10, 120.0)
finally:
    _eng.AKIInfNetGetNbTurnsInNode = _prev_turns
check("apifail flagged", "apifail" in why5, f"{why5}")
check("apifail keeps stop section", [s for s, _, _ in segs5] == [10],
      f"{[s for s, _, _ in segs5]}")

# Model-topology fallback: AKI knows nothing (dead), but the model attaches
# section 20 upstream of 10 -> walk continues with reason 'model'
_prev_topo = _eng._model_topo if hasattr(_eng, "_model_topo") else None
_eng._model_topo = lambda: {"org": {10: 50, 20: 40, 30: 40, 25: 50},
                            "by_dest": {50: [20, 25], 40: [30]},
                            "ok": True, "done": True, "n": 4}
_TURNS[5] = []
_TURNS[4] = []
try:
    segs6, why6 = _cls._upstream_chain(_self, 10, 120.0)
finally:
    _TURNS[5] = [(20, 10), (25, 10)]
    _TURNS[4] = [(30, 20)]
    if _prev_topo is not None:
        _eng._model_topo = _prev_topo
check("model fallback walks", sorted(s for s, _, _ in segs6) == [10, 20, 25, 30],
      f"{sorted(s for s, _, _ in segs6)}")
check("model reason", "model" in why6, f"{why6}")

# Model agrees it's a dead-end -> stays 'dead'
_eng._model_topo = lambda: {"org": {10: None}, "by_dest": {},
                            "ok": True, "done": True, "n": 1}
_TURNS[5] = []
try:
    segs7, why7 = _cls._upstream_chain(_self, 10, 120.0)
finally:
    _TURNS[5] = [(20, 10), (25, 10)]
    if _prev_topo is not None:
        _eng._model_topo = _prev_topo
check("model-confirmed dead", [s for s, _, _ in segs7] == [10],
      f"{[s for s, _, _ in segs7]}")
check("dead reason kept", why7 == "dead", f"{why7}")

print("ALL OK" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
