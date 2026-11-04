"""Rolling cycle-level planner (one-cycle observation delay) for KG.

The existing SCATS-state solver runs once at startup. This module adds the
operator's rolling variant: at a cycle boundary, observe the WHOLE system
state, solve next cycle's splits for all junctions together, then apply that
plan one cycle later. PBIL chooses the global main-share gene vector using
the engine's future-pressure projector; SCATS historical plans seed the base
splits.

Opt-in only (CYCLE_PLANNER=True). Variants are expressed entirely through
flags so champion_search.py can expose several arms:

    CYCLE_PLANNER=True
    CYCLE_PLANNER_USE_SCATS=True
    CYCLE_PLANNER_PBIL=True
    CYCLE_PLANNER_DELAY_CYCLES=1
    CYCLE_PLANNER_INTERVAL_S=120
    CYCLE_PLANNER_WARM_S=300
    CYCLE_PLANNER_CANDIDATES=8
    CYCLE_PLANNER_DELTA=0.15
    CYCLE_PLANNER_HORIZON_CYCLES=4

The planner NEVER moves the model's absolute main-green start: application
goes through controller._apply_plan_durations_offset_preserving(MainPhase).
"""
import math
import random

BUILD = "2026-10-22T2900-cycle-planner"

_ST = {
    "last_t": -1e9,
    "apply_t": None,
    "pending": [],
    "p": {},
    "gene": {},
    "generation": 0,
    "arr": {},
    "arr_src": {},
    "arr_last_t": {},
    "aw": None,
    "aw_prev": {},
}


def _cfg(G, name, default):
    try:
        v = G.get(name, default)
        return default if v is None else v
    except Exception:
        return default


def _live_greens(ctrl, timeSta, G):
    try:
        jid = int(getattr(ctrl, "node_id", 0) or 0) or int(ctrl.id)
        phases = [int(p) for p in (getattr(ctrl, "phase_list", None) or [])]
        if not phases:
            return None, None, None
        g = {}
        for p in phases:
            try:
                g[p] = max(0.0, float(
                    G["GetPhaseDuration"](jid, p, timeSta) or 0.0))
            except Exception:
                g[p] = 0.0
        C = sum(g.values())
        main = int(getattr(ctrl, "MainPhase",
                           getattr(ctrl, "BusPhase", 0)) or 0)
        if C <= 1.0 or main not in g:
            return None, None, None
        return g, C, main
    except Exception:
        return None, None, None



def _arrival_rates(ctrl, live, C, main, timeSta, now, G):
    """Composite arrival-rate estimate (veh/h) per phase.

    Uses, in priority order:
      1. the engine DS snapshot's q_vph (which already blends real detector
         loops, virtual loops, section flow, standing queue and spillback);
      2. REAL AAPI section ENTER crossings (incoming vehicles, not queue);
      3. an EWMA over previous estimates (temporal pattern, not one tick);
      4. for phases with no mapped vehicle sections, a pooled / green-weighted
         fallback from the junction's total incoming flow -- so an unmapped
         phase is inferred from the patterns that DO count, instead of skipped.
    """
    try:
        jid = int(getattr(ctrl, "node_id", 0) or 0) or int(ctrl.id)
        snap = ctrl._approach_ds_snapshot(timeSta) or {}
        info = snap.get("info") or {}
        blend = float(_cfg(G, "CYCLE_PLANNER_ARRIVAL_BLEND", 0.50) or 0.5)
        alpha = float(_cfg(G, "CYCLE_PLANNER_ARRIVAL_ALPHA", 0.30) or 0.3)
        minv = float(_cfg(G, "CYCLE_PLANNER_ARRIVAL_MIN_VPH", 0.0) or 0.0)
        mode = str(_cfg(G, "CYCLE_PLANNER_UNMAPPED_MODE", "green_weighted")
                   or "green_weighted").lower()

        # Section ENTRY crossings (real incoming vehicles) for this junction.
        _sec_map = G.get("_SEC_JCT") or {}
        _evfn = G.get("_section_event_flow")
        _enter_total = 0.0
        _enter_n = 0
        if _evfn is not None and _sec_map:
            for _sec, _j in _sec_map.items():
                if int(_j) != jid:
                    continue
                _v = None
                try:
                    _v = _evfn(_sec, now, 300.0, "enter")
                except Exception:
                    _v = None
                if _v is not None:
                    _enter_total += float(_v)
                    _enter_n += 1

        _ST["arr"].setdefault(jid, {})
        _ST["arr_src"].setdefault(jid, {})
        prev = _ST["arr"].get(jid, {})
        out = {}
        _src = {}
        for p, gv in live.items():
            p = int(p)
            q = 0.0
            try:
                q = float((info.get(p) or {}).get("q_vph", 0.0) or 0.0)
            except Exception:
                q = 0.0
            _sec_ev = None
            if _evfn is not None:
                for _sec, _j in _sec_map.items():
                    if int(_j) != jid:
                        continue
                    try:
                        _v2 = _evfn(_sec, now, 300.0, "enter")
                    except Exception:
                        continue
                    # A single section may feed several phases; do not
                    # double-count. Use only the first non-None entry event
                    # rate for this phase and attribute it by green share.
                    if _v2 is not None:
                        _sec_ev = _v2
                        break
            est = None
            # Measured DS q is phase-specific and already blends detector
            # loops, queue and spillback. The section-event path is only a
            # fallback: it is not phase-specific and, until the AAPI timestamp
            # fix, admitted wall-clock/future events and produced 47k veh/h.
            if q > 0.0:
                est = q
                _src[p] = "ds"
            elif _sec_ev is not None:
                est = _sec_ev
                _src[p] = "events"
            if est is None and mode != "skip":
                share = (float(gv) / max(C, 1.0)) if mode == "green_weighted" \
                    else (1.0 / max(len(live), 1))
                if _enter_total > 0.0:
                    est = _enter_total * share
                    _src[p] = "pooled_%s" % mode
                else:
                    est = minv
                    _src[p] = "min_vph"
            if est is None:
                est = 0.0
            # Physical cap: an approach cannot exceed saturation flow x lanes.
            try:
                _lanes = float((info.get(p) or {}).get("lanes", 1.0) or 1.0)
            except Exception:
                _lanes = 1.0
            _cap = max(float(_cfg(G, "CYCLE_PLANNER_ARRIVAL_MAX_VPH", 7200.0)
                             or 7200.0), max(_lanes, 1.0) * 1800.0)
            est = min(float(est), _cap)
            est = max(minv, float(est))
            # EWMA smoothing per phase (keeps the pattern, kills one-tick noise).
            pprev = prev.get(p)
            pprev = float(pprev) if pprev is not None else None
            if pprev is None:
                out[p] = est
            else:
                out[p] = alpha * est + (1.0 - alpha) * pprev
            _ST["arr"][jid][p] = out[p]
            _ST["arr_src"][jid][p] = _src[p]
        _ST["arr_last_t"][jid] = now
        return out
    except Exception:
        return {}

