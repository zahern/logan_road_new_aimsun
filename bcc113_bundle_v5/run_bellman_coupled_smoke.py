"""run_bellman_coupled_smoke.py -- one-shot smoke test for the COUPLED Bellman DP.

Run INSIDE the Aimsun Python console AFTER A FULL AIMSUN RESTART, KG model open:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_bellman_coupled_smoke.py").read())

It runs NO_TSP + BELLMAN_CTM_DP (local, gated) + BELLMAN_COUPLED (2-junction) on
ONE seed, then parses this run's engine logs and prints a PASS/FAIL verdict:
  * ENGINE_BUILD loaded (edits live, not a cached engine)
  * no [BELLMAN_CTM] errors
  * the COUPLED arm RESOLVED the downstream neighbour (COUPLED[...] with sane
    lag/Cd/Gd) at its junctions -- and whether any junction failed open
  * the action mix (does it both act and hold)
  * the paired objective / throughput vs NO_TSP from the smoke CSV

Edit the CONFIG block to change seed/arms. This is a PLUMBING test (fires /
resolves / doesn't crash), not a performance verdict -- use the 5-seed suite for
that.
"""
import os as _os
import sys as _sys
import glob as _glob
import time as _time
import csv as _csv

# ---- CONFIG (edit freely) --------------------------------------------------
_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
SEED = _os.environ.get("SMOKE_SEED", "300")
# Isolation ladder: NO_TSP (auto) -> adaptive solver -> + bus overlay -> + coupled
# DP. COUPLED - OVERLAY_ONLY = the coupled Bellman decider's own effect; the gated
# DP (0 actions) is just the adaptive base, so AIMSUN_DSW is the honest reference.
ARMS = _os.environ.get(
    "SMOKE_ARMS",
    # PRE-ARM FIX test (1 seed). Ladder pinned the regression to the green-wave
    # PRE-ARM on the decider path (NOT the overlay -- OVERLAY_ONLY was byte-identical
    # to DSW -- and NOT the committed actions). _ADAPTIVE_THRU_OPEN now sets
    # COORD_PREARM_ENABLED=False. Prior (pre-arm ON) numbers to beat on seed 300:
    #   DSW            666h / obj 155  (reference, never had a pre-arm)
    #   CHAIN2         866h / obj 116  (pre-arm ON)
    #   CHAIN2_NOTRUST 1530h / obj 67  (pre-arm ON, the blowup)
    # With the pre-arm OFF, CHAIN2 and NOTRUST should both collapse toward ~666.
    # Watch: [GREEN_OFFSET] [wave/pre-arm] lines should be ~0 now.
    "CHAMP_ADAPTIVE_AIMSUN_DSW,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2,"
    "CHAMP_ADAPTIVE_DSW_BELLMAN_CHAIN2_NOTRUST")
OUT = _os.environ.get("SMOKE_OUT", "bellman_coupled_smoke.csv")
WANT_BUILD = "3182"          # substring expected in ENGINE_BUILD on [LOAD]
# ----------------------------------------------------------------------------

_LOGDIR = _os.path.join(_HERE, "kg", "logs")
for _p in (_HERE, _os.path.join(_HERE, "kg")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)


def _line(c="-"):
    print(c * 72)


def _run():
    _os.environ["ARM_SUITE_SEEDS"] = SEED
    _os.environ["ARM_SUITE_ARMS"] = ARMS
    _os.environ["ARM_SUITE_OUT"] = OUT
    _line("=")
    print("BELLMAN COUPLED SMOKE  seed=%s" % SEED)
    print("arms:", ARMS)
    _line("=")
    _t0 = _time.time()
    _runner = _os.path.join(_HERE, "run_aimsun_arm_suite_5seeds.py")
    # executeAction inside the runner is SYNCHRONOUS on Aimsun 26, so control
    # returns here only after all sims finish (see sync-execute-baseline-hang).
    exec(compile(open(_runner, encoding="utf-8").read(), _runner, "exec"),
         {"__name__": "__main__"})
    return _t0


def _this_run_logs(_t0):
    fs = _glob.glob(_os.path.join(_LOGDIR, "Aimsun_TSP_Log_*.txt"))
    # logs written during this run (small mtime slack for clock/flush)
    return [f for f in fs if _os.path.getmtime(f) >= _t0 - 10.0]


def _read(f):
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except Exception:
        return []


