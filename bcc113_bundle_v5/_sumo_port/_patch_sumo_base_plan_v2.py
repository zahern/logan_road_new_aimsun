"""BASE_PLAN v2: make SOTL actually drive, and make the gate counters readable.

Three defects found in the 2026-11-11 seed-300 smoke:

  1. run_sotl handed the ring back to run_normal whenever _ring_cur was None.
     That is every tick when ECIGetCurrentPhase does not resolve against
     _phase_origin_sections (the SUMO port's AAPI phase map), so the arm was
     indistinguishable from the fixed plan: 151 switches / 42.1 s mean green
     vs the plan's 135 / 44.7 s. LTMP and EFFMP only *looked* alive because
     their comparisons against a None current phase always came out "switch".

  2. _gate_hit throttles [GATE SUMMARY] to one line per 600 s from its FIRST
     hit (which lands at t~1), so in a 600 s run nothing is ever printed and
     sotl_hold / lt_mp_hold / eff_mp_extend could not be read at all. Fixed by
     a single unconditional dump at AAPIFinish.

  3. run_reward_tsp was unconditional in the BASE_PLAN branch, so "base alone"
     was not expressible: every base arm carried the TSP + game layer. With
     BASE_PLAN_TSP=False the arm runs the base controller only, which is what
     separates "SOTL is good" from "the game layer is carrying SOTL".

Idempotent: re-running is a no-op. --dry-run reports without writing.
"""

import argparse
import re
import shutil
import sys
import time

ENGINE = r"Z:\tsp\sumo_hpc\shared_tsp_engine\engine.py"
MODES = r"Z:\tsp\sumo_hpc\shared_tsp_engine\specialized_modes.py"
SWEEP = r"Z:\tsp\sumo_hpc\sumo_bridge\sweep_arms.py"

STAMP = "2026-11-11T0500-sumo-base-plan-sotl-drive"


# ----------------------------------------------------------------------
# engine.py
# ----------------------------------------------------------------------

BP_BUMP = '''    def _bp_bump(self, key, n=1):
        """Count one BASE_PLAN decision. Dumped once, at AAPIFinish.

        Exists because _gate_hit's [GATE SUMMARY] is throttled to 600 s from
        its first hit, which never elapses in a 600 s run -- the family's
        activity had to be inferred from phase traces instead of read.
        """
        try:
            _d = getattr(self, '_bp_diag', None)
            if _d is None:
                _d = {}
                self._bp_diag = _d
            _d[str(key)] = int(_d.get(str(key), 0)) + int(n)
            if globals().get('CONTROL_MODE') == 'BASE_PLAN':
                _BP_REG[id(self)] = self
        except Exception:
            pass

    def _mp_phase_ring(self):'''

SOTL_OLD = """        _phs, _green, _rows, _cur_id, _ring_cur, _elapsed = _m
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
                self.apply_action(_idx, timeSta, time, acycle)"""

SOTL_NEW = """        _phs, _green, _rows, _cur_id, _ring_cur, _elapsed = _m
        try:
            # SOTL must DRIVE the ring -- never hand it back to the plan. A
            # None here is either a genuine interphase (return is correct) or
            # a phase-id map that does not resolve. The SUMO port hits the
            # second case: ECIGetCurrentPhase returns ids that are not in the
            # _phase_origin_sections green set, so the old early-return made
            # this whole base a no-op (151 switches == the fixed plan's 135).
            # Fall back to the ring position this controller last commanded so
            # the self-organising loop keeps running either way.
            if _ring_cur is None:
                self._bp_bump('sotl_unresolved')
                _pos_prev = getattr(self, '_bp_ring_pos', None)
                if _pos_prev is not None and 0 <= int(_pos_prev) < len(_green):
                    _ring_cur = int(_pos_prev)
                else:
                    try:
                        _ring_cur = _phs.index(_cur_id) % len(_green)
                    except Exception:
                        _ring_cur = 0
                if _elapsed < 0.5:      # our own switch: interphase starting
                    self._bp_bump('sotl_transition')
                    return
            _min_g = float(globals().get('MIN_GREEN', 6.0) or 6.0)
            _max_g = float(globals().get('MAX_GREEN', 60.0) or 60.0)
            _thr = float(globals().get('SOTL_THRESHOLD', 1.0) or 0.0)
            _cur_demand = sum(_rows[_ring_cur])
            if _cur_demand <= 0.0:
                # Measurement dead: rotate on the MAX_GREEN backstop instead
                # of shredding the plan at MIN_GREEN every cycle.
                self._bp_bump('sotl_nomeasure')
            if _elapsed < _min_g:
                self._bp_bump('sotl_mingreen')
                return
            if _cur_demand > _thr and _cur_demand > 0.0 and _elapsed < _max_g:
                self._bp_bump('sotl_hold')
                self._gate_hit('sotl_hold', time)
                return
            _nxt_pos = (_ring_cur + 1) % len(_green)
            _nxt = _green[_nxt_pos]
            _idx = _phs.index(_nxt)
            if 0 <= _idx < len(_phs):
                self._bp_ring_pos = _nxt_pos
                self._bp_bump('sotl_switch')
                self._gate_hit('sotl_switch', time)
                self.apply_action(_idx, timeSta, time, acycle)"""

