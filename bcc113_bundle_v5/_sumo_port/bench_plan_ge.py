"""bench_plan_ge.py -- does the Layer-2 pax bus-priority green extension help?

Runs the COMMISSIONED plan (no learning: action 0 every period) twice per seed:

    overlay off : pure commissioned plan
    overlay on  : same plan + _bus_ge() (bus-only, bounded by ge_max_s)

Same scenario, seed, demand and horizon in both runs, so each pair is
like-for-like (AGENTS RULE 3). Metrics come from SUMO tripinfo, pax-weighted the
way the project scores:

    bus_delay_hrs = sum(timeLoss * BusOcc) / 3600      (bus passengers)
    car_delay_hrs = sum(timeLoss * CarOcc) / 3600
    obj           = pax_srv / total_delay_hrs           (higher is better)

plus the overlay's own audit (fires, green seconds borrowed, junctions hit), so
a null result can be attributed instead of guessed.

Usage:
  python bench_plan_ge.py --sumocfg .../kg.sumocfg --seeds 0,1,2 --end 1200 \
      --csv bench_plan_ge.csv
"""
import argparse
import csv
import os
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan_select_env import PlanSelectPaxParallelEnv   # noqa: E402

BUS_OCC = 40.0
CAR_OCC = 1.2


def _is_bus(vtype):
    return "bus" in str(vtype).lower()


def run_one(sumocfg, seed, end, period, bus_priority):
    tag = "on" if bus_priority else "off"
    tip = os.path.abspath("tripinfo_plange_%s_s%d.xml" % (tag, seed))
    stat = os.path.abspath("stats_plange_%s_s%d.xml" % (tag, seed))
    for f in (tip, stat):
        if os.path.exists(f):
            os.remove(f)
    env = PlanSelectPaxParallelEnv(
        os.path.abspath(sumocfg), seed=seed, max_steps=float(end),
        period_s=float(period), plans=["commissioned"],
        bus_priority=bool(bus_priority),
        sumo_args=["--tripinfo-output", tip,
                   "--tripinfo-output.write-unfinished", "true",
                   "--statistic-output", stat])
    env.reset()
    t0 = time.time()
    steps = 0
    while env.agents:
        env.step({a: 0 for a in env.agents})     # hold the commissioned plan
        steps += 1
    wall = time.time() - t0
    ge = env.ge_report()
    env.close()

    bus_d = car_d = 0.0
    bus_pax = car_pax = 0.0
    nb = nc = 0
    bus_loss = []
    if os.path.exists(tip):
        for tr in ET.parse(tip).getroot().findall("tripinfo"):
            loss = float(tr.get("timeLoss", 0.0) or 0.0)
            if _is_bus(tr.get("vType", "")):
                nb += 1
                bus_pax += BUS_OCC
                bus_d += loss * BUS_OCC / 3600.0
                bus_loss.append(loss)
            else:
                nc += 1
                car_pax += CAR_OCC
                car_d += loss * CAR_OCC / 3600.0
    tot_d = bus_d + car_d
    pax = bus_pax + car_pax
    obj = (pax / tot_d) if tot_d > 0 else 0.0

    loaded = inserted = waiting = tele = 0
    if os.path.exists(stat):
        root = ET.parse(stat).getroot()
        v = root.find("vehicles")
        if v is not None:
            loaded = int(v.get("loaded", 0) or 0)
            inserted = int(v.get("inserted", 0) or 0)
            waiting = int(v.get("waiting", 0) or 0)
        t = root.find("teleports")
        if t is not None:
            tele = int(t.get("total", 0) or 0)

    return {"overlay": tag, "seed": seed, "end": end, "period": period,
            "steps": steps, "bus_trips": nb, "car_trips": nc,
            "bus_delay_hrs": round(bus_d, 3), "car_delay_hrs": round(car_d, 3),
            "total_delay_hrs": round(tot_d, 3), "pax": round(pax, 1),
            "obj": round(obj, 4),
            "bus_mean_loss_s": round(sum(bus_loss) / len(bus_loss), 1) if bus_loss else 0.0,
            "loaded": loaded, "inserted": inserted, "waiting": waiting,
            "teleports": tele,
            "ge_triggers": ge["ge_triggers"],
            "ge_fires": ge["ge_fires"], "ge_seconds": ge["ge_seconds"],
            "ge_junctions": ge["ge_junctions"], "ge_fires_max": ge["ge_fires_max"],
            "wall_s": round(wall, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", required=True)
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--end", type=float, default=1200.0)
    ap.add_argument("--period", type=float, default=60.0,
                    help="period divides the horizon exactly (1200/60 = 20)")
    ap.add_argument("--csv", required=True)
    a = ap.parse_args()

    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    rows = []
    for seed in seeds:
        for on in (False, True):
            r = run_one(a.sumocfg, seed, a.end, a.period, on)
            rows.append(r)
            print("[GE] seed=%d overlay=%-3s bus=%d bus_delay=%7.3fh "
                  "car_delay=%8.3fh obj=%7.4f fires=%d ge_s=%.0f "
                  "junctions=%d trig=%d wall=%.0fs"
                  % (seed, r["overlay"], r["bus_trips"], r["bus_delay_hrs"],
                     r["car_delay_hrs"], r["obj"], r["ge_fires"],
                     r["ge_seconds"], r["ge_junctions"], r["ge_triggers"],
                     r["wall_s"]),
                  flush=True)
            with open(a.csv, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)

    print("\n%-6s %8s %12s %12s %9s %8s %7s" % (
        "seed", "overlay", "bus_delay_h", "car_delay_h", "obj",
        "fires", "ge_s"))
    for r in rows:
        print("%-6d %8s %12.3f %12.3f %9.4f %8d %7.0f" % (
            r["seed"], r["overlay"], r["bus_delay_hrs"], r["car_delay_hrs"],
            r["obj"], r["ge_fires"], r["ge_seconds"]))

    print("\npaired delta (on - off), negative bus_delay = overlay helped")
    for seed in seeds:
        off = next(r for r in rows if r["seed"] == seed and r["overlay"] == "off")
        on = next(r for r in rows if r["seed"] == seed and r["overlay"] == "on")
        d_bus = on["bus_delay_hrs"] - off["bus_delay_hrs"]
        p_bus = (d_bus / off["bus_delay_hrs"] * 100.0) if off["bus_delay_hrs"] else 0.0
        d_obj = on["obj"] - off["obj"]
        p_obj = (d_obj / off["obj"] * 100.0) if off["obj"] else 0.0
        print("  seed %d: bus_delay %+7.3fh (%+6.1f%%)   obj %+0.4f (%+5.1f%%)"
              % (seed, d_bus, p_bus, d_obj, p_obj))

    if len(seeds) > 1:
        offs = [r for r in rows if r["overlay"] == "off"]
        ons = [r for r in rows if r["overlay"] == "on"]
        mo = sum(r["bus_delay_hrs"] for r in offs) / len(offs)
        mn = sum(r["bus_delay_hrs"] for r in ons) / len(ons)
        oo = sum(r["obj"] for r in offs) / len(offs)
        on_ = sum(r["obj"] for r in ons) / len(ons)
        print("\nmean over %d seeds: bus_delay %.3f -> %.3f h (%+.1f%%), "
              "obj %.4f -> %.4f (%+.1f%%)"
              % (len(seeds), mo, mn, (mn - mo) / mo * 100.0 if mo else 0.0,
                 oo, on_, (on_ - oo) / oo * 100.0 if oo else 0.0))
    print("rows written: %s" % a.csv)


if __name__ == "__main__":
    main()