def _verify(_t0):
    _line("=")
    print("VERIFY")
    _line("=")
    logs = _this_run_logs(_t0)
    if not logs:
        print("FAIL: no Aimsun_TSP_Log_*.txt from this run found in", _LOGDIR)
        print("      (did the sims run? check the console output above)")
        return
    print("parsed %d engine log file(s) from this run" % len(logs))

    build_lines, err_n = [], 0
    coupled_files = 0            # files that emitted any COUPLED[ marker
    coupled_lines = 0
    failopen_lines = 0          # [BELLMAN_CTM] in a coupled file WITHOUT COUPLED[
    chosen = {}
    lags, cds, gds = [], [], []
    sample = []

    def _num(line, key):
        try:
            seg = line.split(key, 1)[1]
            val = ""
            for ch in seg:
                if ch in "0123456789.-":
                    val += ch
                else:
                    break
            return float(val) if val not in ("", "-", ".") else None
        except Exception:
            return None

    for f in logs:
        lines = _read(f)
        has_coupled = any("COUPLED[" in ln for ln in lines)
        if has_coupled:
            coupled_files += 1
        for ln in lines:
            if "ENGINE_BUILD=" in ln and "ENGINE_BUILD=" not in "".join(build_lines):
                build_lines.append(ln.strip())
            if "[BELLMAN_CTM] error" in ln:
                err_n += 1
            if "[BELLMAN_CTM]" in ln and "error" not in ln:
                if "COUPLED[" in ln:
                    coupled_lines += 1
                    _l, _c, _g = _num(ln, "lag="), _num(ln, "Cd="), _num(ln, "Gd=")
                    if _l is not None:
                        lags.append(_l)
                    if _c is not None:
                        cds.append(_c)
                    if _g is not None:
                        gds.append(_g)
                    if len(sample) < 4:
                        sample.append(ln.strip()[-160:])
                elif has_coupled:
                    failopen_lines += 1
                # action mix (coupled arm only)
                if has_coupled and "chosen=" in ln:
                    tok = ln.split("chosen=", 1)[1].split()[0]
                    act = tok.split("_")[0]
                    chosen[act] = chosen.get(act, 0) + 1

    def _rng(xs):
        return "n=%d min=%.0f max=%.0f" % (len(xs), min(xs), max(xs)) if xs else "n=0"

    # ---- report ----
    bl = build_lines[-1] if build_lines else "(no ENGINE_BUILD line found)"
    ok_build = WANT_BUILD in bl
    print("[%s] build: %s" % ("PASS" if ok_build else "FAIL",
          bl.split("ENGINE_BUILD=")[-1][:60] if "ENGINE_BUILD=" in bl else bl))

    print("[%s] BELLMAN_CTM errors: %d" % ("PASS" if err_n == 0 else "FAIL", err_n))

    ok_res = coupled_lines > 0 and bool(lags)
    print("[%s] downstream resolved: %d COUPLED decision(s) in %d file(s)"
          % ("PASS" if ok_res else "FAIL", coupled_lines, coupled_files))
    if ok_res:
        print("        lag[s]:", _rng(lags), "| Cd[s]:", _rng(cds),
              "| Gd[s]:", _rng(gds))
    print("[%s] fail-open (coupled junctions that did NOT resolve downstream): %d"
          % ("WARN" if failopen_lines else "PASS", failopen_lines))

    print("     action mix (COUPLED arm):",
          chosen if chosen else "(no [BELLMAN_CTM] decision lines)")
    for s in sample:
        print("       e.g. ...", s)

    # ---- paired outcome from the CSV ----
    _line("-")
    csv_path = _os.path.join(_HERE, OUT)
    sm = _os.path.splitext(csv_path)[0] + "_summary.csv"
    use = sm if _os.path.isfile(sm) else csv_path
    try:
        rows = list(_csv.DictReader(open(use, encoding="utf-8-sig",
                                         errors="replace")))
        print("outcome from", _os.path.basename(use), ":")
        obj_k = "objective" if "objective" in (rows[0] if rows else {}) \
            else "stats_Objective_PaxPerDelayHr"
        thr_k = "stats_PaxEquivPassages"
        arm_k = "arm" if (rows and "arm" in rows[0]) else "run_experiment"
        seen = []
        for r in rows:
            nm = r.get(arm_k, "")
            if nm in seen:
                continue
            seen.append(nm)
            o = r.get(obj_k, r.get("stats_Objective_PaxPerDelayHr", ""))
            t = r.get(thr_k, "")
            print("   %-38s obj=%s  thru=%s" % (nm, o, t))
    except Exception as _e:
        print("   (couldn't read outcome CSV:", repr(_e), ")")
    _line("=")
    verdict = ok_build and err_n == 0 and ok_res
    print("SMOKE %s -- %s" % (
        "PASS" if verdict else "CHECK",
        "coupled DP is live, resolving downstream, and deciding"
        if verdict else "see the FAIL/WARN lines above"))
    if failopen_lines:
        print("NOTE: some coupled junctions failed open to single-junction "
              "(no downstream neighbour / unreadable signal) -- expected at the "
              "corridor ENDS, a concern only if it is most junctions.")
    _line("=")


try:
    _t = _run()
    _verify(_t)
except Exception as _e:
    import traceback as _tb
    print("SMOKE CRASHED:", repr(_e))
    _tb.print_exc()
