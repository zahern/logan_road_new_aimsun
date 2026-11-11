"""port_lightsim_mp_to_sumo.py -- run LIGHTSIM_MP on the SUMO fork.

Local Windows script; it only edits files on the Z: share (nothing is executed
on the Aqua login node). It does four things:

  1. copies kg_lightsim_base.py into Z:/tsp/sumo_hpc/shared_tsp_engine/
     (the pure MaxPressure rule, no SUMO or Aimsun imports)
  2. patches shared_tsp_engine/engine.py: ENGINE_BUILD stamp, a
     run_lightsim_mp() method, and the CONTROL_MODE dispatch branch
  3. patches sumo_bridge/sweep_arms.py: the _CTM2_SPILL2_LIGHTSIM_MP arms,
     each games {NASH, UTIL} x {bus prio ON, bus prio OFF}
  4. writes the PBS job that runs the 4 arms x 2 seeds

Every edit is anchored and asserted, so a re-run is a no-op.
"""
import io
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
SUMO = r"Z:\tsp\sumo_hpc"
ENG = os.path.join(SUMO, "shared_tsp_engine", "engine.py")
ARMS = os.path.join(SUMO, "sumo_bridge", "sweep_arms.py")
BASE_SRC = os.path.join(HERE, "kg_lightsim_base.py")
BASE_DST = os.path.join(SUMO, "shared_tsp_engine", "lightsim_base.py")
PBS = os.path.join(SUMO, "run_lightsim_mp_ab_kg.pbs")

BUILD_OLD = b'ENGINE_BUILD = "2026-11-09T1900-sumo-lightsim"'
BUILD_NEW = b'ENGINE_BUILD = "2026-11-10T2000-sumo-lightsim-mp"'

METHOD = b'''    def run_lightsim_mp(self, time, timeSta, acycle):
        """Base plan: LightSim-style MaxPressure over the stage queue rows.

        Ported 2026-11-10 (Aimsun engine.py parity). The TSP / GAME_SOLUTION
        layer runs first and owns the buses; this method only holds the fort
        on ticks where that layer issued NO grant, so the controller
        underneath the game is a real signal rule instead of the fixed plan.

        pressure(stage) = sum of MaxQueueLength on that stage's row
        serve argmax; MIN_GREEN / MAX_GREEN protection is inside the rule.

        MaxQueueLength is np.zeros((n_phases, n_cols)) -- one ROW per stage --
        so no detector-to-phase map is needed. Falls back to run_normal when
        the rule or the queue matrix is unavailable, never raises into update.
        """
        _mpf = globals().get('_lightsim_mp_rule')
        if _mpf is None:
            try:
                from shared_tsp_engine.lightsim_base import max_pressure_phase as _mpf
            except Exception:
                try:
                    from lightsim_base import max_pressure_phase as _mpf
                except Exception:
                    return self.run_normal(time, timeSta, acycle)
            globals()['_lightsim_mp_rule'] = _mpf
        _phs = list(getattr(self, 'phase_list', []) or [])
        if not _phs:
            return self.run_normal(time, timeSta, acycle)
        try:
            _mq = np.asarray(getattr(self, 'MaxQueueLength', None), dtype=float)
        except Exception:
            _mq = None
        if _mq is None or _mq.size == 0 or _mq.ndim != 2:
            return self.run_normal(time, timeSta, acycle)
        try:
            _cur = int(ECIGetCurrentPhase(self.node_id))
        except Exception:
            _cur = int(_phs[0])
        try:
            _el = max(0.0, float(time) - float(ECIGetStartingTimePhase(self.node_id)))
        except Exception:
            _el = 0.0
        _idx0 = _phs.index(_cur) if _cur in _phs else 0
        try:
            _pick0 = int(_mpf(_mq, _idx0, _el))
        except Exception:
            return self.run_normal(time, timeSta, acycle)
        if _pick0 < 0 or _pick0 >= len(_phs):
            return
        _pick = int(_phs[_pick0])
        try:
            if LOG_TSP_EVT and (_pick != _cur
                                or int(time) % 60 == 0):
                _P = [round(float(sum(_r)), 1) for _r in _mq]
                _vprint(f"[LIGHTSIM_MP] inter={self.id} t={time:.0f} "
                        f"cur={_cur} pick={_pick} P={_P}")
        except Exception:
            pass
        if _pick != _cur:
            try:
                self.apply_action(_pick, timeSta, time, acycle)
            except Exception:
                pass

'''

DISPATCH_OLD = b'''            elif CONTROL_MODE == "DRL_DENSITY":
                self.run_reward_tsp(time, timeSta, acycle)
'''

DISPATCH_NEW = b'''            elif CONTROL_MODE == "DRL_DENSITY":
                self.run_reward_tsp(time, timeSta, acycle)

            elif CONTROL_MODE == "LIGHTSIM_MP":
                # Game layer first: it owns the buses and the GAME_SOLUTION
                # arbitration. MaxPressure (run_lightsim_mp) only drives the
                # signal on ticks where that layer issued no grant in the last
                # second, so a TSP grant is never stomped by the base plan.
                self.run_reward_tsp(time, timeSta, acycle)
                _grant_age = float(time) - float(
                    getattr(self, 'last_tsp_action_time', -1e9) or -1e9)
                if _grant_age > 1.0:
                    self.run_lightsim_mp(time, timeSta, acycle)
                self.restore_phase_if_needed(time, timeSta, acycle)
'''

ARMS_OLD = b'for _cname, _cgsol, _cflags in CTM2_ARMS:'

