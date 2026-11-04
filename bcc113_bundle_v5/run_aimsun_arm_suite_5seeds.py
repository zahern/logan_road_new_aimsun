"""run_aimsun_arm_suite_5seeds.py -- 5-seed Aimsun arm matrix vs NO_TSP.

Runs ONE NO_TSP baseline per seed, then every arm in ARM_SUITE_ARMS on the
same seed / demand / build, so each comparison is same-seed paired.

Default suite (edit ARM_SUITE_ARMS or pass it in the environment):
    CHAMP_ADAPTIVE_AIMSUN_DSW          adaptive base (PBIL plan + DSW weights)
    CHAMP_ADAPTIVE_DSW_THRU_OPEN       throughput reward, ungated, bus acts on top
    CHAMP_ADAPTIVE_DSW_BELLMAN_CTM_DP  multi-cell CTM DP (gated baseline for A/B)
    CHAMP_ADAPTIVE_DSW_BELLMAN_OPEN    multi-cell CTM DP, opened (throughput)
    CHAMP_ADAPTIVE_DSW_GAME_BUS        decider bus game on the base (reference)
    CHAMP_ADAPTIVE_DSW_FLOW            Flow policy on the adaptive base

The *_OPEN / THRU arms drop the bus-lateness gate (engine default 30 s) and the
warm-up/congestion/DS-balance vetoes, keeping only a break-even cost backstop, so
the RL/CTM methods act on net PASSENGER THROUGHPUT and the bounded bus-priority
overlay acts on top of the adaptive plan. See champion_search._ADAPTIVE_THRU_OPEN.

MULTI_CELL_CTM is diagnostic-only until its side-only CTM cost is fixed;
it is not in the default comparison. The raw arms (NASH_BARGAIN, DCTSP_MARL_RL, CHAMP_PAXWIN_CYCLE_PBIL, ZIGCTM)
are kept for history and auto-map to the adaptive-base variants above.

Outputs (next to this file):
    paxwin_arm_suite_5seeds.csv           raw per-run rows
    paxwin_arm_suite_5seeds_summary.csv   per-arm summary
    paxwin_arm_suite_5seeds.png           mean objective bars

Run in the Aimsun console AFTER A FULL AIMSUN RESTART, with the KG model open:
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_aimsun_arm_suite_5seeds.py").read())

Overrides (set before the exec):
    import os
    os.environ["ARM_SUITE_ARMS"] = "CHAMP_ADAPTIVE_AIMSUN_DSW,ZIGCTM"
    os.environ["ARM_SUITE_SEEDS"] = "300,400"
    os.environ["ARM_SUITE_OUT"] = "my_subset.csv"
    os.environ["ARM_SUITE_ALLOW_RAW"] = "1"   # keep the historical raw arm
"""
import csv
import importlib
import os as _os
import statistics as _st
import sys as _sys

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
# Only the bundle root is needed to import champion_search; the ACTIVE corridor's
# own dir is added AFTER _cs tells us which corridor is open (kg vs logan_road_new)
# -- a hardcoded kg here would shadow Logan's helper modules on a Logan run.
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

_SEEDS = _os.environ.get("ARM_SUITE_SEEDS", "300,400,500,600,700").strip() \
    or "300,400,500,600,700"
_ARMS = _os.environ.get("ARM_SUITE_ARMS", "").strip() or ",".join([
    "CHAMP_ADAPTIVE_AIMSUN_DSW",          # adaptive base + PBIL plan
    "CHAMP_ADAPTIVE_DSW_THRU_OPEN",       # throughput, ungated, bus acts on top
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CTM_DP",  # multi-cell CTM DP (gated baseline)
    "CHAMP_ADAPTIVE_DSW_BELLMAN_OPEN",    # multi-cell CTM DP, opened + snapshot DS
    "CHAMP_ADAPTIVE_DSW_BELLMAN_COUPLED", # multi-cell CTM DP, COUPLED 2-junction
    "CHAMP_ADAPTIVE_DSW_GAME_BUS",        # decider bus game on the base (ref)
])
_OUT = _os.path.join(
    _HERE,
    _os.environ.get("ARM_SUITE_OUT", "paxwin_arm_suite_5seeds.csv").strip()
    or "paxwin_arm_suite_5seeds.csv")

# ---- validate before touching the simulator --------------------------------
if "champion_search" in _sys.modules:
    importlib.reload(_sys.modules["champion_search"])
import champion_search as _cs

