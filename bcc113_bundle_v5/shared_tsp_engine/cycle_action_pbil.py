"""Fixed-time plan + PBIL action chooser.

The base plan is NEVER re-timed. Once per action interval, each junction
chooses one small action from the enabled set:

    NONE
    GE   small green extension of the current phase
    ER   early red of a cleared non-main phase
    INS  insert/advance to the busiest phase

PBIL maintains a categorical probability vector per junction and reinforces
the action whose next-interval accumulated pax-delay was lower. Actions are
queued and applied one interval later (the operator's one-cycle delay).

Flags:
    CYCLE_ACTION_PBIL=True
    CYCLE_ACTION_ALLOW_GE=True
    CYCLE_ACTION_ALLOW_ER=False
    CYCLE_ACTION_ALLOW_INS=False
    CYCLE_ACTION_INTERVAL_S=120
    CYCLE_ACTION_WARM_S=300
    CYCLE_ACTION_GE_S=2.0
    CYCLE_ACTION_ALPHA=0.20
    CYCLE_ACTION_MIN_P=0.05

It is opt-in and intentionally independent of DS/PBIL split adaptation.
"""
import random

BUILD = "2026-10-22T2920-fixed-action-pbil"

_ST = {
    "last_t": -1e9,
    "apply_t": None,
    "pending": [],
    "p": {},
    "prev_action": {},
    "prev_acc": {},
    "restore": {},
    "generation": 0,
}


def _cfg(G, name, default):
    try:
        v = G.get(name, default)
        return default if v is None else v
    except Exception:
        return default


def _jid(ctrl):
    return int(getattr(ctrl, "node_id", 0) or 0) or int(ctrl.id)


def _phases(ctrl, G):
    try:
        p = [int(x) for x in (getattr(ctrl, "phase_list", None) or [])]
        if p:
            return p
        n = int(G["ECIGetNumberofPhases"](_jid(ctrl)))
        return list(range(1, n + 1))
    except Exception:
        return []


def _state(ctrl, time, timeSta, G):
    try:
        jid = _jid(ctrl)
        cur = int(G["ECIGetCurrentPhase"](jid))
        t0 = float(G["ECIGetStartingTimePhase"](jid))
        el = max(0.0, float(time) - t0)
        ph = _phases(ctrl, G)
        if cur not in ph:
            return None
        dur = float(G["GetPhaseDuration"](jid, cur, timeSta) or 0.0)
        main = int(getattr(ctrl, "MainPhase",
                           getattr(ctrl, "BusPhase", 0)) or 0)
        try:
            snap = ctrl._approach_ds_snapshot(timeSta) or {}
        except Exception:
            snap = {}
        info = snap.get("info") or {}
        return {"cur": cur, "el": el, "dur": dur, "ph": ph,
                "main": main, "info": info, "C": float(
                    snap.get("cycle_s", 0.0) or 0.0)}
    except Exception:
        return None


def _occ(ctrl, info, p):
    try:
        v = float((info.get(int(p)) or {}).get("occ_veh", 0.0) or 0.0)
    except Exception:
        v = 0.0
    try:
        secs = (ctrl._phase_origin_sections() or {}).get(int(p)) or []
        v = max(v, float(ctrl._sections_standing_veh(secs)))
    except Exception:
        pass
    return v


def _flow(info, p):
    try:
        return float((info.get(int(p)) or {}).get("q_vph", 0.0) or 0.0)
    except Exception:
        return 0.0


def _ring_next(st):
    try:
        i = st["ph"].index(st["cur"])
        return int(st["ph"][(i + 1) % len(st["ph"])])
    except Exception:
        return None


def _next_demand_phase(st, ctrl):
    cand = []
    for p in st["ph"]:
        if p == st["cur"] or p == st["main"]:
            continue
        try:
            if p in (ctrl._nonvehicle_phases() or set()):
                continue
        except Exception:
            pass
        cand.append((_occ(ctrl, st["info"], p), _flow(st["info"], p), p))
    if not cand:
        return None
    cand.sort(reverse=True)
    return int(cand[0][2])


