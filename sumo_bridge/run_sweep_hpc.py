# run_sweep_hpc.py
# Strategy tuning sweeps on SUMO - champion-search ARMS x seeds x demand.
#
#   # full Phase-1 replica (8 arms, 5 eval seeds) on KG:
#   python run_sweep_hpc.py --corridor kg --scenario kg_scenario --jobs 6
#
#   # quick two-arm smoke:
#   python run_sweep_hpc.py --corridor kg --scenario kg_scenario --arms NO_TSP,DCTSP_MP_ECTM --seeds 300 --end 900 --jobs 2
#
# Each run = one `run_sumo_hpc.py` subprocess against a per-worker sandbox
# (controller copies with plotting disabled), producing one CSV row per
# (arm, seed, phase, demand scalar).

import argparse
import csv
import glob
import os
import re
import shutil
import subprocess
import sys
import time

from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sweep_arms import (ARMS, LEARNING_ARMS, EVAL_SEEDS, TRAIN_SEEDS,
                        BXT_TRAIN_EPSILON, PLOT_FLAGS_OFF)

REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
CSV_FIELDS = ["corridor", "arm", "strategy", "seed", "phase", "demand_scalar",
              "obj_pax_per_delay_hr", "avg_bus_pass_delay_s",
              "avg_total_pass_delay_per_hr", "avg_main_delay_per_hr",
              "avg_side_delay_per_hr", "bus_passengers", "ok", "wall_s",
              # v8 action-profile telemetry: is the action space working?
              "n_tsp_extensions", "n_tsp_insertions", "n_tsp_green_realloc",
              "n_tsp_early_red", "n_tsp_offset_corr", "n_tsp_phase_skip",
              "n_tsp_phase_rot", "n_decider_cost_veto"]

_ARGS = None          # set in main() for worker processes
_SANDBOX_TPL = None


def _patch_controller(path, repl):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    for var, val in repl.items():
        pat = re.compile(r"(?m)^(%s)(\s*:\s*bool)?\s*=.*$" % re.escape(var))
        if pat.search(txt):
            txt = pat.sub(lambda m: "%s%s = %s"
                          % (m.group(1), m.group(2) or "", val), txt)
        else:
            txt = "%s = %s\n%s" % (var, val, txt)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(txt)


def prepare_sandbox(corridor, sandbox_dir):
    corr = os.path.join(REPO_ROOT, corridor)
    os.makedirs(sandbox_dir, exist_ok=True)
    for fn in ("intersection_controller.py", "intersection_configs.py",
               "Simulation_Stats.py"):
        src = os.path.join(corr, fn)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(sandbox_dir, fn))
    ctrl = os.path.join(sandbox_dir, "intersection_controller.py")
    repl = dict(PLOT_FLAGS_OFF)
    repl["BXT_TRAIN_SEEDS"] = repr(list(TRAIN_SEEDS))
    repl["BXT_EVAL_SEEDS"] = repr(list(EVAL_SEEDS))
    repl["BXT_TRAIN_EPSILON"] = repr(float(BXT_TRAIN_EPSILON))
    _patch_controller(ctrl, repl)
    logs = os.path.join(sandbox_dir, "logs")
    if os.path.isdir(logs):
        shutil.rmtree(logs, ignore_errors=True)
    return ctrl


def build_jobs(args):
    wanted = set(args.arms.split(",")) if args.arms else None
    scalars = [float(x) for x in args.demand.split(",")]
    jobs = []
    for scalar in scalars:
        for arm in ARMS:
            if wanted and arm["name"] not in wanted:
                continue
            is_learner = arm["name"] in LEARNING_ARMS
            seeds = (list(TRAIN_SEEDS) + list(EVAL_SEEDS)) if is_learner \
                else list(args.seeds)
            for seed in seeds:
                phase = "train" if (is_learner and seed in TRAIN_SEEDS) else "eval"
                if phase == "train" and args.skip_train:
                    continue
                jobs.append({"arm": arm, "seed": seed, "phase": phase,
                             "scalar": scalar})
    return jobs


def kpis_from_summary(workdir):
    cands = sorted(glob.glob(os.path.join(workdir, "logs",
                                          "tsp_run_summary_*.txt")),
                   key=os.path.getmtime)
    if not cands:
        return {}
    out = {}
    want = {
        "avg_obj_pass_delay": "obj_pax_per_delay_hr",
        "avg_bus_pass_delay_s": "avg_bus_pass_delay_s",
        "avg_total_pass_delay_per_hr": "avg_total_pass_delay_per_hr",
        "avg_main_pass_delay_per_hr": "avg_main_delay_per_hr",
        "avg_side_pass_delay_per_hr": "avg_side_delay_per_hr",
        "bus_passengers": "bus_passengers",
        # v8 action-profile telemetry (per-family executed counts + vetoes)
        "n_tsp_extensions": "n_tsp_extensions",
        "n_tsp_insertions": "n_tsp_insertions",
        "n_tsp_green_realloc": "n_tsp_green_realloc",
        "n_tsp_early_red": "n_tsp_early_red",
        "n_tsp_offset_corr": "n_tsp_offset_corr",
        "n_tsp_phase_skip": "n_tsp_phase_skip",
        "n_tsp_phase_rot": "n_tsp_phase_rot",
        "n_decider_cost_veto": "n_decider_cost_veto",
    }
    try:
        with open(cands[-1], encoding="utf-8", errors="replace") as f:
            for line in f:
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                k = k.strip()
                v = v.strip()
                if k in want:
                    try:
                        out[want[k]] = float(v)
                    except ValueError:
                        pass
    except Exception:
        pass
    return out