# Now that _cs has detected the open model, put the ACTIVE corridor's own dir on
# the path (kg OR logan_road_new) so its batch_runner / helper modules import,
# not a hardcoded kg.
_corr_dir = _os.path.join(_HERE, getattr(_cs, "CORRIDOR", "kg"))
if _corr_dir not in _sys.path:
    _sys.path.insert(0, _corr_dir)

_names = {a["name"] for a in _cs.ARMS}
_arms = [a.strip() for a in _ARMS.split(",") if a.strip()]

# Resolve historical raw arms onto the adaptive base unless explicitly allowed.
# The raw arms were the ones that fell below NO_TSP; the *_SAFE/base variants
# keep the adaptive plan loop. Set ARM_SUITE_ALLOW_RAW=1 to run the originals.
_RAW_ALIASES = {
    "NASH_BARGAIN": "CHAMP_ADAPTIVE_DSW_NASH",
    "DCTSP_MARL_RL": "CHAMP_ADAPTIVE_DSW_MARL",
    "CHAMP_PAXWIN_CYCLE_PBIL": "CHAMP_ADAPTIVE_AIMSUN_DSW",
    "ZIGCTM": "CHAMP_ADAPTIVE_DSW_MULTI_CELL_CTM",
    "CHAMP_ADAPTIVE_DSW_CTM": "CHAMP_ADAPTIVE_DSW_MULTI_CELL_CTM",
}
if _os.environ.get("ARM_SUITE_ALLOW_RAW", "0").strip() != "1":
    _mapped = []
    for _a in _arms:
        _b = _RAW_ALIASES.get(_a, _a)
        if _b != _a:
            print("  map %s -> %s (adaptive base)" % (_a, _b))
        _mapped.append(_b)
    _arms = _mapped

_unknown = [a for a in _arms if a not in _names]
if _unknown:
    raise SystemExit(
        "unknown arm(s): %s\navailable CHAMP_*/PBIL/MARL arms: %s"
        % (_unknown, sorted(n for n in _names
                            if any(k in n for k in ("ADAPTIVE", "PBIL", "MARL",
                                                    "CTM", "NASH")))))
# Which corridor this suite is meant for. Defaults to 'kg' so every existing KG
# launcher keeps its guard unchanged; a Logan launcher sets ARM_SUITE_CORRIDOR=
# logan_road_new. The guard still catches a stale/wrong model being open.
_EXPECT_CORR = (_os.environ.get("ARM_SUITE_CORRIDOR", "kg").strip() or "kg")
if getattr(_cs, "CORRIDOR", "kg") != _EXPECT_CORR:
    raise SystemExit(
        "wrong corridor open: %r (expected %r) -- open the right Aimsun model, "
        "or set ARM_SUITE_CORRIDOR to match."
        % (getattr(_cs, "CORRIDOR", None), _EXPECT_CORR))

_seed_list = [int(s) for s in _SEEDS.split(",") if s.strip()]
print("=" * 84)
print("ARM SUITE vs NO_TSP -- %d seeds %s" % (len(_seed_list), _seed_list))
print("  arms: %s" % ", ".join(_arms))
print("  out : %s" % _OUT)
print("=" * 84)

# PAXWIN_ARMS runs ONE NO_TSP baseline followed by every listed arm.
_os.environ["PAXWIN_SEEDS"] = _SEEDS
_os.environ["PAXWIN_WARMUP"] = "0"
_os.environ["PAXWIN_ARM"] = _arms[0]
_os.environ["PAXWIN_ARMS"] = ",".join(_arms)
_os.environ["PAXWIN_OUT_CSV"] = _OUT
# Pin the driver's own corridor guard to the same corridor this suite expects.
_os.environ["PAXWIN_EXPECT_CORRIDOR"] = _EXPECT_CORR

_MOD = "run_paxwin_game_vs_notsp"
if _MOD in _sys.modules:
    importlib.reload(_sys.modules[_MOD])
else:
    import run_paxwin_game_vs_notsp  # noqa: F401  (executes the suite)


# ---- per-arm summary --------------------------------------------------------
def _f(r, k):
    try:
        return float(r.get(k, "") or 0.0)
    except Exception:
        return 0.0


