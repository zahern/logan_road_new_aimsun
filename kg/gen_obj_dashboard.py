"""
gen_obj_dashboard.py — HTML dashboard: 5 mathematical-program objectives + KPIs.

Reads batch_results.csv (written by batch_runner.py after each run).
Run standalone after a batch completes, or call from batch_runner.py.

5 objectives (consistent with BARGAIN reward decomposition):
  Z1  Passenger delay     – weighted pax·s (lower = better)
  Z2  Flow bandwidth      – green-window alignment in seconds (higher = better)
  Z3  Bus lateness        – sigma^+ cumulative lateness in pax·s (lower = better)
  Z4  Total travel time   – veh·h (lower = better; also a throughput proxy)
  Z5  Bandwidth flow      – natural-green window·s (higher = better)

Demand-starvation warning: if Z1/Z4 improve but PaxEquivPassages drops vs NO_TSP,
the strategy may be reducing delay by serving fewer vehicles, not by moving them
faster.  The dashboard flags this with a red cell.
"""
import csv, os
from datetime import datetime

CSV_IN   = 'batch_results.csv'
HTML_OUT = 'objective_dashboard.html'

# Wait for batch_results.csv to be created (batch_runner may still be writing)
rows = []
max_wait_s = 60  # max 60 seconds to wait
import time
for attempt in range(max_wait_s):
    if os.path.isfile(CSV_IN):
        break
    if attempt == 0:
        print(f'{CSV_IN} not found — waiting for batch_runner to finish...')
    if attempt > 0 and attempt % 10 == 0:
        print(f'  Still waiting... ({attempt}s elapsed)')
    time.sleep(1)
else:
    print(f'{CSV_IN} not found after {max_wait_s}s — batch may have encountered an error or is still running.')
    import sys; sys.exit(0)