ARMS_NEW = b'''# -- LIGHTSIM_MP (2026-11-10) ------------------------------------------------
# Same CTM2 / SPILL2 / LightSim BLOCK payoff as the twins above; the BASE PLAN
# is what changes: engine CONTROL_MODE="LIGHTSIM_MP" runs the ported LightSim
# MaxPressure rule underneath the TSP + GAME_SOLUTION layer.
#   *NOPRIO twins keep everything identical and set TSP_ACTIVE_INTERSECTIONS=[],
# which trips the engine's junction gate (engine.py:21743) so the bus-priority
# layer stands down. That is the "bus prio ON vs OFF" contrast on an otherwise
# identical controller, not a different arm.
_CTM2_SPILL2_LIGHTSIM_MP = dict(_CTM2_SPILL2_LIGHTSIM, CONTROL_MODE="LIGHTSIM_MP")
for _mpg, _mpgsol in (("NASH", "nash"), ("UTIL", "utilitarian")):
    for _mpp, _mpflags in (("", {}),
                           ("_NOPRIO", {"TSP_ACTIVE_INTERSECTIONS": []})):
        CTM2_ARMS.append((
            "CHAMP_ADAPTIVE_DSW_GAME_SOL_%s_CTM2_SPILL2_LIGHTSIM_MP%s"
            % (_mpg, _mpp),
            _mpgsol,
            dict(_CTM2_SPILL2_LIGHTSIM_MP, **_mpflags),
        ))

'''

PBS_TEXT = """#!/bin/bash
#PBS -N tsp_lsmp_ab
#PBS -P FPAXJW8067
#PBS -l select=1:ncpus=8:mem=48gb
#PBS -l walltime=12:00:00
#PBS -j oe
#PBS -m be

# LIGHTSIM_MP on the KG corridor: base plan = ported LightSim MaxPressure,
# game layer on top, bus priority ON vs OFF per game.
#   4 arms x 2 seeds = 8 replicas, --jobs 4 -> ~2 h.
BASE=${BASE:-/mnt/hpccs01/home/ahernz/tsp/sumo_hpc}
cd $BASE/sumo_bridge || exit 1
source ${VENV:-$BASE/venv}/bin/activate
export SUMO_HOME=${VENV:-$BASE/venv}/lib/python3.12/site-packages/sumo
export PATH=$SUMO_HOME/bin:$PATH
export PYTHONUTF8=1
export MPLBACKEND=Agg

ARMS=CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM_MP,\
CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM_MP_NOPRIO,\
CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2_LIGHTSIM_MP,\
CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2_LIGHTSIM_MP_NOPRIO

echo "== host $(hostname)  $(date) =="
python run_sweep_hpc.py \\
  --corridor kg --scenario kg_scenario \\
  --arms "$ARMS" \\
  --seeds 300,400 \\
  --end 4500 --jobs 4 \\
  --out sweep_lightsim_mp_ab_kg.csv
echo "== done $(date) -> sweep_lightsim_mp_ab_kg.csv =="
"""


def patch_bytes(path, pairs, backup_tag):
    with open(path, "rb") as fh:
        data = fh.read()
    bak = path + ".bak_" + backup_tag
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    changed = False
    for old, new in pairs:
        if new in data:
            print("  already applied: %r" % new[:48])
            continue
        n = data.count(old)
        assert n == 1, "%s: anchor %r count=%d" % (path, old[:60], n)
        data = data.replace(old, new)
        changed = True
    if changed:
        tmp = path + ".lsmp.tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    print("  %s %s" % ("patched" if changed else "unchanged", os.path.basename(path)))


print("1) base rule ->", BASE_DST)
shutil.copy2(BASE_SRC, BASE_DST)
print("   %d bytes" % os.path.getsize(BASE_DST))

print("2) engine.py")
patch_bytes(ENG, [
    (BUILD_OLD, BUILD_NEW),
    (b"    def run_rl(self, time, timeSta, acycle):",
     METHOD + b"    def run_rl(self, time, timeSta, acycle):"),
    (DISPATCH_OLD, DISPATCH_NEW),
], "lightsim_mp_20261110")

print("3) sweep_arms.py")
patch_bytes(ARMS, [(ARMS_OLD, ARMS_NEW + ARMS_OLD)], "lightsim_mp_20261110")

print("4) job file ->", PBS)
with io.open(PBS, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(PBS_TEXT)
print("   %d bytes (LF endings for PBS)" % os.path.getsize(PBS))

print("5) compile")
import py_compile
for f in (ENG, ARMS):
    py_compile.compile(f, doraise=True)
    print("   OK", os.path.basename(f))

print("6) arms registered")
sys.path.insert(0, os.path.join(SUMO, "sumo_bridge"))
sys.path.insert(0, SUMO)
import sweep_arms
mp = [a for a in sweep_arms.CHAMPION_ARMS if a["name"].endswith("LIGHTSIM_MP")
      or a["name"].endswith("LIGHTSIM_MP_NOPRIO")]
print("   found %d" % len(mp))
for a in mp:
    ro = a.get("reward_overrides") or {}
    print("   %-62s mode=%s sol=%s prio=%s"
          % (a["name"], ro.get("CONTROL_MODE"), ro.get("GAME_SOLUTION"),
             "OFF" if ro.get("TSP_ACTIVE_INTERSECTIONS") == [] else "ON"))
assert len(mp) == 4, "expected 4 MP arms, got %d" % len(mp)
print("DONE")
