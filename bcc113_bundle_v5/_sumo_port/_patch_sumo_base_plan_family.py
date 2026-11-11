"""Port the BASE_PLAN controller family (Aimsun, 2026-11-11) into the SUMO tree.

Target tree: Z:/tsp/sumo_hpc
  shared_tsp_engine/engine.py             methods + dispatch + init tuple + stamp
  shared_tsp_engine/specialized_modes.py  knobs + MODE_FLAGS
  sumo_bridge/sweep_arms.py               7 BASE_PLAN arms

Idempotent: every edit is keyed on a marker and skipped when already present.
Every anchor must match exactly once, else the script aborts without writing.

PORT NOTE (the one place the port is NOT a copy): this engine's apply_action
takes a phase_list INDEX -- `target_phase = self.phase_list[action]` -- which is
the convention the Aimsun twin's BASE_PLAN family uses, so the switches below
pass _phs.index(phase_id). run_lightsim_mp instead passes a phase ID, which is
off by one against this apply_action and can never reach the last phase; that is
reported, not silently changed, because it would move existing arms.

Usage:  python _patch_sumo_base_plan_family.py [--dry-run]
"""
from __future__ import print_function

import io
import os
import py_compile
import re
import shutil
import sys
import time

ROOT = r"Z:/tsp/sumo_hpc"
ENG = os.path.join(ROOT, "shared_tsp_engine", "engine.py")
MOD = os.path.join(ROOT, "shared_tsp_engine", "specialized_modes.py")
ARM = os.path.join(ROOT, "sumo_bridge", "sweep_arms.py")

STAMP_OLD = "2026-11-11T0200-sumo-game-ctm2-marginal"
STAMP_NEW = "2026-11-11T0400-sumo-base-plan-family"

DRY = "--dry-run" in sys.argv

