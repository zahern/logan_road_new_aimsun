#!/usr/bin/env python3
"""patch_side_marginal.py -- port SIDE_COST_MARGINAL_COMPETITOR to the SUMO build.

Why: the Aimsun engine carries the marginal-competitor cross cost
(`_marginal_competitor_side_delay` + the `_worst` return in the CTM cross
cost) behind `SIDE_COST_MARGINAL_COMPETITOR`. The SUMO authority bundle at
Z:\\tsp\\sumo_hpc has neither, so the paired A/B could not be run on SUMO and
the two platforms would not be running the same reward.

Three edits, all idempotent, all compile-gated before anything is written:

  1. shared_tsp_engine/engine.py
       - new `_marginal_competitor_side_delay` method + the flag branch at the
         top of `_compute_side_delay_penalty` (per-PHASE granularity)
       - `_ctm_cross_cost_paxs`: track the worst section and return it instead
         of the sum when the flag is on (per-SECTION granularity)
       - ENGINE_BUILD bump
  2. shared_tsp_engine/specialized_modes.py
       - `SIDE_COST_MARGINAL_COMPETITOR = False` + MODE_FLAGS entry, so the
         value arrives from run_config and the stale-flag reset covers it
  3. sumo_bridge/sweep_arms.py
       - `_MARGINAL` twins of the two CHAMP_ADAPTIVE_DSW_GAME_SOL_*_CTM2_SPILL2
         arms, identical except for the flag (paired A/B)

    python _sumo_port/patch_side_marginal.py --dry-run
    python _sumo_port/patch_side_marginal.py
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import sys
import time

ROOT = r"Z:\tsp\sumo_hpc"
ENGINE = os.path.join(ROOT, "shared_tsp_engine", "engine.py")
SPM = os.path.join(ROOT, "shared_tsp_engine", "specialized_modes.py")
ARMS = os.path.join(ROOT, "sumo_bridge", "sweep_arms.py")

MARK = "SIDE_COST_MARGINAL_COMPETITOR"
OLD_BUILD = 'ENGINE_BUILD = "2026-11-10T2300-sumo-lightsim-mp-schedmatch"'
NEW_BUILD = 'ENGINE_BUILD = "2026-11-10T2900-sumo-side-cost-marginal"'

METHOD = '''    def _marginal_competitor_side_delay(self, extra_red, _suppress_log=False):
        """Side cost = the SINGLE highest-cost CONFLICTING PHASE, not the sum.

        Theory (SIDE_COST_MARGINAL_COMPETITOR): in a ring with >2 phases the
        main/bus hold does not pay every side movement at once -- you can only
        hand green to ONE phase next, so the opportunity cost of holding is the
        delay to the single worst competing phase (the MaxPressure argmax), and
        an early-red / fixed-cycle reallocation only displaces the one phase it
        cuts. Summing over all side phases (the aggregate path below) is the
        realized cost ONLY for a TRUE floating-cycle extension, where the whole
        downstream sequence genuinely shifts by extra_red. Every champion arm
        runs a coordinated FIXED-cycle base (ADAPTIVE_DSW), whose plan
        re-converges each cycle, so none of its actions is a true floating
        extension -- the marginal competitor is the right model there.

        Returns (delay_pax_s, veh_h) for the worst conflicting phase, or None
        when the phase->movement map is unavailable (caller falls back to the
        aggregate). Occupancy is applied ONCE here, matching the aggregate's
        own convention, so a caller that post-multiplies CarOcc is unaffected."""
        extra_red = max(safe_float(extra_red), 0.0)
        if extra_red <= 0.0:
            return 0.0, 0.0
        _bp = int(getattr(self, 'BusPhase', -1) or -1)
        _occ = max(safe_float(getattr(self, 'CarOcc', 1.6)), 1.0)
        try:
            _pm = self._phase_movement_map()
        except Exception as _swx:
            _note_swallow('_marginal_competitor#pm', _swx); _pm = None
        _per_phase = []            # (phase_id, delay_pax_s, veh)
        if _pm:
            for _ph, _e in (_pm or {}).items():
                if int(_ph) == _bp:
                    continue
                _secs = set(_f for (_f, _t) in _e.get("turns", []))
                _pveh = 0.0
                for _f in _secs:
                    try:
                        _n, _L, _why = self._zone_queue_count(_f)
                    except Exception:
                        _n = 0
                    if _n > 0:
                        _pveh += float(_n)
                if _pveh > 0.0:
                    _per_phase.append((int(_ph), _pveh * extra_red * _occ, _pveh))
        if not _per_phase:
            # No movement map: treat each side SECTION as its own competitor and
            # keep the worst (still a single-competitor, not a sum).
            _best_d, _best_v = 0.0, 0.0
            for _ss in (self._get_side_sections() or []):
                try:
                    _n, _L, _why = self._zone_queue_count(_ss)
                except Exception:
                    _n = 0
                if _n > 0:
                    _d = float(_n) * extra_red * _occ
                    if _d > _best_d:
                        _best_d, _best_v = _d, float(_n)
            if _best_d <= 0.0:
                return None        # nothing measurable -> let caller aggregate
            return _best_d, _best_v * extra_red / 3600.0
        _ph_sel, _d_sel, _v_sel = max(_per_phase, key=lambda _r: _r[1])
        if not _suppress_log:
            log_to_file(
                "[SIDE_MARGINAL] inter=%s extra_red=%.2f worst_phase=%s "
                "delay=%.1f pax-s (worst of %d competing phases; sum would be "
                "%.1f)" % (self.id, extra_red, _ph_sel, _d_sel, len(_per_phase),
                          sum(_r[1] for _r in _per_phase)))
        return _d_sel, _v_sel * extra_red / 3600.0

'''

SIDE_ANCHOR = (
    "    def _compute_side_delay_penalty(self, extra_red, _suppress_log=False):\n"
    "        extra_red = max(safe_float(extra_red), 0.0)\n"
    "        if extra_red <= 0.0:\n"
    "            return 0.0, 0.0\n"
)

SIDE_REPL = METHOD + SIDE_ANCHOR + (
    "        # MARGINAL-COMPETITOR side cost (SIDE_COST_MARGINAL_COMPETITOR, off by\n"
    "        # default): charge only the single worst conflicting phase instead of\n"
    "        # summing every side movement. Correct for the fixed-cycle coordinated\n"
    "        # plans all current arms run; see _marginal_competitor_side_delay. Falls\n"
    "        # through to the aggregate when the marginal cannot be measured.\n"
    "        if bool(globals().get('SIDE_COST_MARGINAL_COMPETITOR', False)):\n"
    "            try:\n"
    "                _mc = self._marginal_competitor_side_delay(\n"
    "                    extra_red, _suppress_log=_suppress_log)\n"
    "                if _mc is not None:\n"
    "                    return _mc\n"
    "            except Exception as _swx:\n"
    "                _note_swallow('_compute_side_delay_penalty#marginal', _swx)\n"
)

ACC_OLD = "                    _total += max(0.0, _sim(_extra_red_steps) - _sim(0)) * _car_occ\n"
ACC_NEW = ("                    _dsec = max(0.0, _sim(_extra_red_steps) - _sim(0)) * _car_occ\n"
           "                    _total += _dsec\n"
           "                    if _dsec > _worst:\n"
           "                        _worst = _dsec\n")

RET_OLD = ("            _nf = float(getattr(_spm, 'NETWORK_FACTOR', 1.0) or 1.0)\n"
           "            return max(0.0, _total * _nf)\n")
RET_NEW = ("            _nf = float(getattr(_spm, 'NETWORK_FACTOR', 1.0) or 1.0)\n"
           "            # MARGINAL-COMPETITOR (SIDE_COST_MARGINAL_COMPETITOR, off by\n"
           "            # default): the hold displaces ONE competing phase at a time,\n"
           "            # so charge the single worst approach, not the sum.\n"
           "            if bool(globals().get('SIDE_COST_MARGINAL_COMPETITOR', False)):\n"
           "                return max(0.0, _worst * _nf)\n"
           "            return max(0.0, _total * _nf)\n")

FLAG_DECL = "SIDE_COST_MARGINAL_COMPETITOR = False\n\n"
ARMS_BLOCK = '''

# -- SIDE-COST MARGINAL-COMPETITOR TWINS (2026-11-10) -------------------------
# Same CTM2/SPILL2 arms, with SIDE_COST_MARGINAL_COMPETITOR=True: the cross
# (competing-phase) cost is charged as the single worst phase instead of the
# sum over every side movement. Paired A/B: each twin differs from the arm it
# copies in this one flag. Default stays False, so every existing arm is
# unchanged.
for _smname, _smsol, _smov in (
        ("CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2", "nash", _CTM2_SPILL2),
        ("CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2", "utilitarian",
         _CTM2_SPILL2)):
    if any(a.get("name") == _smname + "_MARGINAL" for a in CHAMPION_ARMS):
        continue
    _smbase = next((a for a in CHAMPION_ARMS if a.get("name") == _smname), None)
    if _smbase is None:
        continue
    _smarm = {k: v for k, v in _smbase.items() if k != "reward_overrides"}
    _smarm["name"] = _smname + "_MARGINAL"
    _smarm["reward_overrides"] = dict(
        _smbase.get("reward_overrides") or {},
        SIDE_COST_MARGINAL_COMPETITOR=True)
    CHAMPION_ARMS.append(_smarm)
'''


def _read(p):
    return io.open(p, encoding="utf-8", errors="surrogateescape").read()


def _compile(txt, path):
    compile(txt, path, "exec")


def patch_engine(src):
    if MARK in src:
        return src, "already patched"
    if src.count(SIDE_ANCHOR) != 1:
        raise SystemExit("ANCHOR MISSING/AMBIGUOUS: _compute_side_delay_penalty "
                         "(%d hits)" % src.count(SIDE_ANCHOR))
    src = src.replace(SIDE_ANCHOR, SIDE_REPL, 1)

    st = src.index("    def _ctm_cross_cost_paxs(")
    en = src.index("\n    def ", st + 10)
    sect = src[st:en]
    for name, old, new in (("_total init", "            _total = 0.0\n",
                            "            _total = 0.0\n            _worst = 0.0\n"),
                           ("accumulate", ACC_OLD, ACC_NEW),
                           ("return", RET_OLD, RET_NEW)):
        if sect.count(old) != 1:
            raise SystemExit("ANCHOR MISSING/AMBIGUOUS in _ctm_cross_cost_paxs: "
                             "%s (%d hits)" % (name, sect.count(old)))
        sect = sect.replace(old, new, 1)
    src = src[:st] + sect + src[en:]

    if OLD_BUILD in src:
        src = src.replace(OLD_BUILD, NEW_BUILD, 1)
    elif NEW_BUILD not in src:
        raise SystemExit("ENGINE_BUILD anchor missing: expected %r" % OLD_BUILD)
    return src, "engine patched"


def patch_spm(src):
    if MARK in src:
        return src, "already patched"
    if src.count("\nMODE_FLAGS = [\n") != 1:
        raise SystemExit("MODE_FLAGS anchor missing/ambiguous")
    src = src.replace("\nMODE_FLAGS = [\n",
                      "\n" + FLAG_DECL + "MODE_FLAGS = [\n    'SIDE_COST_MARGINAL_COMPETITOR',\n", 1)
    return src, "spm patched"


def patch_arms(src):
    if MARK in src:
        return src, "already patched"
    if "_CTM2_SPILL2 = dict(" not in src:
        raise SystemExit("_CTM2_SPILL2 missing -- wrong build?")
    return src + ARMS_BLOCK, "twin arms appended"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    for p in (ENGINE, SPM, ARMS):
        if not os.path.isfile(p):
            print("MISSING %s -- is Z: mounted?" % p)
            return 2

    jobs = ((ENGINE, patch_engine), (SPM, patch_spm), (ARMS, patch_arms))
    plan = []
    for path, fn in jobs:
        old = _read(path)
        try:
            new, note = fn(old)
        except SystemExit as e:
            print("REFUSED %s: %s" % (os.path.basename(path), e))
            return 3
        if new != old:
            try:
                _compile(new, path)
            except SyntaxError as e:
                print("PATCH WOULD NOT COMPILE %s: %s" % (path, e))
                return 4
        plan.append((path, old, new, note))
        print("%-18s %-22s %d -> %d bytes"
              % (os.path.basename(path), note, len(old), len(new)))

    if all(old == new for (_p, old, new, _n) in plan):
        print("nothing to do")
        return 0
    if a.dry_run:
        print("dry run: nothing written")
        return 0

    stamp = time.strftime("%Y%m%d_%H%M%S")
    for path, old, new, note in plan:
        if old == new:
            continue
        bak = path + ".bak_sidemarg_" + stamp
        shutil.copy2(path, bak)
        io.open(path, "w", encoding="utf-8", errors="surrogateescape",
                newline="").write(new)
        print("written %s (backup %s)" % (path, bak))

    for path, _fn in jobs:
        _compile(_read(path), path)
    print("all three files compile after write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
