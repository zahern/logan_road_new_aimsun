"""Count DISTINCT outcomes per variant, N runs each.

A two-run comparison is far too weak here: this scenario has a wide outcome
distribution, so any two runs match by chance often enough to call a broken
variant deterministic. This reports how many distinct results N runs produce.
1 distinct == deterministic.
"""
from __future__ import annotations

import collections
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SUMO = os.path.join(os.environ.get("SUMO_HOME",
                                   r"C:\Program Files (x86)\Eclipse\Sumo"),
                    "bin", "sumo.exe")
END = 900
N = 4


def one(cfg, extra, seed=300, tag="m"):
    trip = os.path.join(HERE, "mx_%s.xml" % tag)
    cmd = [SUMO, "-c", cfg, "--seed", str(seed), "--end", str(END),
           "--no-step-log", "true", "--duration-log.statistics", "false",
           "--tripinfo-output", trip] + extra
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        return None
    trips = ET.parse(trip).getroot().findall("tripinfo")
    return (len(trips),
            round(sum(float(t.get("timeLoss", 0)) for t in trips), 1))


def variant(label, cfg, extra):
    outs = []
    for i in range(N):
        o = one(cfg, extra, tag="%s%d" % (label.replace(" ", "_"), i))
        if o is None:
            print("%-34s ERROR" % label)
            return
        outs.append(o)
    c = collections.Counter(outs)
    print("%-34s distinct=%d/%d   %s"
          % (label, len(c), N, ", ".join("n=%d TL=%.0f x%d" % (k[0], k[1], v)
                                         for k, v in c.most_common())))


def main():
    base = os.path.join(HERE, "kg.sumocfg")
    fixed = os.path.join(HERE, "kg_fixed.sumocfg")
    if not os.path.exists(fixed):
        fixed = base
    print("N=%d runs per variant, end=%d, seed 300\n" % (N, END))
    variant("baseline", base, [])
    variant("speeddev 0", base, ["--default.speeddev", "0"])
    variant("no-internal-links", base, ["--no-internal-links", "true"])
    variant("teleport 300", base, ["--time-to-teleport", "300"])
    variant("fixed greengrades", fixed, [])
    variant("fixed + speeddev 0", fixed, ["--default.speeddev", "0"])
    variant("fixed + no-internal-links", fixed,
            ["--no-internal-links", "true"])
    variant("fixed + teleport 300", fixed, ["--time-to-teleport", "300"])


if __name__ == "__main__":
    sys.exit(main())
