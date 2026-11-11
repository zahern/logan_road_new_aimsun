"""Pair the KG LIGHTSIM twins against NO_TSP on pax-hours per sim hour.

The KG baseline is split across two naming schemes, because the twin ladder ran
seeds the legacy game-solution sweep never covered:

    seeds 300-500   parts/gamesol_CHAMP_NO_TSP_eval<SEED>.csv   (legacy sweep)
    seeds 600-700   parts/ladder_NO_TSP_kg_eval<SEED>.csv        (twin ladder)

Both are read here, so every twin seed pairs against its own NO_TSP row rather
than against a different seed or a different corridor (AGENTS RULE 3).

Reported metric: pax-delay hours per simulation hour
(`avg_total_pass_delay_per_hr`, lower is better). Deliberately not the objective:
the two platforms count the passenger numerator differently, while pax-delay
hours carry no passenger denominator and stay comparable across Aimsun/SUMO.

    python pair_kg_twins.py                     # both twins, seeds 300-700
    python pair_kg_twins.py --csv out.csv
    python pair_kg_twins.py --parts Z:\\tsp\\sumo_hpc\\parts

Missing parts are reported as PENDING, not treated as an error: the HPC sweep
may still be writing them.
"""
import argparse
import csv
import os
import statistics as st

DEFAULT_PARTS = r"Z:\tsp\sumo_hpc\parts"
HERE = os.path.dirname(os.path.abspath(__file__))

CORRIDOR = "kg"
SEEDS = [300, 400, 500, 600, 700]
ARM_PREFIX = "CHAMP_ADAPTIVE_DSW_"

TWINS = [
    ("NASH_LIGHTSIM",
     "CHAMP_ADAPTIVE_DSW_GAME_SOL_NASH_CTM2_SPILL2_LIGHTSIM"),
    ("UTIL_LIGHTSIM",
     "CHAMP_ADAPTIVE_DSW_GAME_SOL_UTIL_CTM2_SPILL2_LIGHTSIM"),
]

# (scheme label, filename template) -- the two baseline naming schemes.
BASELINE_SCHEMES = [
    ("gamesol", "gamesol_CHAMP_NO_TSP_eval{eval_seed}.csv"),
    ("ladder", "ladder_NO_TSP_{corr}_eval{eval_seed}.csv"),
]

NA = float("nan")


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return NA


def paxh(row):
    """(pax-delay hours per sim hour, source label) for one part row."""
    v = _f(row.get("avg_total_pass_delay_per_hr"))
    if v == v:
        return v, "column"
    pax = _f(row.get("total_passengers"))
    dly = _f(row.get("avg_pass_delay_s"))
    hrs = _f(row.get("sim_duration_hrs"))
    if pax == pax and dly == dly and hrs == hrs and hrs > 0:
        return pax * dly / 3600.0 / hrs, "derived"
    return NA, "missing"


def load_eval(path):
    """Eval rows of one part file; a missing file yields []."""
    rows = []
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                phase = str(r.get("phase", "")).strip().lower()
                if phase and phase != "eval":
                    continue
                if str(r.get("ok", "")).strip().lower() in ("false", "0", "0.0", "no"):
                    continue
                rows.append(r)
    except OSError:
        return []
    return rows


def twin_path(parts, arm, seed):
    short = arm[len(ARM_PREFIX):] if arm.startswith(ARM_PREFIX) else arm
    return os.path.join(parts, "ladder_%s_%s_eval%d.csv" % (short, CORRIDOR, seed))


