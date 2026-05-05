"""
Master Pipeline Orchestrator
==============================
Run from synth_pop/ directory.  Chains every stage in order; copies output files
between stages automatically.

  Stage 0 — fuse census tables  (Population_Synth)
  Stage 1 — train DATGAN + generate synthetic microdata  (Population_Synth)
  Stage 2 — validate GAN output  (synth_pop/gan_validation.py)
  Stage 3 — greedy household assignment + SA refinement  (Household_Match)
  Stage 4 — household consistency repair  (Household_Match)
  Stage 5 — SA population fitting — SA-GAN  (sa_run_again_n)
  Stage 6 — SA-Only baseline  (synth_pop/sa_only_baseline.py)
  Stage 7 — RSSZ outlier analysis  (synth_pop/rssz_outlier_analysis.py)

Usage:
    python run_pipeline.py [--skip 0 1 ...] [--zones 301011001 ...] [--sa-iter 1000]

All paths are read from config.py.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

# Ensure config is importable from same directory
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd, cwd, label):
    print(f"\n{'='*60}\n  {label}\n  cwd : {cwd}\n  cmd : {' '.join(str(c) for c in cmd)}\n{'='*60}")
    t0 = time.time()
    ret = subprocess.run(cmd, cwd=cwd)
    elapsed = time.time() - t0
    if ret.returncode != 0:
        print(f"[ERROR] {label} exited with code {ret.returncode}")
        sys.exit(ret.returncode)
    print(f"[OK] {label}  ({elapsed:.1f}s)")
    return elapsed


def cp(src, dst_dir, dst_name=None):
    """Copy a file into dst_dir, optionally renaming it."""
    if not os.path.exists(src):
        print(f"[WARN] copy source missing: {src}")
        return False
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, dst_name or os.path.basename(src))
    shutil.copy2(src, dst)
    print(f"  copied  {src}\n       → {dst}")
    return True


def check(path, label):
    ok = os.path.exists(path)
    print(f"  {'[OK]' if ok else '[MISSING]'}  {label}: {path}")
    return ok


# ---------------------------------------------------------------------------
# Stage functions
# ---------------------------------------------------------------------------

def stage_fuse(args):
    run([sys.executable, "step_0 fuse_to_one.py"], config.POP_SYNTH_DIR, "Stage 0 — fuse census tables")
    check(config.LINKED_DATA, "LINKED_DATA_dropped.csv")


def stage_gan(args):
    script = os.path.join(config.POP_SYNTH_DIR, "step1_dag_main_micro-arg.py")
    if not os.path.exists(script):
        script = os.path.join(config.POP_SYNTH_DIR, "step1_dag_main_micro.py")
    cmd = [
        sys.executable, script,
        "--epoch-size",        str(config.GAN_EPOCHS),
        "--batch-size",        str(config.GAN_BATCH_SIZE),
        "--sample-multiplier", str(config.GAN_SAMPLE_MULT),
        "--data_source_name",  config.GAN_DATA_SOURCE,
    ]
    run(cmd, config.POP_SYNTH_DIR, "Stage 1 — train DATGAN & generate synthetic microdata")
    check(config.DATGAN_OUTPUT, "DATGAN.csv")


def stage_gan_validation(args):
    run([sys.executable, os.path.join(HERE, "gan_validation.py")], HERE,
        "Stage 2 — GAN validation (distributions + repair rate)")
    check(os.path.join(config.GAN_VALIDATION_DIR, "validation_summary.csv"), "validation_summary.csv")


def stage_hh_match(args):
    cp(config.DATGAN_OUTPUT, config.HH_MATCH_DIR, dst_name="DATGAN_samples.csv")
    run([sys.executable, "houehold_family_match_c.py"], config.HH_MATCH_DIR,
        "Stage 3 — greedy household assignment + SA refinement")
    check(os.path.join(config.HH_MATCH_DIR, "hhid_fid.csv"), "hhid_fid.csv")


def stage_hh_repair(args):
    run([sys.executable, "household_repairs_e.py"], config.HH_MATCH_DIR,
        "Stage 4 — household consistency repair")
    check(config.HH_MATCH_OUTPUT, "cleaned_dataset_hhid.csv")


def stage_sa_gan(args):
    cp(config.HH_MATCH_OUTPUT, config.SA_DIR, dst_name="cleaned_dataset_hhid.csv")
    zone_args = (["--zones"] + args.zones) if args.zones else []
    run([sys.executable, "sa_multi.py"] + zone_args + ["--max-iter", str(args.sa_iter)],
        config.SA_DIR, "Stage 5 — SA-GAN population fitting")


def stage_sa_only(args):
    zone_args = (["--zones"] + args.zones) if args.zones else []
    run([sys.executable, os.path.join(HERE, "sa_only_baseline.py")] + zone_args
        + ["--max-iter", str(args.sa_iter)], HERE,
        "Stage 6 — SA-Only baseline (Reviewer 2, P31)")
    check(os.path.join(config.SA_ONLY_RESULTS_DIR, "sa_only_rssz_summary.csv"), "sa_only_rssz_summary.csv")


def stage_outlier(args):
    run([sys.executable, os.path.join(HERE, "rssz_outlier_analysis.py")], HERE,
        "Stage 7 — RSSZ outlier analysis (Reviewer 2, Table 2)")
    check(os.path.join(config.RSSZ_OUTLIER_DIR, "rssz_distribution.png"), "rssz_distribution.png")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

STAGES = [
    (0, "fuse",         "Stage 0 — Fuse census tables",               stage_fuse),
    (1, "gan",          "Stage 1 — Train GAN",                        stage_gan),
    (2, "gan-val",      "Stage 2 — GAN validation",                   stage_gan_validation),
    (3, "hh-match",     "Stage 3 — Household match",                  stage_hh_match),
    (4, "hh-repair",    "Stage 4 — Household repair",                 stage_hh_repair),
    (5, "sa-gan",       "Stage 5 — SA-GAN fitting",                   stage_sa_gan),
    (6, "sa-only",      "Stage 6 — SA-Only baseline",                 stage_sa_only),
    (7, "outlier",      "Stage 7 — RSSZ outlier analysis",            stage_outlier),
]


def main():
    p = argparse.ArgumentParser(description="Run the full synthetic population pipeline")
    p.add_argument("--skip",     nargs="*", type=int, default=[], metavar="N",
                   help="Stage numbers to skip")
    p.add_argument("--only",     nargs="*", type=int, default=[], metavar="N",
                   help="Run only these stage numbers (overrides --skip)")
    p.add_argument("--zones",    nargs="*", type=str, help="SA2 zone IDs")
    p.add_argument("--sa-iter",  type=int, default=config.SA_MAX_ITER)
    args = p.parse_args()

    timings = {}
    for num, key, label, fn in STAGES:
        if args.only and num not in args.only:
            continue
        if num in args.skip:
            print(f"\n[SKIP] Stage {num}: {label}")
            continue
        t0 = time.time()
        fn(args)
        timings[label] = round(time.time() - t0, 1)

    print("\n" + "=" * 60)
    print("Pipeline complete. Timings:")
    for lbl, t in timings.items():
        print(f"  {lbl}: {t}s")
    print("\nOpen synth_pop/pipeline_results.ipynb to review all outputs.")


if __name__ == "__main__":
    main()
