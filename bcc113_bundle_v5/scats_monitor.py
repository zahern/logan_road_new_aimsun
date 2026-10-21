"""scats_monitor.py -- offline SCATS health monitor for one Aimsun TSP run.

Parses an Aimsun_TSP_Log_*.txt (no Aimsun needed) and prints, per junction, the
things that decide whether the retiming can possibly beat NO_TSP:

  DS    measured degree of saturation: is it PINNED at the clamp (false gridlock),
        flat across phases (no discrimination), or genuinely varied?
  FLOW  how the flow was measured (virtual loop / snapshot / demand seed) and
        whether the loop was REJECTED as implausible (> saturation).
  SPLIT the greens the split law imposed vs the junction's COMMISSIONED greens
        (a starved arterial phase or a hogged phase is flagged).
  CYCLE the master common cycle vs the commissioned cycle (anchor).
  OFFSET the offset shifts applied (large shifts destroy the green wave).
  PLAN  whether the startup measured plan obeyed the cycle identity (sumG+L==C).

Usage:
  python scats_monitor.py                      # newest log in kg/logs
  python scats_monitor.py <path-to-log>
  python scats_monitor.py <log> --json         # machine-readable dump
"""
import os
import re
import sys
import glob
import json
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.join(HERE, "kg", "logs")


def newest_log():
    cands = glob.glob(os.path.join(LOGDIR, "Aimsun_TSP_Log_*.txt"))
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)


