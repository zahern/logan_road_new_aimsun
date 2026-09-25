#!/usr/bin/env python3
"""test_sched_timetable.py -- offline logic test for the timetable loader.

Stubs PyANGKernel (GKPublicLine timetables/schedules/departures) + the AKI
line enumeration, then checks headway extraction. The SWIG method NAMES are
doc-sourced (unverifiable here); everything downstream of them is verified.
"""
import sys
import types

sys.path.insert(0, "shared_tsp_engine")
import engine as _eng


class _Dur:
    def __init__(self, s):
        self._s = s

    def getTimeInSeconds(self):
        return self._s


class _Dep:
    def __init__(self, fixed=None, mean=None):
        self._fixed = fixed
        self._mean = mean

    def getDepartureTime(self):
        return _Dur(self._fixed)

    def getMeanTime(self):
        return _Dur(self._mean)


class _Sched:
    def __init__(self, start, dtype, deps):
        self._start = start
        self._dtype = dtype
        self._deps = deps

    def getTime(self):
        return _Dur(self._start)

    def getDepartureType(self):
        return self._dtype

    def getDepartureTimes(self):
        return list(self._deps)


class _TT:
    def __init__(self, scheds):
        self._scheds = scheds

    def getSchedules(self):
        return list(self._scheds)


class _Line:
    def __init__(self, tts):
        self._tts = tts

    def getTimeTables(self):
        return list(self._tts)


# line 101: fixed departures 7:00,7:10,7:20,7:50 (+ off-window 12:00, which
# the upper-median convention counts -- same convention as the CSV loader)
# line 102: interval, mean 900 s
_LINES = {
    101: _Line([_TT([_Sched(6 * 3600, "eFixed",
                            [_Dep(fixed=t) for t in
                             (25200, 25800, 26400, 28200, 43200)])])]),
    102: _Line([_TT([_Sched(6 * 3600, "eInterval", [_Dep(mean=900)])])]),
    103: _Line([]),  # no timetables -> CSV/skip
}


class _Catalog:
    def find(self, lid):
        return _LINES.get(int(lid))


class _Model:
    def getCatalog(self):
        return _Catalog()


class _GKS:
    @staticmethod
    def getSystem():
        return _GKS()

    def getActiveModel(self):
        return _Model()  # catalog works; no scenario -> wall-start unknown


_pkg = types.ModuleType("PyANGKernel")
_pkg.GKSystem = _GKS
sys.modules["PyANGKernel"] = _pkg

_eng.AKIPTGetNumberLines = lambda: 3
_eng.AKIPTGetIdLine = lambda i: [101, 102, 103][i]
_eng._SCHED_SPACING.clear()
_eng._SCHED_LOADED[0] = False

fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)


# _gkt_seconds unit checks
check("dur accessor", _eng._gkt_seconds(_Dur(600)) == 600.0)
check("plain number", _eng._gkt_seconds(450) == 450.0)
check("none -> None", _eng._gkt_seconds(None) is None)
check("zero -> None", _eng._gkt_seconds(0) is None)


class _HMS:
    def getHours(self):
        return 1

    def getMinutes(self):
        return 30

    def getSeconds(self):
        return 0.0


check("h/m/s parts", _eng._gkt_seconds(_HMS()) == 5400.0)

n, ni, nf = _eng._sched_spacing_load_timetable()
check("two lines loaded", n == 2, f"n={n}")
check("fixed upper-median gap 1800", abs(_eng._SCHED_SPACING.get(101, -1) - 1800.0) < 1e-9,
      f"H={_eng._SCHED_SPACING.get(101)}")
check("interval mean 900", abs(_eng._SCHED_SPACING.get(102, -1) - 900.0) < 1e-9,
      f"H={_eng._SCHED_SPACING.get(102)}")
check("line without tt skipped", 103 not in _eng._SCHED_SPACING)
check("counts", (ni, nf) == (1, 1), f"({ni},{nf})")

# per-bus departure matching: observed 07:11 vs departures
# 07:00/07:10/07:20/07:50/12:00 -> nearest is 07:10 => dev +60 s (late)
_eng._SCHED_DEPARTURES[101] = [25200.0, 25800.0, 26400.0, 28200.0, 43200.0]
check("late match +60",
      abs(_eng._match_departure_dev(101, 25860.0) - 60.0) < 1e-9,
      f"{_eng._match_departure_dev(101, 25860.0)}")
# observed 07:09:30 -> nearest 07:10 => dev -30 s (early)
check("early match -30",
      abs(_eng._match_departure_dev(101, 25770.0) + 30.0) < 1e-9,
      f"{_eng._match_departure_dev(101, 25770.0)}")
# unknown line -> None (headway fallback)
check("unknown line -> None",
      _eng._match_departure_dev(999, 25860.0) is None)

print("ALL OK" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
