"""LightSim MaxPressure as the BASE signal plan for the Aimsun TSP engine.

Purpose
-------
The Aimsun-side pipeline currently has no "plain signal controller" underneath
the TSP logic: ``CONTROL_MODE`` picks between ``NORMAL`` (fixed plan rolled by
Aimsun), ``HARMONY``/``URTSP``/``REWARD_TSP`` (TSP-driven) and ``DRL_DENSITY``
(which just calls ``run_reward_tsp``).  The game-theory layer therefore has
nothing principled to fall back on when it declines to act, and every arm is
implicitly "TSP plus whatever the local plan was doing".

This module ports the stage-selection rule of LightSim's MaxPressureController
(``lightsim/core/signal.py``) so the engine can run *LightSim's controller* as
the base plan and let the TSP / game layer override it on top -- which is the
architecture the paper needs:

    base plan  : MaxPressure over the phase queue matrix (this module)
    game layer : GAME_SOLUTION / NASH / utilitarian arbitration may override

Why a port and not an import
----------------------------
Aimsun runs its own embedded interpreter; the ``lightsim`` package lives in the
KG probe venv and pulls in SUMO-flavoured state.  Only the decision rule is
needed here, so it is reproduced exactly and kept dependency-free.

The rule (LightSim ``MaxPressureController.get_phase_index``)
-------------------------------------------------------------
    pressure(stage) = sum of queue on the approaches the stage serves
    choose the stage with maximum pressure

with the usual protective constraints applied by the caller (minimum green,
maximum green), which the Aimsun engine already implements in
``apply_action`` (MIN_GREEN = 5 s, MAX_GREEN = 60 s).

Integration point (engine)
--------------------------
    from kg_lightsim_base import max_pressure_phase

    # inside run_reward_tsp, *before* the TSP/game layer gets a chance to act:
    if BASE_PLAN == "lightsim_mp" and not self._tsp_has_action:
        self.apply_action(max_pressure_phase(self.MaxQueueLength, ...), ...)

``self.MaxQueueLength`` is already ``np.zeros((n_phases, n_cols))`` (engine
~9431) with ``n_phases == len(self.phase_list)``, so phase p's row is exactly
the set of approaches that stage serves -- no detector-to-phase map is needed.
"""

from __future__ import annotations

MIN_GREEN = 5.0
MAX_GREEN = 60.0


def _row_sums(queue_by_phase):
    """Sum each phase row; accepts a numpy 2-D array, list of lists or flat list."""
    rows = []
    for r in queue_by_phase:
        try:
            rows.append(float(sum(r)))
        except TypeError:                      # flat sequence of scalars
            rows.append(float(r))
    return rows


def max_pressure_phase(queue_by_phase, current=None, elapsed_green=0.0,
                       min_green=MIN_GREEN, max_green=MAX_GREEN):
    """Return the 0-based stage index MaxPressure would serve now.

    queue_by_phase : sequence (one entry per stage) of per-approach queues
    current        : 0-based index of the stage being served, or None
    elapsed_green  : seconds the current stage has been green

    Protective behaviour mirrors the engine's own ``apply_action``:
      * hold the current stage until ``min_green`` has elapsed
      * force a rotation to the next stage at ``max_green``
      * otherwise serve the highest-pressure stage (ties keep the current one)
    """
    pressures = _row_sums(queue_by_phase)
    n = len(pressures)
    if n == 0:
        return current if current is not None else 0

    if current is not None:
        cur = int(current) % n
        if elapsed_green < min_green:
            return cur
        if elapsed_green >= max_green:
            return (cur + 1) % n

    best = max(range(n), key=lambda i: (pressures[i], i == (current or -1)))
    return best


def _selftest():
    # 4 stages, stage 2 is loaded
    q = [[0.0, 1.0], [0.0, 2.0], [9.0, 8.0], [1.0, 0.0]]
    assert max_pressure_phase(q, current=0, elapsed_green=10) == 2, "picks loaded stage"

    # min green holds
    assert max_pressure_phase(q, current=0, elapsed_green=2) == 0, "holds for min green"

    # max green forces rotation off a loaded stage
    assert max_pressure_phase(q, current=2, elapsed_green=60) == 3, "max green rotates"

    # tie keeps the current stage (stability, avoids flapping)
    tie = [[1.0, 1.0], [1.0, 1.0]]
    assert max_pressure_phase(tie, current=1, elapsed_green=20) == 1, "tie is stable"

    # flat rows degrade gracefully
    assert max_pressure_phase([3.0, 0.0, 1.0], current=None) == 0, "flat input"
    assert max_pressure_phase([], current=0) == 0, "empty input"
    print("kg_lightsim_base: all self-tests passed")


if __name__ == "__main__":
    _selftest()