def _target_from_arrivals(arr, C, main, mg, floor):
    """Webster-style proportional allocation from arrival rates."""
    try:
        if C <= 1.0:
            return None
        weights = {p: max(float(v), 0.0) for p, v in arr.items()}
        tot = sum(weights.values())
        if tot <= 0.0:
            return None
        others = [p for p in weights if p != main]
        if not others:
            return None
        _floor = float(floor if floor is not None else mg)
        tgt = {}
        for p in weights:
            tgt[p] = max(0.0, C * (weights[p] / tot))
        # Enforce min green and main floor; borrow from the largest other phase.
        for p in others:
            if tgt.get(p, 0.0) < mg:
                need = mg - tgt[p]
                tgt[p] = mg
                tgt[main] = tgt.get(main, 0.0) - need
        if tgt.get(main, 0.0) < _floor:
            need = _floor - tgt.get(main, 0.0)
            tgt[main] = _floor
            for p in sorted(others, key=lambda q: -tgt.get(q, 0.0)):
                if need <= 0.05:
                    break
                take = max(0.0, tgt[p] - mg)
                take = min(take, need)
                tgt[p] -= take
                need -= take
            if need > 0.05:
                return None
        # Exact cycle identity (rounding + borrow).
        _s = sum(tgt.values())
        _big = max(others, key=lambda q: tgt.get(q, 0.0))
        tgt[_big] += C - _s
        if tgt[_big] < mg - 0.05:
            return None
        return {p: round(max(0.0, v), 1) for p, v in tgt.items()}
    except Exception:
        return None


def _scats_target(ctrl, live, C, main, timeSta, G):
    try:
        shp = G.get("_shp")
        sss = G.get("_sss")
        if shp is None or sss is None:
            return None
        jid = int(getattr(ctrl, "node_id", 0) or 0) or int(ctrl.id)
        seed = shp.scats_hist_plan(
            jid,
            daytype=int(_cfg(G, "SCATS_HIST_DAYTYPE", 8) or 8),
            tod_min=float(timeSta) / 60.0 % 1440.0,
            share=None)
        if not seed:
            return None
        ms = sss.main_stage_share(seed.get("greens"))
        return sss.target_splits(
            live, main, C, ms,
            float(_cfg(G, "PLAN_MIN_GREEN_S", 7.0) or 7.0))
    except Exception:
        return None