def parse(log_path):
    txt = open(log_path, encoding="utf-8", errors="replace").read()
    lines = txt.splitlines()

    arm = ""
    m = re.search(r"\[ARM\] exp=(\S+)", txt)
    if m:
        arm = m.group(1)

    ds = defaultdict(list)          # jid -> [(t, ds_max, spread, per_phase)]
    split = defaultdict(list)       # jid -> [(t, eff, greens_dict)]
    master = []                     # (group, members, src, crit, C, anchor)
    offsets = defaultdict(list)     # jid -> [shift]
    planopt = defaultdict(list)     # jid -> [ok_bool, greens]
    tiers = Counter()
    vloop = Counter()               # sec -> first logged flow
    vloop_reject = set()
    corridor = []
    chan = {}                       # jid -> (side, rt, slip)
    ds_terms = None                 # last [DS_TERMS] summary
    crit_bases = []                 # 'base' values from the DS diagnostic

    re_ds = re.compile(
        r"\[DS_STATE\] inter=(\d+) t=(\d+) cycle=([\d.]+)s ds_max=([\d.]+) "
        r"ds_spread=([\d.]+) crit_ph=(\d+) src=(\w+) "
        r"(?:crit\{q=(\d+) g=([\d.]+) lanes=(\d+) base=([\d.]+)[^}]*\}\s*)?"
        r"per_phase=\{(.*?)\}")
    re_split = re.compile(
        r"\[DS SPLIT\] inter=(\d+) t=([\d.]+) eff=([\d.]+)s DS=\{(.*?)\} -> greens=\{(.*?)\}")
    re_master = re.compile(
        r"\[DS MASTER\] group=(\S+) members=(\d+) src=(\S+) critDS=([\d.]+) "
        r"-> common C ([\d.]+)->([\d.]+)s")
    re_off = re.compile(r"\[DS OFFSET\] group=\S+ inter=(\d+) target=([\d.]+)s "
                        r"applied=([\d.]+)s shift=([+\-]?[\d.]+)s C=([\d.]+)s")
    re_plan = re.compile(r"\[PLAN_OPT\] inter=(\d+) src=(\w+) C=([\d.]+)s .*?"
                         r"(OK|MISMATCH) greens=\{(.*?)\}")
    re_planw = re.compile(r"\[PLAN_OPT\] inter=(\d+) WARN cycle identity violated "
                          r"\(([\d.]+) != ([\d.]+)\)")
    re_corridor = re.compile(r"\[CORRIDOR\] group=(\S+) route=\[(.*?)\]")
    re_chan = re.compile(r"\[SCATS CHAN\] inter=(\d+) SIDE=(\d+) RT_BAY=(\d+) "
                         r"SLIP=(\d+)")
    re_terms = re.compile(
        r"\[DS_TERMS\].*?DS mean=([\d.]+) max=([\d.]+).*?"
        r"spillback_floors=(\d+).*?starve_guard_floors=(\d+)")
    re_crit = re.compile(
        r"\[DS_STATE\] inter=\d+ t=\d+ .*?crit\{q=(\d+) g=([\d.]+) "
        r"lanes=(\d+) base=([\d.]+)")

    def _dict(s):
        out = {}
        for kv in s.split(","):
            if ":" in kv:
                k, v = kv.split(":", 1)
                try:
                    out[int(k.strip())] = float(v.strip())
                except Exception:
                    pass
        return out

    for ln in lines:
        if "tier=" in ln:
            try:
                tiers[ln.split("tier=")[1].split()[0]] += 1
            except Exception:
                pass
        m = re_ds.search(ln)
        if m:
            ds[int(m.group(1))].append(
                (float(m.group(2)), float(m.group(4)), float(m.group(5)),
                 _dict(m.group(12))))
            try:
                if m.group(11) is not None:
                    crit_bases.append(float(m.group(11)))
            except Exception:
                pass
            continue
        m = re_split.search(ln)
        if m:
            split[int(m.group(1))].append(
                (float(m.group(2)), float(m.group(3)), _dict(m.group(5))))
            continue
        m = re_master.search(ln)
        if m:
            master.append((m.group(1), int(m.group(2)), m.group(3),
                           float(m.group(4)), float(m.group(5)), float(m.group(6))))
            continue
        m = re_off.search(ln)
        if m:
            offsets[int(m.group(1))].append(float(m.group(4)))
            continue
        m = re_plan.search(ln)
        if m:
            planopt[int(m.group(1))].append((m.group(4) == "OK",
                                             float(m.group(3)), _dict(m.group(5))))
            continue
        m = re_planw.search(ln)
        if m:
            pass
        if "[VLOOP REJECT]" in ln:
            mm = re.search(r"sec=(\d+)", ln)
            if mm:
                vloop_reject.add(int(mm.group(1)))
        elif "[VLOOP]" in ln:
            mm = re.search(r"sec=(\d+).*flow=([\d.]+)", ln)
            if mm and int(mm.group(1)) not in vloop:
                vloop[int(mm.group(1))] = float(mm.group(2))
        m = re_corridor.search(ln)
        if m:
            corridor.append((m.group(1), m.group(2).split(",")))
            continue
        m = re_chan.search(ln)
        if m:
            chan[int(m.group(1))] = (int(m.group(2)), int(m.group(3)),
                                    int(m.group(4)))
            continue
        m = re_terms.search(ln)
        if m:
            ds_terms = {"ds_mean": float(m.group(1)), "ds_max": float(m.group(2)),
                        "spillback": int(m.group(3)),
                        "starve": int(m.group(4))}
            continue
        m = re_crit.search(ln)
        if m:
            crit_bases.append(float(m.group(4)))

    return dict(arm=arm, ds=ds, split=split, master=master, offsets=offsets,
                planopt=planopt, tiers=dict(tiers), vloop=dict(vloop),
                vloop_reject=sorted(vloop_reject), corridor=corridor, chan=chan,
                ds_terms=ds_terms, crit_bases=crit_bases)


def commissioned_greens(jid):
    """Best-effort: read the junction's COMMISSIONED cycle/greens from the KG
    corridor config, so the monitor can compare imposed vs commissioned. Returns
    (cycle_s, {phase: green}) or (0, {})."""
    try:
        from kg import intersection_configs as ic
    except Exception:
        return 0, {}
    for attr in ("JUNCTION_CONFIGS", "INTERSECTION_CONFIGS"):
        cfg = getattr(ic, attr, None)
        if isinstance(cfg, dict) and jid in cfg:
            c = cfg[jid]
            return (float(c.get("CycleTime", c.get("cycle_length", 0.0)) or 0.0),
                    {int(k): float(v) for k, v in
                     (c.get("PhaseDuration", c.get("greens", {})) or {}).items()})
    return 0, {}