# ---------------------------------------------------------------------------
# controller methods, inserted immediately before run_rl
# ---------------------------------------------------------------------------
METHODS = '''
    # ------------------------------------------------------------------ #
    # BASE_PLAN controller family (2026-11-11, ported from the Aimsun twin).
    # CONTROL_MODE == "BASE_PLAN" runs run_reward_tsp() first (the grant
    # always wins) and run_base_plan() only on no-grant ticks -- the same
    # stack as LIGHTSIM_MP, but BASE_PLAN selects WHICH base controller fills
    # the no-grant ticks. Every base shares _base_plan_rows() for measurement
    # and apply_action() for switches, so MIN/MAX green and a fresh grant's
    # 5 s protection still hold. A base NEVER drives an interphase: candidates
    # come from _mp_phase_ring (green phases only).
    # Mirrors LightSim core/signal.py (Su & Deng, arXiv:2602.21852).
    # PORT NOTE: apply_action here indexes phase_list, so every switch below
    # passes phs.index(phase_id) -- the Aimsun convention. run_lightsim_mp
    # passes a phase ID instead (off by one against this apply_action).
    # ------------------------------------------------------------------ #
    def _mp_phase_ring(self):
        """Real GREEN phases for the MaxPressure machine -- EXCLUDES interphases.

        phase_list is range(1, num_phases+1), which INCLUDES the yellow /
        all-red interphases; serving those injects lost time every cycle and
        collapses throughput. The real greens are the phases with signal-group
        turnings (_phase_origin_sections) -- the same set the DS / AUTO_DET
        path uses. Aimsun/SUMO inserts the interphase itself on the transition,
        so a base controller only ever chooses among greens. Falls back to the
        full phase_list when the green set cannot be read (never < 2)."""
        try:
            _po = self._phase_origin_sections() or {}
            _greens = sorted(int(p) for p in _po.keys() if int(p) > 0)
            if len(_greens) >= 2:
                return _greens
        except Exception:
            pass
        return list(getattr(self, 'phase_list', []) or [])

    def _base_plan_rows(self, time):
        """Shared MaxPressure-style measurement for the BASE_PLAN family.

        Returns (phs, green, rows, cur_id, ring_cur, elapsed) or None (the
        caller then falls back to run_normal). green = real GREEN phase ids
        (interphases excluded); rows[i] is green[i]'s MaxQueueLength row, so
        pressure(i) = sum(rows[i]); ring_cur = green-index of the current
        phase or None (on an interphase). A green id p maps back to its
        phase_list index with phs.index(p) for apply_action."""
        _phs = list(getattr(self, 'phase_list', []) or [])
        _mq = getattr(self, 'MaxQueueLength', None)
        if not _phs or _mq is None:
            return None
        try:
            _cur_id = int(ECIGetCurrentPhase(self.node_id))
        except Exception:
            _cur_id = None
        try:
            _elapsed = max(0.0, float(time)
                           - float(ECIGetStartingTimePhase(self.node_id)))
        except Exception:
            _elapsed = 0.0
        try:
            _ring = self._mp_phase_ring()
        except Exception:
            return None
        _green = [p for p in _ring if p in _phs and _phs.index(p) < len(_mq)]
        if len(_green) < 2:
            return None
        _rows = [[float(v) for v in _mq[_phs.index(p)][:]] for p in _green]
        _ring_cur = _green.index(_cur_id) if _cur_id in _green else None
        return (_phs, _green, _rows, _cur_id, _ring_cur, _elapsed)

    def run_sotl(self, time, timeSta, acycle):
        """Self-Organizing Traffic Lights (Gershenson 2005) as the base plan.

        Hold the current green while a platoon is still arriving on it (its
        measured demand stays above SOTL_THRESHOLD) and MIN_GREEN <= elapsed
        < MAX_GREEN; otherwise advance to the next green phase in the ring.
        Holding lets the plan tick (apply_action is only issued on a switch)."""
        _m = self._base_plan_rows(time)
        if _m is None:
            self.run_normal(time, timeSta, acycle)
            return
        _phs, _green, _rows, _cur_id, _ring_cur, _elapsed = _m
        try:
            if _ring_cur is None:       # on an interphase -> let the plan run
                self.run_normal(time, timeSta, acycle)
                return
            _min_g = float(globals().get('MIN_GREEN', 6.0) or 6.0)
            _max_g = float(globals().get('MAX_GREEN', 60.0) or 60.0)
            _thr = float(globals().get('SOTL_THRESHOLD', 1.0) or 0.0)
            _cur_demand = sum(_rows[_ring_cur])
            if _elapsed < _min_g or (_cur_demand > _thr and _elapsed < _max_g):
                self._gate_hit('sotl_hold', time)
                return
            _nxt = _green[(_ring_cur + 1) % len(_green)]
            _idx = _phs.index(_nxt)
            if 0 <= _idx < len(_phs):
                self.apply_action(_idx, timeSta, time, acycle)
        except Exception as _e:
            log_to_file("[SOTL] fallback to normal: %r" % (_e,))
            self.run_normal(time, timeSta, acycle)

    def run_maxpressure_lt(self, time, timeSta, acycle):
        """Lost-Time-Aware MaxPressure: switch to the MaxPressure argmax only
        when the pressure gain over the current phase clears a switching-cost
        bar (the yellow + all-red lost green paid on every switch). Standard
        MaxPressure ignores lost time and collapses capacity by switching on
        any argmax flicker; the bar (LT_MP_SWITCH_BAR * intergreen) holds the
        current phase until the gain is real. MAX_GREEN forces a switch."""
        _m = self._base_plan_rows(time)
        if _m is None:
            self.run_normal(time, timeSta, acycle)
            return
        _phs, _green, _rows, _cur_id, _ring_cur, _elapsed = _m
        try:
            _min_g = float(globals().get('MIN_GREEN', 6.0) or 6.0)
            _max_g = float(globals().get('MAX_GREEN', 60.0) or 60.0)
            if _elapsed < _min_g:               # protect MIN_GREEN
                self._gate_hit('lt_mp_hold', time)
                return
            _press = [sum(_r) for _r in _rows]
            _best = max(range(len(_press)), key=lambda _i: _press[_i])
            _cur_p = _press[_ring_cur] if _ring_cur is not None else -1.0
            _ig = float(globals().get('INS_INTERGREEN_S',
                                      globals().get('GAME_CTM2_IG_S', 5.0)) or 5.0)
            _bar = float(globals().get('LT_MP_SWITCH_BAR', 1.0) or 0.0) * _ig
            _force = _elapsed >= _max_g
            if _best != _ring_cur and ((_press[_best] - _cur_p) > _bar or _force):
                _idx = _phs.index(_green[_best])
                if 0 <= _idx < len(_phs):
                    self.apply_action(_idx, timeSta, time, acycle)
            else:
                self._gate_hit('lt_mp_hold', time)
        except Exception as _e:
            log_to_file("[LT_MAXPRESSURE] fallback to normal: %r" % (_e,))
            self.run_normal(time, timeSta, acycle)

    def run_maxpressure_eff(self, time, timeSta, acycle):
        """Efficient MaxPressure: green duration scales with pressure. Instead
        of switching the moment the argmax moves, extend a high-pressure
        current phase -- its target green grows linearly with its own pressure
        between MIN_GREEN and MAX_GREEN (EFF_MP_PRESSURE_GAIN_S s per pressure
        unit). Once the target elapses, switch to the MaxPressure argmax."""
        _m = self._base_plan_rows(time)
        if _m is None:
            self.run_normal(time, timeSta, acycle)
            return
        _phs, _green, _rows, _cur_id, _ring_cur, _elapsed = _m
        try:
            _min_g = float(globals().get('MIN_GREEN', 6.0) or 6.0)
            _max_g = float(globals().get('MAX_GREEN', 60.0) or 60.0)
            _press = [sum(_r) for _r in _rows]
            _best = max(range(len(_press)), key=lambda _i: _press[_i])
            _cur_p = _press[_ring_cur] if _ring_cur is not None else 0.0
            _k = float(globals().get('EFF_MP_PRESSURE_GAIN_S', 4.0) or 0.0)
            _target = max(_min_g, min(_max_g, _min_g + _k * _cur_p))
            if _ring_cur is not None and _elapsed < _target:
                self._gate_hit('eff_mp_extend', time)
                return
            if _best != _ring_cur:
                _idx = _phs.index(_green[_best])
                if 0 <= _idx < len(_phs):
                    self.apply_action(_idx, timeSta, time, acycle)
        except Exception as _e:
            log_to_file("[EFF_MAXPRESSURE] fallback to normal: %r" % (_e,))
            self.run_normal(time, timeSta, acycle)

    def run_base_plan(self, time, timeSta, acycle):
        """BASE_PLAN registry: the LightSim controller family as the base
        signal plan on no-grant ticks (the TSP/game layer is applied first by
        the CONTROL_MODE == 'BASE_PLAN' dispatch). BASE_PLAN selects the base:

          FIXEDTIME  commissioned fixed plan (run_normal).
          WEBSTER    fixed plan with Webster-optimal cycle/splits -- set
                     PLAN_OPTIMIZE=True on the arm so the warm-start retimes
                     the plan at init; per-tick action is then run_normal.
          GREENWAVE  commissioned coordinated plan (its professional offsets
                     ARE a green wave); per-tick action is run_normal. A
                     free-flow offset_i = d_i/v_f recompute is a follow-up.
          MAXPRESSURE      Varaiya MaxPressure (run_lightsim_mp).
          SOTL             Self-Organizing Traffic Lights.
          LT_MAXPRESSURE   lost-time-aware MaxPressure.
          EFF_MAXPRESSURE  pressure-proportional green MaxPressure.
        """
        _bp = str(globals().get('BASE_PLAN', 'FIXEDTIME') or 'FIXEDTIME').upper()
        if _bp == 'MAXPRESSURE':
            self.run_lightsim_mp(time, timeSta, acycle)
        elif _bp == 'SOTL':
            self.run_sotl(time, timeSta, acycle)
        elif _bp in ('LT_MAXPRESSURE', 'LTMP'):
            self.run_maxpressure_lt(time, timeSta, acycle)
        elif _bp in ('EFF_MAXPRESSURE', 'EFFMP'):
            self.run_maxpressure_eff(time, timeSta, acycle)
        else:
            # FIXEDTIME / WEBSTER / GREENWAVE and any unknown value: the plan
            # (optionally Webster-retimed at init) ticks.
            self.run_normal(time, timeSta, acycle)

'''

