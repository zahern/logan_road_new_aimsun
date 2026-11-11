# -*- coding: utf-8 -*-
"""Port the CTM2 payoff stack from the Aimsun engine into the SUMO fork.

    python _sumo_port/port_ctm2.py            # apply (backs up first)
    python _sumo_port/port_ctm2.py --check    # report only, change nothing

What moves, and why each piece is needed by `_game_ctm2_payoffs`:

  shared_tsp_engine/ctm_twoclass.py   REPLACED by the Aimsun copy (the fork's is
                                      the pre-2026-11-05 cut: no out_cap_frac,
                                      no cross_mult, no _step capacity term).
  engine.py  _ctm2/_CTM2_AVAILABLE    the import block the fork never had.
  engine.py  _ctm_calib_sec           kg/ctm_calibration.json per-section CTM
                                      triangle (CTM_CALIB_PATH, opt-in).
  engine.py  _ctm_params              wrapper the geom reader calls.
  engine.py  _section_jam_frac        downstream storage occupancy -> the
                                      GAME_CTM2_SPILLBACK term. Fork has no
                                      _model_topo table; reads plant geometry.
  engine.py  _phase_origin_dests      {phase: to-sections}; without it
                                      _phase_downstream_block returns 0.0 and a
                                      _SPILL arm would be byte-identical to its
                                      non-spill twin.
  engine.py  _cbql_ctm_geom           ApproachGeom (length/speed/lanes/kj/qs).
  engine.py  _vlt_advance_vph         ADVANCE-loop arrival flow. Fork carries no
                                      vloop_layout module, so this measures the
                                      section's rolling-window crossings and
                                      returns None (caller's documented
                                      fallback) when unmeasurable.
  engine.py  _game_ctm2_payoffs       the payoff itself, verbatim.
  engine.py  _game_ctm2_na            [GAME_CTM2_NA] once per reason.
  specialized_modes.py                the ctm2 branch: the fork only LOGGED
                                      [GAME_CTM2_NA] and forced legacy payoffs;
                                      it now calls the payoffs and rebuilds cand /
                                      rows / Cand from (B, C, b) as Aimsun does.
"""
import io
import os
import shutil
import sys

FORK = 'Z:/tsp/sumo_hpc/shared_tsp_engine'
LOCAL = 'shared_tsp_engine'
STAMP = '2026-11-06T1500-sumo-ctm2-payoffs'
CHECK_ONLY = '--check' in sys.argv


def read(p):
    with io.open(p, encoding='utf-8', newline='') as fh:
        return fh.read()


def write(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='') as fh:
        fh.write(s)


def nl_of(src):
    return '\r\n' if '\r\n' in src else '\n'


def conv(block, nl):
    return block.replace('\n', nl) if nl != '\n' else block


# ── module-level block: _ctm2 import + calibration ───────────────────────────
CTM2_IMPORT_BLOCK = '''
# ── TWO-CLASS CTM PAYOFFS (game solvers, GAME_PAYOFF_MODEL='ctm2') ────────────
# Ported from the Aimsun engine 2026-11-06 so an arm named ..._CTM2 scores the
# SAME model on both platforms instead of silently falling back to legacy
# payoffs. ctm_twoclass is stdlib-only and kept byte-identical to the Aimsun
# copy; when it cannot be imported _CTM2_AVAILABLE is False and the callers
# keep the legacy payoffs (they log [GAME_CTM2_NA]).
import json

try:
    try:
        from . import ctm_twoclass as _ctm2
    except ImportError:
        import ctm_twoclass as _ctm2
    _CTM2_AVAILABLE = True
except Exception as _ctm2_err:   # pragma: no cover - surfaced on the banner
    _ctm2 = None
    _CTM2_AVAILABLE = False
    _CTM2_IMPORT_ERR = repr(_ctm2_err)

# VIRTUAL LOOP LAYER: Aimsun builds one in _vlt_build from vloop_layout. This
# build carries no vloop_layout module, so _vlt stays None and
# _vlt_advance_vph measures the section's rolling-window crossings instead
# (see its docstring). Kept optional so a future port can switch it on.
try:
    try:
        from . import vloop_layout as _vll
    except ImportError:
        import vloop_layout as _vll
except Exception:
    _vll = None

# Per-section CTM triangle from kg/ctm_calibration.json
# (calibrate_ctm_from_timeseries.py). OPT-IN: set CTM_CALIB_PATH to the JSON to
# enable; unset = the free-flow defaults. Loaded lazily once per session.
_CTM_CALIB_CACHE = None


def _ctm_calib_sec(sec):
    global _CTM_CALIB_CACHE
    try:
        if _CTM_CALIB_CACHE is None:
            _p = os.environ.get("CTM_CALIB_PATH", "").strip()
            if not _p:
                _CTM_CALIB_CACHE = {}
            if _p and os.path.isfile(_p):
                with open(_p, "r", encoding="utf-8") as _fh:
                    _CTM_CALIB_CACHE = json.load(_fh) or {}
                print("[CTM CALIB] loaded %s (%d sections)"
                      % (_p, len((_CTM_CALIB_CACHE.get("sections") or {}))))
            else:
                _CTM_CALIB_CACHE = {}
        return ((_CTM_CALIB_CACHE.get("sections") or {}).get(str(int(sec)))
                or {})
    except Exception:
        return {}
'''