def report(log_path, as_json=False):
    d = parse(log_path)
    out = {"log": os.path.basename(log_path), "arm": d["arm"],
           "junctions": {}, "flags": []}
    # flow source
    tot_tiers = sum(d["tiers"].values()) or 1
    out["flow_source"] = {k: v for k, v in sorted(d["tiers"].items())}
    out["vloop_secs"] = len(d["vloop"])
    out["vloop_rejected"] = d["vloop_reject"]
    out["channels"] = {jo: {"SIDE": v[0], "RT_BAY": v[1], "SLIP": v[2]}
                       for jo, v in d["chan"].items()}
    out["ds_terms"] = d["ds_terms"]
    if d["crit_bases"]:
        out["crit_base"] = {"n": len(d["crit_bases"]),
                            "mean": round(sum(d["crit_bases"]) / len(d["crit_bases"]), 2),
                            "max": round(max(d["crit_bases"]), 2)}

    all_jids = sorted(set(d["ds"]) | set(d["split"]) | set(d["planopt"]))
    clamp = 2.0
    for jid in all_jids:
        rec = {}
        # DS behaviour
        pinned = tot = 0
        spreads = []
        for (_t, mx, sp, pp) in d["ds"][jid]:
            tot += 1
            if abs(mx - clamp) < 1e-6:
                pinned += 1
            spreads.append(sp)
        rec["ds_n"] = tot
        rec["ds_pinned_frac"] = round(pinned / tot, 2) if tot else None
        rec["ds_spread_mean"] = round(sum(spreads) / len(spreads), 2) if spreads else None
        # splits
        if d["split"][jid]:
            _t, eff, greens = d["split"][jid][-1]
            rec["split_eff_s"] = eff
            rec["split_min_green"] = min(greens.values()) if greens else None
            rec["split_max_green"] = max(greens.values()) if greens else None
            rec["split_starved_phases"] = sorted(
                [p for p, g in greens.items() if g <= 3.1])
        # plan
        if d["planopt"][jid]:
            ok = all(o for (o, _c, _g) in d["planopt"][jid])
            rec["plan_cycle_identity_ok"] = ok
            rec["plan_cycle_s"] = d["planopt"][jid][-1][1]
        # offsets
        if d["offsets"][jid]:
            sh = d["offsets"][jid]
            rec["offset_max_shift_s"] = round(max(abs(x) for x in sh), 1)
        # commissioned
        c0, cg = commissioned_greens(jid)
        if c0:
            rec["commissioned_cycle_s"] = c0
        out["junctions"][jid] = rec

    # master cycles
    out["master"] = [
        {"group": g, "members": n, "src": s, "critDS": c, "C_from": a, "C_to": b}
        for (g, n, s, c, a, b) in d["master"]]

    # ---------------- FLAGS ----------------
    F = out["flags"]
    if out.get("ds_terms"):
        _t = out["ds_terms"]
        if _t["ds_mean"] > 1.5:
            F.append("DS mean=%.2f (max %.2f) -- DS PINNED near the clamp; the "
                     "split law has no discrimination (check the pax factor / "
                     "flow source)" % (_t["ds_mean"], _t["ds_max"]))
    if out.get("crit_base") and out["crit_base"]["mean"] > 3.0:
        F.append("critical-phase BASE DS mean=%.2f -- demand/capacity is inflated "
                 "before any floor (paxf or flow)" % out["crit_base"]["mean"])
    if d["vloop_reject"]:
        F.append("VLOOP over-count REJECTED on %d section(s) -> flows fell back "
                 "to the density x speed snapshot: %s"
                 % (len(d["vloop_reject"]), d["vloop_reject"][:12]))
    for jid, rec in out["junctions"].items():
        if rec.get("ds_pinned_frac", 0) and rec["ds_pinned_frac"] >= 0.5:
            F.append("inter=%s DS PINNED at the clamp for %d%% of the run "
                     "(false gridlock; splits/cycle/offsets driven by garbage)"
                     % (jid, int(100 * rec["ds_pinned_frac"])))
        if rec.get("ds_spread_mean") is not None and rec["ds_n"] > 5 and \
                rec["ds_spread_mean"] < 0.05:
            F.append("inter=%s DS spread ~0 (every phase reads the same DS -> "
                     "no discrimination for the split law)" % jid)
        if rec.get("plan_cycle_identity_ok") is False:
            F.append("inter=%s startup MEASURED plan violated the cycle identity "
                     "(sumG+L != C): greens over-subscribe the cycle" % jid)
        if rec.get("split_starved_phases"):
            F.append("inter=%s split law pushed phases %s to the 3 s skip floor"
                     % (jid, rec["split_starved_phases"]))
        if rec.get("offset_max_shift_s", 0) and rec["offset_max_shift_s"] > 20:
            F.append("inter=%s offset shift up to %.0fs (green wave may be "
                     "destroyed)" % (jid, rec["offset_max_shift_s"]))
    # master shrinking on zero demand
    for mm in out["master"]:
        if mm["critDS"] <= 0.0 and mm["C_to"] < mm["C_from"]:
            F.append("master group=%s shrank cycle %.0f->%.0f on critDS=0 "
                     "(demand not measured)" % (mm["group"], mm["C_from"], mm["C_to"]))
    for jid, ch in out["channels"].items():
        if ch["SIDE"] == 0 and ch["RT_BAY"] == 0 and ch["SLIP"] == 0:
            F.append("inter=%s has NO SIDE/RT_BAY/SLIP channel sections wired "
                     "(cross-street/turn monitoring blind)" % jid)
    if not F:
        F.append("no pathologies detected by the monitor")

    if as_json:
        print(json.dumps(out, indent=2, sort_keys=True))
        return out

    # ---------------- PRINT ----------------
    print("SCATS run monitor -- %s" % out["log"])
    print("arm: %s" % (out["arm"] or "(none)"))
    print("flow source: %s" % out["flow_source"])
    print("virtual-loop sections logged: %d | REJECTED: %d"
          % (out["vloop_secs"], len(out["vloop_rejected"])))
    if out.get("ds_terms"):
        _t = out["ds_terms"]
        print("DS mean=%.2f max=%.2f | spillback_floors=%d starve_guard=%d"
              % (_t["ds_mean"], _t["ds_max"], _t["spillback"], _t["starve"]))
    if out.get("crit_base"):
        print("crit base DS: n=%d mean=%.2f max=%.2f"
              % (out["crit_base"]["n"], out["crit_base"]["mean"],
                 out["crit_base"]["max"]))
    if out["channels"]:
        print("SCATS channel sections wired (SIDE/RT_BAY/SLIP): %s"
              % {k: (v["SIDE"], v["RT_BAY"], v["SLIP"])
                 for k, v in sorted(out["channels"].items())})
    print("=" * 100)
    print("%-10s %6s %8s %8s %8s %8s %8s %8s" %
          ("junction", "ds_n", "pin%", "sprd", "eff", "minG", "maxG", "cycOK"))
    for jid in sorted(out["junctions"]):
        r = out["junctions"][jid]
        print("%-10s %6s %8s %8s %8s %8s %8s %8s" % (
            jid, r.get("ds_n", "-"),
            ("%.0f" % (100 * r["ds_pinned_frac"]) if r.get("ds_pinned_frac")
             is not None else "-"),
            r.get("ds_spread_mean", "-"), r.get("split_eff_s", "-"),
            r.get("split_min_green", "-"), r.get("split_max_green", "-"),
            r.get("plan_cycle_identity_ok", "-")))
    print("=" * 100)
    print("FLAGS (%d):" % len(F))
    for f in F:
        print("  - %s" % f)
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    log = args[0] if args else newest_log()
    if not log or not os.path.exists(log):
        print("no log found; pass a path to an Aimsun_TSP_Log_*.txt")
        sys.exit(1)
    report(log, as_json=as_json)


if __name__ == "__main__":
    main()
