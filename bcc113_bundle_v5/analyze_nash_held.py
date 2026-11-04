"""analyze_nash_held.py -- tally [NASH_HELD] binding constraints per seed and set
them beside the published ladder numbers.

WHY THIS EXISTS. On seed 600 the champion committed 3 actions out of 399 decision
points and lost 5.3% to NO_TSP. The published logs could not say why: the held
path logged only a generic reward, so "the bus was never delayed enough", "every
candidate was net-negative", "the neighbour adjustment ate the benefit", and "it
cleared the costs but was too small" were all the same line. [NASH_HELD] separates
them. This script turns those rows into the per-seed table.

CRITICAL READING RULE. The published ladder logs were produced BEFORE the
instrumentation existed, so their why-columns print `-`, which means NOT MEASURED,
not zero. A `0` is a measured zero. The two are never conflated here, because the
first thing this table is used for is deciding whether the diagnosis changed.

DECISION rows vs CANDIDATE rows. `held` counts DECISION points the decider refused
(from [REWARD_TSP]). `why:*` counts REJECTED CANDIDATES (from [NASH_HELD]), and one
held decision contributes one row per candidate it rejected -- so the why column
does not sum to `held` and must not be read as a partition. `min_gain` and
`min_delay` are one row per decision and are directly comparable.

USAGE (from the bundle root; no Aimsun needed):

    python analyze_nash_held.py
    python analyze_nash_held.py --seeds 600,700
    python analyze_nash_held.py --logs kg/logs --csv paper_ladder_priority_kg.csv
    python analyze_nash_held.py --all            # do not skip old logs by mtime

Exit status is 0 whenever the report is produced; it is a reporting tool, not a
gate.
"""
import argparse
import collections
import csv
import glob
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Log identity is in the first ~20 lines; reading the head of 2700+ files is cheap
# even though the directory as a whole is tens of GB.
_HEAD_LINES = 80
RE_SEED = re.compile(r"seed=(\d+)")
RE_ARM = re.compile(r"\[ARM\]\s+exp=([A-Za-z0-9_.\-]+)")
RE_BUILD = re.compile(r"ENGINE_BUILD=([A-Za-z0-9_.\-]+)")
RE_LOAD = re.compile(r"\[LOAD\]\s+load:\s+bundle=(\S+)")
RE_DEC = re.compile(r"DECISION=([A-Z_0-9]+)")
# The reason field can NEST parens: "(decider gated: pre-warm (t<420s))". A
# [^)]* capture stops at the inner ')' and drops the whole line into '?' -- which
# silently hid 40 of seed 600's holds. Capture greedily from the outer '(' instead.
RE_PAREN = re.compile(r"\((.+)\)\s*$")
RE_HASH = re.compile(r"SHA1[:=]\s*([0-9a-f]{8,40})", re.I)

# The FIRST build that emits [NASH_HELD]. Row count alone cannot decide whether a
# log was instrumented: a cooperative arm selects by coalition score and never
# reaches the picker, so it legitimately emits ZERO rows on a fully instrumented
# build. Calling that "not instrumented" would be as wrong as calling it a
# measured zero -- and it is the one distinction this tool exists to keep. Tags
# are 'YYYY-MM-DDTHHMM-slug', so the fixed-width prefix sorts as a string.
INSTRUMENTED_BUILD = "2026-11-02T1400-cascade-units-nashheld"


def _is_instrumented(build, n_rows):
    """True when this log's build is known to carry the [NASH_HELD] emit paths."""
    if n_rows:
        return True                       # proof: it emitted
    b = (build or "").strip()
    return bool(b) and b != "?" and b >= INSTRUMENTED_BUILD

