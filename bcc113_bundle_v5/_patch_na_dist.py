"""Bucket every NO_ACTION exit in the reward path (2026-11-10).

Before: 805 detections / 973 evaluations / 0 actions, and the log could not
say where the decision died -- only 'no_action_hold_bus=6338' (the debounce
gate) was visible, because just a handful of the ~25 returns on the path
called _gate_hit at all.

After: each detection names ONE cause. [GATE SUMMARY] carries na:<cause>=<n>
next to the existing gate counters, so the missing mass is a measured
distribution instead of an inference.

Idempotent: every anchor is asserted to occur exactly once; a second run
finds the injected lines and exits without touching the file.
"""
import io
import re
import sys

PATH = 'shared_tsp_engine/engine.py'
STAMP_OLD = '2026-11-10T1900-lightsim-mp-schedmatch'
STAMP_NEW = '2026-11-10T2400-lightsim-mp-na-dist'

HELPER = '''    def _no_action_reason(self, reason, time=0.0):
        """Bucket a NO_ACTION outcome by cause (2026-11-10).

        The reward path has ~25 early returns but only the debounce gates
        called _gate_hit, so a run reporting 805 detections, 973 evaluations
        and 0 actions could not say WHERE the decision died. Every return on
        the path now names its own cause and the [GATE SUMMARY] line carries
        an na:<cause>=<n> distribution, so the unaccounted mass is measured.

        First named cause per detection wins: the marker is reset at the top
        of run_reward_tsp, so a detection that walks through several stages
        is booked once, at the stage that actually stopped it.
        """
        try:
            if getattr(self, '_na_cause', None) is not None:
                return
            self._na_cause = str(reason)
            self._gate_hit('na:' + str(reason), time)
        except Exception:
            pass

'''

