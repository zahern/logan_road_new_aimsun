"""
Build an HTML diagnostics page showing why HARMONY chose:
- Green extension (GE)
- Phase insertion (INS)
- Or no action

Usage:
  python plot_tsp_objective_trace.py
  python plot_tsp_objective_trace.py logs/objective_trace_*.csv tsp_objective_trace.html

If objective_trace CSV is unavailable, falls back to detection_points CSV and
parses harmony-* tiers + prearm_note payloads.
"""

import os
import re
import csv
import glob
import json
import sys
import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Match project behavior: inject shared venv for optional plotly/pandas availability.
_venv_sp = os.path.normpath(
    os.path.join(SCRIPT_DIR, '..', 'logan_road_new', '.venv', 'Lib', 'site-packages')
)
if os.path.isdir(_venv_sp) and _venv_sp not in sys.path:
    sys.path.insert(1, _venv_sp)

def _f(v, d=None):
    try:
        return float(v)
    except Exception:
        return d


def _i(v, d=None):
    try:
        return int(float(v))
    except Exception:
        return d


def _latest(glob_pat):
    items = glob.glob(glob_pat)
    if not items:
        return None
    return max(items, key=os.path.getmtime)


def _parse_note_payload(note):
    out = {}
    if not note:
        return out
    for part in [p.strip() for p in str(note).split('|')]:
        if '=' not in part:
            continue
        k, v = part.split('=', 1)
        out[k.strip()] = v.strip()
    return out


def _load_objective_csv(path):
    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            rows.append({
                't': _f(r.get('sim_time_s'), 0.0),
                'junction_id': _i(r.get('junction_id'), -1),
                'veh_id': _i(r.get('veh_id'), -1),
                'mode': (r.get('mode') or '').strip(),
                'decision': (r.get('decision') or '').strip(),
                'reason': (r.get('reason') or '').strip(),
                'bus_eta_s': _f(r.get('bus_eta_s')),
                'time_to_bp_s': _f(r.get('time_to_bp_s')),
                'natural_end_s': _f(r.get('natural_end_s')),
                'next_red_s': _f(r.get('next_red_s')),
                'ge_lb_s': _f(r.get('ge_lb_s')),
                'ge_ub_s': _f(r.get('ge_ub_s')),
                'opt_ge_s': _f(r.get('opt_ge_s')),
                'bp_lb_s': _f(r.get('bp_lb_s')),
                'bp_ub_s': _f(r.get('bp_ub_s')),
                'opt_bp_s': _f(r.get('opt_bp_s')),
                'note': (r.get('note') or '').strip(),
            })
    return rows


def _from_detection_csv(path):
    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            tier = (r.get('tier') or '').strip()
            if tier not in (
                'harmony-no-ge-local', 'harmony-ge-local',
                'harmony-no-ins-local', 'harmony-ins-local',
            ):
                continue
            note = (r.get('prearm_note') or '').strip()
            payload = _parse_note_payload(note)

            mode = 'GE' if '-ge-' in tier else 'INS'
            decision = 'ACTION' if tier in ('harmony-ge-local', 'harmony-ins-local') else 'SKIP'

            reason = 'from_detection_tier'
            if note.startswith('NO_GE'):
                reason = note.split('|', 1)[0].replace('NO_GE', '').strip() or 'NO_GE'
            elif note.startswith('NO_INS'):
                reason = note.split('|', 1)[0].replace('NO_INS', '').strip() or 'NO_INS'
            elif 'GE ' in note:
                reason = 'grant_extension'
            elif 'INS ' in note:
                reason = 'grant_insertion'

            rows.append({
                't': _f(r.get('sim_time_s'), 0.0),
                'junction_id': _i(r.get('junction_id'), -1),
                'veh_id': _i(r.get('veh_id'), -1),
                'mode': mode,
                'decision': decision,
                'reason': reason,
                'bus_eta_s': _f(payload.get('eta_s', r.get('prearm_eta_s'))),
                'time_to_bp_s': _f(payload.get('to_bp_s')),
                'natural_end_s': _f(payload.get('nat_end_s')),
                'next_red_s': None,
                'ge_lb_s': _f(payload.get('lb_s')),
                'ge_ub_s': _f(payload.get('ub_s')),
                'opt_ge_s': None,
                'bp_lb_s': _f(payload.get('lb_s')),
                'bp_ub_s': _f(payload.get('ub_s')),
                'opt_bp_s': _f(payload.get('opt_bp_s')),
                'note': note,
            })

    return rows