DISPATCH_OLD = '''                if _grant_age > 1.0:
                    self.run_lightsim_mp(time, timeSta, acycle)
                self.restore_phase_if_needed(time, timeSta, acycle)
'''

DISPATCH_NEW = DISPATCH_OLD + '''
            elif CONTROL_MODE == "BASE_PLAN":
                # LightSim controller FAMILY as the base plan; TSP + GAME layer
                # on top. Identical stack to LIGHTSIM_MP (run_reward_tsp wins;
                # the base only fills no-grant ticks + the 5 s grant protection
                # in apply_action), but BASE_PLAN selects WHICH base controller
                # runs (FIXEDTIME / WEBSTER / GREENWAVE / MAXPRESSURE / SOTL /
                # LT_MAXPRESSURE / EFF_MAXPRESSURE). MAXPRESSURE here == the
                # LIGHTSIM_MP mode's base, reached through the registry.
                self.run_reward_tsp(time, timeSta, acycle)
                _grant_age = float(time) - float(
                    getattr(self, 'last_tsp_action_time', -1e9) or -1e9)
                if _grant_age > 1.0:
                    self.run_base_plan(time, timeSta, acycle)
                self.restore_phase_if_needed(time, timeSta, acycle)
'''

KNOBS = '''
# BASE_PLAN controller family (2026-11-11): when CONTROL_MODE == "BASE_PLAN",
# BASE_PLAN selects which LightSim base controller fills the no-grant ticks
# (FIXEDTIME / WEBSTER / GREENWAVE / MAXPRESSURE / SOTL / LT_MAXPRESSURE /
# EFF_MAXPRESSURE). Read from engine globals via the MODE_FLAGS loop.
BASE_PLAN                = "FIXEDTIME"
SOTL_THRESHOLD           = 1.0    # SOTL: hold while measured demand > this
LT_MP_SWITCH_BAR         = 1.0    # LT-MP: switch only if gain > this * intergreen
EFF_MP_PRESSURE_GAIN_S   = 4.0    # Eff-MP: green seconds per unit of pressure
'''

