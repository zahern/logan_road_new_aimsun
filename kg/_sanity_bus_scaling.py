# =============================================================================
# _sanity_bus_scaling.py — offline sanity check for set_bus_headway_scalar
# =============================================================================
#
# Loads the REAL set_bus_headway_scalar + helper functions out of every batch
# runner copy (kg + logan x gui_new / bus_demand / signal_bus_demand), runs
# them against a faithful mock of the Aimsun PT-timetable API, and verifies:
#
#   A. Interval schedules: mean headway divided by scalar (x1.5 / x2 / x3)
#   B. No compounding across repeated scalar calls (base_state cache)
#   C. Interval restore back to original at scalar == 1.0
#   D. Fixed schedules: departure count scaled ~scalar x, window preserved
#   E. Only GKPublicLine (bus) objects are touched; car/truck untouched
#   F. "nothing scaled" warning fires when a schedule cannot be scaled
#   G. Mixed network (interval + fixed lines) scales both, counts correctly
#
# Usage:  python _sanity_bus_scaling.py
# Exit code 0 = all checks passed, 1 = at least one failure.
#
# No Aimsun required — the mock implements exactly the API surface the runner
# code uses (GKSystem/GKPublicLine/GKPublicLineTimeTable/Schedule/Departure/
# GKTimeDuration/QTime).

import ast
import contextlib
import io
import os
import sys

try:
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNERS = [
    os.path.join(REPO, "kg", "batch_runner_gui_new.py"),
    os.path.join(REPO, "kg", "batch_runner_gui_new_scaling.py"),
    os.path.join(REPO, "kg", "batch_runner_bus_demand.py"),
    os.path.join(REPO, "kg", "batch_runner_signal_bus_demand.py"),
    os.path.join(REPO, "logan_road_new", "batch_runner_gui_new.py"),
    os.path.join(REPO, "logan_road_new", "batch_runner_gui_new_scaling.py"),
    os.path.join(REPO, "logan_road_new", "batch_runner_bus_demand.py"),
    os.path.join(REPO, "logan_road_new", "batch_runner_signal_bus_demand.py"),
]

_FUNC_NAMES = {
    "_pt_duration_from_secs",
    "_pt_time_to_secs",
    "_pt_secs_to_time",
    "_is_interval_schedule",
    "_scale_one_schedule",
    "set_bus_headway_scalar",
}


# =============================================================================
# ── Mock Aimsun API (mirrors the SIP surface the runner uses) ────────────────
# =============================================================================

class MockGKTimeDuration:
    def __init__(self, h=0, m=0, s=0, ms=0):
        self._secs = h * 3600 + m * 60 + s
        self._ms = ms

    def toSeconds(self):
        return self._secs

    def isNull(self):
        return self._secs == 0

    def toQTime(self):
        return MockQTime(self._secs)

    def __repr__(self):
        return f"GKTimeDuration({self._secs}s)"


class MockQTime:
    def __init__(self, secs):
        self._secs = int(secs) % 86400

    def hour(self):
        return self._secs // 3600

    def minute(self):
        return (self._secs % 3600) // 60

    def second(self):
        return self._secs % 60

    def toSecondsOfDay(self):
        return self._secs

    def __repr__(self):
        return f"QTime({self.hour()}:{self.minute()}:{self.second()})"


class MockDeparture:
    """GKPublicLineTimeTableScheduleDeparture value object."""

    eInterval = 0
    eFixed = 1

    def __init__(self, mean=None, deptime=None):
        self._mean = mean
        self._deptime = deptime

    def getMeanTime(self):
        return self._mean

    def setMeanTime(self, m):
        self._mean = m

    def getDepartureTime(self):
        return self._deptime

    def setDepartureTime(self, t):
        self._deptime = t


class MockSchedule:
    """GKPublicLineTimeTableSchedule — departure_type: 0=eInterval, 1=eFixed."""

    eInterval = 0
    eFixed = 1

    def __init__(self, departure_type, departures):
        self._dtype = departure_type
        self._deps = list(departures)

    def getDepartureType(self):
        return self._dtype

    def getDepartureTimes(self):
        return list(self._deps)  # value-copy semantics, like the SIP QVector

    def setDepartureTime(self, pos, departure):
        self._deps[pos] = departure

    def removeDepartureTimes(self):
        self._deps = []

    def addDepartureTime(self, departure):
        self._deps.append(departure)

    def sortDepartureTimes(self):
        self._deps.sort(key=lambda d: d.getDepartureTime().toSecondsOfDay())


