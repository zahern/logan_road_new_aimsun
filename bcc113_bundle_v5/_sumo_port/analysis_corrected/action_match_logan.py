"""Compare chosen TSP actions between the SUMO and Aimsun ledgers, arm by arm.

The reward_cycle ledger records one row per candidate action per decision, with
is_chosen=1 on the action that was taken. That is the only artefact showing what
the controller did, as opposed to how many bus events a summary counter blamed.

The two platforms do NOT log at the same granularity: a SUMO run writes ~310k
rows and ~13k chosen actions, an Aimsun run ~4k rows and ~110 chosen actions,
because SUMO logs a decision every junction every step while Aimsun logs when a
bus arms the controller. Raw chosen counts are therefore not comparable, and the
with-bus split is only meaningful once bus_in_zone is populated (it is not, in
the SUMO ledger -- see the warning the tool prints).

SUMO ledgers come from the sandbox dirs the HPC runs leave behind, keyed by the
<ARM>_seed<N>_sections.json name. Aimsun ledgers are found under kg/logs (the
ladder runs there carry no seed in the filename, so they are pooled per arm).

    python action_match_logan.py
    python action_match_logan.py --sumo-parts Z:\\tsp\\sumo_hpc
"""
import argparse
import collections
import csv
import glob
import os
import re

SUMO_ROOT = r"Z:\tsp\sumo_hpc"
AIMSUN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEEDS = [300, 400, 500, 600, 700]
ARMS = ["CHAMP_NO_TSP",
        "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2",
        "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM",
        "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2",
        "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2_LIGHTSIM"]
CLASSES = ("NO_ACTION", "GE", "GR", "ER", "INS")


def _cls(action):
    a = str(action or "").upper()
    for p in CLASSES:
        if a.startswith(p):
            return p
    return a or "?"


def _chosen(row):
    return str(row.get("is_chosen", "")).strip().lower() in ("true", "1")


def _bus(row):
    return str(row.get("bus_in_zone", "")).strip().lower() in ("1", "true", "1.0")


def mix(path):
    """(chosen with a bus in zone, chosen with none, total rows)"""
    withb, nob = collections.Counter(), collections.Counter()
    rows = 0
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for r in csv.DictReader(fh):
            rows += 1
            if not _chosen(r):
                continue
            (withb if _bus(r) else nob)[_cls(r.get("action"))] += 1
    return withb, nob, rows


def find_sumo(root):
    """{(arm, seed): newest sandbox ledger}"""
    best = {}
    for p in glob.glob(os.path.join(root, "_sandbox_*", "*_sections.json")):
        name = os.path.basename(p).replace("_sections.json", "")
        m = re.match(r"(.+?)_seed(\d+)$", name)
        if not m or m.group(1) not in ARMS:
            continue
        d = os.path.dirname(p)
        led = sorted(glob.glob(os.path.join(d, "logs", "reward_cycle_*.csv")))
        if not led:
            continue
        key = (m.group(1), int(m.group(2)))
        stamp = os.path.getmtime(led[0])
        if key not in best or stamp > best[key][0]:
            best[key] = (stamp, led[0])
    return {k: v[1] for k, v in best.items()}


def find_aimsun(root):
    """{arm: [ledgers]} under kg/logs (filenames carry no seed)."""
    out = collections.defaultdict(list)
    for p in glob.glob(os.path.join(root, "kg", "logs", "reward_cycle_*.csv")):
        arm = next((a for a in ARMS if a in os.path.basename(p)), None)
        if arm:
            out[arm].append(p)
    return out


def _line(label, n, withb, nob, rows):
    w = sum(withb.values()) or 1
    share = lambda c: 100.0 * withb.get(c, 0) / w
    return ("%-26s %2d %7d %8d %8d %8.1f %5.1f %5.1f %4.1f %4.1f %6.1f" % (
        label, n, rows, sum(withb.values()) + sum(nob.values()), sum(withb.values()),
        share("NO_ACTION"), share("GE"), share("GR"), share("ER"), share("INS"),
        (sum(withb.values()) + sum(nob.values())) / max(sum(withb.values()), 1)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumo-parts", default=SUMO_ROOT)
    ap.add_argument("--aimsun-root", default=AIMSUN_ROOT)
    args = ap.parse_args()

    S = find_sumo(args.sumo_parts)
    A = find_aimsun(args.aimsun_root)
    print("SUMO ledgers: %d | Aimsun ledgers: %d" % (len(S), len(A)))
    for arm in ARMS:
        print("  aimsun %-28s %d" % (
            arm.replace("CHAMP_ADAPTIVE_DSW_GAME_SOL_", ""), len(A.get(arm, []))))

    hdr = ("%-26s %2s %7s %8s %8s %8s %5s %5s %4s %4s %6s" %
           ("arm", "n", "rows", "chosen", "with_bus", "NO_ACT%", "GE%", "GR%",
            "ER%", "INS%", "all/bus"))
    print("\n" + hdr)

    print("-- SUMO (per seed) --")
    agg = collections.defaultdict(lambda: [collections.Counter(), collections.Counter(), 0, 0])
    for arm in ARMS:
        for s in SEEDS:
            p = S.get((arm, s))
            if not p:
                continue
            w, n, rows = mix(p)
            print(_line(arm.replace("CHAMP_ADAPTIVE_DSW_GAME_SOL_", "")[:26] + " s%d" % s,
                        1, w, n, rows))
            a = agg[arm]
            a[0].update(w)
            a[1].update(n)
            a[2] += rows
            a[3] += 1
    print("\n-- SUMO (arm mean over seeds) --")
    for arm in ARMS:
        if agg[arm][3]:
            a = agg[arm]
            print(_line(arm.replace("CHAMP_ADAPTIVE_DSW_GAME_SOL_", "")[:26],
                        a[3], a[0], a[1], a[2]))

    bus_total = sum(sum(a[0].values()) for a in agg.values())
    if agg and bus_total == 0:
        print("\nWARNING: bus_in_zone is 0 on every chosen SUMO row -- the field is not "
              "populated by the SUMO ledger, so the with_bus split and the all/bus ratio "
              "above are meaningless. Read the action mix over ALL chosen rows.")

    if A:
        print("\n-- Aimsun (pooled over the ledgers present; filenames carry no seed) --")
        for arm in ARMS:
            files = A.get(arm, [])
            if not files:
                print("  %-26s no ledger" % arm.replace("CHAMP_ADAPTIVE_DSW_GAME_SOL_", "")[:26])
                continue
            w, n, rows = collections.Counter(), collections.Counter(), 0
            for p in files:
                ww, nn, rr = mix(p)
                w.update(ww)
                n.update(nn)
                rows += rr
            print(_line(arm.replace("CHAMP_ADAPTIVE_DSW_GAME_SOL_", "")[:26],
                        len(files), w, n, rows))
    print("\nNB: Aimsun has no ledger at all for the two LIGHTSIM arms, so those two "
          "cannot be compared action-wise on any seed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