# [NASH_HELD] row fields. Two shapes share the tag: candidate rows carry
# bps/cpc/surplus, gate rows carry delay_s/limit_s. `slack` / `slack_s` is the
# signed margin against the binding constraint in both.
RE_HELD = {
    "inter": re.compile(r"\binter=(\d+)"),
    "t": re.compile(r"\bt=([\d.]+)"),
    "bus": re.compile(r"\bbus=(\d+)"),
    "stage": re.compile(r"\bstage=(\w+)"),
    "why": re.compile(r"\bwhy=(\w+)"),
    "at": re.compile(r"\bat=(\S+)"),
    "bps": re.compile(r"\bbps=(-?[\d.]+)"),
    "cpc": re.compile(r"\bcpc=(-?[\d.]+)"),
    "surplus": re.compile(r"\bsurplus=(-?[\d.]+)"),
    "nadj": re.compile(r"\bnadj=(-?[\d.]+)"),
    "delay_s": re.compile(r"\bdelay_s=(-?[\d.]+)"),
    "limit_s": re.compile(r"\blimit_s=(-?[\d.]+)"),
    "slack": re.compile(r"\bslack=(-?[\d.]+)"),
    "slack_s": re.compile(r"\bslack_s=(-?[\d.]+)"),
    "nrej": re.compile(r"\bnrej=(\d+)"),
}

WHY_ORDER = ["gain_T", "surplus", "ratio", "min_gain", "min_delay", "no_candidates"]


# --------------------------------------------------------------------------- #
# log discovery                                                               #
# --------------------------------------------------------------------------- #
def identify(path):
    """Read only the head of a log and return its identity, or None."""
    seed = arm = build = sha = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for _ in range(_HEAD_LINES):
                line = fh.readline()
                if not line:
                    break
                if seed is None:
                    m = RE_SEED.search(line)
                    if m:
                        seed = int(m.group(1))
                if arm is None:
                    m = RE_ARM.search(line)
                    if m:
                        arm = m.group(1)
                if build is None:
                    m = RE_BUILD.search(line)
                    if m:
                        build = m.group(1)
                if sha is None:
                    m = RE_HASH.search(line)
                    if m:
                        sha = m.group(1)[:12]
                if seed is not None and arm is not None and build is not None:
                    break
    except OSError:
        return None
    if seed is None and arm is None:
        return None
    return {"path": path, "seed": seed, "arm": arm or "?",
            "build": build or "?", "sha": sha or "",
            "mtime": os.path.getmtime(path)}


def discover(log_dir, days, use_all):
    """Newest log per (seed, arm). Identity comes from the file head only."""
    paths = sorted(glob.glob(os.path.join(log_dir, "Aimsun_TSP_Log_*.txt")))
    if not paths:
        return [], {"old": 0, "noid": 0, "total": 0}
    cutoff = 0.0
    if days and not use_all:
        newest = max(os.path.getmtime(p) for p in paths)
        cutoff = newest - days * 86400.0
    idents = []
    n_old = n_noid = 0
    for p in paths:
        try:
            if cutoff and os.path.getmtime(p) < cutoff:
                n_old += 1
                continue
        except OSError:
            continue
        ident = identify(p)
        if ident is None:
            # no seed and no arm in the head: not a corridor run log
            n_noid += 1
            continue
        idents.append(ident)
    idents.sort(key=lambda d: d["mtime"], reverse=True)
    newest = {}
    dupes = collections.Counter()
    for d in idents:
        key = (d["seed"], d["arm"])
        if key in newest:
            dupes[key] += 1
            continue
        newest[key] = d
    runs = []
    for key, d in newest.items():
        d = dict(d)
        d["older_dupes"] = dupes.get(key, 0)
        runs.append(d)
    runs.sort(key=lambda d: (d["seed"] if d["seed"] is not None else -1, d["arm"]))
    return runs, {"old": n_old, "noid": n_noid, "total": len(paths)}


