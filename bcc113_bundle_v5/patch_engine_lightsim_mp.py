"""One-shot patch: wire the LightSim MaxPressure base plan into engine.py.

engine.py is 13 MB with legacy mojibake, so str_replace refuses it.  This
script edits it as BYTES (no decode/encode round-trip, so no mojibake is
introduced) and matches anchors tolerantly against CRLF or LF line endings.

Edits:
  1. optional import of kg_lightsim_base.max_pressure_phase
  2. ENGINE_BUILD stamp bump (the header demands this on every engine edit)
  3. IntersectionController.run_lightsim_mp()          (base plan)
  4. CONTROL_MODE == "LIGHTSIM_MP" dispatch branch     (TSP first, base second)
  5. mode guard lists at 33389 and 33899               (TSP-capable init paths)

The GROUP_BASED/DYNAOPAC guard at 33361 is deliberately NOT touched: it builds
a GroupBasedController this mode does not use.

Run:  python patch_engine_lightsim_mp.py [--check]
"""
from __future__ import annotations

import os
import re
import shutil
import sys

TARGET = os.path.join("shared_tsp_engine", "engine.py")
BACKUP = TARGET + ".pre_lightsim_mp.bak"


def _pattern(old: str) -> "re.Pattern[bytes]":
    return re.compile(b"\r?\n".join(re.escape(line.encode("utf-8"))
                                    for line in old.split("\n")))


def sub(data: bytes, old: str, new: str, expected: int = 1, label: str = ""):
    pat = _pattern(old)

    def repl(m):
        nl = b"\r\n" if b"\r\n" in m.group(0) else b"\n"
        body = new.replace("\n", nl.decode("ascii")).encode("utf-8")
        return body

    data, n = pat.subn(repl, data)
    if n != expected:
        raise SystemExit("FAIL %s: matched %d times, expected %d"
                         % (label or old.split("\n")[0][:60], n, expected))
    print("  ok  %-28s (%d)" % (label or "edit", n))
    return data


IMPORT_OLD = """import os
import sys
import glob
import json
import importlib.util as _importlib_util"""

IMPORT_NEW = """import os
import sys
import glob
import json
import importlib.util as _importlib_util

# MaxPressure base-plan rule (kg_lightsim_base.max_pressure_phase). OPTIONAL:
# Aimsun's embedded interpreter does not necessarily carry this project on
# sys.path, so a failed import must not break the simulation -- run_lightsim_mp
# falls back to the corridor's own plan when it is None.
try:
    _ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
    for _p in (os.path.dirname(_ENGINE_DIR), _ENGINE_DIR):
        if _p and _p not in sys.path:
            sys.path.insert(0, _p)
    from kg_lightsim_base import max_pressure_phase as _max_pressure_phase
except Exception:
    _max_pressure_phase = None"""

BUILD_OLD = 'ENGINE_BUILD = "2026-11-09T1215-bundlecheck"'
BUILD_NEW = 'ENGINE_BUILD = "2026-11-10T1200-lightsim-mp"'

METHOD_OLD = "    def run_rl(self, time, timeSta, acycle):"

METHOD_NEW = '''    def run_lightsim_mp(self, time, timeSta, acycle):
        """LightSim MaxPressure as the BASE plan, TSP/game layer on top.

        The CONTROL_MODE == "LIGHTSIM_MP" dispatch calls check_bus_priority
        (the GAME_SOLUTION / NASH / utilitarian layer) FIRST and only reaches
        this method when that layer declined to act on the tick, so every TSP
        grant still wins over the base plan.  Ported from
        lightsim/core/signal.py MaxPressureController: serve the stage with the
        largest approach queues, hold to MIN_GREEN and rotate at MAX_GREEN
        (apply_action enforces both).

        self.MaxQueueLength is (n_phases, n_cols) -- one ROW PER STAGE -- so a
        stage's pressure is its row sum and no detector->phase map is needed.
        Any failure falls back to run_normal rather than leaving the junction
        uncontrolled for the tick.
        """
        if _max_pressure_phase is None:
            self.run_normal(time, timeSta, acycle)
            return
        try:
            _phs = list(getattr(self, 'phase_list', []) or [])
            _mq = getattr(self, 'MaxQueueLength', None)
            if not _phs or _mq is None:
                self.run_normal(time, timeSta, acycle)
                return

            try:
                _cur_id = int(ECIGetCurrentPhase(self.node_id))
            except Exception:
                _cur_id = None
            _cur = _phs.index(_cur_id) if _cur_id in _phs else None

            try:
                _elapsed = max(0.0, float(time)
                               - float(ECIGetStartingTimePhase(self.node_id)))
            except Exception:
                _elapsed = 0.0

            _n_ph = min(len(_phs), len(_mq))
            _rows = [[float(v) for v in _mq[i][:]] for i in range(_n_ph)]
            _idx = int(_max_pressure_phase(_rows, current=_cur,
                                           elapsed_green=_elapsed))
            if 0 <= _idx < len(_phs):
                self.apply_action(_idx, timeSta, time, acycle)
            else:
                self.run_normal(time, timeSta, acycle)

            # Throttled trace: the first GUI run must be verifiable from the log.
            _n = int(getattr(self, '_lightsim_mp_logged', 0) or 0) + 1
            self._lightsim_mp_logged = _n
            if globals().get('LOG_TSP_EVT', False) and _n <= 20:
                _vprint("[LIGHTSIM_MP] inter=%s t=%.1f cur=%s pick=%s P=%s" % (
                    getattr(self, 'id', '?'), float(time), _cur, _idx,
                    [round(sum(_r), 1) for _r in _rows]))
        except Exception as _e:
            log_to_file("[LIGHTSIM_MP] fallback to normal: %r" % (_e,))
            self.run_normal(time, timeSta, acycle)

    def run_rl(self, time, timeSta, acycle):'''