def _model_target(ctrl, live, C, main, G):
    try:
        cfg = list((getattr(ctrl, "config", {}) or {}).get(
            "GreenPhaseDuration") or [])
        if not cfg:
            return None
        g = {}
        for p in live:
            i = int(p) - 1
            if 0 <= i < len(cfg):
                g[int(p)] = max(0.0, float(cfg[i] or 0.0))
        if not g or sum(g.values()) <= 0:
            return None
        _s = sum(g.values())
        out = {p: C * v / _s for p, v in g.items()}
        mg = float(_cfg(G, "PLAN_MIN_GREEN_S", 7.0) or 7.0)
        for p in out:
            if p != main and out[p] < mg:
                out[main] -= mg - out[p]
                out[p] = mg
        if main in out and out[main] < mg:
            return None
        return {p: round(v, 1) for p, v in out.items()}
    except Exception:
        return None


def _service_gap(ctrl, C, tgt, info, G):
    """Demand-weighted unmet service under a candidate split."""
    try:
        _mu = max(float(getattr(ctrl, "SaturationFlow", 1800.0) or 1800.0), 1.0)
        _num = 0.0
        _den = 0.0
        for p, pi in (info or {}).items():
            _p = int(p)
            _q = max(0.0, float(pi.get("q_vph", 0.0) or 0.0))
            _ln = max(int(pi.get("lanes", 1) or 1), 1)
            _g = max(0.0, float((tgt or {}).get(_p, 0.0)))
            _cap = _mu * _ln * (_g / max(C, 1.0))
            _gap = max(0.0, _q - _cap)
            _num += _gap
            _den += max(_q, 1.0)
        return min(5.0, _num / max(_den, 1.0))
    except Exception:
        return 0.0


def _nash_thru_target(ctrl, live, C, main, timeSta, G):
    """A Nash-throughput split as a CYCLE-PLANNER CANDIDATE.

    The game is between phases over green time: each phase's utility is the
    passengers it can discharge at its allocated green (demand-capped CTM
    capacity x CarOcc). The game is solved by the engine's _mp_nash_alloc
    (thru_override=True) and returned as a full phase target (greens +
    interphases = C) so the DSW plan library can score it against live /
    arrival / SCATS / model. If the library selects it, the normal cycle-plan
    apply path installs it; the DSW plan remains the base controller.
    """
    try:
        if not bool(_cfg(G, "CYCLE_PLANNER_NASH_THRU", False)):
            return None
        try:
            import shared_tsp_engine.engine as _E
        except ImportError:
            import engine as _E
        _alloc = _E._mp_nash_alloc(
            ctrl, float(timeSta), timeSta, thru_override=True)
        if not _alloc:
            return None
        _green = set(int(p) for p in _alloc.keys())
        _main = int(main)
        if _main not in _green:
            return None
        _mg = float(_cfg(G, "PLAN_MIN_GREEN_S", 7.0) or 7.0)
        _inter = {int(p): float(v) for p, v in live.items()
                  if int(p) not in _green}
        _isum = sum(_inter.values())
        _gbudget = float(C) - _isum
        if _gbudget <= 1.0:
            return None
        _sum = sum(max(0.0, float(v)) for v in _alloc.values())
        if _sum <= 1e-6:
            return None
        _tgt = dict(_inter)
        for p, v in _alloc.items():
            _tgt[int(p)] = max(_mg, float(v) * _gbudget / _sum)
        # exact cycle identity: put the rounding residue on the largest
        # non-main green phase
        _others = [p for p in _tgt if p != _main and p not in _inter]
        if not _others:
            return None
        _big = max(_others, key=lambda p: _tgt.get(p, 0.0))
        _tgt[_big] += float(C) - sum(_tgt.values())
        # protect the commissioned main floor (progression)
        try:
            _fl = _main_floor(ctrl, dict(live), _main, _mg, G)
            if _tgt.get(_main, 0.0) < _fl:
                _need = _fl - _tgt.get(_main, 0.0)
                _tgt[_main] = _fl
                for _p in sorted(_others, key=lambda q: -_tgt.get(q, 0.0)):
                    if _need <= 0.05:
                        break
                    _take = min(_need, max(0.0, _tgt[_p] - _mg))
                    _tgt[_p] -= _take
                    _need -= _take
                if _need > 0.05:
                    return None
        except Exception:
            pass
        if _tgt.get(_main, 0.0) < _mg - 0.05:
            return None
        for p in _others:
            if _tgt.get(p, 0.0) < _mg - 0.05:
                return None
        return {p: round(max(0.0, v), 1) for p, v in _tgt.items()}
    except Exception:
        return None


