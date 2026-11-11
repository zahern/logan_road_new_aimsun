#!/usr/bin/env python
"""Paired SUMO A/B: SIDE_COST_MARGINAL_COMPETITOR on the CTM2 game path.

Reuses run_noise_floor.run_one() -- which resolves an arm's reward_overrides,
patches CONTROL_MODE per arm, parses TRUTH and now captures [GAME_MARGINAL] --
but writes its own CSV so the diag columns survive, and keeps the two gates
that return BEFORE the payoff disabled on BOTH arms (see _spillproof_launch.py):
    GAME_CONGESTION_GATE=False   (else q<4 HOLDs at every junction)
    NASH_CORRIDOR_MODE=False     (else the corridor best-response returns first)
"""
import argparse, csv, importlib.util, os, statistics as st, sys, time

DRV = r"Z:\tsp\sumo_hpc\sumo_bridge\_det3\noise_floor\run_noise_floor.py"
SANDBOX = r"Z:\tsp\sumo_hpc\sumo_bridge\_det3\noise_floor\sbx_marg_ab"


def load_drv():
    spec = importlib.util.spec_from_file_location("nf_ab", DRV)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--end", type=float, default=600)
    ap.add_argument("--seed", type=int, default=300)
    ap.add_argument("--arms", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--sandbox", default=SANDBOX)
    ap.add_argument("--scenario", default="kg_scenario_prerouted")
    ap.add_argument("--set", action="append", default=[])
    a = ap.parse_args()

    extra = {}
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        if not _:
            sys.exit("--set needs KEY=VALUE, got %r" % kv)
        extra[k.strip()] = v.strip()

    m = load_drv()
    arms = [x for x in a.arms.split(",") if x]
    rows = []
    print("[AB] arms=%d reps=%d end=%s seed=%d extra=%d %s"
          % (len(arms), a.reps, a.end, a.seed, len(extra), sorted(extra)), flush=True)
    for rep in range(1, a.reps + 1):
        for arm in arms:
            r = m.run_one(arm, rep, a.end, a.seed, a.sandbox, a.scenario, extra)
            rows.append(r)
            print("[AB] %-44s rep%d wall=%6ss obj=%8s delay=%8s pax=%6s "
                  "marg_calls=%s multi=%s maxph=%s gap=%s"
                  % (arm.split("GAME_SOL_")[-1][:44], rep, r.get("wall_s"),
                     r.get("obj"), r.get("delay_hrs"), r.get("pax"),
                     r.get("marg_calls"), r.get("marg_multi"),
                     r.get("marg_maxph"), r.get("marg_gap")), flush=True)
            with open(a.csv, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader(); w.writerows(rows)

    print("\n=========== per-arm ===========")
    by = {}
    for r in rows:
        by.setdefault(r["arm"], []).append(r)
    for arm, rs in by.items():
        def f(k):
            return [float(r[k]) for r in rs if str(r.get(k, "")) not in ("", "None")]
        o, d, p = f("obj"), f("delay_hrs"), f("pax")
        mc = sum(int(r["marg_calls"]) for r in rs if str(r.get("marg_calls", "")) not in ("", "None"))
        print("%-50s n=%d obj=%8.4f sd=%6.4f delay=%7.4f pax=%6.1f marg_calls=%d"
              % (arm[:50], len(rs), st.mean(o) if o else float("nan"),
                 st.stdev(o) if len(o) > 1 else 0.0,
                 st.mean(d) if d else float("nan"),
                 st.mean(p) if p else float("nan"), mc))
    print("\n=========== paired base vs _MARGINAL ===========")
    for base in arms:
        if base.endswith("_MARGINAL"):
            continue
        tw = base + "_MARGINAL"
        if tw not in by:
            continue
        b = [float(r["obj"]) for r in by[base] if r.get("obj") not in ("", None)]
        t = [float(r["obj"]) for r in by[tw] if r.get("obj") not in ("", None)]
        if not (b and t):
            continue
        n = min(len(b), len(t))
        dif = [t[i] - b[i] for i in range(n)]
        # pooled sd of the A/B difference across reps (unpaired-safe bound)
        sdp = st.stdev(dif) if n > 1 else 0.0
        print("%s" % base.split("GAME_SOL_")[-1])
        print("  base : %s" % " ".join("%.4f" % v for v in b))
        print("  twin : %s" % " ".join("%.4f" % v for v in t))
        print("  delta(mean) = %+0.4f   sd(delta)=%0.4f   n=%d   se=%.4f"
              % (st.mean(t) - st.mean(b), sdp, n, sdp / (n ** 0.5) if n else float("nan")))
    print("\nrows written: %s" % a.csv)


if __name__ == "__main__":
    main()