DISPATCH_OLD = '''            elif CONTROL_MODE == "RL":
                tsp_active = self.check_bus_priority(time, timeSta, acycle)
                if not tsp_active:
                    self.run_rl(time, timeSta, acycle)
                self.restore_phase_if_needed(time, timeSta, acycle)'''

DISPATCH_NEW = DISPATCH_OLD + '''

            elif CONTROL_MODE == "LIGHTSIM_MP":
                # BASE PLAN = LightSim MaxPressure; TSP/game layer on top:
                # check_bus_priority runs FIRST so a grant always overrides the
                # base plan, which only fills ticks where the game layer stood
                # down.  This is the "LightSim controller + TSP flavour" stack.
                tsp_active = self.check_bus_priority(time, timeSta, acycle)
                if not tsp_active:
                    self.run_lightsim_mp(time, timeSta, acycle)
                self.restore_phase_if_needed(time, timeSta, acycle)'''

GUARD_MPC_OLD = ('CONTROL_MODE in ("GROUP_BASED", "GROUP_BASED_URTSP", '
                 '"GROUP_BASED_HARMONY", "HARMONY", "REWARD_TSP", "DRL_DENSITY", '
                 '"DYNAOPAC", "DYNAOPAC_HARMONY", "MILP_MPC")')
GUARD_MPC_NEW = GUARD_MPC_OLD.replace('"DRL_DENSITY", ',
                                      '"DRL_DENSITY", "LIGHTSIM_MP", ')

GUARD_OLD = ('CONTROL_MODE in ("GROUP_BASED", "GROUP_BASED_URTSP", '
             '"GROUP_BASED_HARMONY", "HARMONY", "REWARD_TSP", "DRL_DENSITY", '
             '"DYNAOPAC", "DYNAOPAC_HARMONY")')
GUARD_NEW = GUARD_OLD.replace('"DRL_DENSITY", ',
                              '"DRL_DENSITY", "LIGHTSIM_MP", ')


def main():
    if not os.path.exists(TARGET):
        raise SystemExit("missing %s (run from the project root)" % TARGET)
    with open(TARGET, "rb") as fh:
        data = fh.read()
    original = len(data)
    print("patching %s (%.1f MB)" % (TARGET, original / 1e6))

    data = sub(data, IMPORT_OLD, IMPORT_NEW, 1, "kg_lightsim_base import")
    data = sub(data, BUILD_OLD, BUILD_NEW, 1, "ENGINE_BUILD stamp")
    data = sub(data, METHOD_OLD, METHOD_NEW, 1, "run_lightsim_mp method")
    data = sub(data, DISPATCH_OLD, DISPATCH_NEW, 1, "LIGHTSIM_MP dispatch")
    data = sub(data, GUARD_MPC_OLD, GUARD_MPC_NEW, 1, "guard list (MILP_MPC)")
    data = sub(data, GUARD_OLD, GUARD_NEW, 1, "guard list (core)")

    if os.environ.get("PATCH_DRY_RUN"):
        print("dry run: nothing written")
        return 0

    if not os.path.exists(BACKUP):
        shutil.copy2(TARGET, BACKUP)
        print("backup -> %s" % BACKUP)
    with open(TARGET, "wb") as fh:
        fh.write(data)
    print("written: %.1f MB -> %.1f MB" % (original / 1e6, len(data) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
