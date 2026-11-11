"""Per-line / per-stop schedule match with a window and recorded confidence.

Run from the project root:  python _patch_engine_sched.py
"""
import io
import os
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

E = 'shared_tsp_engine/engine.py'


def load(p):
    return io.open(p, encoding='utf-8', errors='replace').read()


def sub1(txt, old, new, tag):
    n = txt.count(old)
    print('  %-26s anchor=%d' % (tag, n))
    if n != 1:
        raise SystemExit('ABORT %s (anchor count %d)' % (tag, n))
    return txt.replace(old, new)


e = load(E)
if 'SCHED_MATCH_MIN_WINDOW_S' in e and 'match_confidence' in e:
    print('engine.py already patched')
    raise SystemExit(0)

shutil.copy2(E, E + '.pre_schedmatch.bak')

e = sub1(e, "_SCHED_WALL_START = [None]\n",
         "_SCHED_WALL_START = [None]\n"
         "_SCHED_MATCH_MIN_WINDOW_S = 120.0   # never narrower than this (s)\n"
         "_SCHED_MATCH_MAX_WINDOW_S = 900.0   # never wider than this (s)\n",
         'constants')

OLDMATCH = (
    'def _match_departure(line_id, observed_wall_s):\n'
    '    """(deviation_s, intended_departure_s) against the nearest scheduled\n'
    '    departure for the line. dev = observed wall entry - intended (early\n'
    '    negative, late positive). Returns (None, None) when the line has no fixed\n'
    '    departures (interval lines / unknown wall-start) so callers fall back to\n'
    '    the headway method. Never raises."""\n'
    '    try:\n'
    '        _deps = _SCHED_DEPARTURES.get(int(line_id))\n'
    '        if not _deps:\n'
    '            return (None, None)\n'
    '        _obs = float(observed_wall_s)\n'
    '        _best_d = None\n'
    '        _best_t = None\n'
    '        for _t in _deps:\n'
    '            try:\n'
    '                _tt = float(_t)\n'
    '            except Exception:\n'
    '                continue\n'
    '            _d = _obs - _tt\n'
    '            if _best_d is None or abs(_d) < abs(_best_d):\n'
    '                _best_d = _d\n'
    '                _best_t = _tt\n'
    '        return (_best_d, _best_t)\n'
    '    except Exception:\n'
    '        return (None, None)\n'
)

NEWMATCH = (
    'def _sched_match_window_s(line_id):\n'
    '    """Half-headway match window for one line, clamped to [120, 900] s.\n'
    '\n'
    '    A bus more than half a headway from a departure cannot be told apart from\n'
    '    the bus on the NEXT departure, so this is the largest deviation the\n'
    '    timetable can still attribute to a specific run.\n'
    '    """\n'
    '    try:\n'
    '        _h = float(_SCHED_SPACING.get(int(line_id)) or 0.0)\n'
    '    except Exception:\n'
    '        _h = 0.0\n'
    '    _w = 0.5 * _h if _h > 0.0 else _SCHED_MATCH_MAX_WINDOW_S\n'
    '    return max(_SCHED_MATCH_MIN_WINDOW_S, min(_SCHED_MATCH_MAX_WINDOW_S, _w))\n'
    '\n'
    '\n'
    'def _match_departure(line_id, observed_wall_s, stop_offset_s=0.0):\n'
    '    """Attribute one bus observation to a scheduled departure of ITS line.\n'
    '\n'
    '    Returns (deviation_s, intended_s, confidence, mode):\n'
    "      'window'    matched inside the line's half-headway window; confidence is\n"
    '                  1 - |dev|/window, so 1.0 is dead on time and ->0 sits at the\n'
    '                  window edge.\n'
    "      'unmatched' the nearest departure is further than any bus on that line\n"
    '                  could plausibly be. The deviation is still returned so the\n'
    '                  caller penalises it (at the clamp), but it is counted as\n'
    '                  unattributed instead of being reported as lateness.\n'
    '      None        the line has no timetable; caller uses the headway method.\n'
    '\n'
    '    stop_offset_s shifts the departure to the scheduled time at a downstream\n'
    '    stop, so the same window works per stop rather than only at line entry.\n'
    '\n'
    '    2026-11-10: this used to return the unbounded nearest departure. On the KG\n'
    '    corridor that produced mean |dev| 877 s and mean signed -418 s on lines\n'
    '    whose headway makes that physically impossible -- the match was landing\n'
    '    roughly half a headway away and reporting the gap as lateness.\n'
    '    """\n'
    '    try:\n'
    '        _lid = int(line_id)\n'
    '        _deps = _SCHED_DEPARTURES.get(_lid)\n'
    '        if not _deps:\n'
    '            return (None, None, 0.0, None)\n'
    '        _obs = float(observed_wall_s)\n'
    '        _off = float(stop_offset_s or 0.0)\n'
    '        _win = _sched_match_window_s(_lid)\n'
    '        _best_d = None\n'
    '        _best_t = None\n'
    '        for _t in _deps:\n'
    '            try:\n'
    '                _tt = float(_t) + _off\n'
    '            except Exception:\n'
    '                continue\n'
    '            _d = _obs - _tt\n'
    '            if _best_d is None or abs(_d) < abs(_best_d):\n'
    '                _best_d = _d\n'
    '                _best_t = _tt\n'
    '        if _best_d is None:\n'
    '            return (None, None, 0.0, None)\n'
    '        if abs(_best_d) <= _win:\n'
    '            return (_best_d, _best_t,\n'
    '                    max(0.0, min(1.0, 1.0 - abs(_best_d) / _win)), "window")\n'
    '        return (_best_d, _best_t, 0.0, "unmatched")\n'
    '    except Exception:\n'
    '        return (None, None, 0.0, None)\n'
)