EDITS = [
    # (anchor, replacement, label)
    ('    def _record_detection(self, time, veh_id=None, inter_id=None):',
     HELPER + '    def _record_detection(self, time, veh_id=None, inter_id=None):',
     'helper'),

    ('        # CBQL_SHAPLEY (observe-only wiring): run the phase-selection Shapley',
     '        self._na_cause = None   # per-detection NO_ACTION cause (na:* buckets)\n'
     '        # CBQL_SHAPLEY (observe-only wiring): run the phase-selection Shapley',
     'reset'),

    ('                if self._coordinated_actuated_base(time, timeSta, acycle):\n'
     '                    return',
     '                if self._coordinated_actuated_base(time, timeSta, acycle):\n'
     "                    self._no_action_reason('actuated_base', time)\n"
     '                    return',
     'actuated_base'),

    ('                if (time - _ps_active) < _min_active:\n'
     '                    return',
     '                if (time - _ps_active) < _min_active:\n'
     "                    self._no_action_reason('min_phase_active', time)\n"
     '                    return',
     'min_phase_active'),

    ('                return\n'
     '            self._prearm_block_logged = False',
     "                self._no_action_reason('prearm_cycle_end', time)\n"
     '                return\n'
     '            self._prearm_block_logged = False',
     'prearm_cycle_end'),

    ('                    if self._maybe_skip_empty_phase(time, timeSta, acycle,\n'
     '                                                    current_phase):\n'
     '                        return',
     '                    if self._maybe_skip_empty_phase(time, timeSta, acycle,\n'
     '                                                    current_phase):\n'
     "                        self._no_action_reason('empty_phase_skip', time)\n"
     '                        return',
     'empty_phase_skip'),

    ('                    log_to_file(f"[MONITOR] inter={self.id} error {_mme!r}")\n'
     '            return',
     '                    log_to_file(f"[MONITOR] inter={self.id} error {_mme!r}")\n'
     "            if getattr(self, '_na_cause', None) is None:\n"
     "                self._no_action_reason('monitor_no_bus', time)\n"
     '            return',
     'monitor_no_bus'),

    ('            _mark_detection_point(self.id, _det_vid, 0.0, 0.0, time, "focus_suppress")\n'
     '            self._record_detection(time)\n'
     '            return',
     '            _mark_detection_point(self.id, _det_vid, 0.0, 0.0, time, "focus_suppress")\n'
     '            self._record_detection(time)\n'
     "            self._no_action_reason('focus_suppress', time)\n"
     '            return',
     'focus_suppress'),

    ("        if bus_eta_s > 2.0 * _cycle:\n"
     "            self._reward_no_action_until = time + float(globals().get('NO_ACTION_HOLD_S', 5.0) or 5.0)\n"
     '            return',
     "        if bus_eta_s > 2.0 * _cycle:\n"
     "            self._reward_no_action_until = time + float(globals().get('NO_ACTION_HOLD_S', 5.0) or 5.0)\n"
     "            self._no_action_reason('bus_beyond_2_cycles', time)\n"
     '            return',
     'bus_beyond_2_cycles'),

    ('        if (_sig_act > _sig_max) or (bus_eta_s < _act_min_lead):\n'
     '            self._reward_no_action_until = time + 3.0\n'
     '            return',
     '        if (_sig_act > _sig_max) or (bus_eta_s < _act_min_lead):\n'
     '            self._reward_no_action_until = time + 3.0\n'
     "            self._no_action_reason('sigma_or_lead_gate', time)\n"
     '            return',
     'sigma_or_lead_gate'),

    ('        if self.flag == 0:\n'
     "            _hold = float(globals().get('NO_ACTION_HOLD_S', 5.0) or 0.0)",
     '        if self.flag == 0:\n'
     "            if getattr(self, '_na_cause', None) is None:\n"
     "                self._no_action_reason('unattributed', time)\n"
     "            _hold = float(globals().get('NO_ACTION_HOLD_S', 5.0) or 0.0)",
     'safety_net'),

    ('            if stats_ok:\n'
     '                self._record_detection(time)\n'
     '            return\n'
     '\n'
     '        # Action 0: NO_ACTION',
     '            if stats_ok:\n'
     '                self._record_detection(time)\n'
     "            self._no_action_reason('focus_suppress_eval', time)\n"
     '            return\n'
     '\n'
     '        # Action 0: NO_ACTION',
     'focus_suppress_eval'),

    ('                    f"below tolerance={-_z4_eff_tol():.0f} -> forcing NO_ACTION",\n'
     '                    )\n'
     '                best_action = "NO_ACTION"',
     '                    f"below tolerance={-_z4_eff_tol():.0f} -> forcing NO_ACTION",\n'
     '                    )\n'
     "                self._no_action_reason('z4_gate', time)\n"
     '                best_action = "NO_ACTION"',
     'z4_gate'),

    ('                    _na_reason = "cost to others outweighs bus benefit"\n'
     '            log_to_file(',
     '                    _na_reason = "cost to others outweighs bus benefit"\n'
     "            _na_tok = 'cost_veto'\n"
     "            _na_nat = False\n"
     '            try:\n'
     '                _na_nat = bool(_nat_green)\n'
     '            except Exception:\n'
     '                _na_nat = False\n'
     '            if _na_nat:\n'
     "                _na_tok = 'natural_green'\n"
     "            elif _na_reason.startswith('per-cycle gap'):\n"
     "                _na_tok = 'per_cycle_gap'\n"
     "            elif _na_reason.startswith('duration <'):\n"
     "                _na_tok = 'duration_below_min'\n"
     "            elif 'pre-warm' in _na_reason:\n"
     "                _na_tok = 'decider_prewarm'\n"
     "            elif 'on-time' in _na_reason:\n"
     "                _na_tok = 'decider_on_time'\n"
     "            elif 'no net-positive' in _na_reason:\n"
     "                _na_tok = 'decider_no_gain'\n"
     '            self._no_action_reason(_na_tok, time)\n'
     '            log_to_file(',
     'funnel'),
]


def main():
    src = io.open(PATH, encoding='utf-8', errors='surrogateescape').read()
    if '_no_action_reason' in src:
        print('already patched -- nothing to do')
        return 0
    out = src
    for anchor, repl, label in EDITS:
        n = out.count(anchor)
        if n != 1:
            print('ANCHOR FAIL %-20s occurrences=%d' % (label, n))
            return 2
        out = out.replace(anchor, repl, 1)
        print('ok %-20s' % label)
    n_stamp = out.count(STAMP_OLD)
    if n_stamp != 1:
        print('STAMP FAIL occurrences=%d' % n_stamp)
        return 3
    out = out.replace(STAMP_OLD, STAMP_NEW, 1)
    print('ok stamp                %s -> %s' % (STAMP_OLD, STAMP_NEW))
    io.open(PATH + '.pre_nadist.bak', 'w', encoding='utf-8',
            errors='surrogateescape').write(src)
    io.open(PATH, 'w', encoding='utf-8', errors='surrogateescape').write(out)
    print('written, backup .pre_nadist.bak')
    return 0


if __name__ == '__main__':
    sys.exit(main())
