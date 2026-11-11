"""SUMO hand-off: BASE_PLAN controller-family smoke / A-B.

Ported 2026-11-11 from the Aimsun twin (build 2026-11-11T0300-base-plan-
controller-family). Run on the PC, NOT the Aqua login node.

What is being tested
--------------------
CONTROL_MODE == "BASE_PLAN" runs the TSP/game layer first (run_reward_tsp wins
every grant) and the selected base controller only on no-grant ticks -- the same
stack as LIGHTSIM_MP. BASE_PLAN picks the base:

    FIXEDTIME       commissioned plan (run_normal)      == plain SPILL2 arm
    WEBSTER         run_normal + PLAN_OPTIMIZE warm start
    GREENWAVE       commissioned coordinated plan (run_normal)
    MAXPRESSURE     run_lightsim_mp (Varaiya MP)
    SOTL            hold green while demand > SOTL_THRESHOLD
    LT_MAXPRESSURE  MP argmax only if gain > LT_MP_SWITCH_BAR * intergreen
    EFF_MAXPRESSURE green target = MIN + EFF_MP_PRESSURE_GAIN_S * pressure

Pre-flight (read the run log)
-----------------------------
1) [LOAD] must say ENGINE_BUILD=2026-11-11T0400-sumo-base-plan-family.
   Anything older means the patched engine was not the one that ran.
2) The arm's run_config must carry CONTROL_MODE=BASE_PLAN and BASE_PLAN=<name>.
   Both are in MODE_FLAGS, so AAPIInit propagates them per arm.
3) MAXPRESSURE arms must print [LIGHTSIM_MP] lines.
   SOTL / LTMP / EFFMP must show gate hits (sotl_hold / lt_mp_hold /
   eff_mp_extend) and NO repeated "[SOTL] fallback to normal" /
   "[LT_MAXPRESSURE] fallback..." / "[EFF_MAXPRESSURE] fallback..." spam.
   Fallback spam = the measurement failed and the arm silently ran run_normal.

Do NOT score when
-----------------
* All 8 arms are byte-identical: the dispatch never fired (dead flag).
* A pressure arm falls back to run_normal every tick (see 3).
* GREENWAVE / WEBSTER == FIXEDTIME exactly: expected TODAY (the distinct
  offset / retiming logic is the flagged follow-up), not a win.

Two known defects in the SUMO twin (reported, NOT changed by this port)
----------------------------------------------------------------------
A. engine.run_lightsim_mp passes a phase ID to apply_action, but apply_action
   indexes phase_list (target_phase = self.phase_list[action]). Every MP switch
   therefore lands one phase late, and the last phase is unreachable
   (action == len(phase_list) fails the bound check). Fix is one line:
       self.apply_action(_phs.index(_pick), timeSta, time, acycle)
   Left alone because it would move the existing LIGHTSIM_MP arms mid-stream.
B. "LIGHTSIM_MP" is absent from the two CONTROL_MODE membership tuples that
   build corridor coordinators and verify External control_type. BASE_PLAN was
   added to both, so BASE_PLAN gets coordinators while LIGHTSIM_MP does not --
   one more reason a BASE_MAXPRESS vs LIGHTSIM_MP comparison is NOT clean.
   The clean control is the plain ..._CTM2_SPILL2 arm (== BASE_PLAN=FIXEDTIME).

1-rep wiring smoke (what is running now)
----------------------------------------
    python _sumo_port/run_gamemarg_ab.py --reps 1 --end 600 --seed 300 \
        --arms "<8 arms, see ARMS below>" \
        --csv _sumo_port/base_plan_smoke_300.csv

5-repeat expansion (only after the smoke shows every base is live)
------------------------------------------------------------------
    same command with --reps 5 (run_one varies the SUMO seed per rep) and a new
    --csv. 8 arms x 5 reps x ~4.5 min ~ 3 h.

Arms (all clones of CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2, differing only
in the base plan; built into CHAMPION_ARMS by sumo_bridge/sweep_arms.py).
"""
from __future__ import print_function

ARMS = [
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_BASE_FIXEDTIME",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_BASE_WEBSTER",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_BASE_GREENWAVE",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_BASE_MAXPRESS",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_BASE_SOTL",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_BASE_LTMP",
    "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_BASE_EFFMP",
]

if __name__ == "__main__":
    print("arms = %d\n" % len(ARMS))
    print("python _sumo_port/run_gamemarg_ab.py --reps 1 --end 600 --seed 300 "
          "--arms \"%s\" --csv _sumo_port/base_plan_smoke_300.csv"
          % ",".join(ARMS))
