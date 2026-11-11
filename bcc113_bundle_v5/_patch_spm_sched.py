"""Record schedule-match confidence in Simulation_Stats and expose KPIs.

Run from the project root:  python _patch_spm_sched.py
"""
import io
import os
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def load(p):
    return io.open(p, encoding='utf-8', errors='replace').read()


def sub1(txt, old, new, tag):
    n = txt.count(old)
    print('  %-24s anchor=%d' % (tag, n))
    if n != 1:
        raise SystemExit('ABORT %s (anchor count %d)' % (tag, n))
    return txt.replace(old, new)


SIG_OLD = (
    '    def add_schedule_dev(self, line_id, dev_s, bus_occ=40.0, veh_id=None,\n'
    '                         observed_time_s=None, intended_time_s=None,\n'
    '                         headway_s=None):'
)
SIG_NEW = (
    '    def add_schedule_dev(self, line_id, dev_s, bus_occ=40.0, veh_id=None,\n'
    '                         observed_time_s=None, intended_time_s=None,\n'
    '                         headway_s=None, match_mode=None,\n'
    '                         match_confidence=None, match_window_s=None,\n'
    '                         stop_offset_s=0.0):'
)

CLAMP_OLD = (
    '        if abs(raw_dev_s) > _cap:\n'
    '            self._sched_pen_clamped = int(\n'
    '                getattr(self, "_sched_pen_clamped", 0) or 0) + 1\n'
)
CLAMP_NEW = CLAMP_OLD + (
    '        # Match quality (2026-11-10). "unmatched" means the nearest scheduled\n'
    '        # departure was further away than any bus on this line could plausibly\n'
    '        # be, so the signed deviation is NOT a lateness measure: penalise it at\n'
    '        # the clamp (maximum) and count it as unattributed rather than letting\n'
    '        # a wrong match masquerade as a measured delay.\n'
    '        _mode = None if match_mode is None else str(match_mode)\n'
    '        _conf = (None if match_confidence is None\n'
    '                 else max(0.0, min(1.0, float(match_confidence))))\n'
    '        _win = None if match_window_s is None else float(match_window_s)\n'
    '        if _mode == "unmatched":\n'
    '            dev_s = _cap if raw_dev_s >= 0.0 else -_cap\n'
    '            self._sched_pen_clamped = int(\n'
    '                getattr(self, "_sched_pen_clamped", 0) or 0) + 1\n'
    '            self._sched_unmatched = int(\n'
    '                getattr(self, "_sched_unmatched", 0) or 0) + 1\n'
    '        elif _mode == "window":\n'
    '            self._sched_matched_abs = float(\n'
    '                getattr(self, "_sched_matched_abs", 0.0) or 0.0) + abs(dev_s)\n'
    '            self._sched_matched_n = int(\n'
    '                getattr(self, "_sched_matched_n", 0) or 0) + 1\n'
    '            self._sched_conf_sum = float(\n'
    '                getattr(self, "_sched_conf_sum", 0.0) or 0.0) + float(_conf or 0.0)\n'
    '            self._sched_conf_n = int(getattr(self, "_sched_conf_n", 0) or 0) + 1\n'
)

REC_OLD = (
    '            "penalty_clamped": 1 if abs(raw_dev_s) > _cap else 0,\n'
    '        })'
)
REC_NEW = (
    '            "penalty_clamped": 1 if abs(raw_dev_s) > _cap else 0,\n'
    '            "match_mode": "" if _mode is None else _mode,\n'
    '            "match_confidence": "" if _conf is None else round(float(_conf), 3),\n'
    '            "match_window_s": "" if _win is None else round(float(_win), 1),\n'
    '            "stop_offset_s": round(float(stop_offset_s or 0.0), 1),\n'
    '        })'
)

EMPTY_OLD = (
    '                    "n_pen_clamped": 0,\n'
    '                    "dev_clamp_s": float(getattr(self, "SCHED_DEV_CLAMP_S",\n'
    '                                                900.0) or 900.0)}'
)
EMPTY_NEW = (
    '                    "n_pen_clamped": 0,\n'
    '                    "n_unmatched": 0,\n'
    '                    "pct_unmatched": 0.0,\n'
    '                    "n_matched": 0,\n'
    '                    "mean_abs_dev_matched": 0.0,\n'
    '                    "mean_match_confidence": 0.0,\n'
    '                    "dev_clamp_s": float(getattr(self, "SCHED_DEV_CLAMP_S",\n'
    '                                                900.0) or 900.0)}'
)

LOC_OLD = (
    '        late = [d for d in lst if d > 0]\n'
    '        early = [d for d in lst if d < -15]'
)
LOC_NEW = LOC_OLD + (
    '\n        _n_unm = int(getattr(self, "_sched_unmatched", 0) or 0)\n'
    '        _n_m = int(getattr(self, "_sched_matched_n", 0) or 0)\n'
    '        _abs_m = float(getattr(self, "_sched_matched_abs", 0.0) or 0.0)\n'
    '        _conf_n = int(getattr(self, "_sched_conf_n", 0) or 0)\n'
    '        _conf_sum = float(getattr(self, "_sched_conf_sum", 0.0) or 0.0)'
)

VAL_OLD = '                "pct_bunched": round(100.0 * len(early) / n, 1),'
VAL_NEW = (
    '                "pct_bunched": round(100.0 * len(early) / n, 1),\n'
    '                "n_unmatched": _n_unm,\n'
    '                "pct_unmatched": round(100.0 * _n_unm / n, 1),\n'
    '                "n_matched": _n_m,\n'
    '                "mean_abs_dev_matched": (round(_abs_m / _n_m, 1)\n'
    '                                         if _n_m else 0.0),\n'
    '                "mean_match_confidence": (round(_conf_sum / _conf_n, 3)\n'
    '                                          if _conf_n else 0.0),'
)

for S in (sys.argv[1:] or ['shared_tsp_engine/Simulation_Stats.py',
                            'kg/Simulation_Stats.py']):
    if not os.path.exists(S):
        print('missing', S)
        continue
    s = load(S)
    if 'match_confidence' in s:
        print(S, 'already patched')
        continue
    shutil.copy2(S, S + '.pre_schedmatch.bak')
    s = sub1(s, SIG_OLD, SIG_NEW, S + ' sig')
    s = sub1(s, CLAMP_OLD, CLAMP_NEW, S + ' mode block')
    s = sub1(s, REC_OLD, REC_NEW, S + ' record fields')
    s = sub1(s, EMPTY_OLD, EMPTY_NEW, S + ' kpi empty')
    s = sub1(s, LOC_OLD, LOC_NEW, S + ' kpi locals')
    s = sub1(s, VAL_OLD, VAL_NEW, S + ' kpi values')
    tmp = S + '.sched.tmp'
    io.open(tmp, 'w', encoding='utf-8', newline='').write(s)
    os.replace(tmp, S)
    import py_compile
    py_compile.compile(S, doraise=True)
    print(S, 'patched + compiled')