# ── IntersectionController methods ──────────────────────────────────────────
METHODS_BLOCK = '''
    def _ctm_params(self, sec):
        """Per-section CTM triangle (kg/ctm_calibration.json); {} = defaults."""
        try:
            return _ctm_calib_sec(sec) or {}
        except Exception:
            return {}

    def _section_jam_frac(self, sec):
        """Fraction of a section's STORAGE currently occupied (0..1+): vehicles
        present / jam capacity (length_m * lanes / JAM_VEH_SPACING_M). >~0.8 means
        the link is nearly full -- serving a movement INTO it causes spillback.
        0.0 when the length/count cannot be read (fail-open: no false gating).

        Ported from the Aimsun engine for the CTM2 spillback term. The Aimsun
        original prefers _model_topo()['len']; this build has no such table, so
        the plant geometry (AKIInfNetGetSectionANGInf) is the only source.
        """
        try:
            _n = int(AKIVehStateGetNbVehiclesSection(int(sec), False) or 0)
        except Exception:
            return 0.0
        if _n <= 0:
            return 0.0
        _len = None
        try:
            _si = AKIInfNetGetSectionANGInf(int(sec))
            if getattr(_si, 'report', -1) >= 0:
                _len = float(getattr(_si, 'length', 0.0) or 0.0)
        except Exception:
            _len = None
        if not _len or _len <= 1.0:
            return 0.0
        try:
            _lanes = max(int(self._sec_lane_count(int(sec)) or 1), 1)
        except Exception:
            _lanes = 1
        _sp = float(globals().get('JAM_VEH_SPACING_M', 7.0) or 7.0)
        _cap = max((float(_len) * _lanes) / max(_sp, 1.0), 1.0)
        return float(_n) / _cap

    def _phase_origin_dests(self):
        """{phase: set(downstream/to section)} from the LIVE signal plan, cached.

        The companion of _phase_origin_sections: same phase -> signal group ->
        turning walk, but keeping the turning's TO-section. _phase_downstream_block
        needs it to price green spent into a jammed receiving link (the CTM2
        GAME_CTM2_SPILLBACK term); {} when the plan cannot be read.
        """
        _c = getattr(self, '_phase_dest_cache', None)
        if _c is not None:
            return _c
        _out = {}
        try:
            _jid = int(getattr(self, 'node_id', 0) or 0) or int(self.id)
            try:
                _n_ph = int(ECIGetNumberofPhases(_jid))
            except Exception:
                _n_ph = int(ECIGetNumberPhases(_jid))
            for _ph in range(1, max(_n_ph, 0) + 1):
                _sgs = set()
                try:
                    _nsg = int(ECIGetNbSignalGroupsPhaseofJunction(_jid, _ph, 0.0))
                    for _pos in range(1, _nsg + 1):
                        try:
                            _sg = int(ECIGetSignalGroupPhaseofJunction(
                                _jid, _ph, _pos, 0.0))
                            if _sg > 0:
                                _sgs.add(_sg)
                        except Exception:
                            pass
                except Exception:
                    pass
                _tos = set()
                for _sg in _sgs:
                    try:
                        _nt = int(ECIGetNumberTurningsofSignalGroup(_jid, int(_sg)))
                        for _ti in range(max(_nt, 0)):
                            try:
                                _fp = intp(); _tp = intp()
                                ECIGetFromToofTurningofSignalGroup(
                                    _jid, int(_sg), _ti, _fp, _tp)
                                _t = int(_tp.value())
                                if _t > 0:
                                    _tos.add(_t)
                            except Exception:
                                continue
                    except Exception:
                        pass
                if _tos:
                    _out[_ph] = _tos
        except Exception:
            _out = {}
        if _out:
            self._phase_dest_cache = _out
        return _out

    def _cbql_ctm_geom(self, sec):
        """ApproachGeom for one section, cached: plant length / speed limit /
        lanes, the controller's JamDensity + SaturationFlow, the CELLQ wave
        speed, and kg/ctm_calibration.json overrides when loaded."""
        _c = getattr(self, '_cbql_ctm_geom_cache', None)
        if _c is None:
            _c = {}
            self._cbql_ctm_geom_cache = _c
        if int(sec) in _c:
            return _c[int(sec)]
        _len = 150.0
        _vf = float(globals().get('CELLQ_CTM_FREEFLOW_KMH', 50.0) or 50.0)
        try:
            _si = AKIInfNetGetSectionANGInf(int(sec))
            if getattr(_si, 'report', -1) >= 0 and float(_si.length) > 0:
                _len = float(_si.length)
            _slim = float(getattr(_si, 'speedLimit', 0.0) or 0.0)
            if _slim > 1.0:
                _vf = _slim
        except Exception as _swx:
            _note_swallow('_cbql_ctm_geom#3', _swx)
            pass
        try:
            _lanes = max(int(self._sec_lane_count(int(sec)) or 1), 1)
        except Exception as _swx:
            _note_swallow('_cbql_ctm_geom#2', _swx)
            _lanes = 1
        _w = float(globals().get('CELLQ_CTM_WAVE_KMH', 18.0) or 18.0)
        _kj = float(getattr(self, 'JamDensity', 200.0) or 200.0)
        _qs = float(getattr(self, 'SaturationFlow', 1800.0) or 1800.0)
        try:
            _cal = self._ctm_params(int(sec)) or {}
        except Exception as _swx:
            _note_swallow('_cbql_ctm_geom#1', _swx)
            _cal = {}
        _g = _ctm2.ApproachGeom(
            length_m=_len, lanes=_lanes,
            v_free_kmh=float(_cal.get('v_free_kmh', _vf) or _vf),
            w_back_kmh=float(_cal.get('w_back_kmh', _w) or _w),
            k_jam_vkm_lane=float(_cal.get('k_jam_vkm_lane', _kj) or _kj),
            q_sat_vph_lane=float(_cal.get('q_max_vph_lane', _qs) or _qs),
            dt_s=float(globals().get('CBQL_CTM_DT_S', 2.0) or 2.0),
            max_cells=int(globals().get('CBQL_CTM_MAX_CELLS', 12) or 12))
        _c[int(sec)] = _g
        return _g

    def _vlt_advance_vph(self, sec, window_s=300.0):
        """Arrival flow (veh/h, all lanes) measured at the ADVANCE loop of the
        approach whose stop line is `sec`. None when it cannot be measured --
        the caller then falls back to _measured_section_flow_vph.

        AIMSUN: reads the virtual-loop bank built by _vlt_build
        (vloop_layout.PointLoopBank.reading). THIS BUILD: no vloop_layout module
        and no _vlt table, so the ADVANCE measurement is the section's
        rolling-window crossing count from Aimsun's own partial statistics --
        the same physical signal a loop at the section entry reports.
        allow_seed=False: an unmeasured section returns None, never the OD
        demand prior (that is a warm-up value, not an arrival rate).
        """
        _v = getattr(self, '_vlt', None)
        if _v and _v.get('built') and globals().get('_vll') is not None:
            for _ap in _v['approaches']:
                if _ap['stop_sec'] == int(sec) and _ap.get('layout') is not None:
                    _adv = self._vlt_loops(_ap, 'ADVANCE')
                    if _adv and _adv[0].occ:
                        return _vll.PointLoopBank.reading(
                            _adv[0], _adv[0].occ[-1][0], window_s)['flow_vph']
            return None
        try:
            _now = float(AKIGetCurrentSimulationTime())
            _f = float(self._section_window_flow(
                int(sec), _now, float(window_s), allow_seed=False))
        except Exception:
            return None
        return _f if _f > 0.0 else None

    def _game_ctm2_payoffs(self, actions, time, timeSta=0.0):
        """Two-class CTM payoffs (B, C, b) pax.s for each (type, seconds) in
        `actions`, for the game solvers (GAME_PAYOFF_MODEL='ctm2'). Seeds every
        real phase's approach sections from the LIVE vehicles (buses counted
        separately), times each action against the plan (ctm_twoclass.
        action_timeline) and simulates GAME_CTM2_HORIZON_S. Returns None when
        the junction state cannot be read (interphase, no plan) -- the caller
        then keeps the legacy payoffs. Entries are None for untimed actions.
        """
        if not _CTM2_AVAILABLE:
            return None
        _jid = int(getattr(self, 'node_id', 0) or 0) or int(self.id)
        _po = self._phase_origin_sections() or {}
        _ring = sorted(int(p) for p in _po)
        if not _ring:
            self._game_ctm2_na('no signal-plan phases with approach sections')
            return None
        try:
            _cur = int(ECIGetCurrentPhase(_jid))
        except Exception as _swx:
            _note_swallow('_game_ctm2_payoffs#cur', _swx)
            self._game_ctm2_na('current phase unreadable')
            return None
        _greens = {}
        for _p in _ring:
            try:
                _greens[_p] = float(GetPhaseDuration(_jid, _p, timeSta) or 0.0)
            except Exception as _swx:
                _note_swallow('_game_ctm2_payoffs#dur', _swx)
                _greens[_p] = 0.0
        _lead = 0.0
        if _cur in _ring:
            try:
                _rem = max(0.0, float(ECIGetStartingTimePhase(_jid)) + _greens[_cur]
                           - float(time))
            except Exception as _swx:
                _note_swallow('_game_ctm2_payoffs#rem', _swx)
                self._game_ctm2_na('no phase start time')
                return None
        else:
            # Interphase, or a green with no modelled approach: every modelled
            # approach is red until the current phase ends, then the ring
            # resumes at the next modelled phase with its full green.
            try:
                _dur_c = float(GetPhaseDuration(_jid, _cur, timeSta) or 0.0)
                _lead = max(0.0, float(ECIGetStartingTimePhase(_jid)) + _dur_c
                            - float(time))
            except Exception as _swx:
                _note_swallow('_game_ctm2_payoffs#lead', _swx)
                self._game_ctm2_na('no start time for phase %s' % _cur)
                return None
            _after = [p for p in _ring if p > _cur]
            _cur = _after[0] if _after else _ring[0]
            _rem = _greens[_cur]
        _btp = int(getattr(self, 'bus_type_pos', -1) or -1)
        _sec_ph = {}
        for _p, _secs in _po.items():
            for _s in (_secs or []):
                _sec_ph.setdefault(int(_s), set()).add(int(_p))
        # CASCADE PRICING (GAME_CTM2_SPILLBACK): throttle each approach's stop-
        # line discharge by its DOWNSTREAM receiving link's free space, so the
        # game cannot bank the benefit of pushing a platoon into a jammed
        # arterial link -- it imports the downstream (arterial) queue into the
        # single-junction payoff through the CTM supply boundary. out_cap_frac =
        # max(0, 1 - gamma*downstream_block); 1.0 (off) keeps the free-sink CTM.
        _spill = bool(globals().get('GAME_CTM2_SPILLBACK', False))
        _spill_g = float(globals().get('GAME_CTM2_SPILLBACK_GAMMA', 1.0) or 1.0)
        _blk = {}
        if _spill:
            for _p in _ring:
                try:
                    _blk[int(_p)] = max(0.0, float(self._phase_downstream_block(int(_p)) or 0.0))
                except Exception:
                    _blk[int(_p)] = 0.0
        _snap = {}
        for _s, _phs in _sec_ph.items():
            _g = self._cbql_ctm_geom(_s)
            _veh = []
            try:
                for _vi in range(max(int(AKIVehStateGetNbVehiclesSection(_s, True)), 0)):
                    _inf = AKIVehStateGetVehicleInfSection(_s, _vi)
                    _veh.append((_g.length_m - float(getattr(_inf, 'CurrentPos', 0.0) or 0.0),
                                 _btp > 0 and int(getattr(_inf, 'type', -1)) == _btp))
            except Exception as _swx:
                _note_swallow('_game_ctm2_payoffs#veh', _swx)
            _arr = None
            try:
                _arr = self._vlt_advance_vph(_s)
            except Exception as _swx:
                _note_swallow('_game_ctm2_payoffs#adv', _swx)
            if _arr is None:
                try:
                    _arr = max(0.0, float(self._measured_section_flow_vph(_s) or 0.0))
                except Exception as _swx:
                    _note_swallow('_game_ctm2_payoffs#arr', _swx)
                    _arr = 0.0
            if _spill:
                _bk = max((_blk.get(int(_p), 0.0) for _p in _phs), default=0.0)
                _ocf = min(max(1.0 - _spill_g * _bk, 0.0), 1.0)
                _snap[_s] = (_g, _ctm2.seed_cells(_g, _veh), _arr,
                             tuple(sorted(_phs)), _ocf)
            else:
                _snap[_s] = (_g, _ctm2.seed_cells(_g, _veh), _arr, tuple(sorted(_phs)))
        _dt = float(globals().get('CBQL_CTM_DT_S', 2.0) or 2.0)
        if not _snap:
            self._game_ctm2_na('no modelled approach sections')
            return None
        return _ctm2.game_payoffs(
            _snap, _ring, _cur, _rem, _greens,
            int(getattr(self, 'BusPhase', -1) or -1), list(actions),
            intergreen=float(globals().get('GAME_CTM2_IG_S',
                                           globals().get('INS_INTERGREEN_S', 5.0)) or 5.0),
            horizon=float(globals().get('GAME_CTM2_HORIZON_S', 60.0) or 60.0),
            dt=_dt, bus_pce=float(globals().get('CBQL_CTM_BUS_PCE', 2.0) or 2.0),
            bus_occ=float(getattr(self, 'BusOcc', 40.0) or 40.0),
            car_occ=float(getattr(self, 'CarOcc', 1.5) or 1.5), lead=_lead,
            cross_mult=float(globals().get('GAME_CROSS_STARVE_MULT', 1.0) or 1.0))

    def _game_ctm2_na(self, reason):
        """[GAME_CTM2_NA] once per junction per reason: why the CTM payoffs
        were not available (the game then falls back to legacy payoffs)."""
        _seen = getattr(self, '_game_ctm2_na_seen', None)
        if _seen is None:
            _seen = set(); self._game_ctm2_na_seen = _seen
        if reason not in _seen:
            _seen.add(reason)
            log_to_file('[GAME_CTM2_NA] inter=%s %s -> legacy payoffs'
                        % (getattr(self, 'id', '?'), reason), force=True)
'''