def _allowed_actions(st, ctrl, G, flags):
    acts = ["NONE"]
    jid = _jid(ctrl)
    busy = (_occ(ctrl, st["info"], st["cur"]) >= 2.0
            or _flow(st["info"], st["cur"]) >= 250.0)
    cap = float(_cfg(G, "CYCLE_ACTION_GE_MAX_S", 120.0) or 20.0)
    if (flags["ge"] and busy and st["dur"] > 0.0
            and st["dur"] < cap):
        acts.append("GE")
    if flags["er"] and st["cur"] != st["main"] and st["el"] >= 7.0:
        low = (_occ(ctrl, st["info"], st["cur"]) <= 1.0
               and _flow(st["info"], st["cur"]) <= 150.0)
        if low and _next_demand_phase(st, ctrl) is not None:
            acts.append("ER")
    if flags["ins"] and st["cur"] != st["main"] and st["el"] >= 7.0:
        tgt = _ring_next(st)
        if (tgt is not None and tgt != st["main"]
                and _occ(ctrl, st["info"], tgt) >= 3.0):
            acts.append("INS")
    return acts


def _restore(ctrl, G, timeSta):
    rec = _ST["restore"].pop(_jid(ctrl), None)
    if not rec:
        return
    p, dur = rec
    try:
        G["ECIChangeTimingPhase"](_jid(ctrl), int(p), float(dur), timeSta)
    except Exception:
        pass


def _apply(ctrl, act, st, G, time, timeSta):
    jid = _jid(ctrl)
    try:
        if act == "GE":
            step = float(_cfg(G, "CYCLE_ACTION_GE_S", 2.0) or 0.0)
            _ST["restore"][jid] = (st["cur"], st["dur"])
            G["ECIChangeTimingPhase"](
                jid, st["cur"], st["dur"] + step, timeSta)
            return True
        if act == "ER":
            _ST["restore"][jid] = (st["cur"], st["dur"])
            G["ECIChangeTimingPhase"](jid, st["cur"], max(7.0, st["el"]),
                                      timeSta)
            return True
        if act == "INS":
            tgt = _ring_next(st)
            if tgt is None or tgt == st["main"]:
                return False
            cyc = st["C"] or float(_cfg(G, "CYCLE_ACTION_DEFAULT_CYCLE_S",
                                        120.0) or 120.0)
            G["ECIChangeDirectPhaseWithInterphaseTransition"](
                jid, int(tgt), timeSta, float(time), float(cyc))
            return True
        return True
    except Exception:
        return False


def _update_pbil(ctrl, G, log, time):
    jid = _jid(ctrl)
    acts = ["NONE", "GE", "ER", "INS"]
    p = _ST["p"].get(jid)
    if not p or len(p) != len(acts):
        p = [1.0 / len(acts)] * len(acts)
        _ST["p"][jid] = p
    try:
        acc = float(getattr(ctrl, "_pbil_acc", 0.0) or 0.0)
        ctrl._pbil_acc = 0.0
    except Exception:
        acc = 0.0
    prev = _ST["prev_action"].get(jid)
    prev_acc = _ST["prev_acc"].get(jid)
    if prev in acts and prev_acc is not None:
        improved = acc <= prev_acc
        alpha = float(_cfg(G, "CYCLE_ACTION_ALPHA", 0.20) or 0.20)
        minp = float(_cfg(G, "CYCLE_ACTION_MIN_P", 0.05) or 0.05)
        i = acts.index(prev)
        target = 1.0 if improved else 0.0
        p[i] = (1.0 - alpha) * p[i] + alpha * target
        for k in range(len(p)):
            if k != i:
                p[k] = (1.0 - alpha) * p[k] + alpha * (1.0 - target) / (
                    len(p) - 1)
        for k in range(len(p)):
            p[k] = max(minp, min(1.0 - minp, p[k]))
        _ST["p"][jid] = p
        log("[PBIL ACT] inter=%s t=%.0f action=%s acc=%.0f prev=%.0f "
            "improved=%s p=%s" % (jid, time, prev, acc, prev_acc,
                                   improved, [round(x, 2) for x in p]),
            force=True)
    _ST["prev_acc"][jid] = acc