# --------------------------------------------------------------------------- #
# log scan                                                                    #
# --------------------------------------------------------------------------- #
def new_scan():
    return {
        "decisions": collections.Counter(),   # DECISION=<kind>
        "reasons": collections.Counter(),     # normalised NO_ACTION reason
        "no_action": 0,                       # EVERY refused decision
        "held": 0,                            # "decider held: no net-positive action"
        "prewarm": 0,                         # "decider gated: pre-warm (t<N s)"
        "held_rows": collections.Counter(),   # [NASH_HELD] rows by why
        "held_decisions": collections.defaultdict(set),
        "slack": collections.defaultdict(list),
        "bps_minus_cpc": collections.defaultdict(list),
        "junctions": set(),
        "candidate_rows": 0,
        "trunc_lines": 0,
        "lines": 0,
    }


def scan(path):
    st = new_scan()
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            st["lines"] += 1
            i = line.find("[")
            if i < 0:
                continue
            if "[REWARD_TSP]" in line:
                m = RE_DEC.search(line)
                if m:
                    kind = m.group(1)
                    st["decisions"][kind] += 1
                    if kind == "NO_ACTION":
                        st["no_action"] += 1
                        p = RE_PAREN.search(line)
                        reason = (p.group(1) if p else "?").strip()
                        # collapse numbers so "pre-warm (t<420s)" groups together
                        norm = re.sub(r"\d+(?:\.\d+)?", "N", reason)
                        st["reasons"][norm] += 1
                        low = reason.lower()
                        if "no net-positive action" in low:
                            st["held"] += 1
                        elif "pre-warm" in low:
                            st["prewarm"] += 1
                continue
            if "[NASH_HELD]" not in line:
                continue
            if RE_HELD["nrej"].search(line):
                # truncation notice: candidates past NASH_HELD_MAX_CANDS were not
                # printed, so they CANNOT appear in the tallies below. Counted so
                # the report can say so instead of silently under-reporting.
                st["trunc_lines"] += 1
                continue
            why = RE_HELD["why"].search(line)
            if not why:
                continue
            why = why.group(1)
            st["held_rows"][why] += 1
            t = RE_HELD["t"].search(line)
            bus = RE_HELD["bus"].search(line)
            stage = RE_HELD["stage"].search(line)
            key = (t.group(1) if t else "?",
                   bus.group(1) if bus else "?",
                   stage.group(1) if stage else "?")
            st["held_decisions"][why].add(key)
            st["candidate_rows"] += 1
            inter = RE_HELD["inter"].search(line)
            if inter:
                st["junctions"].add(inter.group(1))
            for k in ("slack", "slack_s"):
                m = RE_HELD[k].search(line)
                if m:
                    try:
                        st["slack"][why].append(float(m.group(1)))
                    except ValueError:
                        pass
                    break
            b = RE_HELD["bps"].search(line)
            c = RE_HELD["cpc"].search(line)
            if b and c:
                try:
                    st["bps_minus_cpc"][why].append(
                        float(b.group(1)) - float(c.group(1)))
                except ValueError:
                    pass
    return st


# --------------------------------------------------------------------------- #
# published ladder                                                            #
# --------------------------------------------------------------------------- #
def load_ladder(path):
    if not path or not os.path.exists(path):
        return {}, []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    by = {}
    for r in rows:
        try:
            seed = int(float(r.get("run_seed") or -1))
        except (TypeError, ValueError):
            continue
        arm = (r.get("run_experiment") or "?").strip()
        by[(seed, arm)] = r
    return by, rows


def _f(row, key):
    try:
        return float(row.get(key) or "")
    except (TypeError, ValueError):
        return None


def _fmt(v, width, dec=1):
    if v is None:
        return "-".rjust(width)
    return ("%." + str(dec) + "f") % v