e = sub1(e, OLDMATCH, NEWMATCH, 'match_departure')

# ── call site 1: first-sighting loop ────────────────────────────────
e = sub1(e,
         '                dev = None\n'
         '                _intended = None\n'
         '                if _PT_FIRST_SEEN.get(_vid, 1e9) > WARMUP_GRACE_S:\n'
         '                    try:\n'
         '                        _w0 = _SCHED_WALL_START[0]\n'
         '                        if _w0 is not None:\n'
         '                            dev, _intended = _match_departure(\n'
         '                                int(_lid), float(_w0) + float(time))\n'
         '                    except Exception:\n'
         '                        dev, _intended = None, None\n',
         '                dev = None\n'
         '                _intended = None\n'
         '                _match_mode = None\n'
         '                _match_conf = 0.0\n'
         '                _match_win = None\n'
         '                if _PT_FIRST_SEEN.get(_vid, 1e9) > WARMUP_GRACE_S:\n'
         '                    try:\n'
         '                        _w0 = _SCHED_WALL_START[0]\n'
         '                        if _w0 is not None:\n'
         '                            _match_win = _sched_match_window_s(int(_lid))\n'
         '                            dev, _intended, _match_conf, _match_mode = _match_departure(\n'
         '                                int(_lid), float(_w0) + float(time))\n'
         '                    except Exception:\n'
         '                        dev, _intended = None, None\n'
         '                        _match_mode = None\n'
         '                        _match_conf = 0.0\n',
         'site1 match')

e = sub1(e,
         '                    _intended = _last + (_H / _s_eff)\n'
         '                    dev = float(time) - _intended\n',
         '                    _intended = _last + (_H / _s_eff)\n'
         '                    dev = float(time) - _intended\n'
         "                    _match_mode = 'headway'\n",
         'site1 fallback')

e = sub1(e,
         '                    stats.add_schedule_dev(\n'
         '                        int(_lid), dev, veh_id=_vid,\n'
         '                        observed_time_s=float(time), intended_time_s=_intended,\n'
         '                        headway_s=_H)\n',
         '                    stats.add_schedule_dev(\n'
         '                        int(_lid), dev, veh_id=_vid,\n'
         '                        observed_time_s=float(time), intended_time_s=_intended,\n'
         '                        headway_s=_H, match_mode=_match_mode,\n'
         '                        match_confidence=_match_conf, match_window_s=_match_win,\n'
         '                        stop_offset_s=0.0)\n',
         'site1 add_schedule_dev')

# ── call site 2: injection / entry recorder ─────────────────────────
e = sub1(e,
         '        dev = None\n'
         '        _intended = None\n'
         '        if (_PT_FIRST_SEEN.get(vid, 1e9) > WARMUP_GRACE_S\n'
         '                and _w0 is not None):\n'
         '            try:\n'
         '                dev, _intended = _match_departure(\n'
         '                    lid, float(_w0) + float(now_s))\n'
         '            except Exception:\n'
         '                dev, _intended = None, None\n',
         '        dev = None\n'
         '        _intended = None\n'
         '        _match_mode = None\n'
         '        _match_conf = 0.0\n'
         '        _match_win = None\n'
         '        if (_PT_FIRST_SEEN.get(vid, 1e9) > WARMUP_GRACE_S\n'
         '                and _w0 is not None):\n'
         '            try:\n'
         '                _match_win = _sched_match_window_s(lid)\n'
         '                dev, _intended, _match_conf, _match_mode = _match_departure(\n'
         '                    lid, float(_w0) + float(now_s))\n'
         '            except Exception:\n'
         '                dev, _intended = None, None\n'
         '                _match_mode = None\n'
         '                _match_conf = 0.0\n',
         'site2 match')

e = sub1(e,
         '            _intended = last + (headway / scalar)\n'
         '            dev = float(now_s) - _intended\n',
         '            _intended = last + (headway / scalar)\n'
         '            dev = float(now_s) - _intended\n'
         "            _match_mode = 'headway'\n",
         'site2 fallback')

e = sub1(e,
         '            stats.add_schedule_dev(\n'
         '                lid, dev, veh_id=vid, observed_time_s=float(now_s),\n'
         '                intended_time_s=_intended, headway_s=headway)\n',
         '            stats.add_schedule_dev(\n'
         '                lid, dev, veh_id=vid, observed_time_s=float(now_s),\n'
         '                intended_time_s=_intended, headway_s=headway,\n'
         '                match_mode=_match_mode, match_confidence=_match_conf,\n'
         '                match_window_s=_match_win, stop_offset_s=0.0)\n',
         'site2 add_schedule_dev')

e = e.replace('ENGINE_BUILD = "2026-11-10T1800-lightsim-mp-holdplan"',
              'ENGINE_BUILD = "2026-11-10T1900-lightsim-mp-schedmatch"')

tmp = E + '.sched.tmp'
io.open(tmp, 'w', encoding='utf-8', newline='').write(e)
os.replace(tmp, E)

import py_compile
py_compile.compile(E, doraise=True)
print('engine.py patched + compiled')
for line in io.open(E, encoding='utf-8', errors='replace'):
    if line.startswith('ENGINE_BUILD'):
        print('stamp:', line.strip())
        break
