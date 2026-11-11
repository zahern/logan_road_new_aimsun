"""Add match confidence support to the SUMO (older) Simulation_Stats module.

That module predates the clamp work: its add_schedule_dev takes no headway_s
and stores six fields. The SUMO engine now passes headway_s, match_mode,
match_confidence, match_window_s and stop_offset_s, so without this the
TypeError is swallowed by the engine's blanket except and EVERY schedule record
disappears. This adds the keywords, the fields and the KPIs, and clamps ONLY
unattributed records (matched ones stay raw, exactly as before).

Run from the project root:  python _patch_sumo_spm.py
"""
import io
import os
import re
import shutil
import sys
import textwrap

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PATHS = [r"Z:\tsp\sumo_hpc\kg\Simulation_Stats.py",
         r"_sumo_port\kg\Simulation_Stats.py"]

SIG_OLD = (
    '    def add_schedule_dev(self, line_id, dev_s, bus_occ=40.0, veh_id=None,\n'
    '                         observed_time_s=None, intended_time_s=None):'
)
SIG_NEW = (
    '    def add_schedule_dev(self, line_id, dev_s, bus_occ=40.0, veh_id=None,\n'
    '                         observed_time_s=None, intended_time_s=None,\n'
    '                         headway_s=None, match_mode=None,\n'
    '                         match_confidence=None, match_window_s=None,\n'
    '                         stop_offset_s=0.0):'
)

MODE_OLD = (
    '        dev_s = float(dev_s)\n'
    '        lst.append(dev_s)\n'
)
MODE_NEW = (
    '        dev_s = float(dev_s)\n'
    '        # Match quality (2026-11-10). "unmatched" means the nearest scheduled\n'
    '        # departure was further away than any bus on this line could plausibly\n'
    '        # be, so the signed deviation is not a lateness measure: clamp it and\n'
    '        # count it as unattributed rather than reporting a wrong match as\n'
    '        # measured delay. Matched records stay raw here -- this module predates\n'
    '        # the global clamp and nothing else changes for them.\n'
    '        _mode = None if match_mode is None else str(match_mode)\n'
    '        _conf = (None if match_confidence is None\n'
    '                 else max(0.0, min(1.0, float(match_confidence))))\n'
    '        _win = None if match_window_s is None else float(match_window_s)\n'
    '        _cap = 900.0\n'
    '        try:\n'
    '            if headway_s is not None and float(headway_s) > 30.0:\n'
    '                _cap = min(_cap, max(300.0, float(headway_s)))\n'
    '        except Exception:\n'
    '            pass\n'
    '        if _win is not None:\n'
    '            _cap = min(_cap, max(120.0, float(_win)))\n'
    '        if _mode == "unmatched":\n'
    '            dev_s = _cap if dev_s >= 0.0 else -_cap\n'
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
    '        lst.append(dev_s)\n'
)

REC_OLD = (
    '            "abs_deviation_s": round(abs(dev_s), 3),\n'
    '        })'
)
REC_NEW = (
    '            "abs_deviation_s": round(abs(dev_s), 3),\n'
    '            "match_mode": "" if _mode is None else _mode,\n'
    '            "match_confidence": "" if _conf is None else round(float(_conf), 3),\n'
    '            "match_window_s": "" if _win is None else round(float(_win), 1),\n'
    '            "stop_offset_s": round(float(stop_offset_s or 0.0), 1),\n'
    '        })'
)

KPI_LOCALS = (
    '        _n_unm = int(getattr(self, "_sched_unmatched", 0) or 0)\n'
    '        _n_m = int(getattr(self, "_sched_matched_n", 0) or 0)\n'
    '        _abs_m = float(getattr(self, "_sched_matched_abs", 0.0) or 0.0)\n'
    '        _conf_n = int(getattr(self, "_sched_conf_n", 0) or 0)\n'
    '        _conf_sum = float(getattr(self, "_sched_conf_sum", 0.0) or 0.0)\n'
)

EARLY_OLD = '            return {"n": 0,'
EARLY_NEW = (
    '            return {"n_unmatched": _n_unm,\n'
    '                    "pct_unmatched": 0.0,\n'
    '                    "n_matched": _n_m,\n'
    '                    "mean_abs_dev_matched": 0.0,\n'
    '                    "mean_match_confidence": 0.0,\n'
    '                    "n": 0,'
)
MAIN_OLD = '        return {"n": n,'
MAIN_NEW = (
    '        return {"n_unmatched": _n_unm,\n'
    '                "pct_unmatched": (round(100.0 * _n_unm / n, 1) if n else 0.0),\n'
    '                "n_matched": _n_m,\n'
    '                "mean_abs_dev_matched": (round(_abs_m / _n_m, 1) if _n_m else 0.0),\n'
    '                "mean_match_confidence": (round(_conf_sum / _conf_n, 3) if _conf_n else 0.0),\n'
    '                "n": n,'
)


