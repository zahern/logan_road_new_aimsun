# =============================================================================
# beamer_report.py — Beamer (LaTeX) deck generator for TSP batch results
# =============================================================================
# Reads a batch_results_*.csv (the master CSV written by the batch runners /
# the generated batch_runner_gui.py) and emits a self-contained Beamer deck:
#   * title frame
#   * experimental-design frame (strategy set, agency dials, demand levels)
#   * one frame per strategy — regime x demand-scalar response table, with
#     deltas vs the NO_TSP baseline at the same demand scalar
#   * across-strategy response frame (nominal demand)
#   * decision-support frame (winners per demand level + takeaway)
#
# Stdlib only (csv/datetime/os/shutil/subprocess) so it runs inside Aimsun's
# Python as well as the Streamlit studio.  Compilation requires a TeX
# distribution (pdflatex) — not bundled here.
# =============================================================================

import csv
import datetime
import os
import shutil
import subprocess

_REGIMES = ("PRO_BUS", "BALANCED", "PRO_CAR")


def _num(x):
    try:
        if x is None:
            return None
        s = str(x).strip()
        if not s or s.lower() in ("nan", "na", "none", ""):
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def _tex_escape(s):
    return (str(s)
            .replace("\\", r"\textbackslash{}")
            .replace("{", r"\{").replace("}", r"\}")
            .replace("$", r"\$").replace("&", r"\&")
            .replace("#", r"\#").replace("_", r"\_")
            .replace("%", r"\%").replace("~", r"\textasciitilde{}")
            .replace("^", r"\textasciicircum{}"))


def _fmt(x, suffix=""):
    if x is None:
        return "—"
    return f"{x:.1f}{suffix}"


def _pct(x):
    if x is None:
        return "—"
    return f"{x:+.1f}\\%"


def _read_rows(csv_path):
    with open(csv_path, "r", encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.DictReader(f))


def _mean(rows, col):
    vals = [_num(r.get(col)) for r in rows]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _success(rows):
    out = []
    for r in rows:
        ok = str(r.get("run_success", "")).strip().lower()
        if ok in ("1", "true", "yes"):
            out.append(r)
    return out


def _resolve(rows, keys):
    for k in keys:
        if k and k in rows and rows[k] is not None:
            return rows[k]
    return None


# Column names in batch_results_*.csv (fallbacks for older files).
_COL_TOTAL = ("stats_TotalPassDelay_hrs", "inter_sum_TotalPassDelay_hrs")
_COL_AVG   = ("stats_AvgPassDelay_s", "stats_AvgObjPassDelay", "inter_avg_AvgPassDelay_s")
_COL_BUS   = ("stats_AvgBusPassDelay_s", "inter_avg_AvgBusPassDelay_s")
_COL_CAR   = ("stats_AvgCarPassDelay_s", "inter_avg_AvgCarPassDelay_s")
_COL_BUSPAXS = ("stats_SimBusDelay_pax_s",)
_COL_CARPAXS = ("stats_SimCarDelay_pax_s",)
_COL_DET   = ("stats_TSP_Detections", "inter_sum_TSP_Detections", "inter_avg_TSP_Detections")
_COL_EXT   = ("stats_TSP_Extensions", "inter_sum_TSP_Extensions")
_COL_INS   = ("stats_TSP_Insertions", "inter_sum_TSP_Insertions")
_COL_LATE  = ("wobj_Z3_total", "stats_AvgBusPassDelay_s")
_COL_TT    = ("stats_Net_TotalTT_h_All", "stats_Net_TotalTT_h_Bus", "stats_Net_TotalTT_h_Car")
_COL_SPEED = ("stats_Net_AvgSpeed_kmh", "aimsun_avg_speed_kmh")


def _header_col(row, keys):
    for k in keys:
        if k in row:
            return k
    return None


def _metric(row, keys):
    return _num(_resolve(row, keys))


def _group_mean(rows, group_key, col):
    """Mean of col across rows belonging to one (experiment, scalar) group."""
    return _mean(rows, col)


