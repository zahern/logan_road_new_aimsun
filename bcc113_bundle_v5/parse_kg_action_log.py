"""Parse the Aimsun TSP logs for applied actions and decline reasons (KG ladder).

Only the runs that produced the paper's KG tables are parsed:
  * priority batch (build 1030): NO_TSP + M2..M5, seeds 300-700
  * companion 8-arm batch (build 0400): NO_TSP + M1, seeds 300-700
Runs are paired to the CSV rows by arm and run-end time.
"""
import glob
import os
import re
from datetime import datetime

import pandas as pd

R = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\kg\logs"
B = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"

DEC = re.compile(
    r"\[DECISION\] inter=(\d+) t=([\d.]+) bus=(\d+) action=(\S+) dur=([\d.]+)s "
    r"pred_bus=(-?[\d.]+) pred_other=(-?[\d.]+) pred_side=(-?[\d.]+) "
    r"pred_net=(-?[\d.]+) chain=(-?[\d.]+) R=(-?[\d.]+) (\w+) x=([\d.]+) "
    r"side=([\d.]+) q=([\d.]+)")
REW = re.compile(
    r"\[REWARD_TSP\] inter=(\d+) t=([\d.]+) bus=(\d+) eta=([\d.-]+)s "
    r"DECISION=(\S+) R=(-?[\d.]+)(?: \((.*)\))?")

# ---- logs ---------------------------------------------------------------
logs = []
for p in sorted(glob.glob(os.path.join(R, "Aimsun_TSP_Log_20261031_*.txt"))):
    b = os.path.basename(p)
    m = re.search(r"_(\d{8})_(\d{6})\.txt$", b)
    start = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    if not (3 <= start.hour <= 13):
        continue
    lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
    arm = seed = engine = None
    tail = None
    for line in lines:
        if re.match(r"\d\d:\d\d:\d\d", line[:8]):
            tail = line[:8]
        if arm is None and "[ARM]" in line:
            a = re.search(r"exp=(\S+)", line)
            arm = a.group(1) if a else None
        if seed is None and "[BXT_PHASE]" in line:
            s = re.search(r"seed=(\d+)", line)
            seed = int(s.group(1)) if s else None
        if engine is None and "ENGINE_BUILD=" in line:
            e = re.search(r"ENGINE_BUILD=(\S+)", line)
            engine = e.group(1) if e else None
    if not (arm and seed and tail):
        continue
    end = datetime.combine(start.date(), datetime.strptime(tail, "%H:%M:%S").time())
    if end < start:
        end += pd.Timedelta(days=1)
    logs.append(dict(arm=arm, seed=seed, engine=engine, start=start, end=end,
                     path=p, lines=lines))

pri = pd.read_csv(os.path.join(B, "paper_ladder_priority_kg.csv"))
eight = pd.read_csv(os.path.join(B, "paper_ladder_8arm_kg.csv"))
eight = eight[eight.run_experiment.isin(["NO_TSP", "CHAMP_ADAPTIVE_AIMSUN_DSW"])]
pri["batch"] = "priority"
eight["batch"] = "8arm"
d = pd.concat([pri, eight], ignore_index=True)
d["csv_end"] = (pd.to_datetime(d.run_utc, format="%Y-%m-%dT%H:%M:%SZ", utc=True)
                .dt.tz_convert("Etc/GMT-10").dt.tz_localize(None))

rows, declines, chosen = [], [], []
for _, r in d.iterrows():
    cands = [L for L in logs if L["arm"] == r.run_experiment
             and abs((L["end"] - r.csv_end).total_seconds()) < 180]
    if not cands:
        print("no log", r.batch, r.run_experiment, r.run_seed)
        continue
    L = min(cands, key=lambda x: abs((x["end"] - r.csv_end).total_seconds()))
    chosen.append((r.batch, r.run_experiment, int(r.run_seed), L["engine"]))
    for line in L["lines"]:
        mm = DEC.search(line)
        if mm:
            (j, t, bus, act, dur, pb, po, ps, pn, ch, rw, stage, x, side, q) = mm.groups()
            rows.append(dict(batch=r.batch, arm=r.run_experiment, seed=int(r.run_seed),
                             junction=int(j), sim_time_s=float(t),
                             action=act, family=act.split("_")[0], dur_s=float(dur),
                             pred_bus=float(pb), pred_other=float(po),
                             pred_side=float(ps), pred_net=float(pn),
                             chain=float(ch), reward=float(rw), stage=stage,
                             main_x=float(x), side_vph=float(side),
                             queue_veh=float(q)))
        mr = REW.search(line)
        if mr:
            declines.append(dict(batch=r.batch, arm=r.run_experiment, seed=int(r.run_seed),
                                 reason=mr.group(7) or ""))

a = pd.DataFrame(rows)
dl = pd.DataFrame(declines)
print("runs selected:", len(chosen))
print("\napplied actions by arm/family (all seeds):")
print(a.groupby(["arm", "family"]).size().unstack(fill_value=0).to_string())
print("\nactions per seed:")
print(a.groupby(["arm", "seed"]).size().unstack(fill_value=0).to_string())

dl["reason"] = dl.reason.str.replace(r"\(solver.*", "", regex=True).str.strip()
print("\ndecline reasons:")
print(dl.groupby(["arm", "reason"]).size().unstack(fill_value=0).to_string())

print("\ncontext at applied actions (median):")
cols = ["pred_bus", "pred_other", "pred_net", "chain", "dur_s", "main_x",
        "side_vph", "queue_veh"]
print(a.groupby("arm")[cols].median().round(1).to_string())
print("\nshare of actions with pred_net<=0:")
print((a.assign(neg=a.pred_net <= 0).groupby("arm").neg.mean() * 100).round(1).to_string())

a.to_csv(os.path.join(B, "kg_ladder_actions.csv"), index=False)
dl.to_csv(os.path.join(B, "kg_ladder_declines.csv"), index=False)
print("\nwritten")
