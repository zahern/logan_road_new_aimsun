"""Make MainPlusSidePassDelay_hrs reconcile with the headline.

The SIG-WAIT block replaces the section-based bus delay in the HEADLINE with the
pure red-wait definition (`sim_total_delay += new_bus - old_bus`) and adjusts
`_corridor_total_paxs`, but `total_main_delay` / `total_side_delay` were summed
before that point and never adjusted. So main+side exceeded the headline by
exactly (sum of the per-junction bus term - new_bus):

    NO_TSP       183.59 h   (1,046,681 - 385,760 pax-s)
    LIGHTSIM_MP  707.62 h   (2,632,630 -  85,200 pax-s)

`_kpis_for` adds `added_bus_delay` to BOTH total and main, so the bus term is
carried by `main`; the same delta therefore belongs on `total_main_delay`.
After the fix  main + side == total_pass_delay  (both in hours) by construction.

Idempotent: re-running is a no-op. Usage: python -I _patch_split_reconcile.py
"""
import io
import sys

SRC = "kg/Simulation_Stats.py"
MARK = "SPLIT_RECONCILE"

ANCHOR = (
    "            try:\n"
    "                _corridor_total_paxs += (_new_bus - _old_bus)\n"
    "            except Exception:\n"
    "                pass\n"
)

ADD = (
    "            # SPLIT_RECONCILE (2026-11-10): the SAME delta must reach the\n"
    "            # split accumulators. total_main_delay/total_side_delay are\n"
    "            # summed BEFORE this replacement and were never adjusted, so\n"
    "            # main+side exceeded the headline by exactly\n"
    "            # (sum of per-junction bus term - new_bus): 183.59 h (NO_TSP)\n"
    "            # and 707.62 h (LIGHTSIM_MP) on the 2026-11-10 seed-300 pair.\n"
    "            # _kpis_for adds added_bus_delay to BOTH total and main, so the\n"
    "            # bus term is carried by `main` and the delta belongs there.\n"
    "            try:\n"
    "                total_main_delay += (_new_bus - _old_bus) / 3600.0\n"
    "            except Exception:\n"
    "                pass\n"
)


def main():
    with io.open(SRC, encoding="utf-8", newline="") as fh:
        raw = fh.read()
    nl = "\r\n" if "\r\n" in raw else "\n"

    if MARK in raw:
        print("[patch] already applied (%s present) - no change" % MARK)
        return 0

    anchor = ANCHOR.replace("\n", nl)
    add = ADD.replace("\n", nl)

    n = raw.count(anchor)
    if n != 1:
        print("[patch] ABORT: anchor found %d times (expected 1)" % n)
        return 2
    if raw.count("total_main_delay += (_new_bus - _old_bus)") != 0:
        print("[patch] ABORT: adjustment already present without marker")
        return 2

    out = raw.replace(anchor, anchor + add, 1)
    with io.open(SRC, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)
    print("[patch] applied to %s (%d -> %d bytes)" % (SRC, len(raw), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
