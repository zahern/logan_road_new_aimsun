#!/usr/bin/env python3
"""
Cycle-dependent Offset Correction Dashboard
============================================
Analyzes offset-correction (forward green-wave alignment) actions at signal-cycle
boundaries. Unlike plot_offset.py (bus-dependent, per-vehicle tracking), this
dashboard shows cycle-level offset corrections triggered to maintain/recover
corridor green-wave alignment independent of individual bus arrivals.

Offset corrections occur when:
  1. A downstream corridor junction detects upstream/downstream misalignment
  2. The offset error exceeds DCTSP_OC_THRESH_S (e.g., 3s)
  3. A few seconds before the next signal cycle ends (cycle-dependent trigger)
  4. The controller trims the current non-bus phase to advance the bus phase

This dashboard visualizes:
  - Per-junction offset-correction event frequency over time
  - Magnitude of offset corrections (s cut from phase)
  - Reward impact of offset corrections
  - Comparison: offset-corrected cycles vs non-corrected baseline
  - Cycle-end timing and signal-phase relationships
"""

import csv
import json
import os
from collections import defaultdict, OrderedDict
from pathlib import Path


def _read_offset_corrections_from_csv(csv_path: str) -> list:
    """
    Load offset-correction events from green_offsets_*.csv or similar.
    
    Expected columns (or fallback empty):
      - sim_time_s: simulation time (s)
      - junction_id: controller intersection
      - offset_error_s: detected misalignment (s)
      - offset_correction_s: correction applied (s, typically 3-15)
      - oc_reward: reward value for the cycle-end offset correction
      - upstream_junction_id (optional): source of offset signal
      - downstream_alignment_s (optional): residual error after correction
    
    Returns list of dicts with normalized keys (default 0.0 for missing cols).
    """
    if not csv_path or not os.path.isfile(csv_path):
        return []
    
    out = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return []
            
            for row in reader:
                try:
                    # Filter: only rows where offset_correction_s > 0 or oc_reward is non-zero
                    oc_cut = float(row.get("offset_correction_s", 0) or 0)
                    oc_rwd = float(row.get("oc_reward", 0) or 0)
                    
                    if oc_cut <= 0.0 and oc_rwd == 0.0:
                        continue  # Skip rows with no correction event
                    
                    out.append({
                        "t_s": float(row.get("sim_time_s", 0) or 0),
                        "jct_id": int(float(row.get("junction_id", -1) or -1)),
                        "oc_error_s": float(row.get("offset_error_s", 0) or 0),
                        "oc_cut_s": oc_cut,
                        "oc_reward": oc_rwd,
                        "upstream_jct": int(float(row.get("upstream_junction_id", -1) or -1)),
                        "residual_error_s": float(row.get("downstream_alignment_s", 0) or 0),
                    })
                except (ValueError, TypeError):
                    continue
    except Exception:
        pass
    
    return out


def _read_reward_cycle_for_offset_corrections(csv_path: str, exclude_jcts=None) -> list:
    """
    Extract OFFSET_CORRECTION rows from reward_cycle_*.csv.
    
    Filters for rows where action starts with 'OC_' (OFFSET_CORRECTION type).
    Returns list of dicts with cycle-end context.
    """
    if exclude_jcts is None:
        exclude_jcts = set(['39568', '1119660', '11118289'])
    
    if not csv_path or not os.path.isfile(csv_path):
        return []
    
    out = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return []
            
            for row in reader:
                try:
                    action = str(row.get("action", "") or "")
                    # Filter for OFFSET_CORRECTION actions (logged as 'OC_5', 'OC_10', etc.)
                    if not action.startswith("OC_"):
                        continue
                    
                    jct_id = int(float(row.get("junction_id", -1) or -1))
                    if str(jct_id) in exclude_jcts:
                        continue
                    
                    out.append({
                        "t_s": float(row.get("sim_time_s", 0) or 0),
                        "jct_id": jct_id,
                        "veh_id": int(float(row.get("veh_id", -1) or -1)),
                        "action": action,
                        "action_param_s": float(action.split("_")[1]) if "_" in action else 0.0,
                        "reward": float(row.get("reward", 0) or 0),
                        "is_chosen": int(float(row.get("is_chosen", 0) or 0)),
                        "current_phase": int(float(row.get("current_phase", -1) or -1)),
                        "sigma_in_s": float(row.get("sigma_in_s", 0) or 0),
                        "sigma_out_s": float(row.get("sigma_out_s", 0) or 0),
                        "no_action_reward": float(row.get("no_action_reward", 0) or 0),
                        "reward_delta": float(row.get("reward_delta", row.get("reward", 0)) or 0),
                    })
                except (ValueError, TypeError, IndexError):
                    continue
    except Exception:
        pass
    
    return out