def _summary(rows):
    s = {
        'total': len(rows),
        'ge_action': 0,
        'ge_skip': 0,
        'ins_action': 0,
        'ins_skip': 0,
        'reasons': {},
    }
    for r in rows:
        k = (r.get('mode'), r.get('decision'))
        if k == ('GE', 'ACTION'):
            s['ge_action'] += 1
        elif k == ('GE', 'SKIP'):
            s['ge_skip'] += 1
        elif k == ('INS', 'ACTION'):
            s['ins_action'] += 1
        elif k == ('INS', 'SKIP'):
            s['ins_skip'] += 1
        rs = r.get('reason') or 'unknown'
        s['reasons'][rs] = s['reasons'].get(rs, 0) + 1
    return s


def _build_html(rows, src_path, out_path):
    rows = sorted(rows, key=lambda x: (x.get('t', 0.0), x.get('junction_id', -1)))
    stats = _summary(rows)
    rows_json = json.dumps(rows)
    reason_json = json.dumps(stats['reasons'])

    html = """<!DOCTYPE html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>TSP Objective Trace</title>
  <script src=\"https://cdn.plot.ly/plotly-2.32.0.min.js\"></script>
  <style>
    :root {{
      --bg: #f5f7fb;
      --panel: #ffffff;
      --ink: #102236;
      --muted: #5b6b7d;
      --line: #d8e1ea;
      --accent: #1f6feb;
      --ok: #1b8f3e;
      --warn: #d97706;
      --bad: #b42318;
    }}
    body {{ margin: 0; font-family: "Segoe UI", Tahoma, sans-serif; color: var(--ink); background: radial-gradient(circle at 10% 10%, #edf5ff 0%, var(--bg) 40%, #eef8f2 100%); }}
    .wrap {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; margin-bottom: 14px; box-shadow: 0 4px 18px rgba(16,34,54,0.05); }}
    h1 {{ margin: 0 0 8px 0; font-size: 26px; }}
    .muted {{ color: var(--muted); }}
    .kpis {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }}
    .kpi {{ border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; background: #fbfdff; }}
    .kpi .v {{ font-size: 22px; font-weight: 700; }}
    .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    #chartA, #chartB, #chartC {{ width: 100%; height: 430px; }}
    .formula {{ font-family: Consolas, monospace; background: #f8fafc; border: 1px solid var(--line); padding: 8px; border-radius: 8px; }}
    @media (max-width: 980px) {{
      .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .grid2 {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<div class=\"wrap\">
  <div class=\"panel\">
    <h1>TSP Objective Trace</h1>
        <div class=\"muted\">Source: __SRC__</div>
        <div class=\"muted\">Generated: __GENERATED__</div>
    <div class=\"kpis\" style=\"margin-top:10px\">
            <div class=\"kpi\"><div>Total decisions</div><div class=\"v\">__TOTAL__</div></div>
            <div class=\"kpi\"><div>GE actions</div><div class=\"v\" style=\"color:var(--ok)\">__GE_ACTION__</div></div>
            <div class=\"kpi\"><div>GE skips</div><div class=\"v\" style=\"color:var(--warn)\">__GE_SKIP__</div></div>
            <div class=\"kpi\"><div>INS actions</div><div class=\"v\" style=\"color:var(--ok)\">__INS_ACTION__</div></div>
            <div class=\"kpi\"><div>INS skips</div><div class=\"v\" style=\"color:var(--bad)\">__INS_SKIP__</div></div>
    </div>
  </div>

  <div class=\"panel\">
    <div><b>Decision logic being visualized</b></div>
    <div class=\"formula\" style=\"margin-top:6px\">GE trigger candidate if bus_eta_s &gt; next_red_s, optimize GE in [GE_lb, GE_ub]</div>
    <div class=\"formula\" style=\"margin-top:6px\">INS trigger candidate if bus_eta_s &gt; natural_end_s where natural_end_s = time_to_bp_s + BusPhaseDuration</div>
    <div class=\"formula\" style=\"margin-top:6px\">INS optimize BP in [BP_lb, BP_ub], then apply if objective returns viable BP</div>
  </div>

  <div class=\"panel\"><div id=\"chartA\"></div></div>
  <div class=\"grid2\">
    <div class=\"panel\"><div id=\"chartB\"></div></div>
    <div class=\"panel\"><div id=\"chartC\"></div></div>
  </div>
</div>
<script>
const rows = __ROWS_JSON__;
const reasons = __REASON_JSON__;

function pick(rows, mode, decision){ return rows.filter(r => r.mode===mode && r.decision===decision); }
function xs(rows){ return rows.map(r => r.t); }
function ys(rows, k){ return rows.map(r => (r[k]===null || r[k]==="" ? null : Number(r[k]))); }
function txt(rows){ return rows.map(r => `jct=${r.junction_id} bus=${r.veh_id} reason=${r.reason}`); }

const ge = rows.filter(r => r.mode === 'GE');
const ins = rows.filter(r => r.mode === 'INS');

Plotly.newPlot('chartA', [
  {{x: xs(rows), y: ys(rows,'bus_eta_s'), mode:'markers', name:'bus_eta_s', marker:{{size:6,color:'#1f6feb'}}, text: txt(rows), hovertemplate:'t=%{{x:.1f}}<br>eta=%{{y:.1f}}<br>%{{text}}<extra></extra>'}},
  {{x: xs(ins), y: ys(ins,'natural_end_s'), mode:'markers', name:'ins_natural_end_s', marker:{{size:6,color:'#d97706',symbol:'diamond'}}, text: txt(ins), hovertemplate:'t=%{{x:.1f}}<br>natural_end=%{{y:.1f}}<br>%{{text}}<extra></extra>'}},
  {{x: xs(ge), y: ys(ge,'next_red_s'), mode:'markers', name:'ge_next_red_s', marker:{{size:6,color:'#b42318',symbol:'x'}}, text: txt(ge), hovertemplate:'t=%{{x:.1f}}<br>next_red=%{{y:.1f}}<br>%{{text}}<extra></extra>'}}
], {{title:'Trigger Inputs Over Time', template:'plotly_white', xaxis:{{title:'simulation time (s)'}}, yaxis:{{title:'seconds from now'}}}});

Plotly.newPlot('chartB', [
  {{x: xs(ge), y: ys(ge,'ge_lb_s'), mode:'markers', name:'GE_lb_s', marker:{{size:6,color:'#8b5cf6'}}}},
  {{x: xs(ge), y: ys(ge,'ge_ub_s'), mode:'markers', name:'GE_ub_s', marker:{{size:6,color:'#14b8a6'}}}},
  {{x: xs(ge), y: ys(ge,'opt_ge_s'), mode:'markers', name:'opt_GE_s', marker:{{size:7,color:'#1b8f3e',symbol:'star'}}}}
], {{title:'GE Objective Window and Result', template:'plotly_white', xaxis:{{title:'simulation time (s)'}}, yaxis:{{title:'seconds'}}}});

Plotly.newPlot('chartC', [
  {{x: xs(ins), y: ys(ins,'bp_lb_s'), mode:'markers', name:'BP_lb_s', marker:{{size:6,color:'#8b5cf6'}}}},
  {{x: xs(ins), y: ys(ins,'bp_ub_s'), mode:'markers', name:'BP_ub_s', marker:{{size:6,color:'#14b8a6'}}}},
  {{x: xs(ins), y: ys(ins,'opt_bp_s'), mode:'markers', name:'opt_BP_s', marker:{{size:7,color:'#1b8f3e',symbol:'star'}}}}
], {{title:'INS Objective Window and Result', template:'plotly_white', xaxis:{{title:'simulation time (s)'}}, yaxis:{{title:'seconds'}}}});
</script>
</body>
</html>
"""
    html = html.replace("{{", "{").replace("}}", "}")
    html = (
        html
        .replace("__SRC__", str(src_path))
        .replace("__GENERATED__", datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        .replace("__TOTAL__", str(stats['total']))
        .replace("__GE_ACTION__", str(stats['ge_action']))
        .replace("__GE_SKIP__", str(stats['ge_skip']))
        .replace("__INS_ACTION__", str(stats['ins_action']))
        .replace("__INS_SKIP__", str(stats['ins_skip']))
        .replace("__ROWS_JSON__", rows_json)
        .replace("__REASON_JSON__", reason_json)
    )
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    log_dir = os.path.join(SCRIPT_DIR, 'logs')
    in_path = sys.argv[1] if len(sys.argv) > 1 else None
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SCRIPT_DIR, 'tsp_objective_trace.html')

    if not in_path:
        in_path = _latest(os.path.join(log_dir, 'objective_trace_*.csv'))

    rows = []
    src = None
    if in_path and os.path.isfile(in_path):
        try:
            rows = _load_objective_csv(in_path)
            src = in_path
        except Exception as e:
            print(f'[objective-trace] failed to parse objective CSV: {e}')
            rows = []

    if not rows:
        det = _latest(os.path.join(log_dir, 'detection_points_*.csv'))
        if det and os.path.isfile(det):
            rows = _from_detection_csv(det)
            src = det

    if not rows:
        print('[objective-trace] No objective_trace or detection_points data found.')
        return 1

    _build_html(rows, src, out_path)
    print(f'[objective-trace] wrote {out_path}')
    print(f'[objective-trace] rows={len(rows)} source={src}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