# ── specialized_modes.py: the ctm2 branch (log-only -> real payoffs) ────────
SPM_OLD = """        _gc = []
        _pmodel = str(globals().get('GAME_PAYOFF_MODEL', 'legacy') or 'legacy').lower()
        if _pmodel == 'ctm2' and not hasattr(self, '_game_ctm2_payoffs'):
            # The two-class CTM payoffs need _cbql_ctm_geom / _vlt_advance_vph,
            # which this build does not carry. Say so rather than silently score
            # a different model than the Ainsun arm of the same name.
            try:
                _log_func(self, "[GAME_CTM2_NA] inter=%s GAME_PAYOFF_MODEL=ctm2 needs "
                                "_cbql_ctm_geom/_vlt_advance_vph (absent on this "
                                "build) -> legacy payoffs"
                          % getattr(self, 'id', '?'), force=True)
            except Exception:
                pass
        _pmodel = 'legacy'
        for _c in cand:
            _bt = _nash_phase_total_bps(self, _c[0], _c[1],
                                        (0.0 if _monitor else _c[4]))
            _gc.append(_tsp_games.Cand(str(_c[0]), float(_c[1]), float(_bt),
                                       float(_c[5]), 0.0 if _monitor else float(_c[4])))
"""

SPM_NEW = """        # CONGESTION BAND GATE (GAME_CONGESTION_GATE): act only when this junction
        # has a real queue to relieve AND is not OVER-saturated. The game helps on
        # congested-but-recoverable junctions but CASCADES when it reallocates or
        # inserts at an already-saturated junction, so HOLD both below MIN_QUEUE
        # (free -> acting breaks coordination for no gain) and at or above the
        # upper bound (gridlocked -> acting steals unrecoverable cross green).
        # Upper bound: the CELL-STATE jam fraction (veh count / storage, trusted)
        # when GAME_CONGESTION_MAX_JAM is set, else the DS estimator.
        if bool(globals().get('GAME_CONGESTION_GATE', False)):
            _cg_minq = float(globals().get('GAME_CONGESTION_MIN_QUEUE_VEH', 4.0) or 0.0)
            _cg_maxds = float(globals().get('GAME_CONGESTION_MAX_DS', 0.90) or 0.0)
            _cg_maxjam = float(globals().get('GAME_CONGESTION_MAX_JAM', 0.0) or 0.0)
            _cg_q = 0.0
            _cg_ds = 0.0
            _cg_jam = 0.0
            _cg_po = {}
            try:
                _cg_po = self._phase_origin_sections() or {}
                for _cg_secs in _cg_po.values():
                    try:
                        _cg_qq = self._measured_sections_queue_veh(list(_cg_secs or []))
                        if _cg_qq is not None:
                            _cg_q = max(_cg_q, float(_cg_qq))
                    except Exception:
                        pass
            except Exception:
                _cg_q = _cg_minq + 1.0            # fail-open: do not suppress on error
            if _cg_maxjam > 0.0:
                try:
                    for _cg_secs in _cg_po.values():
                        for _cg_s in (_cg_secs or []):
                            try:
                                _cg_jam = max(_cg_jam,
                                              float(self._section_jam_frac(int(_cg_s)) or 0.0))
                            except Exception:
                                pass
                except Exception:
                    _cg_jam = 0.0                 # fail-open
            else:
                try:
                    _cg_ds = float((self._approach_ds_snapshot(timeSta) or {}).get(
                        'ds_max', 0.0) or 0.0)
                except Exception:
                    _cg_ds = 0.0
            _cg_hold = None
            if _cg_q < _cg_minq:
                _cg_hold = 'uncongested q=%.1f<%.1f' % (_cg_q, _cg_minq)
            elif _cg_maxjam > 0.0 and _cg_jam >= _cg_maxjam:
                _cg_hold = 'oversaturated jam=%.2f>=%.2f' % (_cg_jam, _cg_maxjam)
            elif _cg_maxjam <= 0.0 and _cg_maxds > 0.0 and _cg_ds >= _cg_maxds:
                _cg_hold = 'oversaturated ds=%.2f>=%.2f' % (_cg_ds, _cg_maxds)
            if _cg_hold is not None:
                try:
                    _log_func(self, "[GAME_SOLVE] inter=%s t=%.0f HOLD(congestion) %s"
                              % (getattr(self, 'id', '?'), float(time), _cg_hold),
                              force=True)
                except Exception:
                    pass
                return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)
        _gc = []
        _pmodel = str(globals().get('GAME_PAYOFF_MODEL', 'legacy') or 'legacy').lower()
        _ctm2 = None
        if _pmodel == 'ctm2' and hasattr(self, '_game_ctm2_payoffs'):
            # Two-class CTM payoffs (engine._game_ctm2_payoffs). None means the
            # junction state could not be read; the engine logged the reason.
            try:
                _ctm2 = self._game_ctm2_payoffs([(c[0], c[1]) for c in cand],
                                                time, timeSta)
            except Exception as _ge:
                _log_func(self, "[GAME_SOLVE] inter=%s ctm2 payoffs error %r"
                          % (getattr(self, 'id', '?'), _ge))
                _ctm2 = None
        if _ctm2 is not None:
            # every term from the two-class CTM; untimed candidates dropped
            _keep = [i for i, v in enumerate(_ctm2) if v is not None]
            cand = [(cand[i][0], cand[i][1], cand[i][2], cand[i][3],
                     max(0.0, float(_ctm2[i][2])), float(_ctm2[i][1])) for i in _keep]
            # ROWS carry the CTM numbers too: the engine's Z4 gate, reward and
            # logs read these rows. Keeping the legacy bps/cpc there would veto
            # CTM-chosen actions on a different model.
            # Row bps = CTM phase benefit B, cpc = CTM cross cost C.
            rows = [r for r in rows if r[0] == 'NO_ACTION'] + [
                (@@ROWLBL@@, c[1], 0.0, c[2], c[3],
                 float(_ctm2[i][0]), float(_ctm2[i][1]), 0.0, 0.0)
                for c, i in zip(cand, _keep)]
            _gc = [_tsp_games.Cand(str(c[0]), float(c[1]), float(_ctm2[i][0]),
                                   float(_ctm2[i][1]), float(_ctm2[i][2]))
                   for c, i in zip(cand, _keep)]
            _pmodel = 'ctm2'
        else:
            _pmodel = 'legacy' if _pmodel != 'ctm2' else 'legacy_fallback'
            for _c in cand:
                _bt = _nash_phase_total_bps(self, _c[0], _c[1],
                                            (0.0 if _monitor else _c[4]))
                _gc.append(_tsp_games.Cand(str(_c[0]), float(_c[1]), float(_bt),
                                           float(_c[5]), 0.0 if _monitor else float(_c[4])))
"""

