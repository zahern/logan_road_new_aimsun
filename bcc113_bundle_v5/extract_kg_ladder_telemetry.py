"""Extract per-junction and per-decision telemetry from the KG ladder runs.

Two self-consistent batches on 2026-10-31:
  * batch ``8arm``    (build 0400): NO_TSP and AIMSUN_DSW, 03:48-04:47 local
  * batch ``priority``(build 1030): NO_TSP and the four priority layers, 10:23-13:23

Run identity comes from `Aimsun_TSP_Log_<stamp>.txt`: file stamp = run start,
last timestamped line = run end, `[BXT_PHASE] seed=` = CSV `run_seed`.  We pair
by nearest run end to the CSV `run_utc` (which is written ~5 s after the run).
Start-of-run files (queue/bus/presence/tracks) are stamped start + ~10 s;
end-of-run files (ds_truth/plan_evolution/reward_cycle) end + ~6 s.
"""
import glob
import os
import re
from datetime import datetime

import pandas as pd

R = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\kg\logs"
B = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
OUT = B

START_KINDS = {"queue_snapshot": 60, "bus_positions": 60, "presence_snapshot": 60,
               "vehicle_tracks": 60, "corridor_wave_events": 60,
               "green_offsets": 60}
END_KINDS = {"ds_truth_check": 90, "plan_evolution": 90, "reward_cycle": 90}

