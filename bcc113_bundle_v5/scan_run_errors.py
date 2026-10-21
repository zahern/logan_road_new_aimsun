"""scan_run_errors.py -- poll the live Aimsun log and flag errors as they appear.

Run LOCALLY on Windows (reads C:\\...\\kg\\logs directly; nothing on the HPC node):

    python scan_run_errors.py                 # follow newest log, poll 30 s
    python scan_run_errors.py --once          # single scan, no polling
    python scan_run_errors.py --interval 15  # custom poll interval

Watches the newest kg\\logs\\Aimsun_TSP_Log_*.txt, follows new lines as the run
writes them, and prints anything that looks like a failure. On exit prints a
summary. Ctrl+C to stop.
"""

import argparse
import glob
import os
import re
import sys
import time

LOG_DIR = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\kg\logs"
LOG_GLOB = os.path.join(LOG_DIR, "Aimsun_TSP_Log_*.txt")

# (category, regex). Order matters: first match wins.
ERROR_RULES = [
    ("TRACEBACK", re.compile(
        r"Traceback \(most recent call last\)|"
        r"^\s*File \".*\", line \d+|"
        r"\w+Error: |"
        r"Exception calling")),
    ("CRASH", re.compile(r"update crashed inter=|stop_simulation")),
    ("WRITE_FAIL", re.compile(
        r"\[REWARD_CYCLE_CSV\] write error|"
        r"\[QUEUE_SNAP\] write failed|"
        r"\[FINISH\] stats error|"
        r"summary unavailable")),
    ("FALLBACK", re.compile(
        r"\[AUTO_DET\].*FALLBACK|"
        r"\[FINISH\] network debug: source=akiest-system\+incr-fill|"
        r"\[PLAN_SCAN\].*apifail|"
        r"\[PHASEMAP\].*apifail")),
    ("PAST_FF", re.compile(r"GAP_scan_no_delta_past_ff")),   # real hole, not within-budget
    ("SWALLOW", re.compile(r"\[SWALLOWED\].*:[1-9]")),       # any non-zero swallow count
    ("VALIDATE", re.compile(r"\[VALIDATE\].*([1-9]\d* errors|[1-9]\d* warnings)")),
    ("NEVER_STARTED", re.compile(r"sim NEVER STARTED|\[SETUP\].*aborted")),
]

# Lower-severity progress lines worth surfacing (not errors).
INFO_RULES = [
    ("LOAD", re.compile(r"\[LOAD\] AAPILoad complete")),
    ("ARM", re.compile(r"\[ARM\] exp=")),
    ("DS_SELF_GATE", re.compile(r"\[DS_SELF_GATE\]")),
    ("DS_TERMS", re.compile(r"\[DS_TERMS\]")),
    ("FINISH", re.compile(r"\[FINISH\] stats saved OK")),
    ("GATE", re.compile(r"\[DS GATE\]")),
]


def newest_log():
    files = glob.glob(LOG_GLOB)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def classify(line):
    for cat, rx in ERROR_RULES:
        if rx.search(line):
            return cat
    for cat, rx in INFO_RULES:
        if rx.search(line):
            return "info:" + cat
    return None


def scan(path, offset, seen, counts, loud_info):
    """Read `path` from `offset`; return new offset. Updates counts/seen."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return offset
    if size < offset:
        offset = 0                      # file truncated / rotated
    if size == offset:
        return offset
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            new = f.read()
    except OSError:
        return offset
    offset += len(new)
    for line in new.splitlines():
        cat = classify(line)
        if not cat:
            continue
        key = (cat, line)
        if key in seen:
            continue
        seen.add(key)
        counts[cat] = counts.get(cat, 0) + 1
        if cat.startswith("info:"):
            if loud_info:
                print("    %s" % line, flush=True)
            continue
        # error: print with a marker so it stands out in a long log
        print("  [%s] %s" % (cat, line), flush=True)
    return offset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=30.0,
                    help="seconds between polls (default 30)")
    ap.add_argument("--once", action="store_true",
                    help="single scan, then exit")
    ap.add_argument("--loud-info", action="store_true",
                    help="also print progress lines (ARM/DS_TERMS/FINISH)")
    args = ap.parse_args()

    path = newest_log()
    if not path:
        print("no log found matching %s" % LOG_GLOB)
        return 1

    print("watching: %s" % path, flush=True)
    print("error rules: %s" % ", ".join(c for c, _ in ERROR_RULES), flush=True)
    print("=" * 78, flush=True)

    offset = os.path.getsize(path)      # start at end: only NEW errors
    seen = set()
    counts = {}
    polls = 0

    try:
        while True:
            cur = newest_log()
            if cur != path:
                # a new run started: reset and note it
                print("=" * 78, flush=True)
                print("NEW LOG: %s" % cur, flush=True)
                print("=" * 78, flush=True)
                path = cur
                offset = 0
                seen.clear()
            offset = scan(path, offset, seen, counts, args.loud_info)
            polls += 1
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass

    print("=" * 78, flush=True)
    print("SUMMARY after %d poll(s) -- %d distinct flagged line(s)" % (polls, sum(counts.values())))
    if not counts:
        print("  clean: no error/progress lines matched")
    for cat in sorted(counts, key=lambda c: -counts[c]):
        tag = "INFO " if cat.startswith("info:") else "ERR  "
        print("  %s %-22s %d" % (tag, cat, counts[cat]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
