"""_audit_detection_points.py -- are the junction positions in the detection
export contaminated by points in a mixed frame?

make_logan_corridor_map.py reduces each junction to the MEDIAN of its detected
points and its docstring warns that "a few points in that export sit in a mixed
frame". This audits that claim:

  * how many points are in each coordinate class (UTM 56S metres vs lon/lat),
  * where the non-UTM points would land if transformed to UTM -- i.e. whether
    they are the same junction in the wrong frame or a different place,
  * how far each junction's median moves when they are dropped,
  * what position scatter means for the 4--13 m pair separations.

Read-only.    python -I _audit_detection_points.py
"""
import collections
import glob
import json
import math
import os
import statistics as st

from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
TO_UTM = Transformer.from_crs(4326, 32756, always_xy=True)


def klass(x, y):
    if 1e5 <= x <= 8e5 and 5e6 <= y <= 8e6:
        return "utm"
    if abs(x) <= 180 and abs(y) <= 90:
        return "lonlat"
    return "other"


def main():
    src = sorted(glob.glob(os.path.join(
        HERE, "logan_road_new", "logs", "detection_points_*.geojson")))[-1]
    with open(src) as fh:
        data = json.load(fh)
    feats = data["features"]
    print("source :", os.path.basename(src))
    print("crs    :", data.get("crs", "(none declared)"))
    print("points :", len(feats))

    pts = collections.defaultdict(list)
    for f in feats:
        x, y = f["geometry"]["coordinates"]
        pts[f["properties"]["junction_id"]].append((x, y, f["properties"]))

    cls = collections.Counter(klass(x, y) for v in pts.values() for x, y, _ in v)
    print("class  :", dict(cls))

    bad = [(j, x, y, pr) for j, v in pts.items() for x, y, pr in v
           if klass(x, y) != "utm"]
    print("")
    print("non-UTM points: %d" % len(bad))
    per = collections.Counter(j for j, _, _, _ in bad)
    for j in sorted(per):
        print("  junction %-7d %d of %d points" % (j, per[j], len(pts[j])))
    print("")
    print("where they land once transformed 4326 -> 32756:")
    for j, x, y, pr in bad[:25]:
        ux, uy = TO_UTM.transform(x, y)
        mx, _ = _median(pts[j])
        my = _median(pts[j])[1]
        print("  j=%-6d raw (%10.5f, %10.5f) -> UTM (%9.0f, %9.0f)  %8.0f m "
              "from junction median   veh=%s tier=%s"
              % (j, x, y, ux, uy, math.hypot(ux - mx, uy - my),
                 pr.get("veh_id"), pr.get("tier")))

    print("")
    print("median position, all points vs UTM-only:")
    shift = []
    clean = {}
    for j, v in pts.items():
        good = [(x, y) for x, y, _ in v if klass(x, y) == "utm"]
        clean[j] = _median([(x, y) for x, y, _ in v])
        if not good:
            continue
        allm = _median([(x, y) for x, y, _ in v])
        goodm = _median(good)
        d = math.hypot(allm[0] - goodm[0], allm[1] - goodm[1])
        shift.append((d, j, len(v), len(good)))
    for d, j, n, ng in sorted(shift, reverse=True)[:8]:
        print("  %-7d shifts %7.2f m   (%d points, %d UTM)" % (j, d, n, ng))

    print("")
    print("position scatter per junction (UTM points only):")
    print("  %-7s %5s %8s %8s %8s" % ("id", "n", "p50", "p90", "SE(med)"))
    for j in sorted(pts):
        v = [(x, y) for x, y, _ in pts[j] if klass(x, y) == "utm"]
        if len(v) < 3:
            continue
        m = _median(v)
        d = sorted(math.hypot(x - m[0], y - m[1]) for x, y in v)
        p50 = d[len(d) // 2]
        p90 = d[int(0.9 * (len(d) - 1))]
        se = 1.253 * p50 / math.sqrt(len(d))     # SE of a median, MAD form
        print("  %-7d %5d %8.1f %8.1f %8.1f" % (j, len(v), p50, p90, se))

    print("")
    print("pair separations on UTM-only medians:")
    ids = sorted(clean)
    rows = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            d = math.hypot(clean[a][0] - clean[b][0], clean[a][1] - clean[b][1])
            if d < 60.0:
                rows.append((d, a, b))
    for d, a, b in sorted(rows):
        print("  %-7d %-7d %6.1f m" % (a, b, d))

    for limit in (40.0, 150.0):
        print("  single linkage at %5.0f m -> %d points"
              % (limit, _groups(clean, ids, limit)))


def _median(v):
    return (st.median([p[0] for p in v]), st.median([p[1] for p in v]))


def _groups(pos, ids, limit):
    parent = {i: i for i in ids}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]) < limit:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra
    return len({find(i) for i in ids})


if __name__ == "__main__":
    main()