def _base_target(ctrl, live, C, main, timeSta, G, arr=None, log=None, aw=None):
    """Adaptive plan library: live / arrival / SCATS / model plan.

    When CYCLE_PLANNER_PLAN_LIBRARY is on, each candidate is scored with the
    engine's future-pressure projector and the lowest-pressure plan wins. This
    is the Aimsun-adaptive-controller pattern: detector state -> plan review ->
    selected plan, with the fixed/arrival/SCATS plans as the library.
    """
    cands = {"live": dict(live)}
    if arr:
        try:
            _fl = _main_floor(ctrl, dict(live), main,
                             float(_cfg(G, "PLAN_MIN_GREEN_S", 7.0) or 7.0), G)
            _t = _target_from_arrivals(
                arr, C, main, float(_cfg(G, "PLAN_MIN_GREEN_S", 7.0) or 7.0),
                _fl)
            if _t:
                cands["arrival"] = _t
        except Exception:
            pass
    _st = _scats_target(ctrl, live, C, main, timeSta, G)
    if _st:
        cands["scats"] = dict(_st)
    _mt = _model_target(ctrl, live, C, main, G)
    if _mt:
        cands["model"] = _mt
    _nt = _nash_thru_target(ctrl, live, C, main, timeSta, G)
    if _nt:
        cands["nash_thru"] = _nt

    if bool(_cfg(G, "CYCLE_PLANNER_PLAN_LIBRARY", True)) and len(cands) > 1:
        best = None
        best_score = None
        scores = {}
        feats = {}
        _ac = None
        if bool(_cfg(G, "CYCLE_PLANNER_ADAPTIVE_WEIGHTS", False)) and aw:
            try:
                try:
                    import shared_tsp_engine.adaptive_controller as _ac
                except ImportError:
                    import adaptive_controller as _ac
            except Exception:
                _ac = None
        _qsum = 0.0
        _dsmax = 0.0
        _arrsum = 0.0
        _linkp = 0.0
        _inf = {}
        try:
            _sn = ctrl._approach_ds_snapshot(timeSta) or {}
            _inf = _sn.get("info") or {}
            for _pp, _pi in _inf.items():
                _qsum += max(0.0, float(_pi.get("occ_veh", 0.0) or 0.0))
                _dsmax = max(_dsmax, float(_pi.get("ds_flow", 0.0) or 0.0))
                _arrsum += max(0.0, float(_pi.get("q_vph", 0.0) or 0.0))
        except Exception:
            pass
        try:
            _linkp = max(0.0, min(1.0, float(
                ctrl._phase_downstream_block(int(main)))))
        except Exception:
            _linkp = 0.0
        for name, tgt in cands.items():
            pr = _pressure(ctrl, live, tgt, timeSta, G)
            if pr is None:
                continue
            _ms = float(tgt.get(main, 0.0)) / max(C, 1.0)
            feat = {
                "pressure": min(max(float(pr) / 1000.0, 0.0), 5.0),
                "main_share": max(0.0, min(1.0, _ms)),
                "side_share": max(0.0, min(1.0, 1.0 - _ms)),
                "switch": 0.0 if name == "live" else 1.0,
                "queue": min(_qsum / 100.0, 1.0),
                "ds_max": min(_dsmax / 2.0, 1.0),
                "arrival": min(_arrsum / 3000.0, 1.0),
                "link_pressure": _linkp,
                "service_gap": _service_gap(ctrl, C, tgt, _inf, G),
            }
            feats[name] = feat
            sc = (_ac.score(feat, aw) if _ac is not None else float(pr))
            scores[name] = round(float(sc), 2)
            if best_score is None or sc < best_score:
                best, best_score = name, sc
        # (2026-10-23) HYSTERESIS TOWARD THE COMMISSIONED PLAN. The commissioned
        # ("model") plan is seed-stable and already well tuned for progression;
        # the adaptive candidates win on average but occasionally make a slightly
        # wrong move that loses to NO_TSP on a given seed (the +2..+3% seeds).
        # Make the commissioned plan the DEFAULT: only deviate from it when a
        # candidate beats it by more than CYCLE_PLANNER_SWITCH_MARGIN (fractional
        # score improvement). Lower score = better, so require
        #   best_score <= model_score * (1 - margin).
        # margin=0 reproduces the old pure-argmin behaviour.
        try:
            _margin = float(_cfg(G, "CYCLE_PLANNER_SWITCH_MARGIN", 0.0) or 0.0)
            if (_margin > 0.0 and best is not None and best != "model"
                    and "model" in scores):
                _msc = float(scores["model"])
                _bsc = float(best_score)
                # Need a clear improvement over commissioned to justify deviating;
                # otherwise hold the commissioned plan (bounded downside).
                if not (_bsc <= _msc - abs(_msc) * _margin):
                    if log is not None:
                        log("[ADAPTIVE PLAN] inter=%s HOLD model: best=%s %.2f "
                            "vs model %.2f within margin %.0f%% -> commissioned"
                            % (getattr(ctrl, "id", "?"), best, _bsc, _msc,
                               100.0 * _margin), force=True)
                    best, best_score = "model", _msc
        except Exception:
            pass
        if best is not None:
            try:
                if log is not None:
                    log(
                        "[ADAPTIVE PLAN] inter=%s selected=%s score=%.2f "
                        "scores=%s" % (getattr(ctrl, "id", "?"), best,
                                       best_score, scores), force=True)
                    log(
                        "[ADAPTIVE STATE] inter=%s q=%.1f ds_max=%.2f "
                        "arr=%.0f link_pressure=%.2f main_share=%.2f "
                        "service_gap=%.3f weights=%s"
                        % (getattr(ctrl, "id", "?"), _qsum,
                                       _dsmax, _arrsum, _linkp,
                                       float(feats[best].get("main_share", 0.0)),
                                       float(feats[best].get("service_gap", 0.0)),
                                       {k: round(v, 3) for k, v in
                                        ((aw or {}) if isinstance(aw, dict)
                                         else {}).items()}), force=True)
            except Exception:
                pass
            try:
                ctrl._adaptive_features = dict(feats.get(best) or {})
                ctrl._adaptive_plan = best
            except Exception:
                pass
            return dict(cands[best])

    # No library/score: preserve the previous preference order.
    if arr:
        try:
            _fl = _main_floor(ctrl, dict(live), main,
                             float(_cfg(G, "PLAN_MIN_GREEN_S", 7.0) or 7.0), G)
            _t = _target_from_arrivals(
                arr, C, main, float(_cfg(G, "PLAN_MIN_GREEN_S", 7.0) or 7.0),
                _fl)
            if _t:
                return dict(_t)
        except Exception:
            pass
    if _st:
        return dict(_st)
    return dict(live)