PROP_ANCHOR = "'GAME_PAYOFF_MODEL', 'GAME_CTM2_HORIZON_S', 'GAME_CTM2_IG_S',"
PROP_NEW = ("'GAME_PAYOFF_MODEL', 'GAME_CTM2_HORIZON_S', 'GAME_CTM2_IG_S',\r\n"
            "    'GAME_CTM2_SPILLBACK', 'GAME_CTM2_SPILLBACK_GAMMA',\r\n"
            "    'GAME_CROSS_STARVE_MULT', 'CBQL_CTM_DT_S', 'CBQL_CTM_MAX_CELLS',\r\n"
            "    'CBQL_CTM_BUS_PCE', 'JAM_VEH_SPACING_M',\r\n"
            "    'GAME_CONGESTION_GATE', 'GAME_CONGESTION_MIN_QUEUE_VEH',\r\n"
            "    'GAME_CONGESTION_MAX_DS', 'GAME_CONGESTION_MAX_JAM',\r\n"
            "    'GAME_BUS_IN_HORIZON', 'GAME_MIN_BUS_BENEFIT_PAXS',")

# The bus-in-horizon gate + the _ctm2_B wiring sit at the END of the _gsol
# branch (after the solve), where the fork returns on a None pick.
SPM_GATE_ANCHOR = """        if _bi is None:
            return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)
    else:
"""