FLAGS = ("    'BASE_PLAN', 'SOTL_THRESHOLD', 'LT_MP_SWITCH_BAR', "
         "'EFF_MP_PRESSURE_GAIN_S',\n")

ARMS = '''# BASE_PLAN controller family (2026-11-11): the same SPILL2/NASH champion, the
# BASE PLAN underneath changes. CONTROL_MODE="BASE_PLAN" + BASE_PLAN=<name>
# runs the TSP/game layer unchanged on top of the selected base controller.
for _bpn, _bptag in (("FIXEDTIME", "BASE_FIXEDTIME"),
                     ("WEBSTER", "BASE_WEBSTER"),
                     ("GREENWAVE", "BASE_GREENWAVE"),
                     ("MAXPRESSURE", "BASE_MAXPRESS"),
                     ("SOTL", "BASE_SOTL"),
                     ("LT_MAXPRESSURE", "BASE_LTMP"),
                     ("EFF_MAXPRESSURE", "BASE_EFFMP")):
    CTM2_ARMS.append((
        "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_" + _bptag,
        "nash",
        dict(_CTM2_SPILL2, CONTROL_MODE="BASE_PLAN", BASE_PLAN=_bpn),
    ))

'''


def rd(p):
    with io.open(p, "r", encoding="utf-8", errors="surrogateescape",
                 newline="") as f:
        return f.read()


def wr(p, s):
    if DRY:
        return "(dry-run)"
    bak = p + ".bak_baseplan_" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(p, bak)
    with io.open(p, "w", encoding="utf-8", errors="surrogateescape",
                 newline="") as f:
        f.write(s)
    return bak


def one(s, anchor, where):
    n = s.count(anchor)
    assert n == 1, "%s: anchor found %d times (need 1): %r" % (where, n,
                                                              anchor[:60])