def _main_floor(ctrl, base, main, mg, G=None):
    """Floor the MAIN-arterial green at a fraction of its COMMISSIONED value, not
    the arrival-derived base (2026-10-23 fix). The commissioned main green (e.g.
    68 s of a 120 s cycle) exists for PROGRESSION / the coordinated green wave --
    local arrival VOLUME alone does not justify it, so the plan-library's pressure
    scorer happily flattens it (68->33 observed, main delay +106%). Anchoring the
    floor to the commissioned green keeps the green wave intact. Keep-fraction from
    CYCLE_PLANNER_MAIN_KEEP_FRAC (default 0.90); also respects the DS bus floor and
    min-green. Falls back to the old 0.85*base when no commissioned plan is readable."""
    _mg = float(mg)
    _keep = 0.90
    try:
        if G is not None:
            _keep = float(_cfg(G, "CYCLE_PLANNER_MAIN_KEEP_FRAC", 0.90) or 0.90)
    except Exception:
        _keep = 0.90
    _comm_floor = 0.0
    try:
        _cg = (getattr(ctrl, "_init_cycle_greens", None) or (0, {}))[1]
        _cv = float(_cg.get(int(main), 0.0) or 0.0)
        if _cv > 0.0:
            _comm_floor = _cv * _keep
    except Exception:
        _comm_floor = 0.0
    _bus = 0.0
    try:
        _bus = float(ctrl._ds_bus_floor_green())
    except Exception:
        _bus = 0.0
    if _comm_floor <= 0.0 and _bus <= 0.0:
        try:
            _comm_floor = float(base.get(main, _mg)) * 0.85
        except Exception:
            _comm_floor = _mg
    return max(_mg, _bus, _comm_floor)


def _target_from_gene(base, C, main, gene, delta, mg,
                      down_frac=None, floor=None):
    """One bit -> main share up/down, sides rescaled, cycle conserved.

    Gene 1 extends main by `delta`; gene 0 only trims by `down_frac` (default
    is capped at 5%), and never below the DS/model main floor.
    """
    try:
        if main not in base or C <= 1.0:
            return None
        base = {int(p): max(0.0, float(v)) for p, v in base.items()}
        others = [p for p in base if p != main]
        if not others:
            return None
        side_sum = sum(base[p] for p in others)
        if side_sum <= 0.0:
            return None
        _g = 1 if int(gene) else 0
        _down = float(delta if down_frac is None
                      else min(float(delta), float(down_frac)))
        _mult = (1.0 + float(delta)) if _g else (1.0 - _down)
        main_new = base[main] * _mult
        _floor = float(floor if floor is not None
                       else max(float(mg), base[main] * 0.85))
        main_new = max(float(mg), float(_floor),
                       min(C - float(mg) * len(others), main_new))
        rem = C - main_new
        tgt = {main: main_new}
        for p in others:
            tgt[p] = rem * base[p] / side_sum
        # Enforce side min-greens; borrow from main only down to its floor.
        for p in others:
            if tgt[p] < mg:
                need = mg - tgt[p]
                tgt[p] = mg
                main_new -= need
        if main_new < mg:
            return None
        tgt[main] = main_new
        _s = sum(tgt.values())
        if _s <= 0.0:
            return None
        # Exact cycle identity (rounding + borrow).
        _big = max(others, key=lambda p: tgt[p])
        tgt[_big] += C - _s
        if tgt[_big] < mg - 0.05:
            return None
        return {p: round(max(0.0, v), 1) for p, v in tgt.items()}
    except Exception:
        return None


