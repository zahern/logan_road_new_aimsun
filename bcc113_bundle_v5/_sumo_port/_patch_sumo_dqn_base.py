"""Wire the numpy DQN into the SUMO BASE_PLAN family.

Adds a `DQN` base controller (run_dqn) that implements the LightSim paper's
agent spec inside SUMO: 5 s decisions, one-hot phase + normalised queues +
binary queue flags, queue reward, 2x64 MLP with replay/target net.

Idempotent. --dry-run reports without writing.
"""

import argparse
import re
import shutil
import sys
import time

ENGINE = r"Z:\tsp\sumo_hpc\shared_tsp_engine\engine.py"
MODES = r"Z:\tsp\sumo_hpc\shared_tsp_engine\specialized_modes.py"
SWEEP = r"Z:\tsp\sumo_hpc\sumo_bridge\sweep_arms.py"

STAMP = "2026-11-11T0700-sumo-base-plan-dqn"

METHODS = '''    # DQN base controller (2026-11-11). The LightSim paper's RL agent
    # (Su & Deng, arXiv:2602.21852) applied inside SUMO: one decision per
    # DQN_DECIDE_S, one-hot phase + normalised queues + binary queue flags,
    # reward = minus the total incoming queue, 2x64 MLP with replay + target
    # net. The paper's own SUMO test replays a LightSim-trained checkpoint;
    # this machine has neither torch nor LightSim, so the agent learns here.
    def _dqn_state(self, ring_cur, rows, n_green):
        _norm = float(globals().get('DQN_QUEUE_NORM', 30.0) or 30.0)
        _s = np.zeros(3 * int(n_green), dtype=float)
        _i = int(ring_cur) if ring_cur is not None else 0
        if 0 <= _i < int(n_green):
            _s[_i] = 1.0
        else:
            _s[0] = 1.0
        for _k, _r in enumerate(rows):
            _q = float(sum(_r))
            _s[int(n_green) + _k] = min(_q / max(_norm, 1e-6), 1.0)
            _s[2 * int(n_green) + _k] = 1.0 if _q > 0.0 else 0.0
        return _s

    def _dqn_agent_for(self, n_actions):
        """Lazily build this junction's agent (weights reloaded when asked)."""
        try:
            import dqn_base
        except Exception:
            try:
                from shared_tsp_engine import dqn_base
            except Exception:
                return None
        _a = getattr(self, '_dqn', None)
        if _a is not None and int(getattr(_a, 'na', -1)) == int(n_actions):
            return _a
        _seed = int(globals().get('GAME_CTM2_CHAIN_SEED', 0) or 0)
        try:
            _seed += int(self.id)
        except Exception:
            pass
        _a = dqn_base.NumpyDQN(
            3 * int(n_actions), int(n_actions),
            hidden=int(globals().get('DQN_HIDDEN', 64) or 64),
            lr=float(globals().get('DQN_LR', 1e-3) or 1e-3),
            gamma=float(globals().get('DQN_GAMMA', 0.99) or 0.99),
            batch=int(globals().get('DQN_BATCH', 32) or 32),
            buffer=int(globals().get('DQN_BUFFER', 20000) or 20000),
            eps_end=float(globals().get('DQN_EPS_END', 0.05) or 0.05),
            eps_steps=int(globals().get('DQN_EPS_STEPS', 20000) or 20000),
            target_every=int(globals().get('DQN_TARGET_EVERY', 500) or 500),
            train_every=int(globals().get('DQN_TRAIN_EVERY', 4) or 4),
            seed=_seed)
        _wp = str(globals().get('DQN_WEIGHTS_PATH', '') or '')
        if _wp:
            try:
                _a.load(_wp + ".%s.npz" % int(self.id))
                self._bp_bump('dqn_loaded')
            except Exception:
                pass
        self._dqn = _a
        return _a

    def run_dqn(self, time, timeSta, acycle):
        """DQN base controller: choose a green phase, one decision per 5 s."""
        _m = self._base_plan_rows(time)
        if _m is None:
            self._bp_bump('dqn_nomeasure')
            self.run_normal(time, timeSta, acycle)
            return
        _phs, _green, _rows, _cur_id, _ring_cur, _elapsed = _m
        _n = len(_green)
        _agent = self._dqn_agent_for(_n)
        if _agent is None:
            self._bp_bump('dqn_noagent')
            self.run_normal(time, timeSta, acycle)
            return
        if _ring_cur is None:
            _pos = getattr(self, '_dqn_pos', None)
            if _pos is not None and 0 <= int(_pos) < _n:
                _ring_cur = int(_pos)
            else:
                try:
                    _ring_cur = _phs.index(_cur_id) % _n
                except Exception:
                    _ring_cur = 0
        _s = self._dqn_state(_ring_cur, _rows, _n)
        _q_tot = float(sum(sum(_r) for _r in _rows))

        # Learn from the previous decision now that its successor is known.
        _prev = getattr(self, '_dqn_prev', None)
        if _prev is not None:
            try:
                _agent.observe(_prev[0], _prev[1], -float(_prev[2]), _s, False)
                self._bp_bump('dqn_observe')
            except Exception:
                self._bp_bump('dqn_observe_err')

        _min_g = float(globals().get('MIN_GREEN', 6.0) or 6.0)
        _dec = float(globals().get('DQN_DECIDE_S', 5.0) or 5.0)
        _last = float(getattr(self, '_dqn_last_dec', -1.0e9))
        if _elapsed < _min_g or (float(time) - _last) < _dec:
            self._bp_bump('dqn_hold')
            return
        _a = int(_agent.act(_s))
        self._dqn_last_dec = float(time)
        self._dqn_prev = (_s, _a, _q_tot)
        self._dqn_pos = _a
        if _a != _ring_cur:
            try:
                _idx = _phs.index(_green[_a])
            except Exception:
                self._bp_bump('dqn_badact')
                return
            self._bp_bump('dqn_switch')
            try:
                self.apply_action(_idx, timeSta, time, acycle)
            except Exception:
                pass
        else:
            self._bp_bump('dqn_stay')

'''

