"""
Archive duplicate result folders, keeping the NEWEST per (arm, seed).

The batch's executeAction re-issue used to fire a second simulation for the same
(arm, seed), each writing its own timestamped folder under kg/results/. Only the
newest feeds the CSV; the rest are orphaned (wasted compute + disk).

This MOVES the older twins to kg/results/_archive_dupes_<ts>/ -- it never deletes,
so nothing is lost.

Usage:
    python archive_dupe_results.py            # dry run (count only)
    python archive_dupe_results.py --apply    # do the move
"""
import os, re, sys, time, shutil
from collections import defaultdict

RESULTS = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\kg\results"
APPLY = "--apply" in sys.argv
PAT = re.compile(r"^(.+?)_seed(\d+)_")

def main():
    entries = [d for d in os.scandir(RESULTS)
               if d.is_dir() and not d.name.startswith("_archive")]
    groups = defaultdict(list)
    for d in entries:
        m = PAT.match(d.name)
        if not m:
            groups[("__UNMATCHED__", d.name)].append(d)
            continue
        groups[(m.group(1), m.group(2))].append(d)

    to_move = []
    for key, ds in groups.items():
        if len(ds) <= 1:
            continue
        ds.sort(key=lambda d: d.stat().st_mtime)
        to_move.extend(ds[:-1])          # all but the newest

    print("result folders:", len(entries))
    print("(arm,seed) groups:", len(groups))
    print("duplicates to archive:", len(to_move))
    top = sorted(((k, len(v)) for k, v in groups.items() if len(v) > 1),
                 key=lambda t: -t[1])[:8]
    print("worst groups:", [(f"{k[0]}|{k[1]}", n) for k, n in top])

    if not APPLY:
        print("\nDRY RUN -- pass --apply to move them.")
        return

    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(RESULTS, "_archive_dupes_%s" % stamp)
    os.makedirs(dest, exist_ok=True)
    moved = 0; err = 0
    for d in to_move:
        try:
            shutil.move(d.path, os.path.join(dest, d.name))
            moved += 1
        except Exception:
            err += 1
    print("\nmoved %d folders to %s (errors=%d)" % (moved, dest, err))

if __name__ == "__main__":
    main()