def _pressure(ctrl, base, tgt, timeSta, G):
    try:
        _fn = G.get("_pbil_project_pressure")
        if _fn is None or not tgt:
            return None
        mult = {}
        for p, v in tgt.items():
            b = max(float(base.get(p, 0.0)), 0.1)
            mult[int(p)] = float(v) / b
        pr = _fn(ctrl, mult, timeSta)
        return None if pr is None else float(pr)
    except Exception:
        return None


def _apply_one(ctrl, tgt, C, main, timeSta, time, mg, G, log):
    try:
        jid = int(getattr(ctrl, "node_id", 0) or 0) or int(ctrl.id)
        ok, info = ctrl._apply_plan_durations_offset_preserving(
            jid, tgt, C, main, timeSta, time, mg, "cycle_plan")
        if not ok:
            # Keep it as the retry target; _reassert_plan owns the backoff.
            ctrl._plan_target_greens = dict(tgt)
            log("[CYCLE PLAN] inter=%s DEFER: %s" % (jid, info), force=True)
            return False, info
        return True, None
    except Exception as e:
        return False, repr(e)


def _unfloor_minors_to_commissioned(ctrl, tgt, main, mg):
    """CORRIDOR-SAFE MIN-GREEN (2026-10-27). A phase the COMMISSIONED plan runs
    BELOW the configured PLAN_MIN_GREEN_S must not be force-inflated UP to it: that
    steals green from the main the instant the plan is rewritten. KG's minors are 6s
    and mg=6, so nothing changes there; Logan's minors are 5s, so a blanket 6s floor
    stole ~1s x (n_minors) from the main (observed main +12-27%). Pull each such
    phase back to its commissioned green and return the freed seconds to the main,
    preserving the cycle sum. Equivalent to a per-phase floor of
    min(mg, commissioned[p]) without touching the many scalar-mg call sites."""
    try:
        _mg = float(mg)
        _cg = (getattr(ctrl, "_init_cycle_greens", None) or (0, {}))[1] or {}
        if not _cg or not tgt:
            return tgt
        _out = dict(tgt)
        _freed = 0.0
        for _p, _g in list(_out.items()):
            if int(_p) == int(main):
                continue
            _comm = float(_cg.get(int(_p), 0.0) or 0.0)
            if 0.0 < _comm < _mg and float(_g) > _comm + 0.05:
                _freed += float(_g) - _comm
                _out[int(_p)] = _comm
        if _freed > 0.05 and int(main) in _out:
            _out[int(main)] = float(_out[int(main)]) + _freed
        return _out
    except Exception:
        return tgt


