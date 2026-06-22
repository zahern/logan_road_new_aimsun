import csv, glob, statistics
from collections import Counter, defaultdict

f = sorted(glob.glob('logs/reward_cycle_DCTSP_BARGAIN*.csv'), key=lambda x: __import__('os').path.getmtime(x))[-1]
print('File:', f)
rows = list(csv.DictReader(open(f)))
fv = lambda r, k, d=0.0: float(r.get(k, '') or d) if r.get(k, '') not in ('', 'None') else d

# ── 1. ER_BP deep dive ────────────────────────────────────────────────────────
print('\n=== ER_BP_10 breakdown ===')
erbp = [r for r in rows if r['action'] == 'ER_BP_10']
print(f'Total ER_BP_10 rows: {len(erbp)}')

weird = [r for r in erbp if fv(r, 'bus_saved_pax_s') < -100]
print(f'Rows with bus_saved < -100: {len(weird)}')
for r in weird[:6]:
    print(f"  jct={r['junction_id']}  saved={fv(r,'bus_saved_pax_s'):.0f}  car={fv(r,'other_inc_pax_s'):.0f}"
          f"  delay={fv(r,'no_act_delay_s'):.1f}  bp_dur={fv(r,'bp_dur_s'):.1f}"
          f"  eta={fv(r,'bus_eta_s'):.1f}  phase={r.get('current_phase','?')}")

zero_rows = [r for r in erbp if fv(r, 'bus_saved_pax_s') == 0.0]
print(f'Rows with bus_saved == 0: {len(zero_rows)}')
for r in zero_rows[:4]:
    print(f"  jct={r['junction_id']}  delay={fv(r,'no_act_delay_s'):.1f}  car={fv(r,'other_inc_pax_s'):.0f}"
          f"  eta={fv(r,'bus_eta_s'):.1f}  rwd={fv(r,'reward'):.3f}  phase={r.get('current_phase','?')}")

# ── 2. GE current_phase analysis ──────────────────────────────────────────────
print('\n=== GE_5: current_phase breakdown ===')
ge5 = [r for r in rows if r['action'] == 'GE_5']
phase_count = Counter(r.get('current_phase', '?') for r in ge5)
print('Phase distribution:', dict(phase_count))
# For each junction, show whether bus_phase is ever caught
print('\nGE_5 per-junction: n_evaluations  n_right_phase (saved>0)  n_wrong_phase (saved=-200)')
jcts = sorted(set(r['junction_id'] for r in ge5))
for j in jcts:
    jge = [r for r in ge5 if r['junction_id'] == j]
    right = [r for r in jge if fv(r, 'bus_saved_pax_s') > 0]
    wrong = [r for r in jge if fv(r, 'bus_saved_pax_s') < 0]
    zero  = [r for r in jge if fv(r, 'bus_saved_pax_s') == 0]
    phases = Counter(r.get('current_phase','?') for r in jge)
    print(f"  jct={j}  n={len(jge)}  right={len(right)}  wrong={len(wrong)}  zero={len(zero)}  phases={dict(phases)}")

# ── 3. No-action delay vs no-TSP comparison ──────────────────────────────────
print('\n=== Delay distribution (chosen NO_ACTION rows) ===')
na_rows = [r for r in rows if r.get('is_chosen','0')=='1' and r['action']=='NO_ACTION']
na_delays = [fv(r,'no_act_delay_s') for r in na_rows if fv(r,'no_act_delay_s') > 0]
active_rows = [r for r in rows if r.get('is_chosen','0')=='1' and r['action']!='NO_ACTION']
act_delays = [fv(r,'no_act_delay_s') for r in active_rows if fv(r,'no_act_delay_s') > 0]
if na_delays:
    print(f'NO_ACTION situations: n={len(na_delays)}  mean={statistics.mean(na_delays):.1f}s'
          f'  median={statistics.median(na_delays):.1f}s  max={max(na_delays):.1f}s')
if act_delays:
    print(f'Active-action situations: n={len(act_delays)}  mean={statistics.mean(act_delays):.1f}s'
          f'  median={statistics.median(act_delays):.1f}s  max={max(act_delays):.1f}s')

# check no_strategy_delay_pax_s vs strategy_min_delay_pax_s
print('\n=== no_strategy vs strategy delay (all chosen) ===')
chosen = [r for r in rows if r.get('is_chosen','0')=='1']
ns_vals = [fv(r,'no_strategy_delay_pax_s') for r in chosen if fv(r,'no_strategy_delay_pax_s') > 0]
s_vals  = [fv(r,'strategy_min_delay_pax_s') for r in chosen if fv(r,'strategy_min_delay_pax_s') > 0]
if ns_vals:
    print(f'no_strategy_delay  n={len(ns_vals)}  mean={statistics.mean(ns_vals):.1f}')
if s_vals:
    print(f'strategy_min_delay n={len(s_vals)}  mean={statistics.mean(s_vals):.1f}')
