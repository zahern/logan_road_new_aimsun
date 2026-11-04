"""analyze_cascade_ab.py -- before/after [CASCADE] cost and committed actions.

Pairs Aimsun runs of the SAME arm and seed on DIFFERENT engine builds and reports
the two things the cascade fix was supposed to change:

  1. the [CASCADE] cost distribution  (cost=...paxs, max_sat=..., hops=...)
  2. the committed-action counts, read from [DECISION] lines

Both come from the RUN LOG rather than the results CSV, because the log carries
ENGINE_BUILD on its [LOAD] line and the CSV has no build column at all (so a CSV
row cannot be attributed to a build). [DECISION] counts were checked against the
CSV's stats_TSP_* totals on the 2026-11-01 seed-500 run: 20 lines = GE 7 + INS 10
+ ER 3, exact match.

WHY SEED 300 AND 500
  The cascade charges are RARE. Across the six published champion runs there are
  ten charges in total, and SEVEN of them are seed 300:
      seed 300 (7): 1.89M, 3.5K, 10.17M, 233K, 4.23M, 15.20M, 9.1K
      seed 700 (2): 4.91M, 294K        seed 500 (1): 2.81M
      seeds 400/600 (0)
  Seed 500 alone gives a single point; seed 300 gives a distribution. Note also
  that seed 300 is the ONLY seed where the champion beats NO_TSP (+4.5%), while
  seeds 400 and 600 -- which had NO charges -- are the worst losses. Whatever
  suppresses TSP there, it is not this term.

  Because n is small, the report prints an explicit n first and refuses to call
  the spread a distribution below 5 points; on those runs the meaningful signals
  are HOW MANY hops charge at all and the max_sat reached (the old mixed-unit
  version pegged sat at its 0.95 clip, so max_sat read >1 on every charging hop).

USAGE
  python analyze_cascade_ab.py                          # seeds 300,500; champion
  python analyze_cascade_ab.py --seeds 300
  python analyze_cascade_ab.py --seeds 300,500 --arm CHAMP_ADAPTIVE_DSW_GAME_BUS_LOGAN_MICROQ

  The "current" build is read from shared_tsp_engine/engine.py's ENGINE_BUILD
  and the "current" hash from that file's bytes. Every [LOAD] line carries
  SOURCE_HASH (SHA1[:12] of the engine bytes Aimsun actually imported), so a run
  is tied to exact code even if the tag is stale; a run whose hash differs from
  the file on disk is reported STALE (Aimsun served a cached module).
"""
import argparse
import glob
import hashlib
import io
import os
import re
import statistics as st
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

_RE_ARM = re.compile(r"\[ARM\] exp=(\S+)")
_RE_SEED = re.compile(r"\bseed=(\d+)")
_RE_BUILD = re.compile(r"ENGINE_BUILD=(\S+)")
_RE_CASCADE = re.compile(
    r"\[CASCADE\]\s+inter=(\d+)\s+act=([\d.]+)s\s+hops=(\d+)\s+"
    r"cost=([-\d.eE+]+)paxs\s+max_sat=([\d.]+)")
_RE_ZERO = re.compile(
    r"\[CASCADE_ZERO\]\s+inter=(\d+)\s+act=([\d.]+)s\s+reason=(\S+)")
_RE_HOPS = re.compile(r"hops=(\d+)")
_RE_SAT = re.compile(r"max_sat=([\d.]+)")
_RE_DECISION = re.compile(
    r"\[DECISION\]\s+inter=(\d+)\s+t=([\d.]+)\s+.*?action=(\S+)")
_RE_NET = re.compile(r"pred_net=(-?[\d.]+)")
_RE_HASH = re.compile(r"SOURCE_HASH=(\S+)")