def _summary():
    if not _os.path.isfile(_OUT):
        print("No results CSV at", _OUT)
        return
    with open(_OUT, newline="", encoding="utf-8-sig", errors="replace") as fh:
        rows = list(csv.DictReader(fh))

    by = {}
    for r in rows:
        by.setdefault(str(r.get("run_experiment", "")), []).append(r)

    def vals(arm, key, seeds):
        out = {}
        for r in by.get(arm, []):
            try:
                s = int(float(r.get("run_seed")))
            except Exception:
                continue
            if s in seeds:
                out[s] = _f(r, key)
        return out

    base = vals("NO_TSP", "stats_Objective_PaxPerDelayHr", set(_seed_list))
    if not base:
        print("NO_TSP rows missing from", _OUT)
        return

    # BASELINE STABILITY GUARD (2026-10-31). The first replication in a fresh
    # Aimsun process reads a systematically lower objective: KG ladder seed 300
    # NO_TSP objective 117.6 vs a 148.0 median (-20.5%) while its delay (697.7 h)
    # sits mid-range -- so the numerator (passengers passing), not the traffic,
    # is what differs. Because the summary normalises PER SEED, that one row
    # inflates every arm's apparent gain (AIMSUN_DSW +11.8% -> +6.6% without it).
    # Flag any NO_TSP seed more than BASELINE_OUTLIER_PCT from the median and
    # report a second, stable-seed mean so results cannot rest on a warm-up row.
    try:
        _bo_pct = float(os.environ.get("BASELINE_OUTLIER_PCT", "10") or 10.0)
    except Exception:
        _bo_pct = 10.0
    _bmed = _st.median(base.values())
    _bad_seeds = set()
    for _s, _v in base.items():
        if _bmed and abs(_v / _bmed - 1.0) * 100.0 > _bo_pct:
            _bad_seeds.add(_s)
    if _bad_seeds:
        print("\n[BASELINE] NO_TSP outlier seed(s) %s: objective %s vs median %.2f"
              % (sorted(_bad_seeds),
                 {s: round(base[s], 2) for s in sorted(_bad_seeds)}, _bmed))
        print("[BASELINE] those seeds are excluded from objective_pct_stable")
    _stable = [s for s in _seed_list if s not in _bad_seeds and s in base]
    _base_stable_mean = _st.mean([base[s] for s in _stable]) if _stable else 0.0

    metrics = [
        ("stats_Objective_PaxPerDelayHr", "objective", True),
        ("stats_TotalPassDelay_hrs", "total delay (h)", False),
        ("stats_MainPassDelay_hrs", "main delay (h)", False),
        ("stats_SidePassDelay_hrs", "side delay (h)", False),
        ("stats_AvgBusPassDelay_s", "bus delay / pax (s)", False),
        ("stats_TSP_Extensions", "GE actions", False),
        ("stats_TSP_Insertions", "INS actions", False),
        ("stats_TSP_EarlyRed", "ER actions", False),
        ("stats_TSP_NaturalGreen", "natural green", True),
    ]

    summary_rows = []
    print("\n%-32s %8s %10s %10s %8s" %
          ("arm", "obj", "% vs NO_TSP", "bus d/pax", "n"))
    for arm in ["NO_TSP"] + _arms:
        a = vals(arm, "stats_Objective_PaxPerDelayHr", set(_seed_list))
        if not a:
            continue
        m = _st.mean(a.values())
        rel = 100.0 * (m - _st.mean(base.values())) / _st.mean(base.values()) \
            if _st.mean(base.values()) else 0.0
        bus = _st.mean(vals(arm, "stats_AvgBusPassDelay_s",
                            set(_seed_list)).values() or [0.0])
        print("%-32s %8.2f %+9.1f%% %10.2f %8d" % (arm, m, rel, bus, len(a)))
        for s in _seed_list:
            summary_rows.append({
                "arm": arm, "seed": s,
                "objective": a.get(s, ""),
                "objective_pct_vs_no_tsp":
                    (100.0 * (a[s] - base[s]) / base[s]) if s in base and base[s] else "",
                "total_delay_hrs": vals(arm, "stats_TotalPassDelay_hrs", {s}).get(s, ""),
                "main_delay_hrs": vals(arm, "stats_MainPassDelay_hrs", {s}).get(s, ""),
                "side_delay_hrs": vals(arm, "stats_SidePassDelay_hrs", {s}).get(s, ""),
                "bus_delay_per_pax_s": vals(arm, "stats_AvgBusPassDelay_s", {s}).get(s, ""),
                "tsp_extensions": vals(arm, "stats_TSP_Extensions", {s}).get(s, ""),
                "tsp_insertions": vals(arm, "stats_TSP_Insertions", {s}).get(s, ""),
                "tsp_early_red": vals(arm, "stats_TSP_EarlyRed", {s}).get(s, ""),
                "tsp_natural_green": vals(arm, "stats_TSP_NaturalGreen", {s}).get(s, ""),
                "baseline_outlier": int(s in _bad_seeds),
                "objective_pct_stable":
                    (100.0 * (a[s] - base[s]) / base[s])
                    if (s in base and base[s] and s not in _bad_seeds) else "",
            })

    out_csv = _os.path.splitext(_OUT)[0] + "_summary.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary_rows[0].keys()))
        w.writeheader()
        w.writerows(summary_rows)
    print("\nwrote", out_csv)

    # paired significance vs NO_TSP for the objective
    try:
        from scipy import stats as _sps
        print("\npaired objective test vs NO_TSP (same seed):")
        for arm in _arms:
            a = vals(arm, "stats_Objective_PaxPerDelayHr", set(_seed_list))
            seeds = sorted(set(a) & set(base))
            if len(seeds) < 2:
                continue
            t, p = _sps.ttest_rel([a[s] for s in seeds],
                                  [base[s] for s in seeds])
            print("  %-32s t=%6.2f  p=%.3f" % (arm, t, p))
    except Exception as _e:
        print("  significance skipped:", repr(_e))

    # multi-panel bars with value labels: objective, THROUGHPUT (pax pushed
    # through -- the primary goal), network density, total delay.
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        names = [a for a in ["NO_TSP"] + _arms
                 if vals(a, "stats_Objective_PaxPerDelayHr", set(_seed_list))]
        short = [n.replace("CHAMP_ADAPTIVE_", "") for n in names]

        def _mean(arm, key):
            v = list(vals(arm, key, set(_seed_list)).values())
            return _st.mean(v) if v else 0.0

        # (column, title, y-label, higher_is_better, value format)
        panels = [
            ("stats_Objective_PaxPerDelayHr", "Objective", "pax / delay-hr",
             True, "%.1f"),
            ("stats_PaxEquivPassages", "Throughput (pax pushed through)",
             "passenger passages", True, "%.0f"),
            ("stats_Net_AvgDensity_vkm", "Network density", "veh/km",
             False, "%.1f"),
            ("stats_TotalPassDelay_hrs", "Total passenger delay", "delay-hr",
             False, "%.0f"),
        ]
        fig, axes = plt.subplots(2, 2, figsize=(max(10, len(names) * 1.6), 9))
        for ax, (col, title, ylab, hib, fmt) in zip(axes.ravel(), panels):
            means = [_mean(a, col) for a in names]
            base_m = means[0] if means else 0.0
            cols = []
            for n, m in zip(names, means):
                if n == "NO_TSP":
                    cols.append("#90a4ae")
                elif base_m and ((m > base_m) == hib):
                    cols.append("#2e7d32")   # better than NO_TSP = green
                else:
                    cols.append("#c62828")   # worse = red
            bars = ax.bar(range(len(names)), means, color=cols)
            if base_m:
                ax.axhline(base_m, color="#607d8b", ls="--", lw=1)
            # VALUE LABELS spelled out on every bar (+ %% vs NO_TSP)
            for i, (b, m) in enumerate(zip(bars, means)):
                lbl = fmt % m
                if base_m and names[i] != "NO_TSP":
                    lbl += "\n(%+.1f%%)" % (100.0 * (m - base_m) / base_m)
                ax.annotate(lbl, (b.get_x() + b.get_width() / 2, m),
                            ha="center", va="bottom", fontsize=7,
                            xytext=(0, 2), textcoords="offset points")
            ax.set_xticks(range(len(names)))
            ax.set_xticklabels(short, rotation=30, ha="right", fontsize=7)
            ax.set_ylabel(ylab, fontsize=8)
            ax.set_title("%s  (%s)" % (title,
                         "higher=better" if hib else "lower=better"),
                         fontsize=9)
            ax.grid(axis="y", alpha=0.3)
            ax.margins(y=0.15)
        fig.suptitle("Arm suite vs NO_TSP -- %d seeds (dashed = NO_TSP)"
                     % len(_seed_list), fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, 0.97))
        png = _os.path.splitext(_OUT)[0] + ".png"
        fig.savefig(png, dpi=150)
        print("wrote", png)
    except Exception as _e:
        print("plot skipped:", repr(_e))


try:
    _summary()
except Exception as _e:
    print("summary failed:", repr(_e))

print("\nDONE ->", _OUT)