def sub1(txt, old, new, tag):
    n = txt.count(old)
    print('  %-22s anchor=%d' % (tag, n))
    if n != 1:
        raise SystemExit('ABORT %s (anchor count %d)' % (tag, n))
    return txt.replace(old, new)


def patch_kpis(txt):
    i0 = txt.index('    def schedule_kpis(self):')
    i1 = txt.index('\n    def ', i0 + 10)
    body = txt[i0:i1]
    if 'n_unmatched' in body:
        print('  %-22s already patched' % 'kpis')
        return txt
    body = body.replace('        n = len(lst)\n', '        n = len(lst)\n' + KPI_LOCALS, 1)
    body = body.replace(EARLY_OLD, EARLY_NEW, 1)
    body = body.replace(MAIN_OLD, MAIN_NEW, 1)
    print('  %-22s locals=%s early=%s main=%s' % (
        'kpis', KPI_LOCALS in body, EARLY_NEW in body, MAIN_NEW in body))
    if not (KPI_LOCALS in body and EARLY_NEW in body and MAIN_NEW in body):
        raise SystemExit('ABORT kpis (anchor missing)')
    return txt[:i0] + body + txt[i1:]


def extract_methods(path):
    txt = io.open(path, encoding='utf-8', errors='replace').read()
    lines = txt.splitlines()
    j0 = next(i for i, l in enumerate(lines) if 'def add_schedule_dev(' in l)
    j1 = next(i for i in range(j0 + 1, len(lines)) if re.match(r'\s{4}def \w+\(', lines[i]))
    k0 = next(i for i, l in enumerate(lines) if 'def schedule_kpis(' in l)
    k1 = next(i for i in range(k0 + 1, len(lines)) if re.match(r'\s{4}def \w+\(', lines[i]))
    ns = {}
    exec(textwrap.dedent('\n'.join(lines[j0:j1])), ns)
    exec(textwrap.dedent('\n'.join(lines[k0:k1])), ns)

    class Stub:
        pass

    Stub.add_schedule_dev = ns['add_schedule_dev']
    Stub.schedule_kpis = ns['schedule_kpis']
    return Stub


def self_test(path):
    Stub = extract_methods(path)
    st = Stub()
    empty = st.schedule_kpis()
    st.add_schedule_dev(1, 10.0, veh_id=11, headway_s=300.0,
                        match_mode='window', match_confidence=0.933,
                        match_window_s=150.0)
    st.add_schedule_dev(1, -180.0, veh_id=12, headway_s=300.0,
                        match_mode='unmatched', match_confidence=0.0,
                        match_window_s=150.0)
    k = st.schedule_kpis()
    rec = st._schedule_records[1]
    checks = [
        ('empty branch has keys', 'n_unmatched' in empty, True),
        ('n_unmatched', k.get('n_unmatched'), 1),
        ('pct_unmatched', k.get('pct_unmatched'), 50.0),
        ('n_matched', k.get('n_matched'), 1),
        ('mean_abs_dev_matched', k.get('mean_abs_dev_matched'), 10.0),
        ('mean_match_confidence', k.get('mean_match_confidence'), 0.933),
        ('rec mode', rec.get('match_mode'), 'unmatched'),
        ('rec conf', rec.get('match_confidence'), 0.0),
        ('rec window', rec.get('match_window_s'), 150.0),
        ('unmatched clamped to 150', rec.get('deviation_s'), -150.0),
        ('matched left raw', st._schedule_records[0].get('deviation_s'), 10.0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += 0 if ok else 1
        print('    %s %-26s got=%r' % ('OK ' if ok else 'BAD', name, got))
    return bad


total_bad = 0
for P in PATHS:
    if not os.path.exists(P):
        print('missing', P)
        continue
    print('\n== %s' % P)
    s = io.open(P, encoding='utf-8', errors='replace').read()
    if 'match_confidence' in s:
        print('  already patched')
    else:
        shutil.copy2(P, P + '.pre_schedmatch.bak')
        s = sub1(s, SIG_OLD, SIG_NEW, 'sig')
        s = sub1(s, MODE_OLD, MODE_NEW, 'mode block')
        s = sub1(s, REC_OLD, REC_NEW, 'record fields')
        s = patch_kpis(s)
        tmp = P + '.sched.tmp'
        io.open(tmp, 'w', encoding='utf-8', newline='').write(s)
        os.replace(tmp, P)
        import py_compile
        py_compile.compile(P, doraise=True)
        print('  patched + compiled')
    total_bad += self_test(P)

print('\nself-test failures:', total_bad)