with open(CSV_IN, 'r', encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

def fv(r, k, default=0.0):
    try: return float(r.get(k, '') or default)
    except: return default

data = []
for r in rows:
    exp = r.get('run_experiment', '?')
    # Z1: prefer wobj_Z1_total; fall back to SimTotalDelay (stable Aimsun network stat)
    _z1 = fv(r, 'wobj_Z1_total') or fv(r, 'stats_SimTotalDelay_pax_s')
    # Z2: prefer wobj_Z2_total; if 0 fall back to natural-green bandwidth estimate
    _z2 = fv(r, 'wobj_Z2_total')
    if _z2 == 0.0:
        _dets = fv(r, 'stats_TSP_Detections'); _natg = fv(r, 'stats_TSP_NaturalGreen')
        if _dets > 0:
            _rate = _natg / _dets
            _z2 = _dets * (_rate * 12.0 + (1.0 - _rate) * 3.0)
    # Z3: prefer wobj_Z3_total; fall back to SimBusDelay (bus pax·s proxy for lateness)
    _z3 = fv(r, 'wobj_Z3_total') or fv(r, 'stats_SimBusDelay_pax_s')
    # Z4: prefer wobj_Z4_total; fall back to sum of TT stats
    _z4 = fv(r, 'wobj_Z4_total') or (fv(r, 'stats_Net_TotalTT_h_Car')
                                      + fv(r, 'stats_Net_TotalTT_h_Bus')
                                      + fv(r, 'stats_Net_TotalTT_h_Truck'))
    # Z5: bandwidth flow = natural-green count × avg green window (s) — higher better
    _dets5 = fv(r, 'stats_TSP_Detections'); _natg5 = fv(r, 'stats_TSP_NaturalGreen')
    _z5_bw = 0.0
    if _dets5 > 0:
        _rate5 = _natg5 / _dets5
        _z5_bw = _dets5 * (_rate5 * 12.0 + (1.0 - _rate5) * 3.0)
    data.append({
        'exp': exp,
        # 5 objectives
        'z1':  _z1,   # pax·s total delay — lower better
        'z2':  _z2,   # bandwidth alignment s — higher better
        'z3':  _z3,   # bus lateness pax·s — lower better
        'z4':  _z4,   # total travel time veh·h — lower better
        'z5':  _z5_bw,# bandwidth flow (natural-green window s) — higher better
        'obj': fv(r, 'wobj_objective_total'),
        # KPI columns
        'td':  fv(r, 'stats_TotalPassDelay_hrs'),
        'ad':  fv(r, 'stats_AvgPassDelay_s'),
        'pax': fv(r, 'stats_PaxEquivPassages'),    # throughput proxy
        'bt':  fv(r, 'stats_Net_TotalTT_h_Bus'),
        'ct':  fv(r, 'stats_Net_TotalTT_h_Car'),
        'nb':  fv(r, 'stats_N_DistinctBuses'),
        'nc':  fv(r, 'stats_N_DistinctCars'),
        'sd':  fv(r, 'stats_SidePassDelay_hrs'),
        'natg': _natg5, 'dets': _dets5,
    })

# ── Baseline throughput (NO_TSP row, first seed) for starvation detection ─────
_no_tsp_pax = next((d['pax'] for d in data if 'NO_TSP' in d['exp']), None)

def bar(v, mx, color='#2F5496', reverse=False):
    """Horizontal bar; reverse=True means lower value is better (bar from right)."""
    if mx <= 0: return ''
    pct = max(0, min(abs(v) / mx * 100, 100))
    if reverse:
        pct = 100 - pct  # invert so green = low = long bar
    return (f'<span style="display:inline-block;background:{color};'
            f'width:{pct:.0f}px;height:10px;margin-left:4px;vertical-align:middle"></span>')

def starvation_flag(d):
    """Red cell if pax served is >3% below NO_TSP baseline."""
    if _no_tsp_pax and _no_tsp_pax > 0 and d['pax'] < _no_tsp_pax * 0.97:
        drop_pct = 100 * (1 - d['pax'] / _no_tsp_pax)
        tip = f"Demand starvation: {drop_pct:.1f}% fewer passengers served than NO_TSP"
        pax_str = f"{d['pax']:,.0f}"
        return f'<td style="background:#FFD0D0;font-weight:bold" title="{tip}">⚠ {pax_str}</td>'
    pax_str = f"{d['pax']:,.0f}"
    return f'<td>{pax_str}</td>'

maxes = {k: max((abs(d[k]) for d in data), default=1) or 1
         for k in ['z1','z2','z3','z4','z5','obj','td','ad','bt','ct','sd']}

# ── Static summary: Z1–Z5 ranked ─────────────────────────────────────────────
_no_tsp_row = next((d for d in data if 'NO_TSP' in d['exp']), None)

def _delta_pct(val, base, lower_better=True):
    if not base: return ''
    pct = (val - base) / abs(base) * 100
    if lower_better:
        sym, cls = ('▼', 'good') if pct < -0.5 else (('▲', 'bad') if pct > 0.5 else ('≈', ''))
    else:
        sym, cls = ('▲', 'good') if pct > 0.5 else (('▼', 'bad') if pct < -0.5 else ('≈', ''))
    return f'<span class="{cls}">{sym}{abs(pct):.1f}%</span>' if cls else '<span>≈</span>'

def _rank_bg(values, idx, lower_better=True):
    n = len(values)
    if n <= 1: return ''
    ranked = sorted(range(n), key=lambda i: values[i], reverse=not lower_better)
    rank = ranked.index(idx)
    if rank == 0: return 'background:#D4EDDA'
    if rank == n - 1: return 'background:#FFD0D0'
    return ''

_z1v = [d['z1'] for d in data]
_z2v = [d['z2'] for d in data]
_z3v = [d['z3'] for d in data]
_z4v = [d['z4'] for d in data]
_z5v = [d['z5'] for d in data]

summary_rows = ''
for i, d in enumerate(data):
    b = _no_tsp_row
    summary_rows += f'''<tr>
<td><b>{d['exp']}</b></td>
<td style="{_rank_bg(_z1v,i,True)}">{d['z1']/1e6:,.2f}M &nbsp;{_delta_pct(d['z1'],b['z1'],True) if b else ''}</td>
<td style="{_rank_bg(_z2v,i,False)}">{d['z2']:,.0f} &nbsp;{_delta_pct(d['z2'],b['z2'],False) if b else ''}</td>
<td style="{_rank_bg(_z3v,i,True)}">{d['z3']/1e6:,.2f}M &nbsp;{_delta_pct(d['z3'],b['z3'],True) if b else ''}</td>
<td style="{_rank_bg(_z4v,i,True)}">{d['z4']:,.1f} &nbsp;{_delta_pct(d['z4'],b['z4'],True) if b else ''}</td>
<td style="{_rank_bg(_z5v,i,False)}">{d['z5']:,.0f} &nbsp;{_delta_pct(d['z5'],b['z5'],False) if b else ''}</td>
</tr>'''

rows_html = ''
for d in data:
    rows_html += f'''<tr>
<td>{d['exp']}</td>
<td>{d['z1']/1e6:,.2f}M {bar(d['z1'],maxes['z1'],'#C00000')}</td>
<td>{d['z2']:,.0f} {bar(d['z2'],maxes['z2'],'#00873E')}</td>
<td>{d['z3']/1e6:,.2f}M {bar(d['z3'],maxes['z3'],'#FF7F0E')}</td>
<td>{d['z4']:,.1f} {bar(d['z4'],maxes['z4'],'#8B0000')}</td>
<td>{d['z5']:,.0f} {bar(d['z5'],maxes['z5'],'#1F77B4')}</td>
<td>{d['obj']/1e6:,.3f}M</td>
<td class="sep">{d['td']:,.1f} {bar(d['td'],maxes['td'],'#D62728')}</td>
<td>{d['ad']:,.1f} {bar(d['ad'],maxes['ad'],'#E74C3C')}</td>
{starvation_flag(d)}
<td>{d['bt']:,.1f}</td>
<td>{d['ct']:,.1f}</td>
<td>{d['sd']:,.1f}</td>
</tr>'''

legend = '''
<div class="legend">
  <b>Objective direction:</b>
  Z1 Pax Delay — <span class="bad">lower is better ↓</span> |
  Z2 Bandwidth — <span class="good">higher is better ↑</span> |
  Z3 Bus Lateness — <span class="bad">lower is better ↓</span> |
  Z4 Travel Time — <span class="bad">lower is better ↓</span> |
  Z5 BW Flow (natural-green window·s) — <span class="good">higher is better ↑</span><br>
  <b>Demand starvation:</b> ⚠ red PaxEquiv cell = strategy serves &gt;3%
  fewer passengers than NO_TSP baseline — delay may be artificially low.
</div>'''

html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>5-Objective Dashboard</title>
<style>
body{{font-family:Segoe UI,sans-serif;margin:15px;background:#f5f5f5}}
h1{{color:#2F5496;font-size:18px}}
h2{{color:#444;font-size:13px;margin-top:18px;border-bottom:1px solid #ccc;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;background:white;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
th{{background:#2F5496;color:white;padding:6px 8px;text-align:left;font-size:10px;white-space:nowrap}}
th.good{{background:#00873E}}
th.bad{{background:#A00000}}
th.bw{{background:#1F5F8B}}
th.sep{{border-left:2px solid #94B4D6}}
td{{padding:4px 8px;font-size:10px;border-bottom:1px solid #eee;white-space:nowrap}}
td.sep{{border-left:2px solid #94B4D6}}
tr:hover{{background:#f0f4ff}}
.legend{{margin-top:12px;color:#555;font-size:9.5px;background:white;padding:8px;border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
.good{{color:#00873E;font-weight:bold}}
.bad{{color:#A00000;font-weight:bold}}
</style></head><body>
<h1>5-Objective + KPI Dashboard — {datetime.now().strftime('%Y-%m-%d %H:%M')}</h1>

<h2>Summary — Z1 / Z2 / Z3 / Z4 / Z5 at a glance &nbsp;<small style="font-weight:normal;color:#555">(green = best, red = worst; Δ% vs NO_TSP baseline)</small></h2>
<table>
<tr>
  <th>Experiment</th>
  <th class="bad">Z1 &nbsp;Pax Delay ↓<br><small>(pax·s)</small></th>
  <th class="good">Z2 &nbsp;Bandwidth ↑<br><small>(s)</small></th>
  <th class="bad">Z3 &nbsp;Bus Lateness ↓<br><small>(pax·s)</small></th>
  <th class="bad">Z4 &nbsp;Travel Time ↓<br><small>(veh·h)</small></th>
  <th class="bw">Z5 &nbsp;BW Flow ↑<br><small>(window·s)</small></th>
</tr>
{summary_rows}
</table>

<h2>Section 1 — Mathematical-program objectives (BARGAIN decomposition)</h2>
<table>
<tr>
  <th>Experiment</th>
  <th class="bad">Z1 Pax Delay<br>(pax·s) ↓</th>
  <th class="good">Z2 Bandwidth<br>(s) ↑</th>
  <th class="bad">Z3 Bus Lateness<br>(pax·s) ↓</th>
  <th class="bad">Z4 Travel Time<br>(veh·h) ↓</th>
  <th class="bw">Z5 BW Flow<br>(window·s) ↑</th>
  <th>Composite<br>Objective</th>
  <th class="sep bad">Total Pax<br>Delay (h) ↓</th>
  <th class="bad">Avg Pax<br>Delay (s) ↓</th>
  <th>Pax Equiv<br>Passages</th>
  <th>Bus TT<br>(h)</th>
  <th>Car TT<br>(h)</th>
  <th>Side Pax<br>Delay (h)</th>
</tr>
{rows_html}
</table>
{legend}
<div class="legend" style="margin-top:6px">
  <b>{len(data)} experiment rows</b> | Generated from {CSV_IN} |
  Z1/Z2/Z3 accumulated by <code>_accumulate_weighted_objective()</code> in
  <code>intersection_controller.py</code> |
  Z4 = Net_TotalTT_h_Car + Bus + Truck (post-hoc from Aimsun stats) |
  Z5 = natural-green count × avg green-window s (TSP_Detections / TSP_NaturalGreen stats)
</div>
</body></html>'''

with open(HTML_OUT, 'w', encoding='utf-8') as f:
    f.write(html)
print(f'Dashboard written: {HTML_OUT}  ({len(data)} experiments)')