SPM_GATE_NEW = """        if _bi is None:
            return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)
        # BUS-IN-HORIZON GATE (GAME_BUS_IN_HORIZON): the CTM2 bus payoff is 0
        # whenever the detected bus is not inside the approach-cell horizon at
        # decision time, so the game would act on CAR utility alone (not transit
        # priority) and cascade. When on, require the pick to ACTUALLY help the
        # bus (u_bus > GAME_MIN_BUS_BENEFIT_PAXS); else HOLD. This reads the
        # realised CTM bus benefit, not an ETA proxy.
        if (bool(globals().get('GAME_BUS_IN_HORIZON', False))
                and float(_gc[_bi].u_bus) <= float(globals().get(
                    'GAME_MIN_BUS_BENEFIT_PAXS', 0.0) or 0.0)):
            try:
                _log_func(self, "[GAME_SOLVE] inter=%s t=%.0f HOLD(bus_horizon) "
                          "pick=%s_%gs u_bus=%.0f u_car=%.0f (bus not served in "
                          "horizon)" % (getattr(self, 'id', '?'), float(time),
                          _gc[_bi].family, _gc[_bi].duration,
                          _gc[_bi].u_bus, _gc[_bi].u_car), force=True)
            except Exception:
                pass
            return ('NO_ACTION', 0.0, 0.0, 0.0, so_na, tp_na, rows)
        if _pmodel == 'ctm2':
            # the MIN-GAIN gate must read the SAME model as the game's payoffs
            _ctm2_B = float(_gc[_bi].B)
    else:
"""

