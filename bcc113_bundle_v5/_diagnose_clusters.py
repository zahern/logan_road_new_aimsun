"""_diagnose_clusters.py -- why the Logan corridor map draws 13 dots for 23 IDs.

make_logan_corridor_map.py single-linkage clusters junction positions within
CLUSTER_M (150 m). This prints the measured separations so the merges can be
judged: same physical intersection, or distinct sites pulled together by one
close pair.

    python -I _diagnose_clusters.py
"""
import collections
import glob
import json
import math
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLUSTER_M = 150.0


def main():
    src = sorted(glob.glob(os.path.join(
        HERE, "logan_road_new", "logs", "detection_points_*.geojson")))[-1]
    pts = collections.defaultdict(list)
    with open(src) as fh:
        for feat in json.load(fh)["features"]:
            x, y = feat["geometry"]["coordinates"]
            pts[feat["properties"]["junction_id"]].append((x, y))
    pos = {j: (st.median([p[0] for p in v]), st.median([p[1] for p in v]))
           for j, v in pts.items()}
    print("source :", os.path.basename(src))
    print("ids    :", len(pos), " points per id: min %d max %d"
          % (min(len(v) for v in pts.values()),
             max(len(v) for v in pts.values())))

    ids = sorted(pos)
    print("")
    print("nearest neighbour of each junction (metres):")
    for i in ids:
        best = min(((math.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]), j)
                    for j in ids if j != i))
        print("  %-8d -> %-8d  %7.1f m" % (i, best[1], best[0]))

    parent = {i: i for i in ids}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    bridges = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            d = math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1])
            if d < CLUSTER_M:
                bridges.append((d, a, b))
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra

    groups = collections.defaultdict(list)
    for i in ids:
        groups[find(i)].append(i)

    print("")
    print("CLUSTER_M = %.0f m -> %d groups from %d ids"
          % (CLUSTER_M, len(groups), len(ids)))
    for members in sorted(groups.values(), key=lambda g: -max(pos[m][1] for m in g)):
        mx = max((math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1])
                  for a in members for b in members), default=0.0)
        print("  %-34s n=%d  max separation %6.1f m"
              % ("/".join(str(m) for m in members), len(members), mx))

    print("")
    print("pairs closer than %.0f m (these are what merge):" % CLUSTER_M)
    for d, a, b in sorted(bridges):
        print("  %-8d %-8d %6.1f m" % (a, b, d))

    print("")
    for limit in (40.0, 60.0, 80.0, 100.0, 120.0):
        p = {i: i for i in ids}

        def f2(a):
            while p[a] != a:
                p[a] = p[p[a]]
                a = p[a]
            return a
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if math.hypot(pos[a][0] - pos[b][0],
                              pos[a][1] - pos[b][1]) < limit:
                    ra, rb = f2(a), f2(b)
                    if ra != rb:
                        p[rb] = ra
        n = len({f2(i) for i in ids})
        print("  at %5.0f m -> %2d points" % (limit, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
