"""
analyze_spm_sweep.py  — Compare BARGAIN_SPM parameter sweep results.

Run from the project root after completing sweep simulations:
    python analyze_spm_sweep.py

Reads summary.json from all DCTSP_BARGAIN_SPM / DCTSP_SPM_V3_* result folders
and prints a ranked comparison table.  Also shows per-junction breakdown for
the configured "problem junctions" (those with worst car delay in the baseline run).
"""

import os
import json
import glob
from collections import defaultdict

RESULTS_DIR   = os.path.join(os.path.dirname(__file__), "results")
SEED          = 300
NO_TSP_NAME   = "NO_TSP"

# Junctions identified as problem sites in previous analysis
PROBLEM_JCTS  = [39593, 39587, 39576, 36393, 36385]

# ── Helpers ──────────────────────────────────────────────────────────────────

def h_to_s(h): return h * 3600.0

def _load(folder):
    """Return (name, summary_dict) or None if not found."""
    pattern = os.path.join(RESULTS_DIR, folder, "summary.json")
    matches = glob.glob(pattern)
    if not matches:
        return None
    with open(matches[0], encoding="utf-8") as f:
        return json.load(f)


def _find_experiments():
    """Return sorted list of matching experiment folder names."""
    all_dirs = [d for d in os.listdir(RESULTS_DIR)
                if os.path.isdir(os.path.join(RESULTS_DIR, d))]
    target_prefixes = (
        "NO_TSP", "DCTSP_BARGAIN_SPM", "DCTSP_ZIG",
        "DCTSP_SPM_V3_",
    )
    hits = []
    for d in sorted(all_dirs):
        if f"_seed{SEED}_" not in d:
            continue
        if any(d.startswith(p) for p in target_prefixes):
            hits.append(d)
    return hits


def _global_kpis(summary):
    g = summary.get("global_kpis", summary)  # support flat or nested
    # pax-hours of delay (prefer pax·s fields for precision)
    bus_h   = g.get("sim_bus_delay_pax_s",  0.0) / 3600.0
    car_h   = g.get("sim_car_delay_pax_s",  0.0) / 3600.0
    total_h = g.get("sim_total_delay_pax_s", 0.0) / 3600.0
    if total_h == 0.0:
        # fallback to hours fields
        bus_h   = g.get("bus_pax_delay_veh_h",   0.0)
        car_h   = g.get("car_pax_delay_veh_h",   0.0)
        total_h = g.get("total_pax_delay_veh_h", bus_h + car_h)
    n_ins   = g.get("n_tsp_insertions", g.get("n_insertions", 0))
    n_ext   = g.get("n_tsp_extensions", g.get("n_extensions", 0))
    n_det   = g.get("n_tsp_detections", g.get("n_detections", 0))
    return total_h, bus_h, car_h, n_ins, n_ext, n_det


