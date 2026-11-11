"""probe_det.py -- two root causes behind the GE result.

1. REPRODUCIBILITY. If plain SUMO (no traci) reproduces exactly at a fixed seed,
   then any drift is introduced by the harness. If it does not, every A/B pair in
   this project carries that noise.

2. BUS CLASS. _bus_ge only fires for vehicles whose getVehicleClass() == "bus".
   The bench counts buses from the tripinfo vType string, so the two can disagree.
   This prints the classes actually on the network and whether any vehicle's
   vType id looks like a bus.

Usage:
  python probe_det.py --sumocfg .../kg.sumocfg --seed 0 --end 1200 --period 60
"""
import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET


def total_loss(path):
    if not os.path.exists(path):
        return None, 0
    tot, n = 0.0, 0
    for tr in ET.parse(path).getroot().findall("tripinfo"):
        tot += float(tr.get("timeLoss", 0.0) or 0.0)
        n += 1
    return tot, n


def pure_run(sumo, cfg, seed, end, out):
    cmd = [sumo, "-c", cfg, "--seed", str(seed), "--step-length", "1.0",
           "--no-step-log", "true", "--no-warnings", "true", "--end", str(end),
           "--tripinfo-output", out,
           "--tripinfo-output.write-unfinished", "true"]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    return total_loss(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--end", type=float, default=1200.0)
    ap.add_argument("--period", type=float, default=60.0)
    a = ap.parse_args()

    sumo = os.path.join(os.environ.get("SUMO_HOME", ""), "bin", "sumo.exe")
    if not os.path.exists(sumo):
        sumo = os.path.join(os.environ.get("SUMO_HOME", ""), "bin", "sumo")

    print("== 1. plain SUMO, no traci, same seed twice ==", flush=True)
    a1 = pure_run(sumo, os.path.abspath(a.sumocfg), a.seed, a.end,
                  os.path.abspath("tripinfo_det_A.xml"))
    a2 = pure_run(sumo, os.path.abspath(a.sumocfg), a.seed, a.end,
                  os.path.abspath("tripinfo_det_B.xml"))
    print("  A: trips=%d loss=%.3f" % (a1[1], a1[0] or -1), flush=True)
    print("  B: trips=%d loss=%.3f" % (a2[1], a2[0] or -1), flush=True)
    exact = a1[1] == a2[1] and a1[0] is not None and a2[0] is not None \
        and abs(a1[0] - a2[0]) < 1e-6
    print("  plain SUMO reproduces exactly: %s (delta %.3f s)"
          % (exact, (a2[0] or 0) - (a1[0] or 0)), flush=True)

    print("\n== 2. what classes are actually running ==", flush=True)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from plan_select_env import PlanSelectPaxParallelEnv
    env = PlanSelectPaxParallelEnv(os.path.abspath(a.sumocfg), seed=a.seed,
                                   max_steps=float(a.end),
                                   period_s=float(a.period),
                                   plans=["commissioned"], bus_priority=False)
    env.reset()
    conn = env.conn
    classes = {}
    bus_like = 0
    bus_like_served = 0
    lib = env.libs[env.agents[0]]
    served_lanes = set()
    for gi in lib.green_idx:
        served_lanes |= lib.phase_lanes.get(gi, set())
    served_counts = {}
    for t in range(int(a.end)):
        conn.simulationStep()
        if t % 20 == 0:
            for v in conn.vehicle.getIDList():
                try:
                    vt = conn.vehicle.getTypeID(v)
                    cls = conn.vehicle.getVehicleClass(v)
                except Exception:
                    continue
                classes[cls] = classes.get(cls, 0) + 1
                if "bus" in str(vt).lower():
                    bus_like += 1
    for ln in served_lanes:
        try:
            served_counts[ln] = len(conn.lane.getLastStepVehicleIDs(ln))
        except Exception:
            served_counts[ln] = -1
    env.close()

    print("  classes seen (sampled): %s" % classes, flush=True)
    print("  samples whose vType id contains 'bus': %d" % bus_like, flush=True)
    print("  junction %s served lanes and their last-step vehicle counts: %s"
          % (lib.id, served_counts), flush=True)


if __name__ == "__main__":
    main()