# --------------------------------------------------------------------------- #
# report                                                                      #
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Tally [NASH_HELD] binding constraints per seed and compare "
                    "against the published ladder.")
    ap.add_argument("--logs", default=os.path.join(HERE, "logan_road_new", "logs"))
    ap.add_argument("--csv", default=os.path.join(
        HERE, "paper_ladder_priority_logan.csv"))
    ap.add_argument("--run-csv", default="",
                    help="results CSV of a NEW run (e.g. the instrumented re-run); "
                         "its objective is shown beside the published one so a "
                         "tally is never read against the wrong build")
    ap.add_argument("--seeds", default="", help="e.g. 600,700 (default: all found)")
    ap.add_argument("--arms", default="", help="arm-name substring filter")
    ap.add_argument("--days", type=int, default=30,
                    help="ignore logs older than N days (default 30; 0 = all)")
    ap.add_argument("--all", action="store_true",
                    help="scan every log regardless of age")
    ap.add_argument("--all-runs", action="store_true",
                    help="report every arm, not just the ones in the ladder CSV")
    ap.add_argument("--verbose", action="store_true", help="per-run detail")
    args = ap.parse_args(argv)

    seed_filter = set()
    if args.seeds:
        for s in args.seeds.split(","):
            s = s.strip()
            if s:
                seed_filter.add(int(s))
    arm_filter = args.arms.strip().lower()

    runs, dstat = discover(args.logs, args.days, args.all)
    if seed_filter:
        runs = [r for r in runs if r["seed"] in seed_filter]
    if arm_filter:
        runs = [r for r in runs if arm_filter in r["arm"].lower()]

    ladder, ladder_rows = load_ladder(args.csv)
    # Default scope is the LADDER: 290 runs across every arm ever tried is noise
    # for this question, and the table is meant to sit beside those 35 rows.
    if ladder and not args.all_runs:
        runs = [r for r in runs if (r["seed"], r["arm"]) in ladder]
    if seed_filter and ladder_rows:
        ladder_rows = [r for r in ladder_rows
                       if str(r.get("run_seed")) in {str(s) for s in seed_filter}]

    print("=" * 108)
    print("NASH_HELD BINDING CONSTRAINTS PER SEED")
    print("  logs : %s" % args.logs)
    print("  csv  : %s" % (args.csv if ladder_rows else "(not found -- no ladder join)"))
    print("  runs : %d newest log(s) per (seed, arm)  [dir has %d logs: %d "
          "older than --days, %d without seed/arm in the header]"
          % (len(runs), dstat["total"], dstat["old"], dstat["noid"]))
    if ladder and not args.all_runs:
        print("  scope: arms/seeds present in the ladder CSV (--all-runs to widen)")
    if seed_filter:
        print("  seeds: %s" % ",".join(str(s) for s in sorted(seed_filter)))
    print("=" * 108)

    scans = []
    for r in runs:
        st = scan(r["path"])
        r = dict(r)
        r["st"] = st
        scans.append(r)

    # ---------------- A. inventory ----------------
    print("\nA. LOG INVENTORY + DECISION MIX")
    # 30 chars keeps the tag's informative slug: at 13 the two candidate builds
    # both read '2026-11-02T14' and the column could not answer the one question
    # it exists for -- whether this log is on the instrumented build.
    print("  %-5s %-36s %-30s %9s %7s %8s %7s %8s  %s"
              % ("seed", "arm", "engine build", "decisions", "commit",
                 "no_action", "prewarm", "net-neg", "NASH_HELD"))
    for r in scans:
        st, build = r["st"], r["build"]
        commits = sum(v for k, v in st["decisions"].items() if k != "NO_ACTION")
        n_rows = sum(st["held_rows"].values())
        if n_rows:
            status = "instrumented (%d rows)" % n_rows
        elif _is_instrumented(build, n_rows):
            status = "instrumented (0 rows)"
        else:
            status = "not instrumented"
        print("  %-5s %-36s %-30s %9d %7d %8d %7d %8d  %s"
              % (r["seed"], r["arm"][:36], build[:30],
                 sum(st["decisions"].values()), commits, st["no_action"],
                 st["prewarm"], st["held"], status))
        if args.verbose and st["reasons"]:
            for reason, n in st["reasons"].most_common():
                print("        %6d  %s" % (n, reason))

    # ---------------- B. why tally by seed ----------------
    instrumented = [r for r in scans if sum(r["st"]["held_rows"].values())]
    print("\nB. [NASH_HELD] WHY TALLY BY SEED"
          "   (rows = REJECTED CANDIDATES, not decisions)")
    if not instrumented:
        print("  No log in this selection carries [NASH_HELD].")
        if any(_is_instrumented(r["build"], 0) for r in scans):
            print("  But some logs here ARE on the instrumented build, so zero rows")
            print("  means the emit paths never fired on those arms -- not that the")
            print("  instrumentation is missing. Check the arm: cooperative and")
            print("  MARL arms never reach the picker.")
        else:
            print("  The instrumentation landed on ENGINE_BUILD %s;"
                  % INSTRUMENTED_BUILD)
            print("  every log in this selection predates it, so the why-columns")
            print("  below read '-' (NOT MEASURED) rather than 0.")
    else:
        seedy = collections.defaultdict(lambda: collections.Counter())
        seedj = collections.defaultdict(set)
        for r in instrumented:
            seedy[r["seed"]].update(r["st"]["held_rows"])
            seedj[r["seed"]] |= r["st"]["junctions"]
        whys = [w for w in WHY_ORDER
                if any(seedy[s].get(w) for s in seedy)]
        extra = sorted({w for s in seedy for w in seedy[s]} - set(whys))
        whys += extra
        print("  %-6s %-8s %s  %8s"
              % ("seed", "rows",
                 " ".join("%6s" % w[:8] for w in whys), "junctions"))
        for s in sorted(seedy):
            row = seedy[s]
            cells = " ".join("%6s" % row.get(w, 0) for w in whys)
            print("  %-6s %-8d %s  %8d"
                  % (s, sum(row.values()), cells, len(seedj[s])))
        print("\n  slack (signed margin against the binding constraint; 0 = nearly"
              " accepted)")
        print("  %-10s %8s %10s %10s %10s" % ("why", "n", "min", "median", "max"))
        allslack = collections.defaultdict(list)
        for r in instrumented:
            for w, vals in r["st"]["slack"].items():
                allslack[w].extend(vals)
        for w in whys:
            v = allslack.get(w) or []
            if not v:
                continue
            print("  %-10s %8d %10.1f %10.1f %10.1f"
                  % (w, len(v), min(v), statistics.median(v), max(v)))
        trunc = sum(r["st"]["trunc_lines"] for r in instrumented)
        if trunc:
            print("  %d decision(s) hit NASH_HELD_MAX_CANDS and printed a"
                  " truncation line; those extra candidates are NOT in the"
                  " counts above."
                  % trunc)

    # ---------------- C. against the published ladder ----------------
    print("\nC. VS THE PUBLISHED LADDER")
    if not ladder_rows:
        print("  (no ladder CSV -- skipping)")
    else:
        # per-seed NO_TSP baseline for the objective
        base = {}
        for r in ladder_rows:
            if (r.get("run_experiment") or "").strip().upper() == "NO_TSP":
                v = _f(r, "stats_Objective_PaxPerDelayHr")
                if v is not None:
                    base[int(float(r["run_seed"]))] = v
        by_arm = {}
        for r in scans:
            by_arm[(r["seed"], r["arm"])] = r

        # NEW-RUN JOIN (optional). After the instrumented re-run the tallies come
        # from the NEW logs while --csv still holds the PUBLISHED numbers; showing
        # only the published objective next to new tallies would invite reading a
        # delta against the wrong build. Both are printed, side by side.
        new_by, new_base = {}, {}
        if args.run_csv:
            if not os.path.exists(args.run_csv):
                print("  (--run-csv not found: %s -- new-run columns omitted)"
                      % args.run_csv)
            else:
                new_by, new_rows = load_ladder(args.run_csv)
                for (seed, arm), rr in new_by.items():
                    if arm.strip().upper() == "NO_TSP":
                        v = _f(rr, "stats_Objective_PaxPerDelayHr")
                        if v is not None:
                            new_base[seed] = v

        print("  obj = stats_Objective_PaxPerDelayHr (higher is better);"
              " delta vs NO_TSP on the SAME seed")
        print("  dec/commit/noact come from the newest matching log."
              + ("  obj_new = %s" % args.run_csv if new_by else ""))
        hdr = "  %-5s %-36s %8s %7s" % ("seed", "arm", "obj", "vsNO")
        if new_by:
            hdr += " %8s %7s" % ("obj_new", "vsNO_n")
        hdr += " %5s %6s %5s  %s" % (
            "dec", "commit", "noact",
            "binding constraints (cand rows: gain_T/surplus/ratio;"
            " decision rows: min_gain/min_delay)")
        print(hdr)
        for r in sorted(ladder_rows,
                        key=lambda r: (int(float(r["run_seed"])),
                                       (r.get("run_experiment") or ""))):
            seed = int(float(r["run_seed"]))
            arm = (r.get("run_experiment") or "?").strip()
            obj = _f(r, "stats_Objective_PaxPerDelayHr")
            dlt = None
            if obj is not None and base.get(seed):
                dlt = 100.0 * (obj - base[seed]) / base[seed]
            run = by_arm.get((seed, arm))
            if run:
                st = run["st"]
                dec = sum(st["decisions"].values()) or None
                commit = sum(v for k, v in st["decisions"].items()
                             if k != "NO_ACTION")
                held = st["no_action"] or None
                hr = st["held_rows"]
                if sum(hr.values()):
                    bits = ["%s=%d" % (w, hr[w]) for w in WHY_ORDER if hr.get(w)]
                    for w in sorted(set(hr) - set(WHY_ORDER)):
                        bits.append("%s=%d" % (w, hr[w]))
                    why = " ".join(bits)
                elif _is_instrumented(run["build"], 0):
                    # Instrumented build, zero rows: a MEASURED zero, not a gap.
                    # The inert/co-op arms never reach the picker, so they should
                    # land here on every seed of the patched build.
                    why = "0  (measured: never reached the picker)"
                else:
                    why = "-  (not instrumented)"
            else:
                dec = commit = held = None
                why = "-  (no log in selection)"
            line = "  %-5d %-36s %8s %7s" % (
                seed, arm[:36], _fmt(obj, 8, 3),
                ("%6.1f%%" % dlt) if dlt is not None else "      -")
            if new_by:
                rr = new_by.get((seed, arm))
                obj2 = _f(rr, "stats_Objective_PaxPerDelayHr") if rr else None
                dlt2 = None
                if obj2 is not None and new_base.get(seed):
                    dlt2 = 100.0 * (obj2 - new_base[seed]) / new_base[seed]
                line += " %8s %7s" % (
                    _fmt(obj2, 8, 3),
                    ("%6.1f%%" % dlt2) if dlt2 is not None else "      -")
            line += " %5s %6s %5s  %s" % (
                dec if dec is not None else "-",
                commit if commit is not None else "-",
                held if held is not None else "-", why)
            print(line)

        missing = [r for r in ladder_rows
                   if (int(float(r["run_seed"])),
                       (r.get("run_experiment") or "?").strip()) not in by_arm]
        extra = [r for r in scans
                 if (r["seed"], r["arm"]) not in ladder]
        if missing:
            print("\n  ladder rows with no matching log in this selection: %d"
                  % len(missing))
        if extra:
            print("  logs with no ladder row (reruns / other arms): %s"
                  % ", ".join("%s/%s" % (r["seed"], r["arm"]) for r in extra[:6]))

    print("\n  '-' in a why-column means NOT MEASURED (log predates the"
          " instrumentation); '0' means measured zero.")
    print("  [NASH_HELD] appeared on ENGINE_BUILD %s and later."
          % INSTRUMENTED_BUILD)
    return 0


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    sys.exit(main())