AAPI_ANCHOR = ("try:\n    from AAPI import *\nexcept Exception:\n"
               "    pass  # not running inside Aimsun (e.g. static analysis / py_compile)\n")
METHOD_ANCHOR = "            return max((_sf(int(t)) for t in _tos), default=0.0)\n        except Exception:\n            return 0.0\n"


def main():
    rep = []

    # -- 0. preconditions --------------------------------------------------
    eng = read(FORK + '/engine.py')
    spm = read(FORK + '/specialized_modes.py')
    nl = nl_of(eng)
    nlen = '    action_label(c[0], c[1])'
    if 'def action_label' in spm or 'action_label =' in spm:
        row_label = 'action_label(c[0], c[1])'
    else:
        row_label = "('%s_%gs' % (c[0], c[1]))"
    if 'timeSta' not in spm:
        print('ABORT: specialized_modes has no timeSta in scope at the ctm2 branch')
        return 2
    new_methods = conv(METHODS_BLOCK, nl)
    new_import = conv(CTM2_IMPORT_BLOCK, nl)
    aapi = conv(AAPI_ANCHOR, nl)
    m_anchor = conv(METHOD_ANCHOR, nl)
    spm_old = conv(SPM_OLD, nl)
    spm_new = conv(SPM_NEW.replace('@@ROWLBL@@', row_label, 1), nl)

    problems = []
    if aapi not in eng:
        problems.append('engine.py: AAPI import anchor not found')
    if m_anchor not in eng:
        problems.append('engine.py: _phase_downstream_block anchor not found')
    eng_done = '_game_ctm2_payoffs' in eng      # re-run: engine part already in
    if eng_done:
        print('engine.py: CTM2 methods already present -> engine step skipped')
    spm_done = ('_game_ctm2_payoffs' in spm
                and '_ctm2_B = float(_gc[_bi].B)' in spm)   # re-run: in
    if spm_done:
        print('specialized_modes.py: ctm2 branch already applied -> SM step skipped')
    if not spm_done and spm_old not in spm:
        problems.append('specialized_modes.py: ctm2 branch anchor not found')
    if conv(PROP_ANCHOR, nl_of(spm)) not in spm:
        problems.append('specialized_modes.py: propagation-list anchor not found')
    if not spm_done and conv(SPM_GATE_ANCHOR, nl_of(spm)) not in spm:
        problems.append('specialized_modes.py: post-solve anchor not found')
    if problems:
        print('ABORT (nothing written):')
        for p in problems:
            print('  -', p)
        return 2

    print('targets: engine.py (%d lines, nl=%r), specialized_modes.py, ctm_twoclass.py'
          % (eng.count(nl), nl))
    print('row label in the CTM2 rows: %s' % row_label)

    if CHECK_ONLY:
        print('--check: anchors all resolve, nothing written')
        return 0

    # -- 1. ctm_twoclass.py: the fork's copy is the pre-spillback cut ---------
    src = LOCAL + '/ctm_twoclass.py'
    dst = FORK + '/ctm_twoclass.py'
    if read(src) != read(dst):
        shutil.copyfile(dst, dst + '.bak_20261106_ctm2port')
        write(dst, read(src))
        rep.append('ctm_twoclass.py: replaced with the Aimsun copy (backup %s)'
                   % os.path.basename(dst + '.bak_20261106_ctm2port'))
    else:
        rep.append('ctm_twoclass.py: already identical')

    # -- 2. engine.py: import block + calibration helper + methods -----------
    if not eng_done:
        if STAMP not in eng:
            eng = eng.replace(
                conv('ENGINE_BUILD = "2026-11-06T1200-sumo-game-ladder"', nl),
                conv('ENGINE_BUILD = "%s"' % STAMP, nl), 1)
        eng = eng.replace(aapi, aapi + new_import, 1)
        eng = eng.replace(m_anchor, m_anchor + new_methods, 1)
        shutil.copyfile(FORK + '/engine.py',
                        FORK + '/engine.py.bak_20261106_ctm2port')
        write(FORK + '/engine.py', eng)
        rep.append('engine.py: +_ctm2 import, +_ctm_calib_sec, +7 methods, BUILD=%s'
                   % STAMP)
    else:
        rep.append('engine.py: unchanged (already ported)')

    # -- 3. specialized_modes.py: real ctm2 branch + knobs ------------------
    spm = spm.replace(spm_old, spm_new, 1)
    spm = spm.replace(conv(SPM_GATE_ANCHOR, nl_of(spm)),
                      conv(SPM_GATE_NEW, nl_of(spm)), 1)
    spm = spm.replace(conv(PROP_ANCHOR, nl_of(spm)), conv(PROP_NEW, nl_of(spm)), 1)
    shutil.copyfile(FORK + '/specialized_modes.py',
                    FORK + '/specialized_modes.py.bak_20261106_ctm2port')
    write(FORK + '/specialized_modes.py', spm)
    rep.append('specialized_modes.py: ctm2 branch calls the payoffs, congestion + '
               'bus-in-horizon gates, _ctm2_B wired; 13 knobs propagated')

    # -- 4. compile gate ----------------------------------------------------
    ok = True
    for p in ('engine.py', 'specialized_modes.py', 'ctm_twoclass.py'):
        try:
            compile(read(FORK + '/' + p), p, 'exec')
            rep.append('compile ok: %s' % p)
        except SyntaxError as e:
            ok = False
            rep.append('COMPILE FAIL %s: %s line %s' % (p, e.msg, e.lineno))
    for r in rep:
        print('  ' + r)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