# ---- run identity ----------------------------------------------------------
runs = []
for p in glob.glob(os.path.join(R, "Aimsun_TSP_Log_20261031_*.txt")):
    b = os.path.basename(p)
    m = re.search(r"_(\d{8})_(\d{6})\.txt$", b)
    start = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    if not (3 <= start.hour <= 14):
        continue
    tail, arm, seed = None, None, None
    with open(p, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if re.match(r"\d\d:\d\d:\d\d", line[:8]):
                tail = line[:8]
            if arm is None and "[ARM]" in line:
                a = re.search(r"exp=(\S+)", line)
                arm = a.group(1) if a else None
            if seed is None and "[BXT_PHASE]" in line:
                s = re.search(r"seed=(\d+)", line)
                seed = int(s.group(1)) if s else None
    if arm and seed and tail:
        end = datetime.combine(start.date(), datetime.strptime(tail, "%H:%M:%S").time())
        if end < start:
            end += pd.Timedelta(days=1)
        runs.append(dict(arm=arm, seed=seed, start=start, end=end))
runs = pd.DataFrame(runs)
print("logs parsed:", len(runs))

# ---- CSVs ------------------------------------------------------------------
pri = pd.read_csv(os.path.join(B, "paper_ladder_priority_kg.csv"))
eight = pd.read_csv(os.path.join(B, "paper_ladder_8arm_kg.csv"))
eight = eight[eight.run_experiment.isin(["NO_TSP", "CHAMP_ADAPTIVE_AIMSUN_DSW"])]
pri["batch"] = "priority"
eight["batch"] = "8arm"
d = pd.concat([pri, eight], ignore_index=True)
d["csv_end"] = (pd.to_datetime(d.run_utc, format="%Y-%m-%dT%H:%M:%SZ", utc=True)
                .dt.tz_convert("Etc/GMT-10").dt.tz_localize(None))

# ---- file index ------------------------------------------------------------
KINDS = list(START_KINDS) + list(END_KINDS)
pat = re.compile(r"^(%s)_(.*?)_(\d{8})_(\d{6})\.csv$" % "|".join(KINDS))
files = {}
for f in glob.glob(os.path.join(R, "*.csv")):
    b = os.path.basename(f)
    if b.endswith("_summary.csv"):
        continue
    m = pat.match(b)
    if not m:
        continue
    files.setdefault((m.group(2), m.group(1)), []).append(
        (datetime.strptime(m.group(3) + m.group(4), "%Y%m%d%H%M%S"), f))

junc, ts, trig, jts = [], [], [], []
used = {k: 0 for k in KINDS}
for _, r in d.iterrows():
    arm, seed = r.run_experiment, int(r.run_seed)
    cand = runs[(runs.arm == arm) &
                ((runs.end - r.csv_end).abs() < pd.Timedelta(seconds=180))]
    if cand.empty:
        print("NO LOG", r.batch, arm, seed)
        continue
    row = cand.iloc[((cand.end - r.csv_end).abs()).argmin()]
    start, end = row.start, row.end
    rec = {}
    for kind, win in list(START_KINDS.items()) + list(END_KINDS.items()):
        anchor = start if kind in START_KINDS else end
        cc = [(s, f) for s, f in files.get((arm, kind), [])
              if abs((s - anchor).total_seconds()) <= win]
        if cc:
            rec[kind] = max(cc, key=lambda x: os.path.getsize(x[1]))[1]
            used[kind] += 1
        else:
            rec[kind] = None
    if not rec["queue_snapshot"]:
        print("NO QUEUE", r.batch, arm, seed)
        continue

    q = pd.read_csv(rec["queue_snapshot"])
    last = q.sort_values("sim_time_s").groupby("junction_id").tail(1)
    qmean = q.groupby("junction_id").queue_total.mean()
    for _, x in last.iterrows():
        junc.append(dict(batch=r.batch, arm=arm, seed=seed,
                         junction=int(x.junction_id),
                         delay_total_s=float(x.delay_total_s),
                         delay_bus_s=float(x.delay_bus_s),
                         delay_car_s=float(x.delay_car_s),
                         queue_mean_veh=float(qmean[x.junction_id])))
    g = (q.groupby("sim_time_s")
         .agg(delay_total_s=("delay_total_s", "sum"),
              queue_total=("queue_total", "sum")).reset_index())
    g.insert(0, "seed", seed)
    g.insert(0, "arm", arm)
    g.insert(0, "batch", r.batch)
    ts.append(g)
    qq = q[["sim_time_s", "junction_id", "queue_total", "delay_total_s"]].copy()
    qq.insert(0, "seed", seed)
    qq.insert(0, "arm", arm)
    qq.insert(0, "batch", r.batch)
    jts.append(qq)

    if rec.get("reward_cycle"):
        rc = pd.read_csv(rec["reward_cycle"])
        keep = [c for c in ("sim_time_s", "junction_id", "veh_id", "bus_eta_s",
                            "current_phase", "action", "reward", "bus_saved_pax_s",
                            "other_inc_pax_s", "side_inc_pax_s", "is_chosen",
                            "bus_dist_m", "bus_speed_kmh", "bus_in_zone",
                            "max_queue_bus_veh", "red_dur_bus_s", "main_x",
                            "side_max_flow_vph", "queue_veh", "tsp_armed",
                            "monitor", "stage", "bus_late_s", "headway_s",
                            "gate", "decider_min_late") if c in rc.columns]
        rc = rc[keep].copy()
        rc.insert(0, "seed", seed)
        rc.insert(0, "arm", arm)
        rc.insert(0, "batch", r.batch)
        trig.append(rc)

    print("%-9s %-30s %d  %s-%s  q=%s" % (
        r.batch, arm.replace("CHAMP_ADAPTIVE_", ""), seed,
        start.strftime("%H:%M:%S"), end.strftime("%H:%M:%S"),
        os.path.basename(rec["queue_snapshot"])[-18:-4]))

print("\nfile coverage:", {k: used[k] for k in KINDS})
pd.DataFrame(junc).to_csv(os.path.join(OUT, "kg_ladder_junction_delay.csv"), index=False)
pd.concat(ts).to_csv(os.path.join(OUT, "kg_ladder_delay_timeseries.csv"), index=False)
pd.concat(jts).to_csv(os.path.join(OUT, "kg_ladder_junction_timeseries.csv"), index=False)
if trig:
    pd.concat(trig).to_csv(os.path.join(OUT, "kg_ladder_triggers.csv"), index=False)
print("written")
