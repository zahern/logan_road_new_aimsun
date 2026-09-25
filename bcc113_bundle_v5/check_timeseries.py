#!/usr/bin/env python3
"""check_timeseries.py -- functional test for the controller flow logic.

Validates section_timeseries.csv (per-30s per-section q/k/v written live by
Simulation_Stats) for one run folder, WITHOUT Aimsun (stdlib only):

    python check_timeseries.py [run_folder]

Default: newest folder under kg\\results (else logan_road_new\\results)
containing section_timeseries.csv.

Checks:
  1. SHAPE      -- required columns, 30 s windows, contiguous per section.
  2. PROVENANCE -- AKIEST vs IMPOSED split; IMPOSED rows must satisfy
                   q == k*v*lanes (identity forced by construction).
  3. AKIEST     -- independently measured triplets; residual distribution.
  4. MEANS      -- per-section window means must reproduce section_stats.csv
                   run-means (same samples, same folder).
  5. BOUNDS     -- physical plausibility per row.

Exit 0 unless a FAIL fires (WARNs still exit 0).
"""
import csv
import os
import statistics as st
import sys

def _bundle_root():
    # __file__ is undefined under console exec(); Aimsun's cwd is its install
    # dir -- neither locates the bundle. The bundle is wherever
    # champion_search.py lives: check __file__ dir, cwd, then the known path.
    _cands = []
    try:
        if "__file__" in dir():
            _cands.append(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    _cands.append(os.getcwd())
    _cands.append(r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5")
    for _c in _cands:
        if os.path.isfile(os.path.join(_c, "champion_search.py")):
            return _c
    return _cands[-1]


ROOT = _bundle_root()
REQ = ("t_start_s", "t_end_s", "SectionID", "IntersectionID", "IsMain",
       "Lanes", "Length_km", "q_veh_h", "k_vkm_lane", "v_kmh",
       "n_veh", "queue_veh", "src", "q_minus_kv")


def _f(x, default=float("nan")):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _candidate_roots():
    # Console cwd is unreliable (Aimsun console opens elsewhere), so search
    # every plausible bundle location and use whichever actually holds results.
    seen, out = set(), []
    for _r in (ROOT, r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"):
        _r = os.path.abspath(_r)
        if _r not in seen:
            seen.add(_r)
            out.append(_r)
    return out


def _has_live_rows(path, need=1):
    """True if the timeseries holds >=need AKIEST rows (measurable run)."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for i, row in enumerate(csv.DictReader(fh)):
                if row.get("src") == "AKIEST" and _f(row.get("q_veh_h")) > 0:
                    need -= 1
                    if need <= 0:
                        return True
                if i > 20000:
                    break
    except OSError:
        pass
    return False


def _find_latest():
    # Newest FINISHED *measurable* run: requires simulation_results.csv (no
    # in-progress folders) AND at least one AKIEST row (truncated warmup-only
    # runs like MARL_RL seed400/2026-09-06 measure nothing). Falls back to the
    # newest finished folder with an explicit warning.
    cands, fallback = [], None
    for _root in _candidate_roots():
        for corr in ("kg", "logan_road_new"):
            base = os.path.join(_root, corr, "results")
            if not os.path.isdir(base):
                continue
            for name in os.listdir(base):
                p = os.path.join(base, name)
                csvp = os.path.join(p, "section_timeseries.csv")
                finp = os.path.join(p, "simulation_results.csv")
                if os.path.isfile(csvp) and os.path.isfile(finp):
                    try:
                        mt = os.path.getmtime(csvp)
                    except OSError:
                        continue
                    cands.append((mt, p))
    if not cands:
        return None
    cands.sort(reverse=True)
    for _mt, _p in cands:
        if _has_live_rows(os.path.join(_p, "section_timeseries.csv")):
            return _p
    print("WARNING: no finished run with live (AKIEST) rows; showing newest "
          "finished folder (likely truncated) for inspection only.")
    return cands[0][1]


def main(folder):
    fails, warns = [], []

    ts_path = os.path.join(folder, "section_timeseries.csv")
    if not os.path.isfile(ts_path):
        print(f"FAIL: no section_timeseries.csv in {folder}")
        return 1
    with open(ts_path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    print(f"folder: {folder}\nrows: {len(rows)}")
    if not rows:
        print("FAIL: timeseries file empty")
        return 1

    # ── 1. SHAPE ──
    missing = [c for c in REQ if c not in rows[0]]
    if missing:
        print(f"FAIL: missing columns {missing}")
        return 1
    widths = {(round(_f(r["t_end_s"]) - _f(r["t_start_s"]), 3)) for r in rows}
    print(f"window widths seen (s): {sorted(widths)}")
    partial = sum(1 for r in rows
                  if abs(round(_f(r["t_end_s"]) - _f(r["t_start_s"]), 3) - 30.0) > 1e-6)
    if partial:
        print(f"partial (warmup) windows excluded from gap check: {partial}")
    by_sec = {}
    for r in rows:
        # Skip warmup/partial windows: only full 30 s samples must be contiguous.
        if abs(round(_f(r["t_end_s"]) - _f(r["t_start_s"]), 3) - 30.0) > 1e-6:
            continue
        by_sec.setdefault(str(r["SectionID"]), []).append(round(_f(r["t_end_s"]), 1))
    gaps = 0
    for sec, ends in by_sec.items():
        ends = sorted(ends)
        # First interval aligns from the warmup sample; check regularity after it.
        diffs = [b - a for a, b in zip(ends[1:], ends[2:])]
        if any(abs(d - 30.0) > 1.0 for d in diffs):
            gaps += 1
    print(f"sections: {len(by_sec)}, sections with window gaps: {gaps}")
    if gaps:
        warns.append(f"{gaps} section(s) miss 30 s windows")

    # ── 2/3. PROVENANCE + residuals ──
    srcs = {}
    for r in rows:
        srcs[r.get("src", "?")] = srcs.get(r.get("src", "?"), 0) + 1
    print(f"src split: {srcs}")
    if set(srcs) - {"AKIEST", "IMPOSED"}:
        fails.append(f"unknown src values: {sorted(set(srcs) - {'AKIEST', 'IMPOSED'})}")

    def rel(r):
        q = _f(r["q_veh_h"])
        if not (q == q) or q <= 50:
            return None
        res = _f(r["q_minus_kv"], 0.0)
        return abs(res) / q

    imp = [rel(r) for r in rows if r.get("src") == "IMPOSED"]
    imp = [x for x in imp if x is not None]
    if imp:
        print(f"IMPOSED rel-resid: max={max(imp):.5f} (must be ~0, identity forced)")
        if max(imp) > 0.01:
            fails.append(f"IMPOSED rows violate q=k*v*lanes (max rel {max(imp):.4f})")
    aki = [rel(r) for r in rows if r.get("src") == "AKIEST"]
    aki = [x for x in aki if x is not None]
    if not aki:
        fails.append("no AKIEST rows with q>50: nothing independently measured")
    else:
        med, p90 = st.median(aki), sorted(aki)[min(len(aki) - 1, int(0.9 * len(aki)))]
        print(f"AKIEST rel-resid (q>50): n={len(aki)} median={med:.3f} p90={p90:.3f}")
        if med == 0.0 and p90 == 0.0:
            fails.append("AKIEST residuals identically zero: mislabeled IMPOSED rows?")
        elif med > 0.25:
            warns.append(f"AKIEST median rel-resid {med:.2f} > 0.25: snapshot/window mismatch high")

    # ── 4. MEANS vs section_stats.csv ──
    st_path = os.path.join(folder, "section_stats.csv")
    if not os.path.isfile(st_path):
        warns.append("section_stats.csv missing: mean-consistency skipped")
    else:
        with open(st_path, newline="", encoding="utf-8-sig") as fh:
            srows = list(csv.DictReader(fh))
        last = {}
        for r in srows:  # file is append-only: last row per section wins
            if str(r.get("SectionID", "")):
                last[str(r["SectionID"])] = r
        agg = {}
        for r in rows:
            a = agg.setdefault(str(r["SectionID"]), {"q": [], "k": [], "v": []})
            a["q"].append(_f(r["q_veh_h"]))
            a["k"].append(_f(r["k_vkm_lane"]))
            a["v"].append(_f(r["v_kmh"]))
        n_cmp, n_ok = 0, 0
        diffs = []
        for sec, a in agg.items():
            if sec not in last:
                continue
            try:
                ref = float(last[sec]["AvgFlow_veh_h"])
            except (TypeError, ValueError, KeyError):
                continue
            mq = st.mean([x for x in a["q"] if x == x])
            denom = abs(ref) if ref else 1.0
            d = abs(mq - ref) / denom
            diffs.append(d)
            n_cmp += 1
            if d <= 0.05:
                n_ok += 1
        if n_cmp == 0:
            warns.append("no overlapping sections with section_stats.csv")
        else:
            print(f"mean-consistency: {n_ok}/{n_cmp} sections within 5% "
                  f"(median diff {st.median(diffs):.4f})")
            if n_ok < 0.8 * n_cmp:
                fails.append("window means do NOT reproduce section_stats run-means: "
                             "record path diverges from accumulator path")

    # ── 5. BOUNDS ──
    bad = 0
    for r in rows:
        q, k, v = _f(r["q_veh_h"]), _f(r["k_vkm_lane"]), _f(r["v_kmh"])
        qu = _f(r["queue_veh"])
        if not (0 <= q <= 20000 and k >= 0 and k <= 1000 and 0 <= v <= 150
                and qu >= 0):
            bad += 1
            if bad <= 3:
                print(f"  out-of-bounds: sec={r['SectionID']} t={r['t_end_s']} "
                      f"q={q} k={k} v={v} queue={qu}")
    print(f"bound violations: {bad}")
    if bad:
        fails.append(f"{bad} row(s) physically implausible")

    has_new = any("k_snap_vkm_lane" in r for r in rows)
    if has_new:
        # ── 6. k_avg vs k_snap: prove time-averaging improved consistency ──
        for tag, kf in (("avg", "k_vkm_lane"), ("snap", "k_snap_vkm_lane")):
            rels = []
            for r in rows:
                if r.get("src") != "AKIEST":
                    continue
                q = _f(r["q_veh_h"])
                if not (q == q) or q <= 50:
                    continue
                kk = _f(r.get(kf, "nan"))
                vv = _f(r["v_kmh"])
                ll = _f(r.get("Lanes", 1))
                if kk == kk and vv == vv and vv > 1:
                    rels.append(abs(q - kk * ll * vv) / q)
            if rels:
                print(f"k_{tag} rel-resid (AKIEST q>50): n={len(rels)} "
                      f"median={st.median(rels):.3f}")
        # ── 7. Threshold monotonicity: q3 <= q5 <= q10 per row ──
        mono_bad = sum(
            1 for r in rows
            if not (_f(r.get("queue_veh_3", 0)) <= _f(r.get("queue_veh", 0)) + 1e-9
                    <= _f(r.get("queue_veh_10", 0)) + 1e-9))
        print(f"threshold-monotonicity violations: {mono_bad}")
        if mono_bad:
            fails.append(f"{mono_bad} row(s) break q3<=q5<=q10: queue logic bug")
        # ── 8. Intersection conservation: dQ ~ (up-down)*dt, main+side split ──
        for side_tag, is_main in (("main", "1"), ("side", "0")):
            errs, n_skip = [], 0
            sects = {}
            for r in rows:
                if str(r.get("IsMain", "")) != is_main:
                    continue
                sects.setdefault((str(r.get("IntersectionID")), round(_f(r["t_end_s"]), 1)),
                                 []).append(r)
            by_inter = {}
            for (iid, te), rs in sects.items():
                # Vehicle conservation applies to the TOTAL section occupancy
                # (n_veh, all lanes), NOT the queued subset. Using
                # queue_veh x Lanes (vehicles below 5 km/h) compared the CHANGE
                # IN QUEUE against NET FLOW -- but sections gain/lose MOVING
                # vehicles without queueing, so that leg always disagreed by the
                # non-queued throughput (~12 veh main / 8 side, a false alarm).
                # n_veh is already an all-lanes count, so no x Lanes. (fixed 2026-09-07)
                qv = sum(_f(r.get("n_veh", 0)) or 0 for r in rs)
                up = sum(_f(r.get("q_up_veh_h", 0)) or 0 for r in rs)
                dn = sum(_f(r.get("q_veh_h", 0)) or 0 for r in rs)
                by_inter.setdefault(iid, []).append((te, qv, up, dn))
            for iid, series in by_inter.items():
                series.sort()
                for (t0, q0, _u0, _d0), (t1, q1, u1, d1) in zip(series, series[1:]):
                    dt = t1 - t0
                    if not (20 <= dt <= 45):
                        continue
                    if u1 == 0 and d1 == 0:
                        continue  # nothing happening
                    if u1 == 0 and d1 > 0:
                        n_skip += 1  # upflow unreadable here; cannot verify
                        continue
                    pred = (u1 - d1) * dt / 3600.0
                    errs.append(abs((q1 - q0) - pred))
            if errs:
                print(f"conservation ({side_tag}): n={len(errs)} median|dN-(up-dn)dt|="
                      f"{st.median(errs):.2f} veh (skipped-upflow={n_skip})")
                if st.median(errs) > 5.0:
                    warns.append(f"{side_tag} vehicle conservation median err "
                                 f"{st.median(errs):.1f} veh > 5: occupancy/flow legs disagree")
            else:
                print(f"conservation ({side_tag}): no verifiable windows (upflow missing?)")
                if n_skip > 20:
                    warns.append(f"{side_tag}: {n_skip} windows lack upflow readings")
        # ── 9. Queue-metres calibration table ──
        ratios_m, ratios_lq, agree_35, agree_510, n_q = [], [], 0, 0, 0
        for r in rows:
            qm, q5 = _f(r.get("queue_m", "nan")), _f(r.get("queue_veh", "nan"))
            lanes = _f(r.get("Lanes", 1)) or 1
            lq = _f(r.get("aki_longqueue_avg", "nan"))
            if q5 == q5 and q5 > 0.5:
                n_q += 1
                if qm == qm:
                    ratios_m.append(qm / (q5 * lanes * 5.0))
                if lq == lq and lq > 0:
                    ratios_lq.append(lq / (q5 * lanes))
                if _f(r.get("queue_veh_3", "nan")) <= q5 + 1e-9:
                    agree_35 += 1
                if q5 <= _f(r.get("queue_veh_10", "nan")) + 1e-9:
                    agree_510 += 1
        if n_q:
            _mm = f"{st.median(ratios_m):.2f}" if ratios_m else "n/a"
            _ml = f"{st.median(ratios_lq):.2f}" if ratios_lq else "n/a"
            print(f"queue calibration (n={n_q} queued windows): "
                  f"queue_m/(N*5m) median={_mm} "
                  f"(~1.0 = jam-packed contiguous); "
                  f"LongQueue/N median={_ml} "
                  f"(~1.0 = AKI agrees); "
                  f"q3<=q5 {agree_35 / n_q:.0%}, q5<=q10 {agree_510 / n_q:.0%}")
    else:
        print("(new-column checks skipped: run predates k_avg/queue_m/q_up fields)")

    print("-" * 60)
    for w in warns:
        print(f"WARN: {w}")
    if fails:
        for x in fails:
            print(f"FAIL: {x}")
        print("VERDICT: FAIL")
        return 1
    print("VERDICT: PASS" + (" (with warnings)" if warns else ""))
    return 0


if __name__ == "__main__":
    _folder = sys.argv[1] if len(sys.argv) > 1 else _find_latest()
    if not _folder:
        print("No run folder with section_timeseries.csv found under kg/results "
              "or logan_road_new/results. Pass a run folder explicitly.")
        sys.exit(1)
    sys.exit(main(_folder))