def _regime_of(exp_name):
    up = exp_name.upper()
    for r in _REGIMES:
        if up.endswith("_" + r) or ("_" + r) in up:
            return r
    return ""


def _strategy_of(exp_name, strategy_prefixes):
    up = exp_name.upper()
    for s, tag in sorted(strategy_prefixes, key=lambda x: -len(x[0])):
        if up == s.upper() or up.startswith(s.upper() + "_"):
            return tag
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Deck generation
# ─────────────────────────────────────────────────────────────────────────────

def render_deck(batch_csv, out_tex, title, subtitle="",
                strategies=None, regimes=_REGIMES):
    """Build a Beamer deck from batch_results CSV.  Returns the out path."""
    rows = _read_rows(batch_csv)
    if not rows:
        raise ValueError(f"no rows in {batch_csv}")

    done = _success(rows)
    if not done:
        done = rows  # fall back to all rows if run_success absent

    exp_col = "run_experiment" if "run_experiment" in rows[0] else None
    scalar_col = "run_demand_scalar" if "run_demand_scalar" in rows[0] else None
    if exp_col is None:
        raise ValueError("batch_results CSV has no run_experiment column")

    # Strategy detection — from explicit list or inferred from experiment names.
    if strategies is None:
        strategies = [
            ("CPD_QL", "CPD-QL (Tabular Q-Learning)"),
            ("CELLQLEARN", "CellQ (CTM Q-Learning)"),
            ("CTMGS", "CellSearch (Exhaustive grid)"),
            ("HSLWR", "WaveGate (Harmony Search)"),
            ("NASHHS", "NashGate (Nash bargaining)"),
            ("CELLQLEARN_DP", "CellQ-Learn with DP (V2X DP)"),
        ]

    exps = sorted({r[exp_col] for r in done})
    scalars = sorted({_num(r[scalar_col]) for r in done if scalar_col and _num(r[scalar_col]) is not None}) \
        if scalar_col else [None]
    if not scalars:
        scalars = [None]

    # Baseline lookup: mean of NO_TSP rows at each demand scalar.  When a
    # per-regime NO_TSP baseline exists (e.g. NO_TSP_PRO_BUS, generated so the
    # passenger-weighted KPI uses the same bus/car occupancy as the TSP run),
    # a TSP regime compares against ITS OWN NO_TSP_{REGIME} row so the delta is
    # apples-to-apples.  Falls back to the plain NO_TSP rows (any regime).
    baseline_by_scalar = {}
    for s in scalars:
        all_base = [r for r in done
                    if "NO_TSP" in str(r.get(exp_col, "")).upper()
                    and (scalar_col is None or _num(r.get(scalar_col)) == s)]
        per_regime = {}
        for reg in regimes:
            reg_rows = [r for r in all_base
                        if (_regime_of(str(r.get(exp_col, "")))
                            .upper() == reg.upper())]
            per_regime[reg.upper()] = reg_rows
        baseline_by_scalar[s] = {
            "all": all_base,
            "regime": per_regime,
        }

    def _base_for(s, reg):
        """Return the baseline rows matching a TSP regime + demand scalar."""
        bl = baseline_by_scalar.get(s) or {}
        reg_rows = (bl.get("regime") or {}).get(reg.upper()) or []
        if reg_rows:
            return reg_rows
        return bl.get("all") or []

    present_strategies = [(tag, label) for tag, label in strategies
                          if any(_strategy_of(e, [(tag, label)]) for e in exps)]

    L = []
    L.append("% Auto-generated by beamer_report.py — do not hand-edit")
    L.append(r"\documentclass[10pt]{beamer}")
    L.append(r"\usepackage[T1]{fontenc}")
    L.append(r"\usepackage[utf8]{inputenc}")
    L.append(r"\usepackage{booktabs}")
    L.append(r"\usepackage{xcolor}")
    L.append(r"\usepackage{array}")
    L.append(r"\usetheme{Madrid}")
    L.append(r"\usecolortheme{whale}")
    L.append(r"\setbeamertemplate{navigation symbols}{}")
    L.append("")
    L.append(r"\title{%s}" % _tex_escape(title))
    if subtitle:
        L.append(r"\subtitle{%s}" % _tex_escape(subtitle))
    L.append(r"\date{%s}" % datetime.date.today().isoformat())
    L.append("")
    L.append(r"\begin{document}")
    L.append(r"\frame{\titlepage}")
    L.append("")

    # ── Design frame ─────────────────────────────────────────────────────────
    strat_line = r" $\cdot$ ".join(r"\texttt{%s}" % _tex_escape(tag) for tag, _ in present_strategies) \
        if present_strategies else "—"
    L.append(r"\begin{frame}{Design}")
    L.append(r"\centering")
    L.append(r"\begin{tabular}{lp{9.5cm}}")
    L.append(r"\toprule")
    L.append(r"\textbf{Axis} & \textbf{Levels} \\")
    L.append(r"\midrule")
    L.append(r"Strategy & %s \\" % strat_line)
    L.append(r"Bus-vs-car value & \texttt{PRO\_BUS} (bus 60 / car 1.2 pax) $\cdot$ "
             r"\texttt{BALANCED} (40 / 1.5) $\cdot$ \texttt{PRO\_CAR} (30 / 2.5) \\")
    L.append(r"Bus lateness & takeover 30\,s / sens 2.5 $\cdot$ 60\,s / 1.5 $\cdot$ "
             r"9999\,s / 0.5 (plus $\gamma$ 0.5 / 0.2 / 0.0) \\")
    L.append(r"Demand / congestion & %s \\" %
             r" $\cdot$ ".join(_fmt(s, "$\\times$") if s is not None else "—"
                              for s in scalars))
    L.append(r"Baseline & \texttt{NO\_TSP} fixed-time control at each demand level \\")
    L.append(r"\bottomrule")
    L.append(r"\end{tabular}")
    L.append(r"\end{frame}")
    L.append("")

    # ── Per-strategy frames ───────────────────────────────────────────────────
    for tag, label in present_strategies:
        L.append(r"\begin{frame}{%s}" % _tex_escape(label))
        L.append(r"\centering\small")
        L.append(r"\begin{tabular}{lrrrrrrrrr}")
        L.append(r"\toprule")
        L.append(r"Regime & Scalar & TotDelay & $\Delta$Tot & BusDel & $\Delta$Bus"
                 r" & CarDel & B/C & Detections & Lateness \\")
        L.append(r"& & (hrs) & \% & (s) & \% & (s) & & & \\")
        L.append(r"\midrule")
        for s in scalars:
            for reg in regimes:
                grp = [r for r in done
                       if _strategy_of(r.get(exp_col, ""), [(tag, label)]) is not None
                       and _regime_of(r.get(exp_col, "")).upper() == reg.upper()
                       and (scalar_col is None or _num(r.get(scalar_col)) == s)]
                if not grp:
                    continue
                base_rows = _base_for(s, reg)
                tot = _group_mean(grp, None, _header_col(grp[0], _COL_TOTAL))
                avg = _group_mean(grp, None, _header_col(grp[0], _COL_AVG))
                bus = _group_mean(grp, None, _header_col(grp[0], _COL_BUS))
                car = _group_mean(grp, None, _header_col(grp[0], _COL_CAR))
                det = _group_mean(grp, None, _header_col(grp[0], _COL_DET))
                late = _group_mean(grp, None, _header_col(grp[0], _COL_LATE))

                base_tot = _group_mean(base_rows, None, _header_col(base_rows[0], _COL_TOTAL)) \
                    if base_rows else None
                base_bus = _group_mean(base_rows, None, _header_col(base_rows[0], _COL_BUS)) \
                    if base_rows else None

                dtot = _pct(((tot - base_tot) / base_tot * 100.0)) if (tot is not None and base_tot) else "—"
                dbus = _pct(((bus - base_bus) / base_bus * 100.0)) if (bus is not None and base_bus) else "—"

                bc = _benefit_cost(grp, base_rows,
                                   _header_col(grp[0], _COL_BUSPAXS),
                                   _header_col(grp[0], _COL_CARPAXS))

                scl = _fmt(s) if s is not None else "—"
                L.append(r"%s & %s & %s & %s & %s & %s & %s & %s & %s & %s \\"
                         % (r"\texttt{%s}" % _tex_escape(reg.upper()),
                            scl,
                            _fmt(tot), dtot, _fmt(bus), dbus, _fmt(car),
                            bc, _fmt(det, ""), _fmt(late, "")))
        L.append(r"\bottomrule")
        L.append(r"\end{tabular}")
        L.append(r"\end{frame}")
        L.append("")

    # ── Across-strategy response at nominal demand ────────────────────────────
    nominal = [s for s in scalars if s is not None and abs(s - 1.0) < 1e-9]
    if nominal:
        s = nominal[0]
        L.append(r"\begin{frame}{Across strategies — total delay response at demand $\times 1.0$}")
        L.append(r"\centering\small")
        L.append(r"\begin{tabular}{lccc}")
        L.append(r"\toprule")
        L.append(r"Strategy & \texttt{PRO\_BUS} & \texttt{BALANCED} & \texttt{PRO\_CAR} \\")
        L.append(r"\midrule")
        for tag, label in present_strategies:
            cells = []
            for reg in regimes:
                grp = [r for r in done
                       if _strategy_of(r.get(exp_col, ""), [(tag, label)]) is not None
                       and _regime_of(r.get(exp_col, "")).upper() == reg.upper()
                       and _num(r.get(scalar_col)) == s]
                base_rows = _base_for(s, reg)
                tot = _group_mean(grp, None, _header_col(grp[0], _COL_TOTAL)) if grp else None
                base_tot = _group_mean(base_rows, None, _header_col(base_rows[0], _COL_TOTAL)) \
                    if base_rows else None
                if tot is not None and base_tot:
                    cells.append(_pct((tot - base_tot) / base_tot * 100.0))
                else:
                    cells.append("—")
            L.append(r"\texttt{%s} & %s & %s & %s \\"
                     % (_tex_escape(tag), cells[0], cells[1], cells[2]))
        L.append(r"\bottomrule")
        L.append(r"\end{tabular}")
        L.append(r"\end{frame}")
        L.append("")

    # ── Decision support ──────────────────────────────────────────────────────
    L.append(r"\begin{frame}{Decision support — winners per demand level}")
    L.append(r"\small")
    for s in scalars:
        best_tot = best_bus = None
        bc_best = None
        for tag, label in present_strategies:
            for reg in regimes:
                grp = [r for r in done
                       if _strategy_of(r.get(exp_col, ""), [(tag, label)]) is not None
                       and _regime_of(r.get(exp_col, "")).upper() == reg.upper()
                       and (scalar_col is None or _num(r.get(scalar_col)) == s)]
                if not grp:
                    continue
                base_rows = _base_for(s, reg)
                tot = _group_mean(grp, None, _header_col(grp[0], _COL_TOTAL))
                bus = _group_mean(grp, None, _header_col(grp[0], _COL_BUS))
                bc = _benefit_cost(grp, base_rows,
                                   _header_col(grp[0], _COL_BUSPAXS),
                                   _header_col(grp[0], _COL_CARPAXS))
                key = (tag, reg, tot)
                if best_tot is None or (tot is not None and best_tot[2] is not None and tot < best_tot[2]):
                    best_tot = key
                if best_bus is None or (bus is not None and best_bus[2] is not None and bus < best_bus[2]):
                    best_bus = (tag, reg, bus)
                if bc not in (None, "—", r"$\infty$") and (bc_best is None or _num(bc) > _num(bc_best[2])):
                    bc_best = (tag, reg, bc)
        scl = _fmt(s) if s is not None else "all"
        bt_name = _tex_escape(f"{best_tot[0]}_{best_tot[1]}") if best_tot else "---"
        bt_val  = _fmt(best_tot[2]) if best_tot and best_tot[2] is not None else "---"
        bb_name = _tex_escape(f"{best_bus[0]}_{best_bus[1]}") if best_bus else "---"
        bc_name = _tex_escape(f"{bc_best[0]}_{bc_best[1]}") if bc_best else "---"
        L.append(r"\textbf{Demand %s:} lowest total delay = \texttt{%s} (%s); "
                 r"lowest bus delay = \texttt{%s}; best benefit/cost = \texttt{%s} \\"
                 % (scl, bt_name, bt_val, bb_name, bc_name))
    L.append(r"\vspace{0.35cm}")
    L.append(r"\textbf{Practitioner takeaway:} compare the three regimes at each "
             r"demand level — a bus-first (\texttt{PRO\_BUS}) agency trades car delay "
             r"for bus gain; a car-first (\texttt{PRO\_CAR}) agency concedes bus gain "
             r"to protect general traffic; the balanced regime sits between. The "
             r"regime that wins the total-delay comparison indicates which valuation "
             r"the corridor's demand profile rewards.")
    L.append(r"\end{frame}")
    L.append("")

    L.append(r"\end{document}")
    L.append("")

    os.makedirs(os.path.dirname(os.path.abspath(out_tex)), exist_ok=True)
    with open(out_tex, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return out_tex


def _benefit_cost(grp, base_rows, bus_pax_col, car_pax_col):
    if not grp or not base_rows or not bus_pax_col or not car_pax_col:
        return "—"
    bus = _mean(grp, bus_pax_col)
    car = _mean(grp, car_pax_col)
    base_bus = _mean(base_rows, bus_pax_col)
    base_car = _mean(base_rows, car_pax_col)
    if None in (bus, car, base_bus, base_car):
        return "—"
    d_bus = base_bus - bus   # pax·s saved (>0 good)
    d_car = car - base_car   # pax·s lost  (>0 bad)
    if d_bus <= 0:
        return "—"          # no bus benefit → ratio undefined
    if d_car <= 0:
        return r"$\infty$"
    return f"{d_bus / d_car:.1f}"


# ─────────────────────────────────────────────────────────────────────────────
# Compilation
# ─────────────────────────────────────────────────────────────────────────────

def find_pdflatex():
    exe = shutil.which("pdflatex")
    if exe:
        return exe
    candidates = [
        r"C:\Program Files\MiKTeX\miktex\bin\x64\pdflatex.exe",
        r"C:\Program Files\MiKTeX\miktex\bin\pdflatex.exe",
        r"C:\texlive\2024\bin\windows\pdflatex.exe",
        r"C:\texlive\2023\bin\windows\pdflatex.exe",
        r"C:\texlive\2022\bin\windows\pdflatex.exe",
        r"C:\texlive\2021\bin\windows\pdflatex.exe",
        r"C:\texlive\2020\bin\windows\pdflatex.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def compile_deck(tex_path, runs=2):
    """Compile a deck twice (refs) with pdflatex.  Returns (ok, message)."""
    exe = find_pdflatex()
    if not exe:
        return (False,
                "pdflatex not found. Install MiKTeX or TeX Live, or compile "
                f"manually:  pdflatex -interaction=nonstopmode {os.path.basename(tex_path)}")
    workdir = os.path.dirname(os.path.abspath(tex_path))
    base = os.path.basename(tex_path)
    for i in range(runs):
        proc = subprocess.run(
            [exe, "-interaction=nonstopmode", "-halt-on-error", base],
            cwd=workdir, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            tail = (proc.stdout or proc.stderr or "")[-1500:]
            return (False, f"pdflatex failed (pass {i + 1}):\n{tail}")
    pdf = os.path.splitext(tex_path)[0] + ".pdf"
    if os.path.isfile(pdf):
        return (True, f"Compiled -> {pdf}")
    return (False, "pdflatex ran but produced no PDF.")


if __name__ == "__main__":
    import sys
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + "_deck.tex"
    render_deck(src, out, title="TSP results", subtitle=os.path.basename(src))
    print(f"Wrote {out}")
