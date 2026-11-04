"""Extract the mean measured queue per Logan ladder run (arm x seed).

Run identity comes from the Aimsun logs: `Aimsun_TSP_Log_<stamp>.txt` carries
`[ARM] exp=<arm>` and `[BXT_PHASE] seed=<seed>` (the log seed equals the CSV
run_seed), and the file stamp is the run start.  The queue_snapshot file for
that run is the one stamped within two minutes of the start.
"""
import glob
import os
import re
from datetime import datetime

import pandas as pd

B = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
R = os.path.join(B, "logan_road_new", "logs")
CSV = os.path.join(B, "paper_ladder_priority_logan.csv")
OUT = os.path.join(B, "logan_ladder_queue.csv")

d = pd.read_csv(CSV)
d = d[d.run_experiment.astype(str).str.endswith("_LOGAN")
      | (d.run_experiment == "NO_TSP")]

runs = []
for p in sorted(glob.glob(os.path.join(R, "Aimsun_TSP_Log_*.txt"))):
    b = os.path.basename(p)
    m = re.search(r"_(\d{8})_(\d{6})\.txt$", b)
    start = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    head = open(p, encoding="utf-8", errors="replace").read(8000)
    arm = re.search(r"\[ARM\] exp=(\S+)", head)
    seed = re.search(r"\[BXT_PHASE\] seed=(\d+)", head)
    if arm and seed:
        runs.append((arm.group(1), int(seed.group(1)), start, p))
runs = pd.DataFrame(runs, columns=["arm", "seed", "start", "log"])
print("logs parsed:", len(runs))

qfiles = {}
for f in glob.glob(os.path.join(R, "queue_snapshot_*.csv")):
    b = os.path.basename(f)
    m = re.match(r"^queue_snapshot_(.+)_(\d{8})_(\d{6})\.csv$", b)
    if m:
        qfiles[(m.group(1), datetime.strptime(m.group(2) + m.group(3),
                                              "%Y%m%d%H%M%S"))] = f

rows = []
for _, r in d.iterrows():
    arm, seed = r.run_experiment, int(r.run_seed)
    cand = runs[(runs.arm == arm) & (runs.seed == seed)]
    if cand.empty:
        print("!! no log for", arm, seed)
        continue
    start = cand.iloc[-1].start
    qc = [(s, f) for (a, s), f in qfiles.items()
          if a == arm and abs((s - start).total_seconds()) <= 120]
    if len(qc) != 1:
        print("!! %s seed %d: %d queue files" % (arm, seed, len(qc)))
        continue
    q = pd.read_csv(qc[0][1])
    rows.append(dict(arm=arm, seed=seed, queue_mean=float(q.queue_total.mean()),
                     queue_main=float(q.queue_main.mean()),
                     queue_side=float(q.queue_side.mean()),
                     n_rows=len(q), file=os.path.basename(qc[0][1])))

out = pd.DataFrame(rows)
out.to_csv(OUT, index=False)
print("\nwrote %s (%d rows)" % (OUT, len(out)))
print(out.groupby("arm").queue_mean.mean().round(2).to_string())