DUMP_FN = '''# ----------------------------------------------------------------------
# BASE_PLAN diagnostics (2026-11-11). _gate_hit prints [GATE SUMMARY] only
# once 600 s have passed since its FIRST hit (t~1), so in a 600 s run the
# sotl_hold / lt_mp_hold / eff_mp_extend counters are never readable. Every
# controller that touches a base controller registers himself here and the
# whole table is dumped once, unconditionally, from AAPIFinish.
# ----------------------------------------------------------------------
_BP_REG = {}


def dump_base_plan_diag():
    """One [BASE_PLAN DIAG] table per run: which base ran, and what it did."""
    try:
        log_to_file("[BASE_PLAN DIAG] mode=%s base=%s ctrls=%d"
                    % (globals().get('CONTROL_MODE'),
                       globals().get('BASE_PLAN'), len(_BP_REG)))
        _tot = {}
        for _cid in sorted(_BP_REG):
            _c = _BP_REG[_cid]
            _all = {}
            for _src in (getattr(_c, '_gate_counts', None) or {},
                         getattr(_c, '_bp_diag', None) or {}):
                for _k, _v in _src.items():
                    _all[_k] = _all.get(_k, 0) + int(_v)
            for _k, _v in _all.items():
                _tot[_k] = _tot.get(_k, 0) + _v
            if _all:
                log_to_file("[BASE_PLAN DIAG] inter=%s %s"
                            % (getattr(_c, 'id', '?'),
                               " ".join("%s=%d" % (_k, _v) for _k, _v in
                                        sorted(_all.items(),
                                               key=lambda kv: -kv[1]))))
        log_to_file("[BASE_PLAN DIAG] total %s"
                    % " ".join("%s=%d" % (_k, _v) for _k, _v in
                               sorted(_tot.items(), key=lambda kv: -kv[1])))
        log_to_file("[BASE_PLAN DIAG] end")
    except Exception as _e:
        try:
            log_to_file("[BASE_PLAN DIAG] error %r" % (_e,), force=True)
        except Exception:
            pass


def AAPIFinish():'''

# Inserted at the top of the post-stats try block, before _vlt_finish(), so
# it runs after results are saved but cannot disturb the stats handler.
FINISH_OLD = "        _vlt_finish()"

FINISH_NEW = '''        try:
            dump_base_plan_diag()
        except Exception as _bde:
            log_to_file("[BASE_PLAN] diag dump error: %r" % (_bde,), force=True)
        _vlt_finish()'''

DISPATCH_OLD = """                # LIGHTSIM_MP mode's base, reached through the registry.
                self.run_reward_tsp(time, timeSta, acycle)"""

DISPATCH_NEW = """                # LIGHTSIM_MP mode's base, reached through the registry.
                # BASE_PLAN_TSP=False runs the base controller ALONE: no TSP
                # grants, no game layer. That is the arm that separates "this
                # base is good" from "the game layer is carrying this base".
                if bool(globals().get('BASE_PLAN_TSP', True)):
                    self.run_reward_tsp(time, timeSta, acycle)
                else:
                    self._bp_bump('base_plan_notsp')"""

GATE_OLD = """            _g[str(reason)] = int(_g.get(str(reason), 0)) + 1"""

GATE_NEW = """            _g[str(reason)] = int(_g.get(str(reason), 0)) + 1
            if globals().get('CONTROL_MODE') == 'BASE_PLAN':
                _BP_REG[id(self)] = self"""


