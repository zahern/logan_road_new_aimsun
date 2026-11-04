import glob
import os
import re
from datetime import datetime

import pandas as pd

R = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\kg\logs"
CSV = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\paper_ladder_priority_kg.csv"
OUT = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\kg_ladder_runmap.csv"

d = pd.read_csv(CSV)
d["utc"] = pd.to_datetime(d.run_utc, format="%Y-%m-%dT%H:%M:%SZ", utc=True)
d["end"] = d.utc.dt.tz_convert("Etc/GMT-10").dt.tz_localize(None)

KINDS = ("queue_snapshot", "ds_truth_check", "bus_positions", "presence_snapshot",
         "vehicle_tracks", "reward_cycle", "green_offsets", "plan_evolution",
         "corridor_wave_events")

pat = re.compile(
    r"^(queue_snapshot|sections_truth|bus_positions|vehicle_tracks|presence_snapshot|"
    r"reward_cycle|green_offsets|plan_evolution|phase_movements|corridor_wave_events|"
    r"Aimsun_TSP_Log|ds_truth_check)_(.*?)_(\d{8})_(\d{6})\.csv$")

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

rows = []
for arm, grp in d.groupby("run_experiment", sort=False):
    grp = grp.sort_values("end")
    ends = list(grp.end)
    for k, (_, r) in enumerate(grp.iterrows()):
        lo = ends[k - 1] if k else ends[k] - pd.Timedelta(minutes=15)
        hi = ends[k]
        rec = {"arm": arm, "seed": int(r.run_seed), "run_end": r.end}
        for kind in KINDS:
            cands = [(s, f) for s, f in files.get((arm, kind), []) if lo < s <= hi]
            rec[kind] = cands[0][1] if len(cands) == 1 else (
                "" if not cands else "AMBIG:%d" % len(cands))
            rec[kind + "_n"] = len(cands)
        rows.append(rec)

out = pd.DataFrame(rows)
for _, r in out.iterrows():
    print("%-34s %3d  %s" % (
        r.arm[:34], r.seed,
        " ".join("%s:%d" % (k[:6], r[k + "_n"]) for k in KINDS)))

print()
for kind in KINDS:
    n = (out[kind].astype(str).str.len() > 0).sum()
    amb = out[kind].astype(str).str.startswith("AMBIG").sum()
    print("%-22s runs=%2d ambiguous=%d" % (kind, n - amb, amb))

out.drop(columns=[k + "_n" for k in KINDS]).to_csv(OUT, index=False)
print("wrote", os.path.basename(OUT))