def tick(time, timeSta, controllers, log, G):
    """Call from the engine's post-manage tick. No-op unless CYCLE_PLANNER."""
    try:
        if not bool(_cfg(G, "CYCLE_PLANNER", False)):
            return
        if not controllers:
            return
        now = float(time or 0.0)
        delay = int(_cfg(G, "CYCLE_PLANNER_DELAY_CYCLES", 1) or 0)
        mg = float(_cfg(G, "PLAN_MIN_GREEN_S", 7.0) or 7.0)
        # New replication in the same Aimsun process: clear the prior plan
        # queue and phase probabilities (time reset).
        if now + 1.0 < float(_ST.get("last_t", -1e9)):
            _ST.update({"last_t": -1e9, "apply_t": None, "pending": [],
                        "p": {}, "gene": {}, "generation": 0,
                        "arr": {}, "arr_src": {}, "arr_last_t": {},
                        "aw": None, "aw_prev": {}})

        # Load adaptive weights BEFORE applying the pending plan: the apply
        # step scores/updates the previous plan, so _ac must already exist.
        _ac = None
        _aw = _ST.get("aw")
        if bool(_cfg(G, "CYCLE_PLANNER_ADAPTIVE_WEIGHTS", False)):
            try:
                try:
                    import shared_tsp_engine.adaptive_controller as _ac
                except ImportError:
                    import adaptive_controller as _ac
                if _aw is None:
                    _path = (_cfg(G, "ADAPTIVE_WEIGHTS_PATH", "")
                             or _ac.default_path())
                    _aw = _ac.load(_path)
                    _ST["aw"] = _aw
                    log("[ADAPTIVE WEIGHTS] loaded %s %s"
                        % (_path, {k: round(v, 3) for k, v in _aw.items()}),
                        force=True)
            except Exception as _awe:
                _ac = None
                log("[ADAPTIVE WEIGHTS] load error: %r" % (_awe,), force=True)

        # 1) Apply the plan that was solved one cycle ago.
        if _ST["pending"] and _ST["apply_t"] is not None \
                and now >= float(_ST["apply_t"]):
            _n_ok = 0
            for rec in _ST["pending"]:
                _jid = int(getattr(rec["ctrl"], "node_id", 0) or 0) \
                    or int(rec["ctrl"].id)
                _prev = _ST.get("aw_prev", {}).get(_jid)
                try:
                    _acc = float(getattr(rec["ctrl"], "_pbil_acc", 0.0) or 0.0)
                    rec["ctrl"]._pbil_acc = 0.0
                except Exception:
                    _acc = 0.0
                if _prev and _ST.get("aw") is not None and _ac is not None:
                    _rw = ((float(_prev.get("acc", 0.0)) - _acc)
                           / max(abs(float(_prev.get("acc", 0.0))), 1.0))
                    # NOTE: `x or default` coerces a legitimate 0.0 to the default
                    # (0.0 is falsy), which silently prevented FREEZING the weights
                    # (ADAPTIVE_WEIGHT_LR=0 became 0.05). Read with an explicit None
                    # check so 0.0 is honoured -> LR=0 and REG=0 truly freeze.
                    _lr_c = _cfg(G, "ADAPTIVE_WEIGHT_LR", 0.05)
                    _reg_c = _cfg(G, "ADAPTIVE_WEIGHT_REG", 0.02)
                    _lr = float(_lr_c if _lr_c is not None else 0.05)
                    _reg = float(_reg_c if _reg_c is not None else 0.02)
                    if _lr <= 0.0 and _reg <= 0.0:
                        # Fully frozen: skip the update AND the save, so a seeded
                        # weights file is not overwritten by a no-op write.
                        log("[ADAPTIVE WEIGHTS] inter=%s FROZEN (lr=reg=0) w=%s"
                            % (_jid, {k: round(v, 3)
                                      for k, v in _ST["aw"].items()}),
                            force=True)
                    else:
                        _ST["aw"] = _ac.update(
                            _ST["aw"], _prev.get("features") or {}, _rw,
                            _lr, _reg)
                        try:
                            _path = (_cfg(G, "ADAPTIVE_WEIGHTS_PATH", "")
                                     or _ac.default_path())
                            _ac.save(_path, _ST["aw"])
                        except Exception:
                            pass
                        log("[ADAPTIVE WEIGHTS] inter=%s reward=%+.3f w=%s"
                            % (_jid, _rw, {k: round(v, 3)
                                           for k, v in _ST["aw"].items()}),
                            force=True)
                _ST.setdefault("aw_prev", {})[_jid] = {
                    "features": rec.get("features") or {}, "acc": _acc}
                # Corridor-safe min-green: don't inflate a commissioned-sub-mg minor
                # (KG unaffected; Logan's 5s minors stop robbing the main).
                rec["tgt"] = _unfloor_minors_to_commissioned(
                    rec["ctrl"], rec["tgt"], rec["main"], mg)
                ok, _ = _apply_one(
                    rec["ctrl"], rec["tgt"], rec["C"], rec["main"],
                    timeSta, now, mg, G, log)
                _n_ok += 1 if ok else 0
            log("[CYCLE PLAN] t=%.0f APPLY %d/%d junctions (delay=%dc)"
                % (now, _n_ok, len(_ST["pending"]), delay), force=True)
            _ST["pending"] = []
            _ST["apply_t"] = None

        warm = float(_cfg(G, "CYCLE_PLANNER_WARM_S", 300.0) or 0.0)
        if now < warm:
            return
        interval = float(_cfg(G, "CYCLE_PLANNER_INTERVAL_S", 120.0) or 120.0)
        if interval <= 0.0:
            interval = 120.0
        if now - float(_ST["last_t"]) < interval:
            return

        # Adaptive plan weights: loaded once, learned from realized delay.
        _ac = None
        _aw = _ST.get("aw")
        if bool(_cfg(G, "CYCLE_PLANNER_ADAPTIVE_WEIGHTS", False)):
            try:
                try:
                    import shared_tsp_engine.adaptive_controller as _ac
                except ImportError:
                    import adaptive_controller as _ac
                if _aw is None:
                    _path = (_cfg(G, "ADAPTIVE_WEIGHTS_PATH", "")
                             or _ac.default_path())
                    _aw = _ac.load(_path)
                    _ST["aw"] = _aw
                    log("[ADAPTIVE WEIGHTS] loaded %s %s"
                        % (_path, {k: round(v, 3) for k, v in _aw.items()}),
                        force=True)
            except Exception as _awe:
                _ac = None
                log("[ADAPTIVE WEIGHTS] load error: %r" % (_awe,), force=True)

        # 2) Snapshot the whole system at this cycle boundary.
        rows = []
        for _iid, c in list(controllers.items()):
            live, C, main = _live_greens(c, timeSta, G)
            if live is None:
                continue
            arr = _arrival_rates(c, live, C, main, timeSta, now, G)
            base = _base_target(c, live, C, main, timeSta, G, arr=arr, log=log, aw=_aw)
            rows.append({"ctrl": c, "live": live, "base": base,
                         "C": C, "main": main, "arr": arr,
                         "features": getattr(c, "_adaptive_features", {}),
                         "floor": _main_floor(c, base, main, mg, G),
                         "jid": int(getattr(c, "node_id", 0) or 0)
                         or int(c.id)})
            log("[ARRIVAL EST] inter=%s t=%.0f src=%s arr=%s"
                % (int(getattr(c, "node_id", 0) or 0) or int(c.id),
                   now, _ST["arr_src"].get(
                       int(getattr(c, "node_id", 0) or 0) or int(c.id), {}),
                   {p: round(v, 0) for p, v in arr.items()}), force=True)
        if not rows:
            _ST["last_t"] = now
            return

        # 3) PBIL over a global gene vector (one bit per junction).
        use_pbil = bool(_cfg(G, "CYCLE_PLANNER_PBIL", True))
        delta = float(_cfg(G, "CYCLE_PLANNER_DELTA", 0.15) or 0.0)
        down = float(_cfg(G, "CYCLE_PLANNER_MAIN_DOWN_FRAC", 0.05) or 0.0)
        K = int(_cfg(G, "CYCLE_PLANNER_CANDIDATES", 8) or 8)
        best = {r["jid"]: int(_ST["gene"].get(r["jid"], 1)) for r in rows}
        best_tgt = {}
        for r in rows:
            best_tgt[r["jid"]] = _target_from_gene(
                r["base"], r["C"], r["main"], best[r["jid"]], delta, mg,
                down_frac=down, floor=r["floor"])
        _base_pr = None
        _best_pr = None
        if use_pbil and delta > 0.0:
            for r in rows:
                if _ST["p"].get(r["jid"]) is None:
                    _ST["p"][r["jid"]] = 0.5
            cands = [dict(best),
                     {j: 1 - int(g) for j, g in best.items()}]
            for _ in range(max(K - 2, 0)):
                cands.append({
                    r["jid"]: (1 if random.random()
                               < float(_ST["p"].get(r["jid"], 0.5)) else 0)
                    for r in rows})
            for ci, genes in enumerate(cands):
                tot = 0.0
                ok = True
                tgts = {}
                for r in rows:
                    t = _target_from_gene(
                        r["base"], r["C"], r["main"],
                        genes.get(r["jid"], 1), delta, mg,
                        down_frac=down, floor=r["floor"])
                    if not t:
                        ok = False
                        break
                    pr = _pressure(r["ctrl"], r["base"], t, timeSta, G)
                    if pr is None:
                        ok = False
                        break
                    tgts[r["jid"]] = t
                    tot += pr
                if not ok:
                    continue
                if ci == 0:
                    _base_pr = tot
                if _best_pr is None or tot < _best_pr:
                    _best_pr, best, best_tgt = tot, dict(genes), tgts
            if _best_pr is not None:
                alpha = float(_cfg(G, "CYCLE_PLANNER_PBIL_ALPHA", 0.2) or 0.2)
                minp = float(_cfg(G, "CYCLE_PLANNER_PBIL_MIN_P", 0.05) or 0.05)
                for r in rows:
                    j = r["jid"]
                    p = ((1.0 - alpha) * float(_ST["p"].get(j, 0.5))
                         + alpha * float(best.get(j, 1)))
                    _ST["p"][j] = max(minp, min(1.0 - minp, p))
                _ST["gene"] = dict(best)
                _ST["generation"] = int(_ST.get("generation", 0)) + 1
                gain = (100.0 * (_base_pr - _best_pr) / _base_pr
                        if _base_pr and _base_pr > 0 else 0.0)
                log("[CYCLE PBIL] t=%.0f gen=%d best=%.0f base=%.0f "
                    "gain=%.1f%% genes=%s"
                    % (now, _ST["generation"], _best_pr, _base_pr, gain,
                       "".join(str(best.get(r["jid"], 0)) for r in rows)),
                    force=True)

        # 4) Queue for one-cycle-delayed application.
        _ST["pending"] = [{
            "ctrl": r["ctrl"], "tgt": best_tgt.get(r["jid"]),
            "C": r["C"], "main": r["main"],
            "features": r.get("features") or {}} for r in rows
            if best_tgt.get(r["jid"])]
        _ST["apply_t"] = now + interval * max(delay, 0)
        _ST["last_t"] = now
        log("[CYCLE PLAN] t=%.0f SOLVED %d junctions, apply_t=%.0f "
            "(delay=%dc, pbil=%s, scats=%s)"
            % (now, len(_ST["pending"]), _ST["apply_t"], delay,
               use_pbil, bool(_cfg(G, "CYCLE_PLANNER_USE_SCATS", True))),
            force=True)

        # delay=0 still applies on the next tick (one observation step).
        if delay <= 0:
            _ST["apply_t"] = now
    except Exception as e:
        try:
            log("[CYCLE PLAN] error: %r" % (e,), force=True)
        except Exception:
            pass