def load_baselines(parts):
    """seed -> (arm, paxh, scheme, filename, row); first scheme that has it wins."""
    out = {}
    for seed in SEEDS:
        for scheme, tpl in BASELINE_SCHEMES:
            name = tpl.format(eval_seed=seed, corr=CORRIDOR)
            path = os.path.join(parts, name)
            rows = [r for r in load_eval(path) if "NO_TSP" in str(r.get("arm", ""))]
            if not rows:
                continue
            r = rows[0]
            v, _src = paxh(r)
            if v != v:
                continue
            out[seed] = (r.get("arm", ""), v, scheme, name, r)
            break
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Pair the KG LIGHTSIM twins against NO_TSP on pax-hours.")
    ap.add_argument("--parts", default=DEFAULT_PARTS,
                    help="directory holding the SUMO part CSVs")
    ap.add_argument("--csv", default=os.path.join(HERE, "kg_twins_vs_no_tsp_paxh.csv"),
                    help="where to write the paired rows")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.parts):
        print("parts directory not found: %s" % args.parts)
        return 2

    base = load_baselines(args.parts)
    print("baselines (NO_TSP, pax-delay h per sim h, lower is better)")
    for seed in SEEDS:
        if seed in base:
            arm, v, scheme, name, _r = base[seed]
            print("  seed %d  %-9s %10.2f   %s" % (seed, scheme, v, name))
        else:
            print("  seed %d  %-9s %10s   MISSING (no baseline row)" % (seed, "-", "-"))
    if not base:
        print("\nno NO_TSP baseline rows -- nothing to pair")
        return 1

    # every row we pair must be the KG corridor at the same demand build
    demand = {}
    for seed, (_arm, _v, _s, _n, r) in base.items():
        d = _f(r.get("demand_scalar"))
        corridor = str(r.get("corridor", "")).strip().lower()
        if corridor and corridor != CORRIDOR:
            print("  WARNING seed %d baseline corridor=%r, expected %r"
                  % (seed, corridor, CORRIDOR))
        demand[seed] = d

    recs, pending = [], []
    for label, arm in TWINS:
        for seed in SEEDS:
            path = twin_path(args.parts, arm, seed)
            rows = [r for r in load_eval(path) if r.get("arm", arm) == arm] or load_eval(path)
            if seed not in base:
                pending.append((label, seed, "no NO_TSP baseline"))
                continue
            if not rows:
                pending.append((label, seed, "part not written yet"))
                continue
            r = rows[0]
            corridor = str(r.get("corridor", "")).strip().lower()
            if corridor and corridor != CORRIDOR:
                pending.append((label, seed, "corridor=%s, not %s" % (corridor, CORRIDOR)))
                continue
            d = _f(r.get("demand_scalar"))
            b_d = demand.get(seed, NA)
            if d == d and b_d == b_d and abs(d - b_d) > 1e-9:
                pending.append((label, seed, "demand_scalar %.3f != baseline %.3f" % (d, b_d)))
                continue
            v, src = paxh(r)
            if v != v:
                pending.append((label, seed, "no pax-hours column"))
                continue
            b = base[seed][1]
            recs.append(dict(label=label, arm=arm, seed=seed, paxh=v,
                             base=b, scheme=base[seed][2], source=src,
                             delta_pct=(v - b) / b * 100.0 if b else NA,
                             delta_abs=v - b))

    if not recs and not pending:
        print("\nno twin rows and no missing pairs -- nothing to do")
        return 1

    print("\nper-seed pax-delay hours per sim hour (lower is better)")
    print("  %-15s %5s %9s %10s %10s %9s %9s"
          % ("arm", "seed", "baseline", "paxh", "delta", "delta%", "source"))
    for r in recs:
        print("  %-15s %5d %9.2f %10.2f %+10.2f %+8.1f%% %9s"
              % (r["label"], r["seed"], r["base"], r["paxh"],
                 r["delta_abs"], r["delta_pct"], r["source"]))

    if pending:
        print("\nnot paired")
        for label, seed, why in pending:
            print("  %-15s %5d  %s" % (label, seed, why))

    print("\nmeans over paired seeds (against the same-seed NO_TSP)")
    print("  %-15s %3s %10s %10s %9s %s"
          % ("arm", "n", "base", "paxh", "delta%", "seeds"))
    for label, _arm in TWINS:
        rs = [r for r in recs if r["label"] == label]
        if not rs:
            continue
        agree = sum(1 for r in rs if r["delta_pct"] < 0)
        print("  %-15s %3d %10.2f %10.2f %+8.1f%% %d/%d better"
              % (label, len(rs), st.mean([r["base"] for r in rs]),
                 st.mean([r["paxh"] for r in rs]),
                 st.mean([r["delta_pct"] for r in rs]), agree, len(rs)))

    with open(args.csv, "w", newline="", encoding="utf-8") as fh:
        fields = ["label", "seed", "scheme", "base", "paxh", "delta_abs",
                  "delta_pct", "source"]
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows([{k: r[k] for k in fields} for r in recs])
    print("\nwrote %s" % args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
