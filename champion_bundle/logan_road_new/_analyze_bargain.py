import csv, glob, os, statistics, collections

# ── Find latest BARGAIN run results ──────────────────────────────────────────
rc_files = sorted(glob.glob('logs/reward_cycle_DCTSP_BARGAIN_SPM_*.csv'), key=os.path.getmtime)
print(f"reward_cycle files: {[os.path.basename(f) for f in rc_files]}")
if not rc_files:
    print("No BARGAIN reward_cycle files found"); raise SystemExit

fn = rc_files[-1]
print(f"\nAnalysing: {fn}\n")
all_rows = list(csv.DictReader(open(fn, newline='', encoding='utf-8')))
chosen   = [r for r in all_rows if r.get('is_chosen','0') == '1']
print(f"Total rows: {len(all_rows)}  Chosen rows: {len(chosen)}")

# ── Action distribution ───────────────────────────────────────────────────────
acts = collections.Counter(r['action'] for r in chosen)
print("\nChosen action distribution:")
for a, n in sorted(acts.items()):
    print(f"  {a:<20s}  n={n}")

# ── Reward delta stats ────────────────────────────────────────────────────────
def fv(r, k):
    return float(r.get(k) or 0)

deltas = [fv(r,'reward_delta') for r in chosen]
if deltas:
    print(f"\nreward_delta: mean={statistics.mean(deltas):.3f}  "
          f"median={statistics.median(deltas):.3f}  "
          f"neg_frac={sum(d<0 for d in deltas)/len(deltas)*100:.1f}%")

# ── Per-action reward_delta stats ─────────────────────────────────────────────
print("\nPer-action reward_delta stats:")
by = collections.defaultdict(list)
for r in chosen:
    by[r['action']].append(fv(r,'reward_delta'))
for a, v in sorted(by.items()):
    mn = statistics.mean(v)
    neg = sum(x < 0 for x in v)
    print(f"  {a:<20s}  n={len(v):3d}  mean={mn:+.3f}  neg={neg}")

# ── Gating check: how many detections hit BG_MIN gates ───────────────────────
print("\nBargain-gated events (BARGAIN_GATED or overridden to NO_ACTION):")
gated = [r for r in all_rows if 'BARGAIN_GATE' in r.get('action','').upper()
         or r.get('bargain_gated','0') == '1']
print(f"  Explicit gated rows: {len(gated)}")

# ── no_act_delay distribution for NO_ACTION chosen (what was skipped) ────────
na_chosen = [r for r in chosen if r['action'] == 'NO_ACTION']
na_delays = [fv(r,'no_act_delay_s') for r in na_chosen]
if na_delays:
    pct_high = sum(d >= 20 for d in na_delays)
    print(f"\nNO_ACTION chosen: n={len(na_delays)}  "
          f"mean_delay={statistics.mean(na_delays):.1f}s  "
          f"n_delay>=20s={pct_high}")

# ── Bus saved per chosen non-NO_ACTION ───────────────────────────────────────
active = [r for r in chosen if r['action'] not in ('NO_ACTION',)]
bps = [fv(r,'bus_saved_pax_s') for r in active]
if bps:
    print(f"\nActive actions bus_saved_pax_s: mean={statistics.mean(bps):.0f}  "
          f"zeros={sum(b==0 for b in bps)}/{len(bps)}")

# ── Per-junction chosen action summary ───────────────────────────────────────
print("\nPer-junction chosen action breakdown:")
for jid in sorted(set(r['junction_id'] for r in chosen)):
    jrows = [r for r in chosen if r['junction_id'] == jid]
    jacts = collections.Counter(r['action'] for r in jrows)
    delays = [fv(r,'no_act_delay_s') for r in jrows if fv(r,'no_act_delay_s') > 0]
    mean_d = statistics.mean(delays) if delays else 0.0
    print(f"  jct={jid:<8s}  n={len(jrows):3d}  "
          f"mean_delay={mean_d:.1f}s  "
          f"acts={dict(jacts)}")

# ── Compare with per-intersection CSV ────────────────────────────────────────
print("\n--- Per-intersection results comparison ---")
print(f"{'Experiment':<42s}  {'AvgBusDelay':>12s}  {'Ext':>4s}  {'Ins':>4s}  {'Obj':>8s}")
for folder in sorted(glob.glob('results/*seed*'), key=os.path.getmtime):
    fn2 = os.path.join(folder, 'simulation_results_per_intersection.csv')
    if not os.path.isfile(fn2): continue
    rows2 = list(csv.DictReader(open(fn2)))
    tot_bus = sum(float(r.get('BusTotalTT_hrs') or 0) for r in rows2)
    tot_ext = sum(int(r.get('TSP_Extensions') or 0) for r in rows2)
    tot_ins = sum(int(r.get('TSP_Insertions') or 0) for r in rows2)
    bd = [float(r.get('AvgBusPassDelay_s') or 0) for r in rows2 if float(r.get('BusVehPassages') or 0) > 0]
    avg_bd  = statistics.mean(bd) if bd else 0
    obj_vals= [float(r.get('Objective_PaxPerDelayHr') or 0) for r in rows2 if float(r.get('Objective_PaxPerDelayHr') or 0)>0]
    avg_obj = statistics.mean(obj_vals) if obj_vals else 0
    exp = folder.split(os.sep)[-1][:40]
    print(f"  {exp:<42s}  {avg_bd:12.1f}  {tot_ext:4d}  {tot_ins:4d}  {avg_obj:8.3f}")