DISPATCH_OLD = """        elif _bp in ('EFF_MAXPRESSURE', 'EFFMP'):
            self.run_maxpressure_eff(time, timeSta, acycle)"""

DISPATCH_NEW = """        elif _bp in ('EFF_MAXPRESSURE', 'EFFMP'):
            self.run_maxpressure_eff(time, timeSta, acycle)
        elif _bp in ('DQN', 'DQ'):
            self.run_dqn(time, timeSta, acycle)"""

DUMP_OLD = """            if _all:
                log_to_file("[BASE_PLAN DIAG] inter=%s %s"
                            % (getattr(_c, 'id', '?'),
                               " ".join("%s=%d" % (_k, _v) for _k, _v in
                                        sorted(_all.items(),
                                               key=lambda kv: -kv[1]))))"""

DUMP_NEW = DUMP_OLD + """
            _ag = getattr(_c, '_dqn', None)
            if _ag is not None:
                try:
                    log_to_file(
                        "[BASE_PLAN DIAG] inter=%s dqn_steps=%d dqn_updates=%d "
                        "dqn_eps=%.3f dqn_loss=%.5f"
                        % (getattr(_c, 'id', '?'), _ag.steps, _ag.updates,
                           _ag.last_eps, _ag.last_loss))
                except Exception:
                    pass
                _wp = str(globals().get('DQN_WEIGHTS_PATH', '') or '')
                if _wp:
                    try:
                        _ag.save(_wp + ".%s.npz" % int(getattr(_c, 'id', 0)))
                    except Exception:
                        pass"""

KNOBS_OLD = "EFF_MP_PRESSURE_GAIN_S   = 4.0    # Eff-MP: green seconds per unit of pressure"