def _set_control_mode(ctrl_path, strategy):
    """Mirror kg/batch_runner.py set_control_mode(): the sandbox controller
    ships with CONTROL_MODE = "NORMAL"; without patching it to the arm's real
    mode the controller runs run_normal() and TSP NEVER engages (measured:
    every arm byte-identical to NO_TSP in sweep o25051010).  Sandboxes are
    per-worker and jobs within a worker are sequential, so patching before
    each subprocess is race-free."""
    if strategy == "GROUP_BASED_FIXED":
        mode, prio = "GROUP_BASED", "True"
    elif strategy in ("REWARD_TSP", "DRL_DENSITY", "HARMONY", "URTSP", "NORMAL"):
        mode, prio = strategy, "False"
    elif strategy == "GLOBAL_REWARD":
        mode, prio = "DRL_DENSITY", "False"   # DRL_DENSITY reward path
    else:
        mode, prio = strategy, "True"
    _patch_controller(ctrl_path, {"CONTROL_MODE": repr(mode),
                                  "GROUP_BASED_BUS_PRIORITY": prio})


def _run_job(job):
    """worker: runs in a Pool process; globals _ARGS/_SANDBOX_TPL set by init"""
    sandbox = "%s_p%d" % (_SANDBOX_TPL, os.getpid())
    if not os.path.exists(os.path.join(sandbox, "intersection_controller.py")):
        prepare_sandbox(_ARGS.corridor, sandbox)

    arm = job["arm"]
    # CONTROL_MODE must match this arm BEFORE the subprocess execs the sandbox
    # controller (the file is read fresh by every run_sumo_hpc invocation).
    _set_control_mode(os.path.join(sandbox, "intersection_controller.py"),
                      arm["strategy"])

    rov = dict(arm.get("reward_overrides") or {})
    if arm["strategy"] != "NORMAL":
        rov["Z4_CONSTRAINT_MODE"] = True
        rov.setdefault("Z4_TOLERANCE_VEH_S", 300.0)
    exp = "%s_%s_d%.2f_seed%d" % (arm["name"], job["phase"],
                                  job["scalar"], job["seed"])
    cmd = [sys.executable, "-u", os.path.join(HERE, "run_sumo_hpc.py"),
           "--corridor", _ARGS.corridor,
           "--scenario", _ARGS.scenario,
           "--strategy", arm["name"],
           "--experiment", exp,
           "--seed", str(job["seed"]),
           "--demand-scalar", str(job["scalar"]),
           "--end", str(_ARGS.end),
           "--controller", sandbox]
    for k, v in rov.items():
        cmd += ["--set", "%s=%r" % (k, v)]

    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    wall = time.time() - t0
    row = {"corridor": _ARGS.corridor, "arm": arm["name"],
           "strategy": arm["strategy"], "seed": job["seed"],
           "phase": job["phase"], "demand_scalar": job["scalar"],
           "ok": r.returncode == 0, "wall_s": round(wall, 1)}
    row.update(kpis_from_summary(sandbox))
    obj = row.get("obj_pax_per_delay_hr", "-")
    print("[SWEEP] %-18s seed=%-5s %-5s d=%.2f -> %s obj=%s (%.0fs)"
          % (arm["name"], job["seed"], job["phase"], job["scalar"],
             "ok" if row["ok"] else "FAIL", obj, wall))
    if not row["ok"]:
        tail = (r.stderr or "").strip().splitlines()[-3:]
        for ln in tail:
            print("    | %s" % ln[-160:])
    return row


def _init_worker(args, tpl):
    global _ARGS, _SANDBOX_TPL
    _ARGS = args
    _SANDBOX_TPL = tpl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corridor", required=True, choices=["kg", "logan_road_new"])
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--arms", default=None, help="comma list of arm names")
    ap.add_argument("--seeds", default=",".join(str(s) for s in EVAL_SEEDS))
    ap.add_argument("--demand", default="1.0", help="comma list of scalars")
    ap.add_argument("--end", type=float, default=4500.0)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--skip-train", action="store_true",
                    help="drop learner train-phase runs (eval only)")
    ap.add_argument("--out", default=None, help="results CSV path")
    args = ap.parse_args()
    if not args.scenario:
        args.scenario = "%s_scenario" % args.corridor
    args.seeds = [int(x) for x in str(args.seeds).split(",")]

    jobs = build_jobs(args)
    out_csv = args.out or "sweep_%s.csv" % args.corridor
    if not os.path.isabs(out_csv):
        out_csv = os.path.join(HERE, out_csv)
    tpl = os.path.join(HERE, "_sandbox_" + args.corridor)
    print("[SWEEP] %d runs -> %s" % (len(jobs), out_csv))

    rows = []
    with Pool(processes=args.jobs, initializer=_init_worker,
              initargs=(args, tpl)) as pool:
        for i, row in enumerate(pool.imap_unordered(_run_job, jobs)):
            rows.append(row)
            with open(out_csv, "w", newline="", encoding="utf-8") as f:
                wtr = csv.DictWriter(f, fieldnames=CSV_FIELDS,
                                     extrasaction="ignore")
                wtr.writeheader()
                for rr in rows:
                    wtr.writerow(rr)
            print("[SWEEP] progress %d/%d" % (i + 1, len(jobs)))
    print("[SWEEP] done -> %s" % out_csv)


if __name__ == "__main__":
    main()
