"""
check_car_count.py -- 1-run CAR-COUNT sanity check (NOT the full champion search).

Runs ONE NO_TSP replication on the currently-open corridor and prints the
car-counting diagnostics + a clear PASS/FAIL, so you can confirm cars are being
counted correctly (Option B network-wide fix) BEFORE committing to a full sweep.

RUN inside Aimsun, model open:   check_car_count.py

This version is SELF-DIAGNOSING: it prints a marker at every step and dumps a
full traceback on ANY error, so if it stops we can see exactly where. Nothing
should ever fail silently.
"""
import os as _os
import sys as _sys
import traceback as _tb
import importlib.util as _ilu

# Plain print() so we get output even if batch_runner never loads.
def _say(msg):
    try:
        print("[CARCHECK] " + str(msg))
    except Exception:
        pass

_say("starting check_car_count.py")


def _load_champion_search():
    try:
        here = _os.path.dirname(_os.path.abspath(__file__))
    except NameError:
        here = _os.path.abspath(_os.getcwd())
    _say("script folder = " + here)
    if here not in _sys.path:
        _sys.path.insert(0, here)
    cs_path = _os.path.join(here, "champion_search.py")
    if not _os.path.isfile(cs_path):
        raise RuntimeError("champion_search.py NOT found next to this file (looked in "
                           + here + "). Unzip the bundle so both files share a folder.")
    _say("loading champion_search.py (this also loads batch_runner + detects corridor)")
    spec = _ilu.spec_from_file_location("champion_search", cs_path)
    mod = _ilu.module_from_spec(spec)
    _sys.modules["champion_search"] = mod
    spec.loader.exec_module(mod)
    _say("champion_search loaded; corridor = " + str(getattr(mod, "CORRIDOR", "?")))
    return mod


def _run():
    cs = _load_champion_search()
    br = cs._br
    log = br.log
    CORRIDOR = cs.CORRIDOR
    CONTROLLER_PATH = br.CONTROLLER_PATH
    RUN_CONFIG_PATH = br.RUN_CONFIG_PATH
    PROJECT_DIR = br.PROJECT_DIR
    RESULTS_CSV = _os.path.join(cs._ROOT, "car_count_check_" + CORRIDOR + ".csv")

    _say("corridor=" + CORRIDOR + " | running 1x NO_TSP seed 300 demand 1.0x")
    try:
        if _os.path.exists(RESULTS_CSV):
            _os.remove(RESULTS_CSV)
    except Exception:
        pass
    try:
        br._set_logging(CONTROLLER_PATH, enabled=False)
    except Exception as e:
        _say("WARN _set_logging: " + repr(e))
    try:
        cs._disable_batch_plotting(CONTROLLER_PATH)
    except Exception as e:
        _say("WARN disable_plotting: " + repr(e))

    _say("patching controller to NO_TSP baseline")
    try:
        br.set_control_mode("NORMAL", CONTROLLER_PATH, None)
        br.set_coordinated(CONTROLLER_PATH, False)
        br.set_coordination_algo(CONTROLLER_PATH, "KALMAN")
        br.set_reward_weights(CONTROLLER_PATH, None)
    except Exception as e:
        _say("WARN patch: " + repr(e))
    try:
        cs._set_controller_bxt_seeds(CONTROLLER_PATH, [], [], cs.BXT_TRAIN_EPSILON)
    except Exception as e:
        _say("WARN bxt_seeds: " + repr(e))
    try:
        br.set_demand_scalar(1.0, {})
    except Exception as e:
        _say("WARN demand_scalar: " + repr(e))

    _say("starting the replication (this runs the simulation)")
    rep = br.get_first_replication()
    m = cs._run_and_collect(
        br, rep, "NO_TSP", "NORMAL", 300, 1.0, False, "KALMAN",
        False, None, "ADAPTIVE_KALMAN",
        CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR, RESULTS_CSV, log)

    try:
        br._set_logging(CONTROLLER_PATH, enabled=True)
    except Exception:
        pass

    _say("replication done; reading metrics")
    if not m:
        _say("RESULT: FAIL -- no metrics were collected (run did not complete).")
        return

    def gv(k):
        try:
            return float(m.get(k))
        except Exception:
            return None

    ncars = gv('stats_N_DistinctCars')
    nbus = gv('stats_N_DistinctBuses')
    carpax = gv('stats_CarPaxEquivPassages')
    avgcar = gv('stats_AvgCarPassDelay_s')
    avgbus = gv('stats_AvgBusPassDelay_s')
    obj = gv('stats_Objective_PaxPerDelayHr')

    _say("-" * 60)
    _say("N_DistinctCars      = " + str(ncars) + "   (want: THOUSANDS)")
    _say("N_DistinctBuses     = " + str(nbus))
    _say("CarPaxEquivPassages = " + str(carpax) + "   (want: thousands)")
    _say("AvgCarPassDelay_s   = " + str(avgcar) + "   (want: tens of s, NOT ~75000)")
    _say("AvgBusPassDelay_s   = " + str(avgbus))
    _say("Objective           = " + str(obj))
    _say("-" * 60)

    ok_cars = (ncars is not None and ncars >= 500)
    ok_avg = (avgcar is not None and 0.0 < avgcar < 600.0)
    if ok_cars and ok_avg:
        _say("RESULT: PASS -- cars counted correctly; safe to run the full sweep.")
    else:
        _say("RESULT: FAIL -- car counting still off:")
        if not ok_cars:
            _say("   N_DistinctCars=" + str(ncars) + " (<500; expected thousands)")
        if not ok_avg:
            _say("   AvgCarPassDelay_s=" + str(avgcar) + " (expected tens of s, not >600)")
        _say("   -> copy this whole [CARCHECK] block back to Zeke.")


# Call unconditionally (do NOT rely on __name__ == '__main__') and dump any error.
try:
    _run()
    _say("finished.")
except Exception:
    _say("FAILED with an exception -- traceback below:")
    _tb.print_exc()
    try:
        _say("traceback (string): " + _tb.format_exc())
    except Exception:
        pass