def current_hash():
    """SHA1[:12] of engine.py ON DISK NOW -- what a fresh import would stamp."""
    path = os.path.join(_HERE, "shared_tsp_engine", "engine.py")
    try:
        with open(path, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()[:12]
    except Exception:
        return "?"


def _stale(src_hash, now):
    """Marker for a log whose executed bytes are not the file on disk now."""
    if src_hash in ("?", now):
        return ""
    return "  << STALE (disk=%s)" % now


def current_build():
    path = os.path.join(_HERE, "shared_tsp_engine", "engine.py")
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("ENGINE_BUILD"):
                    m = re.search(r'"([^"]+)"', line)
                    if m:
                        return m.group(1)
    except Exception:
        pass
    return "?"


def index_logs(log_dir, arm, seed):
    """[(mtime, build, path)] for logs whose [ARM]/seed match, oldest first."""
    out = []
    for path in glob.glob(os.path.join(log_dir, "Aimsun_TSP_Log_*.txt")):
        try:
            with io.open(path, encoding="utf-8", errors="replace") as fh:
                head = fh.read(30000)
        except Exception:
            continue
        m = _RE_ARM.search(head)
        if not m or m.group(1) != arm:
            continue
        if str(seed) not in _RE_SEED.findall(head):
            continue
        b = _RE_BUILD.search(head)
        h = _RE_HASH.search(head)
        try:
            mt = os.path.getmtime(path)
        except Exception:
            mt = 0.0
        out.append((mt, b.group(1) if b else "?",
                    h.group(1) if h else "?", path))
    out.sort()
    return out


def parse_log(path):
    """Cascade charges, cascade zeros, and committed actions for one run."""
    casc, zero, dec, net_pos = [], [], [], 0
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "[CASCADE]" in line:
                m = _RE_CASCADE.search(line)
                if m:
                    casc.append((int(m.group(1)), float(m.group(2)),
                                 int(m.group(3)), float(m.group(4)),
                                 float(m.group(5))))
                continue
            if "[CASCADE_ZERO]" in line:
                m = _RE_ZERO.search(line)
                if m:
                    h = _RE_HOPS.search(line)
                    s = _RE_SAT.search(line)
                    zero.append((int(m.group(1)), m.group(3),
                                 int(h.group(1)) if h else None,
                                 float(s.group(1)) if s else None))
                continue
            if "[DECISION]" in line:
                m = _RE_DECISION.search(line)
                if m:
                    act = m.group(3)
                    fam = act.split("_")[0] if "_" in act else act
                    dec.append((int(m.group(1)), act, fam))
                    n = _RE_NET.search(line)
                    if n and float(n.group(1)) > 0.0:
                        net_pos += 1
    return casc, zero, dec, net_pos


def _fam_counts(dec):
    counts = {}
    for _i, _a, fam in dec:
        counts[fam] = counts.get(fam, 0) + 1
    return dict(sorted(counts.items()))


def _decade_hist(vals):
    buckets = {}
    for v in vals:
        if v <= 0:
            buckets["0"] = buckets.get("0", 0) + 1
            continue
        key = "1e%d" % (len("%d" % int(v)) - 1)
        buckets[key] = buckets.get(key, 0) + 1
    return dict(sorted(buckets.items(), key=lambda kv: (kv[0] != "0", kv[0])))


def describe(tag, entry, show_detail=True):
    if entry is None:
        print("\n  %s  NOT FOUND on this build." % tag)
        return None
    mt, build, src_hash, path = entry
    casc, zero, dec, net_pos = parse_log(path)
    costs = [c[3] for c in casc]

    print("\n  %s  build=%s  hash=%s%s"
          % (tag, build, src_hash, _stale(src_hash, current_hash())))
    print("    log  %s" % os.path.basename(path))
    print("    committed actions ([DECISION]) : %d%s"
          % (len(dec), ("  " + str(_fam_counts(dec))) if dec else ""))
    if dec:
        print("    ...of which pred_net > 0      : %d / %d (%.0f%%)"
              % (net_pos, len(dec), 100.0 * net_pos / len(dec)))
    print("    [CASCADE] charges             : %d" % len(casc))
    if costs:
        print("    cascade cost (pax.s)          : n=%d  min=%.4g  median=%.4g  "
              "max=%.4g  sum=%.4g"
              % (len(costs), min(costs), st.median(costs), max(costs),
                 sum(costs)))
        print("    by decade                     : %s" % _decade_hist(costs))
        sats = [c[4] for c in casc]
        print("    max_sat at charge             : min=%.2f  median=%.2f  max=%.2f"
              % (min(sats), st.median(sats), max(sats)))
        print("    hops at charge                : %s"
              % sorted({c[2] for c in casc}))
        print("    junctions charged             : %s"
              % sorted({c[0] for c in casc}))
        if show_detail and len(casc) <= 12:
            print("    per charge:")
            for i, a, h, c, s in casc:
                print("      inter=%-6d act=%4.0fs hops=%d  cost=%12.4g  "
                      "max_sat=%5.2f" % (i, a, h, c, s))
        if len(costs) < 5:
            print("    NOTE n<5: not a distribution. Judge the SCALE and the")
            print("         max_sat, not a median.")
    if zero:
        reasons = {}
        for _i, why, _h, _s in zero:
            reasons[why] = reasons.get(why, 0) + 1
        print("    [CASCADE_ZERO]                : %d  %s" % (len(zero), reasons))
        zs = [z[3] for z in zero if z[3] is not None]
        if zs:
            print("    ...max_sat seen when not charged: max=%.2f" % max(zs))
    return {"build": build, "hash": src_hash, "path": path,
            "n": len(casc), "costs": costs,
            "acts": len(dec), "fams": _fam_counts(dec),
            "sats": [c[4] for c in casc]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="300,500",
                    help="comma-separated seeds (default 300,500)")
    ap.add_argument("--arm", default="CHAMP_ADAPTIVE_DSW_GAME_BUS_LOGAN")
    ap.add_argument("--log-dir",
                    default=os.path.join(_HERE, "logan_road_new", "logs"))
    args = ap.parse_args(argv)
    seeds = [int(s) for s in args.seeds.replace(" ", "").split(",") if s]

    cur = current_build()
    cur_hash = current_hash()
    print("=" * 84)
    print("CASCADE / COMMITTED-ACTION A/B -- arm=%s" % args.arm)
    print("  seeds         : %s" % seeds)
    print("  current build : %s" % cur)
    print("  current hash  : %s   (engine.py on disk now)" % cur_hash)
    print("=" * 84)

    befores, afters, found_any = {}, {}, False
    for seed in seeds:
        runs = index_logs(args.log_dir, args.arm, seed)
        print("\n" + "-" * 84)
        print("SEED %d -- %d run log(s) on record" % (seed, len(runs)))
        if not runs:
            print("  no log for this arm+seed.")
            continue
        found_any = True
        for _name, _b, _h, _p in runs:
            print("  %-40s %-32s %s%s"
                  % (os.path.basename(_p), "CURRENT" if _b == cur else _b, _h,
                     _stale(_h, cur_hash)))
        before = [r for r in runs if r[1] != cur]
        after = [r for r in runs if r[1] == cur]
        befores[seed] = describe("BEFORE (published)",
                                 before[-1] if before else None)
        afters[seed] = describe("AFTER  (patched build)",
                                after[-1] if after else None)

    if not found_any:
        print("\nNo logs matched. Check --arm / --log-dir.")
        return 1

    b_costs = [c for s in seeds for c in (befores.get(s) or {}).get("costs", [])]
    a_costs = [c for s in seeds for c in (afters.get(s) or {}).get("costs", [])]
    b_acts = sum((befores.get(s) or {}).get("acts", 0) for s in seeds)
    a_acts = sum((afters.get(s) or {}).get("acts", 0) for s in seeds)

    print("\n" + "=" * 84)
    print("POOLED over seeds %s" % seeds)
    if b_costs:
        print("  BEFORE charges : n=%d  min=%.4g  median=%.4g  max=%.4g"
              % (len(b_costs), min(b_costs), st.median(b_costs), max(b_costs)))
        print("  BEFORE decades : %s" % _decade_hist(b_costs))
    if a_costs:
        print("  AFTER  charges : n=%d  min=%.4g  median=%.4g  max=%.4g"
              % (len(a_costs), min(a_costs), st.median(a_costs), max(a_costs)))
        print("  AFTER  decades : %s" % _decade_hist(a_costs))
    if any(afters.values()):
        print("  committed actions: %d -> %d" % (b_acts, a_acts))
    else:
        print("  committed actions: %d -> (not run)" % b_acts)

    if not a_costs and not any(afters.values()):
        print("\n  >> The patched-build runs do not exist yet. This tool is ready;")
        print("     run_logan_cascade_ab.py fills in the AFTER side once executed")
        print("     inside Aimsun. Nothing above an AFTER heading is a new result.")
    elif a_costs and b_costs:
        print("\n  DELTA median cost: %.4g -> %.4g  (%.3gx)"
              % (st.median(b_costs), st.median(a_costs),
                 st.median(a_costs) / st.median(b_costs)
                 if st.median(b_costs) else float("nan")))
        print("  If AFTER still clusters at 1e6+ pax.s with max_sat > 1, the unit")
        print("  fix did not reach the running module: check the [LOAD] line shows")
        print("  the current build (Aimsun caches loaded modules -- quit+relaunch).")
    print("=" * 84)
    return 0


if __name__ == "__main__":
    sys.exit(main())