class MockTimeTable:
    """GKPublicLineTimeTable."""

    def __init__(self, schedules):
        self._schedules = list(schedules)

    def getSchedules(self):
        return list(self._schedules)


class MockLine:
    """GKPublicLine."""

    def __init__(self, timetables, name="line"):
        self._tts = list(timetables)
        self._name = name

    def getTimeTables(self):
        return list(self._tts)

    def __repr__(self):
        return f"GKPublicLine({self._name})"


class _Catalog:
    def __init__(self):
        self._by_type = {}

    def add(self, type_name, obj_id, obj):
        self._by_type.setdefault(type_name, {})[obj_id] = obj

    def getObjectsByType(self, type_name):
        return dict(self._by_type.get(type_name, {}))


class _Model:
    def __init__(self):
        self.catalog = _Catalog()
        self._types = {"GKPublicLine": "GKPublicLine"}

    def getType(self, name):
        return self._types.get(name, name)

    def getCatalog(self):
        return self.catalog


class MockGKSystem:
    _model = None

    @staticmethod
    def getSystem():
        return MockGKSystem

    @staticmethod
    def getActiveModel():
        return MockGKSystem._model


# =============================================================================
# ── Helpers: load real functions out of a runner file via AST ────────────────
# =============================================================================

def load_scaling_funcs(path):
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    ns = {
        "GKSystem": MockGKSystem,
        "GKTimeDuration": MockGKTimeDuration,
    }
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _FUNC_NAMES:
            code = compile(ast.Module([node], []), path, "exec")
            exec(code, ns)
    missing = _FUNC_NAMES - set(ns)
    if missing:
        raise RuntimeError(f"{path}: missing functions {sorted(missing)}")
    return ns


def make_dur(secs):
    h, rem = divmod(max(0, int(secs)), 3600)
    m, s = divmod(rem, 60)
    return MockGKTimeDuration(h, m, s)


def make_qtime(secs):
    return MockQTime(secs)


def build_interval_line(line_id, mean_secs, name="interval"):
    dep = MockDeparture(mean=make_dur(mean_secs))
    sch = MockSchedule(MockSchedule.eInterval, [dep])
    tt = MockTimeTable([sch])
    return line_id, MockLine([tt], name)


def build_fixed_line(line_id, times_secs, name="fixed"):
    deps = [MockDeparture(deptime=make_qtime(t)) for t in times_secs]
    sch = MockSchedule(MockSchedule.eFixed, deps)
    tt = MockTimeTable([sch])
    return line_id, MockLine([tt], name)


def install_model(lines, with_car=False):
    m = _Model()
    for lid, line in lines:
        m.catalog.add("GKPublicLine", lid, line)
    if with_car:
        m.catalog.add("GKVehicle", 9001, object())  # car/truck — must be untouched
    MockGKSystem._model = m
    return m


# =============================================================================
# ── Checks ───────────────────────────────────────────────────────────────────
# =============================================================================