def _policy_state(ctrl, st, G):
    try:
        info = st.get("info") or {}
        cur = int(st["cur"])
        main = int(st["main"])
        ph = list(st["ph"])
        try:
            nxt = int(ph[(ph.index(cur) + 1) % len(ph)])
        except Exception:
            nxt = cur
        def _ds(p):
            try:
                return float((info.get(p) or {}).get("ds_flow", 0.0) or 0.0)
            except Exception:
                return 0.0
        def _arr(p):
            try:
                return float((info.get(p) or {}).get("q_vph", 0.0) or 0.0)
            except Exception:
                return 0.0

        # Per-second global bus tracker (engine._BUS_TRACK): nearest bus to THIS
        # junction, so the Flow policy can act on lateness/ETA, not just queues.
        _bus = None
        try:
            try:
                import shared_tsp_engine.engine as _E
            except ImportError:
                import engine as _E
            _bt = getattr(_E, "_BUS_TRACK", {}) or {}
            _jid = int(getattr(ctrl, "id", -1) or -1)
            for _bst in _bt.values():
                if int(_bst.get("nearest_jct", -1) or -1) != _jid:
                    continue
                if (_bus is None
                        or float(_bst.get("dist_m", 1e9) or 1e9)
                        < float(_bus.get("dist_m", 1e9) or 1e9)):
                    _bus = _bst
        except Exception:
            _bus = None
        return {
            "phase": cur, "main_phase": main,
            "phase_is_main": 1 if cur == main else 0,
            "queue_cur": _occ(ctrl, info, cur),
            "queue_main": _occ(ctrl, info, main),
            "queue_next": _occ(ctrl, info, nxt),
            "ds_cur": _ds(cur), "ds_main": _ds(main), "ds_next": _ds(nxt),
            "arrivals_cur": _arr(cur), "arrivals_next": _arr(nxt),
            "elapsed_s": st.get("el", 0.0), "dur_s": st.get("dur", 0.0),
            "cycle_s": st.get("C", 0.0),
            "bus_present": 1 if _bus else 0,
            "bus_eta_s": (round(float(_bus.get("eta_s", 999.0) or 999.0), 1)
                          if _bus else 999.0),
            "bus_late_s": (round(float(_bus.get("late_s", 0.0) or 0.0), 1)
                           if _bus else 0.0),
            "bus_speed_kmh": (round(float(_bus.get("speed_kmh", 0.0) or 0.0), 1)
                              if _bus else 0.0),
        }
    except Exception:
        return {}

