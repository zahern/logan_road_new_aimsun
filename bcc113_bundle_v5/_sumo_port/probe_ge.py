"""probe_ge.py -- two questions the GE bench cannot answer on its own.

1. REPRODUCIBILITY. Two identical runs at the same seed must produce the same
   result (AGENTS RULE 3). If they do not, an on/off pair cannot attribute a
   difference to the overlay.

2. BUS VISIBILITY. _bus_ge only extends when a bus is on a served lane AND the
   phase has <= ge_detect_s left. Zero triggers can mean "no bus was ever on a
   served lane" or "buses were there but never inside the window". This counts
   both, and buckets the remaining-green seen while a bus was present.

Read-only: it scans the same traci state _bus_ge reads and never changes a phase.

Usage:
  python probe_ge.py --sumocfg .../kg.sumocfg --seed 0 --end 1200 --period 60
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan_select_env import PlanSelectPaxParallelEnv   # noqa: E402


def _served(conn, lib, state):
    out = set()
    for sig, ch in enumerate(state):
        if ch in ("G", "g") and sig < len(lib.links) and lib.links[sig]:
            out.add(lib.links[sig][0][0])
    return out


def run_once(cfg, seed, end, period, tag, instrument=False):
    tip = os.path.abspath("tripinfo_geprobe_%s_s%d.xml" % (tag, seed))
    if os.path.exists(tip):
        os.remove(tip)
    env = PlanSelectPaxParallelEnv(
        cfg, seed=seed, max_steps=float(end), period_s=float(period),
        plans=["commissioned"], bus_priority=False,
        sumo_args=["--tripinfo-output", tip,
                   "--tripinfo-output.write-unfinished", "true"])
    env.reset()
    conn = env.conn
    st = {"ticks_with_bus": 0, "min_rem": 1e9, "buckets": {"<=6": 0, "6-15": 0,
                                                          "15-30": 0, ">30": 0},
          "ticks": 0}
    n = max(1, int(round(period)))
    while env._sim_t < end:
        for _ in range(n):
            if instrument:
                now = conn.simulation.getTime()
                for lib in env.libs.values():
                    try:
                        state = conn.trafficlight.getRedYellowGreenState(lib.id)
                        rem = conn.trafficlight.getNextSwitch(lib.id) - now
                    except Exception:
                        continue
                    served = _served(conn, lib, state)
                    seen = False
                    for ln in served:
                        try:
                            if any(conn.vehicle.getVehicleClass(v) == "bus"
                                   for v in conn.lane.getLastStepVehicleIDs(ln)):
                                seen = True
                                break
                        except Exception:
                            pass
                    if seen:
                        st["ticks_with_bus"] += 1
                        st["min_rem"] = min(st["min_rem"], float(rem))
                        if rem <= 6:
                            st["buckets"]["<=6"] += 1
                        elif rem <= 15:
                            st["buckets"]["6-15"] += 1
                        elif rem <= 30:
                            st["buckets"]["15-30"] += 1
                        else:
                            st["buckets"][">30"] += 1
                st["ticks"] += 1
            conn.simulationStep()
            env._sim_t += 1.0
    env.close()

    total_loss = 0.0
    trips = 0
    if os.path.exists(tip):
        for tr in ET.parse(tip).getroot().findall("tripinfo"):
            total_loss += float(tr.get("timeLoss", 0.0) or 0.0)
            trips += 1
    return {"trips": trips, "total_time_loss": round(total_loss, 3),
            "stats": st}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--end", type=float, default=1200.0)
    ap.add_argument("--period", type=float, default=60.0)
    a = ap.parse_args()

    a1 = run_once(os.path.abspath(a.sumocfg), a.seed, a.end, a.period, "A")
    b1 = run_once(os.path.abspath(a.sumocfg), a.seed, a.end, a.period, "B",
                  instrument=True)

    print("[probe] run A: trips=%d total_time_loss=%.3f"
          % (a1["trips"], a1["total_time_loss"]))
    print("[probe] run B: trips=%d total_time_loss=%.3f"
          % (b1["trips"], b1["total_time_loss"]))
    same = (a1["trips"] == b1["trips"]
            and abs(a1["total_time_loss"] - b1["total_time_loss"]) < 1e-6)
    print("[probe] same seed reproduces exactly: %s  (delta loss %.3f s)"
          % (same, b1["total_time_loss"] - a1["total_time_loss"]))

    st = b1["stats"]
    print("[probe] ticks scanned=%d  ticks with a bus on a served lane=%d"
          % (st["ticks"], st["ticks_with_bus"]))
    print("[probe] remaining-green buckets while a bus was present: %s"
          % st["buckets"])
    if st["ticks_with_bus"]:
        print("[probe] min remaining green seen with a bus: %.1fs "
               "(GE window is 6.0s)" % st["min_rem"])
    else:
        print("[probe] no bus was EVER on a served lane -> the window is not "
               "the problem, the bus visibility is")


if __name__ == "__main__":
    main()