def patch_engine(src):
    """Apply the engine.py edits; raise if any anchor is not exactly once."""
    edits = [
        ("_bp_bump method", "    def _mp_phase_ring(self):", BP_BUMP),
        ("run_sotl drive", SOTL_OLD, SOTL_NEW),
        ("dispatch BASE_PLAN_TSP", DISPATCH_OLD, DISPATCH_NEW),
        ("_gate_hit register", GATE_OLD, GATE_NEW),
        ("dump_base_plan_diag", "def AAPIFinish():", DUMP_FN),
    ]
    out = src
    for label, old, new in edits:
        n = out.count(old)
        if n != 1:
            raise SystemExit("[FAIL] anchor %r occurs %d times" % (label, n))
        out = out.replace(old, new)
    # AAPIFinish hook: insert the dump call right after the stats save.
    n = out.count(FINISH_OLD)
    if n != 1:
        raise SystemExit("[FAIL] AAPIFinish stats anchor occurs %d times" % n)
    out = out.replace(FINISH_OLD, FINISH_NEW)
    return out


def patch_modes(src):
    """Add BASE_PLAN_TSP to the knob block and to MODE_FLAGS."""
    if "BASE_PLAN_TSP" in src:
        return src
    lines = src.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^BASE_PLAN\s*=", line):
            indent = line[:len(line) - len(line.lstrip())]
            lines.insert(i + 1, indent + "BASE_PLAN_TSP=True")
            break
    else:
        raise SystemExit("[FAIL] no module-level BASE_PLAN= knob found")
    out = "\n".join(lines)
    old = "'BASE_PLAN', 'SOTL_THRESHOLD'"
    if out.count(old) != 1:
        raise SystemExit("[FAIL] MODE_FLAGS BASE_PLAN anchor not unique")
    out = out.replace(old, "'BASE_PLAN', 'BASE_PLAN_TSP', 'SOTL_THRESHOLD'")
    return out


ARMS_ANCHOR = '''        dict(_CTM2_SPILL2, CONTROL_MODE="BASE_PLAN", BASE_PLAN=_bpn),
    ))

for _cname, _cgsol, _cflags in CTM2_ARMS:'''

ARMS_NEW = '''        dict(_CTM2_SPILL2, CONTROL_MODE="BASE_PLAN", BASE_PLAN=_bpn),
    ))

# BASE_PLAN x TSP layer (2026-11-11): the same base controller with the TSP +
# game layer switched OFF. At seed 300 the switch rate could not tell SOTL from
# the fixed plan, and the objective is a ratio that falls when throughput falls
# -- so the only way to attribute a base's score is to run it WITH and WITHOUT
# the layer on top. Pairs with the _BASE_* arms above.
for _bpn, _bptag in (("FIXEDTIME", "BASE_FIXEDTIME_NOTSP"),
                     ("SOTL", "BASE_SOTL_NOTSP"),
                     ("MAXPRESSURE", "BASE_MAXPRESS_NOTSP")):
    CTM2_ARMS.append((
        "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_" + _bptag,
        "nash",
        dict(_CTM2_SPILL2, CONTROL_MODE="BASE_PLAN", BASE_PLAN=_bpn,
             BASE_PLAN_TSP=False),
    ))

for _cname, _cgsol, _cflags in CTM2_ARMS:'''


def patch_arms(src):
    """Add the no-TSP twins of the base arms."""
    n = src.count(ARMS_ANCHOR)
    if n != 1:
        raise SystemExit("[FAIL] arm anchor occurs %d times" % n)
    return src.replace(ARMS_ANCHOR, ARMS_NEW)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    changed = 0

    for path, fn, marker in ((ENGINE, patch_engine, "_bp_bump"),
                             (MODES, patch_modes, "BASE_PLAN_TSP=True"),
                             (SWEEP, patch_arms, "BASE_SOTL_NOTSP")):
        with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
            src = f.read()
        if marker in src:
            print("[SKIP] %s already patched" % path)
            continue
        out = fn(src)
        print("[OK] %s  +%d bytes" % (path, len(out) - len(src)))
        if not args.dry_run:
            bak = "%s.bak_bp2_%s" % (path, stamp)
            shutil.copy2(path, bak)
            with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
                f.write(out)
            print("[BAK] %s" % bak)
        changed += 1

    print("[STAMP] %s" % STAMP)
    print("[DONE] %s" % ("dry-run, nothing written" if args.dry_run
                         else "patched %d files" % changed))


if __name__ == "__main__":
    sys.exit(main())