def tick(time, timeSta, controllers, log, G):
    try:
        if not bool(_cfg(G, "CYCLE_ACTION_PBIL", False)):
            return
        if not controllers:
            return
        now = float(time or 0.0)
        if bool(_cfg(G, "CYCLE_ACTION_POLICY", "")) and str(
                _cfg(G, "CYCLE_ACTION_POLICY", "")).lower() == "flow":
            if _ST.get("policy") is None:
                try:
                    try:
                        import shared_tsp_engine.flow_policy as _fp
                    except ImportError:
                        import flow_policy as _fp
                    _ST["policy"] = _fp.load(_fp.resolve_path(
                        _cfg(G, "FLOW_POLICY_PATH", "") or None))
                    if _ST["policy"] is None:
                        log("[FLOW POLICY] no policy file; falling back to PBIL",
                            force=True)
                    else:
                        log("[FLOW POLICY] loaded %s"
                            % _fp.resolve_path(
                                _cfg(G, "FLOW_POLICY_PATH", "") or None),
                            force=True)
                except Exception as _fpe:
                    _ST["policy"] = None
                    log("[FLOW POLICY] load failed: %r" % (_fpe,), force=True)
        else:
            _ST["policy"] = None
        if now + 1.0 < float(_ST.get("last_t", -1e9)):
            _ST.update({"last_t": -1e9, "apply_t": None, "pending": [],
                        "p": {}, "prev_action": {}, "prev_acc": {},
                        "restore": {}, "generation": 0})
        interval = float(_cfg(G, "CYCLE_ACTION_INTERVAL_S", 120.0) or 120.0)
        if interval <= 0.0:
            interval = 120.0

        # Apply the action chosen during the previous interval.
        if _ST["pending"] and _ST["apply_t"] is not None \
                and now >= float(_ST["apply_t"]):
            for rec in _ST["pending"]:
                _restore(rec["ctrl"], G, timeSta)
                if rec["act"] != "NONE":
                    st = _state(rec["ctrl"], now, timeSta, G)
                    if st is not None:
                        _apply(rec["ctrl"], rec["act"], st, G, now, timeSta)
                _ST["prev_action"][rec["jid"]] = rec["act"]
            log("[FIXED ACT] t=%.0f APPLY %d actions"
                % (now, len(_ST["pending"])), force=True)
            _ST["pending"] = []
            _ST["apply_t"] = None

        warm = float(_cfg(G, "CYCLE_ACTION_WARM_S", 300.0) or 0.0)
        if now < warm:
            return
        if now - float(_ST["last_t"]) < interval:
            return

        flags = {
            "ge": bool(_cfg(G, "CYCLE_ACTION_ALLOW_GE", True)),
            "er": bool(_cfg(G, "CYCLE_ACTION_ALLOW_ER", False)),
            "ins": bool(_cfg(G, "CYCLE_ACTION_ALLOW_INS", False)),
        }
        pending = []
        for _iid, c in list(controllers.items()):
            jid = _jid(c)
            _update_pbil(c, G, log, now)
            st = _state(c, now, timeSta, G)
            if st is None:
                continue
            acts = _allowed_actions(st, c, G, flags)
            pick = None
            _pol = _ST.get("policy")
            if _pol:
                try:
                    try:
                        import shared_tsp_engine.flow_policy as _fp
                    except ImportError:
                        import flow_policy as _fp
                    pick = _fp.choose(_policy_state(c, st, G), _pol)
                except Exception:
                    pick = None
                if pick not in acts:
                    pick = None
            if pick is None:
                p = _ST["p"].get(jid) or [0.25] * 4
                total = sum(p[k] for k in range(4) if
                            ["NONE", "GE", "ER", "INS"][k] in acts)
                if total <= 0.0:
                    continue
                r = random.random() * total
                pick = "NONE"
                acc = 0.0
                for k, a in enumerate(["NONE", "GE", "ER", "INS"]):
                    if a not in acts:
                        continue
                    acc += p[k]
                    if r <= acc:
                        pick = a
                        break
            pending.append({"ctrl": c, "jid": jid, "act": pick})
        _ST["pending"] = pending
        _ST["apply_t"] = now + interval * max(
            int(_cfg(G, "CYCLE_ACTION_DELAY_CYCLES", 1) or 0), 0)
        _ST["last_t"] = now
        _ST["generation"] = int(_ST.get("generation", 0)) + 1
        log("[FIXED ACT] t=%.0f CHOSE %d actions %s apply_t=%.0f"
            % (now, len(pending),
               ",".join("%s:%s" % (r["jid"], r["act"]) for r in pending),
               _ST["apply_t"]), force=True)
    except Exception as e:
        try:
            log("[FIXED ACT] error: %r" % (e,), force=True)
        except Exception:
            pass