def generate_offset_correction_cycle_dashboard(reward_csv_path: str,
                                                output_html_path: str = "offset_correction_cycle.html",
                                                exclude_jcts=None) -> None:
    """
    Generate cycle-dependent offset-correction dashboard HTML.
    
    Reads OFFSET_CORRECTION rows from reward_cycle_*.csv, groups by cycle,
    and visualizes offset-correction magnitude, timing, and reward impact.
    """
    if exclude_jcts is None:
        exclude_jcts = set(['39568', '1119660', '11118289'])
    
    oc_rows = _read_reward_cycle_for_offset_corrections(reward_csv_path, exclude_jcts)
    
    if not oc_rows:
        print(f"[WARNING] No OFFSET_CORRECTION actions found in {reward_csv_path}")
        return
    
    # ── Group by junction ────────────────────────────────────────────────────
    by_jct = defaultdict(list)
    for row in oc_rows:
        by_jct[row["jct_id"]].append(row)
    
    # Sort each junction's events by time
    for jct_id in by_jct:
        by_jct[jct_id].sort(key=lambda x: x["t_s"])
    
    # ── Summary statistics ───────────────────────────────────────────────────
    total_oc_events = len(oc_rows)
    total_oc_cut_s = sum(row["action_param_s"] for row in oc_rows)
    avg_oc_cut_s = total_oc_cut_s / total_oc_events if total_oc_events > 0 else 0.0
    
    chosen_events = [row for row in oc_rows if row["is_chosen"]]
    total_oc_reward = sum(row["reward_delta"] for row in chosen_events)
    avg_oc_reward = total_oc_reward / len(chosen_events) if chosen_events else 0.0
    
    # ── Prepare data for JavaScript charts ────────────────────────────────────
    jct_ids_sorted = sorted(by_jct.keys())
    jct_data_js = {}
    
    for jct_id in jct_ids_sorted:
        events = by_jct[jct_id]
        jct_data_js[str(jct_id)] = {
            "event_times": [e["t_s"] for e in events],
            "action_params": [e["action_param_s"] for e in events],
            "rewards": [e["reward"] for e in events],
            "is_chosen": [e["is_chosen"] for e in events],
            "sigmas_in": [e["sigma_in_s"] for e in events],
            "sigmas_out": [e["sigma_out_s"] for e in events],
            "phases": [e["current_phase"] for e in events],
            "count": len(events),
        }
    
    # ── Generate HTML ────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Offset Correction Cycle Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
            margin-bottom: 10px;
            font-size: 2.2em;
        }}
        .subtitle {{
            color: #666;
            margin-bottom: 30px;
            font-size: 0.95em;
        }}
        .summary-card {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .card {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .card h3 {{
            color: #f39c12;
            font-size: 0.85em;
            text-transform: uppercase;
            margin-bottom: 8px;
            font-weight: 600;
        }}
        .card .value {{
            font-size: 2em;
            font-weight: 700;
            color: #333;
        }}
        .card .unit {{
            color: #999;
            font-size: 0.85em;
            margin-top: 4px;
        }}
        .chart-container {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .chart-container h2 {{
            color: #333;
            font-size: 1.3em;
            margin-bottom: 15px;
            border-bottom: 2px solid #f39c12;
            padding-bottom: 10px;
        }}
        .chart {{
            width: 100%;
            height: 400px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        th {{
            background: #f39c12;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }}
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid #eee;
        }}
        tr:hover {{
            background: #fafafa;
        }}
        .positive {{
            color: #27ae60;
            font-weight: 600;
        }}
        .negative {{
            color: #e74c3c;
            font-weight: 600;
        }}
        .neutral {{
            color: #95a5a6;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔄 Offset Correction Cycle Dashboard</h1>
        <p class="subtitle">Cycle-dependent signal phase adjustments for green-wave alignment recovery</p>
        
        <div class="summary-card">
            <div class="card">
                <h3>Total OC Events</h3>
                <div class="value">{total_oc_events}</div>
                <div class="unit">offset-correction cycles</div>
            </div>
            <div class="card">
                <h3>Total Cut Time</h3>
                <div class="value">{total_oc_cut_s:.1f}s</div>
                <div class="unit">cumulative phase reduction</div>
            </div>
            <div class="card">
                <h3>Average OC Size</h3>
                <div class="value">{avg_oc_cut_s:.1f}s</div>
                <div class="unit">per cycle</div>
            </div>
            <div class="card">
                <h3>Total OC Reward</h3>
                <div class="value {('positive' if total_oc_reward >= 0 else 'negative')}">{total_oc_reward:.1f}</div>
                <div class="unit">pax·s cumulative</div>
            </div>
            <div class="card">
                <h3>Avg OC Reward</h3>
                <div class="value {('positive' if avg_oc_reward >= 0 else 'negative')}">{avg_oc_reward:.2f}</div>
                <div class="unit">per chosen action</div>
            </div>
            <div class="card">
                <h3>Chosen Actions</h3>
                <div class="value">{len(chosen_events)}</div>
                <div class="unit">{100*len(chosen_events)/total_oc_events:.0f}% of OC events</div>
            </div>
        </div>

        <div class="chart-container">
            <h2>Offset Corrections Timeline (all junctions)</h2>
            <div id="timeline_chart" class="chart"></div>
        </div>

        <div class="chart-container">
            <h2>OC Magnitude by Junction</h2>
            <div id="magnitude_chart" class="chart"></div>
        </div>

        <div class="chart-container">
            <h2>OC Event Frequency by Junction</h2>
            <div id="frequency_chart" class="chart"></div>
        </div>

        <div class="chart-container">
            <h2>OC Reward Distribution (Chosen vs Evaluated)</h2>
            <div id="reward_chart" class="chart"></div>
        </div>

        <div class="chart-container">
            <h2>Per-Junction OC Detail</h2>
            <table>
                <thead>
                    <tr>
                        <th>Junction ID</th>
                        <th>OC Events</th>
                        <th>Total Cut (s)</th>
                        <th>Avg Cut (s)</th>
                        <th>Chosen Events</th>
                        <th>Total Reward (pax·s)</th>
                        <th>Avg Reward (pax·s)</th>
                    </tr>
                </thead>
                <tbody>
"""
    
    for jct_id in jct_ids_sorted:
        events = by_jct[jct_id]
        jct_chosen = [e for e in events if e["is_chosen"]]
        jct_total_cut = sum(e["action_param_s"] for e in events)
        jct_avg_cut = jct_total_cut / len(events) if events else 0.0
        jct_total_reward = sum(e["reward_delta"] for e in jct_chosen)
        jct_avg_reward = jct_total_reward / len(jct_chosen) if jct_chosen else 0.0
        
        html += f"""                    <tr>
                        <td><strong>{jct_id}</strong></td>
                        <td>{len(events)}</td>
                        <td>{jct_total_cut:.1f}</td>
                        <td>{jct_avg_cut:.1f}</td>
                        <td>{len(jct_chosen)}</td>
                        <td class="{('positive' if jct_total_reward >= 0 else 'negative')}">{jct_total_reward:.1f}</td>
                        <td class="{('positive' if jct_avg_reward >= 0 else 'negative')}">{jct_avg_reward:.2f}</td>
                    </tr>
"""
    
    html += """                </tbody>
            </table>
        </div>
    </div>

    <script>
"""
    
    # ── Timeline chart (all events across all junctions) ──────────────────────
    all_times = [row["t_s"] for row in oc_rows]
    all_cuts = [row["action_param_s"] for row in oc_rows]
    all_jcts = [row["jct_id"] for row in oc_rows]
    all_is_chosen = [row["is_chosen"] for row in oc_rows]
    
    html += f"""
        var timelineData = [{{
            x: {json.dumps(all_times)},
            y: {json.dumps(all_cuts)},
            mode: 'markers',
            type: 'scatter',
            marker: {{
                size: 8,
                color: {json.dumps([1 if c else 0 for c in all_is_chosen])},
                colorscale: [['0', '#bdc3c7'], ['1', '#f39c12']],
                line: {{color: '#333', width: 1}},
                showscale: false
            }},
            text: {json.dumps([f"Junction {j}, Cut: {c:.1f}s, Chosen: {bool(ch)}" for j, c, ch in zip(all_jcts, all_cuts, all_is_chosen)])},
            hovertemplate: '%{{text}}<extra></extra>',
            name: 'OC Events'
        }}];
        
        Plotly.newPlot('timeline_chart', timelineData, {{
            title: '',
            xaxis: {{ title: 'Simulation Time (s)' }},
            yaxis: {{ title: 'Phase Cut (s)', zeroline: true }},
            hovermode: 'closest',
            height: 400
        }}, {{responsive: true}});
"""
    
    # ── Magnitude by junction (box plot) ────────────────────────────────────
    magnitude_data = []
    for jct_id in jct_ids_sorted:
        events = by_jct[jct_id]
        cuts = [e["action_param_s"] for e in events]
        magnitude_data.append({
            'y': cuts,
            'name': str(jct_id),
            'type': 'box',
            'boxmean': 'sd'
        })
    
    html += f"""
        var magnitudeData = {json.dumps(magnitude_data)};
        Plotly.newPlot('magnitude_chart', magnitudeData, {{
            title: '',
            yaxis: {{ title: 'Phase Cut (s)' }},
            xaxis: {{ title: 'Junction ID' }},
            hovermode: 'closest',
            height: 400
        }}, {{responsive: true}});
"""
    
    # ── Frequency by junction (bar chart) ────────────────────────────────────
    freq_jcts = [str(jct_id) for jct_id in jct_ids_sorted]
    freq_counts = [len(by_jct[jct_id]) for jct_id in jct_ids_sorted]
    freq_chosen = [len([e for e in by_jct[jct_id] if e["is_chosen"]]) for jct_id in jct_ids_sorted]
    
    html += f"""
        var frequencyData = [
            {{x: {json.dumps(freq_jcts)}, y: {json.dumps(freq_counts)}, type: 'bar', name: 'Total Events', marker: {{color: '#3498db'}}}},
            {{x: {json.dumps(freq_jcts)}, y: {json.dumps(freq_chosen)}, type: 'bar', name: 'Chosen Events', marker: {{color: '#f39c12'}}}}
        ];
        Plotly.newPlot('frequency_chart', frequencyData, {{
            title: '',
            barmode: 'group',
            yaxis: {{ title: 'Event Count' }},
            xaxis: {{ title: 'Junction ID' }},
            hovermode: 'closest',
            height: 400
        }}, {{responsive: true}});
"""
    
    # ── Reward distribution (chosen vs evaluated) ──────────────────────────────
    chosen_rewards = [e["reward"] for e in oc_rows if e["is_chosen"]]
    eval_rewards = [e["reward"] for e in oc_rows if not e["is_chosen"]]
    
    html += f"""
        var rewardData = [
            {{y: {json.dumps(chosen_rewards)}, name: 'Chosen OC Actions', type: 'histogram', marker: {{color: '#f39c12'}}}},
            {{y: {json.dumps(eval_rewards)}, name: 'Evaluated OC Actions', type: 'histogram', marker: {{color: '#bdc3c7'}}}}
        ];
        Plotly.newPlot('reward_chart', rewardData, {{
            title: '',
            barmode: 'overlay',
            xaxis: {{ title: 'Reward (pax·s)' }},
            yaxis: {{ title: 'Frequency' }},
            hovermode: 'closest',
            height: 400
        }}, {{responsive: true}});
    </script>
</body>
</html>
"""
    
    # Write HTML file
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"[OK] Offset correction cycle dashboard written to {output_html_path}")
    print(f"     Total OC events: {total_oc_events}")
    print(f"     Total cut time: {total_oc_cut_s:.1f}s")
    print(f"     Avg OC magnitude: {avg_oc_cut_s:.1f}s per cycle")
    print(f"     Total OC reward: {total_oc_reward:.1f} pax·s")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python plot_offset_correction_cycle.py <reward_cycle_csv> [output_html]")
        print("\nExample:")
        print("  python plot_offset_correction_cycle.py reward_cycle_DCTSP_INV_DELAY_2025-01-15_103042.csv offset_correction_cycle.html")
        sys.exit(1)
    
    reward_csv = sys.argv[1]
    output_html = sys.argv[2] if len(sys.argv) > 2 else "offset_correction_cycle.html"
    
    generate_offset_correction_cycle_dashboard(reward_csv, output_html)
