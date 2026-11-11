"""Aggregate the KALMAN NO_TSP vs CHAMP re-measurement.

Reads the two CSVs written by run_noise_floor.py, checks that each arm actually
ran the configuration it claims (resolved_mode / flags), and reports the delay
comparison with an exact permutation test (no SciPy needed: 5 vs 5 is 252
splits, so the two-sided p-value is exact rather than approximated).

Usage: python compare_kalman.py <notsp.csv> <champ.csv> \
           [baseline_notsp.csv baseline_champ.csv]

The optional baseline pair is a measurement at another --end, so the change in
penalty between horizons (i.e. whether TSP hurts more once the network loads
up) is reported directly.
"""
import csv
import itertools
import math
import sys


def load(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f)]


def col(rows, name):
    out = []
    for r in rows:
        v = r.get(name)
        if v is None or v == "":
            continue
        out.append(float(v))
    return out


def mean(xs):
    return sum(xs) / len(xs)


def sd(xs):
    if len(xs) < 2:
        return float("nan")
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def perm_p(a, b):
    """Two-sided exact permutation p-value for the difference of means."""
    obs = abs(mean(a) - mean(b))
    pool = list(a) + list(b)
    na = len(a)
    hits = 0
    total = 0
    for idx in itertools.combinations(range(len(pool)), na):
        s = set(idx)
        ga = [pool[i] for i in s]
        gb = [pool[i] for i in range(len(pool)) if i not in s]
        total += 1
        if abs(mean(ga) - mean(gb)) >= obs - 1e-12:
            hits += 1
    return hits / total, total


def cohens_d(a, b):
    sa, sb = sd(a), sd(b)
    sp = math.sqrt(((len(a) - 1) * sa ** 2 + (len(b) - 1) * sb ** 2) / (len(a) + len(b) - 2))
    return (mean(b) - mean(a)) / sp if sp else float("nan")


def describe(label, xs):
    m, s = mean(xs), sd(xs)
    cv = 100.0 * s / m if m else float("nan")
    print("  %-22s n=%-2d mean=%9.4f  sd=%7.4f  cv=%5.2f%%  min=%9.4f  max=%9.4f"
          % (label, len(xs), m, s, cv, min(xs), max(xs)))
    return m, s


def horizon(rows):
    ends = sorted({r.get("end") for r in rows if r.get("end")})
    return ",".join(ends) if ends else "?"


def main():
    args = sys.argv[1:]
    if len(args) not in (2, 4):
        raise SystemExit("usage: compare_kalman.py <notsp.csv> <champ.csv> "
                         "[baseline_notsp.csv baseline_champ.csv]")
    notsp_path, champ_path = args[0], args[1]
    base = (args[2], args[3]) if len(args) == 4 else None
    A, B = load(notsp_path), load(champ_path)

    print("=== harness self-check (each arm must run what it claims) ===")
    for name, rows in (("NO_TSP", A), ("CHAMP", B)):
        modes = sorted({r.get("resolved_mode", "?") for r in rows})
        methods = sorted({r.get("method", "?") for r in rows})
        flags = sorted({r.get("nflags", "?") for r in rows})
        early = [r.get("stopped_early") for r in rows]
        print("  %-6s reps=%d resolved=%s method=%s flags=%s stopped_early=%s"
              % (name, len(rows), ",".join(modes), ",".join(methods), ",".join(flags), early))

    print("\n=== delay (TotalPassDelay_hrs -- lower is better) ===")
    da, db = col(A, "delay_hrs"), col(B, "delay_hrs")
    ma, sa = describe("NO_TSP (KALMAN)", da)
    mb, sb = describe("CHAMP  (KALMAN)", db)
    diff = mb - ma
    p, total = perm_p(da, db)
    print("  difference (CHAMP - NO_TSP) = %+.4f h  (%+.2f%%)  |d| = %.2f  perm p = %.4f (%d splits)"
          % (diff, 100.0 * diff / ma, abs(cohens_d(da, db)), p, total))

    print("\n=== passengers ===")
    pa, pb = col(A, "pax"), col(B, "pax")
    describe("NO_TSP", pa)
    describe("CHAMP", pb)
    print("  difference = %+.1f pax  perm p = %.4f" % (mean(pb) - mean(pa), perm_p(pa, pb)[0]))

    print("\n=== objective (pax per delay-hour -- derived from the two above) ===")
    oa, ob = col(A, "obj"), col(B, "obj")
    describe("NO_TSP", oa)
    describe("CHAMP", ob)
    print("  difference = %+.3f  perm p = %.4f" % (mean(ob) - mean(oa), perm_p(oa, ob)[0]))
    print("  NOTE: obj = pax / delay, so this is not independent evidence.")

    print("\n=== demand coverage (a 600 s cut only loads ~21%% of the corridor) ===")
    for name, rows in (("NO_TSP", A), ("CHAMP", B)):
        completed = col(rows, "rows")
        print("  %-6s end=%-6s completed_trips=%s  pax=%s"
              % (name, horizon(rows),
                 "%.0f" % mean(completed) if completed else "?",
                 "%.1f" % mean(col(rows, "pax")) if col(rows, "pax") else "?"))

    if base:
        A0, B0 = load(base[0]), load(base[1])
        m0a, m0b = mean(col(A0, "delay_hrs")), mean(col(B0, "delay_hrs"))
        pen0, pen1 = m0b - m0a, diff
        print("\n=== cross-horizon: does the penalty grow with load? ===")
        print("  baseline end=%-6s NO_TSP %8.3f  CHAMP %8.3f  penalty %+8.3f h (%+.2f%%)"
              % (horizon(A0), m0a, m0b, pen0, 100.0 * pen0 / m0a))
        print("  full     end=%-6s NO_TSP %8.3f  CHAMP %8.3f  penalty %+8.3f h (%+.2f%%)"
              % (horizon(A), ma, mb, pen1, 100.0 * pen1 / ma))
        print("  change in penalty = %+.3f h  (%+.2f pts of baseline delay)"
              % (pen1 - pen0, 100.0 * (pen1 - pen0) / m0a))
        print("  NOTE: horizons differ in demand, so only the CHAMP-vs-NO_TSP contrast")
        print("  is comparable within a horizon -- never the absolute values.")


if __name__ == "__main__":
    main()