def run_check(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
        return True
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        return False
    except Exception as e:
        print(f"  FAIL  {name}: unexpected {type(e).__name__}: {e}")
        return False


def capture_scale(func, scalar, base_state):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        n = func(scalar, base_state)
    return n, buf.getvalue()


def make_checks(func):
    checks = {}

    def check_A_interval_x2():
        install_model([build_interval_line(1, 600)])  # 10 min headway
        base = {}
        n, _ = capture_scale(func, 2.0, base)
        assert n == 1, f"expected 1 schedule scaled, got {n}"
        sch = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")[1].getTimeTables()[0].getSchedules()[0]
        mean = sch.getDepartureTimes()[0].getMeanTime()
        assert mean.toSeconds() == 300, f"x2 headway expected 300s, got {mean.toSeconds()}"

    def check_A_interval_x15():
        install_model([build_interval_line(1, 600)])
        base = {}
        n, _ = capture_scale(func, 1.5, base)
        assert n == 1
        sch = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")[1].getTimeTables()[0].getSchedules()[0]
        mean = sch.getDepartureTimes()[0].getMeanTime()
        assert mean.toSeconds() == 400, f"x1.5 headway expected 400s, got {mean.toSeconds()}"

    def check_A_interval_x3():
        install_model([build_interval_line(1, 600)])
        base = {}
        capture_scale(func, 3.0, base)
        sch = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")[1].getTimeTables()[0].getSchedules()[0]
        mean = sch.getDepartureTimes()[0].getMeanTime()
        assert mean.toSeconds() == 200, f"x3 headway expected 200s, got {mean.toSeconds()}"

    def check_B_no_compounding():
        install_model([build_interval_line(1, 600)])
        base = {}
        capture_scale(func, 2.0, base)   # -> 300s
        capture_scale(func, 2.0, base)   # must stay 300s (from original, not compounded)
        sch = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")[1].getTimeTables()[0].getSchedules()[0]
        mean = sch.getDepartureTimes()[0].getMeanTime()
        assert mean.toSeconds() == 300, f"compounded! expected 300s, got {mean.toSeconds()}"
        capture_scale(func, 3.0, base)   # -> 200s from original 600
        mean = sch.getDepartureTimes()[0].getMeanTime()
        assert mean.toSeconds() == 200, f"expected 200s after x3, got {mean.toSeconds()}"

    def check_C_restore_x1():
        install_model([build_interval_line(1, 600)])
        base = {}
        capture_scale(func, 3.0, base)
        n, _ = capture_scale(func, 1.0, base)
        assert n == 1, f"restore x1 should scale back, got n={n}"
        sch = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")[1].getTimeTables()[0].getSchedules()[0]
        mean = sch.getDepartureTimes()[0].getMeanTime()
        assert mean.toSeconds() == 600, f"restore expected 600s, got {mean.toSeconds()}"

    def check_D_fixed_x2():
        install_model([build_fixed_line(1, [0, 300, 600])])
        base = {}
        n, _ = capture_scale(func, 2.0, base)
        assert n == 1, f"expected 1 fixed schedule scaled, got {n}"
        sch = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")[1].getTimeTables()[0].getSchedules()[0]
        times = sorted(d.getDepartureTime().toSecondsOfDay() for d in sch.getDepartureTimes())
        assert len(times) == 6, f"x2 fixed expected 6 runs, got {len(times)}: {times}"
        assert times[0] == 0 and times[-1] == 600, f"window not preserved: {times}"
        # even spacing across 0..600
        gaps = {times[i + 1] - times[i] for i in range(len(times) - 1)}
        assert gaps == {120}, f"expected uniform 120s gaps, got {gaps}"

    def check_D_fixed_x3():
        install_model([build_fixed_line(1, [0, 300, 600])])
        base = {}
        capture_scale(func, 3.0, base)
        sch = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")[1].getTimeTables()[0].getSchedules()[0]
        times = sorted(d.getDepartureTime().toSecondsOfDay() for d in sch.getDepartureTimes())
        assert len(times) == 9, f"x3 fixed expected 9 runs, got {len(times)}: {times}"

    def check_D_fixed_x15():
        install_model([build_fixed_line(1, [0, 300, 600])])
        base = {}
        capture_scale(func, 1.5, base)
        sch = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")[1].getTimeTables()[0].getSchedules()[0]
        times = sorted(d.getDepartureTime().toSecondsOfDay() for d in sch.getDepartureTimes())
        assert len(times) == 4, f"x1.5 fixed expected 4 runs, got {len(times)}: {times}"

    def check_E_only_buses_touched():
        install_model([build_interval_line(1, 600)], with_car=True)
        base = {}
        capture_scale(func, 2.0, base)
        # a car/truck entry present in the catalog is never looked up or changed
        assert "GKVehicle" in MockGKSystem._model.catalog._by_type, "car entry missing from catalog"
        assert len(MockGKSystem._model.catalog._by_type["GKVehicle"]) == 1
        bus_lines = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")
        assert len(bus_lines) == 1, "only the bus line should be queried"

    def check_F_nothing_scaled_warning():
        install_model([build_fixed_line(1, [0])])  # fixed with a single run -> cannot scale
        base = {}
        n, out = capture_scale(func, 2.0, base)
        assert n == 0, f"expected 0 scaled, got {n}"
        assert "nothing scaled" in out.lower(), "expected 'nothing scaled' warning"

    def check_G_mixed_network():
        install_model([
            build_interval_line(1, 600),
            build_fixed_line(2, [0, 300, 600]),
        ])
        base = {}
        n, _ = capture_scale(func, 2.0, base)
        assert n == 2, f"expected 2 schedules scaled, got {n}"
        lines = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")
        s1 = lines[1].getTimeTables()[0].getSchedules()[0]
        s2 = lines[2].getTimeTables()[0].getSchedules()[0]
        mean = s1.getDepartureTimes()[0].getMeanTime().toSeconds()
        runs = len(s2.getDepartureTimes())
        assert mean == 300 and runs == 6, f"interval mean={mean}, fixed runs={runs}"

    def check_H1_interval_x1_noop_preserves_obj():
        # ISSUE 1: x1.0 must be a no-op AND must not rebuild the departure.
        # The old code did `type(deps[0])()` + setMeanTime, dropping every other
        # departure property and cutting bus service ~25% even at x1.0.
        install_model([build_interval_line(1, 600)])
        sch = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")[1] \
            .getTimeTables()[0].getSchedules()[0]
        dep0 = sch.getDepartureTimes()[0]
        dep0._extra_vehicle_ref = "BUS-42"  # property the old rebuild lost
        base = {}
        n, _ = capture_scale(func, 1.0, base)
        assert n == 0, f"x1.0 no-op expected 0 scaled, got {n}"
        cur = sch.getDepartureTimes()[0]
        assert cur is dep0, "x1.0 must NOT rebuild the departure object"
        assert getattr(cur, "_extra_vehicle_ref", None) == "BUS-42", \
            "extra departure property was lost"
        assert cur.getMeanTime().toSeconds() == 600, "headway must stay 600s"

    def check_H2_interval_scale_preserves_obj():
        install_model([build_interval_line(1, 600)])
        sch = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")[1] \
            .getTimeTables()[0].getSchedules()[0]
        dep0 = sch.getDepartureTimes()[0]
        dep0._extra_vehicle_ref = "BUS-42"
        base = {}
        n, _ = capture_scale(func, 3.0, base)
        assert n == 1
        cur = sch.getDepartureTimes()[0]
        assert cur is dep0, "scaling must mutate in place, not rebuild"
        assert getattr(cur, "_extra_vehicle_ref", None) == "BUS-42", \
            "extra property lost by rebuild"
        assert cur.getMeanTime().toSeconds() == 200

    def check_H3_interval_restore_preserves_obj():
        install_model([build_interval_line(1, 600)])
        sch = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")[1] \
            .getTimeTables()[0].getSchedules()[0]
        dep0 = sch.getDepartureTimes()[0]
        dep0._extra_vehicle_ref = "BUS-42"
        base = {}
        capture_scale(func, 3.0, base)
        n, _ = capture_scale(func, 1.0, base)
        assert n == 1, f"restore should scale back, got n={n}"
        cur = sch.getDepartureTimes()[0]
        assert cur is dep0, "restore must mutate in place, not rebuild"
        assert getattr(cur, "_extra_vehicle_ref", None) == "BUS-42", \
            "extra property lost during restore"
        assert cur.getMeanTime().toSeconds() == 600

    def check_I_fixed_restore_x1():
        # ISSUE 2: after an upscale, x1.0 must restore the ORIGINAL run list
        # instead of silently keeping the upscaled list in memory.
        install_model([build_fixed_line(1, [0, 300, 600])])
        base = {}
        capture_scale(func, 3.0, base)
        n, _ = capture_scale(func, 1.0, base)
        assert n == 1, f"fixed restore should rewrite, got n={n}"
        sch = MockGKSystem._model.catalog.getObjectsByType("GKPublicLine")[1] \
            .getTimeTables()[0].getSchedules()[0]
        times = sorted(d.getDepartureTime().toSecondsOfDay()
                       for d in sch.getDepartureTimes())
        assert times == [0, 300, 600], \
            f"fixed restore expected [0,300,600], got {times}"
        # repeat x1.0 must be a clean no-op (never compounds)
        n2, _ = capture_scale(func, 1.0, base)
        assert n2 == 0, f"second x1.0 should be a no-op, got n={n2}"

    def check_J_readback_ok():
        # The verification pass must report success when the stored mean time
        # equals base/scalar (i.e. the mock behaves like the real API should).
        install_model([build_interval_line(1, 600)])
        base = {}
        n, out = capture_scale(func, 2.0, base)
        assert n == 1
        assert "Readback OK" in out, f"expected 'Readback OK', got: {out!r}"

    def check_J_readback_catches_inverted_sign():
        # Simulate a deployed copy that writes base*scalar instead of
        # base/scalar (exactly the friend's observed bug: x1.5 -> flow/base1.5):
        # make MockDeparture.setMeanTime store DOUBLE the value it receives, so
        # the stored headway is base*scalar while the code "thinks" it wrote
        # base/scalar.  The verification pass must flag the mismatch loudly.
        install_model([build_interval_line(1, 600)])
        orig = MockDeparture.setMeanTime

        def evil(self, m):
            return orig(self, MockGKTimeDuration(0, 0, int(m.toSeconds()) * 2))

        MockDeparture.setMeanTime = evil
        try:
            base = {}
            n, out = capture_scale(func, 2.0, base)
            assert n == 1
            assert "READBACK MISMATCH" in out, \
                f"expected READBACK MISMATCH, got: {out!r}"
        finally:
            MockDeparture.setMeanTime = orig

    checks["A1 interval x2 halves headway"] = check_A_interval_x2
    checks["A2 interval x1.5 = 400s"] = check_A_interval_x15
    checks["A3 interval x3 = 200s"] = check_A_interval_x3
    checks["B  repeated calls never compound"] = check_B_no_compounding
    checks["C  x1.0 restores interval"] = check_C_restore_x1
    checks["D1 fixed x2 = 6 uniform runs"] = check_D_fixed_x2
    checks["D2 fixed x3 = 9 runs"] = check_D_fixed_x3
    checks["D3 fixed x1.5 = 4 runs"] = check_D_fixed_x15
    checks["E  only GKPublicLine (buses) touched"] = check_E_only_buses_touched
    checks["F  nothing-scaled warning fires"] = check_F_nothing_scaled_warning
    checks["G  mixed network scales both"] = check_G_mixed_network
    checks["H1 interval x1.0 no-op preserves departure object"] = check_H1_interval_x1_noop_preserves_obj
    checks["H2 interval scaling mutates in place (no rebuild)"] = check_H2_interval_scale_preserves_obj
    checks["H3 interval x1.0 restore mutates in place"] = check_H3_interval_restore_preserves_obj
    checks["I  fixed x1.0 restores original run list"] = check_I_fixed_restore_x1
    checks["J1 readback reports OK on correct store"] = check_J_readback_ok
    checks["J2 readback catches inverted-sign store"] = check_J_readback_catches_inverted_sign
    return checks


# =============================================================================
# ── Main ─────────────────────────────────────────────────────────────────────
# =============================================================================

def main():
    overall = True
    for path in RUNNERS:
        print(f"\n=== {os.path.relpath(path, REPO)} ===")
        try:
            funcs = load_scaling_funcs(path)
        except Exception as e:
            print(f"  FAIL  could not load functions: {e}")
            overall = False
            continue
        ok_all = True
        for name, check in make_checks(funcs["set_bus_headway_scalar"]).items():
            if not run_check(name, check):
                ok_all = False
        if ok_all:
            print("  -> all checks passed")
        else:
            overall = False

    print("\n" + "=" * 60)
    print("OVERALL:", "ALL PASS" if overall else "FAILURES PRESENT")
    print("=" * 60)
    return overall


if __name__ == "__main__":
    # Intentionally no sys.exit(): Aimsun's embedded Python reports any
    # SystemExit as a "Python Error", even for a clean 0 exit code.  The
    # boolean return is only meaningful when run from a real shell.
    main()