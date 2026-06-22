"""
plot_reward_breakdown.py
========================
Reward decomposition dashboard for DCTSP strategies.

Shows for each strategy and action type:
  1. NO_ACTION delay context — how bad the situation was when each action was chosen
  2. bus_saved_pax_s vs other_inc_pax_s vs net benefit
  3. Selection frequency and average reward when chosen
  4. Reward vs NO_ACTION baseline (delta chart)
  5. Summary table

Usage:
    python plot_reward_breakdown.py
    python plot_reward_breakdown.py logs/ reward_breakdown.html
"""
import os, sys, csv, glob, json, collections
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Action label registry — auto-discovered from CSV, with fallback list.
# Kept as a dict for color assignment; unknown actions get a default gray.
_KNOWN_ACTIONS = {
    "NO_ACTION": "#7f8c8d",
    "GE_5": "#27ae60", "GE_10": "#2ecc71", "GE_15": "#1abc9c",
    "GR_5":  "#a3e635", "GR_10": "#84cc16", "GR_15": "#65a30d",
    "INS_5": "#e74c3c", "INS_10": "#e74c3c", "INS_15": "#c0392b", "INS_20": "#922b21",
    "INS_POST_8": "#e67e22", "INS_POST_10": "#e67e22", "INS_POST_15": "#d35400",
    "INS_POST_18": "#d35400", "INS_POST_20": "#d35400",
    "INS_PRETERM_8": "#8e44ad", "INS_PRETERM_10": "#8e44ad",
    "INS_PRETERM_15": "#8e44ad", "INS_PRETERM_18": "#8e44ad",
    "INS_PRETERM_20": "#8e44ad",
}

def _action_color(label: str) -> str:
    """Return a color for an action label, generating one if unknown."""
    if label in _KNOWN_ACTIONS:
        return _KNOWN_ACTIONS[label]
    # Auto-generate colors for unknown labels by hashing
    _h = hash(label) & 0xFFFFFF
    return f"#{_h:06x}"

def _action_sort_key(label: str) -> tuple:
    """Sort actions: NA first, then by type, then by duration."""
    if label == "NO_ACTION":
        return (0, 0)
    parts = label.split("_")
    type_order = {"GE": 1, "GR": 2, "INS": 3, "INS_POST": 3, "INS_PRETERM": 4, "ER": 5, "EARLY_RED": 5}
    _t = type_order.get(parts[0], 10)
    _d = 0
    for p in parts[1:]:
        try:
            _d = int(float(p))
            break
        except ValueError:
            continue
    return (_t, _d)

_HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<title>DCTSP Reward Breakdown</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
:root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--muted:#8b949e;--line:#30363d;--acc:#58a6ff;}
body{margin:0;font-family:"Segoe UI",sans-serif;background:var(--bg);color:var(--ink);}
.wrap{max-width:1350px;margin:0 auto;padding:18px;}
h1{font-size:21px;color:var(--acc);margin:0 0 6px}
h2{font-size:14px;color:var(--acc);margin:14px 0 4px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px;margin-bottom:12px}
.info{background:#0d2137;border:1px solid #1a4a7a;border-radius:6px;padding:9px;font-size:12px;color:#90c8f8;margin-bottom:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:11px}
table{border-collapse:collapse;width:100%;font-size:11px}
th{background:#21262d;padding:5px 8px;text-align:left;border:1px solid var(--line)}
td{padding:4px 8px;border:1px solid var(--line)}
</style></head><body><div class="wrap">
<div class="card">
  <h1>DCTSP Reward Breakdown &#8212; Where Do the Numbers Come From?</h1>
  <div class="info">
    <b>Total-delay-aware reward (2026 fix):</b>
    R = w<sub>hw</sub>&times;&Delta;hw + (1&minus;w<sub>hw</sub>)&times;(CPD&Delta; &minus; baseline_cross_traffic/occ)<br>
    Adding the cross-traffic baseline makes <b>NO_ACTION negative</b> even when the bus is on a green phase
    (the intersection is still paying the cost of the bus phase cycle for other vehicles).<br>
    <b>reward_delta between actions is unchanged</b> &mdash; the baseline is a constant offset at each detection event,
    so action ranking and selection are identical to the previous formulation.<br>
    <b>bus_saved_pax_s</b> &gt; 0 = action reduces bus delay (good).
    <b>other_inc_pax_s</b> &gt; 0 = action adds incremental car/truck delay (bad).<br>
    <b>GE (Green Extension):</b> extends the current bus-phase green by 5/10/15 s so a late bus can catch it.
    Car cost = triangle-area queue delay on cross-street approaches. Only fires when bus is about to miss green.<br>
    <b>GR (Green Reallocation):</b> borrows green time from the current non-bus phase and advances the bus phase earlier
    in the cycle, then recovers the same amount by shortening the planned bus phase later (net-zero green addition).
    Cross-traffic cost &asymp; 0 (cut is recovered), so GR is the lowest-disruption action. Only evaluated when
    the bus is on the wrong phase (non-bus phase is currently running) and DCTSP_GREEN_REALLOC_MODE is enabled.<br>
    <b>INS (Insertion):</b> inserts a dedicated bus-phase green of 10/15/20 s into the cycle, interrupting the
    current cross-street phase.  Highest bus benefit but also highest car cost &mdash; subject to cascade
    multiplier (BG_CASCADE_MULT) in BARGAIN mode to account for spillback beyond the local intersection.<br>
    <b>INV_DELAY</b> rewards range 0&ndash;2.0 (1/(&epsilon;+delay), max when delay=0, &epsilon;=0.5).<br>
    <b>SELFORG fix:</b> balance check now uses UpFlowList cross-traffic estimate (OtherDelay was always 0 in DCTSP path).
  </div>
</div>

<div class="card">
  <h2>1. NO_ACTION Delay Context &mdash; How bad was the situation when each action was chosen?</h2>
  <div class="info">Higher context delay = bus was in worse trouble when the action was selected. GE and INS should only be chosen for serious delay situations (large no_strategy_delay).</div>
  <div class="grid" id="ctx"></div>
</div>

<div class="card">
  <h2>2. Component Breakdown &mdash; Bus Saved vs Car Cost vs Net (avg over all evaluations)</h2>
  <div class="info">Green = bus delay saved. Red = incremental car delay added (shown as negative). Orange = net. Actions with negative net are rarely chosen.</div>
  <div class="grid" id="comp"></div>
</div>

<div class="card">
  <h2>3. Selection Frequency &amp; Average Reward (chosen evaluations only)</h2>
  <div class="info">Bars = % of evaluation cycles where each action was chosen. Diamonds = average reward when chosen. High NO_ACTION % is correct when buses arrive on green.</div>
  <div class="grid" id="sel"></div>
</div>

<div class="card">
  <h2>4. Reward vs NO_ACTION Baseline (with total-delay fix: NO_ACTION now negative)</h2>
  <div class="info">With the baseline fix, NO_ACTION reward is now negative proportional to intersection delay (not 0). Delta (dots) shows improvement over NO_ACTION baseline.
  Green delta = action is better than doing nothing. Red = action is worse.</div>
  <div class="grid" id="base"></div>
</div>

<div class="card">
  <h2>5. Strategy Comparison &mdash; Action Rate &amp; TSP Effectiveness</h2>
  <div class="info">Action rate = fraction of detections where TSP was applied. Effective TSP: low action rate with high bus delay reduction (conservative but impactful).</div>
  <div class="grid" id="cmp"></div>
</div>

<div class="card">
  <h2>6. Model vs Measured Debug Audit (requires reward_cycle v2 columns)</h2>
  <div class="info">
    <b>OtherDelay model</b> = shockwave queue model estimate for cross-traffic (pax&middot;s).<br>
    <b>Measured car cumul</b> = cumulative car pax delay from Aimsun AKIEst statistics.<br>
    <b>No-action bus delay</b> = bus delay estimate under no TSP action (seconds).<br>
    Large gap between model and measured = shockwave model drifting from reality.
  </div>
  <div class="grid" id="debug"></div>
</div>

<div class="card">
  <h2>7. Summary Table</h2>
  <div id="tbl" style="overflow-x:auto"></div>
</div>
<div class="card">
  <h2>8. Continuous Duration Distribution (HS-solved values)</h2>
  <div class="info">Shows the distribution of durations found by Harmony Search for each action type. Each point is one evaluation. Box = interquartile range.</div>
  <div class="grid" id="dur"></div>
</div>
</div>
<script>
const D=__DATA__; const ST=__STRATS__; const AC=__ACTS__; const CO=__COLORS__;
const _c=a=>CO[a]||'#888';
function mkDiv(){const d=document.createElement('div');d.style.height='310px';return d;}

// 1. Context — no_strategy_delay_pax_s when each action was evaluated
(function(){
  const el=document.getElementById('ctx'); el.innerHTML='';
  ST.forEach(s=>{
    const d=D[s]||{}; const dv=mkDiv(); el.appendChild(dv);
    const acts=AC.filter(a=>d[a]&&d[a].n>0);
    Plotly.newPlot(dv,[
      {x:acts,y:acts.map(a=>d[a].avg_noact_delay||0),type:'bar',name:'Avg total delay (pax-s)',
        marker:{color:acts.map(_c)},text:acts.map(a=>(d[a].avg_noact_delay||0).toFixed(0)),textposition:'outside'},
      {x:acts,y:acts.map(a=>d[a].avg_eta||0),type:'scatter',mode:'markers',name:'Avg bus ETA (s)',
        marker:{size:9,color:'#f1c40f'},yaxis:'y2'},
    ],{template:'plotly_dark',title:s,xaxis:{tickangle:30},
      yaxis:{title:'Total pax-s delay (bus+car baseline)'},
      yaxis2:{title:'Bus ETA (s)',overlaying:'y',side:'right',color:'#f1c40f',showgrid:false},
      legend:{orientation:'h',y:-0.3},height:300,margin:{t:40,b:80}});
  });
})();

// 2. Components — bus saved vs car cost vs net
(function(){
  const el=document.getElementById('comp'); el.innerHTML='';
  ST.forEach(s=>{
    const d=D[s]||{}; const dv=mkDiv(); el.appendChild(dv);
    const acts=AC.filter(a=>d[a]&&d[a].n>0&&a!=='NO_ACTION');
    Plotly.newPlot(dv,[
      {x:acts,y:acts.map(a=>d[a].avg_bus||0),type:'bar',name:'Bus saved (pax-s)',marker:{color:'rgba(39,174,96,0.8)'}},
      {x:acts,y:acts.map(a=>-(d[a].avg_other||0)),type:'bar',name:'Car cost (neg, pax-s)',marker:{color:'rgba(231,76,60,0.7)'}},
      {x:acts,y:acts.map(a=>d[a].avg_net||0),type:'scatter',mode:'markers+lines',name:'Net',
        marker:{size:9,color:'#f39c12'},line:{color:'#f39c12',width:2}},
    ],{template:'plotly_dark',title:s,barmode:'overlay',
      xaxis:{tickangle:30},
      yaxis:{title:'pax-seconds',zeroline:true,zerolinecolor:'#555'},
      shapes:[{type:'line',x0:-0.5,x1:acts.length-0.5,y0:0,y1:0,line:{color:'white',width:1,dash:'dash'}}],
      legend:{orientation:'h',y:-0.3},height:300,margin:{t:40,b:80}});
  });
})();

// 3. Selection frequency and avg reward
(function(){
  const el=document.getElementById('sel'); el.innerHTML='';
  ST.forEach(s=>{
    const d=D[s]||{}; const dv=mkDiv(); el.appendChild(dv);
    const acts=AC.filter(a=>d[a]&&d[a].n>0);
    Plotly.newPlot(dv,[
      {x:acts,y:acts.map(a=>d[a].pct_chosen||0),type:'bar',name:'% chosen',
        marker:{color:acts.map(_c)},
        text:acts.map(a=>`${d[a].chosen}x`),textposition:'outside'},
      {x:acts,y:acts.map(a=>d[a].avg_r||0),type:'scatter',mode:'markers',name:'Avg reward (chosen)',
        marker:{size:9,symbol:'diamond',color:'white'},yaxis:'y2'},
    ],{template:'plotly_dark',title:s,xaxis:{tickangle:30},
      yaxis:{title:'% of evaluations chosen'},
      yaxis2:{title:'Avg reward (when chosen)',overlaying:'y',side:'right',showgrid:false},
      legend:{orientation:'h',y:-0.3},height:300,margin:{t:40,b:80}});
  });
})();

// 4. Reward vs NO_ACTION baseline (with baseline fix: NO_ACTION now negative)
(function(){
  const el=document.getElementById('base'); el.innerHTML='';
  ST.forEach(s=>{
    const d=D[s]||{}; const dv=mkDiv(); el.appendChild(dv);
    const acts=AC.filter(a=>d[a]&&d[a].n>0);
    const avgr =acts.map(a=>d[a].avg_r||0);
    const noact=acts.map(a=>d[a].avg_noact_r||(d['NO_ACTION']||{}).avg_r||0);
    const delta=avgr.map((v,i)=>+(v-noact[i]).toFixed(3));
    Plotly.newPlot(dv,[
      {x:acts,y:avgr,type:'bar',name:'Avg reward',marker:{color:acts.map(_c),opacity:0.75}},
      {x:acts,y:noact,type:'scatter',mode:'markers',name:'NO_ACTION baseline (same cycles)',
        marker:{symbol:'line-ew',size:18,color:'white',line:{width:3}}},
      {x:acts,y:delta,type:'scatter',mode:'markers+text',name:'Delta vs baseline',
        marker:{size:9,color:delta.map(v=>v>0?'#2ecc71':'#e74c3c')},
        text:delta.map(v=>v.toFixed(2)),textposition:'top center',yaxis:'y2'},
    ],{template:'plotly_dark',title:s,xaxis:{tickangle:30},
      yaxis:{title:'Avg reward (with baseline cost)'},
      yaxis2:{title:'Delta vs NO_ACTION',overlaying:'y',side:'right',showgrid:false},
      legend:{orientation:'h',y:-0.3},height:300,margin:{t:40,b:80}});
  });
})();

// 5. Strategy comparison: action rate vs avg reward delta
(function(){
  const el=document.getElementById('cmp'); el.innerHTML='';
  const allActs=['GE_5','GE_10','GE_15','GR_5','GR_10','GR_15','INS_10','INS_15','INS_20'];
  const dv=mkDiv(); dv.style.height='380px'; el.appendChild(dv);
  const stRates=ST.map(s=>{
    const d=D[s]||{};
    const na_n=(d['NO_ACTION']||{}).n||1;
    const total=allActs.reduce((acc,a)=>acc+((d[a]||{}).n||0),0)+na_n;
    const fired=allActs.reduce((acc,a)=>acc+((d[a]||{}).chosen||0),0);
    const avgDelta=allActs.reduce((acc,a)=>{
      const ad=d[a]; if(!ad||!ad.n)return acc;
      return acc+(ad.avg_r-(d['NO_ACTION']||{}).avg_r||0);
    },0)/Math.max(allActs.filter(a=>d[a]&&d[a].n).length,1);
    return {s,rate:100*fired/Math.max(total,1),avgDelta};
  });
  Plotly.newPlot(dv,[
    {x:stRates.map(r=>r.s),y:stRates.map(r=>+r.rate.toFixed(1)),type:'bar',
      name:'TSP Action Rate (%)',marker:{color:stRates.map(r=>r.rate>40?'#e74c3c':'#2ecc71')}},
    {x:stRates.map(r=>r.s),y:stRates.map(r=>+r.avgDelta.toFixed(3)),type:'scatter',
      mode:'markers+lines',name:'Avg reward delta vs NO_ACTION',
      marker:{size:10,color:'#f1c40f'},line:{color:'#f1c40f',width:2},yaxis:'y2'},
  ],{template:'plotly_dark',title:'Strategy Action Rates & Avg Reward Delta',
    xaxis:{tickangle:20},
    yaxis:{title:'TSP Action Rate (%)'},
    yaxis2:{title:'Avg reward delta',overlaying:'y',side:'right',color:'#f1c40f',showgrid:false},
    shapes:[{type:'line',x0:-0.5,x1:ST.length-0.5,y0:0,y1:0,line:{color:'white',width:1,dash:'dash'},yref:'y2'}],
    legend:{orientation:'h',y:-0.25},height:360,margin:{t:40,b:80}});
})();

// 6. Debug audit
(function(){
  const el=document.getElementById('debug'); el.innerHTML='';
  const anyDebug=ST.some(s=>AC.some(a=>(D[s]||{})[a]&&((D[s]||{})[a].has_debug_cols)));
  if(!anyDebug){
    el.innerHTML='<p style="color:var(--muted);padding:8px">No debug columns found (requires reward_cycle v2 format &mdash; run a new simulation).</p>';
    return;
  }
  ST.forEach(s=>{
    const d=D[s]||{}; const dv=mkDiv(); el.appendChild(dv);
    const acts=AC.filter(a=>d[a]&&d[a].n>0);
    Plotly.newPlot(dv,[
      {x:acts,y:acts.map(a=>d[a].avg_other_model||0),type:'bar',name:'OtherDelay model (pax·s)',marker:{color:'rgba(52,152,219,0.8)'}},
      {x:acts,y:acts.map(a=>d[a].avg_meas_car||0),type:'bar',name:'Measured car cumul (pax·s)',marker:{color:'rgba(155,89,182,0.7)'}},
      {x:acts,y:acts.map(a=>d[a].avg_no_act_delay_s||0),type:'scatter',mode:'markers+lines',
        name:'No-action bus delay (s)',
        marker:{size:9,color:'#f1c40f'},line:{color:'#f1c40f',width:2},yaxis:'y2'},
    ],{template:'plotly_dark',title:s,barmode:'group',xaxis:{tickangle:30},
      yaxis:{title:'pax·s'},
      yaxis2:{title:'Bus no-act delay (s)',overlaying:'y',side:'right',color:'#f1c40f',showgrid:false},
      legend:{orientation:'h',y:-0.3},height:300,margin:{t:40,b:80}});
  });
})();

// 7. Summary table
(function(){
  const rows=[];
  const _pad = (v) => v != null ? Number(v).toFixed(1) : '—';
  ST.forEach(s=>AC.forEach(a=>{
    const d=(D[s]||{})[a]; if(!d||!d.n) return;
    rows.push(`<tr style="color:${_c(a)}">
      <td><b>${s}</b></td><td>${a}</td>
      <td>${d.n}</td><td>${d.chosen}</td><td>${d.pct_chosen}%</td>
      <td>${_pad(d.avg_param)}</td>
      <td>${(d.avg_noact_delay||0).toFixed(0)}</td>
      <td>${(d.avg_r||0).toFixed(3)}</td>
      <td>${(d.avg_bus||0).toFixed(1)}</td>
      <td>${(d.avg_other||0).toFixed(1)}</td>
      <td style="color:${(d.avg_net||0)>0?'#2ecc71':'#e74c3c'}">${(d.avg_net||0).toFixed(1)}</td>
      <td>${(d.avg_noact_r||0).toFixed(3)}</td>
      <td>${(d.avg_other_model||0).toFixed(1)}</td>
      <td>${(d.avg_meas_car||0).toFixed(1)}</td>
      <td>${(d.avg_no_act_delay_s||0).toFixed(2)}</td>
    </tr>`);
  }));
  document.getElementById('tbl').innerHTML=`<table>
    <thead><tr><th>Strategy</th><th>Action</th><th>Evals</th><th>Chosen</th><th>%</th>
    <th>Avg Param (s)</th><th>Avg Context Delay</th><th>Avg Reward</th>
    <th>Avg Bus Saved</th><th>Avg Car Cost</th><th>Net</th>
    <th>Avg NA R</th><th>OtherDelay Model</th><th>Measured Car</th><th>No-act Bus (s)</th>
    </tr></thead>
    <tbody>${rows.join('')}</tbody></table>`;
})();

// 8. Continuous duration distribution (HS-solved values)
(function(){
  const el=document.getElementById('dur'); el.innerHTML='';
  const durData=[];
  ST.forEach(s=>{
    const sd=D[s]||{};
    AC.forEach(a=>{
      const d=sd[a]; if(!d||!d.params||!d.params.length) return;
      d.params.forEach(v=>durData.push({strategy:s,action:a,duration:v}));
    });
  });
  if(!durData.length){el.innerHTML='<p style="color:var(--muted);padding:8px">No continuous-duration data found (requires HS_EXT or action_param_s column).</p>';return;}
  const durActs=[...new Set(durData.map(d=>d.action))];
  const traces=durActs.map(a=>{
    const vals=durData.filter(d=>d.action===a).map(d=>d.duration);
    return {type:'box',y:vals,name:a,marker:{color:_c(a)},boxmean:true};
  });
  const dv=mkDiv(); dv.style.height='400px'; el.appendChild(dv);
  Plotly.newPlot(dv,traces,{template:'plotly_dark',title:'HS-Solved Duration Distribution',
    yaxis:{title:'Duration (s)'},margin:{t:40,b:60}});
})();
</script></body></html>
})();
</script></body></html>
"""


def _f(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def generate(log_dir=None, out_html=None):
    """
    Generate the reward breakdown dashboard HTML.

    Parameters
    ----------
    log_dir  : directory containing reward_cycle_*.csv files.
               Defaults to <script_dir>/logs.
    out_html : output HTML path.
               Defaults to <script_dir>/reward_breakdown.html.

    Returns the output path on success, or None on failure.
    """
    if log_dir  is None: log_dir  = os.path.join(SCRIPT_DIR, "logs")
    if out_html is None: out_html = os.path.join(SCRIPT_DIR, "reward_breakdown.html")

    # ── load latest reward_cycle CSV per strategy ──────────────────────────────
    strat_files = {}
    for f in sorted(glob.glob(os.path.join(log_dir, "reward_cycle_*.csv")),
                    key=os.path.getmtime):
        stem  = Path(f).stem.replace("reward_cycle_", "")
        parts = stem.rsplit("_", 2)
        strat = (parts[0] if len(parts) == 3 and parts[1].isdigit()
                           and parts[2].isdigit() else stem)
        strat_files[strat] = f

    if not strat_files:
        print(f"[reward_breakdown] no reward_cycle CSV files found in {log_dir}")
        return None

    all_data = {}
    for strat, f in strat_files.items():
        with open(f, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        acts = collections.defaultdict(lambda: {
            "n": 0, "chosen": 0, "r": [], "bus": [], "other": [],
            "noact_r": [], "noact_delay": [], "eta": [], "t": [],
            "other_model": [], "meas_car": [], "no_act_delay_s": [],
            "params": [],
        })
        for r in rows:
            a      = r.get("action", "")
            chosen = r.get("is_chosen", "0") == "1"
            param  = _f(r.get("action_param_s"), None)
            d = acts[a]
            d["n"] += 1
            if chosen:
                d["chosen"] += 1
            d["r"].append(_f(r.get("reward")))
            d["bus"].append(_f(r.get("bus_saved_pax_s")))
            d["other"].append(_f(r.get("other_inc_pax_s")))
            d["noact_r"].append(_f(r.get("no_action_reward")))
            d["noact_delay"].append(_f(r.get("no_strategy_delay_pax_s")))
            d["eta"].append(_f(r.get("bus_eta_s")))
            d["t"].append(_f(r.get("sim_time_s")))
            d["other_model"].append(_f(r.get("other_delay_model_pax_s")))
            d["meas_car"].append(_f(r.get("measured_car_pax_s_cumul")))
            d["no_act_delay_s"].append(_f(r.get("no_act_delay_s")))
            if param is not None:
                d["params"].append(param)

        def avg(lst):
            return round(sum(lst) / max(len(lst), 1), 3)

        summary = {}
        for a, d in acts.items():
            summary[a] = {
                "n": d["n"],
                "chosen": d["chosen"],
                "pct_chosen": round(100.0 * d["chosen"] / max(d["n"], 1), 1),
                "avg_r":    avg(d["r"]),
                "avg_bus":  avg(d["bus"]),
                "avg_other": avg(d["other"]),
                "avg_net":  avg([b - o for b, o in zip(d["bus"], d["other"])]),
                "avg_noact_r":     avg(d["noact_r"]),
                "avg_noact_delay": avg(d["noact_delay"]),
                "avg_eta":  avg(d["eta"]),
                "avg_other_model": avg(d["other_model"]),
                "avg_meas_car": avg(d["meas_car"]),
                "avg_no_act_delay_s": avg(d["no_act_delay_s"]),
                "has_debug_cols": any(v != 0.0 for v in d["no_act_delay_s"]),
                "avg_param": avg(d["params"]) if d["params"] else None,
                "params": d["params"],
            }
        all_data[strat] = summary

    strategies = sorted(all_data.keys())
    print(f"[reward_breakdown] strategies: {strategies}")

    # Build sorted action list from all discovered actions across all strategies
    all_actions = set()
    for sdata in all_data.values():
        all_actions.update(sdata.keys())
    _sorted_actions = sorted(all_actions, key=_action_sort_key)
    _colors = {a: _action_color(a) for a in _sorted_actions}

    js_data   = json.dumps(all_data)
    js_strats = json.dumps(strategies)
    js_acts   = json.dumps(_sorted_actions)
    js_colors = json.dumps(_colors)

    html = (_HTML_TEMPLATE
        .replace("__DATA__",   js_data)
        .replace("__STRATS__", js_strats)
        .replace("__ACTS__",   js_acts)
        .replace("__COLORS__", js_colors))

    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[reward_breakdown] written -> {out_html}")
    return out_html


if __name__ == "__main__":
    _log_dir  = sys.argv[1] if len(sys.argv) > 1 else None
    _out_html = sys.argv[2] if len(sys.argv) > 2 else None
    generate(_log_dir, _out_html)