KNOBS_NEW = """EFF_MP_PRESSURE_GAIN_S   = 4.0    # Eff-MP: green seconds per unit of pressure

# DQN base (LightSim paper spec, arXiv:2602.21852): one decision every
# DQN_DECIDE_S, 2x64 MLP, Adam lr 1e-3, gamma 0.99, replay batch 32,
# epsilon 1.0 -> DQN_EPS_END over DQN_EPS_STEPS, target sync every 500
# updates, reward = minus total incoming queue. DQN_WEIGHTS_PATH persists
# per-junction weights (".<id>.npz") so training accumulates across reps.
DQN_DECIDE_S             = 5.0
DQN_HIDDEN               = 64
DQN_LR                   = 1e-3
DQN_GAMMA                = 0.99
DQN_BATCH                = 32
DQN_BUFFER               = 20000
DQN_EPS_END              = 0.05
DQN_EPS_STEPS            = 20000
DQN_TARGET_EVERY         = 500
DQN_TRAIN_EVERY          = 4
DQN_QUEUE_NORM           = 30.0
DQN_WEIGHTS_PATH         = \"\""""

FLAGS_OLD = "'BASE_PLAN', 'BASE_PLAN_TSP', 'SOTL_THRESHOLD', 'LT_MP_SWITCH_BAR', 'EFF_MP_PRESSURE_GAIN_S',"

FLAGS_NEW = FLAGS_OLD + """
    'DQN_DECIDE_S', 'DQN_HIDDEN', 'DQN_LR', 'DQN_GAMMA', 'DQN_BATCH',
    'DQN_BUFFER', 'DQN_EPS_END', 'DQN_EPS_STEPS', 'DQN_TARGET_EVERY',
    'DQN_TRAIN_EVERY', 'DQN_QUEUE_NORM', 'DQN_WEIGHTS_PATH',"""

ARMS_OLD = """        dict(_CTM2_SPILL2, CONTROL_MODE="BASE_PLAN", BASE_PLAN=_bpn,
             BASE_PLAN_TSP=False),
    ))"""

ARMS_NEW = ARMS_OLD + """

# DQN base (2026-11-11): the LightSim paper's RL agent as the base plan.
for _bpn, _bptag in (("DQN", "BASE_DQN"),):
    CTM2_ARMS.append((
        "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_" + _bptag,
        "nash",
        dict(_CTM2_SPILL2, CONTROL_MODE="BASE_PLAN", BASE_PLAN=_bpn),
    ))"""


def sub_once(src, old, new, label):
    n = src.count(old)
    if n != 1:
        raise SystemExit("[FAIL] anchor %r occurs %d times" % (label, n))
    return src.replace(old, new)


def patch_engine(src):
    src = sub_once(src, "    def run_base_plan(self, time, timeSta, acycle):",
                   METHODS + "    def run_base_plan(self, time, timeSta, acycle):",
                   "run_base_plan insert")
    src = sub_once(src, DISPATCH_OLD, DISPATCH_NEW, "run_base_plan DQN branch")
    src = sub_once(src, DUMP_OLD, DUMP_NEW, "diag dump DQN")
    return src


def patch_modes(src):
    src = sub_once(src, KNOBS_OLD, KNOBS_NEW, "DQN knobs")
    src = sub_once(src, FLAGS_OLD, FLAGS_NEW, "MODE_FLAGS DQN")
    return src


def patch_arms(src):
    return sub_once(src, ARMS_OLD, ARMS_NEW, "BASE_DQN arm")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    changed = 0
    jobs = ((ENGINE, patch_engine, "_dqn_agent_for"),
            (MODES, patch_modes, "DQN_DECIDE_S"),
            (SWEEP, patch_arms, "BASE_DQN"))
    for path, fn, marker in jobs:
        with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
            src = f.read()
        if marker in src:
            print("[SKIP] %s already patched" % path)
            continue
        out = fn(src)
        print("[OK] %s  +%d bytes" % (path, len(out) - len(src)))
        if not args.dry_run:
            bak = "%s.bak_dqn_%s" % (path, stamp)
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