def _jct_kpis(summary, jct_id):
    for jct in summary.get("intersections", []):
        jid = jct.get("intersection_id", jct.get("id", -1))
        if int(jid) == jct_id:
            # main_pass_delay_hrs = pax-hours of delay on main approach
            main_h = jct.get("main_pass_delay_hrs",
                             jct.get("main_approach_delay_veh_h",
                             jct.get("delay_veh_h", 0.0)))
            n_ins  = jct.get("tsp_insertions", jct.get("n_tsp_insertions", jct.get("n_insertions", 0)))
            n_ext  = jct.get("tsp_extensions", jct.get("n_tsp_extensions", jct.get("n_extensions", 0)))
            spd    = jct.get("avg_speed_kmh",  jct.get("mean_speed_kmh", 0.0))
            den    = jct.get("avg_density_vkm", jct.get("mean_density_vkm", 0.0))
            return main_h, n_ins, n_ext, spd, den
    return 0.0, 0, 0, 0.0, 0.0


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    folders = _find_experiments()
    if not folders:
        print(f"No matching result folders found in {RESULTS_DIR} for seed={SEED}.")
        return

    rows = []
    no_tsp_total = None

    for folder in folders:
        summary = _load(folder)
        if summary is None:
            print(f"  [SKIP] {folder} — no summary.json")
            continue
        exp_name = folder.split(f"_seed{SEED}_")[0]
        total_h, bus_h, car_h, n_ins, n_ext, n_det = _global_kpis(summary)
        if exp_name == NO_TSP_NAME:
            no_tsp_total = total_h
        rows.append({
            "name":    exp_name,
            "folder":  folder,
            "total_h": total_h,
            "bus_h":   bus_h,
            "car_h":   car_h,
            "n_ins":   n_ins,
            "n_ext":   n_ext,
            "n_det":   n_det,
            "summary": summary,
        })

    if no_tsp_total is None or no_tsp_total == 0.0:
        no_tsp_total = rows[0]["total_h"] if rows else 1.0
        print(f"[WARN] NO_TSP not found; using first entry as baseline.")

    # Sort by total_h ascending (best first)
    rows.sort(key=lambda r: r["total_h"])

    # ── Global comparison table ───────────────────────────────────────────────
    hdr = f"{'Experiment':<30} {'Total(h)':>8} {'vs NO_TSP':>9} {'Bus(h)':>8} {'Car(h)':>8} {'n_ins':>6} {'n_ext':>6} {'n_det':>6}"
    print("\n" + "="*len(hdr))
    print("GLOBAL COMPARISON  (seed=300, ranked by total pax delay)")
    print("="*len(hdr))
    print(hdr)
    print("-"*len(hdr))
    for r in rows:
        delta_pct = (r["total_h"] - no_tsp_total) / max(no_tsp_total, 1.0) * 100.0
        flag = " ←BEST" if r == rows[0] else ""
        print(f"{r['name']:<30} {r['total_h']:>8.1f} {delta_pct:>+8.1f}%  "
              f"{r['bus_h']:>8.1f} {r['car_h']:>8.1f} "
              f"{r['n_ins']:>6} {r['n_ext']:>6} {r['n_det']:>6}{flag}")
    print("="*len(hdr))

    # ── Per-junction table for problem junctions ──────────────────────────────
    print(f"\nPER-JUNCTION BREAKDOWN — problem sites (seed={SEED})")
    for jct in PROBLEM_JCTS:
        print(f"\n  Junction {jct}")
        jhdr = f"    {'Experiment':<30} {'main_h':>7} {'Δ vs NO':>9} {'n_ins':>6} {'n_ext':>6} {'spd':>6} {'den':>6}"
        print(jhdr)
        print("    " + "-"*(len(jhdr)-4))
        # Get NO_TSP baseline for this junction
        no_tsp_row = next((r for r in rows if r["name"] == NO_TSP_NAME), None)
        no_jct_h = _jct_kpis(no_tsp_row["summary"], jct)[0] if no_tsp_row else 0.0
        for r in rows:
            jh, ji, je, spd, den = _jct_kpis(r["summary"], jct)
            delta = jh - no_jct_h
            flag = " ** WORSE" if delta > 5.0 else ""
            print(f"    {r['name']:<30} {jh:>7.1f} {delta:>+8.1f}h  "
                  f"{ji:>6} {je:>6} {spd:>6.1f} {den:>6.1f}{flag}")

    # ── Action rate summary ───────────────────────────────────────────────────
    print(f"\nACTION RATE (insertions per 100 detections)")
    print(f"  {'Experiment':<30} {'ins_rate%':>10} {'ext_rate%':>10}")
    for r in rows:
        if r["n_det"] > 0:
            ins_rate = r["n_ins"] / r["n_det"] * 100.0
            ext_rate = r["n_ext"] / r["n_det"] * 100.0
            print(f"  {r['name']:<30} {ins_rate:>9.1f}%  {ext_rate:>9.1f}%")


if __name__ == "__main__":
    main()
