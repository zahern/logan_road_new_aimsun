#!/usr/bin/env python3
"""check_champion.py -- per-arm summary of champion_kg.csv."""
import csv

with open("champion_kg.csv", "r", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))
print(f"Total rows: {len(rows)}")

arms = {}
for r in rows:
    arms.setdefault(r.get("run_experiment", "UNKNOWN"), []).append(r)

print(f"{'ARM':24s} {'n':>3s} {'mean_obj':>12s} {'det':>5s} {'ext':>4s} "
      f"{'ins':>4s} {'gr':>4s} {'er':>4s} {'noact':>6s} {'natgrn':>6s}")
for name in sorted(arms):
    rs = arms[name]
    objs, dets, exts, inss, grs, ers, noacts, natgs = ([] for _ in range(8))
    for r in rs:
        try:
            objs.append(float(r.get("stats_Objective_PaxPerDelayHr") or "nan"))
        except ValueError:
            pass
        for lst, key in ((dets, "stats_TSP_Detections"),
                         (exts, "stats_TSP_Extensions"),
                         (inss, "stats_TSP_Insertions"),
                         (grs, "stats_TSP_GreenRealloc"),
                         (ers, "stats_TSP_EarlyRed"),
                         (noacts, "stats_TSP_Detected_NoAction"),
                         (natgs, "stats_TSP_NaturalGreen")):
            try:
                lst.append(int(float(r.get(key) or 0)))
            except ValueError:
                pass
    objs = [o for o in objs if o == o]
    ostr = f"{sum(objs)/len(objs):12.1f}" if objs else f"{'NO OBJ':>12s}"
    print(f"{name:24s} {len(rs):3d} {ostr} {sum(dets):5d} {sum(exts):4d} "
          f"{sum(inss):4d} {sum(grs):4d} {sum(ers):4d} {sum(noacts):6d} "
          f"{sum(natgs):6d}")