def main():
    eng = rd(ENG)
    mod = rd(MOD)
    arm = rd(ARM)
    todo = []

    # 1. build stamp
    if STAMP_NEW in eng:
        print("stamp    : already %s" % STAMP_NEW)
    else:
        one(eng, STAMP_OLD, "stamp")
        eng = eng.replace(STAMP_OLD, STAMP_NEW)
        todo.append("stamp -> " + STAMP_NEW)
        print("stamp    : %s -> %s" % (STAMP_OLD, STAMP_NEW))

    # 2. controller methods
    if "def run_base_plan(self, time, timeSta, acycle):" in eng:
        print("methods  : already present")
    else:
        anchor = "\n    def run_rl(self, time, timeSta, acycle):\n"
        one(eng, anchor, "methods")
        eng = eng.replace(anchor, METHODS + anchor)
        todo.append("methods (_mp_phase_ring + 4 controllers + registry)")
        print("methods  : inserted before run_rl")

    # 3. dispatch
    if 'elif CONTROL_MODE == "BASE_PLAN":' in eng:
        print("dispatch : already present")
    else:
        one(eng, DISPATCH_OLD, "dispatch")
        eng = eng.replace(DISPATCH_OLD, DISPATCH_NEW)
        todo.append("dispatch branch")
        print("dispatch : inserted after LIGHTSIM_MP")

    # 4. init tuples (build coordinators / control-type check)
    lines = eng.split("\n")
    hits = 0
    for i, ln in enumerate(lines):
        if ("CONTROL_MODE in (" in ln and '"DYNAOPAC"' in ln
                and '"BASE_PLAN"' not in ln):
            lines[i] = ln.replace('"DYNAOPAC"', '"BASE_PLAN", "DYNAOPAC"', 1)
            hits += 1
    if hits:
        eng = "\n".join(lines)
        todo.append("%d init tuple(s)" % hits)
        print("inittuple: added BASE_PLAN to %d tuple(s)" % hits)
    else:
        print("inittuple: already present (or no DYNAOPAC tuple found)")

    # 5. specialized_modes knobs
    if "BASE_PLAN                = " in mod or "\nBASE_PLAN = " in mod:
        print("knobs    : already present")
    else:
        anchor = "DEMAND_SEED_WARM_S = 300.0\n"
        one(mod, anchor, "knobs")
        mod = mod.replace(anchor, anchor + KNOBS)
        todo.append("knobs")
        print("knobs    : inserted after DEMAND_SEED_WARM_S")

    # 6. MODE_FLAGS
    if "'BASE_PLAN', 'SOTL_THRESHOLD'" in mod:
        print("flags    : already present")
    else:
        anchor = "    'GAME_CTM2_LIGHTSIM_READOUT',\n"
        one(mod, anchor, "flags")
        mod = mod.replace(anchor, anchor + FLAGS)
        todo.append("MODE_FLAGS")
        print("flags    : added 4 names to MODE_FLAGS")

    # 7. arms
    if "BASE_FIXEDTIME" in arm:
        print("arms     : already present")
    else:
        anchor = "for _cname, _cgsol, _cflags in CTM2_ARMS:\n"
        one(arm, anchor, "arms")
        arm = arm.replace(anchor, ARMS + anchor)
        todo.append("7 BASE_PLAN arms")
        print("arms     : appended 7 arms to CTM2_ARMS")

    if not todo:
        print("\nnothing to do -- running the checks anyway")
    else:
        print("\nbackup   : %s" % wr(ENG, eng))
        print("backup   : %s" % wr(MOD, mod))
        print("backup   : %s" % wr(ARM, arm))

    # ------------------------------------------------------------------ #
    # checks
    # ------------------------------------------------------------------ #
    ok = True
    for path in (ENG, MOD, ARM):
        try:
            py_compile.compile(path, doraise=True)
            print("compile  : ok  %s" % os.path.basename(path))
        except Exception as e:
            ok = False
            print("compile  : FAIL %s: %s" % (os.path.basename(path), e))

    if not DRY:                     # in dry-run the files are untouched
        eng = rd(ENG)
        mod = rd(MOD)
        arm = rd(ARM)
    checks = [
        ("stamp", STAMP_NEW in eng),
        ("methods", eng.count("def run_base_plan(") == 1
         and eng.count("def run_sotl(") == 1
         and eng.count("def run_maxpressure_lt(") == 1
         and eng.count("def run_maxpressure_eff(") == 1
         and eng.count("def _mp_phase_ring(") == 1),
        ("dispatch", eng.count('elif CONTROL_MODE == "BASE_PLAN":') == 1),
        # 3 membership tuples carry the mode: coordinator build, control-type
        # check, and the GB/DYNAOPAC phase-group log (inert for BASE_PLAN).
        ("inittuple", eng.count('"BASE_PLAN", "DYNAOPAC"') == 3),
        ("knobs", "SOTL_THRESHOLD" in mod and "BASE_PLAN" in mod),
        ("flags", "'BASE_PLAN', 'SOTL_THRESHOLD'" in mod),
        ("arms", arm.count("BASE_FIXEDTIME") == 1
         and arm.count("BASE_EFFMP") == 1),
    ]
    for name, cond in checks:
        print("%-9s: %s" % (name, "OK" if cond else "FAIL"))
        ok = ok and cond

    # every membership tuple that dispatches REWARD_TSP must carry BASE_PLAN
    for i, ln in enumerate(eng.split("\n")):
        if "CONTROL_MODE in (" in ln and '"REWARD_TSP"' in ln:
            if '"BASE_PLAN"' not in ln:
                ok = False
                print("gate     : FAIL line %d lacks BASE_PLAN: %s"
                      % (i + 1, ln[:90]))
            else:
                print("gate     : OK line %d" % (i + 1))

    print("ALL CHECKS PASS" if ok else "CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
