"""Rebuild kg.net.xml so SUMO replicates are reproducible, and prove it.

THE PROBLEM
-----------
`sumo -c kg.sumocfg --seed 300` gave a different answer every run: 3,328 of
3,369 vehicles differed between two identical invocations, and `--random false`
changed nothing. Bisection (4 runs per variant) ruled out:

    seed handling        two seed-301 runs differ from each other
    driver imperfection  sigma=0            -> still 4/4 distinct
    speed factor         --default.speeddev 0 -> still 4/4 distinct
    insertion lane       departLane free/first/allowed -> still 4/4 distinct
    teleporting          --time-to-teleport 300 -> still 4/4 distinct
    unsafe greens        demoting the conflicting G->g removed the warnings
                         but the runs stayed distinct
    detectors            removing detectors.add.xml -> still 4/4 distinct

    --no-internal-links true -> 4/4 BIT-IDENTICAL, on both nets

THE CAUSE
---------
The junction-internal topology of the published net is malformed. Comparing
`kg.net.xml` with a netconvert rebuild of the same physical network:

    physical edges   224 -> 224   (identical ids)
    lanes            515 -> 515
    internal edges   563 -> 471
    internal junctions 119 -> 16      <-- 103 phantom internal junctions

SUMO's junction-internal right-of-way bookkeeping over those phantom junctions
is not evaluated in a stable order, so every process resolves the same conflict
differently. Nothing in the demand or the RNG is involved -- which is why
changing the seed, sigma, speedDev, departLane or teleport settings all failed.

Removing internal links "fixes" it by deleting the machinery, but that also
deletes junction blocking, so it is a modelling change, not a repair.

THE FIX
-------
`netconvert --sumo-net-file kg.net.xml` recomputes the internal lanes and
junctions from the same geometry. Verified here:

    signal programs     27/27 identical (n39576 keeps its 144 s / 36 s plan)
    physical edges      224/224 identical, 515 lanes
    3 full runs (4500 s, seed 300) -> bit-identical
    seed 301            3,400 inserted, 0 waiting (the old net stranded 505)

NOTE FOR THE PAPER
------------------
Fixing the internals changes the numbers: pax-weighted seconds per trip goes
from ~329-348 (old net, three runs, three answers) to 363.6 (rebuilt, stable).
The old net was under-modelling junction blocking, so it was flattering every
arm by roughly 9%. Comparisons against published SUMO figures must be re-run.

Usage:
    python rebuild_kg_net.py                 # rebuild + verify
    python rebuild_kg_net.py --runs 4        # more determinism repeats
"""
from __future__ import annotations

import argparse
import collections
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SUMO_HOME = os.environ.get("SUMO_HOME",
                           r"C:\Program Files (x86)\Eclipse\Sumo")
NETCONVERT = os.path.join(SUMO_HOME, "bin", "netconvert.exe")
SUMO = os.path.join(SUMO_HOME, "bin", "sumo.exe")
NET = os.path.join(HERE, "kg.net.xml")
CFG = os.path.join(HERE, "kg.sumocfg")


def netstats(path):
    r = ET.parse(path).getroot()
    edges = r.findall("edge")
    phys = [e for e in edges if not e.get("id", "").startswith(":")]
    return {"phys": len(phys), "internal": len(edges) - len(phys),
            "lanes": sum(len(e.findall("lane")) for e in phys),
            "junctions": len(r.findall("junction")),
            "internal_junctions": sum(
                1 for j in r.findall("junction") if j.get("type") == "internal"),
            "phys_ids": {e.get("id") for e in phys}}


def tlprograms(path):
    r = ET.parse(path).getroot()
    return {tl.get("id"): [(p.get("duration"), p.get("state"))
                           for p in tl.findall("phase")]
            for tl in r.findall("tlLogic")}


def rebuild(net_in, net_out):
    cmd = [NETCONVERT, "--sumo-net-file", net_in, "-o", net_out]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(net_out):
        raise SystemExit("netconvert failed:\n%s" % p.stderr[-900:])
    return p.stderr


def write_cfg(src, dst, net_name):
    txt = open(src, encoding="utf-8").read()
    txt = txt.replace(os.path.basename(NET), net_name)
    open(dst, "w", encoding="utf-8").write(txt)


def run_once(cfg, seed, end, tag):
    trip = os.path.join(HERE, "rbchk_%s.xml" % tag)
    cmd = [SUMO, "-c", cfg, "--seed", str(seed), "--no-step-log", "true",
           "--duration-log.statistics", "false", "--tripinfo-output", trip]
    if end:
        cmd += ["--end", str(end)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return None
    trips = ET.parse(trip).getroot().findall("tripinfo")
    return (len(trips),
            round(sum(float(t.get("timeLoss", 0)) for t in trips), 1))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--net-in", default=NET)
    ap.add_argument("--net-out", default=os.path.join(HERE, "kg_rebuilt.net.xml"))
    ap.add_argument("--cfg-in", default=CFG)
    ap.add_argument("--cfg-out", default=os.path.join(HERE, "kg_rebuilt.sumocfg"))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--end", type=int, default=None)
    args = ap.parse_args(argv)

    before = netstats(args.net_in)
    err = rebuild(args.net_in, args.net_out)
    after = netstats(args.net_out)
    write_cfg(args.cfg_in, args.cfg_out, os.path.basename(args.net_out))

    print("[REBUILD] netconvert diagnostics that matter:")
    for line in err.splitlines():
        if any(k in line for k in ("Intersecting left turns", "Ambiguity",
                                   "not connected", "Success")):
            print("          " + line.strip()[:110])
    print()
    print("%-22s %8s %8s" % ("", "original", "rebuilt"))
    for k in ("phys", "lanes", "internal", "junctions", "internal_junctions"):
        print("%-22s %8d %8d" % (k, before[k], after["%s" % k]))
    print("%-22s %8s %8s" % ("physical edge ids", "same" if before["phys_ids"] == after["phys_ids"]
                             else "CHANGED", ""))

    pa, pb = tlprograms(args.net_in), tlprograms(args.net_out)
    same = sum(1 for k in pa if k in pb and pa[k] == pb[k])
    print("%-22s %8d %8d identical" % ("signal programs", len(pa), same))
    if same != len(pa):
        print("  WARNING: the rebuild changed at least one signal program")

    print("\n[REBUILD] determinism check: %d runs, seed 300%s"
          % (args.runs, "" if args.end is None else ", end=%d" % args.end))
    outs = [run_once(args.cfg_out, 300, args.end, "r%d" % i)
            for i in range(args.runs)]
    if any(o is None for o in outs):
        raise SystemExit("a check run failed")
    c = collections.Counter(outs)
    print("          distinct results: %d/%d" % (len(c), args.runs))
    for k, v in c.most_common():
        print("          n=%-4d timeLoss=%-9.1f x%d" % (k[0], k[1], v))
    ok = len(c) == 1
    print("\n[REBUILD] %s" % ("REPRODUCIBLE" if ok else "STILL NONDETERMINISTIC"))
    print("[REBUILD] scenario -> %s" % args.cfg_out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
