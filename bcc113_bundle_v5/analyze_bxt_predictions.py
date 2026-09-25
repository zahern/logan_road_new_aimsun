"""analyze_bxt_predictions.py -- how well is the BXT/CELLQLEARN decider performing?

Parses the [BXT_EVAL] diagnostic lines (emitted when BXT_EVAL_DIAGNOSTICS=True,
which the smoke pipeline turns on) and reports PREDICTED vs REALIZED per decision:

  * ACTION MIX      -- what the decider actually chose (NO_ACTION vs GE/INS/...).
  * CALIBRATION     -- did the benefit it PREDICTED (pred_adv = pred_bps-pred_cpc)
                       match the benefit it REALIZED (NO_ACTION baseline - measured
                       delay, ~1.5 cycles later)? Mean pred vs mean realized, mean
                       error (pred-realized), and sign agreement.
  * HIT RATE        -- of the actions it took, how many ACTUALLY helped
                       (realized_adv > 0). This is the bottom-line "is it any good".

Each [BXT_EVAL] line:
  [BXT_EVAL] inter=.. bus=.. t=.. action=ATYPE_Ps pred_bps=.. pred_cpc=..
             pred_adv=.. realized_bus=.. realized_car=.. realized_adv=(num|NA)

Run in a terminal:
    python analyze_bxt_predictions.py [path/to/Aimsun_TSP_Log_*.txt]
or in the Aimsun console (auto-picks the newest kg/logs log):
    exec(open(r"...\\analyze_bxt_predictions.py").read())
"""
import os
import re
import sys
import glob

_LINE = re.compile(
    r"\[BXT_EVAL\]\s+inter=(?P<inter>\S+)\s+bus=(?P<bus>\S+)\s+t=(?P<t>[\d.]+)\s+"
    r"action=(?P<atype>[A-Z_]+)_(?P<param>[\d.]+)s?\s+"
    r"pred_bps=(?P<pbps>-?[\d.]+)\s+pred_cpc=(?P<pcpc>-?[\d.]+)\s+"
    r"pred_adv=(?P<padv>-?[\d.]+)\s+realized_bus=(?P<rbus>-?[\d.]+)\s+"
    r"realized_car=(?P<rcar>-?[\d.]+)\s+realized_adv=(?P<radv>NA|-?[\d.]+)")


def _newest_log():
    here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else "."
    cands = []
    for sub in ("kg/logs", "logan_road_new/logs", "kg", "logan_road_new", "."):
        cands += glob.glob(os.path.join(here, sub, "Aimsun_TSP_Log_*.txt"))
    return max(cands, key=os.path.getmtime) if cands else None


def _mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = _mean(xs), _mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    d = (sxx * syy) ** 0.5
    return sxy / d if d > 0 else float("nan")


def analyze(path):
    recs = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for ln in f:
            m = _LINE.search(ln)
            if not m:
                continue
            d = m.groupdict()
            recs.append({
                "atype": d["atype"],
                "param": float(d["param"]),
                "pred_adv": float(d["padv"]),
                "pred_bps": float(d["pbps"]),
                "pred_cpc": float(d["pcpc"]),
                "realized_adv": (None if d["radv"] == "NA" else float(d["radv"])),
            })

    print("=" * 70)
    print(f"BXT PREDICTED-vs-REALIZED  |  {os.path.basename(path)}")
    print("=" * 70)
    if not recs:
        print("No [BXT_EVAL] lines found. Run with BXT_EVAL_DIAGNOSTICS=True")
        print("(the smoke pipeline sets it automatically). Then re-run this.")
        return

    # ── ACTION MIX ────────────────────────────────────────────────────────────
    mix = {}
    for r in recs:
        mix[r["atype"]] = mix.get(r["atype"], 0) + 1
    n = len(recs)
    print(f"\nACTION MIX ({n} decisions):")
    for a, c in sorted(mix.items(), key=lambda kv: -kv[1]):
        print(f"  {a:16} {c:6}  ({100.0*c/n:5.1f}%)")
    n_act = sum(c for a, c in mix.items() if a != "NO_ACTION")
    print(f"  -> acted on {n_act}/{n} ({100.0*n_act/max(n,1):.1f}%); "
          f"NO_ACTION {100.0*mix.get('NO_ACTION',0)/max(n,1):.1f}%")

    # ── CALIBRATION (scored actions only) ─────────────────────────────────────
    scored = [r for r in recs if r["atype"] != "NO_ACTION" and r["realized_adv"] is not None]
    print(f"\nCALIBRATION (scored actions with a realized outcome: {len(scored)}):")
    if not scored:
        print("  none scored yet -- the NO_ACTION baseline had not accumulated when")
        print("  these actions closed. Longer run / more NO_ACTION samples needed.")
    else:
        pa = [r["pred_adv"] for r in scored]
        ra = [r["realized_adv"] for r in scored]
        err = [p - a for p, a in zip(pa, ra)]
        agree = sum(1 for p, a in zip(pa, ra) if (p > 0) == (a > 0))
        print(f"  mean PREDICTED advantage : {_mean(pa):8.0f} pax-s")
        print(f"  mean REALIZED  advantage : {_mean(ra):8.0f} pax-s")
        print(f"  mean error (pred-real)   : {_mean(err):8.0f} pax-s "
              f"({'OVER' if _mean(err)>0 else 'UNDER'}-predicts benefit)")
        print(f"  correlation pred vs real : {_pearson(pa, ra):8.2f}")
        print(f"  sign agreement           : {agree}/{len(scored)} "
              f"({100.0*agree/len(scored):.0f}%)")

    # ── HIT RATE (bottom line) ────────────────────────────────────────────────
    if scored:
        helped = sum(1 for r in scored if r["realized_adv"] > 0)
        print(f"\nHIT RATE: {helped}/{len(scored)} actions actually REDUCED delay "
              f"({100.0*helped/len(scored):.0f}%).")
        by = {}
        for r in scored:
            k = f"{r['atype']}_{r['param']:.0f}s"
            by.setdefault(k, []).append(r["realized_adv"])
        print("  per action:")
        for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
            hr = 100.0 * sum(1 for x in v if x > 0) / len(v)
            print(f"    {k:16} n={len(v):4}  hit={hr:5.1f}%  "
                  f"mean_realized={_mean(v):7.0f} pax-s")
    print("=" * 70)


if __name__ == "__main__" or "__file__" in globals():
    _p = sys.argv[1] if len(sys.argv) > 1 else _newest_log()
    if not _p or not os.path.isfile(_p):
        print(f"log not found: {_p!r} -- pass a path as the first argument.")
    else:
        analyze(_p)
