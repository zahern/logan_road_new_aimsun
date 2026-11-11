"""Port the windowed schedule match to the SUMO engine copies.

Run from the project root:  python _patch_sumo_sched.py
"""
import glob
import io
import os
import re
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ENGINES = [
    (r"Z:\tsp\sumo_hpc\shared_tsp_engine\engine.py",
     '2026-11-10T2300-sumo-lightsim-mp-schedmatch'),
    (r"_sumo_port\shared_tsp_engine\engine.py",
     '2026-11-10T2300-sumo-schedmatch'),
]

SPM_CANDIDATES = [
    r"Z:\tsp\sumo_hpc\shared_tsp_engine\Simulation_Stats.py",
    r"Z:\tsp\sumo_hpc\kg\Simulation_Stats.py",
    r"_sumo_port\shared_tsp_engine\Simulation_Stats.py",
]

OLD_MATCH = (
    'def _match_departure_dev(line_id, observed_wall_s):\n'
    '    """Per-bus schedule deviation from the timetable: observed wall entry\n'
    '    minus the nearest scheduled initial departure for the line (early\n'
    '    negative, late positive). Returns None when the line has no fixed\n'
    '    departures (interval lines, unknown wall-start) so callers fall back\n'
    '    to the headway method. Never raises."""\n'
    '    try:\n'
    '        _deps = _SCHED_DEPARTURES.get(int(line_id))\n'
    '        if not _deps:\n'
    '            return None\n'
    '        _obs = float(observed_wall_s)\n'
    '        _best_d = None\n'
    '        for _t in _deps:\n'
    '            try:\n'
    '                _d = _obs - float(_t)\n'
    '            except Exception:\n'
    '                continue\n'
    '            if _best_d is None or abs(_d) < abs(_best_d):\n'
    '                _best_d = _d\n'
    '        return _best_d\n'
    '    except Exception:\n'
    '        return None\n'
)

NEW_MATCH = (
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
    'def _match_departure_dev(line_id, observed_wall_s, stop_offset_s=0.0):\n'
    '    """Attribute one bus observation to a scheduled departure of ITS line.\n'
    '\n'
    '    Returns (deviation_s, intended_s, confidence, mode):\n'
    "      'window'    matched inside the line's half-headway window; confidence is\n"
    '                  1 - |dev|/window.\n'
    "      'unmatched' the nearest departure is further than any bus on that line\n"
    '                  could plausibly be; the deviation is still returned so the\n'
    '                  caller penalises it (at the clamp), but it is counted as\n'
    '                  unattributed instead of being reported as lateness.\n'
    '      None        the line has no timetable; caller uses the headway method.\n'
    '\n'
    '    stop_offset_s shifts the departure to the scheduled time at a downstream\n'
    '    stop, so the same window works per stop rather than only at line entry.\n'
    '\n'
    '    2026-11-10: ported from the Aimsun twin. The unbounded nearest departure\n'
    '    produced mean |dev| 877 s on a corridor whose headway makes that\n'
    '    physically impossible -- the match was landing about half a headway away\n'
    '    and reporting the gap as lateness.\n'
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


def sub1(txt, old, new, tag):
    n = txt.count(old)
    print('  %-26s anchor=%d' % (tag, n))
    if n != 1:
        raise SystemExit('ABORT %s (anchor count %d)' % (tag, n))
    return txt.replace(old, new)


def patch_engine(path, stamp):
    print('\n== %s' % path)
    e = io.open(path, encoding='utf-8', errors='replace').read()
    if 'SCHED_MATCH_MIN_WINDOW_S' in e and 'match_confidence' in e:
        print('  already patched')
        return
    shutil.copy2(path, path + '.pre_schedmatch.bak')

    e = sub1(e, '_SCHED_WALL_START = [None]\n',
             '_SCHED_WALL_START = [None]\n'
             '_SCHED_MATCH_MIN_WINDOW_S = 120.0   # never narrower than this (s)\n'
             '_SCHED_MATCH_MAX_WINDOW_S = 900.0   # never wider than this (s)\n',
             'constants')
    e = sub1(e, OLD_MATCH, NEW_MATCH, 'match_departure_dev')

    # site 1 -----------------------------------------------------------------
    e = sub1(e,
             '                dev = None\n'
             '                _intended = None\n'
             '                if _PT_FIRST_SEEN.get(_vid, 1e9) > WARMUP_GRACE_S:\n'
             '                    try:\n'
             '                        _w0 = _SCHED_WALL_START[0]\n'
             '                        if _w0 is not None:\n'
             '                            dev = _match_departure_dev(\n'
             '                                int(_lid), float(_w0) + float(time))\n'
             '                    except Exception:\n'
             '                        dev = None\n',
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
             '                            dev, _intended, _match_conf, _match_mode = _match_departure_dev(\n'
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
             '                        observed_time_s=float(time), intended_time_s=_intended)\n',
             '                    stats.add_schedule_dev(\n'
             '                        int(_lid), dev, veh_id=_vid,\n'
             '                        observed_time_s=float(time), intended_time_s=_intended,\n'
             '                        headway_s=_H, match_mode=_match_mode,\n'
             '                        match_confidence=_match_conf, match_window_s=_match_win,\n'
             '                        stop_offset_s=0.0)\n',
             'site1 add_schedule_dev')

    # site 2 -----------------------------------------------------------------
    e = sub1(e,
             '        dev = None\n'
             '        _intended = None\n'
             '        if (_PT_FIRST_SEEN.get(vid, 1e9) > WARMUP_GRACE_S\n'
             '                and _w0 is not None):\n'
             '            try:\n'
             '                dev = _match_departure_dev(\n'
             '                    lid, float(_w0) + float(now_s))\n'
             '            except Exception:\n'
             '                dev = None\n',
             '        dev = None\n'
             '        _intended = None\n'
             '        _match_mode = None\n'
             '        _match_conf = 0.0\n'
             '        _match_win = None\n'
             '        if (_PT_FIRST_SEEN.get(vid, 1e9) > WARMUP_GRACE_S\n'
             '                and _w0 is not None):\n'
             '            try:\n'
             '                _match_win = _sched_match_window_s(lid)\n'
             '                dev, _intended, _match_conf, _match_mode = _match_departure_dev(\n'
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
             '                intended_time_s=_intended)\n',
             '            stats.add_schedule_dev(\n'
             '                lid, dev, veh_id=vid, observed_time_s=float(now_s),\n'
             '                intended_time_s=_intended, headway_s=headway,\n'
             '                match_mode=_match_mode, match_confidence=_match_conf,\n'
             '                match_window_s=_match_win, stop_offset_s=0.0)\n',
             'site2 add_schedule_dev')

    e = re.sub(r'^ENGINE_BUILD = ".*"$',
               'ENGINE_BUILD = "%s"' % stamp, e, count=1, flags=re.M)

    tmp = path + '.sched.tmp'
    io.open(tmp, 'w', encoding='utf-8', newline='').write(e)
    os.replace(tmp, path)
    import py_compile
    py_compile.compile(path, doraise=True)
    print('  patched + compiled')


for path, stamp in ENGINES:
    if not os.path.exists(path):
        print('missing', path)
        continue
    patch_engine(path, stamp)

print('\n== SUMO Simulation_Stats candidates ==')
found = [p for p in SPM_CANDIDATES if os.path.exists(p)]
print('  existing:', found or 'none')
for p in found:
    s = io.open(p, encoding='utf-8', errors='replace').read()
    have = 'match_confidence' in s
    print('  %-58s match_confidence=%s' % (p, have))
