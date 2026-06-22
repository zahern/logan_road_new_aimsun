"""
Usage
-----
  python generate_dashboard.py                     # auto-discover batch_results.csv
  python generate_dashboard.py batch_results.csv   out.html

Key fixes vs v1
---------------
  • Delta vs NORMAL baseline — every strategy shown as % improvement over NORMAL
  • Green rate CSV matching — sequential time-order zip, not filename heuristic
  • Density/speed filter — suppressed when all-zero (broken Aimsun stat)
  • Flow metric added   — aimsun_total_flow_veh
  • Normalized "spider" comparison chart so all KPIs visible on one scale
"""

import os
import sys
import csv
import glob
import json
import math
import datetime
import collections
import html as _html

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
  from plot_green_wave import (
    _load_detections,
    _junctions_from_detections,
    _find_tsp_vehicles,
    _phase_at_stopline,
    _geographic_junction_order,
    ALL_CORRIDOR_JCTS,
  )
  HAS_GW = True
except ImportError:
  HAS_GW = False
  ALL_CORRIDOR_JCTS = []
  print("[dashboard] plot_green_wave unavailable — using lightweight green-rate fallback")

# Derive active (TSP-controlled) vs passive (all other corridor junctions from Inter dict).
# Active = INTERSECTIONS_CONFIG junctions with SignalGroupIDList (the 9 controlled junctions).
# Passive = everything in Inter that is NOT actively controlled.
# ALL_INTER_JCTS = every junction in the Inter model setup dict (23 total).
try:
  from intersection_configs import INTERSECTIONS_CONFIG as _IC
  try:
    from intersection_configs import Inter as _INTER_DICT
  except ImportError:
    _INTER_DICT = {}
  _ACTIVE_JCTS  = [str(jid) for jid, cfg in _IC.items() if 'SignalGroupIDList' in cfg]
  _ACTIVE_SET   = set(_ACTIVE_JCTS)
  # Passive = all junctions in Inter OR INTERSECTIONS_CONFIG that are NOT actively controlled
  _ALL_INTER_JCTS   = sorted(set(str(j) for j in _INTER_DICT) | set(str(j) for j in _IC))
  _PASSIVE_JCTS     = [j for j in _ALL_INTER_JCTS if j not in _ACTIVE_SET]
  _ALL_CONFIG_JCTS  = _ALL_INTER_JCTS   # full set for seeding all_jct_ids
except ImportError:
  _IC = {}
  _ACTIVE_JCTS = []
  _PASSIVE_JCTS = []
  _ALL_CONFIG_JCTS = []
  _ALL_INTER_JCTS = []


# =============================================================================
# Data loading helpers
# =============================================================================

def _read_batch_csv(path: str) -> list:
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        print(f"[dashboard] Cannot read {path}: {e}")
        return []


def _flt(val, default=None):
    try:
        return float(val) if val not in (None, "", "N/A") else default
    except (TypeError, ValueError):
        return default


def _intish(val, default=0):
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _pick(row: dict, candidates: list, default=None):
    for c in candidates:
        v = row.get(c)
        if v not in (None, "", "N/A"):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return default


def _first_valid_metric(*values, allow_zero=True):
    for v in values:
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(fv):
            continue
        if not allow_zero and abs(fv) <= 1e-9:
            continue
        return fv
    return None


def _detect_csvs(log_dir: str) -> list:
    """Return detection_points CSV paths sorted by mtime (oldest first)."""
    return sorted(glob.glob(os.path.join(log_dir, "detection_points_*.csv")),
                  key=os.path.getmtime)


def _wave_csvs(log_dir: str) -> list:
  """Return corridor_wave_events CSV paths sorted by mtime (oldest first)."""
  return sorted(glob.glob(os.path.join(log_dir, "corridor_wave_events_*.csv")),
          key=os.path.getmtime)


def _bus_tracking_csvs(log_dir: str) -> list:
  """Return bus_positions CSV paths sorted by mtime (oldest first)."""
  return sorted(glob.glob(os.path.join(log_dir, "bus_positions_*.csv")),
          key=os.path.getmtime)


def _objective_trace_csvs(log_dir: str) -> list:
  """Return objective_trace CSV paths sorted by mtime (oldest first)."""
  return sorted(glob.glob(os.path.join(log_dir, "objective_trace_*.csv")),
          key=os.path.getmtime)


def _match_objective_trace_csv_by_name(exp_name: str, all_csvs: list) -> str:
  """Match objective_trace_<EXPERIMENT>_<ts>.csv to this experiment."""
  exp_lower = (exp_name or "").strip().lower()
  if not exp_lower:
    return None
  for p in reversed(all_csvs):
    stem = os.path.splitext(os.path.basename(p))[0].lower()
    if not stem.startswith("objective_trace_"):
      continue
    payload = stem[len("objective_trace_"):]
    parts = payload.split("_")
    if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
      exp_token = "_".join(parts[:-2]).strip().lower()
      if exp_token == exp_lower:
        return p
  for p in reversed(all_csvs):
    stem = os.path.basename(p).lower()
    if exp_lower in stem:
      return p
  return None


def _objective_trace_from_csv(path: str) -> list:
  """Load objective_trace CSV into list of dicts."""
  if not path or not os.path.isfile(path):
    return []
  out = []
  try:
    with open(path, newline="", encoding="utf-8") as f:
      for r in csv.DictReader(f):
        try:
          out.append({
            "t": float(r.get("sim_time_s", 0) or 0),
            "jct": int(float(r.get("junction_id", 0) or 0)),
            "vid": int(float(r.get("veh_id", -1) or -1)),
            "mode": str(r.get("mode", "") or ""),
            "decision": str(r.get("decision", "") or ""),
            "reason": str(r.get("reason", "") or ""),
            "current_phase": int(float(r.get("current_phase", -1) or -1)),
            "bus_phase": int(float(r.get("bus_phase", -1) or -1)),
            "bus_eta_s": float(r.get("bus_eta_s", 0) or 0),
            "time_to_bp_s": float(r.get("time_to_bp_s", 0) or 0),
            "natural_end_s": float(r.get("natural_end_s", 0) or 0),
            "next_red_s": float(r.get("next_red_s", 0) or 0),
            "ge_lb_s": float(r.get("ge_lb_s", 0) or 0),
            "ge_ub_s": float(r.get("ge_ub_s", 0) or 0),
            "opt_ge_s": float(r.get("opt_ge_s", 0) or 0),
            "bp_lb_s": float(r.get("bp_lb_s", 0) or 0),
            "bp_ub_s": float(r.get("bp_ub_s", 0) or 0),
            "opt_bp_s": float(r.get("opt_bp_s", 0) or 0),
            "delay_saved_pax_s": float(r.get("delay_saved_pax_s", 0) or 0),
            "delay_delta_pax_s": float(r.get("delay_delta_pax_s", 0) or 0),
            "delay_base_pax_s": float(r.get("delay_base_pax_s", 0) or 0),
            "delay_with_strategy_pax_s": float(r.get("delay_with_strategy_pax_s", 0) or 0),
            "no_strategy_delay_pax_s": float(r.get("no_strategy_delay_pax_s", r.get("delay_base_pax_s", 0)) or 0),
            "strategy_min_delay_pax_s": float(r.get("strategy_min_delay_pax_s", r.get("delay_with_strategy_pax_s", 0)) or 0),
            "delay_rule_pick": str(r.get("delay_rule_pick", "") or ""),
            "wave_active": int(float(r.get("wave_active", 0) or 0)),
            "focus_bus_id": int(float(r.get("focus_bus_id", -1) or -1)),
            "note": str(r.get("note", "") or ""),
          })
        except Exception:
          continue
  except Exception:
    pass
  return out


def _queue_entry_snapshots_from_csv(path: str) -> list:
    """Parse a queue_snapshot_*.csv for the per-approach entry-point chart.

    Reads directional queue columns: queue_main_nb, queue_main_sb, queue_side_eb, queue_side_wb
    or falls back to queue_side_detail (format: dir:sec_id:n_veh per section separated by |).
    Returns a list of dicts suitable for renderQueueEntryPoints().
    """
    if not path or not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    t = float(r.get("sim_time_s", 0) or 0)
                    jct = int(float(r.get("junction_id", -1) or -1))
                    main_veh = float(r.get("n_main_veh", 0) or 0)
                    main_dir = str(r.get("main_dir", "main") or "main")
                    sides = {}

                    # Try new directional columns first (queue_main_nb, queue_main_sb, queue_side_eb, queue_side_wb)
                    q_main_nb = float(r.get("queue_main_nb", 0) or 0)
                    q_main_sb = float(r.get("queue_main_sb", 0) or 0)
                    q_side_eb = float(r.get("queue_side_eb", 0) or 0)
                    q_side_wb = float(r.get("queue_side_wb", 0) or 0)

                    if q_main_nb > 0 or q_main_sb > 0 or q_side_eb > 0 or q_side_wb > 0:
                        # Use directional breakdown
                        if q_main_nb > 0:
                            sides["Main NB"] = q_main_nb
                        if q_main_sb > 0:
                            sides["Main SB"] = q_main_sb
                        if q_side_eb > 0:
                            sides["Cross EB"] = q_side_eb
                        if q_side_wb > 0:
                            sides["Cross WB"] = q_side_wb
                    else:
                        # Fall back to parsing queue_side_detail for older CSV files
                        qsd = str(r.get("queue_side_detail", "") or "")
                        for tok in qsd.split("|"):
                            tok = tok.strip()
                            if not tok:
                                continue
                            parts = tok.split(":")
                            if len(parts) == 3:          # dir:sec_id:n_veh  (new)
                                d, sid, nv = parts
                                key = d.strip() if d.strip() else f"sec{sid}"
                            elif len(parts) == 2:         # sec_id:n_veh  (legacy)
                                sid, nv = parts
                                key = f"sec{sid}"
                            else:
                                continue
                            try:
                                # Aggregate by direction key (sum vehicles)
                                sides[key] = sides.get(key, 0.0) + float(nv)
                            except ValueError:
                                pass

                    out.append({"t": t, "jct": jct, "main_dir": main_dir,
                                "main_veh": main_veh, "sides": sides})
                except Exception:
                    continue
    except Exception:
        pass
    return out


def _reward_cycle_csvs(log_dir: str) -> list:
  """Return reward_cycle CSV paths sorted by mtime (oldest first)."""
  return sorted(glob.glob(os.path.join(log_dir, "reward_cycle_*.csv")),
          key=os.path.getmtime)


def _match_reward_cycle_csv_by_name(exp_name: str, all_csvs: list) -> str:
  """Match reward_cycle_<EXPERIMENT>_<ts>.csv to this experiment."""
  exp_lower = (exp_name or "").strip().lower()
  if not exp_lower:
    return None
  for p in reversed(all_csvs):
    stem = os.path.splitext(os.path.basename(p))[0].lower()
    if not stem.startswith("reward_cycle_"):
      continue
    payload = stem[len("reward_cycle_"):]
    parts = payload.split("_")
    if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
      exp_token = "_".join(parts[:-2]).strip().lower()
      if exp_token == exp_lower:
        return p
  for p in reversed(all_csvs):
    stem = os.path.basename(p).lower()
    if exp_lower in stem:
      return p
  return None


def _reward_cycle_from_csv(path: str) -> list:
  """Load reward_cycle CSV into list of dicts."""
  if not path or not os.path.isfile(path):
    return []
  out = []
  try:
    with open(path, newline="", encoding="utf-8") as f:
      for r in csv.DictReader(f):
        try:
          out.append({
            "t": float(r.get("sim_time_s", 0) or 0),
            "jct": int(float(r.get("junction_id", -1) or -1)),
            "vid": int(float(r.get("veh_id", -1) or -1)),
            "bus_eta_s": float(r.get("bus_eta_s", 0) or 0),
            "current_phase": int(float(r.get("current_phase", -1) or -1)),
            "action": str(r.get("action", "") or ""),
            "reward": float(r.get("reward", 0) or 0),
            "bus_saved_pax_s": float(r.get("bus_saved_pax_s", 0) or 0),
            "other_inc_pax_s": float(r.get("other_inc_pax_s", 0) or 0),
            "side_inc_pax_s": float(r.get("side_inc_pax_s", 0) or 0),
            "density_inc_pax_s": float(r.get("density_inc_pax_s", 0) or 0),
            "throughput_gap_veh": float(r.get("throughput_gap_veh", 0) or 0),
            "throughput_infeasible": int(float(r.get("throughput_infeasible", 0) or 0)),
            "ge_inapplicable_cycle": int(float(r.get("ge_inapplicable_cycle", 0) or 0)),
            "is_chosen": int(float(r.get("is_chosen", 0) or 0)),
            "upflow_bus_vph": float(r.get("upflow_bus_vph", 0) or 0),
            "max_queue_bus_veh": float(r.get("max_queue_bus_veh", 0) or 0),
            "red_dur_bus_s": float(r.get("red_dur_bus_s", 0) or 0),
            # Signal timing columns (present in slim old-format CSVs)
            "sigma_in_s":  float(r.get("sigma_in_s",  0) or 0),
            "sigma_out_s": float(r.get("sigma_out_s", 0) or 0),
            # Raw actual reward and per-cycle delta (DCTSP-format CSVs)
            "reward_delta":     float(r.get("reward_delta",      r.get("reward", 0)) or 0),
            "no_action_reward": float(r.get("no_action_reward",  0) or 0),
            # Decomposed delay columns written by DCTSP_MARL reward writer
            "no_strategy_delay_pax_s": float(r.get("no_strategy_delay_pax_s",
                                                    r.get("delay_base_pax_s", 0)) or 0),
            "strategy_min_delay_pax_s": float(r.get("strategy_min_delay_pax_s",
                                                     r.get("delay_with_strategy_pax_s", 0)) or 0),
            # Cumulative Aimsun-measured car delay and kinematic no-action delay
            # used for MDN calibration: predicted vs actual intersection delay chart.
            "measured_car_pax_s_cumul": float(r.get("measured_car_pax_s_cumul", 0) or 0),
            "no_act_delay_s":          float(r.get("no_act_delay_s", 0) or 0),
            # Bus occupancy (pax) — used to decompose NA_total into bus/car portions
            "bus_occ": float(r.get("bus_occ", 20) or 20),
            # Delay validation columns (new; absent in older CSVs → default empty str)
            "dd1_delay_s": r.get("dd1_delay_s", ""),
            "mb_delay_s":  r.get("mb_delay_s",  ""),
            # Cross-traffic model predictions (pax·s).
            # other_delay_model_pax_s     — NF-amplified (used in reward decisions).
            # other_delay_model_pax_s_nf1 — raw triangle without NF (use for validation
            #   chart so the 45° line is meaningful; falls back to NF-divided value for
            #   older CSVs that don't have the nf1 column).
            "other_delay_model_pax_s":    float(r.get("other_delay_model_pax_s", 0) or 0),
            "network_factor":             float(r.get("network_factor", 1) or 1),
            # nf1 column: use explicit if present, else divide by network_factor
            "other_delay_model_pax_s_nf1": (
                float(r["other_delay_model_pax_s_nf1"])
                if r.get("other_delay_model_pax_s_nf1", "") not in ("", None)
                else float(r.get("other_delay_model_pax_s", 0) or 0)
                     / max(float(r.get("network_factor", 1) or 1), 1.0)
            ),
            # Per-event Aimsun-measured car delay delta and observation window (s)
            # (written by IC since v2025-05-27; older CSVs → 0).
            "measured_car_pax_s_delta": float(r.get("measured_car_pax_s_delta", 0) or 0),
            "interval_s":  float(r.get("interval_s",  0) or 0),
            "bp_dur_s":    float(r.get("bp_dur_s",    0) or 0),
          })
        except Exception:
          continue
  except Exception:
    pass
  return out


def _wave_events_from_csv(path: str) -> list:
  if not path or not os.path.isfile(path):
    return []
  out = []
  try:
    with open(path, newline="", encoding="utf-8") as f:
      for r in csv.DictReader(f):
        try:
          out.append({
            "t":          float(r.get("sim_time_s", "0") or 0.0),
            "event":      str(r.get("event", "")).strip(),
            "source_jct": int(float(r.get("source_jct", "-1") or -1)),
            "target_jct": int(float(r.get("target_jct", "-1") or -1)),
            "veh_id":     int(float(r.get("veh_id", "-1") or -1)),
            "note":       str(r.get("note", "") or ""),
          })
        except Exception:
          continue
  except Exception as e:
    print(f"[dashboard] wave-event read failed for {path}: {e}")
  return out


def _green_rates_from_csv(det_csv: str, allowed_vids: set | None = None) -> dict:
    """
    Load one detection CSV and return {jct_id_str: green_pct} for TSP buses.
    Returns {} if plot_green_wave is unavailable or CSV is missing.
    """
    if not det_csv or not os.path.isfile(det_csv):
        return {}
    if not HAS_GW:
      return _green_rates_from_csv_fallback(det_csv, allowed_vids)
    rows = _load_detections(det_csv)
    if not rows:
        return {}
    tsp_vids = set(_find_tsp_vehicles(rows))
    if allowed_vids:
        tsp_vids &= set(int(v) for v in allowed_vids if int(v) > 0)
    tsp_rows = [r for r in rows if r["vid"] in tsp_vids]
    stats: dict = {}
    for r in tsp_rows:
        jid = r["jct"]
        if jid not in stats:
            stats[jid] = {"g": 0, "r": 0}
        p = _phase_at_stopline(r)
        if p in ("green", "orange"):
            stats[jid]["g"] += 1
        else:
            stats[jid]["r"] += 1
    junctions_derived = _junctions_from_detections(rows)
    preferred = [j for j in ALL_CORRIDOR_JCTS if j in stats]
    extras = [j for j in stats.keys() if j not in set(preferred)]
    ordered = _geographic_junction_order(
      junctions_derived,
      preferred + extras if (preferred or extras) else list(stats.keys()))
    result = {}
    for jid in ordered:
        tot = stats.get(jid, {}).get("g", 0) + stats.get(jid, {}).get("r", 0)
        result[str(jid)] = round(
            100 * stats.get(jid, {}).get("g", 0) / tot, 1) if tot else 0.0
    return result


def _green_rates_from_csv_fallback(det_csv: str, allowed_vids: set | None = None) -> dict:
    """
    Lightweight fallback when plot_green_wave dependencies are unavailable.

    Uses detection_points CSV columns directly:
      - junction_id / jct
      - signal_phase
      - bus_phase

    A row is considered green if signal_phase == bus_phase.
    """
    try:
        with open(det_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception as e:
        print(f"[dashboard] fallback green-rate read failed for {det_csv}: {e}")
        return {}

    stats = {}
    for r in rows:
        if allowed_vids:
            try:
                _vid = int(float((r.get("veh_id") or r.get("vid") or "0")))
            except Exception:
                _vid = 0
            if _vid <= 0 or _vid not in allowed_vids:
                continue
        jid_raw = (r.get("junction_id") or r.get("jct") or "").strip()
        if not jid_raw:
            continue
        try:
            jid = str(int(float(jid_raw)))
        except Exception:
            jid = jid_raw

        try:
            sp = int(float((r.get("signal_phase") or "-1")))
            bp = int(float((r.get("bus_phase") or "-1")))
        except Exception:
            sp, bp = -1, -1

        if jid not in stats:
            stats[jid] = {"g": 0, "r": 0}
        if sp >= 0 and bp >= 0 and sp == bp:
            stats[jid]["g"] += 1
        else:
            stats[jid]["r"] += 1

    out = {}
    for jid in sorted(stats.keys(), key=lambda x: int(x) if str(x).lstrip("-").isdigit() else str(x)):
        tot = stats[jid]["g"] + stats[jid]["r"]
        out[str(jid)] = round(100.0 * stats[jid]["g"] / tot, 1) if tot else 0.0
    return out


# =============================================================================
# Build dashboard data
# =============================================================================

def _run_label(row: dict) -> str:
    """Human-readable run label from batch row."""
    exp   = (row.get("run_experiment", "") or "").upper()
    strat = (row.get("run_strategy",   "") or "").upper()
    seed  = row.get("run_seed", "")
    coord = str(row.get("run_coordinated", "")).lower() in ("true", "1", "yes")

    # Friendly display names keyed on experiment name first, then strategy
    _FRIENDLY = {
        "NO_TSP":           "No TSP",
        "NORMAL":           "No TSP",
        "HARMONY_INDEP":    "Phase-Based Uncoordinated",
        "HARMONY_COORD":    "Phase-Based Coordinated",
        "DYNAOPAC_HARMONY": "Discrete-Time Best-Action",
        "DYNAOPAC_COORD":   "Discrete-Time Best-Action",
        "DYNAOPAC_INDEP":   "Discrete-Time Best-Action (Indep)",
    }
    if exp in _FRIENDLY:
        label = _FRIENDLY[exp]
    elif strat == "NORMAL":
        label = "No TSP"
    elif strat == "HARMONY":
        label = "Phase-Based Coordinated" if coord else "Phase-Based Uncoordinated"
    elif strat in ("DYNAOPAC", "DYNAOPAC_HARMONY"):
        label = "Discrete-Time Best-Action"
    else:
        label = exp or strat or "Run"

    if seed not in (None, "", "0", 0):
        label += f" (s{seed})"
    return label


def _all_same(vals):
    """True if all non-None values are identical."""
    clean = [v for v in vals if v is not None]
    return len(clean) > 1 and len(set(round(v, 4) for v in clean)) == 1


def _all_zero(vals):
    clean = [v for v in vals if v is not None]
    return clean and all(abs(v) < 1e-9 for v in clean)


def _dedup_batch_rows(batch_rows: list) -> list:
    """
    Keep only the LAST (most recent) row per (experiment, seed) pair.

    batch_results.csv accumulates rows across multiple batch_runner sessions.
    Keying on (experiment, seed) means all seeds within the current batch are
    preserved (so the dashboard shows per-seed bars), while re-running the same
    experiment+seed combination replaces the old result with the newer one.
    """
    seen: dict = {}
    for row in batch_rows:
        exp  = row.get("run_experiment") or row.get("run_strategy", "UNKNOWN")
        seed = row.get("run_seed", "")
        seen[(exp, seed)] = row   # later rows overwrite earlier -> keep last per (exp, seed)
    return list(seen.values())


def _match_det_csv_by_name(exp_name: str, all_det_csvs: list) -> str:
    """
    Match a detection CSV to an experiment by looking for the experiment name
    in the filename.  Detection CSVs are now named:
        detection_points_<EXPERIMENT>_<timestamp>.csv
    Falls back to None if no match found.
    """
    exp_lower = (exp_name or "").strip().lower()
    if not exp_lower:
      return None

    # Search newest-first and require an exact experiment token match.
    # Filename format:
    #   detection_points_<EXPERIMENT>_<YYYYMMDD>_<HHMMSS>.csv
    for p in reversed(all_det_csvs):
      stem = os.path.splitext(os.path.basename(p))[0].lower()
      if not stem.startswith("detection_points_"):
        continue
      payload = stem[len("detection_points_"):]
      parts = payload.split("_")
      if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
        exp_token = "_".join(parts[:-2]).strip().lower()
        if exp_token == exp_lower:
          return p

    # Backward-compatible fallback for legacy names without the experiment token.
    for p in reversed(all_det_csvs):
      stem = os.path.basename(p).lower()
      if exp_lower in stem:
        return p
    return None



def _match_wave_csv_by_name(exp_name: str, all_wave_csvs: list) -> str:
    """Match corridor_wave_events_<EXPERIMENT>_<ts>.csv to this experiment."""
    exp_lower = (exp_name or "").strip().lower()
    if not exp_lower:
        return None

    for p in reversed(all_wave_csvs):
        stem = os.path.splitext(os.path.basename(p))[0].lower()
        if not stem.startswith("corridor_wave_events_"):
            continue
        payload = stem[len("corridor_wave_events_"):]
        parts = payload.split("_")
        if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
            exp_token = "_".join(parts[:-2]).strip().lower()
            if exp_token == exp_lower:
                return p

    for p in reversed(all_wave_csvs):
        stem = os.path.basename(p).lower()
        if exp_lower in stem:
            return p
    return None


def _match_bus_tracking_csv_by_name(exp_name: str, all_csvs: list) -> str:
    """Match bus_positions_<EXPERIMENT>_<ts>.csv to this experiment."""
    exp_lower = (exp_name or "").strip().lower()
    if not exp_lower:
        return None
    for p in reversed(all_csvs):
        stem = os.path.splitext(os.path.basename(p))[0].lower()
        if not stem.startswith("bus_positions_"):
            continue
        payload = stem[len("bus_positions_"):]
        parts = payload.split("_")
        if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
            exp_token = "_".join(parts[:-2]).strip().lower()
            if exp_token == exp_lower:
                return p
    for p in reversed(all_csvs):
        stem = os.path.basename(p).lower()
        if exp_lower in stem:
            return p
    return None


def _bus_tracking_from_csv(path: str) -> list:
    """Load bus_positions CSV into list of dicts with typed values."""
    if not path or not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    _vid = int(float(r.get("veh_id", 0) or 0))
                except Exception:
                    _vid = 0
                try:
                    _jct = int(float(r.get("nearest_jct", 0) or 0))
                except Exception:
                    _jct = 0
                try:
                    _inz = int(float(r.get("in_zone", 0) or 0))
                except Exception:
                    _inz = 0
                out.append({
                    "t":    float(r.get("sim_time_s", 0)),
                    "vid":  _vid,
                    "x":    float(r.get("x", 0)),
                    "y":    float(r.get("y", 0)),
                    "jct":  _jct,
                    "dist": float(r.get("dist_m", 0)),
                    "in_zone": _inz,
                    "zone_r":  float(r.get("zone_radius_m", 0)),
                    "event": r.get("event", "track"),
                })
    except Exception:
        pass
    return out


def _detection_junction_stats_from_csv(det_csv: str) -> dict:
    """Summarise detector-based bus coverage per junction."""
    if not det_csv or not os.path.isfile(det_csv):
        return {}

    # Use the project intersection config as the canonical filter.
    # ALL_CORRIDOR_JCTS comes from plot_green_wave and can refer to a different
    # corridor definition, which can zero-out detected_buses in the dashboard.
    allowed_jcts = (
        set(int(j) for j in _ALL_CONFIG_JCTS)
        if _ALL_CONFIG_JCTS else None
    )
    stats: dict = {}
    try:
        with open(det_csv, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                vid = _intish(r.get("veh_id", -1), -1)
                jct = _intish(r.get("junction_id", -1), -1)
                if vid <= 0 or jct <= 0:
                    continue
                if allowed_jcts is not None and jct not in allowed_jcts:
                    continue
                key = str(jct)
                rec = stats.setdefault(key, {
                    "_bus_ids": set(),
                    "_pairs": set(),
                    "_green_pairs": set(),
                })
                pair = (vid, jct)
                rec["_bus_ids"].add(vid)
                rec["_pairs"].add(pair)
                sig = _intish(r.get("signal_phase", -1), -1)
                bus = _intish(r.get("bus_phase", -1), -1)
                if sig >= 0 and bus >= 0 and sig == bus:
                    rec["_green_pairs"].add(pair)
    except Exception:
        return {}

    out = {}
    for jct, rec in stats.items():
        out[jct] = {
            "_bus_ids": set(rec["_bus_ids"]),
            "detected_buses": len(rec["_bus_ids"]),
            "detected_pairs": len(rec["_pairs"]),
            "green_detected_pairs": len(rec["_green_pairs"]),
        }
    return out


def _bus_tracking_summary(rows: list) -> dict:
    """Summarise continuous bus-position coverage corridor-wide and by junction."""
    if not rows:
        return {
            "tracked_bus_count": 0,
            "tracked_jct_count": 0,
            "tracked_samples": 0,
            "tracked_zone_entries": 0,
            "tracked_zone_exits": 0,
            "tracked_nearest_changes": 0,
            "per_jct": {},
        }

    allowed_jcts = (
        set(int(j) for j in ALL_CORRIDOR_JCTS)
        if HAS_GW and ALL_CORRIDOR_JCTS else None
    )
    tracked_bus_ids = set()
    per_jct: dict = {}
    tracked_samples = 0
    tracked_zone_entries = 0
    tracked_zone_exits = 0
    tracked_nearest_changes = 0

    for row in rows:
        vid = _intish(row.get("vid", row.get("veh_id", -1)), -1)
        jct = _intish(row.get("jct", row.get("nearest_jct", -1)), -1)
        event = str(row.get("event", "track") or "track").strip()
        if vid > 0:
            tracked_bus_ids.add(vid)
        if jct <= 0:
            continue
        if allowed_jcts is not None and jct not in allowed_jcts:
            continue

        key = str(jct)
        rec = per_jct.setdefault(key, {
            "_bus_ids": set(),   # buses that entered the zone (≤ zone_radius_m)
            "tracked_samples": 0,
            "zone_entries": 0,
            "zone_exits": 0,
            "nearest_changes": 0,
            "enter_events": 0,
        })

        # Only mark a bus as "tracked at this junction" when it actually entered
        # the detection zone.  Pure "track" rows just mean the bus's nearest
        # junction is this one at some point — that includes buses on parallel
        # roads >1 km away that should never count in the coverage denominator.
        in_zone = str(row.get("in_zone", "0") or "0").strip()
        if vid > 0 and (event in ("zone_enter", "zone_exit") or in_zone == "1"):
            rec["_bus_ids"].add(vid)

        if event == "track":
            tracked_samples += 1
            rec["tracked_samples"] += 1
        elif event == "zone_enter":
            tracked_zone_entries += 1
            rec["zone_entries"] += 1
        elif event == "zone_exit":
            tracked_zone_exits += 1
            rec["zone_exits"] += 1
        elif event == "nearest_jct_change":
            tracked_nearest_changes += 1
            rec["nearest_changes"] += 1
        elif event == "enter_system":
            rec["enter_events"] += 1

    out_per_jct = {}
    for jct, rec in per_jct.items():
        out_per_jct[jct] = {
            "_bus_ids": set(rec["_bus_ids"]),
            "tracked_buses": len(rec["_bus_ids"]),
            "tracked_samples": rec["tracked_samples"],
            "zone_entries": rec["zone_entries"],
            "zone_exits": rec["zone_exits"],
            "nearest_changes": rec["nearest_changes"],
            "enter_events": rec["enter_events"],
        }

    return {
        "_bus_ids": set(tracked_bus_ids),
        "tracked_bus_count": len(tracked_bus_ids),
        "tracked_jct_count": len(out_per_jct),
        "tracked_samples": tracked_samples,
        "tracked_zone_entries": tracked_zone_entries,
        "tracked_zone_exits": tracked_zone_exits,
        "tracked_nearest_changes": tracked_nearest_changes,
        "per_jct": out_per_jct,
    }


def _focus_history_csvs(log_dir: str = "logs") -> list:
    """Return focus_history CSV paths sorted by mtime (oldest first)."""
    return sorted(glob.glob(os.path.join(log_dir, "focus_history_*.csv")),
                  key=os.path.getmtime)


def _queue_snapshot_csvs(log_dir: str = "logs") -> list:
    """Return queue_snapshot CSV paths sorted by mtime (oldest first)."""
    return sorted(glob.glob(os.path.join(log_dir, "queue_snapshot_*.csv")),
                  key=os.path.getmtime)


def _match_queue_snapshot_csv_by_name(exp_name: str, all_csvs: list) -> str:
    """Match queue_snapshot_<EXPERIMENT>_<ts>.csv to this experiment."""
    exp_lower = (exp_name or "").strip().lower()
    if not exp_lower:
        return None
    for p in reversed(all_csvs):
        stem = os.path.splitext(os.path.basename(p))[0].lower()
        if not stem.startswith("queue_snapshot_"):
            continue
        payload = stem[len("queue_snapshot_"):]
        parts = payload.split("_")
        if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
            exp_token = "_".join(parts[:-2]).strip().lower()
            if exp_token == exp_lower:
                return p
    for p in reversed(all_csvs):
        stem = os.path.basename(p).lower()
        if exp_lower in stem and "queue_snapshot" in stem:
            return p
    return None


def _dynaropac_csvs(log_dir: str) -> list:
    """Return dynaropac_decisions CSV paths sorted by mtime."""
    return sorted(glob.glob(os.path.join(log_dir, "dynaropac_decisions_*.csv")),
                  key=os.path.getmtime)


def _match_dynaropac_csv_by_name(exp_name: str, all_csvs: list) -> str:
    exp_lower = (exp_name or "").strip().lower()
    if not exp_lower:
        return None
    for p in reversed(all_csvs):
        stem = os.path.splitext(os.path.basename(p))[0].lower()
        if not stem.startswith("dynaropac_decisions_"):
            continue
        payload = stem[len("dynaropac_decisions_"):]
        parts = payload.split("_")
        if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
            exp_token = "_".join(parts[:-2]).strip().lower()
            if exp_token == exp_lower:
                return p
    return None


def _dynaropac_decisions_from_csv(path: str) -> list:
    """Load dynaropac_decisions CSV. Returns list of decision rows."""
    if not path or not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    # Parse string-encoded lists back
                    _ext_raw   = r.get("extensions_s", "[]")
                    _delay_raw = r.get("delays_paxs", "[]")
                    import ast
                    extensions = ast.literal_eval(_ext_raw)
                    delays     = ast.literal_eval(_delay_raw)
                    out.append({
                        "t":              float(r.get("sim_time_s", 0) or 0),
                        "jct":            int(float(r.get("junction_id", 0) or 0)),
                        "cur_phase":      int(float(r.get("cur_phase", 1) or 1)),
                        "before_dur":     float(r.get("before_dur_s", 0) or 0),
                        "extensions":     extensions,
                        "delays":         delays,
                        "best_ext":       float(r.get("best_ext_s", 0) or 0),
                        "best_delay":     float(r.get("best_delay", 0) or 0),
                        "baseline_delay": float(r.get("baseline_delay", 0) or 0),
                        "saving":         float(r.get("saving_paxs", 0) or 0),
                        "bus_detected":   int(float(r.get("bus_detected", 0) or 0)),
                        "applied":        int(float(r.get("applied", 0) or 0)),
                    })
                except Exception:
                    continue
    except Exception:
        pass
    return out


def _queue_snapshot_from_csv(path: str) -> list:
    """Load queue_snapshot CSV into list of dicts."""
    if not path or not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    out.append({
                        "t":            float(r.get("sim_time_s", 0) or 0),
                        "jct":          int(float(r.get("junction_id", 0) or 0)),
                        "buses_in_zone": int(float(r.get("buses_in_zone", 0) or 0)),
                        "queue_main":   int(float(r.get("queue_main", 0) or 0)),
                        "queue_side":   int(float(r.get("queue_side", 0) or 0)),
                        "queue_total":  int(float(r.get("queue_total", 0) or 0)),
                        "tsp_state":    str(r.get("tsp_state", "NORMAL") or "NORMAL"),
                        "phase":        int(float(r.get("current_phase", -1) or -1)),
                        "corridor_bus_count": int(float(r.get("corridor_bus_count", 0) or 0)),
                        "delay_total_s": float(r.get("delay_total_s", 0) or 0),
                        "delay_bus_s":   float(r.get("delay_bus_s",   0) or 0),
                        "delay_car_s":   float(r.get("delay_car_s",   0) or 0),
                        "sw_q_main":    float(r.get("sw_q_main",    0) or 0),
                        "sw_q_side":    float(r.get("sw_q_side",    0) or 0),
                        "sw_flow_main": float(r.get("sw_flow_main", 0) or 0),
                        "sw_density_main": float(r.get("sw_density_main", 0) or 0),
                        "sw_red_s":     float(r.get("sw_red_s",     0) or 0),
                        "sw_flow_side": float(r.get("sw_flow_side", 0) or 0),
                        "sw_strat_main": str(r.get("sw_strat_main", "") or ""),
                        "sw_strat_side": str(r.get("sw_strat_side", "") or ""),
                    })
                except Exception:
                    continue
    except Exception:
        pass
    return out


def _load_junction_centroids(log_dir: str = "logs") -> dict:
    """
    Load junction_centroids_*.csv files (written by AAPIFinish) to get
    accurate model-coordinate positions for each junction.

    Returns dict: str(junction_id) → {"x": float, "y": float}
    """
    csvs = sorted(glob.glob(os.path.join(log_dir, "junction_centroids_*.csv")),
                  key=os.path.getmtime)
    if not csvs:
        return {}
    out = {}
    try:
        with open(csvs[-1], newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    jid = str(_intish(r.get("junction_id", 0), 0))
                    if jid == "0":
                        continue
                    x = float(r.get("x") or 0)
                    y = float(r.get("y") or 0)
                    if x == 0 and y == 0:
                        continue
                    out[jid] = {"x": round(x, 1), "y": round(y, 1)}
                except Exception:
                    continue
    except Exception:
        pass
    return out


def _match_focus_csv_by_name(exp_name: str, all_csvs: list) -> str:
    """Match focus_history_<EXPERIMENT>_<ts>.csv to this experiment."""
    exp_lower = (exp_name or "").strip().lower()
    if not exp_lower:
        return None
    for p in reversed(all_csvs):
        stem = os.path.splitext(os.path.basename(p))[0].lower()
        if not stem.startswith("focus_history_"):
            continue
        payload = stem[len("focus_history_"):]
        parts = payload.split("_")
        if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
            exp_token = "_".join(parts[:-2]).strip().lower()
            if exp_token == exp_lower:
                return p
    for p in reversed(all_csvs):
        stem = os.path.basename(p).lower()
        if exp_lower in stem:
            return p
    return None


def _focus_history_from_csv(path: str) -> list:
    """Load focus_history CSV into list of dicts."""
    if not path or not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    _vid = int(float(r.get("veh_id", 0) or 0))
                except Exception:
                    _vid = 0
                try:
                    _jid = int(float(r.get("jct_id", 0) or 0))
                except Exception:
                    _jid = 0
                out.append({
                    "start_t": float(r.get("start_t", 0)),
                    "end_t":   float(r.get("end_t", 0)),
                    "veh_id":  _vid,
                    "jct_id":  _jid,
                    "outcome": r.get("outcome", ""),
                    "held_s":  float(r.get("held_s", 0)),
                })
    except Exception:
        pass
    return out


def _focus_junction_summary(rows: list) -> dict:
    """Summarise focus-bus events by junction."""
    if not rows:
        return {"focus_bus_count": 0, "per_jct": {}}

    # Use the project's own junction config (not the green-wave corridor list,
    # which may belong to a different network, e.g. Logan Road vs KG).
    allowed_jcts = (
        set(int(j) for j in _ALL_CONFIG_JCTS)
        if _ALL_CONFIG_JCTS else None
    )
    focus_bus_ids = set()
    per_jct: dict = {}
    for row in rows:
        vid = _intish(row.get("veh_id", -1), -1)
        jct = _intish(row.get("jct_id", -1), -1)
        if vid > 0:
            focus_bus_ids.add(vid)
        if jct <= 0:
            continue
        if allowed_jcts is not None and jct not in allowed_jcts:
            continue
        rec = per_jct.setdefault(str(jct), {"_bus_ids": set(), "focus_events": 0})
        if vid > 0:
            rec["_bus_ids"].add(vid)
        rec["focus_events"] += 1

    out_per_jct = {}
    for jct, rec in per_jct.items():
        out_per_jct[jct] = {
            "_bus_ids": set(rec["_bus_ids"]),
            "focus_buses": len(rec["_bus_ids"]),
            "focus_events": rec["focus_events"],
        }

    return {
        "_bus_ids": set(focus_bus_ids),
        "focus_bus_count": len(focus_bus_ids),
        "per_jct": out_per_jct,
    }


def _latest_rows_by_intersection(rows: list) -> list:
    """Keep only the latest row per IntersectionID from an append-only CSV."""
    latest = {}
    for r in rows:
        iid = str(r.get("IntersectionID", "")).strip()
        if not iid:
            continue
        latest[iid] = r
    return list(latest.values())


def _merge_per_intersection_coverage(per_inter: list,
                                     det_stats: dict,
                                     track_summary: dict,
                                     focus_summary: dict) -> list:
    """Merge detector/tracking/focus bus coverage into per-junction rows."""
    row_map = {}
    for row in per_inter or []:
        iid = str(row.get("iid", "")).strip()
        if iid:
            row_map[iid] = dict(row)

    all_iids = set(row_map.keys())
    all_iids.update(det_stats.keys())
    all_iids.update((track_summary or {}).get("per_jct", {}).keys())
    all_iids.update((focus_summary or {}).get("per_jct", {}).keys())
    if _ALL_CONFIG_JCTS:
        all_iids.update(str(j) for j in _ALL_CONFIG_JCTS)

    for iid in all_iids:
        row = row_map.setdefault(iid, {"iid": iid})
        det = det_stats.get(iid, {})
        track = (track_summary or {}).get("per_jct", {}).get(iid, {})
        focus = (focus_summary or {}).get("per_jct", {}).get(iid, {})
        det_ids = set(det.get("_bus_ids", set()) or set())
        track_ids = set(track.get("_bus_ids", set()) or set())
        focus_ids = set(focus.get("_bus_ids", set()) or set())
        known_ids = det_ids | track_ids | focus_ids
        position_tracked_buses = (
            len(track_ids)
            if track_ids else int(track.get("tracked_buses", 0) or 0)
        )
        detected_buses = (
            len(det_ids)
            if det_ids else int(det.get("detected_buses", 0) or 0)
        )
        focus_buses = (
            len(focus_ids)
            if focus_ids else int(focus.get("focus_buses", 0) or 0)
        )
        tracked_buses = (
            len(known_ids)
            if known_ids else max(position_tracked_buses, detected_buses, focus_buses)
        )
        row.update({
            "tracked_buses": tracked_buses,
            "position_tracked_buses": position_tracked_buses,
            "tracked_samples": int(track.get("tracked_samples", 0) or 0),
            "zone_entries": int(track.get("zone_entries", 0) or 0),
            "zone_exits": int(track.get("zone_exits", 0) or 0),
            "nearest_changes": int(track.get("nearest_changes", 0) or 0),
            "detected_buses": detected_buses,
            "detected_pairs": int(det.get("detected_pairs", 0) or 0),
            "green_detected_pairs": int(det.get("green_detected_pairs", 0) or 0),
            "focus_buses": focus_buses,
            "focus_events": int(focus.get("focus_events", 0) or 0),
            "tracked_only_buses": (
                len(known_ids - det_ids)
                if known_ids else max(tracked_buses - detected_buses, 0)
            ),
            "coverage_pct": (
                round(100.0 * detected_buses / tracked_buses, 1)
                if tracked_buses > 0 else None
            ),
        })

    def _iid_sort_key(v):
        try:
            return (0, int(float(str(v))))
        except Exception:
            return (1, str(v))

    def _valid_merge_iid(v):
        try:
            jid = int(float(str(v)))
            return not (12000 <= jid <= 21999)
        except Exception:
            return True

    # If we know the KG config junctions, restrict to those only
    if _ALL_CONFIG_JCTS:
        _cfg_set = set(str(j) for j in _ALL_CONFIG_JCTS)
        filtered = {k: v for k, v in row_map.items() if k in _cfg_set}
    else:
        filtered = {k: v for k, v in row_map.items() if _valid_merge_iid(k)}

    return sorted(filtered.values(), key=lambda x: _iid_sort_key(x.get("iid", "")))


def _latest_rows_by_section(rows: list) -> list:
    """Keep only the latest row per SectionID from an append-only CSV."""
    latest = {}
    for r in rows:
        sid = str(r.get("SectionID", "")).strip()
        if not sid:
            continue
        latest[sid] = r
    return list(latest.values())


def _load_per_intersection_data(batch_row: dict, log_dir: str) -> list:
    """
    Load per-intersection rows for one batch run.

    Looks for the results folder path stored in batch_row["stats_results_folder"],
    then reads simulation_results_per_intersection.csv from that folder.

    Filters to the current run using ScenarioID/ExperimentID/ReplicationID when
    available; falls back to strategy name match.

    Returns a list of dicts, one per intersection, with the key metrics.
    Returns [] when the CSV cannot be found or loaded.
    """
    results_folder = batch_row.get("stats_results_folder", "")
    if not results_folder or not os.path.isdir(results_folder):
        # Try to discover it from log_dir using the strategy/seed pattern
        strategy = batch_row.get("run_strategy", "")
        seed     = batch_row.get("run_seed", "0")
        if strategy and log_dir:
            results_base = os.path.join(os.path.dirname(log_dir), "results")
            prefix = f"{strategy}_seed{seed}"
            try:
                candidates = [
                    d for d in os.scandir(results_base)
                    if d.is_dir() and d.name.startswith(prefix)
                ] if os.path.isdir(results_base) else []
                if candidates:
                    results_folder = max(candidates, key=lambda d: d.stat().st_mtime).path
            except Exception:
                pass

    if not results_folder:
        return []

    inter_csv = os.path.join(results_folder, "simulation_results_per_intersection.csv")
    if not os.path.isfile(inter_csv):
        # ── Fallback: build per-intersection rows from section_stats.csv ──────
        # section_stats.csv is always written by save_results() and has per-section
        # density/speed/flow/queue.  Aggregate sections by IntersectionID.
        sec_csv = os.path.join(results_folder, "section_stats.csv")
        if not os.path.isfile(sec_csv):
            return []
        try:
            with open(sec_csv, newline="", encoding="utf-8") as _sf:
                all_sec_rows = list(csv.DictReader(_sf))
        except Exception:
            return []
        if not all_sec_rows:
            return []
        # De-duplicate: section_stats.csv is append-only across runs.
        # Keep the LAST row per SectionID (last written = most recent run).
        _last_by_sid = {}
        for _r in all_sec_rows:
            _sid = str(_r.get("SectionID", "") or "")
            if _sid:
                _last_by_sid[_sid] = _r   # always overwrite → keeps last
        sec_rows = list(_last_by_sid.values()) if _last_by_sid else []
        if not sec_rows:
            return []
        # Aggregate by intersection: length-weighted density/speed/flow; sum queue
        _agg = {}
        for _r in sec_rows:
            _iid = str(_r.get("IntersectionID", "")).strip()
            if not _iid or _iid == "0":
                continue
            _l = float(_r.get("Length_km", 0) or 0)
            _d = float(_r.get("AvgDensity_vkm", 0) or 0)
            _s = float(_r.get("AvgSpeed_kmh", 0) or 0)
            _fl = float(_r.get("AvgFlow_veh_h", 0) or 0)
            _q  = float(_r.get("AvgQueue_veh", 0) or 0)
            if _iid not in _agg:
                _agg[_iid] = {"wt_len":0.0,"wt_d":0.0,"wt_s":0.0,"wt_fl":0.0,"q":0.0,"n":0}
            a = _agg[_iid]
            if _l > 0:
                a["wt_len"] += _l; a["wt_d"] += _d*_l
                a["wt_s"]  += _s*_l; a["wt_fl"] += _fl*_l
                a["q"] += _q; a["n"] += 1
        result_fallback = []
        for _iid, a in _agg.items():
            _tl = max(a["wt_len"], 1e-9)
            result_fallback.append({
                "iid": _iid,
                "distinct_buses": None, "distinct_cars": None, "distinct_trucks": None,
                "bus_passages": None, "car_passages": None, "truck_passages": None,
                "pax_equiv": None, "bus_pax_equiv": None,
                "car_pax_equiv": None, "truck_pax_equiv": None,
                "total_delay": None, "main_delay": None, "side_delay": None,
                "bus_tt": None, "avg_bus_delay": None, "avg_car_delay": None,
                "avg_truck_delay": None,
                "avg_main_delay_per_hr": None, "avg_side_delay_per_hr": None,
                "avg_total_delay_per_hr": None, "sim_duration_hrs": None,
                "tsp_det": None, "tsp_ext": None, "tsp_ins": None,
                "tsp_natural_green": None, "tsp_skip_ge": None,
                "tsp_skip_ins": None, "tsp_no_action": None,
                "avg_extension_s": None, "avg_insertion_s": None,
                "avg_insertion_wait_s": None,
                "avg_density": round(a["wt_d"] / _tl, 4),
                "avg_speed":   round(a["wt_s"] / _tl, 3),
                "avg_flow":    round(a["wt_fl"] / _tl, 2),
                "avg_queue":   round(a["q"] / max(a["n"], 1), 2),
            })
        if result_fallback:
            print(f"[dashboard] per-intersection: loaded {len(result_fallback)} junctions from section_stats.csv (fallback)")
        return result_fallback

    try:
        with open(inter_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return []

    if not rows:
        return []

    # Filter to this run only
    # Try ScenarioID/ExperimentID/ReplicationID from the global CSV row first
    _scen = str(batch_row.get("stats_ScenarioID", "")).strip()
    _exp  = str(batch_row.get("stats_ExperimentID", "")).strip()
    _rep  = str(batch_row.get("stats_ReplicationID", "")).strip()
    strategy = batch_row.get("run_strategy", "")
    exp_name = batch_row.get("run_experiment", "")

    if _scen and _exp and _rep:
        run_rows = [
            r for r in rows
            if str(r.get("ScenarioID", "")).strip()  == _scen
            and str(r.get("ExperimentID", "")).strip() == _exp
            and str(r.get("ReplicationID", "")).strip() == _rep
        ]
    else:
        run_rows = [r for r in rows if r.get("TSP_Strategy", "") == strategy]

    if not run_rows:
      # Fallback 1: strategy rows, if IDs were unavailable/mismatched
      run_rows = [r for r in rows if r.get("TSP_Strategy", "") == strategy]

    if not run_rows:
      # Fallback 2: newest rows from tail of file
      run_rows = rows[-18:] if len(rows) >= 18 else rows

    # CSV is append-only over repeated runs. Keep latest value per intersection.
    run_rows = _latest_rows_by_intersection(run_rows)

    if not run_rows:
      print(f"[dashboard] per-intersection: no rows resolved for exp={exp_name} strategy={strategy}")
      return []

    result = []
    for r in run_rows:
        iid = r.get("IntersectionID", "?")
        result.append({
            "iid":           iid,
            "distinct_buses": _flt(r.get("N_DistinctBuses")),
            "distinct_cars":  _flt(r.get("N_DistinctCars")),
            "distinct_trucks": _flt(r.get("N_DistinctTrucks")),
            "bus_passages":  _flt(r.get("BusVehPassages")),
            "car_passages":  _flt(r.get("CarVehPassages")),
            "truck_passages": _flt(r.get("TruckVehPassages")),
            "pax_equiv":     _flt(r.get("PaxEquivPassages")),
            "bus_pax_equiv": _flt(r.get("BusPaxEquivPassages")),
            "car_pax_equiv": _flt(r.get("CarPaxEquivPassages")),
            "truck_pax_equiv": _flt(r.get("TruckPaxEquivPassages")),
            "total_delay":   _flt(r.get("TotalPassDelay_hrs")),
            "main_delay":    _flt(r.get("MainPassDelay_hrs")),
            "side_delay":    _flt(r.get("SidePassDelay_hrs")),
            "bus_tt":        _flt(r.get("BusTotalTT_hrs")),
            "avg_bus_delay": _flt(r.get("AvgBusPassDelay_s")),
            "avg_car_delay": _flt(r.get("AvgCarPassDelay_s")),
            "avg_truck_delay": _flt(r.get("AvgTruckPassDelay_s")),
            "avg_main_delay_per_hr": _flt(r.get("AvgMainPassDelay_pax_h_per_sim_h")),
            "avg_side_delay_per_hr": _flt(r.get("AvgSidePassDelay_pax_h_per_sim_h")),
            "avg_total_delay_per_hr": _flt(r.get("AvgTotalPassDelay_pax_h_per_sim_h")),
            "sim_duration_hrs": _flt(r.get("SimDuration_hrs")),
            "tsp_det":       _flt(r.get("TSP_Detections")),
            "tsp_ext":       _flt(r.get("TSP_Extensions")),
            "tsp_ins":       _flt(r.get("TSP_Insertions")),
            "tsp_natural_green": _flt(r.get("TSP_NaturalGreen")),
            "tsp_skip_ge":   _flt(r.get("TSP_Skipped_GE")),
            "tsp_skip_ins":  _flt(r.get("TSP_Skipped_Ins")),
            "tsp_no_action": _flt(r.get("TSP_Detected_NoAction")),
            "avg_extension_s": _flt(r.get("TSP_AvgExtension_s")),
            "avg_insertion_s": _flt(r.get("TSP_AvgInsertion_s")),
            "avg_insertion_wait_s": _flt(r.get("TSP_AvgInsertionWait_s")),
            "avg_density": _flt(r.get("AvgDensity_vkm")),
            "avg_speed":   _flt(r.get("AvgSpeed_kmh")),
            "avg_flow":    _flt(r.get("AvgFlow_veh_h")),
            "avg_queue":   _flt(r.get("AvgQueue_veh")),
        })

    def _iid_sort_key(v):
        try:
            return (0, int(float(str(v))))
        except Exception:
            return (1, str(v))

    # Exclude junction IDs that belong to other networks (e.g. Logan Road
    # junctions 17249–21895 which share this results folder via legacy data).
    # Junctions in the 12000–21999 range are not part of the KG network.
    def _valid_iid(v):
        try:
            jid = int(float(str(v)))
            return not (12000 <= jid <= 21999)
        except Exception:
            return True   # keep non-numeric IDs

    if _ALL_CONFIG_JCTS:
        _cfg_int_set = set(int(j) for j in _ALL_CONFIG_JCTS if str(j).lstrip("-").isdigit())
        result = [
            row for row in result
            if _valid_iid(row.get("iid", ""))
            and (not _cfg_int_set or _intish(row.get("iid", -1), -1) in _cfg_int_set)
        ]
    else:
        result = [row for row in result if _valid_iid(row.get("iid", ""))]

    result = sorted(result, key=lambda x: _iid_sort_key(x.get("iid", "")))

    return result


def _load_per_section_data(batch_row: dict, log_dir: str) -> list:
    """Load per-section density/speed/flow from section_stats.csv."""
    results_folder = batch_row.get("stats_results_folder", "")
    if not results_folder or not os.path.isdir(results_folder):
        strategy = batch_row.get("run_strategy", "")
        seed     = batch_row.get("run_seed", "0")
        if strategy and log_dir:
            results_base = os.path.join(os.path.dirname(log_dir), "results")
            prefix = f"{strategy}_seed{seed}"
            try:
                candidates = [
                    d for d in os.scandir(results_base)
                    if d.is_dir() and d.name.startswith(prefix)
                ] if os.path.isdir(results_base) else []
                if candidates:
                    results_folder = max(candidates, key=lambda d: d.stat().st_mtime).path
            except Exception:
                pass
    if not results_folder:
        return []

    sec_csv = os.path.join(results_folder, "section_stats.csv")
    if not os.path.isfile(sec_csv):
        return []

    try:
        with open(sec_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return []

    if not rows:
        return []

    # Filter to this run
    _scen = str(batch_row.get("stats_ScenarioID", "")).strip()
    _exp  = str(batch_row.get("stats_ExperimentID", "")).strip()
    _rep  = str(batch_row.get("stats_ReplicationID", "")).strip()
    strategy = batch_row.get("run_strategy", "")

    if _scen and _exp and _rep:
        run_rows = [
            r for r in rows
            if str(r.get("ScenarioID", "")).strip() == _scen
            and str(r.get("ExperimentID", "")).strip() == _exp
            and str(r.get("ReplicationID", "")).strip() == _rep
        ]
    else:
        run_rows = [r for r in rows if r.get("TSP_Strategy", "") == strategy]

    if not run_rows:
        run_rows = [r for r in rows if r.get("TSP_Strategy", "") == strategy]
    if not run_rows:
        run_rows = rows

    run_rows = _latest_rows_by_section(run_rows)

    result = []
    for r in run_rows:
        try:
            _is_main = int(float(r.get("IsMain", 0) or 0))
        except Exception:
            _is_main = 0
        try:
            _samples = int(float(r.get("N_Samples", 0) or 0))
        except Exception:
            _samples = 0
        result.append({
            "sec_id":   r.get("SectionID", "?"),
            "iid":      r.get("IntersectionID", "?"),
            "is_main":  _is_main,
            "length_km": _flt(r.get("Length_km")),
            "density":  _flt(r.get("AvgDensity_vkm")),
            "speed":    _flt(r.get("AvgSpeed_kmh")),
            "flow":     _flt(r.get("AvgFlow_veh_h")),
            "queue":    _flt(r.get("AvgQueue_veh")),
            "samples":  _samples,
        })

    def _safe_intish(v, default=0):
        try:
            return int(float(str(v)))
        except Exception:
            return default

    result = sorted(
        result,
        key=lambda x: (
            _safe_intish(x.get("iid", 0), 0),
            -_safe_intish(x.get("is_main", 0), 0),
            _safe_intish(x.get("sec_id", 0), 0),
        ),
    )

    return result


def _weighted_section_metric(per_section: list, key: str):
    """Length-weighted fallback for global network metrics from section_stats.csv."""
    if not per_section:
        return None
    num = 0.0
    den = 0.0
    for row in per_section:
        v = _flt(row.get(key))
        if v is None or not math.isfinite(v):
            continue
        w = _flt(row.get("length_km"), 1.0)
        if w is None or w <= 0.0:
            w = 1.0
        num += v * w
        den += w
    if den <= 0.0:
        return None
    return num / den


def _signal_plan_rows() -> list:
    """Nominal main-vs-side timing bars used by the dashboard comparison."""
    out = []
    for jid, cfg in sorted(_IC.items(), key=lambda kv: int(kv[0]) if str(kv[0]).lstrip("-").isdigit() else str(kv[0])):
        try:
            cycle = float(cfg.get("CycleTime", cfg.get("cycle_length", 0.0)) or 0.0)
            main_green = float(cfg.get("BusPhaseDuration", 0.0) or 0.0)
            if main_green <= 0.0:
                phase_durs = cfg.get("PhaseDurationList") or cfg.get("phase_durations") or []
                bus_phase = int(float(cfg.get("BusPhase", 1) or 1))
                if phase_durs and 0 <= bus_phase - 1 < len(phase_durs):
                    main_green = float(phase_durs[bus_phase - 1] or 0.0)
            if cycle <= 0.0:
                phase_durs = cfg.get("PhaseDurationList") or cfg.get("phase_durations") or []
                cycle = sum(float(x or 0.0) for x in phase_durs)
            if cycle <= 0.0:
                cycle = 135.0
            main_green = max(0.0, min(main_green or 0.0, cycle))
            side_green = max(cycle - main_green, 0.0)
            out.append({
                "jct": str(jid),
                "cycle_s": round(cycle, 1),
                "main_green_s": round(main_green, 1),
                "main_red_s": round(side_green, 1),
                "side_green_s": round(side_green, 1),
                "side_red_s": round(main_green, 1),
                "bus_phase": int(float(cfg.get("BusPhase", 0) or 0)),
            })
        except Exception:
            continue
    return out


def _load_simulation_results_row(batch_row: dict, log_dir: str) -> dict:
    """Load the single-row simulation_results.csv record for this run, if present."""
    results_folder = batch_row.get("stats_results_folder", "")
    if not results_folder or not os.path.isdir(results_folder):
        strategy = batch_row.get("run_strategy", "")
        seed = batch_row.get("run_seed", "0")
        if strategy and log_dir:
            results_base = os.path.join(os.path.dirname(log_dir), "results")
            prefix = f"{strategy}_seed{seed}"
            try:
                candidates = [
                    d for d in os.scandir(results_base)
                    if d.is_dir() and d.name.startswith(prefix)
                ] if os.path.isdir(results_base) else []
                if candidates:
                    results_folder = max(candidates, key=lambda d: d.stat().st_mtime).path
            except Exception:
                pass
    if not results_folder:
        return {}

    sim_csv = os.path.join(results_folder, "simulation_results.csv")
    if not os.path.isfile(sim_csv):
        return {}

    try:
        with open(sim_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return {}

    if not rows:
        return {}

    scen = str(batch_row.get("stats_ScenarioID", "")).strip()
    exp = str(batch_row.get("stats_ExperimentID", "")).strip()
    rep = str(batch_row.get("stats_ReplicationID", "")).strip()
    strategy = str(batch_row.get("run_strategy", "")).strip()

    for r in rows:
        if scen and exp and rep:
            if (
                str(r.get("ScenarioID", "")).strip() == scen
                and str(r.get("ExperimentID", "")).strip() == exp
                and str(r.get("ReplicationID", "")).strip() == rep
            ):
                return r
    for r in rows:
        if strategy and str(r.get("TSP_Strategy", "")).strip() == strategy:
            return r
    return rows[0]


def _normalize_wave_events_for_journey(stops: list, wave_events: list) -> list:
    """
    Collapse noisy controller events into a single readable story per bus/junction.

    The raw wave log can emit repeated grants/successes and, in some cases, events
    after the bus has already been detected at the stop line. For the dashboard we
    keep the earliest meaningful event and suppress obviously stale repeats.
    """
    if not wave_events:
        return []

    # Build arrival times ONLY from physical presence rows — IC-detect, harmony
    # decision rows, and track-zone rows.  coord-prearm rows fire BEFORE the bus
    # physically reaches the next junction and must NOT set arr_t, otherwise
    # prearm_success events (which fire 0.1–0.5 s later at the same sim time)
    # would be incorrectly dropped by the strict_pre_arrival_only gate.
    _PHYSICAL_TIERS = ("IC-detect", "PT-coord", "harmony-", "track-zone", "sec-", "det-")
    arrival_by_jct = {}
    for s in sorted(stops or [], key=lambda x: x.get("t", 0)):
        tier = str(s.get("tier", "") or "")
        if not any(tier.startswith(p) for p in _PHYSICAL_TIERS):
            continue
        jid = int(s.get("jct", -1) or -1)
        if jid > 0 and str(jid) not in arrival_by_jct:
            arrival_by_jct[str(jid)] = float(s.get("t", 0) or 0.0)

    dedupe_window_s = 1.5
    single_per_jct = {
        "grant",
        "prearm_fired",
        "prearm_success",
        "prearm_missed",
        "prearm_expired",
        "prearm_skipped",
        "tsp_skip",
    }
    pre_arrival_only = {
        "grant",
        "prearm_fired",
        "prearm_success",
        "prearm_queued",
        "prearm_retarget",
    }
    strict_pre_arrival_only = {"grant", "prearm_success"}

    last_seen = {}
    kept_single = set()
    out = []
    for w in sorted(wave_events, key=lambda e: float(e.get("t", 0) or 0.0)):
        evt = str(w.get("event", "") or "").strip()
        if not evt:
            continue
        target_jct = int(w.get("target_jct", -1) or -1)
        source_jct = int(w.get("source_jct", -1) or -1)
        jct = target_jct if target_jct > 0 else source_jct
        if jct <= 0:
            continue
        t = round(float(w.get("t", 0) or 0.0), 1)
        arr_t = arrival_by_jct.get(str(jct))
        if arr_t is not None:
            if evt in strict_pre_arrival_only and t >= (arr_t - 0.05):
                continue
            if evt in pre_arrival_only and t > (arr_t + 0.5):
                continue
        if evt in single_per_jct and (evt, jct) in kept_single:
            continue
        last_t = last_seen.get((evt, jct))
        if last_t is not None and (t - last_t) <= dedupe_window_s:
            continue
        last_seen[(evt, jct)] = t
        if evt in single_per_jct:
            kept_single.add((evt, jct))
        out.append({
            "jct": jct,
            "t": t,
            "event": evt,
            "source_jct": source_jct,
            "target_jct": target_jct,
        })
    # Post-filter: prearm_missed / prearm_expired should only appear at
    # junctions that actually had a prearm_fired for this bus.  Without this
    # guard they can show up on junctions the coordinator never pre-armed
    # (e.g. when _wave_origin changes between waves) and can appear long after
    # the bus has already left the junction.
    _fired_jcts = {e["jct"] for e in out if e["event"] == "prearm_fired"}
    out = [
        e for e in out
        if e["event"] not in ("prearm_missed", "prearm_expired", "prearm_discarded")
        or e["jct"] in _fired_jcts
    ]
    return out


def _bus_journeys_from_csv(det_csv: str, wave_events: list = None) -> list:
    """
    Extract per-bus corridor journeys from a detection CSV, optionally
    enriched with corridor wave events (prearm_fired / prearm_success /
    prearm_missed / grant) from the corridor_wave_events CSV.

    Returns a list of journey dicts, each:
      { vid, stops: [{jct, t, on_green, tier, x, y}, ...],
        n_jcts, cls,  wave_events: [{jct, t, event}, ...] }

    cls = 'full' (>=6 jcts), 'partial' (3-5), 'short' (2).
    Only buses seen at >= 2 junctions are included.
    """
    if not HAS_GW or not det_csv or not os.path.isfile(det_csv):
        return []
    rows = _load_detections(det_csv)
    if not rows:
        return []
    # Group by vehicle
    by_vid: dict = {}
    for r in rows:
        by_vid.setdefault(r["vid"], []).append(r)

    # Build wave-event lookup: vid -> list of {jct, t, event}
    we_by_vid: dict = {}
    if wave_events:
        for w in wave_events:
            vid = w.get("veh_id", -1)
            if vid <= 0:
                continue
            tgt = int(w.get("target_jct", -1) or -1)
            src = int(w.get("source_jct", -1) or -1)
            we_by_vid.setdefault(vid, []).append({
                "jct": tgt if tgt > 0 else src,
                "t": round(w["t"], 1),
                "event": w["event"],
                "source_jct": src,
                "target_jct": tgt,
            })

    # Keep only rows that represent physical bus presence at/near the junction.
    # Synthetic prearm marker tiers (coord-prearm*) are control events, not
    # movement stops, and should not influence selected-bus corridor route flow.
    _PHYSICAL_TIERS = ("IC-detect", "PT-coord", "harmony-", "track-zone", "track-section", "sec-", "det-")

    # Minimum plausible travel time between two different junctions (seconds).
    # Use a small anti-teleport gate to suppress overlapping-zone artefacts
    # while still preserving legitimate short inter-junction transitions.
    _MIN_INTER_JCT_S = 4.0

    journeys = []
    for vid, stops in by_vid.items():
        jcts_visited = set(s["jct"] for s in stops)
        if len(jcts_visited) < 2:
            continue
        sorted_stops = sorted(stops, key=lambda s: s["t"])
        journey_stops = []
        for s in sorted_stops:
          _tier = str(s.get("tier", "") or "")
          if not any(_tier.startswith(p) for p in _PHYSICAL_TIERS):
            continue
          p = _phase_at_stopline(s)
          stop = {
            "jct": s["jct"],
            "t": round(s["t"], 1),
            "on_green": 1 if p in ("green", "orange") else 0,
            "tier": s.get("tier", ""),
            "x": round(s.get("x", 0) or 0, 1),
            "y": round(s.get("y", 0) or 0, 1),
          }
          # Drop stops where the bus "teleports" — a different junction appears
          # within _MIN_INTER_JCT_S of the previous stop.  This removes artefacts
          # from overlapping detection zones or simultaneous section-map triggers.
          if journey_stops and stop["jct"] != journey_stops[-1]["jct"]:
            if stop["t"] - journey_stops[-1]["t"] < _MIN_INTER_JCT_S:
              continue  # implausible travel time — skip this stop
          journey_stops.append(stop)
        # Recalculate jcts_visited after filtering
        jcts_visited_filtered = set(s["jct"] for s in journey_stops)
        if len(jcts_visited_filtered) < 2:
            continue
        n_jcts = len(jcts_visited_filtered)
        cls = "full" if n_jcts >= 6 else ("partial" if n_jcts >= 3 else "short")
        j_obj = {
            "vid": vid,
            "stops": journey_stops,
            "n_jcts": n_jcts,
            "cls": cls,
        }
        # Attach wave events for this vehicle (prearm / grant)
        vwe = _normalize_wave_events_for_journey(journey_stops, we_by_vid.get(vid, []))
        if vwe:
            j_obj["wave"] = sorted(vwe, key=lambda e: e["t"])
        journeys.append(j_obj)
    # Sort by first detection time
    journeys.sort(key=lambda j: j["stops"][0]["t"] if j["stops"] else 0)
    return journeys


def _phase_samples_from_csv(det_csv: str) -> list:
    """
    Extract phase-state samples from detection_points CSV.

    Returns rows:
      {t, jct, vid, signal_phase, bus_phase, on_green, tier,
       prearm_status, prearm_note, focus_role}

    Note: these are detection snapshots (not continuous per-second phase traces).
    """
    if not det_csv or not os.path.isfile(det_csv):
      return []

    out = []
    try:
        with open(det_csv, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    t = float(r.get("sim_time_s", 0) or 0)
                    jct = int(float(r.get("junction_id", -1) or -1))
                    vid = int(float(r.get("veh_id", -1) or -1))
                    sig = int(float(r.get("signal_phase", -1) or -1))
                    bus = int(float(r.get("bus_phase", -1) or -1))
                except Exception:
                    continue
                if jct <= 0 or vid <= 0:
                    continue
                on_green = 1 if (sig >= 0 and bus >= 0 and sig == bus) else 0
                out.append({
                    "t": round(t, 1),
                    "jct": jct,
                    "vid": vid,
                    "signal_phase": sig,
                    "bus_phase": bus,
                    "on_green": on_green,
                  "tier": str(r.get("tier", "") or ""),
                  "prearm_status": str(r.get("prearm_status", "") or ""),
                  "prearm_note": str(r.get("prearm_note", "") or ""),
                  "focus_role": str(r.get("focus_role", "") or ""),
                })
    except Exception:
        return []
    return out


def _detection_pair_stats_from_csv(det_csv: str) -> dict:
    """
    Compute unique detection counts using bus×junction pairs.

    Returns:
      {
        "pair_count": int,
        "bus_count": int,
        "jct_count": int,
        "max_pairs": int,
        "green_pair_count": int,
        "nongreen_pair_count": int,
      }
    """
    if not det_csv or not os.path.isfile(det_csv):
        return {
            "pair_count": 0, "bus_count": 0, "jct_count": 0, "max_pairs": 0,
            "green_pair_count": 0, "nongreen_pair_count": 0,
        }

    allowed_jcts = set(int(j) for j in ALL_CORRIDOR_JCTS) if HAS_GW and ALL_CORRIDOR_JCTS else None
    pairs = set()
    green_pairs = set()
    buses = set()
    jcts = set()
    try:
        with open(det_csv, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    vid = int(float(r.get("veh_id", -1) or -1))
                    jct = int(float(r.get("junction_id", -1) or -1))
                except Exception:
                    continue
                if vid <= 0 or jct <= 0:
                    continue
                if allowed_jcts is not None and jct not in allowed_jcts:
                    continue
                pair = (vid, jct)
                pairs.add(pair)
                buses.add(vid)
                jcts.add(jct)
                try:
                  sig = int(float(r.get("signal_phase", -1) or -1))
                  bus = int(float(r.get("bus_phase", -1) or -1))
                except Exception:
                  sig, bus = -1, -1
                if sig >= 0 and bus >= 0 and sig == bus:
                  green_pairs.add(pair)
    except Exception:
            return {
              "pair_count": 0, "bus_count": 0, "jct_count": 0, "max_pairs": 0,
              "green_pair_count": 0, "nongreen_pair_count": 0,
            }

    jct_cap = len(allowed_jcts) if allowed_jcts else len(jcts)
    max_pairs = len(buses) * max(jct_cap, 0)
    return {
        "pair_count": len(pairs),
        "bus_count": len(buses),
        "jct_count": len(jcts),
        "max_pairs": max_pairs,
      "green_pair_count": len(green_pairs),
      "nongreen_pair_count": max(0, len(pairs) - len(green_pairs)),
    }


def build_dashboard_data(batch_rows: list, log_dir: str) -> dict:
    """Build the JSON data object embedded in the HTML template."""

    # ── Deduplicate: keep only the last row per experiment name ──────────────
    batch_rows = _dedup_batch_rows(batch_rows)

    all_det_csvs = _detect_csvs(log_dir)   # sorted oldest->newest

    # ── Sequential fallback: if no experiment-name CSVs exist yet, zip the N
    # most recent detection CSVs with the first N batch rows (in insertion order)
    # — this matches the batch runner's experiment execution order.
    # Old style: detection_points_YYYYMMDD_HHMMSS.csv  -> segment after prefix = 8 digits
    # New style: detection_points_EXPNAME_YYYYMMDD_HHMMSS.csv -> first segment is non-numeric
    def _is_named_csv(path: str) -> bool:
        stem = os.path.splitext(os.path.basename(path))[0]
        after = stem[len("detection_points_"):]  # strip "detection_points_"
        first_seg = after.split("_")[0]
        return not first_seg.isdigit()
    has_named_csvs = any(_is_named_csv(p) for p in all_det_csvs)
    _seq_fallback: dict = {}  # id(row) -> csv path for sequential fallback
    if not has_named_csvs and all_det_csvs:
        recent = all_det_csvs[-len(batch_rows):]   # take the last N CSVs
        for i, row in enumerate(batch_rows):
            if i < len(recent):
                _seq_fallback[id(row)] = recent[i]

    # Pre-seed with all known corridor junctions so the green-rate chart always
    # shows every junction even when a run's detection CSV is missing or empty.
    # Also include ALL config junctions (passive detection-zone ones) so the corridor
    # spatial map and journey chart can show them alongside active TSP junctions.
    all_jct_ids: set = set(str(j) for j in ALL_CORRIDOR_JCTS) if HAS_GW else set()
    all_jct_ids.update(_ALL_CONFIG_JCTS)  # include passive/monitoring junctions
    runs_data:   list = []
    all_wave_csvs = _wave_csvs(log_dir) if log_dir else []
    all_bus_track_csvs = _bus_tracking_csvs(log_dir) if log_dir else []
    all_obj_csvs = _objective_trace_csvs(log_dir) if log_dir else []
    all_reward_csvs = _reward_cycle_csvs(log_dir) if log_dir else []
    all_focus_csvs = _focus_history_csvs(log_dir) if log_dir else []
    all_queue_snap_csvs = _queue_snapshot_csvs(log_dir) if log_dir else []
    all_dynaropac_csvs = _dynaropac_csvs(log_dir) if log_dir else []

    for row in batch_rows:
        label       = _run_label(row)
        strategy    = row.get("run_strategy", "UNKNOWN")
        exp_name    = row.get("run_experiment", strategy)
        coordinated = str(row.get("run_coordinated", "")).lower() in ("true", "1", "yes")
        seed_raw    = row.get("run_seed", "")
        try:
            seed_val = int(float(seed_raw)) if seed_raw not in ("", None) else None
        except (TypeError, ValueError):
            seed_val = None
        success     = str(row.get("run_success", "")).lower() in ("true", "1", "yes", "success")

        # ── Numeric metrics ──────────────────────────────────────────────────
        total_delay   = _pick(row, ["stats_TotalPassDelay_hrs",
                                    "inter_sum_TotalPassDelay_hrs"])
        main_delay    = _pick(row, ["stats_MainPassDelay_hrs",
                                    "inter_sum_MainPassDelay_hrs"])
        side_delay    = _pick(row, ["stats_SidePassDelay_hrs",
                                    "inter_sum_SidePassDelay_hrs"])
        bus_tt        = _pick(row, ["stats_BusTotalTT_hrs",
                                    "inter_sum_BusTotalTT_hrs"])
        avg_bus_delay   = _pick(row, ["stats_AvgBusPassDelay_s",
                                      "inter_avg_AvgBusPassDelay_s"])
        avg_pass_delay  = _pick(row, ["stats_AvgPassDelay_s",
                                      "inter_avg_AvgPassDelay_s"])
        avg_car_delay   = _pick(row, ["stats_AvgCarPassDelay_s",
                                      "inter_avg_AvgCarPassDelay_s"])
        avg_truck_delay = _pick(row, ["stats_AvgTruckPassDelay_s",
                                      "inter_avg_AvgTruckPassDelay_s"])
        pax_equiv       = _pick(row, ["stats_PaxEquivPassages",
                                      "inter_sum_PaxEquivPassages"])
        bus_pax_equiv   = _pick(row, ["stats_BusPaxEquivPassages",
                                      "inter_sum_BusPaxEquivPassages"])
        car_pax_equiv   = _pick(row, ["stats_CarPaxEquivPassages",
                                      "inter_sum_CarPaxEquivPassages"])
        truck_pax_equiv = _pick(row, ["stats_TruckPaxEquivPassages",
                                      "inter_sum_TruckPaxEquivPassages"])
        distinct_cars   = _pick(row, ["stats_N_DistinctCars",
                                      "inter_sum_N_DistinctCars"])
        distinct_buses  = _pick(row, ["stats_N_DistinctBuses",
                                      "inter_sum_N_DistinctBuses"])
        distinct_trucks = _pick(row, ["stats_N_DistinctTrucks",
                                      "inter_sum_N_DistinctTrucks"])
        # Avg pax delay per simulation-hour (pax·hrs of delay per sim-hour)
        avg_main_delay_per_hr  = _pick(row, ["stats_AvgMainPassDelay_pax_h_per_sim_h"])
        avg_side_delay_per_hr  = _pick(row, ["stats_AvgSidePassDelay_pax_h_per_sim_h"])
        avg_total_delay_per_hr = _pick(row, ["stats_AvgTotalPassDelay_pax_h_per_sim_h"])
        sim_duration_hrs       = _pick(row, ["stats_SimDuration_hrs"])
        # TSP event counts — prefer stats_ (from global simulation_results.csv, single-run)
        # over inter_sum_ (from per-intersection CSV, which can include prior runs if
        # ScenarioID filtering fails).  This prevents the "1500 vs 530" discrepancy
        # where inter_sum inflates detection count with accumulated historical rows.
        tsp_det       = _pick(row, ["stats_TSP_Detections",
                                    "inter_sum_TSP_Detections"])
        tsp_ext       = _pick(row, ["stats_TSP_Extensions",
                                    "inter_sum_TSP_Extensions"])
        tsp_ins       = _pick(row, ["stats_TSP_Insertions",
                                    "inter_sum_TSP_Insertions"])
        # TSP outcome breakdown — consistent with stats_ source
        tsp_natural_green = _pick(row, ["stats_TSP_NaturalGreen",
                                        "inter_sum_TSP_NaturalGreen"])
        tsp_skip_ge       = _pick(row, ["stats_TSP_Skipped_GE",
                                        "inter_sum_TSP_Skipped_GE"])
        tsp_skip_ins      = _pick(row, ["stats_TSP_Skipped_Ins",
                                        "inter_sum_TSP_Skipped_Ins"])
        tsp_no_action     = _pick(row, ["stats_TSP_Detected_NoAction",
                                        "inter_sum_TSP_Detected_NoAction"])
        # ── TSP_Paper 4-objective values (from batch_results wobj_* columns) ─
        # Z1 = Σ passenger delay (bus + car, pax·s) — minimise
        # Z2 = flow-weighted green bandwidth        — MAXIMISE (higher is better)
        # Z3 = total bus lateness Σσ+ (s)           — minimise
        # Z4 = corridor travel time (s)             — minimise
        wobj_Z1 = _pick(row, ["wobj_Z1_total"])
        wobj_Z2 = _pick(row, ["wobj_Z2_total"])
        wobj_Z3 = _pick(row, ["wobj_Z3_total"])
        wobj_Z4 = _pick(row, ["wobj_Z4_total"])
        wobj_total = _pick(row, ["wobj_objective_total"])
        bus_predictor = (row.get("run_bus_predictor") or "KALMAN").strip().upper() or "KALMAN"
        sim_row = _load_simulation_results_row(row, log_dir)
        per_section = _load_per_section_data(row, log_dir)
        sec_density = _weighted_section_metric(per_section, "density")
        sec_speed = _weighted_section_metric(per_section, "speed")
        sec_flow = _weighted_section_metric(per_section, "flow")

        # Network stats — prefer batch_results values, then per-run simulation_results.csv,
        # then older PyANGKernel fallback keys.
        density = _first_valid_metric(
          _pick(sim_row, ["Net_Density_All", "Net_AvgDensity_vkm"]),
          _pick(row, ["stats_Net_Density_All", "stats_Net_AvgDensity_vkm", "aimsun_avg_density_vkm"]),
          sec_density,
          allow_zero=False,
        )
        if density is None:
            density = _first_valid_metric(
                _pick(sim_row, ["Net_Density_All", "Net_AvgDensity_vkm"]),
                _pick(row, ["stats_Net_Density_All", "stats_Net_AvgDensity_vkm", "aimsun_avg_density_vkm"]),
                sec_density,
                allow_zero=True,
            )
        speed = _first_valid_metric(
            _pick(sim_row, ["Net_AvgSpeed_kmh"]),
            _pick(row, ["stats_Net_AvgSpeed_kmh", "aimsun_avg_speed_kmh"]),
            sec_speed,
            allow_zero=False,
        )
        if sec_speed is not None and sec_speed > 0.0 and speed is not None and 0.0 < speed < 0.5 * sec_speed:
            speed = sec_speed
        flow = _first_valid_metric(
            _pick(sim_row, ["Net_TotalFlowVeh"]),
            _pick(row, ["stats_Net_TotalFlowVeh", "aimsun_total_flow_veh"]),
            allow_zero=False,
        )
        # Sanity clamp: Aimsun sometimes returns a cumulative passage count
        # (~673 M for DCTSP_MARL) instead of veh/h when the wrong statistic
        # type is resolved.  Any value > 50 000 veh/h is physically impossible
        # for this corridor — treat it as missing.
        # Better fallback: estimate network throughput from (distinct cars + buses
        # + trucks) / sim_duration_hrs.  This gives a comparable metric to the
        # GKSystemStatistic "all types" flow that the other experiments report
        # (N_sys_exit / I × 3600).  sec_flow is a length-weighted per-SECTION
        # average and is a different, smaller metric — do NOT use it as a
        # substitute for network-level throughput.
        if flow is not None and flow > 50_000:
            _dc = distinct_cars or 0.0
            _db = distinct_buses or 0.0
            _dt = distinct_trucks or 0.0
            _dh = sim_duration_hrs or 1.25   # default 1.25 h if unknown
            if (_dc + _db) > 0 and float(_dh) > 0:
                flow = round((_dc + _db + _dt) / float(_dh))
            else:
                flow = sec_flow  # last resort: section-level weighted average
        elapsed = _pick(row, ["run_elapsed_s"])
        # Per-vehicle-type network stats from PyANGKernel (length-weighted, collected after run)
        net_flow_car    = _pick(row, ["aimsun_flow_car"])
        net_flow_bus    = _pick(row, ["aimsun_flow_bus"])
        net_flow_truck  = _pick(row, ["aimsun_flow_truck"])
        net_dens_car    = _pick(row, ["aimsun_density_car"])
        net_dens_bus    = _pick(row, ["aimsun_density_bus"])
        net_dens_truck  = _pick(row, ["aimsun_density_truck"])
        net_spd_car     = _pick(row, ["aimsun_speed_car"])
        net_spd_bus     = _pick(row, ["aimsun_speed_bus"])
        net_spd_truck   = _pick(row, ["aimsun_speed_truck"])
        # Per-type network stats — prefer stats_Net_* from simulation_results.csv (via AAPI at finish)
        # Fall back to aimsun_* from PyANGKernel post-run collection
        net_flow_car = _first_valid_metric(
            _pick(row, ["stats_Net_Flow_Car", "aimsun_flow_car"]),
            _pick(sim_row, ["Net_Flow_Car"]),
            allow_zero=False,
        )
        net_flow_bus = _first_valid_metric(
            _pick(row, ["stats_Net_Flow_Bus", "aimsun_flow_bus"]),
            _pick(sim_row, ["Net_Flow_Bus"]),
            allow_zero=False,
        )
        net_flow_truck = _first_valid_metric(
            _pick(row, ["stats_Net_Flow_Truck", "aimsun_flow_truck"]),
            _pick(sim_row, ["Net_Flow_Truck"]),
            allow_zero=False,
        )
        net_dens_car = _first_valid_metric(
            _pick(row, ["stats_Net_Density_Car", "aimsun_density_car"]),
            _pick(sim_row, ["Net_Density_Car"]),
            allow_zero=False,
        )
        net_dens_bus = _first_valid_metric(
            _pick(row, ["stats_Net_Density_Bus", "aimsun_density_bus"]),
            _pick(sim_row, ["Net_Density_Bus"]),
            allow_zero=False,
        )
        net_dens_truck = _first_valid_metric(
            _pick(row, ["stats_Net_Density_Truck", "aimsun_density_truck"]),
            _pick(sim_row, ["Net_Density_Truck"]),
            allow_zero=False,
        )
        net_spd_car = _first_valid_metric(
            _pick(row, ["stats_Net_Speed_Car", "aimsun_speed_car"]),
            _pick(sim_row, ["Net_Speed_Car"]),
            allow_zero=False,
        )
        net_spd_bus = _first_valid_metric(
            _pick(row, ["stats_Net_Speed_Bus", "aimsun_speed_bus"]),
            _pick(sim_row, ["Net_Speed_Bus"]),
            allow_zero=False,
        )
        net_spd_truck = _first_valid_metric(
            _pick(row, ["stats_Net_Speed_Truck", "aimsun_speed_truck"]),
            _pick(sim_row, ["Net_Speed_Truck"]),
            allow_zero=False,
        )
        type_flow_sum = sum(
            float(v) for v in (net_flow_car, net_flow_bus, net_flow_truck)
            if v is not None and math.isfinite(float(v))
        )
        if type_flow_sum > 0.0 and (flow is None or flow < 0.5 * type_flow_sum):
            flow = type_flow_sum
        if (flow is None or flow <= 0.0) and sec_flow is not None and sec_flow > 0.0:
            flow = sec_flow
        net_delay_all = _first_valid_metric(
            _pick(row, ["stats_Net_Delay_All", "aimsun_avg_delay_s_km"]),
            _pick(sim_row, ["Net_Delay_All"]),
          allow_zero=True,
        )
        net_delay_car = _first_valid_metric(
            _pick(row, ["stats_Net_Delay_Car", "aimsun_delay_car"]),
            _pick(sim_row, ["Net_Delay_Car"]),
          allow_zero=True,
        )
        net_delay_bus = _first_valid_metric(
            _pick(row, ["stats_Net_Delay_Bus", "aimsun_delay_bus"]),
            _pick(sim_row, ["Net_Delay_Bus"]),
          allow_zero=True,
        )
        net_delay_truck = _first_valid_metric(
            _pick(row, ["stats_Net_Delay_Truck", "aimsun_delay_truck"]),
            _pick(sim_row, ["Net_Delay_Truck"]),
          allow_zero=True,
        )
        net_entry_delay_all = _first_valid_metric(
          _pick(row, ["stats_Net_EntryDelay_All"]),
          _pick(sim_row, ["Net_EntryDelay_All", "Net_Delay_All"]),
          allow_zero=True,
        )
        net_exit_delay_all = _first_valid_metric(
          _pick(row, ["stats_Net_ExitDelay_All"]),
          _pick(sim_row, ["Net_ExitDelay_All", "Net_Delay_All"]),
          allow_zero=True,
        )
        net_entry_delay_car = _first_valid_metric(
          _pick(row, ["stats_Net_EntryDelay_Car"]),
          _pick(sim_row, ["Net_EntryDelay_Car", "Net_Delay_Car"]),
          allow_zero=True,
        )
        net_exit_delay_car = _first_valid_metric(
          _pick(row, ["stats_Net_ExitDelay_Car"]),
          _pick(sim_row, ["Net_ExitDelay_Car", "Net_Delay_Car"]),
          allow_zero=True,
        )
        net_entry_delay_bus = _first_valid_metric(
          _pick(row, ["stats_Net_EntryDelay_Bus"]),
          _pick(sim_row, ["Net_EntryDelay_Bus", "Net_Delay_Bus"]),
          allow_zero=True,
        )
        net_exit_delay_bus = _first_valid_metric(
          _pick(row, ["stats_Net_ExitDelay_Bus"]),
          _pick(sim_row, ["Net_ExitDelay_Bus", "Net_Delay_Bus"]),
          allow_zero=True,
        )
        net_entry_delay_truck = _first_valid_metric(
          _pick(row, ["stats_Net_EntryDelay_Truck"]),
          _pick(sim_row, ["Net_EntryDelay_Truck", "Net_Delay_Truck"]),
          allow_zero=True,
        )
        net_exit_delay_truck = _first_valid_metric(
          _pick(row, ["stats_Net_ExitDelay_Truck"]),
          _pick(sim_row, ["Net_ExitDelay_Truck", "Net_Delay_Truck"]),
          allow_zero=True,
        )
        # Fallback: if system-level delay is 0 but per-type delays exist, use
        # flow-weighted average (AKIEstGetGlobalStatisticsSystem returns 0 for DTa
        # in some Aimsun builds/runs while per-type stats work fine).
        if (net_delay_all is None or net_delay_all == 0.0):
            _wt_d, _wt_f = 0.0, 0.0
            for _d, _f in [
                (net_delay_car,   net_flow_car),
                (net_delay_bus,   net_flow_bus),
                (net_delay_truck, net_flow_truck),
            ]:
                if _d is not None and _d > 0.0 and _f is not None and _f > 0.0:
                    _wt_d += _d * _f
                    _wt_f += _f
            if _wt_f > 0.0:
                net_delay_all = round(_wt_d / _wt_f, 2)
                if net_entry_delay_all is None or net_entry_delay_all == 0.0:
                    net_entry_delay_all = net_delay_all
                if net_exit_delay_all is None or net_exit_delay_all == 0.0:
                    net_exit_delay_all = net_delay_all

        # Extended section stats from collect_extra_section_stats
        # These map to Net_EntryTT_*/Net_ExitTT_*/Net_ExitSpd_*/etc. columns in simulation_results.csv
        def _xpick(key):
            """Pick a scalar float from sim_row for an extended-stats column."""
            v = _pick(sim_row, [key])
            if v is None:
                return None
            try:
                f = float(v)
                return f if math.isfinite(f) else None
            except (TypeError, ValueError):
                return None

        net_entry_tt_all   = _xpick("Net_EntryTT_All")
        net_entry_tt_car   = _xpick("Net_EntryTT_Car")
        net_entry_tt_bus   = _xpick("Net_EntryTT_Bus")
        net_entry_tt_hov   = _xpick("Net_EntryTT_HOV")
        net_entry_tt_truck = _xpick("Net_EntryTT_Truck")

        net_exit_tt_all    = _xpick("Net_ExitTT_All")
        net_exit_tt_car    = _xpick("Net_ExitTT_Car")
        net_exit_tt_bus    = _xpick("Net_ExitTT_Bus")
        net_exit_tt_hov    = _xpick("Net_ExitTT_HOV")
        net_exit_tt_truck  = _xpick("Net_ExitTT_Truck")

        net_exit_spd_all   = _xpick("Net_ExitSpd_All")
        net_exit_spd_car   = _xpick("Net_ExitSpd_Car")
        net_exit_spd_bus   = _xpick("Net_ExitSpd_Bus")
        net_exit_spd_hov   = _xpick("Net_ExitSpd_HOV")
        net_exit_spd_truck = _xpick("Net_ExitSpd_Truck")

        net_stop_time_all   = _xpick("Net_StopTime_All")
        net_stop_time_car   = _xpick("Net_StopTime_Car")
        net_stop_time_bus   = _xpick("Net_StopTime_Bus")
        net_stop_time_truck = _xpick("Net_StopTime_Truck")

        net_num_stops_all   = _xpick("Net_NumStops_All")
        net_num_stops_car   = _xpick("Net_NumStops_Car")
        net_num_stops_bus   = _xpick("Net_NumStops_Bus")
        net_num_stops_truck = _xpick("Net_NumStops_Truck")

        net_total_dist_all   = _xpick("Net_TotalDist_All")
        net_total_dist_car   = _xpick("Net_TotalDist_Car")
        net_total_dist_bus   = _xpick("Net_TotalDist_Bus")
        net_total_dist_truck = _xpick("Net_TotalDist_Truck")

        net_total_tt_h_all   = _xpick("Net_TotalTT_h_All")
        net_total_tt_h_car   = _xpick("Net_TotalTT_h_Car")
        net_total_tt_h_bus   = _xpick("Net_TotalTT_h_Bus")
        net_total_tt_h_truck = _xpick("Net_TotalTT_h_Truck")

        net_exit_count_all   = _xpick("Net_ExitCount_All")
        net_exit_count_car   = _xpick("Net_ExitCount_Car")
        net_exit_count_bus   = _xpick("Net_ExitCount_Bus")
        net_exit_count_truck = _xpick("Net_ExitCount_Truck")

        net_input_flow_all   = _xpick("Net_InputFlow_All")
        net_input_flow_car   = _xpick("Net_InputFlow_Car")
        net_input_flow_bus   = _xpick("Net_InputFlow_Bus")
        net_input_flow_truck = _xpick("Net_InputFlow_Truck")

        net_exit_flow_all    = _xpick("Net_ExitFlow_All")
        net_exit_flow_car    = _xpick("Net_ExitFlow_Car")
        net_exit_flow_bus    = _xpick("Net_ExitFlow_Bus")
        net_exit_flow_truck  = _xpick("Net_ExitFlow_Truck")

        net_total_lc_all    = _xpick("Net_TotalLC_All")
        net_total_lc_car    = _xpick("Net_TotalLC_Car")
        net_total_lc_bus    = _xpick("Net_TotalLC_Bus")
        net_total_lc_truck  = _xpick("Net_TotalLC_Truck")

        net_mean_queue_all   = _xpick("Net_MeanQueue_All")
        net_mean_queue_car   = _xpick("Net_MeanQueue_Car")
        net_mean_queue_bus   = _xpick("Net_MeanQueue_Bus")
        net_mean_queue_truck = _xpick("Net_MeanQueue_Truck")

        net_max_queue_all    = _xpick("Net_MaxQueue_All")
        net_max_queue_car    = _xpick("Net_MaxQueue_Car")
        net_max_queue_bus    = _xpick("Net_MaxQueue_Bus")
        net_max_queue_truck  = _xpick("Net_MaxQueue_Truck")

        net_vq_avg_all    = _xpick("Net_VQAvg_All")
        net_vq_avg_bus    = _xpick("Net_VQAvg_Bus")
        net_vq_max_all    = _xpick("Net_VQMax_All")
        net_wait_vq_all   = _xpick("Net_WaitVQ_All")
        net_wait_vq_bus   = _xpick("Net_WaitVQ_Bus")

        # Prearm coordination stats — written by record_prearm_stats in AAPIFinish
        # (only non-zero for GROUP_BASED modes that use CorridorCoordinator)
        prearm_fired   = _pick(row, ["stats_Prearm_Fired",    "stats_prearm_fired"])
        prearm_success = _pick(row, ["stats_Prearm_Success",  "stats_prearm_success"])
        prearm_missed  = _pick(row, ["stats_Prearm_Missed",   "stats_prearm_missed"])
        prearm_expired  = _pick(row, ["stats_Prearm_Expired",  "stats_prearm_expired"])
        prearm_discarded= _pick(row, ["stats_Prearm_Discarded","stats_prearm_discarded"])
        prearm_late_success = _pick(row, ["stats_Prearm_LateSuccess", "stats_prearm_late_success"])
        prearm_late_delay_s = _pick(row, ["stats_Prearm_LateSuccessDelay_s", "stats_prearm_late_success_delay_s"])
        avg_extension_s = _pick(row, ["stats_TSP_AvgExtension_s", "inter_avg_TSP_AvgExtension_s"])
        avg_insertion_s = _pick(row, ["stats_TSP_AvgInsertion_s", "inter_avg_TSP_AvgInsertion_s"])
        avg_insertion_wait_s = _pick(row, ["stats_TSP_AvgInsertionWait_s", "inter_avg_TSP_AvgInsertionWait_s"])

        # ── Green rates from detection CSV ───────────────────────────────────
        # Try experiment-name match first (new style filenames); fall back to
        # sequential zip for old-style timestamp-only filenames.
        det_csv = (_match_det_csv_by_name(exp_name, all_det_csvs)
                   or _seq_fallback.get(id(row)))
        focus_csv = _match_focus_csv_by_name(exp_name, all_focus_csvs)
        focus_history = _focus_history_from_csv(focus_csv) if focus_csv else []
        focus_bus_ids = {int(f.get("veh_id", 0) or 0) for f in focus_history if int(f.get("veh_id", 0) or 0) > 0}
        focus_summary = _focus_junction_summary(focus_history)

        green_rates_all = _green_rates_from_csv(det_csv, None) if det_csv else {}
        green_rates_focus = _green_rates_from_csv(det_csv, focus_bus_ids) if (det_csv and focus_bus_ids) else {}
        all_jct_ids.update(green_rates_all.keys())
        all_jct_ids.update(green_rates_focus.keys())

        mean_green = (round(sum(green_rates_all.values()) / len(green_rates_all), 1)
                if green_rates_all else None)
        mean_green_focus = (round(sum(green_rates_focus.values()) / len(green_rates_focus), 1)
                if green_rates_focus else None)

        # ── Per-intersection detail ───────────────────────────────────────────
        per_inter = _load_per_intersection_data(row, log_dir)
        per_section = _load_per_section_data(row, log_dir)

        # ── Wave events for this run ──────────────────────────────────────────
        wave_csv = _match_wave_csv_by_name(exp_name, all_wave_csvs)
        wave_evts = _wave_events_from_csv(wave_csv) if wave_csv else []

        obj_csv = _match_objective_trace_csv_by_name(exp_name, all_obj_csvs)
        objective_trace = _objective_trace_from_csv(obj_csv) if obj_csv else []
        reward_csv = _match_reward_cycle_csv_by_name(exp_name, all_reward_csvs)
        reward_cycle = _reward_cycle_from_csv(reward_csv) if reward_csv else []

        bus_journeys = _bus_journeys_from_csv(det_csv, wave_evts) if det_csv else []
        phase_samples = _phase_samples_from_csv(det_csv) if det_csv else []
        det_pair_stats = _detection_pair_stats_from_csv(det_csv) if det_csv else {
          "pair_count": 0, "bus_count": 0, "jct_count": 0, "max_pairs": 0,
          "green_pair_count": 0, "nongreen_pair_count": 0,
        }
        det_jct_stats = _detection_junction_stats_from_csv(det_csv) if det_csv else {}

        # ── Bus position tracking data ────────────────────────────────────────
        bus_track_csv = _match_bus_tracking_csv_by_name(exp_name, all_bus_track_csvs)
        bus_tracking = _bus_tracking_from_csv(bus_track_csv) if bus_track_csv else []
        track_summary = _bus_tracking_summary(bus_tracking)

        # ── Queue snapshot data (60-second snapshots per junction) ─────────────
        queue_snap_csv = _match_queue_snapshot_csv_by_name(exp_name, all_queue_snap_csvs)
        queue_snapshots = _queue_snapshot_from_csv(queue_snap_csv) if queue_snap_csv else []
        # Per-approach entry-point detail (new format with direction labels)
        queue_entry_snapshots = _queue_entry_snapshots_from_csv(queue_snap_csv) if queue_snap_csv else []

        # ── DYNAOPAC decision log (phase-duration search candidates + delays) ──
        dyn_csv = _match_dynaropac_csv_by_name(exp_name, all_dynaropac_csvs)
        dynaropac_decisions = _dynaropac_decisions_from_csv(dyn_csv) if dyn_csv else []
        per_inter = _merge_per_intersection_coverage(
            per_inter,
            det_jct_stats,
            track_summary,
            focus_summary,
        )
        all_jct_ids.update(det_jct_stats.keys())
        all_jct_ids.update((track_summary or {}).get("per_jct", {}).keys())
        all_jct_ids.update((focus_summary or {}).get("per_jct", {}).keys())
        all_jct_ids.update(str(pi.get("iid")) for pi in per_inter if pi.get("iid") is not None)

        tracked_bus_count = int(track_summary.get("tracked_bus_count", 0))
        detected_bus_count = int(det_pair_stats.get("bus_count", 0))
        tracked_only_bus_count = max(tracked_bus_count - detected_bus_count, 0)
        tracking_coverage_pct = (
            round(100.0 * detected_bus_count / tracked_bus_count, 1)
            if tracked_bus_count > 0 else None
        )

        run_obj = {
            "label":       label,
            "strategy":    strategy,
            "exp_name":    exp_name,
            "coordinated": coordinated,
            "seed":        seed_val,
            "success":     success,
            "elapsed":     round(elapsed, 1) if elapsed is not None else None,
            # delays (hrs)
            "total_delay":    _rnd(total_delay, 3),
            "main_delay":     _rnd(main_delay,  3),
            "side_delay":     _rnd(side_delay,  3),
            "bus_tt":         _rnd(bus_tt,      3),
            # per-pax delays (s)
            "avg_pass_delay":  _rnd(avg_pass_delay,  2),
            "avg_bus_delay":   _rnd(avg_bus_delay,   2),
            "avg_car_delay":   _rnd(avg_car_delay,   2),
            "avg_truck_delay":        _rnd(avg_truck_delay,       2),
            # volume behind passenger-weighted delay metrics
            "pax_equiv":        _rnd(pax_equiv,       1),
            "bus_pax_equiv":    _rnd(bus_pax_equiv,   1),
            "car_pax_equiv":    _rnd(car_pax_equiv,   1),
            "truck_pax_equiv":  _rnd(truck_pax_equiv, 1),
            "distinct_cars":    _int(distinct_cars),
            "distinct_buses":   _int(distinct_buses),
            "distinct_trucks":  _int(distinct_trucks),
            # Avg pax delay per simulation-hour (pax·hrs/sim-hr) — independent of sim length
            "avg_main_delay_per_hr":  _rnd(avg_main_delay_per_hr,  3),
            "avg_side_delay_per_hr":  _rnd(avg_side_delay_per_hr,  3),
            "avg_total_delay_per_hr": _rnd(avg_total_delay_per_hr, 3),
            "sim_duration_hrs":       _rnd(sim_duration_hrs,        2),
            # tsp events — full breakdown
            "tsp_det":          _int(tsp_det),
            "tsp_det_unique":   int(det_pair_stats.get("pair_count", 0)),
            "tsp_det_bus_count": int(det_pair_stats.get("bus_count", 0)),
            "tsp_det_jct_count": int(det_pair_stats.get("jct_count", 0)),
            "tsp_det_max_pairs": int(det_pair_stats.get("max_pairs", 0)),
            "tsp_green_unique": int(det_pair_stats.get("green_pair_count", 0)),
            "tsp_nongreen_unique": int(det_pair_stats.get("nongreen_pair_count", 0)),
            "tracked_bus_count": tracked_bus_count,
            "tracked_jct_count": int(track_summary.get("tracked_jct_count", 0)),
            "tracked_samples": int(track_summary.get("tracked_samples", 0)),
            "tracked_only_bus_count": tracked_only_bus_count,
            "tracking_coverage_pct": tracking_coverage_pct,
            "focus_bus_count": int(focus_summary.get("focus_bus_count", 0)),
            "journey_bus_count": len({int(j.get("vid", 0) or 0) for j in bus_journeys if int(j.get("vid", 0) or 0) > 0}),
            "stats_distinct_buses_raw": _int(row.get("stats_N_DistinctBuses")),
            "tsp_ext":          _int(tsp_ext),
            "tsp_ins":          _int(tsp_ins),
            "tsp_natural_green": _int(tsp_natural_green),
            "tsp_skip_ge":      _int(tsp_skip_ge),
            "tsp_skip_ins":     _int(tsp_skip_ins),
            "tsp_no_action":    _int(tsp_no_action),
            # network (length-weighted averages from PyANGKernel / AAPI stats)
            "density":           _rnd(density,        3),
            "density_all":       _rnd(density,        3),
            "speed":             _rnd(speed,           2),
            "flow":              _rnd(flow,            0),
            # per-type network stats (only populated when PyANGKernel API succeeds)
            "net_flow_car":      _rnd(net_flow_car,    1),
            "net_flow_bus":      _rnd(net_flow_bus,    1),
            "net_flow_truck":    _rnd(net_flow_truck,  1),
            "net_dens_car":      _rnd(net_dens_car,    2),
            "net_dens_bus":      _rnd(net_dens_bus,    2),
            "net_dens_truck":    _rnd(net_dens_truck,  2),
            "net_spd_car":       _rnd(net_spd_car,     2),
            "net_spd_bus":       _rnd(net_spd_bus,     2),
            "net_spd_truck":     _rnd(net_spd_truck,   2),
            "net_delay_all":     _rnd(net_delay_all,   2),
            "net_delay_car":     _rnd(net_delay_car,   2),
            "net_delay_bus":     _rnd(net_delay_bus,   2),
            "net_delay_truck":   _rnd(net_delay_truck, 2),
            "net_entry_delay_all":   _rnd(net_entry_delay_all,   2),
            "net_exit_delay_all":    _rnd(net_exit_delay_all,    2),
            "net_entry_delay_car":   _rnd(net_entry_delay_car,   2),
            "net_exit_delay_car":    _rnd(net_exit_delay_car,    2),
            "net_entry_delay_bus":   _rnd(net_entry_delay_bus,   2),
            "net_exit_delay_bus":    _rnd(net_exit_delay_bus,    2),
            "net_entry_delay_truck": _rnd(net_entry_delay_truck, 2),
            "net_exit_delay_truck":  _rnd(net_exit_delay_truck,  2),
            # Extended section stats (from collect_extra_section_stats)
            "net_entry_tt_all":    _rnd(net_entry_tt_all,   2),
            "net_entry_tt_car":    _rnd(net_entry_tt_car,   2),
            "net_entry_tt_bus":    _rnd(net_entry_tt_bus,   2),
            "net_entry_tt_hov":    _rnd(net_entry_tt_hov,   2),
            "net_entry_tt_truck":  _rnd(net_entry_tt_truck, 2),
            "net_exit_tt_all":     _rnd(net_exit_tt_all,    2),
            "net_exit_tt_car":     _rnd(net_exit_tt_car,    2),
            "net_exit_tt_bus":     _rnd(net_exit_tt_bus,    2),
            "net_exit_tt_hov":     _rnd(net_exit_tt_hov,    2),
            "net_exit_tt_truck":   _rnd(net_exit_tt_truck,  2),
            "net_exit_spd_all":    _rnd(net_exit_spd_all,   2),
            "net_exit_spd_car":    _rnd(net_exit_spd_car,   2),
            "net_exit_spd_bus":    _rnd(net_exit_spd_bus,   2),
            "net_exit_spd_hov":    _rnd(net_exit_spd_hov,   2),
            "net_exit_spd_truck":  _rnd(net_exit_spd_truck, 2),
            "net_stop_time_all":   _rnd(net_stop_time_all,  2),
            "net_stop_time_car":   _rnd(net_stop_time_car,  2),
            "net_stop_time_bus":   _rnd(net_stop_time_bus,  2),
            "net_stop_time_truck": _rnd(net_stop_time_truck,2),
            "net_num_stops_all":   _rnd(net_num_stops_all,  3),
            "net_num_stops_car":   _rnd(net_num_stops_car,  3),
            "net_num_stops_bus":   _rnd(net_num_stops_bus,  3),
            "net_num_stops_truck": _rnd(net_num_stops_truck,3),
            "net_total_dist_all":  _rnd(net_total_dist_all,  1),
            "net_total_dist_car":  _rnd(net_total_dist_car,  1),
            "net_total_dist_bus":  _rnd(net_total_dist_bus,  1),
            "net_total_dist_truck":_rnd(net_total_dist_truck,1),
            "net_total_tt_h_all":  _rnd(net_total_tt_h_all,  2),
            "net_total_tt_h_car":  _rnd(net_total_tt_h_car,  2),
            "net_total_tt_h_bus":  _rnd(net_total_tt_h_bus,  2),
            "net_total_tt_h_truck":_rnd(net_total_tt_h_truck,2),
            "net_exit_count_all":  _rnd(net_exit_count_all,  0),
            "net_exit_count_car":  _rnd(net_exit_count_car,  0),
            "net_exit_count_bus":  _rnd(net_exit_count_bus,  0),
            "net_exit_count_truck":_rnd(net_exit_count_truck,0),
            "net_input_flow_all":  _rnd(net_input_flow_all,  0),
            "net_input_flow_car":  _rnd(net_input_flow_car,  0),
            "net_input_flow_bus":  _rnd(net_input_flow_bus,  0),
            "net_input_flow_truck":_rnd(net_input_flow_truck,0),
            "net_exit_flow_all":   _rnd(net_exit_flow_all,   0),
            "net_exit_flow_car":   _rnd(net_exit_flow_car,   0),
            "net_exit_flow_bus":   _rnd(net_exit_flow_bus,   0),
            "net_exit_flow_truck": _rnd(net_exit_flow_truck, 0),
            "net_total_lc_all":    _rnd(net_total_lc_all,    0),
            "net_total_lc_car":    _rnd(net_total_lc_car,    0),
            "net_total_lc_bus":    _rnd(net_total_lc_bus,    0),
            "net_total_lc_truck":  _rnd(net_total_lc_truck,  0),
            "net_mean_queue_all":  _rnd(net_mean_queue_all,  1),
            "net_mean_queue_car":  _rnd(net_mean_queue_car,  1),
            "net_mean_queue_bus":  _rnd(net_mean_queue_bus,  1),
            "net_mean_queue_truck":_rnd(net_mean_queue_truck,1),
            "net_max_queue_all":   _rnd(net_max_queue_all,   1),
            "net_max_queue_car":   _rnd(net_max_queue_car,   1),
            "net_max_queue_bus":   _rnd(net_max_queue_bus,   1),
            "net_max_queue_truck": _rnd(net_max_queue_truck, 1),
            "net_vq_avg_all":      _rnd(net_vq_avg_all,      1),
            "net_vq_avg_bus":      _rnd(net_vq_avg_bus,      1),
            "net_vq_max_all":      _rnd(net_vq_max_all,      1),
            "net_wait_vq_all":     _rnd(net_wait_vq_all,     1),
            "net_wait_vq_bus":     _rnd(net_wait_vq_bus,     1),
            # coordination pre-arm (only non-zero for GROUP_BASED with CorridorCoordinator)
            "prearm_fired":    _int(prearm_fired),
            "prearm_success":  _int(prearm_success),
            "prearm_missed":   _int(prearm_missed),
            "prearm_expired":  _int(prearm_expired),
            "prearm_discarded":_int(prearm_discarded),
            "prearm_late_success": _int(prearm_late_success),
            "prearm_late_delay_s": _rnd(prearm_late_delay_s, 1),
            "prearm_success_rate_pct": _rnd(
              (100.0 * float(prearm_success) / float(prearm_fired))
              if (prearm_fired not in (None, 0, 0.0) and prearm_success is not None)
              else None,
              1,
            ),
            "avg_extension_s": _rnd(avg_extension_s, 1),
            "avg_insertion_s": _rnd(avg_insertion_s, 1),
            "avg_insertion_wait_s": _rnd(avg_insertion_wait_s, 1),
            "tsp_natural_green_rate_pct": _rnd(
              (100.0 * float(det_pair_stats.get("green_pair_count", 0))
               / float(det_pair_stats.get("pair_count", 0)))
              if (det_pair_stats.get("pair_count", 0) not in (None, 0, 0.0))
              else None,
              1,
            ),
            # green wave
            "mean_green":  mean_green,
            "mean_green_focus": mean_green_focus,
            "green_rates": green_rates_all,
            "green_rates_focus": green_rates_focus,
            # per-intersection breakdown (list of dicts, one per junction)
            "per_inter":   per_inter,
            # per-section density/speed/flow (list of dicts, one per section)
            "per_section": per_section,
            # per-bus corridor journeys (list of {vid, stops:[{jct,t,on_green,x,y}]})
            "bus_journeys": bus_journeys,
            # detection snapshots for decision-space overlay
            "phase_samples": phase_samples,
            # objective trace rows (decision evaluation / skip / action)
            "objective_trace": objective_trace,
            # reward-cycle rows (state-action-reward decomposition per candidate)
            "reward_cycle": reward_cycle,
            # continuous bus position tracking (list of {t,vid,x,y,jct,dist,in_zone,zone_r,event})
            "bus_tracking": bus_tracking,
            # focus priority history (list of {start_t, end_t, veh_id, jct_id, outcome, held_s})
            "focus_history": focus_history,
            "focus_bus_ids": sorted(focus_bus_ids),
            # queue snapshots (list of {t, jct, buses_in_zone, queue_main, queue_side, queue_total, tsp_state})
            "queue_snapshots": queue_snapshots,
            # per-approach entry-point snapshots (list of {t, jct, main_dir, main_veh, sides:{key:n_veh}})
            "queue_entry_snapshots": queue_entry_snapshots,
            # DYNAOPAC decisions (list of {t, jct, before_dur, extensions, delays, best_ext, applied, ...})
            "dynaropac_decisions": dynaropac_decisions,
            # TSP_Paper objectives (Z1–Z4 + weighted total, from wobj_* batch_results columns)
            "wobj_Z1":    _rnd(wobj_Z1,    0),
            "wobj_Z2":    _rnd(wobj_Z2,    1),
            "wobj_Z3":    _rnd(wobj_Z3,    0),
            "wobj_Z4":    _rnd(wobj_Z4,    1),
            "wobj_total": _rnd(wobj_total, 0),
            "bus_predictor": bus_predictor,
        }
        runs_data.append(run_obj)

    # ── Ordered junction list ─────────────────────────────────────────────────
    # Restrict to the 12 intersections defined in INTERSECTIONS_CONFIG only.
    # Data from detections / bus tracking may include junctions outside the
    # controlled corridor — exclude those to keep the dashboard focused.
    _cfg_jct_set = set(_ALL_CONFIG_JCTS) if _ALL_CONFIG_JCTS else None
    jct_list = sorted(
        int(j) for j in all_jct_ids
        if str(j).lstrip("-").isdigit()
        and (_cfg_jct_set is None or str(j) in _cfg_jct_set)
        and not (12000 <= int(j) <= 21999)
    )
    try:
        from plot_green_wave import _geographic_junction_order as _gjo
        jct_list = [j for j in _gjo({j: (0, j) for j in jct_list}, jct_list)]
    except Exception:
        pass

    # ── Compute delta vs NORMAL baseline ────────────────────────────────────
    normal_run = None
    for r in runs_data:
        if r["strategy"].upper() == "NORMAL":
            normal_run = r
            break
    if normal_run is None and runs_data:
        normal_run = runs_data[0]   # fall back to first row

    LOWER_IS_BETTER = {"total_delay", "main_delay", "side_delay", "bus_tt",
                        "avg_bus_delay", "avg_car_delay", "avg_truck_delay", "density", "density_all",
                        "net_delay_all", "net_delay_car", "net_delay_bus", "net_delay_truck",
                        "net_entry_delay_all", "net_exit_delay_all",
                        "net_entry_delay_car", "net_exit_delay_car",
                        "net_entry_delay_bus", "net_exit_delay_bus",
                        "net_entry_delay_truck", "net_exit_delay_truck",
                        "avg_main_delay_per_hr", "avg_side_delay_per_hr", "avg_total_delay_per_hr",
                        "tracked_only_bus_count"}
    HIGHER_IS_BETTER = {"speed", "flow", "tsp_det_unique", "mean_green",
                        "tracked_bus_count", "tracking_coverage_pct"}
    DELTA_KEYS = list(LOWER_IS_BETTER | HIGHER_IS_BETTER)

    for r in runs_data:
        delta = {}
        for k in DELTA_KEYS:
            base = normal_run.get(k)
            val  = r.get(k)
            if base is None or val is None or abs(base) < 1e-9:
                delta[k] = None
                continue
            pct = (val - base) / abs(base) * 100.0
            # For lower-is-better: negative pct = improvement (flip sign so +ve = good)
            if k in LOWER_IS_BETTER:
                pct = -pct
            delta[k] = round(pct, 1)
        r["delta"] = delta

    # ── Suppress all-zero or all-identical fields ────────────────────────────
    # Only suppress density/speed/flow if ALL values are zero AND the run data
    # also lacks the stats_Net_* columns (indicates stats collection failed).
    # When values differ across runs (even if some are 0), keep them visible.
    suppress_fields: set = set()
    for k in ["density", "speed", "flow", "mean_green"]:
        vals = [r.get(k) for r in runs_data]
        non_none = [v for v in vals if v is not None]
        if not non_none:
            # No data at all — suppress
            suppress_fields.add(k)
            print(f"[dashboard] Suppressing '{k}' — no data in any run")
        elif _all_zero(non_none) and _all_same(non_none):
            # All zero AND all identical — suppress (stats broken)
            suppress_fields.add(k)
            print(f"[dashboard] Suppressing '{k}' — all zero/identical: {vals}")
        else:
            print(f"[dashboard] Keeping '{k}': {vals}")

    # Collect all unique intersection IDs from per_inter data
    all_inter_ids_set: set = set()
    for r in runs_data:
        for pi in r.get("per_inter", []):
            all_inter_ids_set.add(str(pi["iid"]))
    try:
        all_inter_ids_sorted = sorted(all_inter_ids_set, key=lambda x: int(x))
    except Exception:
        all_inter_ids_sorted = sorted(all_inter_ids_set)

    # Whether any coordinated run exists (used to decide if pre-arm section shows)
    has_coordinated = any(r.get("coordinated") for r in runs_data)

    # Derive junction centroid coordinates from detection snapshots first, then
    # fall back to continuous tracking rows near each junction.
    jct_coords = {}
    for r in runs_data:
        for j in r.get("bus_journeys", []):
            for s in j.get("stops", []):
                jid = str(s["jct"])
                if s.get("x") and s.get("y"):
                    jct_coords.setdefault(jid, {"sx": 0, "sy": 0, "n": 0})
                    jct_coords[jid]["sx"] += s["x"]
                    jct_coords[jid]["sy"] += s["y"]
                    jct_coords[jid]["n"]  += 1
        for p in r.get("bus_tracking", []):
            jid = str(p.get("jct", ""))
            if not jid or jid in ("-1", "0"):
                continue
            x = _flt(p.get("x"))
            y = _flt(p.get("y"))
            if x is None or y is None:
                continue
            in_zone = _intish(p.get("in_zone", 0), 0)
            event = str(p.get("event", "track") or "track")
            if not in_zone and event not in ("zone_enter", "zone_exit", "nearest_jct_change"):
                continue
            weight = 2 if in_zone else 1
            jct_coords.setdefault(jid, {"sx": 0, "sy": 0, "n": 0})
            jct_coords[jid]["sx"] += x * weight
            jct_coords[jid]["sy"] += y * weight
            jct_coords[jid]["n"]  += weight
    jct_positions = {}
    for jid, v in jct_coords.items():
        if v["n"] > 0:
            jct_positions[jid] = {
                "x": round(v["sx"] / v["n"], 1),
                "y": round(v["sy"] / v["n"], 1),
            }

    # Enrich with accurate centroid positions from junction_centroids_*.csv
    # (written by AAPIFinish). Centroid positions take priority over bus-tracking
    # weighted averages because they are derived from the junction model geometry.
    centroid_positions = _load_junction_centroids(log_dir)
    for jid, pos in centroid_positions.items():
        jct_positions[jid] = pos

    return {
        "generated":       datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "runs":            runs_data,
        "junctions":       [str(j) for j in jct_list],
        "intersections":   all_inter_ids_sorted,
        "suppress":        list(suppress_fields),
        "normal_label":    normal_run.get("label") if normal_run else None,
        "delta_keys":      DELTA_KEYS,
        "lower_is_better": list(LOWER_IS_BETTER),
        "has_coordinated": has_coordinated,
        "jct_positions":   jct_positions,
        # Active junctions = TSP-controlled (have SignalGroupIDList in INTERSECTIONS_CONFIG)
        # Passive junctions = detection-zone only (fixed signal timing, no TSP)
        "active_jcts":     _ACTIVE_JCTS,
        "passive_jcts":    _PASSIVE_JCTS,
        "signal_plans":    _signal_plan_rows(),
    }


def _rnd(v, decimals):
    if v is None:
        return None
    try:
        return round(float(v), decimals)
    except (TypeError, ValueError):
        return None


def _int(v):
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# =============================================================================
# HTML template (self-contained, Chart.js CDN)
# =============================================================================

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kelvin Grove TSP — Simulation Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<style>
:root {
  --bg: #0d0d1e; --bg2: #13132b; --bg3: #1a1a35;
  --border: #2a2a50; --text: #cccce8; --muted: #7070a0;
  --green: #00e676; --orange: #ffb300; --red: #ff5252;
  --blue: #29b6f6; --purple: #ab47bc; --cyan: #26c6da;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text);
       font-family: 'Segoe UI', sans-serif; font-size: 14px; padding: 16px; }
h1  { font-size: 1.6rem; color: #e8e8ff; margin-bottom: 4px; }
.subtitle { color: var(--muted); font-size: 0.88rem; margin-bottom: 20px; }
.grid   { display: grid; gap: 18px; }
.grid-2 { grid-template-columns: 1fr 1fr; }
.grid-3 { grid-template-columns: 1fr 1fr 1fr; }
.card   { background: var(--bg2); border: 1px solid var(--border);
          border-radius: 10px; padding: 16px; }
.card h2 { font-size: 1.05rem; color: #b0b0e0; margin-bottom: 12px;
           border-bottom: 1px solid var(--border); padding-bottom: 6px; }
canvas { max-width: 100%; }
/* KPI row */
.kpi-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
.kpi { flex: 1 1 150px; background: var(--bg3); border: 1px solid var(--border);
       border-radius: 8px; padding: 12px 16px; }
.kpi .label { font-size: 0.72rem; color: var(--muted); text-transform: uppercase;
               letter-spacing: 0.05em; }
.kpi .val   { font-size: 1.45rem; font-weight: 700; color: #e8e8ff; margin-top: 2px; }
.kpi .unit  { font-size: 0.72rem; color: var(--muted); }
.kpi.improved { border-color: #00e67660; }
.kpi.worse    { border-color: #ff525260; }
/* Run selector */
.run-tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.run-tab  { padding: 5px 14px; border-radius: 20px; border: 1px solid var(--border);
             cursor: pointer; font-size: 13px; background: var(--bg3);
             color: var(--muted); transition: all 0.15s; }
.run-tab.active { background: #1a2a40; color: var(--blue); border-color: var(--blue); }
/* Table */
.tbl-wrap { overflow-x: auto; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
th { background: #0a0a22; color: #9090cc; padding: 7px 10px;
     text-align: left; border-bottom: 2px solid var(--border);
     white-space: nowrap; position: sticky; top: 0; z-index: 1; }
td { padding: 6px 10px; border-bottom: 1px solid #1e1e38; white-space: nowrap; }
tr:hover td { background: #1a1a30; }
.best  { color: var(--green); font-weight: 700; }
.worst { color: var(--red); }
.tag   { display: inline-block; padding: 2px 8px; border-radius: 12px;
         font-size: 11px; font-weight: 600; }
.tag-coord { background: #1b3b28; color: var(--green); }
.tag-indep { background: #2b1a10; color: var(--orange); }
/* Coord flow */
.flow { display: flex; align-items: center; overflow-x: auto; margin-top: 8px; }
.flow-jct { text-align: center; min-width: 80px; }
.flow-jct .name { font-size: 11px; color: var(--muted); }
.flow-jct .bubble { width: 48px; height: 48px; border-radius: 50%;
                    display: flex; align-items: center; justify-content: center;
                    font-size: 13px; font-weight: 700; margin: 4px auto; }
.bubble-g { background: #00e67620; border: 2px solid var(--green); color: var(--green); }
.bubble-o { background: #ffb30020; border: 2px solid var(--orange); color: var(--orange); }
.bubble-r { background: #ff525220; border: 2px solid var(--red); color: var(--red); }
/* Prearm fired but priority not activated — signal was aware, chose not to intervene */
.bubble-p { background: #ab47bc20; border: 2px dashed var(--purple); color: var(--purple); }
/* Detected + TSP evaluated but not optimal — harmony decided not worth extending, phase ended */
.bubble-y { background: #f9a82520; border: 2px dashed #f9a825; color: #f9a825; }
/* Delay-optimisation skip: orange with slash symbol (legacy, now replaced by bubble-p) */
.bubble-opt { background: #ffb30015; border: 2px dashed var(--orange); color: var(--orange); }
/* Per-bus route view: junctions not on this bus's route */
.bubble-skip { background: transparent; border: 1px dashed #444; color: #444; font-size: 18px; }
/* Fixed-signal junctions (detection-zone only, no TSP control) */
.bubble-f { background: #1a1210; border: 2px solid #6b4c20; color: #b08040; font-size: 10px; }
/* Focus bus banner */
.focus-banner { display:inline-block; background:#f1c40f20; border:1px solid #f1c40f60;
                color:#f1c40f; border-radius:6px; padding:2px 10px; font-size:11px;
                font-weight:700; margin-right:8px; vertical-align:middle; }
.flow-jct-skip { opacity: 0.35; }
.flow-arrow { font-size: 20px; color: var(--muted); min-width: 24px; text-align: center; }
.flow-arrow-skip { opacity: 0.2; }
/* Delta badge */
.delta-pos { color: var(--green); font-size: 11px; }
.delta-neg { color: var(--red);   font-size: 11px; }
.delta-na  { color: var(--muted); font-size: 11px; }
/* Section header */
.section-hdr { color: var(--muted); font-size: 0.75rem; text-transform: uppercase;
                letter-spacing: 0.08em; margin: 20px 0 8px; }
</style>
</head>
<body>

<h1>🚌 Kelvin Grove TSP — Simulation Comparison Dashboard</h1>
<p class="subtitle" id="gen-time"></p>

TEMPLATE_FALLBACK_HTML

<!-- ── KPI summary (vs NORMAL baseline) ─────────────────────────────── -->
<div id="kpi-row" class="kpi-row"></div>

<!-- ── Audience summary (decision quality) ───────────────────────────── -->
<p class="section-hdr">Audience Summary <span style="font-size:0.8rem;color:var(--muted)">(action quality and reward sanity)</span></p>
<div id="audience-kpi-row" class="kpi-row"></div>

<!-- ── Charts row 1: Delays ──────────────────────────────────────────── -->
<!-- ── TSP_Paper 4-Objective Summary ──────────────────────────────────── -->
<p class="section-hdr">TSP Objectives (Z1–Z4) <span style="font-size:0.78rem;color:var(--muted)">(from TSP_Paper weighted objective; lower is better for all four)</span></p>
<div class="card" id="objectives-card">
  <div style="font-size:11px;color:var(--muted);margin-bottom:8px">
    <b>Z1</b> Total passenger delay (bus + car, pax·s) &nbsp;·&nbsp;
    <b>Z2</b> Flow-weighted bandwidth (maximise) &nbsp;·&nbsp;
    <b>Z3</b> Total bus lateness Σσ⁺ (s) &nbsp;·&nbsp;
    <b>Z4</b> Corridor travel time (s).
    Values normalised to NO_TSP baseline (NO_TSP = 100%). Missing bars = no objective data for that run.
  </div>
  <div style="font-size:10px;color:#ff9966;background:#1a0a00;border-left:3px solid #ff9966;padding:8px;margin-bottom:12px">
    <b>Trade-offs:</b> TSP improves Z1 (passenger delay) but Z4 (total veh·h) typically increases 10–20% due to car delays. Z2 is not comparable: NO_TSP includes 334 natural-green detections, while TSP has 0 (forced intervention breaks pattern).
  </div>
  <canvas id="chart-objectives" height="240"></canvas>
  <div id="objectives-na" style="display:none;margin-top:8px;font-size:11px;color:#b08080">No wobj_Z* data found — run a batch with PREDICTOR_SWEEP_ENABLED=True to populate.</div>
  <!-- Raw Z1–Z4 values table -->
  <div style="margin-top:14px;overflow-x:auto">
    <div style="font-size:10px;color:#7777aa;margin-bottom:4px">
      <span style="color:#64dc78;font-weight:700">★ green bold</span> = best across all experiments &nbsp;·&nbsp;
      <span style="color:#f05050">red</span> = worst &nbsp;·&nbsp;
      Z1 ↓ min &nbsp;·&nbsp; Z2 ↑ max &nbsp;·&nbsp; Z3 ↓ min &nbsp;·&nbsp; Z4 ↓ min
    </div>
    <table id="raw-z-table" style="width:100%;border-collapse:collapse;font-size:10.5px;color:#c0c0e0">
      <thead>
        <tr style="border-bottom:1px solid #333355;color:#8888cc">
          <th style="text-align:left;padding:4px 8px">Experiment</th>
          <th style="text-align:right;padding:4px 8px">Z1 Pax Delay ↓</th>
          <th style="text-align:right;padding:4px 8px">Z2 Bandwidth ↑</th>
          <th style="text-align:right;padding:4px 8px">Z3 Lateness ↓</th>
          <th style="text-align:right;padding:4px 8px">Z4 Travel Time ↓</th>
          <th style="text-align:right;padding:4px 8px">Weighted Obj</th>
          <th style="text-align:right;padding:4px 8px">Avg Delay ↓</th>
          <th style="text-align:right;padding:4px 8px">Flow (veh)</th>
          <th style="text-align:right;padding:4px 8px">Insertions</th>
        </tr>
      </thead>
      <tbody id="raw-z-tbody"></tbody>
    </table>
  </div>
</div>

<p class="section-hdr">Predictor Comparison <span style="font-size:0.78rem;color:var(--muted)">(KALMAN / ADAPTIVE_KALMAN / LSTM_SS across algorithms — avg passenger delay s/pax)</span></p>
<div class="card" id="predictor-card">
  <div style="font-size:11px;color:var(--muted);margin-bottom:8px">
    Grouped by TSP algorithm, each group shows three bars (one per predictor). Lower = better.
    Only PRED_* experiments are shown.
  </div>
  <canvas id="chart-predictor-delay" height="240"></canvas>
  <div id="predictor-na" style="display:none;margin-top:8px;font-size:11px;color:#b08080">No PRED_* experiment data found — enable PREDICTOR_SWEEP_ENABLED and re-run the batch.</div>
</div>

<p class="section-hdr">Delay Metrics</p>
<div id="dynaopac-delay-note" style="display:none;margin-bottom:10px;padding:8px 12px;background:#1a1a38;border-left:3px solid #f0a020;border-radius:4px;font-size:12px;color:#c0c0e0">
  <strong>DYNAOPAC note:</strong> DYNAOPAC uses the <em>same GroupBased phase-based controller as HARMONY</em> — it is
  <em>not</em> a different signal algorithm. Both run the same phase sequencer; DYNAOPAC's label refers to the DynaROPAC
  person-delay objective guiding coordination decisions (pre-arm timing, GE/insertion eligibility), applied in 1-second
  increments. Because results are computed from the same phase-based engine, any difference between DYNAOPAC and HARMONY
  is due to coordination strategy, not a different signal model.
  If avg bus delay appears <strong>higher</strong> than HARMONY but total pax delay is similar, check bus passage counts:
  fewer buses completing approach sections (faster clearance due to TSP) lowers the denominator, inflating the average.
  Use <em>Bus Total Travel Time (hrs)</em> alongside avg bus delay to interpret results correctly.
</div>
<div class="grid grid-2">
  <div class="card">
    <h2>Total Passenger Delay (hrs)</h2>
    <canvas id="chart-delay-hrs" height="240"></canvas>
    <div id="delay-hrs-na" style="display:none;padding:12px;font-size:12px;color:#b08080;border:1px solid #3a1a1a;border-radius:6px;margin-top:8px">
      <strong>Data not available for this batch.</strong><br>
      Delay metrics require <code>simulation_results.csv</code> which is written at the end of each
      simulation run. These runs either used a short simulation period or the file was not written.<br>
      <em>Run a full simulation with the current code to populate these metrics.</em>
    </div>
  </div>
  <div class="card">
    <h2>Per-Passenger Delays (seconds)</h2>
    <canvas id="chart-delay-s" height="240"></canvas>
    <div id="delay-s-na" style="display:none;padding:12px;font-size:12px;color:#b08080;border:1px solid #3a1a1a;border-radius:6px;margin-top:8px">
      <strong>Data not available.</strong> Requires <code>AvgBusPassDelay_s</code> / <code>AvgCarPassDelay_s</code>
      from <code>simulation_results.csv</code>. See note above.
    </div>
  </div>
</div>

<!-- ── Charts row 1b: Main-road vs side-street delay breakdown ─────── -->
<p class="section-hdr">Delay Breakdown — Main Corridor vs Side Streets</p>
<div class="grid grid-2">
  <div class="card">
    <h2>Bus Delay vs Car Delay (s/pax)</h2>
    <div style="font-size:11px;color:var(--muted);margin-bottom:6px">Average per-passenger delay in seconds. Bus passengers include PT occupancy weighting.</div>
    <canvas id="chart-bus-car-delay" height="220"></canvas>
    <div id="bus-car-delay-na" style="display:none;padding:10px;font-size:11px;color:#b08080">No avg bus/car delay data available.</div>
  </div>
  <div class="card">
    <h2>Main vs Side Pax Delay (pax·h)</h2>
    <div style="font-size:11px;color:var(--muted);margin-bottom:6px">Total passenger delay on main corridor vs side streets. Larger gap between runs = more side-street reduction.</div>
    <canvas id="chart-main-side-delay" height="220"></canvas>
    <div id="main-side-delay-na" style="display:none;padding:10px;font-size:11px;color:#b08080">No main/side delay data available.</div>
  </div>
</div>


<p class="section-hdr">% Improvement vs NORMAL Baseline <span id="baseline-note" style="font-size:0.8rem;color:var(--muted)"></span></p>
<div class="card">
  <canvas id="chart-delta" height="180"></canvas>
</div>

<!-- ── Charts row 3: TSP events + Green rate ─────────────────────────── -->
<p class="section-hdr">TSP & Signal Performance</p>
<div class="grid grid-2">
  <div class="card">
    <h2>TSP Detection Outcomes (stacked by result)</h2>
    <div style="font-size:11px;color:var(--muted);margin-bottom:8px">
      Primary KPI view uses unique bus×junction detections only.
      Raw skip/no-action counters remain available in diagnostics tables.
    </div>
    <canvas id="chart-tsp" height="260"></canvas>
  </div>
  <div class="card">
    <h2>Green Arrival Rate by Junction (%)</h2>
    <canvas id="chart-green" height="240"></canvas>
  </div>
</div>

<div class="card" id="card-tsp-outcome">
  <h2>TSP Priority Outcome (raw events per run)</h2>
  <div style="font-size:11px;color:var(--muted);margin-bottom:8px">
    Detected buses split by decision outcome: granted extension/insertion, denied by delay objective,
    naturally on green, or no action in NORMAL mode.
  </div>
  <canvas id="chart-tsp-outcome" height="260"></canvas>
</div>

<!-- ── Charts row 4: Network + Bus TT ───────────────────────────────── -->
<p class="section-hdr">Network Metrics</p>
<div class="grid grid-2">
  <div class="card" id="card-flow">
    <h2>Network Flow (veh/h)</h2>
    <canvas id="chart-flow" height="220"></canvas>
  </div>
  <div class="card" id="card-density">
    <h2>Network Density (veh/km/lane)</h2>
    <canvas id="chart-density" height="220"></canvas>
  </div>
  <div class="card">
    <h2>Bus Total Travel Time (hrs)</h2>
    <div style="font-size:11px;color:var(--muted);margin-bottom:6px">
      Sum of all bus zone-crossing times across all monitored junctions. TSP can make this
      <em>higher</em> than the baseline because: (1) faster buses complete more corridor
      traversals in the same simulation window, adding more trips to the sum; (2) buses
      arriving at additional junctions get detected and counted. The per-passenger delay
      metrics (below) are the correct indicator of TSP benefit.
    </div>
    <canvas id="chart-bus-tt" height="220"></canvas>
  </div>
  <div class="card" id="card-speed">
    <h2>Network Speed (km/h)</h2>
    <canvas id="chart-speed" height="220"></canvas>
  </div>
  <div class="card" id="card-pax-delay">
    <h2>Avg Delay per Passenger (s)</h2>
    <div style="font-size:11px;color:var(--muted);margin-bottom:6px">
      All-passenger, bus-passenger, and car-passenger average delay.
      TSP improves bus/all-pax delay at the cost of slightly higher car delay —
      this is why network speed may appear lower under coordinated TSP.
    </div>
    <canvas id="chart-pax-delay" height="220"></canvas>
  </div>
  <div class="card" id="card-volume">
    <h2>Total Volume (pax-equivalent passages)</h2>
    <div style="font-size:11px;color:var(--muted);margin-bottom:6px">
      Stacked bars show the passenger-equivalent denominator used by AvgPassDelay.
      The line is Net_TotalFlowVeh, so you can see whether lower delay came from lower demand.
    </div>
    <canvas id="chart-volume" height="220"></canvas>
  </div>
</div>

<!-- ── Coordination pre-arm outcomes ─────────────────────────────────── -->
<p class="section-hdr">Coordination Pre-arm Outcomes <span style="font-size:0.78rem;color:var(--muted)">(coordinated runs only — requires COORDINATED_TSP=True)</span></p>
<div class="card" id="card-prearm">
  <canvas id="chart-prearm" height="160"></canvas>
  <div id="prearm-note" style="color:var(--muted);font-size:12px;margin-top:8px;display:none"></div>
</div>

<div class="card" id="card-wave-chain" style="margin-top:10px">
  <h2>Corridor Adjustment Chain (event counts)</h2>
  <canvas id="chart-wave-chain" height="170"></canvas>
</div>

<!-- ── Harmony timing averages ───────────────────────────────────────── -->
<p class="section-hdr">Harmony TSP Timing — Average Durations per Action</p>
<div class="card">
  <canvas id="chart-harmony-timing" height="160"></canvas>
  <div id="harmony-timing-note" style="color:var(--muted);font-size:12px;margin-top:8px;display:none"></div>
</div>

<!-- ── No-action reason breakdown ─────────────────────────────────────── -->
<p class="section-hdr">No-Action Reasons by Junction <span style="font-size:0.78rem;color:var(--muted)">(stacked counts from harmony decision rows)</span></p>
<div class="card" id="card-noaction-reasons">
  <div class="run-tabs" id="noaction-run-tabs"></div>
  <div style="margin-top:4px;margin-bottom:4px;font-size:11px;color:var(--muted)">
    <label>Sample rows:
      <select id="noaction-sample-mode" style="font-size:11px;padding:1px 4px">
        <option value="earliest" selected>Earliest</option>
        <option value="latest">Latest</option>
        <option value="both">Both (earliest + latest)</option>
      </select>
    </label>
    <button id="noaction-export-btn" style="margin-left:12px;font-size:11px;padding:2px 8px">Export selected as CSV</button>
  </div>
  <canvas id="chart-noaction-reasons" height="220"></canvas>
  <div id="noaction-reasons-note" style="color:var(--muted);font-size:12px;margin-top:8px;display:none"></div>
  <div id="noaction-reasons-drilldown" style="margin-top:8px;display:none">
    <div id="noaction-reasons-drilldown-title" style="font-size:11px;color:var(--muted);margin-bottom:6px"></div>
    <div class="tbl-wrap">
      <table id="noaction-reasons-drilldown-table">
        <thead></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ── Run selector / Coord flow ─────────────────────────────────────── -->
<p class="section-hdr">Corridor Coordination Flow <span style="font-size:0.78rem;color:var(--muted)">(bubble % = downstream green-rate, not prearm success; adaptive bands per run)</span></p>
<div class="card">
  <div class="run-tabs" id="run-tabs"></div>
  <div style="margin-top:4px;margin-bottom:4px;font-size:11px;color:var(--muted)">
    <label>Bus filter: <select id="bus-flow-select" style="font-size:11px;padding:1px 4px"><option value="">All buses (aggregate)</option></select></label>
    <label style="margin-left:12px">Bands:
      <select id="coord-band-mode" style="font-size:11px;padding:1px 4px">
        <option value="adaptive" selected>Adaptive (per run)</option>
        <option value="fixed">Fixed (green>=55, amber>=30)</option>
      </select>
    </label>
  </div>
  <div class="flow" id="coord-flow"></div>
</div>

<!-- ── Bus Journey Corridor Map (time-space) ─────────────────────────── -->
<p class="section-hdr">Bus Corridor Journeys <span style="font-size:0.78rem;color:var(--muted)">(time-space diagram)</span></p>
<div class="card">
  <div class="run-tabs" id="journey-run-tabs"></div>
  <div style="margin-top:6px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-size:11px;color:var(--muted)">
    <label><input type="checkbox" id="jrn-filter-full" checked> Full corridor (≥6 jcts)</label>
    <label><input type="checkbox" id="jrn-filter-partial" checked> Partial (3-5 jcts)</label>
    <label><input type="checkbox" id="jrn-filter-short"> Short (2 jcts)</label>
    <label><input type="checkbox" id="jrn-filter-prearm"> Only buses with prearm events</label>
  </div>
  <div style="margin-top:8px;font-size:11px;color:var(--muted)" id="journey-no-data" style="display:none">No bus journey data available for this run.</div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="journey-canvas" height="500" style="width:100%;min-width:700px"></canvas>
  </div>
  <div style="margin-top:6px;font-size:11px;color:var(--muted)">
    Each line = one bus traversing the corridor. Line slope shows speed (steeper = slower).<br>
    <span style="color:#2ecc71">●</span> arrived on green &nbsp;
    <span style="color:#e74c3c">●</span> arrived on red &nbsp;
    <span style="color:#f1c40f">◆</span> prearm fired (junction received preparation signal) &nbsp;
    <span style="color:#2ecc71">★</span> prearm success (junction prepared extension window) &nbsp;
    <span style="color:#e74c3c">✕</span> prearm missed &nbsp;
    <span style="color:#3498db">▸</span> grant<br>
    <span style="font-weight:bold;color:#e8e8ff">━</span> full corridor &nbsp;
    <span style="font-weight:bold;color:#888">─ ─</span> partial &nbsp;
    <span style="color:#555">· · ·</span> short<br>
    <span style="color:var(--muted)">Note: multiple prearm events per bus/junction = ETA recalculations; a successful prearm does not guarantee green arrival if the bus misses the window.</span>
  </div>
</div>

<!-- ── Coordination Example ───────────────────────────────────────────── -->
<p class="section-hdr">Coordination Example <span style="font-size:0.78rem;color:var(--muted)">(select a bus to see its exact journey: pre-arm timing, signal phase at arrival, TSP actions)</span></p>
<div class="card">
  <div class="run-tabs" id="coordex-run-tabs"></div>
  <div style="margin-top:6px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-size:11px;color:var(--muted)">
    <label>Bus: <select id="coordex-bus-select" style="font-size:11px;padding:1px 4px"><option value="">— select a bus —</option></select></label>
    <span id="coordex-bus-info" style="font-size:11px;color:var(--muted)"></span>
  </div>
  <div style="margin-top:8px;font-size:11px;color:var(--muted)" id="coordex-no-data">Select a bus to see the coordination example.</div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="coordex-canvas" height="360" style="width:100%;min-width:700px;display:none"></canvas>
  </div>
  <!-- ── Reward breakdown for selected bus ────────────────────────────── -->
  <div id="coordex-reward-wrap" style="display:none;margin-top:10px">
    <div style="font-size:11px;font-weight:600;color:var(--muted);margin-bottom:4px">
      DCTSP Reward Breakdown — all candidates at each junction for selected bus
      <span style="font-weight:400;color:#666">(requires reward_cycle CSV — from DCTSP_MARL/MDN/ZIG runs)</span>
    </div>
    <div style="overflow-x:auto">
      <table id="coordex-reward-table" style="font-size:10px;border-collapse:collapse;width:100%;min-width:700px">
        <thead>
          <tr style="color:#7070a0;border-bottom:1px solid #222">
            <th style="text-align:left;padding:3px 6px">Junction</th>
            <th style="text-align:right;padding:3px 6px">Sim t (s)</th>
            <th style="text-align:right;padding:3px 6px">Bus ETA</th>
            <th style="text-align:right;padding:3px 6px">σ_in</th>
            <th style="text-align:right;padding:3px 6px" title="bus delay (s) / total intersection pax·s under no strategy">No-Act Delay</th>
            <th style="text-align:right;padding:3px 6px">NO_ACTION r</th>
            <th style="text-align:right;padding:3px 6px" title="reward / bus pax·s saved / car pax·s cost">GE_5</th>
            <th style="text-align:right;padding:3px 6px" title="reward / bus pax·s saved / car pax·s cost">GE_10</th>
            <th style="text-align:right;padding:3px 6px" title="reward / bus pax·s saved / car pax·s cost">GE_15</th>
            <th style="text-align:right;padding:3px 6px" title="green realloc (zero car cost) — reward / bus pax·s saved">GR_5</th>
            <th style="text-align:right;padding:3px 6px" title="green realloc (zero car cost) — reward / bus pax·s saved">GR_10</th>
            <th style="text-align:right;padding:3px 6px" title="green realloc (zero car cost) — reward / bus pax·s saved">GR_15</th>
            <th style="text-align:right;padding:3px 6px" title="reward / bus pax·s saved / car pax·s cost">INS_10</th>
            <th style="text-align:right;padding:3px 6px" title="reward / bus pax·s saved / car pax·s cost">INS_15</th>
            <th style="text-align:right;padding:3px 6px" title="reward / bus pax·s saved / car pax·s cost">INS_20</th>
            <th style="text-align:right;padding:3px 6px" title="reward / bus pax·s saved / car pax·s cost">ER_10</th>
            <th style="text-align:right;padding:3px 6px" title="reward / bus pax·s saved / car pax·s cost">ER_20</th>
            <th style="text-align:right;padding:3px 6px" title="reward / bus pax·s saved / car pax·s cost">ER_30</th>
            <th style="text-align:right;padding:3px 6px" title="bus-phase early-red — reward / bus pax·s saved / car pax·s cost">ER_BP_10</th>
            <th style="text-align:right;padding:3px 6px" title="bus-phase early-red — reward / bus pax·s saved / car pax·s cost">ER_BP_20</th>
            <th style="text-align:right;padding:3px 6px" title="bus-phase early-red — reward / bus pax·s saved / car pax·s cost">ER_BP_30</th>
            <th style="text-align:left;padding:3px 6px">★ Chosen</th>
          </tr>
        </thead>
        <tbody id="coordex-reward-tbody"></tbody>
      </table>
    </div>
    <div id="coordex-reward-no-data" style="font-size:11px;color:var(--muted);display:none">No reward_cycle data for this bus (run a DCTSP_MARL/MDN experiment to populate).</div>
  </div>
  <div style="margin-top:6px;font-size:11px;color:var(--muted)">
    <strong>How to read:</strong> X-axis = simulation time. Each horizontal band = one corridor junction.<br>
    <span style="background:#1a4a1a;padding:0 4px">&#9608;</span> bus phase green window &nbsp;
    <span style="background:#4a1a1a;padding:0 4px">&#9608;</span> red/other phases &nbsp;
    <span style="color:#f1c40f">◆ prearm issued</span> &nbsp;
    <span style="color:#2ecc71">★ prearm success</span> &nbsp;
    <span style="color:#e74c3c">✕ prearm missed</span> &nbsp;
    <span style="color:#3498db">▸ bus granted</span> &nbsp;
    <span style="color:#aaa">● bus arrived</span> (green=on green, red=on red)<br>
    <strong style="color:var(--orange)">⚠ Prearm interpretation:</strong>
    <span style="color:var(--muted)">
      "Prearm issued" = corridor sent a preparation signal to the downstream junction.
      "Prearm success" = that junction acknowledged and prepared an extension window.
      A bus can still arrive on <span style="color:var(--red)">red</span> after a prearm success if:
      (1) it arrived before or after the prepared window (ETA prediction error),
      (2) the extension ran out before arrival, or
      (3) a later bus was given priority.
      Multiple "prearm issued" events for the same bus/junction are re-firings due to
      ETA recalculation as the bus gets closer — only the final outcome matters.
    </span>
  </div>
</div>

<!-- ── Corridor Spatial Map ──────────────────────────────────────────── -->
<p class="section-hdr">Corridor Spatial Map <span style="font-size:0.78rem;color:var(--muted)">(junction positions &amp; per-bus observed paths)</span></p>
<div class="card">
  <div class="run-tabs" id="spatmap-run-tabs"></div>
  <div style="margin-top:4px;margin-bottom:4px;font-size:11px;color:var(--muted)">
    <label>Bus: <select id="spatmap-bus-select" style="font-size:11px;padding:1px 4px"><option value="">All buses</option></select></label>
    <label style="margin-left:12px"><input type="checkbox" id="spatmap-show-corridor" checked> Show corridor spine</label>
    <label style="margin-left:12px"><input type="checkbox" id="spatmap-show-green" checked> Colour by green/red</label>
  </div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="spatmap-canvas" height="500" style="width:100%;min-width:500px"></canvas>
  </div>
  <div style="margin-top:6px;font-size:11px;color:var(--muted)">
    <span style="color:#3498db">■</span> junction &nbsp;
    <span style="color:#2ecc71">●</span> stop on green &nbsp;
    <span style="color:#e74c3c">●</span> stop on red &nbsp;
    <span style="color:#8e44ad">━</span> bus path &nbsp;
    <span style="color:#555;text-decoration:underline dotted">┄</span> corridor spine
  </div>
</div>

<!-- ── Per-intersection breakdown ────────────────────────────────────── -->
<p class="section-hdr">Bus Position Tracking <span style="font-size:0.78rem;color:var(--muted)">(continuous PT bus locations &amp; detection zone proximity)</span></p>
<div class="card">
  <div class="run-tabs" id="bustrack-run-tabs"></div>
  <div style="margin-top:4px;margin-bottom:4px;font-size:11px;color:var(--muted)">
    <label>Bus: <select id="bustrack-bus-select" style="font-size:11px;padding:1px 4px"><option value="">All buses</option></select></label>
    <label style="margin-left:12px">Junction: <select id="bustrack-jct-select" style="font-size:11px;padding:1px 4px"><option value="">Nearest</option></select></label>
    <label style="margin-left:12px">Distance mode:
      <select id="bustrack-ref-mode" style="font-size:11px;padding:1px 4px">
        <option value="nearest">Nearest junction (dynamic)</option>
        <option value="selected">Selected junction (absolute)</option>
        <option value="corridor" selected>Corridor position (all intersections)</option>
      </select>
    </label>
    <label style="margin-left:12px">Range:
      <select id="bustrack-range-mode" style="font-size:11px;padding:1px 4px">
        <option value="relevant" selected>Relevant (near/intersection influence)</option>
        <option value="all">All distances</option>
      </select>
    </label>
  </div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="bustrack-canvas" height="400" style="width:100%;min-width:500px"></canvas>
  </div>
  <div style="margin-top:6px;font-size:11px;color:var(--muted)">
    <span style="color:#2ecc71">■</span> in detection zone &nbsp;
    <span style="color:#e74c3c">■</span> outside zone &nbsp;
    <span style="color:#f39c12">▲</span> zone enter &nbsp;
    <span style="color:#9b59b6">▼</span> zone exit &nbsp;
    <span style="color:#ccc;text-decoration:dashed">---</span> zone radius
  </div>
  <div style="margin-top:4px;font-size:11px;color:var(--muted)" id="bustrack-summary"></div>
</div>

<!-- ── Queue Lengths & Delay Over Time ───────────────────────────────── -->
<p class="section-hdr">Queue Lengths &amp; Delay Over Time <span style="font-size:0.78rem;color:var(--muted)">(60-second snapshots, all intersections — queue here is a local controller snapshot, not an Aimsun network mean-queue statistic)</span></p>
<div class="card">
  <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-size:11px;color:var(--muted)">
    <label>Run:
      <select id="queue-run-sel" style="font-size:11px"></select>
    </label>
    <label>Junction:
      <select id="queue-jct-sel" style="font-size:11px"><option value="">All</option></select>
    </label>
    <label><input type="checkbox" id="queue-show-buses" checked> Overlay buses in zone</label>
    <label><input type="checkbox" id="queue-show-delay"> Overlay cumulative delay (pax-s)</label>
  </div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="queue-canvas" height="300" style="width:100%;min-width:500px"></canvas>
  </div>
  <div style="margin-top:6px;font-size:11px;color:var(--muted)">
    Solid lines = local queue snapshot per junction (left y-axis, vehicles). Coloured dashed lines = buses in detection zone per junction (right y-axis).<br>
    Dotted lines = cumulative pax-seconds delay per junction (right y-axis, ÷1000) when delay overlay is enabled.<br>
    White dashed line = total PT buses on the corridor network (right y-axis) — this is the ground truth of how many buses exist at each moment.<br>
    Each colour = one junction. TSP state background bands: blue=GE, purple=INS.
  </div>
</div>

<!-- ── Queue per Entry-Point Approach ────────────────────────────── -->
<p class="section-hdr">Queue per Entry-Point Approach <span style="font-size:0.78rem;color:var(--muted)">(vehicles queued on each incoming section, labelled by NB/EB/SB/WB approach direction)</span></p>
<div class="card">
  <div class="run-tabs" id="queue-entry-run-tabs"></div>
  <div id="queue-entry-no-data" style="margin-top:8px;font-size:11px;color:var(--muted)">No per-approach queue data available for this run.</div>
  <div id="queue-entry-container" style="margin-top:8px"></div>
  <div style="margin-top:6px;font-size:11px;color:var(--muted)">
    One line per entry-point section. White = bus approach (main). Coloured lines = side approaches.
    Labels show direction (NB/EB/SB/WB) and section ID in parentheses. Y-axis = vehicles queued (instantaneous controller snapshot, 60-second intervals).
  </div>
</div>

<!-- ── Global Bus Focus Priority History ─────────────────────────────── -->
<p class="section-hdr">Global Bus Focus Priority <span style="font-size:0.78rem;color:var(--muted)">(one bus gets exclusive corridor-wide priority until it completes or times out)</span></p>
<div class="card">
  <div class="run-tabs" id="focus-run-tabs"></div>
  <div style="margin-top:8px;font-size:11px;color:var(--muted)" id="focus-no-data">No focus history data available for this run.</div>
  <div class="tbl-wrap" style="margin-top:8px">
    <table id="focus-table"><thead></thead><tbody></tbody></table>
  </div>
  <div style="margin-top:4px;font-size:11px;color:var(--muted)" id="focus-summary"></div>
</div>

<!-- ── Per-Bus Corridor KPI Comparison ───────────────────────────── -->
<p class="section-hdr">Per-Bus Corridor KPI Comparison <span style="font-size:0.78rem;color:var(--muted)">(priority-granted buses are a hard-case subset, not a random sample)</span></p>
<div class="card">
  <div class="run-tabs" id="buscomp-run-tabs"></div>
  <div style="margin-top:4px;font-size:11px;color:var(--muted)">
    <strong style="color:var(--green)">Blue bars</strong> = buses that received at least one priority grant in the coordinated run &nbsp;|&nbsp;
    <strong style="color:var(--orange)">Orange bars</strong> = buses that never received priority &nbsp;|&nbsp;
    Corridor delay = sum of per-junction stop-times for that bus across the run.<br>
    <span style="color:var(--muted)">Important: priority buses are usually the late / hard cases that triggered TSP, so they can still have worse raw delay than the non-priority group. Use the same-bus cross-experiment comparison below to judge benefit.</span>
  </div>
  <div style="display:flex;gap:12px;margin-top:8px;flex-wrap:wrap;font-size:11px;color:var(--muted)">
    <label><input type="checkbox" id="buscomp-show-delay" checked> Total corridor delay (s)</label>
    <label><input type="checkbox" id="buscomp-show-tt" checked> Total travel time (s)</label>
    <label><input type="checkbox" id="buscomp-show-count" checked> Priority grants per junction</label>
  </div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="buscomp-canvas" height="280" style="width:100%;min-width:420px"></canvas>
  </div>
  <div id="buscomp-no-data" style="margin-top:8px;font-size:11px;color:var(--muted)">No bus journey data available for this run.</div>
  <div id="buscomp-summary" style="margin-top:6px;font-size:11px;color:var(--muted)"></div>
</div>

<!-- ── Decision Space (TSP Corridor Timeline) ─────────────────────── -->
<p class="section-hdr">Decision Space <span style="font-size:0.78rem;color:var(--muted)">(when each junction is under TSP control and how long until it returns to normal)</span></p>
<div class="card">
  <div class="run-tabs" id="decision-run-tabs"></div>
  <div style="margin-top:4px;margin-bottom:4px;font-size:11px;color:var(--muted)">
    <label><input type="checkbox" id="decision-show-phase" checked> Show signal snapshots (green/red)</label>
    <label style="margin-left:12px"><input type="checkbox" id="decision-show-focus" checked> Highlight tracked focus-bus arrivals</label>
    <label style="margin-left:12px"><input type="checkbox" id="decision-show-lines" checked> Show tracked bus trajectories</label>
  </div>
  <div style="margin-top:8px;font-size:11px;color:var(--muted)" id="decision-no-data">No TSP focus history available for this run.</div>
  <div style="margin-top:4px;font-size:11px;color:var(--muted)" id="decision-summary"></div>
  <canvas id="decision-chart" style="display:none;width:100%;max-height:340px"></canvas>
  <div style="margin-top:6px;font-size:10.5px;color:var(--muted)">
    Bars show TSP-held duration at each junction. Extension = blue, Insertion = purple, other = orange.
    Gap between bars = time until next TSP event at that junction (normal operation window).<br>
    Dashed lines = tracked bus trajectories across the corridor; dots/triangles show green/red phase snapshots and focus-bus arrivals.
  </div>
</div>

<!-- ── Per-intersection breakdown ────────────────────────────────────── -->
<p class="section-hdr">Signal Timing Comparison <span style="font-size:0.78rem;color:var(--muted)">(all runs — main vs side green/red within the signal cycle)</span></p>
<div class="card">
  <div style="margin-top:4px;margin-bottom:8px;font-size:11px;color:var(--muted)">
    Each row shows where the main and side entries sit in the nominal cycle. Green/red bars include second markers at the cycle boundaries; right columns show run-specific green/red arrival samples and TSP action counts.
  </div>
  <div class="tbl-wrap">
    <table id="signal-timing-table"><thead></thead><tbody></tbody></table>
  </div>
</div>

<p class="section-hdr">Per-Intersection Breakdown <span style="font-size:0.78rem;color:var(--muted)">(select run above; combines position tracking, controller detections, and focus history)</span></p>
<div class="card">
  <div class="run-tabs" id="inter-run-tabs"></div>
  <div style="margin-top:8px;font-size:11px;color:var(--muted)" id="inter-no-data" style="display:none">No per-intersection data available for this run.</div>
  <div class="tbl-wrap" style="margin-top:8px">
    <table id="inter-table"><thead></thead><tbody></tbody></table>
  </div>
</div>

<!-- ── Delay by Junction (all runs) ──────────────────────────────────── -->
<p class="section-hdr">Junction Metrics <span style="font-size:0.78rem;color:var(--muted)">(all runs overlaid — passenger delay, bus coverage, and corridor performance by junction)</span></p>
<div class="card">
  <div style="margin-top:4px;margin-bottom:4px;font-size:11px;color:var(--muted)">
    <label>Metric:
      <select id="jct-delay-metric" style="font-size:11px;padding:1px 4px">
        <option value="total_delay">Total delay (hrs)</option>
        <option value="main_delay">Main delay (hrs)</option>
        <option value="side_delay">Side delay (hrs)</option>
        <option value="avg_main_delay_per_hr">Main avg delay/sim-hr (pax·h/h)</option>
        <option value="avg_side_delay_per_hr">Side avg delay/sim-hr (pax·h/h)</option>
        <option value="avg_total_delay_per_hr">Total avg delay/sim-hr (pax·h/h)</option>
        <option value="avg_bus_delay">Avg bus delay (s)</option>
        <option value="avg_car_delay">Avg car delay (s)</option>
        <option value="avg_truck_delay">Avg truck delay (s)</option>
        <option value="distinct_buses">Distinct buses (stats)</option>
        <option value="tracked_buses">Known buses (union of all sources)</option>
        <option value="position_tracked_buses">Position-tracked buses (GPS scan)</option>
        <option value="detected_buses">TSP-detected buses (proximity trigger)</option>
        <option value="tracked_only_buses">Pos-tracked only — not TSP-triggered (tracking gap)</option>
        <option value="coverage_pct">TSP coverage of position-tracked buses (%)</option>
        <option value="focus_buses">Focus (global-tracked) buses</option>
        <option value="bus_passages">Bus passages</option>
        <option value="avg_density">Density (veh/km/lane)</option>
        <option value="avg_speed">Speed (km/h)</option>
        <option value="avg_flow">Flow (v/h)</option>
        <option value="avg_queue">Queue (veh)</option>
      </select>
    </label>
    <label style="margin-left:12px"><input type="checkbox" id="jct-delay-compare" checked> Compare all runs</label>
  </div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="jct-delay-canvas" height="280" style="width:100%;min-width:500px"></canvas>
  </div>
  <div style="margin-top:4px;font-size:11px;color:var(--muted)">
    Each group = one corridor junction. Bars = runs (colour coded). Hover for exact values.
    <strong>Metric notes:</strong>
    "Position-tracked buses" = buses scanned by continuous PT position tracking (GPS-style).
    "TSP-detected buses" = buses that triggered a TSP proximity event at this junction.
    "Pos-tracked only" = buses seen by position scan but never triggered TSP — indicates a detection gap.
    "Proximity detections unique" = unique (bus, junction) pairs in the detection log, which can exceed "TSP trigger events" because proximity scans are logged before any TSP decision is made.
    Lower is better for delay/density/queue; higher is better for speed/flow/coverage.
  </div>
</div>

<!-- ── Per-section (corridor) breakdown ──────────────────────────────── -->
<p class="section-hdr">Per-Section Density / Speed / Flow <span style="font-size:0.78rem;color:var(--muted)">(Aimsun section-stat style, select run above)</span></p>
<div class="card">
  <div class="run-tabs" id="sec-run-tabs"></div>
  <div style="margin-top:6px;padding:6px 10px;background:#1a1a30;border-radius:4px;font-size:11px;color:#9090cc">
    <strong>Note:</strong> These rows are intended to read like Aimsun section statistics:
    density is vehicles per kilometer of lane, flow is vehicles per hour, speed is section speed, and queue is a time-averaged queue measure.
    Low approach speeds during peak are still expected because queued vehicles dominate the section state near signals.
  </div>
  <div style="margin-top:8px;font-size:11px;color:var(--muted)" id="sec-no-data" style="display:none">No per-section data available for this run.</div>
  <div class="tbl-wrap" style="margin-top:8px">
    <table id="sec-table"><thead></thead><tbody></tbody></table>
  </div>
</div>

<!-- ── Same-Bus Cross-Experiment Comparison ──────────────────────────── -->
<p class="section-hdr">Same-Bus Cross-Experiment Comparison <span style="font-size:0.78rem;color:var(--muted)">(buses granted GE or Phase Insertion in the Coordinated run, tracked across all run types)</span></p>
<div class="card">
  <div style="margin-top:4px;font-size:11px;color:var(--muted)">
    Compares the same bus vehicle IDs that were granted priority in TSP runs against their behaviour in the NORMAL (no-TSP) baseline.
    Green extensions granted = junctions where the bus received a priority action. Red arrivals = junctions where the bus hit a red.
  </div>
  <div id="xcomp-no-data" style="margin-top:8px;font-size:11px;color:var(--muted)">Requires ≥2 runs including a NORMAL baseline.</div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="xcomp-canvas" height="240" style="width:100%;min-width:420px;display:none"></canvas>
  </div>
  <div style="overflow-x:auto;margin-top:16px">
    <h3 style="font-size:13px;color:var(--muted);margin:0 0 6px">Same-Bus Red-Phase Arrival Count</h3>
    <div style="font-size:11px;color:var(--muted);margin-bottom:6px">
      Each bar = number of corridor junctions where the bus arrived on red, for the <strong>same bus ID</strong>
      across all three strategies. The green/yellow right-axis bars show how many fewer red stops the bus had
      with TSP vs No-TSP — <strong>positive = improvement, negative = TSP made it worse for this bus</strong>.<br>
      <strong>Cohort note:</strong> these buses received GE or INS in the coordinated run — they are the hardest
      cases (late arrivals, poor wave alignment). Their raw red-stop count in NO_TSP is therefore higher than
      the average bus. The <em>delta</em> (right axis) is the fair measure of TSP benefit.
    </div>
    <canvas id="xcomp-delay-canvas" height="200" style="width:100%;min-width:420px;display:none"></canvas>
    <div id="xcomp-delay-no-data" style="font-size:11px;color:var(--muted);display:none"></div>
  </div>
</div>

<!-- ── Reward State-Action Diagnostics ───────────────────────────────── -->
<p class="section-hdr">Reward State-Action Diagnostics <span style="font-size:0.78rem;color:var(--muted)">(actual reward per action: INV_DELAY/V2X = 1/(cost+ε) ∈ (0,1]; MARL = Δpax·s)</span></p>
<div class="card" id="reward-section">
  <div class="run-tabs" id="reward-run-tabs"></div>
  <!-- View mode toggle -->
  <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
    <button id="reward-mode-jct" class="run-tab active" style="font-size:11px;padding:3px 10px">By Junction</button>
    <button id="reward-mode-bus" class="run-tab" style="font-size:11px;padding:3px 10px">By Bus Journey</button>
  </div>
  <!-- Junction-mode controls -->
  <div id="reward-jct-controls" style="display:flex;gap:12px;margin-top:6px;flex-wrap:wrap;font-size:11px;color:var(--muted)">
    <label>Junction: <select id="reward-jct-sel" style="font-size:11px"><option value="">All</option></select></label>
    <label><input type="checkbox" id="reward-only-chosen"> Chosen actions only</label>
  </div>
  <!-- Bus-journey-mode controls -->
  <div id="reward-bus-controls" style="display:none;gap:12px;margin-top:6px;flex-wrap:wrap;font-size:11px;color:var(--muted)">
    <label>Bus (veh_id): <select id="reward-bus-sel" style="font-size:11px"><option value="">All buses</option></select></label>
    <label><input type="checkbox" id="reward-bus-all-cands"> Show all candidates (not just chosen)</label>
  </div>
  <div style="margin-top:6px;font-size:11px;color:var(--muted)">
    <span id="reward-mode-hint">Actual reward value per candidate action. INV_DELAY/V2X: higher = better (0–1 scale). MARL: positive = TSP improved passenger delay. NO_ACTION baseline shown as a separate series.</span>
  </div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="reward-canvas" height="250" style="width:100%;min-width:420px"></canvas>
  </div>
  <div id="reward-no-data" style="margin-top:8px;font-size:11px;color:var(--muted)">No reward_cycle data found (run a DCTSP experiment to populate — DCTSP_MARL, DCTSP_INV_DELAY, or DCTSP_V2X).</div>
</div>

<!-- ── MDN Delay Calibration ─────────────────────────────────────────── -->
<p class="section-hdr">Delay Calibration <span style="font-size:0.78rem;color:var(--muted)">(predicted bus delay vs actual headway change — seconds; for well-calibrated models these should align on NO_ACTION rows)</span></p>
<div class="card" id="mdn-calib-section">
  <div class="run-tabs" id="mdn-calib-run-tabs"></div>
  <div style="display:flex;gap:12px;margin-top:6px;flex-wrap:wrap;font-size:11px;color:var(--muted)">
    <label>Junction: <select id="mdn-calib-jct-sel" style="font-size:11px"><option value="">All junctions</option></select></label>
    <label><input type="checkbox" id="mdn-calib-chosen-only"> Chosen actions only</label>
  </div>
  <div style="margin-top:4px;font-size:11px;color:var(--muted)">
    <span style="color:#4ecdc4">&#9632;</span> Predicted bus delay — no action (s)&nbsp;&nbsp;
    <span style="color:#9b59b6">&#9632;</span> Incoming headway σ_in (s)&nbsp;&nbsp;
    <span style="color:#64dc78">&#9675;</span> Actual Δheadway σ_out−σ_in: INS&nbsp;
    <span style="color:#4ecdc4">&#9675;</span> GE&nbsp;
    <span style="color:#ff9f43">&#9675;</span> EARLY_RED&nbsp;
    <span style="color:#a0a0c8">&#9675;</span> NO_ACTION
  </div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="mdn-calib-canvas" height="260" style="width:100%;min-width:420px"></canvas>
  </div>
  <div id="mdn-calib-no-data" style="margin-top:8px;font-size:11px;color:var(--muted)">No MDN calibration data — run a DCTSP_MDN experiment to populate.</div>
</div>

<!-- ── Delay Method Validation ──────────────────────────────────────── -->
<p class="section-hdr">Delay Method Validation <span style="font-size:0.78rem;color:var(--muted)">(top: cross-traffic model vs Aimsun measured pax·s — bottom: D/D/1 &amp; MB bus delay vs kinematic reference)</span></p>
<div class="card" id="delay-val-section">
  <div class="run-tabs" id="delay-val-run-tabs"></div>
  <div style="display:flex;gap:12px;margin-top:6px;flex-wrap:wrap;font-size:11px;color:var(--muted)">
    <label>Junction: <select id="delay-val-jct-sel" style="font-size:11px"><option value="">All junctions</option></select></label>
    <label><input type="checkbox" id="delay-val-dd1" checked> D/D/1 queue</label>
    <label><input type="checkbox" id="delay-val-mb" checked> Moving bottleneck</label>
  </div>
  <div style="margin-top:4px;font-size:11px;color:var(--muted)">
    <b>Top:</b> X = actual total car delay pax·s (Δ measured_car_pax_s_cumul between consecutive NO_ACTION events per junction, time-normalised to bp_dur window).
    Y = cross-traffic cost model pax·s, <b>NF=1 raw triangle</b> (<code>other_delay_model_pax_s_nf1</code>).
    If well-calibrated, points should follow the 45° line.
    <em>Note: NF (NETWORK_FACTOR) is a decision bias applied in reward calculations, not a calibration target —
    older dashboards showed the NF-amplified value (4–5× for ZIG/INV_DELAY) which caused apparent over-prediction.</em>
    <br><b>Bottom:</b> X = kinematic bus delay (s, reference). Y = D/D/1 or moving-bottleneck alternative estimate.
  </div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="delay-val-canvas" height="280" style="width:100%;min-width:420px"></canvas>
  </div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="delay-val-canvas2" height="240" style="width:100%;min-width:420px"></canvas>
  </div>
  <div id="delay-val-no-data" style="margin-top:8px;font-size:11px;color:var(--muted)">No delay validation data — run any DCTSP experiment with dd1_delay_s / mb_delay_s columns.</div>
</div>

<!-- ── MDN Phase Delay Decomposition ────────────────────────────────── -->
<p class="section-hdr">Phase Delay Decomposition <span style="font-size:0.78rem;color:var(--muted)">(per-detection: bus-phase vs cross-traffic predicted pax·s — inspect MDN reward signal accuracy per phase)</span></p>
<div class="card" id="mdn-phase-section">
  <div class="run-tabs" id="mdn-phase-run-tabs"></div>
  <div style="display:flex;gap:12px;margin-top:6px;flex-wrap:wrap;font-size:11px;color:var(--muted)">
    <label>Junction: <select id="mdn-phase-jct-sel" style="font-size:11px"><option value="">All junctions</option></select></label>
  </div>
  <div style="margin-top:4px;font-size:11px;color:var(--muted)">
    Each bar group = one bus detection. Left pair = NO_ACTION total (bus phase pax·s in cyan / cross-traffic in grey).
    Right pair = chosen action (bus saved in green / cross-traffic cost in red).
    <strong style="color:#ffd632">Reward = bus_saved − car_cost</strong>.
    Bus phase pax·s = <code>no_act_delay_s × bus_occ</code>.  Cross-traffic = <code>NA_total − bus_phase</code>.
  </div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="mdn-phase-canvas" height="260" style="width:100%;min-width:420px"></canvas>
  </div>
  <div id="mdn-phase-no-data" style="margin-top:8px;font-size:11px;color:var(--muted)">No phase decomposition data — run a DCTSP_MDN/ZIG experiment with reward_cycle CSV to populate.</div>
</div>

<!-- ── DYNAOPAC Phase Optimisation Decisions ─────────────────────────── -->
<p class="section-hdr">DYNAOPAC Phase Optimisation <span style="font-size:0.78rem;color:var(--muted)">(delay vs green-extension candidates searched each step — only visible for DYNAOPAC_HARMONY runs)</span></p>
<div class="card" id="dynaropac-section">
  <div class="run-tabs" id="dyn-run-tabs"></div>
  <div style="display:flex;gap:12px;margin-top:6px;flex-wrap:wrap;font-size:11px;color:var(--muted)">
    <label>Junction: <select id="dyn-jct-sel" style="font-size:11px"><option value="">All (avg)</option></select></label>
    <label><input type="checkbox" id="dyn-show-applied" checked> Highlight applied decisions</label>
  </div>
  <div style="overflow-x:auto;margin-top:8px">
    <canvas id="dyn-canvas" height="260" style="width:100%;min-width:420px"></canvas>
  </div>
  <div id="dyn-no-data" style="margin-top:8px;font-size:11px;color:var(--muted)">No DYNAOPAC decision data (run a DYNAOPAC_HARMONY experiment to populate).</div>
  <div style="margin-top:6px;font-size:11px;color:var(--muted)">
    Each point = one phase-duration search step. X-axis = extension tried (s). Y-axis = total person-delay for that duration.
    Orange dashed line = no-action baseline. Stars = applied decisions. Hover for junction and time detail.
  </div>
</div>

<!-- ── Aimsun-format Network Statistics ───────────────────────────────── -->
<p class="section-hdr">Network Statistics <span style="font-size:0.78rem;color:var(--muted)">(Aimsun-format — network density, entry-based delay/flow/speed, and corridor passenger-delay overlays)</span></p>
<div class="card">
  <div style="margin-bottom:8px;padding:6px 10px;background:#1a1028;border-left:3px solid #9b59b6;border-radius:4px;font-size:11px;color:#b090cc">
    <strong>Important:</strong> Network statistics require a <strong>new simulation run</strong>
    to reflect the corrected collection logic. Values from older runs may still contain zeros or older fallback approximations.
    NORMAL run reference values are shown in the <em>Notes</em> column.
  </div>
  <div style="margin-bottom:8px;font-size:11px;color:var(--muted)">
    Values shown follow Aimsun's statistical definitions as closely as this dashboard can reproduce from the available outputs.
    Entry-Based metrics refer to vehicles that entered during the interval, including vehicles still inside at the end of the interval where Aimsun defines them that way.
    Density is reported per kilometer of lane. N/A = not collected for this run.
  </div>
  <div class="tbl-wrap">
    <table id="aimsun-stats-table"><thead></thead><tbody></tbody></table>
  </div>
</div>

<!-- ── Full results table ─────────────────────────────────────────────── -->
<p class="section-hdr">Full Results Table</p>
<div class="card">
  <div class="tbl-wrap">
    <table id="results-table"><thead></thead><tbody></tbody></table>
  </div>
</div>

<script>
// ── Embedded data ─────────────────────────────────────────────────────────
const DATA = TEMPLATE_DATA_JSON;

// ── Helpers ───────────────────────────────────────────────────────────────
const runs    = DATA.runs;
const jcts    = DATA.junctions;
const inters  = DATA.intersections || [];
const SUPP    = new Set(DATA.suppress || []);
const NORMAL_LABEL = DATA.normal_label;
const LIB     = new Set(DATA.lower_is_better || []);
const HAS_COORD = DATA.has_coordinated || false;
// Active junctions: TSP-controlled (SignalGroupIDList in config). Passive: fixed signal timing.
const ACTIVE_JCTS  = new Set((DATA.active_jcts  || []).map(String));
const PASSIVE_JCTS = new Set((DATA.passive_jcts || []).map(String));
const SIGNAL_PLANS = DATA.signal_plans || [];

document.getElementById('gen-time').textContent =
  `Generated ${DATA.generated}  •  ${runs.length} run(s)  •  ${jcts.length} corridor junction(s)`;
if (NORMAL_LABEL) {
  document.getElementById('baseline-note').textContent = `  (baseline: ${NORMAL_LABEL})`;
}

// ── Colour palette ────────────────────────────────────────────────────────
const PALETTE = [
  'rgba(41,182,246,0.82)',   // blue
  'rgba(0,230,118,0.82)',    // green
  'rgba(255,179,0,0.82)',    // amber
  'rgba(171,71,188,0.82)',   // purple
  'rgba(255,82,82,0.82)',    // red
  'rgba(38,198,218,0.82)',   // cyan
  'rgba(212,225,87,0.82)',   // lime
  'rgba(255,112,67,0.82)',   // orange
];
const PALETTE_EDGE = PALETTE.map(c => c.replace('0.82','1'));

function color(i)     { return PALETTE[i % PALETTE.length]; }
function colorEdge(i) { return PALETTE_EDGE[i % PALETTE.length]; }

const CHART_READY = (typeof window.Chart !== 'undefined');
if (!CHART_READY) {
  // Keep the rest of the dashboard functional when CDN/script loading is blocked.
  const warn = document.createElement('div');
  warn.style.cssText = 'margin:0 0 12px 0;padding:10px 12px;border:1px solid #6b4c20;border-radius:8px;background:#1a1210;color:#f0c080;font-size:12px;';
  warn.textContent = 'Chart.js failed to load (offline/CDN blocked). Summary charts are disabled, but tables and diagnostics remain available.';
  const anchor = document.querySelector('.kpi-row') || document.body.firstChild;
  if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(warn, anchor);

  window.Chart = function() {
    return { destroy() {} };
  };
  window.Chart.defaults = { font: {} };
}

Chart.defaults.color = '#9090cc';
Chart.defaults.borderColor = '#2a2a50';
Chart.defaults.font.family = "'Segoe UI', sans-serif";

const SCALE_X = { ticks:{color:'#9090cc'}, grid:{color:'#1e1e38'} };
const SCALE_Y = { ticks:{color:'#9090cc'}, grid:{color:'#1e1e38'} };

function barChart(id, labels, datasets, extraOpts={}) {
  const ctx = document.getElementById(id);
  if (!ctx) return null;
  return new Chart(ctx.getContext('2d'), {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color:'#aaaacc', font:{size:11} } },
        tooltip: { backgroundColor:'#0a0a22', titleColor:'#ccccee',
                   bodyColor:'#9090cc', borderColor:'#2a2a50', borderWidth:1 }
      },
      scales: { x: SCALE_X, y: SCALE_Y },
      ...extraOpts
    }
  });
}

// ── Show DYNAOPAC delay note when any DYNAOPAC run is present ────────────
{
  const hasDynaopac = runs.some(r => (r.label || '').toUpperCase().includes('DYNAOPAC'));
  const noteEl = document.getElementById('dynaopac-delay-note');
  if (noteEl && hasDynaopac) noteEl.style.display = 'block';
}

// ── TSP_Paper 4-Objective bar chart (Z1–Z4 normalised to NO_TSP) ────────────
{
  // Find NO_TSP baseline (first run with label containing 'NO_TSP' or NORMAL strategy)
  const baseRun = runs.find(r => (r.exp_name || '').toUpperCase().includes('NO_TSP')
                               || (r.strategy || '').toUpperCase() === 'NORMAL');
  const z1Base = baseRun ? Number(baseRun.wobj_Z1) : null;
  const z2Base = baseRun ? Number(baseRun.wobj_Z2) : null;
  const z3Base = baseRun ? Number(baseRun.wobj_Z3) : null;
  const z4Base = baseRun ? Number(baseRun.wobj_Z4) : null;
  const hasObjData = runs.some(r => r.wobj_Z1 != null);
  const objNa = document.getElementById('objectives-na');
  const objCv = document.getElementById('chart-objectives');
  if (!hasObjData) {
    if (objNa) objNa.style.display = '';
    if (objCv) objCv.style.display = 'none';
  } else {
    const norm = (v, base) => (v != null && base != null && base !== 0)
      ? Math.round(Number(v) / base * 100) : null;
    const Z1_COL = 'rgba(244,67,54,0.72)';
    const Z2_COL = 'rgba(255,152,0,0.72)';
    const Z3_COL = 'rgba(33,150,243,0.72)';
    const Z4_COL = 'rgba(76,175,80,0.72)';
    new Chart(objCv, {
      type: 'bar',
      data: {
        labels: runs.map(r => r.label),
        datasets: [
          { label: 'Z1 Pax Delay', data: runs.map(r => norm(r.wobj_Z1, z1Base)),
            backgroundColor: Z1_COL, borderColor: Z1_COL.replace('0.72','1'), borderWidth:1 },
          { label: 'Z2 Bandwidth', data: runs.map(r => norm(r.wobj_Z2, z2Base)),
            backgroundColor: Z2_COL, borderColor: Z2_COL.replace('0.72','1'), borderWidth:1 },
          { label: 'Z3 Total Lateness', data: runs.map(r => norm(r.wobj_Z3, z3Base)),
            backgroundColor: Z3_COL, borderColor: Z3_COL.replace('0.72','1'), borderWidth:1 },
          { label: 'Z4 Travel Time', data: runs.map(r => norm(r.wobj_Z4, z4Base)),
            backgroundColor: Z4_COL, borderColor: Z4_COL.replace('0.72','1'), borderWidth:1 },
        ],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { labels: { color: '#9090cc', font: { size: 10 } } },
          title: { display: true, text: 'Z1–Z4 normalised to NO_TSP baseline (100% = same as no-TSP)',
                   color: '#7070a0', font: { size: 11 } },
          tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y ?? 'N/A'}%` } },
          annotation: {
            annotations: {
              baseline: { type: 'line', yMin: 100, yMax: 100,
                borderColor: 'rgba(255,255,255,0.25)', borderWidth: 1, borderDash: [4,4] },
            },
          },
        },
        scales: {
          x: { ticks: { color: '#8080b0', font: { size: 10 }, maxRotation: 35 }, grid: { color: '#1a1a3a' } },
          y: { ticks: { color: '#8080b0', font: { size: 10 }, callback: v => v + '%' },
               grid: { color: '#1a1a3a' },
               title: { display: true, text: '% of NO_TSP', color: '#8080b0', font: { size: 10 } } },
        },
      },
    });
  }
}

// ── Raw Z1–Z4 values table ───────────────────────────────────────────────────
{
  const tbody = document.getElementById('raw-z-tbody');
  if (tbody) {
    const fmt = (v, dec=0) => {
      if (v == null || v === '' || isNaN(Number(v))) return '—';
      const n = Number(v);
      if (Math.abs(n) >= 1e6) return (n/1e6).toFixed(2) + 'M';
      if (Math.abs(n) >= 1e3) return (n/1e3).toFixed(1) + 'k';
      return n.toFixed(dec);
    };

    // ── Per-column global best/worst (across all experiments) ────────────────
    // Z1, Z3, Z4, delay: lower = better.  Z2: higher = better.
    const _nums = k => runs.map(r => r[k] != null ? Number(r[k]) : null).filter(v => v !== null && !isNaN(v));
    const _best = (k, lb) => { const vs = _nums(k); return vs.length ? (lb ? Math.min(...vs) : Math.max(...vs)) : null; };
    const bestZ1  = _best('wobj_Z1', true);
    const bestZ2  = _best('wobj_Z2', false);   // MAXIMISE
    const bestZ3  = _best('wobj_Z3', true);
    const bestZ4  = _best('wobj_Z4', true);
    const bestDel = _best('avg_pass_delay', true);
    const worstZ1 = _best('wobj_Z1', false);
    const worstZ2 = _best('wobj_Z2', true);
    const worstZ3 = _best('wobj_Z3', false);
    const worstZ4 = _best('wobj_Z4', false);
    const worstDel = _best('avg_pass_delay', false);

    // Colour helper: vs global best/worst (±1% tolerance)
    const cell = (v, best, worst, lb) => {
      if (v == null || best == null) return { style: '', star: '' };
      const eps = Math.abs(best) * 0.01;
      const isB = lb ? v <= best + eps : v >= best - eps;
      const isW = lb ? v >= worst - eps : v <= worst + eps;
      return {
        style: isB ? 'color:#64dc78;font-weight:700' : isW ? 'color:#f05050' : '',
        star: isB ? ' ★' : '',
      };
    };

    const rowHtml = runs.map(r => {
      const z1 = r.wobj_Z1 != null ? Number(r.wobj_Z1) : null;
      const z2 = r.wobj_Z2 != null ? Number(r.wobj_Z2) : null;
      const z3 = r.wobj_Z3 != null ? Number(r.wobj_Z3) : null;
      const z4 = r.wobj_Z4 != null ? Number(r.wobj_Z4) : null;
      const d  = r.avg_pass_delay != null ? Number(r.avg_pass_delay) : null;
      const cZ1 = cell(z1, bestZ1,  worstZ1,  true);
      const cZ2 = cell(z2, bestZ2,  worstZ2,  false);  // Z2: higher = better
      const cZ3 = cell(z3, bestZ3,  worstZ3,  true);
      const cZ4 = cell(z4, bestZ4,  worstZ4,  true);
      const cD  = cell(d,  bestDel, worstDel, true);
      return `<tr style="border-bottom:1px solid #1c1c3a">
        <td style="padding:3px 8px;font-weight:500">${r.label||r.exp_name||'—'}</td>
        <td style="text-align:right;padding:3px 8px;${cZ1.style}">${fmt(r.wobj_Z1)}${cZ1.star}</td>
        <td style="text-align:right;padding:3px 8px;${cZ2.style}">${fmt(r.wobj_Z2,1)}${cZ2.star}</td>
        <td style="text-align:right;padding:3px 8px;${cZ3.style}">${fmt(r.wobj_Z3,0)}${cZ3.star}</td>
        <td style="text-align:right;padding:3px 8px;${cZ4.style}">${fmt(r.wobj_Z4,1)}${cZ4.star}</td>
        <td style="text-align:right;padding:3px 8px">${fmt(r.wobj_total)}</td>
        <td style="text-align:right;padding:3px 8px;${cD.style}">${fmt(r.avg_pass_delay,1)}${cD.star}</td>
        <td style="text-align:right;padding:3px 8px">${fmt(r.flow,0)}</td>
        <td style="text-align:right;padding:3px 8px">${r.tsp_ins!=null?Number(r.tsp_ins):'—'}</td>
      </tr>`;
    }).join('');
    tbody.innerHTML = rowHtml;
  }
}

// ── Predictor comparison: PRED_* experiments grouped by algorithm ────────────
{
  const predRuns = runs.filter(r => (r.exp_name || '').toUpperCase().startsWith('PRED_'));
  const predNa = document.getElementById('predictor-na');
  const predCv = document.getElementById('chart-predictor-delay');
  if (!predRuns.length) {
    if (predNa) predNa.style.display = '';
    if (predCv) predCv.style.display = 'none';
  } else {
    // Extract unique algorithm labels from experiment name: PRED_{PREDICTOR}_{ALGO}
    const predTypes = ['KALMAN', 'ADAPTIVE_KALMAN', 'LSTM_SS'];
    const predColors = ['rgba(0,188,212,0.75)', 'rgba(255,152,0,0.75)', 'rgba(156,39,176,0.75)'];
    // Collect unique algo labels
    const algoSet = new Set();
    predRuns.forEach(r => {
      const parts = (r.exp_name || '').replace(/^PRED_/, '');
      const pIdx = predTypes.findIndex(p => parts.startsWith(p));
      if (pIdx >= 0) algoSet.add(parts.slice(predTypes[pIdx].length + 1));
    });
    const algos = [...algoSet].sort();
    const datasets = predTypes.map((pred, pi) => ({
      label: pred.replace('_', ' '),
      backgroundColor: predColors[pi],
      borderColor: predColors[pi].replace('0.75','1'),
      borderWidth: 1,
      data: algos.map(algo => {
        const r = predRuns.find(r => (r.exp_name||'').toUpperCase() === `PRED_${pred}_${algo}`.toUpperCase());
        return r ? (r.avg_pass_delay ?? null) : null;
      }),
    }));
    new Chart(predCv, {
      type: 'bar',
      data: { labels: algos, datasets },
      options: {
        responsive: true,
        plugins: {
          legend: { labels: { color: '#9090cc', font: { size: 10 } } },
          title: { display: true, text: 'Predictor type × TSP algorithm — avg passenger delay (s/pax)',
                   color: '#7070a0', font: { size: 11 } },
        },
        scales: {
          x: { ticks: { color: '#8080b0', font: { size: 10 } }, grid: { color: '#1a1a3a' } },
          y: { ticks: { color: '#8080b0', font: { size: 10 } }, grid: { color: '#1a1a3a' },
               title: { display: true, text: 'Avg delay (s/pax)', color: '#8080b0', font: { size: 10 } } },
        },
      },
    });
  }
}

// ── Delay chart (hrs) ────────────────────────────────────────────────────
{
  const hasDelayData = runs.some(r => r.total_delay !== null && r.total_delay !== undefined);
  const naEl = document.getElementById('delay-hrs-na');
  if (!hasDelayData) {
    if (naEl) naEl.style.display = '';
    // Hide canvas so it doesn't show an empty grey box
    const cv = document.getElementById('chart-delay-hrs');
    if (cv) cv.style.display = 'none';
  } else {
    barChart('chart-delay-hrs',
      ['Total pax delay', 'Main-street delay', 'Side-street delay'],
      runs.map((r,i) => ({
        label: r.label,
        data: [r.total_delay, r.main_delay, r.side_delay],
        backgroundColor: color(i), borderColor: colorEdge(i), borderWidth:1,
      }))
    );
  }
}

// ── Per-passenger delays (seconds) ───────────────────────────────────────
{
  const hasPerPaxData = runs.some(r => r.avg_bus_delay !== null && r.avg_bus_delay !== undefined);
  const naEl2 = document.getElementById('delay-s-na');
  if (!hasPerPaxData) {
    if (naEl2) naEl2.style.display = '';
    const cv2 = document.getElementById('chart-delay-s');
    if (cv2) cv2.style.display = 'none';
  } else {
    barChart('chart-delay-s',
      ['Avg bus delay (s)', 'Avg car delay (s)'],
      runs.map((r,i) => ({
        label: r.label,
        data: [r.avg_bus_delay, r.avg_car_delay],
        backgroundColor: color(i), borderColor: colorEdge(i), borderWidth:1,
      }))
    );
  }
}

// ── Bus vs Car delay grouped bar (new dedicated chart) ────────────────────
{
  const BUS_COL  = 'rgba(0,188,212,0.75)';
  const CAR_COL  = 'rgba(255,160,0,0.75)';
  const hasBusCarData = runs.some(r => r.avg_bus_delay != null || r.avg_car_delay != null);
  const bcNa = document.getElementById('bus-car-delay-na');
  const bcCv = document.getElementById('chart-bus-car-delay');
  if (!hasBusCarData) {
    if (bcNa) bcNa.style.display = '';
    if (bcCv) bcCv.style.display = 'none';
  } else {
    const runLabels = runs.map(r => r.label);
    new Chart(document.getElementById('chart-bus-car-delay').getContext('2d'), {
      type: 'bar',
      data: {
        labels: runLabels,
        datasets: [
          {
            label: 'Avg bus pax delay (s)',
            data: runs.map(r => r.avg_bus_delay ?? null),
            backgroundColor: BUS_COL, borderColor: BUS_COL, borderWidth: 1,
          },
          {
            label: 'Avg car pax delay (s)',
            data: runs.map(r => r.avg_car_delay ?? null),
            backgroundColor: CAR_COL, borderColor: CAR_COL, borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true, animation: false,
        plugins: {
          legend: { labels: { color: '#aaaacc', font: { size: 11 } } },
          tooltip: { backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc', borderColor: '#2a2a50', borderWidth: 1 },
        },
        scales: {
          x: SCALE_X,
          y: { ...SCALE_Y, title: { display: true, text: 's / pax', color: '#7070a0', font: { size: 11 } } },
        },
      },
    });
  }
}

// ── Main vs Side Pax Delay grouped bar ───────────────────────────────────
{
  const MAIN_COL = 'rgba(46,204,113,0.75)';
  const SIDE_COL = 'rgba(231,76,60,0.75)';
  const hasMainSide = runs.some(r => r.main_delay != null || r.side_delay != null);
  const msNa = document.getElementById('main-side-delay-na');
  const msCv = document.getElementById('chart-main-side-delay');
  if (!hasMainSide) {
    if (msNa) msNa.style.display = '';
    if (msCv) msCv.style.display = 'none';
  } else {
    const runLabels = runs.map(r => r.label);
    new Chart(document.getElementById('chart-main-side-delay').getContext('2d'), {
      type: 'bar',
      data: {
        labels: runLabels,
        datasets: [
          {
            label: 'Main corridor (pax·h)',
            data: runs.map(r => r.main_delay ?? null),
            backgroundColor: MAIN_COL, borderColor: MAIN_COL, borderWidth: 1,
          },
          {
            label: 'Side streets (pax·h)',
            data: runs.map(r => r.side_delay ?? null),
            backgroundColor: SIDE_COL, borderColor: SIDE_COL, borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true, animation: false,
        plugins: {
          legend: { labels: { color: '#aaaacc', font: { size: 11 } } },
          tooltip: { backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc', borderColor: '#2a2a50', borderWidth: 1 },
        },
        scales: {
          x: SCALE_X,
          y: { ...SCALE_Y, title: { display: true, text: 'pax·h', color: '#7070a0', font: { size: 11 } } },
        },
      },
    });
  }
}


// ── Delta vs NORMAL (%) ───────────────────────────────────────────────────
{
  const deltaKeys   = ['total_delay','main_delay','side_delay','avg_bus_delay',
                       'avg_car_delay','mean_green','speed'];
  const deltaLabels = ['Total pax Δ','Main Δ','Side Δ','Avg bus Δ',
                       'Avg car Δ','Green rate Δ','Speed Δ'];
  const nonNormal = runs.filter(r => r.label !== NORMAL_LABEL);
  if (nonNormal.length) {
    barChart('chart-delta', deltaLabels,
      nonNormal.map((r,i) => ({
        label: r.label,
        data: deltaKeys.map(k => r.delta ? r.delta[k] : null),
        backgroundColor: color(i), borderColor: colorEdge(i), borderWidth:1,
      })),
      {
        scales: {
          x: SCALE_X,
          y: { ...SCALE_Y,
               ticks: { ...SCALE_Y.ticks, callback: v => v + '%' },
               title: { display:true, text:'% improvement vs NORMAL (positive = better)',
                        color:'#7070a0', font:{size:11} }
          }
        },
        plugins: {
          legend: { labels:{color:'#aaaacc', font:{size:11}} },
          tooltip: {
            backgroundColor:'#0a0a22', titleColor:'#ccccee',
            bodyColor:'#9090cc', borderColor:'#2a2a50', borderWidth:1,
            callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.raw !== null ? ctx.raw.toFixed(1)+'%' : '—'}` }
          },
          annotation: {
            annotations: [{
              type:'line', yMin:0, yMax:0,
              borderColor:'rgba(255,255,255,0.25)', borderWidth:1,
              borderDash:[4,4]
            }]
          }
        }
      }
    );
  }
}

// ── TSP outcome breakdown — stacked bar per run ───────────────────────────
// Each run = one bar group, each category = one stacked segment.
// X labels = run labels; stacks = outcome categories.
{
  const runLabels = runs.map(r => r.label);
  const tspCategories = [
    { key:'tsp_green_unique',    label:'Unique green detections (bus×jct)', color:'rgba(0,230,118,0.85)' },
    { key:'tsp_nongreen_unique', label:'Unique non-green detections (bus×jct)', color:'rgba(255,82,82,0.85)' },
  ];
  const ctx = document.getElementById('chart-tsp');
  if (ctx) {
    new Chart(ctx.getContext('2d'), {
      type: 'bar',
      data: {
        labels: runLabels,
        datasets: tspCategories.map(cat => ({
          label: cat.label,
          data: runs.map(r => r[cat.key] ?? 0),
          backgroundColor: cat.color,
          borderColor: cat.color.replace('0.85','1').replace('0.55','1'),
          borderWidth: 1,
        }))
      },
      options: {
        responsive: true,
        plugins: {
          legend: { labels:{ color:'#aaaacc', font:{size:10} }, position:'bottom' },
          tooltip: {
            backgroundColor:'#0a0a22', titleColor:'#ccccee',
            bodyColor:'#9090cc', borderColor:'#2a2a50', borderWidth:1,
            callbacks: {
              footer: (items) => {
                const total = items.reduce((s,i)=>s+(i.raw||0), 0);
                const idx = (items && items.length && items[0].dataIndex != null) ? items[0].dataIndex : -1;
                const r = idx >= 0 ? runs[idx] : null;
                const unique = r ? (r.tsp_det_unique ?? 0) : 0;
                const cap = r ? (r.tsp_det_max_pairs ?? 0) : 0;
                return `Unique shown: ${total} | Unique bus×jct: ${unique}${cap ? ` / ${cap} max` : ''}`;
              }
            }
          }
        },
        scales: {
          x: { ...SCALE_X, stacked: true },
          y: { ...SCALE_Y, stacked: true,
               title:{ display:true, text:'Count', color:'#7070a0', font:{size:10} } }
        }
      }
    });
  }
}

// ── TSP priority decision outcomes — stacked bar per run ─────────────────
{
  const ctx = document.getElementById('chart-tsp-outcome');
  if (ctx) {
    const hasOutcomeData = runs.some(r =>
      (r.tsp_ext || 0) +
      (r.tsp_ins || 0) +
      (r.tsp_skip_ge || 0) +
      (r.tsp_skip_ins || 0) +
      (r.tsp_natural_green || 0) +
      (r.tsp_no_action || 0) > 0
    );

    if (!hasOutcomeData) {
      const card = document.getElementById('card-tsp-outcome');
      if (card) card.style.display = 'none';
    } else {
      new Chart(ctx.getContext('2d'), {
        type: 'bar',
        data: {
          labels: runs.map(r => r.label),
          datasets: [
            { label:'Green Extension (granted)',   data: runs.map(r => r.tsp_ext ?? 0),           backgroundColor:'rgba(52,152,219,0.85)', borderColor:'rgba(52,152,219,1)', borderWidth:1 },
            { label:'Insertion (granted)',         data: runs.map(r => r.tsp_ins ?? 0),           backgroundColor:'rgba(171,71,188,0.85)', borderColor:'rgba(171,71,188,1)', borderWidth:1 },
            { label:'GE denied (delay objective)', data: runs.map(r => r.tsp_skip_ge ?? 0),       backgroundColor:'rgba(255,152,0,0.85)', borderColor:'rgba(255,152,0,1)', borderWidth:1 },
            { label:'INS denied (delay objective)',data: runs.map(r => r.tsp_skip_ins ?? 0),      backgroundColor:'rgba(255,213,0,0.85)', borderColor:'rgba(255,213,0,1)', borderWidth:1 },
            { label:'Natural green (no action)',   data: runs.map(r => r.tsp_natural_green ?? 0), backgroundColor:'rgba(0,200,83,0.55)', borderColor:'rgba(0,200,83,1)', borderWidth:1 },
            { label:'No action (NORMAL mode)',     data: runs.map(r => r.tsp_no_action ?? 0),     backgroundColor:'rgba(120,120,140,0.55)', borderColor:'rgba(120,120,140,1)', borderWidth:1 },
          ]
        },
        options: {
          responsive: true,
          plugins: {
            legend: { labels:{ color:'#aaaacc', font:{size:10} }, position:'bottom' },
            tooltip: {
              backgroundColor:'#0a0a22', titleColor:'#ccccee',
              bodyColor:'#9090cc', borderColor:'#2a2a50', borderWidth:1,
              callbacks: {
                footer: (items) => {
                  const idx = items && items.length ? items[0].dataIndex : -1;
                  const r = idx >= 0 ? runs[idx] : null;
                  if (!r) return '';
                  const granted = (r.tsp_ext || 0) + (r.tsp_ins || 0);
                  const denied = (r.tsp_skip_ge || 0) + (r.tsp_skip_ins || 0);
                  const total = granted + denied + (r.tsp_natural_green || 0) + (r.tsp_no_action || 0);
                  const denyRate = total > 0 ? ((100.0 * denied) / total).toFixed(1) : '0.0';
                  return `Total: ${total} | Granted: ${granted} | Denied: ${denied} (${denyRate}%)`;
                }
              }
            }
          },
          scales: {
            x: { ...SCALE_X, stacked: true },
            y: {
              ...SCALE_Y,
              stacked: true,
              title:{ display:true, text:'Count (raw events)', color:'#7070a0', font:{size:10} }
            }
          }
        }
      });
    }
  }
}

// ── Green rate by junction ────────────────────────────────────────────────
if (jcts.length > 0) {
  barChart('chart-green',
    jcts.map(j => 'jct '+j),
    runs.map((r,i) => ({
      label: r.label,
      data: jcts.map(j => r.green_rates[j] ?? null),
      backgroundColor: color(i), borderColor: colorEdge(i), borderWidth:1,
    })),
    { scales:{ x: SCALE_X, y:{...SCALE_Y, min:0, max:100,
        ticks:{...SCALE_Y.ticks, callback: v=>v+'%'}} } }
  );
}

// ── Flow & Density (separate charts) ──────────────────────────────────────
{
  const hasFlow = !SUPP.has('flow') && runs.some(r=>r.flow!==null);
  const hasD    = !SUPP.has('density') && runs.some(r=>r.density!==null);
  if (!hasFlow) {
    document.getElementById('card-flow').style.display = 'none';
  } else {
    barChart('chart-flow',
      runs.map(r => r.label),
      [{
        label: 'Flow (veh/h)',
        data: runs.map(r => r.flow),
        backgroundColor: runs.map((_,i) => color(i)),
        borderColor: runs.map((_,i) => colorEdge(i)),
        borderWidth: 1,
      }],
      { plugins:{ legend:{display:false} } }
    );
  }
  if (!hasD) {
    document.getElementById('card-density').style.display = 'none';
  } else {
    barChart('chart-density',
      runs.map(r => r.label),
      [{
        label: 'Density (veh/km/lane)',
        data: runs.map(r => r.density),
        backgroundColor: runs.map((_,i) => color(i)),
        borderColor: runs.map((_,i) => colorEdge(i)),
        borderWidth: 1,
      }],
      { plugins:{ legend:{display:false} } }
    );
  }
}

// ── Bus total TT (separate tiny scale) ───────────────────────────────────
barChart('chart-bus-tt',
  runs.map(r => r.label),
  [{
    label: 'Bus TT (hrs)',
    data: runs.map(r => r.bus_tt),
    backgroundColor: runs.map((_,i) => color(i)),
    borderColor: runs.map((_,i) => colorEdge(i)),
    borderWidth: 1,
  }],
  { plugins:{ legend:{display:false} } }
);

// ── Avg delay per passenger (contextualises raw flow/speed) ───────────────
{
  const delayCtx = document.getElementById('chart-pax-delay');
  if (delayCtx) {
    barChart('chart-pax-delay',
      runs.map(r => r.label),
      [
        { label: 'All pax (s/pax)',  data: runs.map(r => r.avg_pass_delay   ?? null),
          backgroundColor: runs.map((_,i) => color(i)), borderWidth: 1 },
        { label: 'Bus pax (s/pax)',  data: runs.map(r => r.avg_bus_delay    ?? null),
          backgroundColor: runs.map((_,i) => color(i) + '99'), borderWidth: 1,
          borderColor: runs.map((_,i) => colorEdge(i)), borderDash: [4,2] },
        { label: 'Car pax (s/pax)',  data: runs.map(r => r.avg_car_delay    ?? null),
          backgroundColor: runs.map((_,i) => colorEdge(i) + '55'), borderWidth: 1 },
      ],
      {
        plugins: {
          legend: { labels: { color: '#9090cc', font: { size: 10 } } },
          subtitle: {
            display: true,
            text: 'Lower = better  ·  Raw network flow/speed may drop under TSP due to signal disruption — avg pax delay shows the true benefit',
            color: '#6060aa', font: { size: 9 }, padding: { bottom: 4 },
          },
        },
      }
    );
  }
}

// ── Speed ─────────────────────────────────────────────────────────────────
// Total volume behind passenger-delay metrics
{
  const volumeCtx = document.getElementById('chart-volume');
  if (volumeCtx) {
    const hasVolume = runs.some(r => r.pax_equiv !== null || r.flow !== null);
    if (!hasVolume) {
      const card = document.getElementById('card-volume');
      if (card) card.style.display = 'none';
    } else {
      new Chart(volumeCtx.getContext('2d'), {
        type: 'bar',
        data: {
          labels: runs.map(r => r.label),
          datasets: [
            { label:'Bus pax-equivalent', data:runs.map(r => r.bus_pax_equiv ?? 0),
              backgroundColor:'rgba(41,182,246,0.78)', borderColor:'rgba(41,182,246,1)', borderWidth:1, stack:'pax', yAxisID:'y' },
            { label:'Car pax-equivalent', data:runs.map(r => r.car_pax_equiv ?? 0),
              backgroundColor:'rgba(102,187,106,0.72)', borderColor:'rgba(102,187,106,1)', borderWidth:1, stack:'pax', yAxisID:'y' },
            { label:'Truck pax-equivalent', data:runs.map(r => r.truck_pax_equiv ?? 0),
              backgroundColor:'rgba(255,183,77,0.78)', borderColor:'rgba(255,183,77,1)', borderWidth:1, stack:'pax', yAxisID:'y' },
            { label:'Net_TotalFlowVeh', type:'line', data:runs.map(r => r.flow ?? null),
              borderColor:'rgba(236,64,122,1)', backgroundColor:'rgba(236,64,122,0.18)',
              borderWidth:2, tension:0.2, pointRadius:3, yAxisID:'y2' },
          ],
        },
        options: {
          responsive: true,
          interaction: { mode:'index', intersect:false },
          plugins: {
            legend: { labels:{ color:'#aaaacc', font:{size:10} }, position:'bottom' },
            tooltip: {
              backgroundColor:'#0a0a22', titleColor:'#ccccee',
              bodyColor:'#9090cc', borderColor:'#2a2a50', borderWidth:1,
              callbacks: {
                footer: (items) => {
                  const idx = items && items.length ? items[0].dataIndex : -1;
                  const r = idx >= 0 ? runs[idx] : null;
                  if (!r) return '';
                  const veh = [
                    r.distinct_cars != null ? `${r.distinct_cars} cars` : null,
                    r.distinct_buses != null ? `${r.distinct_buses} buses` : null,
                    r.distinct_trucks != null ? `${r.distinct_trucks} trucks` : null,
                  ].filter(Boolean).join(', ');
                  return `Total pax-equiv: ${_formatTimeForNoAction(r.pax_equiv)}${veh ? ` | Distinct: ${veh}` : ''}`;
                }
              }
            }
          },
          scales: {
            x: { ...SCALE_X, stacked:true },
            y: { ...SCALE_Y, stacked:true,
                 title:{ display:true, text:'Pax-equivalent passages', color:'#7070a0', font:{size:10} } },
            y2:{ position:'right', grid:{ drawOnChartArea:false }, ticks:{ color:'#6060aa', font:{size:10} },
                 title:{ display:true, text:'Net flow vehicles', color:'#7070a0', font:{size:10} } },
          }
        }
      });
    }
  }
}

if (SUPP.has('speed') || runs.every(r=>r.speed===null)) {
  document.getElementById('card-speed').style.display = 'none';
} else {
  barChart('chart-speed',
    runs.map(r => r.label),
    [{ label:'Avg speed (km/h)',
       data: runs.map(r => r.speed),
       backgroundColor: runs.map((_,i)=>color(i)),
       borderColor:     runs.map((_,i)=>colorEdge(i)),
       borderWidth: 1 }],
    { plugins:{ legend:{display:false} } }
  );
}

// ── Pre-arm coordination outcomes ─────────────────────────────────────────
// Show whenever there are coordinated runs — even if counts are 0
// (e.g. HARMONY coordinated doesn't use CorridorCoordinator so shows 0s,
//  while GROUP_BASED coordinated shows real pre-arm counts)
{
  const coordRuns = runs.filter(r => r.coordinated);
  if (coordRuns.length > 0) {
    const hasAnyPrearm = coordRuns.some(r => (r.prearm_fired || 0) > 0);
    barChart('chart-prearm',
      runs.map(r => r.label),
      [
        { label:'Fired',     data: runs.map(r=>r.prearm_fired    ?? 0), backgroundColor:'rgba(41,182,246,0.7)',  borderWidth:1 },
        { label:'Success',   data: runs.map(r=>r.prearm_success  ?? 0), backgroundColor:'rgba(0,230,118,0.7)',   borderWidth:1 },
        { label:'Late success', data: runs.map(r=>r.prearm_late_success ?? 0), backgroundColor:'rgba(255,213,79,0.75)', borderWidth:1 },
        { label:'Missed',    data: runs.map(r=>r.prearm_missed   ?? 0), backgroundColor:'rgba(255,82,82,0.7)',   borderWidth:1 },
        { label:'Expired',   data: runs.map(r=>r.prearm_expired  ?? 0), backgroundColor:'rgba(255,179,0,0.7)',   borderWidth:1 },
        { label:'Discarded', data: runs.map(r=>r.prearm_discarded?? 0), backgroundColor:'rgba(120,120,180,0.55)',borderWidth:1 },
      ]
    );
    if (!hasAnyPrearm) {
      const note = document.getElementById('prearm-note');
      if (note) {
        note.style.display = 'block';
        note.textContent = 'All pre-arm counts are zero. Pre-arm coordination requires COORDINATED_TSP=True. Both GROUP_BASED and HARMONY coordinated modes use CorridorCoordinator pre-arming when enabled. Zero counts mean the run was completed without COORDINATED_TSP enabled, or no pre-arm opportunities arose.';
      }
    }
  } else {
    const card = document.getElementById('card-prearm');
    if (card) card.style.display = 'none';
  }
}

// ── Harmony timing averages ──────────────────────────────────────────────
{
  const hasAnyTiming = runs.some(r => (r.avg_extension_s||0) > 0 || (r.avg_insertion_s||0) > 0 || (r.avg_insertion_wait_s||0) > 0);
  const timingNote = document.getElementById('harmony-timing-note');
  if (timingNote) {
    timingNote.style.display = 'block';
    timingNote.textContent = 'Avg INS wait (s) = average bus ETA (seconds to arrival) at the moment the insertion phase fires — how far in advance of bus arrival the insertion is triggered. A value of ~10 s means the insertion fires ~10 s before the bus reaches the stop line. This is NOT the frequency between insertions.';
  }
  if (!hasAnyTiming) {
    if (timingNote) {
      timingNote.textContent = 'No GE/insertion duration data yet — requires re-run with updated code.';
    }
  } else {
    barChart('chart-harmony-timing',
      ['Avg green extension (s)', 'Avg insertion phase (s)', 'Avg INS lead to arrival (s)'],
      runs.map((r, i) => ({
        label: r.label,
        data: [r.avg_extension_s ?? 0, r.avg_insertion_s ?? 0, r.avg_insertion_wait_s ?? 0],
        backgroundColor: color(i), borderColor: colorEdge(i), borderWidth: 1,
      })),
      { plugins: { legend: { labels: { color: '#aaaacc', font: { size: 11 } } } },
        scales: { x: SCALE_X, y: { ...SCALE_Y,
          title: { display: true, text: 'seconds', color: '#7070a0', font: { size: 10 } } } } }
    );
  }
}

// ── No-action reasons by junction (stacked) ─────────────────────────────
{
  let noActionReasonChart = null;
  let noActionCurrentSelection = {
    runLabel: '',
    jct: '',
    reasonKey: '',
    rowsAll: [],
  };

  function _csvCell(v) {
    const s = String(v == null ? '' : v);
    return `"${s.replaceAll('"', '""')}"`;
  }

  function _formatTimeForNoAction(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return 'n/a';
    return n.toFixed(1);
  }

  function _sampleRowsForNoAction(rows, mode, k = 8) {
    const all = (rows || []).slice().sort((a, b) => Number(a.t || 0) - Number(b.t || 0));
    if (!all.length) return [];
    if (mode === 'latest') return all.slice(Math.max(0, all.length - k));
    if (mode === 'both') {
      const half = Math.max(1, Math.floor(k / 2));
      const first = all.slice(0, half).map(r => ({ ...r, _sample_window: 'earliest' }));
      const last = all.slice(Math.max(0, all.length - half)).map(r => ({ ...r, _sample_window: 'latest' }));
      const seen = new Set();
      const merged = [];
      [...first, ...last].forEach(r => {
        const key = `${r.t}|${r.vid}|${r.tier}|${r.note}`;
        if (seen.has(key)) return;
        seen.add(key);
        merged.push(r);
      });
      return merged;
    }
    return all.slice(0, k);
  }

  function _setNoActionDrilldown(rows, jct, reasonKey, runLabel, totalCount, mode) {
    const box = document.getElementById('noaction-reasons-drilldown');
    const title = document.getElementById('noaction-reasons-drilldown-title');
    const table = document.getElementById('noaction-reasons-drilldown-table');
    const exportBtn = document.getElementById('noaction-export-btn');
    if (!box || !title || !table) return;

    const thead = table.querySelector('thead');
    const tbody = table.querySelector('tbody');
    if (!thead || !tbody) return;

    if (!rows || !rows.length) {
      box.style.display = 'none';
      title.textContent = '';
      thead.innerHTML = '';
      tbody.innerHTML = '';
      if (exportBtn) exportBtn.disabled = true;
      return;
    }

    box.style.display = 'block';
    title.textContent = `${runLabel} | jct ${jct} | ${_reasonLabel(reasonKey)} | sample: ${mode} | showing ${rows.length} of ${totalCount} raw rows`;
    if (exportBtn) exportBtn.disabled = false;

    thead.innerHTML = '<tr><th>Time (s)</th><th>Bus</th><th>Tier</th><th>Window</th><th>Raw note</th></tr>';
    tbody.innerHTML = '';

    rows.forEach(rw => {
      const tr = document.createElement('tr');

      const tdT = document.createElement('td');
      tdT.textContent = _formatTimeForNoAction(rw.t);
      tr.appendChild(tdT);

      const tdBus = document.createElement('td');
      tdBus.textContent = String(rw.vid || 'n/a');
      tr.appendChild(tdBus);

      const tdTier = document.createElement('td');
      tdTier.textContent = String(rw.tier || 'n/a');
      tr.appendChild(tdTier);

      const tdW = document.createElement('td');
      tdW.textContent = String(rw._sample_window || mode);
      tr.appendChild(tdW);

      const tdNote = document.createElement('td');
      tdNote.textContent = String(rw.note || '');
      tr.appendChild(tdNote);

      tbody.appendChild(tr);
    });
  }

  function _reasonTokenFromNote(note, prefix) {
    const raw = String(note || '');
    let body = raw;
    if (prefix && body.startsWith(prefix)) body = body.slice(prefix.length);
    // Notes use '|' as field separator (e.g. "natural_green_future_bus_phase | eta_s=6.9 | ...");
    // also guard against legacy ';' separator.
    const head = (body.split(';')[0] || body).split('|')[0];
    return head.trim();
  }

  function _normalizeReason(token) {
    const t = String(token || '').trim();
    if (!t) return 'unspecified';
    if (t === 'natural_green_future_bus_phase' || t === 'natural_green_current_phase') return 'natural_catchable';
    if (t === 'impractical_upper_bound') return 'impractical_upper_bound';
    if (t === 'not_optimal' || t === 'not_optimal_too_short' || t === 'too_short') return 'objective_rejected';
    if (t === 'over_max_extension') return 'over_max_extension';
    if (t === 'insufficient_cycle_headroom') return 'insufficient_cycle_headroom';
    if (t === 'harmony_nan') return 'optimizer_nan';
    if (t === 'no_bus_detected') return 'no_bus_detected';
    if (t === 'cooldown') return 'cooldown';
    return t;
  }

  function _reasonLabel(key) {
    if (key === 'natural_catchable') return 'Natural phase catchable';
    if (key === 'objective_rejected') return 'Objective rejected';
    if (key === 'impractical_upper_bound') return 'ETA > insertion upper bound';
    if (key === 'over_max_extension') return 'Over max extension';
    if (key === 'insufficient_cycle_headroom') return 'Insufficient cycle headroom';
    if (key === 'optimizer_nan') return 'Optimizer NaN';
    if (key === 'cooldown') return 'Cooldown active';
    if (key === 'no_bus_detected') return 'No bus detected';
    if (key === 'unspecified') return 'Unspecified';
    return key.replaceAll('_', ' ');
  }

  function renderNoActionReasons(ri) {
    const r = runs[ri];
    const noteEl = document.getElementById('noaction-reasons-note');
    const canvas = document.getElementById('chart-noaction-reasons');
    const modeSel = document.getElementById('noaction-sample-mode');
    const sampleMode = modeSel ? String(modeSel.value || 'earliest') : 'earliest';
    if (!canvas) return;
    _setNoActionDrilldown([], '', '', '', 0, sampleMode);
    noActionCurrentSelection = { runLabel: '', jct: '', reasonKey: '', rowsAll: [] };
    if (noActionReasonChart) { noActionReasonChart.destroy(); noActionReasonChart = null; }

    const rows = (r.phase_samples || []).filter(p => {
      const tier = String(p.tier || '');
      return tier === 'harmony-no-ge-local' || tier === 'harmony-no-ins-local';
    });

    if (!rows.length) {
      if (noteEl) {
        noteEl.style.display = 'block';
        noteEl.textContent = 'No harmony no-action decision rows found for this run.';
      }
      const c2d = canvas.getContext('2d');
      c2d.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }

    const byJctReason = {};
    const byJctReasonRows = {};
    const reasonSet = new Set();
    rows.forEach(p => {
      const j = String(p.jct || '');
      if (!j) return;
      const tier = String(p.tier || '');
      const pref = tier === 'harmony-no-ge-local' ? 'NO_GE ' : 'NO_INS ';
      const tok = _reasonTokenFromNote(p.prearm_note, pref);
      const reason = _normalizeReason(tok);
      reasonSet.add(reason);
      if (!byJctReason[j]) byJctReason[j] = {};
      byJctReason[j][reason] = (byJctReason[j][reason] || 0) + 1;

      const k = `${j}||${reason}`;
      if (!byJctReasonRows[k]) byJctReasonRows[k] = [];
      byJctReasonRows[k].push({
        t: p.t ?? p.time ?? p.sim_time,
        vid: p.vid ?? p.bus_id,
        tier,
        note: p.prearm_note,
      });
    });

    const jcts = Object.keys(byJctReason).sort((a, b) => Number(a) - Number(b));
    const reasonOrder = [
      'natural_catchable', 'objective_rejected', 'impractical_upper_bound',
      'over_max_extension', 'insufficient_cycle_headroom',
      'cooldown', 'optimizer_nan', 'no_bus_detected', 'unspecified'
    ];
    const reasons = [
      ...reasonOrder.filter(k => reasonSet.has(k)),
      ...Array.from(reasonSet).filter(k => !reasonOrder.includes(k)).sort(),
    ];

    const palette = ['#66bb6a', '#ffb300', '#ef5350', '#ab47bc', '#42a5f5', '#8d6e63', '#90a4ae', '#ec407a'];
    const datasets = reasons.map((reason, idx) => ({
      label: _reasonLabel(reason),
      data: jcts.map(j => Number((byJctReason[j] || {})[reason] || 0)),
      backgroundColor: palette[idx % palette.length],
      borderColor: palette[idx % palette.length],
      borderWidth: 1,
      stack: 'reason',
    }));

    noActionReasonChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: jcts.map(j => `jct ${j}`),
        datasets,
      },
      options: {
        responsive: true,
        animation: false,
        onClick: (_evt, elements) => {
          if (!elements || !elements.length) return;
          const el = elements[0];
          const datasetIndex = Number(el.datasetIndex);
          const dataIndex = Number(el.index);
          if (!Number.isFinite(datasetIndex) || !Number.isFinite(dataIndex)) return;
          const reasonKey = reasons[datasetIndex];
          const jct = jcts[dataIndex];
          if (!reasonKey || !jct) return;
          const key = `${jct}||${reasonKey}`;
          const all = (byJctReasonRows[key] || []).slice().sort((a, b) => Number(a.t || 0) - Number(b.t || 0));
          noActionCurrentSelection = { runLabel: r.label, jct, reasonKey, rowsAll: all };
          const modeSelNow = document.getElementById('noaction-sample-mode');
          const mode = modeSelNow ? String(modeSelNow.value || 'earliest') : 'earliest';
          const sample = _sampleRowsForNoAction(all, mode, 8);
          _setNoActionDrilldown(sample, jct, reasonKey, r.label, all.length, mode);
        },
        plugins: {
          legend: { labels: { color: '#aaaacc', font: { size: 10 } }, position: 'bottom' },
          tooltip: {
            backgroundColor:'#0a0a22', titleColor:'#ccccee', bodyColor:'#9090cc', borderColor:'#2a2a50', borderWidth:1,
          },
          title: {
            display: true,
            text: `${r.label} — no-action decision reasons by junction`,
            color: '#7070a0',
            font: { size: 11 },
          },
        },
        scales: {
          x: { stacked: true, ticks: { color:'#9090cc' }, grid: { color:'#1e1e38' } },
          y: { stacked: true, ticks: { color:'#9090cc' }, grid: { color:'#1e1e38' }, min: 0,
            title: { display: true, text: 'No-action decision count', color: '#7070a0', font: { size: 10 } } },
        },
      },
    });

    if (noteEl) {
      noteEl.style.display = 'block';
      noteEl.textContent = `Rows counted: ${rows.length}. Includes harmony-no-ge-local and harmony-no-ins-local decision rows only.`;
    }
  }

  const card = document.getElementById('card-noaction-reasons');
  if (!runs.length) {
    if (card) card.style.display = 'none';
  } else {
    const exportBtn = document.getElementById('noaction-export-btn');
    if (exportBtn) {
      exportBtn.disabled = true;
      exportBtn.addEventListener('click', () => {
        const sel = noActionCurrentSelection;
        if (!sel || !sel.rowsAll || !sel.rowsAll.length) return;
        const modeSel = document.getElementById('noaction-sample-mode');
        const mode = modeSel ? String(modeSel.value || 'earliest') : 'earliest';
        const sampled = _sampleRowsForNoAction(sel.rowsAll, mode, 8);
        const lines = [
          ['run_label','junction','reason','sample_mode','sample_window','time_s','bus','tier','raw_note'].map(_csvCell).join(','),
          ...sampled.map(rw => [
            sel.runLabel, sel.jct, sel.reasonKey, mode, (rw._sample_window || mode),
            _formatTimeForNoAction(rw.t), (rw.vid || ''), (rw.tier || ''), (rw.note || '')
          ].map(_csvCell).join(','))
        ];
        const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
        const a = document.createElement('a');
        const reasonSafe = String(sel.reasonKey || 'reason').replaceAll(/[^a-zA-Z0-9_-]/g, '_');
        a.href = URL.createObjectURL(blob);
        a.download = `noaction_${sel.runLabel}_j${sel.jct}_${reasonSafe}_${mode}.csv`;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
          URL.revokeObjectURL(a.href);
          a.remove();
        }, 0);
      });
    }

    const modeSel = document.getElementById('noaction-sample-mode');
    if (modeSel) {
      modeSel.addEventListener('change', () => {
        const sel = noActionCurrentSelection;
        if (!sel || !sel.rowsAll || !sel.rowsAll.length) return;
        const mode = String(modeSel.value || 'earliest');
        const sampled = _sampleRowsForNoAction(sel.rowsAll, mode, 8);
        _setNoActionDrilldown(sampled, sel.jct, sel.reasonKey, sel.runLabel, sel.rowsAll.length, mode);
      });
    }

    const _noActionInit = runs.findIndex(r => r.coordinated && (r.tsp_natural_green ?? 0) > 0);
    const noActionInitialRunIdx = _noActionInit >= 0 ? _noActionInit : 0;

    // Build tabs locally so this block does not depend on initialRunIdx,
    // which is declared later in the script.
    const noActionTabs = document.getElementById('noaction-run-tabs');
    if (noActionTabs) {
      noActionTabs.innerHTML = '';
      runs.forEach((r, i) => {
        const btn = document.createElement('button');
        btn.className = 'run-tab' + (i === noActionInitialRunIdx ? ' active' : '');
        btn.textContent = r.label;
        btn.onclick = () => {
          noActionTabs.querySelectorAll('.run-tab').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          renderNoActionReasons(i);
        };
        noActionTabs.appendChild(btn);
      });
    }
    renderNoActionReasons(noActionInitialRunIdx);
  }
}

// ── Corridor adjustment chain (grant -> downstream outcomes) ─────────────
{
  const hasWaveData = runs.some(r => {
    const wc = r.wave_counts || {};
    return Object.values(wc).some(v => (v || 0) > 0);
  });
  if (!hasWaveData) {
    const card = document.getElementById('card-wave-chain');
    if (card) card.style.display = 'none';
  } else {
    barChart('chart-wave-chain',
      ['Grant', 'Queued', 'Fired', 'Success', 'Missed', 'Expired', 'Discarded'],
      runs.map((r, i) => {
        const wc = r.wave_counts || {};
        return {
          label: r.label,
          data: [
            wc.grant || 0,
            wc.prearm_queued || 0,
            wc.prearm_fired || 0,
            wc.prearm_success || 0,
            wc.prearm_missed || 0,
            wc.prearm_expired || 0,
            wc.prearm_discarded || 0,
          ],
          backgroundColor: color(i), borderColor: colorEdge(i), borderWidth: 1,
        };
      })
    );
  }
}

// ── KPI cards (best/worst highlighted) ───────────────────────────────────
const kpiDefs = [
  { key:'total_delay',            label:'Total pax delay',       unit:'hrs',   lb:true },
  { key:'avg_total_delay_per_hr', label:'Total pax delay/sim-hr',unit:'pax·h/h',lb:true },
  { key:'main_delay',             label:'Main-st delay',          unit:'hrs',   lb:true },
  { key:'avg_main_delay_per_hr',  label:'Main delay/sim-hr',     unit:'pax·h/h',lb:true },
  { key:'avg_side_delay_per_hr',  label:'Side delay/sim-hr',     unit:'pax·h/h',lb:true },
  { key:'bus_tt',                 label:'Bus TT',                 unit:'hrs',   lb:true },
  { key:'avg_bus_delay',          label:'Avg bus delay',          unit:'s',     lb:true },
  { key:'avg_car_delay',          label:'Avg car delay',          unit:'s',     lb:true },
  { key:'tracked_bus_count', label:'Tracked buses', unit:'',    lb:false },
  { key:'tracking_coverage_pct', label:'Detection coverage', unit:'%', lb:false },
  { key:'tsp_natural_green_rate_pct', label:'Natural green share (unique bus×jct)', unit:'%', lb:false },
  { key:'prearm_success_rate_pct',    label:'Prearm success',      unit:'%', lb:false },
  { key:'tsp_det_unique',label:'Unique detections (bus×jct)', unit:'', lb:false },
  { key:'mean_green',    label:'Mean green %',      unit:'%',   lb:false },
];

const kpiRow = document.getElementById('kpi-row');
kpiDefs.forEach(def => {
  const vals = runs.map(r => r[def.key]).filter(v => v !== null && v !== undefined);
  if (!vals.length) return;
  const allSame = vals.every(v=>Math.abs(v-vals[0])<0.001);
  const best  = def.lb ? Math.min(...vals) : Math.max(...vals);
  const worst = def.lb ? Math.max(...vals) : Math.min(...vals);
  const bestRun = runs.find(r => r[def.key] === best);
  const pct = !allSame && Math.abs(worst)>0.001
              ? Math.abs((best-worst)/worst*100).toFixed(1) : null;

  const div = document.createElement('div');
  const improved = !allSame && vals.length > 1;
  div.className = 'kpi' + (improved ? ' improved' : '');
  div.innerHTML = `
    <div class="label">${def.label}</div>
    <div class="val">${best !== null ? (Number.isInteger(best) ? best : best.toFixed(2)) : '—'}</div>
    <div class="unit">${def.unit}${bestRun ? ' — <b>'+bestRun.label+'</b>' : ''}</div>
    ${pct ? `<div class="delta-pos">Δ ${pct}% vs worst</div>` : allSame ? `<div class="delta-na">identical across runs</div>` : ''}`;
  kpiRow.appendChild(div);
});

// ── Audience summary cards (presentation-ready headline KPIs) ────────────
function _pickAudienceRun() {
  const ranked = runs
    .map(r => {
      const obj = (r.objective_trace || []);
      const act = obj.filter(x => (x.mode === 'GE' || x.mode === 'INS') && x.decision === 'ACTION').length;
      const rew = (r.reward_cycle || []).filter(x => Number(x.is_chosen) === 1).length;
      return { r, score: act * 10 + rew };
    })
    .sort((a, b) => b.score - a.score);
  const coordBest = ranked.find(x => x.r.coordinated && x.score > 0);
  if (coordBest) return coordBest.r;
  return ranked.length ? ranked[0].r : null;
}

function _num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function _buildAudienceSummary() {
  const row = document.getElementById('audience-kpi-row');
  if (!row) return;
  row.innerHTML = '';

  const run = _pickAudienceRun();
  if (!run) {
    row.innerHTML = '<div class="kpi"><div class="label">Audience Summary</div><div class="val">N/A</div><div class="unit">No runs loaded</div></div>';
    return;
  }

  const objActions = (run.objective_trace || []).filter(x =>
    (x.mode === 'GE' || x.mode === 'INS') && x.decision === 'ACTION');

  // For DCTSP_MARL runs, objective_trace is absent but reward_cycle has the
  // decomposed delay fields (no_strategy_delay_pax_s / strategy_min_delay_pax_s).
  // Build actionComp from objective_trace first; fall back to reward_cycle chosen
  // GE/INS rows that have non-zero baseline delay.
  let actionComp = objActions
    .map(x => {
      const base = _num(x.no_strategy_delay_pax_s) ?? _num(x.delay_base_pax_s);
      const strat = _num(x.strategy_min_delay_pax_s) ?? _num(x.delay_with_strategy_pax_s);
      return { base, strat };
    })
    .filter(x => x.base !== null && x.strat !== null);

  if (actionComp.length === 0) {
    // Fall back to reward_cycle rows — look at ALL rows (not just chosen) so we
    // can compare the chosen action vs its NO_ACTION baseline for the same cycle.
    const rcRows = run.reward_cycle || [];
    // Group rows by (t, jct, vid)
    const cycleMap = {};
    for (const row of rcRows) {
      const key = `${row.t}|${row.jct}|${row.vid}`;
      if (!cycleMap[key]) cycleMap[key] = [];
      cycleMap[key].push(row);
    }
    for (const rows of Object.values(cycleMap)) {
      const naRow = rows.find(r => r.action === 'NO_ACTION');
      const chosen = rows.find(r => Number(r.is_chosen) === 1 &&
                                    r.action !== 'NO_ACTION' &&
                                    (r.action.startsWith('GE') || r.action.startsWith('INS')));
      if (!naRow || !chosen) continue;
      // Prefer absolute delay fields (new CSV format: bus pax·s)
      const base  = _num(chosen.no_strategy_delay_pax_s);
      const strat = _num(chosen.strategy_min_delay_pax_s);
      if (base !== null && strat !== null && base > 0) {
        actionComp.push({ base, strat });
        continue;
      }
      // Fallback: use bus_saved_pax_s (intermediate CSV format, only if non-zero)
      const savedPax = _num(chosen.bus_saved_pax_s);
      if (savedPax !== null && savedPax !== 0) {
        actionComp.push({ base: Math.max(savedPax, 0) + 1.0, strat: 1.0, savedDirect: savedPax });
        continue;
      }
      // Last resort: compare sigma_out_s (old slim CSV format, in seconds not pax·s)
      const naOut     = _num(naRow.sigma_out_s);
      const chosenOut = _num(chosen.sigma_out_s);
      if (naOut !== null && chosenOut !== null) {
        const savedSec = naOut - chosenOut;
        actionComp.push({ base: naOut + 0.001, strat: chosenOut, savedDirect: savedSec, unitSec: true });
      }
    }
  }

  const anyUnitSec  = actionComp.some(x => x.unitSec);
  const betterN = actionComp.filter(x => x.savedDirect !== undefined
    ? x.savedDirect > 0 : x.strat < x.base).length;
  const betterPct = actionComp.length ? (100.0 * betterN / actionComp.length) : null;

  const savedVals = actionComp.map(x => x.savedDirect !== undefined
    ? x.savedDirect : x.base - x.strat);
  const meanSaved = savedVals.length ? (savedVals.reduce((a, b) => a + b, 0) / savedVals.length) : null;

  const rewardChosen = (run.reward_cycle || []).filter(x => Number(x.is_chosen) === 1);
  const rewardVals = rewardChosen.map(x => _num(x.reward)).filter(v => v !== null);
  const posRewardPct = rewardVals.length
    ? (100.0 * rewardVals.filter(v => v > 0).length / rewardVals.length)
    : (savedVals.length ? (100.0 * savedVals.filter(v => v > 0).length / savedVals.length) : null);
  const rewardSource = rewardVals.length ? 'reward_cycle' : (savedVals.length ? 'objective fallback' : 'no data');

  const rewardCandidates = (run.reward_cycle || []).filter(x => {
    const a = String(x.action || '');
    return a.startsWith('GE_') || a.startsWith('INS_');
  });
  const gateRejectedN = rewardCandidates.filter(x => Number(x.throughput_infeasible) === 1).length;
  const gateRejectedPct = rewardCandidates.length
    ? (100.0 * gateRejectedN / rewardCandidates.length)
    : null;

  // Cycle-level signal: NO_ACTION chosen while at least one candidate in the
  // same decision cycle was rejected by the throughput constraint.
  const rewardRows = (run.reward_cycle || []);
  const cycleMap = new Map();
  rewardRows.forEach(x => {
    const key = `${Number(x.t) || 0}|${Number(x.jct) || -1}|${Number(x.vid) || -1}`;
    let c = cycleMap.get(key);
    if (!c) {
      c = {
        chosenAction: null,
        candidateCount: 0,
        hasInfeasibleCandidate: false,
      };
      cycleMap.set(key, c);
    }
    const a = String(x.action || '');
    if (Number(x.is_chosen) === 1) c.chosenAction = a;
    if (a.startsWith('GE_') || a.startsWith('INS_')) {
      c.candidateCount += 1;
      if (Number(x.throughput_infeasible) === 1) c.hasInfeasibleCandidate = true;
    }
  });
  const decisionCycles = Array.from(cycleMap.values()).filter(c => c.candidateCount > 0);
  const forcedNoActionN = decisionCycles.filter(c => c.chosenAction === 'NO_ACTION' && c.hasInfeasibleCandidate).length;
  const forcedNoActionPct = decisionCycles.length
    ? (100.0 * forcedNoActionN / decisionCycles.length)
    : null;

  const geCycleMap = new Map();
  rewardRows.forEach(x => {
    const key = `${Number(x.t) || 0}|${Number(x.jct) || -1}|${Number(x.vid) || -1}`;
    let c = geCycleMap.get(key);
    if (!c) {
      c = { hasGeCandidate: false, geInapplicable: false };
      geCycleMap.set(key, c);
    }
    const a = String(x.action || '');
    if (a.startsWith('GE_')) c.hasGeCandidate = true;
    if (Number(x.ge_inapplicable_cycle) === 1) c.geInapplicable = true;
  });
  const geDecisionCycles = Array.from(geCycleMap.values()).filter(c => c.hasGeCandidate || c.geInapplicable);
  const geInapplicableN = geDecisionCycles.filter(c => c.geInapplicable).length;
  const geInapplicablePct = geDecisionCycles.length
    ? (100.0 * geInapplicableN / geDecisionCycles.length)
    : null;

  function _card(label, value, unit, note, improved = true) {
    const div = document.createElement('div');
    div.className = 'kpi' + (improved ? ' improved' : ' worse');
    div.innerHTML = `
      <div class="label">${label}</div>
      <div class="val">${value}</div>
      <div class="unit">${unit}</div>
      <div class="delta-na">${note}</div>`;
    row.appendChild(div);
  }

  _card(
    'Actions Choosing Lower Delay',
    betterPct === null ? 'N/A' : `${betterPct.toFixed(1)}%`,
    run.label,
    actionComp.length ? `${betterN}/${actionComp.length} GE/INS actions had strategy < no-strategy${anyUnitSec ? ' (sigma_out proxy)' : ''}` : 'No GE/INS ACTION rows with comparable delay terms',
    betterPct === null ? false : betterPct >= 50.0
  );

  _card(
    'Mean pax_saved (Chosen)',
    meanSaved === null ? 'N/A' : `${meanSaved.toFixed(1)}`,
    anyUnitSec ? 's per chosen action (bus, proxy)' : 'pax·s per chosen action',
    savedVals.length ? `Computed over ${savedVals.length} GE/INS cycles${anyUnitSec ? ' (sigma_out proxy, old log format)' : ''}` : 'No comparable chosen actions',
    meanSaved === null ? false : meanSaved >= 0.0
  );

  _card(
    'Positive Net Reward Share',
    posRewardPct === null ? 'N/A' : `${posRewardPct.toFixed(1)}%`,
    run.label,
    rewardVals.length
      ? `${rewardVals.filter(v => v > 0).length}/${rewardVals.length} chosen decisions have reward > 0 (${rewardSource})`
      : (savedVals.length ? `Using objective fallback: ${savedVals.filter(v => v > 0).length}/${savedVals.length}` : 'No reward/objective decision data'),
    posRewardPct === null ? false : posRewardPct >= 50.0
  );

  _card(
    'Throughput-Gate Rejection Rate',
    gateRejectedPct === null ? 'N/A' : `${gateRejectedPct.toFixed(1)}%`,
    run.label,
    rewardCandidates.length
      ? `${gateRejectedN}/${rewardCandidates.length} GE/INS candidates were rejected by throughput constraint`
      : 'No GE/INS candidate rows available',
    gateRejectedPct === null ? false : gateRejectedPct <= 20.0
  );

  _card(
    'Cycles Forced to NO_ACTION by Gate',
    forcedNoActionPct === null ? 'N/A' : `${forcedNoActionPct.toFixed(1)}%`,
    run.label,
    decisionCycles.length
      ? `${forcedNoActionN}/${decisionCycles.length} decision cycles chose NO_ACTION with at least one throughput-infeasible GE/INS candidate`
      : 'No decision cycles with GE/INS candidates',
    forcedNoActionPct === null ? false : forcedNoActionPct <= 20.0
  );

  _card(
    'GE Inapplicable Cycles',
    geInapplicablePct === null ? 'N/A' : `${geInapplicablePct.toFixed(1)}%`,
    run.label,
    geDecisionCycles.length
      ? `${geInapplicableN}/${geDecisionCycles.length} cycles had GE skipped because estimated no-action bus delay was negligible`
      : 'No bus-phase GE decision cycles detected',
    geInapplicablePct === null ? false : geInapplicablePct <= 40.0
  );
}

_buildAudienceSummary();

// ── Run tabs + Coord flow ─────────────────────────────────────────────────
let activeInterRun = 0;
function renderCoordFlow(ri, filterVid) {
  const r    = runs[ri];
  const flow = document.getElementById('coord-flow');
  flow.innerHTML = '';

  // Runtime health banner: quick integrity checks for wiring/data issues.
  const flowHealth = {
    high: [],
    med: [],
    info: [],
  };
  const healthEl = document.createElement('div');
  healthEl.className = 'metric-note';
  healthEl.style.marginBottom = '8px';
  healthEl.style.padding = '6px 8px';
  healthEl.style.borderRadius = '6px';
  healthEl.style.background = '#121827';
  healthEl.style.border = '1px solid #2a3555';
  healthEl.style.fontSize = '11px';
  healthEl.style.color = 'var(--muted)';
  flow.appendChild(healthEl);

  // ── Populate bus dropdown ──────────────────────────────────────────────
  const sel = document.getElementById('bus-flow-select');
  const allJ = r.bus_journeys || [];
  const focusBusIds = new Set(r.focus_bus_ids || []);
  const _phaseSampleCount = (r.phase_samples || []).length;
  const _greenRateJctCount = Object.keys(r.green_rates || {}).length;
  const _waveEventCount = allJ.reduce((n, j) => n + ((j.wave || []).length), 0);
  const _statsDistinctBusCount = Number(r.stats_distinct_buses_raw || 0);
  const _knownTrackedBusCount = Number(r.tracked_bus_count || 0);
  const _journeyBusCount = Number(r.journey_bus_count || 0);

  if (allJ.length === 0) {
    flowHealth.high.push('No bus_journeys loaded for this run');
  }
  if (_greenRateJctCount === 0) {
    flowHealth.high.push('No green-rate junction metrics loaded');
  }
  if (r.coordinated && _phaseSampleCount === 0) {
    flowHealth.high.push('Coordinated run has no phase_samples');
  }
  if (r.coordinated && _waveEventCount === 0) {
    flowHealth.high.push('Coordinated run has no wave events in journey data');
  }
  if (_statsDistinctBusCount > 0 && _knownTrackedBusCount > 0 && _knownTrackedBusCount < 0.60 * _statsDistinctBusCount) {
    flowHealth.high.push(
      `Known tracked buses (${_knownTrackedBusCount}) << stats distinct buses (${_statsDistinctBusCount})`
    );
  }
  if (_knownTrackedBusCount > 0 && _journeyBusCount > 0 && _journeyBusCount < 0.60 * _knownTrackedBusCount) {
    flowHealth.med.push(
      `Journey buses (${_journeyBusCount}) are much lower than tracked buses (${_knownTrackedBusCount}); some buses may not traverse enough junctions to form journeys`
    );
  }
  // Keep current selection stable across re-renders
  if (!filterVid) {
    sel.innerHTML = '<option value="">All buses (aggregate)</option>';
    const corridorBuses = allJ.filter(j => j.cls === 'full' || j.cls === 'partial')
                              .sort((a,b) => (a.stops[0]?.t||0) - (b.stops[0]?.t||0));
    corridorBuses.forEach(j => {
      const opt = document.createElement('option');
      opt.value = j.vid;
      const greenCnt = j.stops.filter(s => s.on_green).length;
      const isFocus = focusBusIds.has(j.vid);
      const focusTag = isFocus ? '⭐ ' : '';
      opt.textContent = `${focusTag}Bus ${j.vid}  (${j.cls}, ${j.n_jcts} jcts, ${greenCnt}/${j.stops.length} green${isFocus ? ', FOCUS' : ''})`;
      if (isFocus) opt.style.color = '#f1c40f';
      sel.appendChild(opt);
    });
  }

  // ── Per-bus junction stats ─────────────────────────────────────────────
  let perJctBusStats = null;  // {jct: {det, green}} when a single bus is selected
  let busRouteJcts   = null;  // ordered junction IDs on the selected bus's route
  let busJ           = null;  // full journey object for selected bus (for wave events)
  if (filterVid) {
    busJ = allJ.find(j => j.vid == filterVid) || null;
    if (!busJ) {
      flowHealth.high.push(`Selected bus ${filterVid} not found in bus_journeys`);
    }
    if (busJ) {
      perJctBusStats = {};
      busJ.stops.forEach(s => {
        // Stringify so the key matches jcts (DATA.junctions are strings)
        perJctBusStats[String(s.jct)] = { det: 1, green: s.on_green };
      });
      busRouteJcts = busJ.stops.map(s => String(s.jct));
      if (busRouteJcts.length < 2) {
        flowHealth.med.push(`Selected bus ${filterVid} has sparse route (${busRouteJcts.length} stop)`);
      }
    }
  }

  const summary = document.createElement('div');
  summary.style.width = '100%';
  summary.style.marginBottom = '8px';
  summary.style.fontSize = '12px';
  summary.style.color = 'var(--muted)';
  const ngShare = (r.tsp_natural_green_rate_pct !== null && r.tsp_natural_green_rate_pct !== undefined)
    ? `${r.tsp_natural_green_rate_pct.toFixed(1)}%`
    : 'n/a';
  const ngFocus = (r.mean_green_focus !== null && r.mean_green_focus !== undefined)
    ? `${r.mean_green_focus.toFixed(1)}%`
    : null;
  const prearmRate = (r.prearm_success_rate_pct !== null && r.prearm_success_rate_pct !== undefined)
    ? `${r.prearm_success_rate_pct.toFixed(1)}%`
    : 'n/a';
  const focusScoped = (r.focus_bus_ids || []).length > 0;
  const bandModeSel = document.getElementById('coord-band-mode');
  const bandMode = bandModeSel ? bandModeSel.value : 'adaptive';

  function quantile(sortedVals, q) {
    if (!sortedVals.length) return null;
    if (sortedVals.length === 1) return sortedVals[0];
    const pos = (sortedVals.length - 1) * q;
    const lo = Math.floor(pos);
    const hi = Math.ceil(pos);
    if (lo === hi) return sortedVals[lo];
    const w = pos - lo;
    return sortedVals[lo] * (1 - w) + sortedVals[hi] * w;
  }

  // Build blended scores used for aggregate bubble colouring (all-bus with focus-aware weighting).
  const scoreByJct = {};
  const scoreVals = [];
  jcts.forEach(j => {
    const pAll = r.green_rates[j] ?? null;
    const pFocus = (r.green_rates_focus || {})[j] ?? null;
    if (pAll === null) return;
    const s = (pFocus === null) ? pAll : (0.7 * pAll + 0.3 * pFocus);
    scoreByJct[j] = s;
    scoreVals.push(s);
  });

  let amberCut = 30;
  let greenCut = 55;
  if (bandMode === 'adaptive' && scoreVals.length >= 3) {
    const srt = scoreVals.slice().sort((a, b) => a - b);
    amberCut = quantile(srt, 0.33);
    greenCut = quantile(srt, 0.66);
    amberCut = Math.max(15, Math.min(amberCut, 75));
    greenCut = Math.max(amberCut + 8, Math.min(greenCut, 90));
  }

  const selectedBusIsFocus = filterVid && focusBusIds.has(Number(filterVid));
  if (filterVid && busRouteJcts) {
    const greenCnt = perJctBusStats ? Object.values(perJctBusStats).filter(s => s.green).length : 0;
    const allGreen = greenCnt === busRouteJcts.length;
    const focusPrefix = selectedBusIsFocus ? '\u2b50 GLOBAL TRACKED BUS  |  ' : '';
    const greenStatus = allGreen
      ? '\u2714 All junctions green (corridor pass achieved)'
      : `\u26a0 ${greenCnt}/${busRouteJcts.length} junctions green \u2014 ${busRouteJcts.length - greenCnt} red/amber`;
    const focusNote = selectedBusIsFocus && !allGreen
      ? '  |  Red junctions: TSP could not extend without exceeding cross-traffic delay threshold, or bus arrived outside the prepared window'
      : '';
    summary.innerHTML =
      `<span style="color:${selectedBusIsFocus?'#f1c40f':'var(--muted)'}">${focusPrefix}</span>` +
      `Bus ${filterVid}  route: ${busRouteJcts.join(' \u2192 ')}  |  ` +
      `<span style="color:${allGreen?'var(--green)':'var(--orange)'}">${greenStatus}</span>` +
      `<span style="color:var(--muted)">${focusNote}</span>` +
      `  |  Greyed = not on route  |  ` +
      `<span style="color:var(--green)">\u2713 green</span>  ` +
      `<span style="color:#f9a825">\u25c7 TSP skip (detected, not optimal)</span>  ` +
      `<span style="color:var(--purple)">\u2298 coord skip (prearm fired)</span>  ` +
      `<span style="color:var(--orange)">! late arrival</span>  ` +
      `<span style="color:var(--red)">\u2715 red</span>`;
  } else {
    summary.textContent =
      `Natural green share (unique bus\u00d7jct, only buses that visited each junction): ${ngShare}` +
      `${focusScoped && ngFocus ? ` | focus buses: ${ngFocus}` : ''}` +
      `  |  Prearm: ${r.prearm_fired||0} fired, ${r.prearm_success||0} success (${prearmRate}), ${r.prearm_missed||0} missed, ${r.prearm_late_success||0} late, ${r.prearm_expired||0} expired, ${r.prearm_discarded||0} discarded`;
    if (scoreVals.length) {
      summary.textContent += `  |  Bands: green>=${greenCut.toFixed(0)}, amber>=${amberCut.toFixed(0)} (${bandMode})`;
    }
  }
  flow.appendChild(summary);

  // Debug strip for focused bus: shows raw wave + harmony decision rows by jct.
  // Each row is {text, severity} where severity drives line highlight color.
  let flowDebugRows = [];
  let bubbleCounts = {};
  let flowDebugStats = {
    jcts: 0,
    anomaly_total: 0,
    fired_without_success: 0,
    success_without_fired: 0,
    wave_without_decision: 0,
    wave_without_detection_stop: 0,
    decision_without_wave: 0,
  };
  let flowDebugBody = null;
  let flowDebugToggleBtn = null;
  if (filterVid && busRouteJcts) {
    const dbg = document.createElement('div');
    dbg.className = 'metric-note';
    dbg.style.marginTop = '6px';
    dbg.style.whiteSpace = 'normal';
    dbg.innerHTML = `<strong>Debug (bus ${filterVid})</strong> — wave events + harmony decision at each junction `;
    const dbgLegend = document.createElement('span');
    dbgLegend.style.marginLeft = '8px';
    dbgLegend.style.fontSize = '11px';
    dbgLegend.style.color = 'var(--muted)';
    dbgLegend.innerHTML =
      `<span style="color:#ff8a80">High</span>: fired/success mismatch  |  ` +
      `<span style="color:#ffd180">Med</span>: wave without decision/detection  |  ` +
      `<span style="color:#fff59d">Low</span>: decision without wave`;
    flowDebugToggleBtn = document.createElement('button');
    flowDebugToggleBtn.className = 'run-tab';
    flowDebugToggleBtn.style.marginLeft = '8px';
    flowDebugToggleBtn.style.padding = '2px 8px';
    flowDebugToggleBtn.style.fontSize = '11px';
    flowDebugToggleBtn.textContent = 'Show debug';
    flowDebugToggleBtn.onclick = () => {
      if (!flowDebugBody) return;
      const hidden = flowDebugBody.style.display === 'none';
      flowDebugBody.style.display = hidden ? 'block' : 'none';
      flowDebugToggleBtn.textContent = hidden ? 'Hide debug' : 'Show debug';
    };
    dbg.appendChild(dbgLegend);
    dbg.appendChild(flowDebugToggleBtn);
    flow.appendChild(dbg);
  }

  const busRouteSet = busRouteJcts ? new Set(busRouteJcts) : null;
  // When a specific bus is selected, only render junctions on that bus's route.
  // In aggregate view, render all corridor junctions.
  const renderJcts = (filterVid && busRouteJcts) ? busRouteJcts : jcts;
  renderJcts.forEach((j, idx) => {
    const onRoute    = !busRouteSet || busRouteSet.has(j);
    const isPassiveJ = PASSIVE_JCTS.has(String(j));
    let pct = r.green_rates[j] ?? null;
    let pctFocus = (r.green_rates_focus || {})[j] ?? null;
    let bClass = 'bubble-r', sym = '\u2715';
    let extraLabel = '';
    let tooltipText = '';
    let busWaveAtJct = [];
    let decisionRow = null;
    let decisionNote = '';
    let decisionTier = '';
    let decisionStatus = '';
    let decisionIsNoGe = false;
    let decisionIsNoIns = false;
    let decisionIsGeAction = false;
    let decisionIsInsAction = false;
    let hadPrearmSuccess = false;
    let hadPrearmFired = false;
    let hadGrant = false;
    let hadTspSkip = false;
    let hadPrearmSkipped = false;
    let hadGrantOnly = false;
    let hadNoIntervention = true;
    let bsForDebug = null;

    // Passive/fixed junction: show different bubble, no TSP info
    if (isPassiveJ) {
      bClass = 'bubble-f';
      sym = 'FIX';
      extraLabel = 'fixed signal';
      tooltipText = 'Fixed signal timing \u2014 no TSP control at this junction';
    } else {

    // Wave events for selected bus at this junction (prearm chain data)
    busWaveAtJct = (filterVid && busJ)
      ? (busJ.wave || []).filter(w => String(w.jct) === String(j))
      : [];
    const busDecisionRows = filterVid
      ? (r.phase_samples || []).filter(p =>
          Number(p.vid) === Number(filterVid)
          && String(p.jct) === String(j)
          && typeof p.tier === 'string'
          && p.tier.startsWith('harmony-')
        )
      : [];
    decisionRow = busDecisionRows.length ? busDecisionRows[busDecisionRows.length - 1] : null;
    decisionNote = String(decisionRow?.prearm_note || '');
    decisionTier = String(decisionRow?.tier || '');
    decisionStatus = String(decisionRow?.prearm_status || '');
    decisionIsNoGe = decisionNote.startsWith('NO_GE');
    decisionIsNoIns = decisionNote.startsWith('NO_INS');
    decisionIsGeAction = decisionTier === 'harmony-ge-local' && decisionStatus === 'action';
    decisionIsInsAction = decisionTier === 'harmony-ins-local' && decisionStatus === 'action';
    hadPrearmSuccess = busWaveAtJct.some(w => w.event === 'prearm_success');
    hadPrearmFired   = busWaveAtJct.some(w => w.event === 'prearm_fired');
    hadGrant         = busWaveAtJct.some(w => w.event === 'grant');
    hadTspSkip       = busWaveAtJct.some(w => w.event === 'tsp_skip');
    hadPrearmSkipped = busWaveAtJct.some(w => w.event === 'prearm_skipped');
    hadGrantOnly     = hadGrant && !hadPrearmSuccess && !hadPrearmFired;
    hadNoIntervention = !hadPrearmSuccess && !hadPrearmFired && !hadTspSkip && !hadGrant;
    bsForDebug = (filterVid && perJctBusStats) ? (perJctBusStats[j] || null) : null;

    if (filterVid && perJctBusStats) {
      if (!onRoute) {
        bClass = 'bubble-skip'; sym = '\u00b7'; extraLabel = 'not on route';
      } else {
        const bs = bsForDebug;
        if (decisionIsGeAction || decisionIsInsAction) {
          bClass = (bs && !bs.green) ? 'bubble-o' : 'bubble-g';
          sym = '\u2713';
          extraLabel = decisionNote || (decisionIsInsAction ? 'INS action' : 'GE action');
          tooltipText = decisionIsInsAction
            ? `Phase insertion applied here${decisionNote ? ` — ${decisionNote}` : ''}`
            : `Green extension applied here${decisionNote ? ` — ${decisionNote}` : ''}`;
        } else if (decisionIsNoGe || decisionIsNoIns) {
          bClass = 'bubble-y'; sym = '\u25c7';
          extraLabel = decisionIsNoIns ? 'no INS' : 'no GE';
          tooltipText = decisionIsNoIns
            ? `Focused-bus decision: no phase insertion here${decisionNote ? ` — ${decisionNote}` : ''}`
            : `Focused-bus decision: no green extension here${decisionNote ? ` — ${decisionNote}` : ''}`;
        } else if (!bs) {
          // No detection entry \u2014 check if coordinator skipped this junction
          if (hadPrearmSkipped) {
            bClass = 'bubble-p'; sym = '\u2298'; extraLabel = 'ignored (cooldown)';
            tooltipText = 'Coordinator detected this bus but did not activate priority \u2014 junction in cooldown from a recent serve of the same bus';
          } else {
            bClass = 'bubble-o'; sym = '?'; extraLabel = 'in zone / no det';
            tooltipText = 'Bus detected near junction but phase not captured';
          }
        } else if (hadGrantOnly) {
          bClass = 'bubble-y'; sym = '\u25c7'; extraLabel = 'detected';
          tooltipText = bs.green
            ? 'Bus detected at this junction and arrived on green naturally \u2014 no prearm or phase action was started because priority was not delay-optimal'
            : 'Bus detected at this junction, but no prearm or phase action was started because priority was not delay-optimal';
        } else if (hadNoIntervention) {
          // Detected this bus but chose not to intervene (or no local action required).
          bClass = 'bubble-p'; sym = '\u2298'; extraLabel = 'detected / no action';
          tooltipText = bs.green
            ? 'Bus detected at this junction and arrived on green; controller did not apply GE/INS here'
            : 'Bus detected at this junction, but no GE/INS intervention was applied here';
        } else if (bs.green) {
          bClass = 'bubble-g'; sym = '\u2713'; extraLabel = 'green';
          tooltipText = hadPrearmSuccess
            ? 'Green \u2014 controller accepted the prearm and the bus arrived during the prepared window'
            : 'Arrived on green phase';
        } else {
          if (hadPrearmSuccess) {
            bClass = 'bubble-o'; sym = '!'; extraLabel = 'red (late)';
            tooltipText = 'Controller accepted the prearm, but the bus still reached the stop line on red \u2014 the prepared window did not line up with arrival';
          } else if (hadPrearmSkipped) {
            bClass = 'bubble-p'; sym = '\u2298'; extraLabel = 'ignored (cooldown)';
            tooltipText = 'Coordinator saw this bus but skipped priority \u2014 junction in cooldown (same bus served recently)';
          } else if (hadPrearmFired) {
            // Purple: coord system was aware of this bus but did not activate priority (not delay-optimal)
            bClass = 'bubble-p'; sym = '\u2298'; extraLabel = 'coord skip';
            tooltipText = 'Prearm fired \u2014 signal was aware of this bus but did not activate priority (not delay-optimal at this junction)';
          } else if (hadTspSkip) {
            // Amber: bus detected at this junction, TSP evaluated GE/insertion, decided not optimal
            // \u2014 harmony objective found cross-traffic cost > bus benefit, phase ended naturally
            bClass = 'bubble-y'; sym = '\u25c7'; extraLabel = 'TSP skip';
            tooltipText = 'Bus detected \u2014 TSP evaluated priority but decided not delay-optimal; phase ended naturally';
          } else {
            bClass = 'bubble-r'; sym = '\u2715'; extraLabel = 'red';
            tooltipText = selectedBusIsFocus
              ? 'Focus bus arrived on red \u2014 no prearm reached this junction'
              : 'Arrived on red phase';
          }
        }
      }
    } else {
      const colorScore = (pct === null) ? null : (scoreByJct[j] ?? null);
      if (colorScore === null)         { bClass = 'bubble-o'; sym = '?'; }
      else if (colorScore >= greenCut) { bClass = 'bubble-g'; sym = '\u2713'; }
      else if (colorScore >= amberCut) { bClass = 'bubble-o'; sym = '~'; }
      if (pct !== null) {
        const scoreTxt = (scoreByJct[j] !== undefined && scoreByJct[j] !== null)
          ? `${scoreByJct[j].toFixed(1)}` : 'n/a';
        tooltipText = `all=${pct.toFixed(1)}%${pctFocus !== null ? `, focus=${pctFocus.toFixed(1)}%` : ''}, score=${scoreTxt}, bands: g>=${greenCut.toFixed(0)} a>=${amberCut.toFixed(0)}`;
      }
    }
    } // end isPassiveJ else
    // Passive (fixed-signal) junctions are always on the corridor bus route \u2014
    // the bus physically passes through them even without TSP detection.
    // Never grey them out: always show the FIX bubble in full colour.
    const effectiveOnRoute = isPassiveJ ? true : onRoute;
    const el = document.createElement('div');
    el.className = 'flow-jct' + (filterVid && !effectiveOnRoute ? ' flow-jct-skip' : '');
    if (tooltipText) el.title = tooltipText;
    const label = (filterVid && perJctBusStats)
      ? extraLabel
      : (pct !== null
          ? (pctFocus !== null ? `${pct}% (${pctFocus}% focus)` : `${pct}%`)
          : 'no data');
    const jctLbl = isPassiveJ ? `jct ${j}<br><small>(fixed)</small>` : `jct ${j}`;
    const flowLabel = isPassiveJ ? 'fixed signal' : label;
    bubbleCounts[flowLabel] = (bubbleCounts[flowLabel] || 0) + 1;
    el.innerHTML = `<div class="name">${jctLbl}</div>
      <div class="bubble ${bClass}">${sym}</div>
      <div class="name">${flowLabel}</div>`;
    flow.appendChild(el);
    if (idx < renderJcts.length - 1) {
      const arr = document.createElement('div');
      arr.className = 'flow-arrow' + (filterVid && !effectiveOnRoute ? ' flow-arrow-skip' : '');
      arr.textContent = r.coordinated ? '\u27f9' : '->';
      flow.appendChild(arr);
    }

    // Collect a one-line debug entry per rendered junction when a bus is selected.
    if (filterVid && busRouteJcts && !isPassiveJ) {
      flowDebugStats.jcts += 1;
      const anomalies = [];
      if (hadPrearmFired && !hadPrearmSuccess) {
        anomalies.push('fired_without_success');
        flowDebugStats.fired_without_success += 1;
      }
      if (hadPrearmSuccess && !hadPrearmFired) {
        anomalies.push('success_without_fired');
        flowDebugStats.success_without_fired += 1;
      }
      if ((hadPrearmFired || hadPrearmSuccess || hadGrant || hadPrearmSkipped) && !decisionRow) {
        anomalies.push('wave_without_decision');
        flowDebugStats.wave_without_decision += 1;
      }
      if ((hadPrearmFired || hadPrearmSuccess || hadGrant) && !bsForDebug) {
        anomalies.push('wave_without_detection_stop');
        flowDebugStats.wave_without_detection_stop += 1;
      }
      if (decisionRow && !hadPrearmFired && !hadPrearmSuccess && !hadGrant && !hadTspSkip && !hadPrearmSkipped) {
        anomalies.push('decision_without_wave');
        flowDebugStats.decision_without_wave += 1;
      }
      flowDebugStats.anomaly_total += anomalies.length;

      const waveTxt = (busWaveAtJct || []).length
        ? busWaveAtJct.map(w => `${w.event}@${Number(w.t).toFixed(1)}`).join(', ')
        : 'none';
      const decisionTxt = decisionRow
        ? `${decisionTier || 'n/a'}:${decisionStatus || 'n/a'}${decisionNote ? ` (${decisionNote})` : ''}`
        : 'none';
      const stateTxt = `state=[green=${bsForDebug ? Number(bsForDebug.green) : 'na'}, fired=${hadPrearmFired ? 1 : 0}, success=${hadPrearmSuccess ? 1 : 0}, grant=${hadGrant ? 1 : 0}, tsp_skip=${hadTspSkip ? 1 : 0}, prearm_skipped=${hadPrearmSkipped ? 1 : 0}]`;
      const anomalyTxt = anomalies.length ? ` anomalies=[${anomalies.join(', ')}]` : '';
      let sev = 'ok';
      if (anomalies.some(a => a === 'fired_without_success' || a === 'success_without_fired')) {
        sev = 'high';
      } else if (anomalies.some(a => a === 'wave_without_decision' || a === 'wave_without_detection_stop')) {
        sev = 'med';
      } else if (anomalies.some(a => a === 'decision_without_wave')) {
        sev = 'low';
      }
      flowDebugRows.push({
        text: `jct ${j}: bubble=${extraLabel || bClass}; ${stateTxt}; wave=[${waveTxt}]; decision=[${decisionTxt}]${anomalyTxt}`,
        severity: sev,
      });
    }
  });

  if (filterVid && busRouteJcts && flowDebugRows.length) {
    flowDebugRows.unshift({
      text: `summary: jcts=${flowDebugStats.jcts}, anomalies=${flowDebugStats.anomaly_total}, ` +
        `fired_without_success=${flowDebugStats.fired_without_success}, ` +
        `success_without_fired=${flowDebugStats.success_without_fired}, ` +
        `wave_without_decision=${flowDebugStats.wave_without_decision}, ` +
        `wave_without_detection_stop=${flowDebugStats.wave_without_detection_stop}, ` +
        `decision_without_wave=${flowDebugStats.decision_without_wave}`,
      severity: flowDebugStats.anomaly_total > 0 ? 'med' : 'ok',
    });

    const _escHtml = (s) => String(s)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;');
    const _lineStyle = (sev) => {
      if (sev === 'high') return 'color:#ff8a80;background:#3a1212;border-left:3px solid #ff5252;padding-left:6px;';
      if (sev === 'med')  return 'color:#ffd180;background:#2f210f;border-left:3px solid #ffb74d;padding-left:6px;';
      if (sev === 'low')  return 'color:#fff59d;background:#2c2a12;border-left:3px solid #ffee58;padding-left:6px;';
      return 'color:#b0bec5;';
    };

    const dbgBody = document.createElement('div');
    dbgBody.className = 'metric-note';
    dbgBody.style.marginTop = '4px';
    dbgBody.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
    dbgBody.style.fontSize = '11px';
    dbgBody.style.display = 'none';
    dbgBody.innerHTML = flowDebugRows
      .map(rw => `<div style="${_lineStyle(rw.severity)}">${_escHtml(rw.text)}</div>`)
      .join('');
    flowDebugBody = dbgBody;
    flow.appendChild(dbgBody);
  }

  // Finalize and render runtime health summary after all counts are known.
  if (filterVid && busRouteJcts) {
    if (flowDebugStats.jcts === 0) {
      flowHealth.high.push('No active corridor junctions rendered for selected bus');
    }
    if (flowDebugStats.anomaly_total > 0) {
      flowHealth.med.push(`Debug anomalies detected: ${flowDebugStats.anomaly_total}`);
    }
    const _coordSkipCnt = bubbleCounts['coord skip'] || 0;
    if (flowDebugStats.jcts > 0 && _coordSkipCnt === flowDebugStats.jcts) {
      flowHealth.med.push('All rendered junctions are coord skip (check prearm/decision gating)');
    }
  }

  if (!flowHealth.high.length && !flowHealth.med.length) {
    flowHealth.info.push('Runtime health: OK');
  }
  const _pill = (txt, bg, fg, br) => `<span style="display:inline-block;margin-right:6px;margin-bottom:4px;padding:1px 6px;border-radius:10px;background:${bg};color:${fg};border:1px solid ${br}">${txt}</span>`;
  const parts = [];
  if (flowHealth.high.length) {
    parts.push(_pill(`HIGH ${flowHealth.high.length}`, '#3a1212', '#ff8a80', '#ff5252'));
    flowHealth.high.forEach(x => parts.push(`<div style="color:#ff8a80">• ${x}</div>`));
  }
  if (flowHealth.med.length) {
    parts.push(_pill(`MED ${flowHealth.med.length}`, '#2f210f', '#ffd180', '#ffb74d'));
    flowHealth.med.forEach(x => parts.push(`<div style="color:#ffd180">• ${x}</div>`));
  }
  if (flowHealth.info.length) {
    parts.push(_pill('INFO', '#1f2a35', '#b0bec5', '#607d8b'));
    flowHealth.info.forEach(x => parts.push(`<div style="color:#b0bec5">• ${x}</div>`));
  }
  healthEl.innerHTML = `<strong>Runtime Health</strong><div style="margin-top:4px">${parts.join('')}</div>`;
}

const tabsDiv = document.getElementById('run-tabs');
const defaultRunIdx = runs.findIndex(r => r.coordinated && (r.tsp_natural_green ?? 0) > 0);
const initialRunIdx = defaultRunIdx >= 0 ? defaultRunIdx : 0;

function buildRunTabs(containerId, onSelect) {
  const host = document.getElementById(containerId);
  if (!host) return;
  host.innerHTML = '';
  runs.forEach((r, i) => {
    const btn = document.createElement('button');
    btn.className = 'run-tab' + (i === initialRunIdx ? ' active' : '');
    btn.textContent = r.label;
    btn.onclick = () => {
      host.querySelectorAll('.run-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      onSelect(i);
    };
    host.appendChild(btn);
  });
}

runs.forEach((r,i) => {
  const btn = document.createElement('button');
  btn.className = 'run-tab' + (i===initialRunIdx?' active':'');
  const tag = r.coordinated ? '🔗 Coord' : '⚡ Indep';
  btn.textContent = `${r.label}  [${tag}]`;
  btn.onclick = () => {
    document.querySelectorAll('.run-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeInterRun = i;
    document.getElementById('bus-flow-select').value = '';
    renderCoordFlow(i);
  };
  tabsDiv.appendChild(btn);
});
if (runs.length) renderCoordFlow(initialRunIdx);

// Bus-flow dropdown listener
document.getElementById('bus-flow-select').addEventListener('change', function() {
  const vid = this.value ? parseInt(this.value) : null;
  renderCoordFlow(activeInterRun, vid);
  // Preserve selected value after re-render
  if (vid) this.value = vid;
});

document.getElementById('coord-band-mode').addEventListener('change', function() {
  const busSel = document.getElementById('bus-flow-select');
  const vid = busSel.value ? parseInt(busSel.value) : null;
  renderCoordFlow(activeInterRun, vid);
  if (vid) busSel.value = vid;
});

// ── Bus Journey Time-Space Diagram ────────────────────────────────────────
{
  const jctPos = DATA.jct_positions || {};
  // Build ordered junction list by Y coordinate (south→north)
  const orderedJcts = jcts.slice().sort((a,b) => {
    const ya = jctPos[a] ? jctPos[a].y : 0;
    const yb = jctPos[b] ? jctPos[b].y : 0;
    return ya - yb;
  });
  const jctIdxMap = {};
  orderedJcts.forEach((j, i) => { jctIdxMap[j] = i; });

  let activeJourneyRun = initialRunIdx;

  function renderJourneyMap(ri) {
    const r = runs[ri];
    const canvas = document.getElementById('journey-canvas');
    const noDataEl = document.getElementById('journey-no-data');
    const ctx = canvas.getContext('2d');
    const allJourneys = r.bus_journeys || [];

    // Apply filters
    const showFull    = document.getElementById('jrn-filter-full').checked;
    const showPartial = document.getElementById('jrn-filter-partial').checked;
    const showShort   = document.getElementById('jrn-filter-short').checked;
    const onlyPrearm  = document.getElementById('jrn-filter-prearm').checked;

    const journeys = allJourneys.filter(j => {
      const cls = j.cls || 'short';
      if (cls === 'full'    && !showFull)    return false;
      if (cls === 'partial' && !showPartial) return false;
      if (cls === 'short'   && !showShort)   return false;
      if (onlyPrearm && !(j.wave && j.wave.length)) return false;
      return true;
    });

    if (!journeys.length || orderedJcts.length < 2) {
      if (noDataEl) noDataEl.style.display = 'block';
      canvas.style.display = 'none';
      return;
    }
    if (noDataEl) noDataEl.style.display = 'none';
    canvas.style.display = '';

    // Compute layout
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth || 900;
    const H = 500;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const padL = 72, padR = 30, padT = 24, padB = 40;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;

    // Time range from filtered journeys
    let tMin = Infinity, tMax = -Infinity;
    journeys.forEach(j => {
      j.stops.forEach(s => { if (s.t < tMin) tMin = s.t; if (s.t > tMax) tMax = s.t; });
      (j.wave || []).forEach(w => { if (w.t < tMin) tMin = w.t; if (w.t > tMax) tMax = w.t; });
    });
    if (tMin >= tMax) { tMax = tMin + 600; }
    const tPad = (tMax - tMin) * 0.03;
    tMin -= tPad; tMax += tPad;

    const nJcts = orderedJcts.length;
    const xOf = t => padL + (t - tMin) / (tMax - tMin) * plotW;
    const yOf = ji => padT + plotH - (ji / Math.max(nJcts - 1, 1)) * plotH;

    // Background
    ctx.fillStyle = '#0a0a1a';
    ctx.fillRect(0, 0, W, H);

    // Grid lines & junction labels
    // Active junctions (blue label), passive/fixed junctions (orange label, dashed line)
    ctx.lineWidth = 1;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    orderedJcts.forEach((j, i) => {
      const y = yOf(i);
      const jidStr    = String(j);
      const isActive  = ACTIVE_JCTS.has(jidStr);
      const isPassive = PASSIVE_JCTS.has(jidStr);
      ctx.strokeStyle = isPassive ? '#3a2a1a' : '#1a1a3a';
      ctx.setLineDash(isPassive ? [3,4] : []);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = isActive ? '#7777aa' : (isPassive ? '#b08040' : '#555588');
      ctx.font = (isActive ? 'bold ' : '') + '11px system-ui, sans-serif';
      const lbl = isPassive ? `${j} (fixed)` : String(j);
      ctx.fillText(lbl, padL - 4, y);
    });

    // Time axis labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    const tRange = tMax - tMin;
    const nTicks = Math.min(Math.floor(plotW / 80), 12);
    const tStep = tRange / nTicks;
    for (let i = 0; i <= nTicks; i++) {
      const t = tMin + i * tStep;
      const x = xOf(t);
      ctx.strokeStyle = '#1a1a3a';
      ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, H - padB); ctx.stroke();
      const mins = Math.floor(t / 60);
      const secs = Math.floor(t % 60);
      ctx.fillStyle = '#7777aa';
      ctx.fillText(mins + ':' + String(secs).padStart(2, '0'), x, H - padB + 4);
    }
    ctx.fillStyle = '#9999bb';
    ctx.font = '12px system-ui, sans-serif';
    ctx.fillText('Simulation time (min:sec)', padL + plotW / 2, H - 6);

    // Color palette
    const busColors = [
      'rgba(46,204,113,0.55)', 'rgba(52,152,219,0.55)', 'rgba(155,89,182,0.55)',
      'rgba(241,196,15,0.55)', 'rgba(230,126,34,0.55)', 'rgba(231,76,60,0.55)',
      'rgba(26,188,156,0.55)', 'rgba(149,165,166,0.55)', 'rgba(236,240,241,0.45)',
    ];

    // Draw bus journeys
    journeys.forEach((j, bi) => {
      const stops = j.stops.filter(s => jctIdxMap[String(s.jct)] !== undefined);
      if (stops.length < 2) return;

      const cls = j.cls || 'short';
      const hasWave = j.wave && j.wave.length > 0;
      const lineColor = busColors[bi % busColors.length];

      // Line style by classification
      ctx.strokeStyle = lineColor;
      if (cls === 'full') {
        ctx.lineWidth = 2.4;
        ctx.setLineDash([]);
      } else if (cls === 'partial') {
        ctx.lineWidth = 1.6;
        ctx.setLineDash([8, 4]);
      } else {
        ctx.lineWidth = 1.0;
        ctx.setLineDash([3, 3]);
      }

      // Draw line segments
      ctx.beginPath();
      stops.forEach((s, si) => {
        const x = xOf(s.t);
        const y = yOf(jctIdxMap[String(s.jct)]);
        if (si === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.setLineDash([]);

      // Draw dots at each detection stop
      stops.forEach(s => {
        const x = xOf(s.t);
        const y = yOf(jctIdxMap[String(s.jct)]);
        ctx.beginPath();
        ctx.arc(x, y, cls === 'full' ? 5 : 4, 0, Math.PI * 2);
        ctx.fillStyle = s.on_green ? '#2ecc71' : '#e74c3c';
        ctx.fill();
        ctx.strokeStyle = s.on_green ? '#1a9c52' : '#b03a2e';
        ctx.lineWidth = 1.2;
        ctx.stroke();
      });

      // Draw wave event markers
      if (hasWave) {
        (j.wave).forEach(w => {
          const ji = jctIdxMap[String(w.jct)];
          if (ji === undefined) return;
          const x = xOf(w.t);
          const y = yOf(ji);
          const evt = w.event;

          if (evt === 'prearm_fired') {
            // Diamond marker
            ctx.fillStyle = '#f1c40f';
            ctx.beginPath();
            ctx.moveTo(x, y - 6); ctx.lineTo(x + 5, y);
            ctx.lineTo(x, y + 6); ctx.lineTo(x - 5, y); ctx.closePath();
            ctx.fill();
          } else if (evt === 'prearm_success') {
            // Star / filled star
            ctx.fillStyle = '#2ecc71';
            ctx.font = 'bold 14px sans-serif';
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText('★', x, y);
          } else if (evt === 'prearm_missed' || evt === 'prearm_expired') {
            // Red X
            ctx.strokeStyle = '#e74c3c';
            ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(x - 4, y - 4); ctx.lineTo(x + 4, y + 4); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(x + 4, y - 4); ctx.lineTo(x - 4, y + 4); ctx.stroke();
          } else if (evt === 'grant') {
            // Blue triangle (grant at source junction)
            ctx.fillStyle = '#3498db';
            ctx.beginPath();
            ctx.moveTo(x, y - 5); ctx.lineTo(x + 5, y + 3); ctx.lineTo(x - 5, y + 3);
            ctx.closePath(); ctx.fill();
          }
        });
      }
    });

    // Summary counts
    const nFull = journeys.filter(j => j.cls === 'full').length;
    const nPartial = journeys.filter(j => j.cls === 'partial').length;
    const nShort = journeys.filter(j => j.cls === 'short').length;
    const nWithWave = journeys.filter(j => j.wave && j.wave.length).length;

    // Title
    ctx.fillStyle = '#bbbbdd';
    ctx.font = 'bold 13px system-ui, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(
      r.label + ' — ' + journeys.length + ' buses shown' +
      ' (full:' + nFull + ' partial:' + nPartial + ' short:' + nShort +
      ' prearm:' + nWithWave + ')',
      padL, 4
    );
  }

  const journeyTabsDiv = document.getElementById('journey-run-tabs');
  runs.forEach((r, i) => {
    const btn = document.createElement('button');
    btn.className = 'run-tab' + (i === initialRunIdx ? ' active' : '');
    btn.textContent = r.label;
    btn.onclick = () => {
      document.querySelectorAll('#journey-run-tabs .run-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeJourneyRun = i;
      renderJourneyMap(i);
    };
    journeyTabsDiv.appendChild(btn);
  });
  // Filter checkbox listeners
  ['jrn-filter-full','jrn-filter-partial','jrn-filter-short','jrn-filter-prearm'].forEach(id => {
    document.getElementById(id).addEventListener('change', () => renderJourneyMap(activeJourneyRun));
  });
  if (runs.length) renderJourneyMap(initialRunIdx);
}

// ── Corridor Spatial Map ──────────────────────────────────────────────────
{
  const jctPos = DATA.jct_positions || {};
  const orderedJcts = jcts.slice().sort((a,b) => {
    const ya = jctPos[a] ? jctPos[a].y : 0;
    const yb = jctPos[b] ? jctPos[b].y : 0;
    return ya - yb;
  });
  let activeSpatRun = 0;
  const spatCanvas = document.getElementById('spatmap-canvas');
  const spatCtx = spatCanvas ? spatCanvas.getContext('2d') : null;

  function renderSpatialMap(ri, filterVid) {
    if (!spatCtx) return;
    const r = runs[ri];
    const allJ = r.bus_journeys || [];
    const sel = document.getElementById('spatmap-bus-select');
    const showSpine = document.getElementById('spatmap-show-corridor').checked;
    const showGreen = document.getElementById('spatmap-show-green').checked;

    // Populate bus dropdown (only on first render or run change)
    if (!filterVid) {
      sel.innerHTML = '<option value="">All buses</option>';
      const corridorBuses = allJ.filter(j => j.n_jcts >= 2)
                                .sort((a,b) => (a.stops[0]?.t||0) - (b.stops[0]?.t||0));
      corridorBuses.forEach(j => {
        const opt = document.createElement('option');
        opt.value = j.vid;
        const gc = j.stops.filter(s => s.on_green).length;
        opt.textContent = `Bus ${j.vid}  (${j.cls}, ${j.n_jcts} jcts, ${gc}/${j.stops.length} green)`;
        sel.appendChild(opt);
      });
    }

    // Gather all XY points for scaling
    const allPts = [];
    for (const jid of orderedJcts) {
      const p = jctPos[jid];
      if (p) allPts.push(p);
    }
    // Include bus stops with valid XY
    const busesToDraw = filterVid
      ? allJ.filter(j => j.vid == filterVid)
      : allJ.filter(j => j.n_jcts >= 3);
    busesToDraw.forEach(j => {
      j.stops.forEach(s => { if (s.x && s.y) allPts.push({x: s.x, y: s.y}); });
    });
    if (allPts.length < 2) { spatCtx.clearRect(0,0,spatCanvas.width,spatCanvas.height); return; }

    const minX = Math.min(...allPts.map(p=>p.x));
    const maxX = Math.max(...allPts.map(p=>p.x));
    const minY = Math.min(...allPts.map(p=>p.y));
    const maxY = Math.max(...allPts.map(p=>p.y));
    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;

    const dpr = window.devicePixelRatio || 1;
    const W = spatCanvas.clientWidth;
    const H = spatCanvas.clientHeight || 500;
    spatCanvas.width = W * dpr;
    spatCanvas.height = H * dpr;
    spatCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    spatCtx.clearRect(0, 0, W, H);

    const pad = 40;
    const mapW = W - 2*pad;
    const mapH = H - 2*pad;
    // Maintain aspect ratio
    const scaleX = mapW / rangeX;
    const scaleY = mapH / rangeY;
    const sc = Math.min(scaleX, scaleY);
    const offX = pad + (mapW - rangeX * sc) / 2;
    const offY = pad + (mapH - rangeY * sc) / 2;
    function tx(x) { return offX + (x - minX) * sc; }
    function ty(y) { return offY + mapH - (y - minY) * sc; }  // flip Y (south=bottom)

    // Draw corridor spine
    if (showSpine) {
      spatCtx.beginPath();
      spatCtx.strokeStyle = '#555';
      spatCtx.lineWidth = 1.5;
      spatCtx.setLineDash([6, 4]);
      let first = true;
      orderedJcts.forEach(jid => {
        const p = jctPos[jid];
        if (!p) return;
        if (first) { spatCtx.moveTo(tx(p.x), ty(p.y)); first = false; }
        else spatCtx.lineTo(tx(p.x), ty(p.y));
      });
      spatCtx.stroke();
      spatCtx.setLineDash([]);
    }

    // Draw bus paths
    const busColors = ['#8e44ad','#e67e22','#1abc9c','#e74c3c','#3498db',
                       '#f39c12','#2ecc71','#9b59b6','#d35400','#16a085'];
    busesToDraw.forEach((j, bi) => {
      const validStops = j.stops.filter(s => s.x && s.y);
      if (validStops.length < 2) return;
      const col = filterVid ? '#8e44ad' : busColors[bi % busColors.length];
      spatCtx.beginPath();
      spatCtx.strokeStyle = col;
      spatCtx.lineWidth = filterVid ? 2.5 : 1.2;
      spatCtx.globalAlpha = filterVid ? 1.0 : 0.45;
      spatCtx.moveTo(tx(validStops[0].x), ty(validStops[0].y));
      for (let k = 1; k < validStops.length; k++) {
        spatCtx.lineTo(tx(validStops[k].x), ty(validStops[k].y));
      }
      spatCtx.stroke();
      spatCtx.globalAlpha = 1.0;

      // Draw stop dots
      if (filterVid || busesToDraw.length <= 5) {
        validStops.forEach(s => {
          spatCtx.beginPath();
          const dotCol = showGreen ? (s.on_green ? '#2ecc71' : '#e74c3c') : col;
          spatCtx.fillStyle = dotCol;
          spatCtx.arc(tx(s.x), ty(s.y), filterVid ? 5 : 3, 0, Math.PI*2);
          spatCtx.fill();
        });
      }

      // Label bus ID
      if (filterVid || busesToDraw.length <= 10) {
        const last = validStops[validStops.length-1];
        spatCtx.fillStyle = col;
        spatCtx.font = '10px sans-serif';
        spatCtx.fillText(`bus ${j.vid}`, tx(last.x)+6, ty(last.y)-4);
      }
    });

    // Draw junction markers (on top)
    // Active junctions (TSP-controlled) = blue; passive/fixed = orange; unknown = grey
    orderedJcts.forEach(jid => {
      const p = jctPos[jid];
      if (!p) return;
      const isActive  = ACTIVE_JCTS.has(String(jid));
      const isPassive = PASSIVE_JCTS.has(String(jid));
      const dotCol  = isActive ? '#3498db' : (isPassive ? '#f39c12' : '#888');
      const lblCol  = isActive ? '#ddd'    : (isPassive ? '#f39c12' : '#888');
      spatCtx.beginPath();
      spatCtx.fillStyle = dotCol;
      spatCtx.arc(tx(p.x), ty(p.y), isActive ? 7 : 5, 0, Math.PI*2);
      spatCtx.fill();
      spatCtx.strokeStyle = '#fff';
      spatCtx.lineWidth = 1.5;
      spatCtx.stroke();
      // Label
      spatCtx.fillStyle = lblCol;
      spatCtx.font = (isActive ? 'bold ' : '') + '10px sans-serif';
      spatCtx.textAlign = 'left';
      const lbl = isActive ? `jct ${jid}` : `jct ${jid} (fixed)`;
      spatCtx.fillText(lbl, tx(p.x)+9, ty(p.y)+3);
    });
  }

  // Run tabs
  const spatTabsDiv = document.getElementById('spatmap-run-tabs');
  runs.forEach((r,i) => {
    const btn = document.createElement('button');
    btn.className = 'run-tab' + (i===initialRunIdx?' active':'');
    const tag = r.coordinated ? '🔗' : '⚡';
    btn.textContent = `${r.label}  [${tag}]`;
    btn.onclick = () => {
      spatTabsDiv.querySelectorAll('.run-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeSpatRun = i;
      document.getElementById('spatmap-bus-select').value = '';
      renderSpatialMap(i);
    };
    spatTabsDiv.appendChild(btn);
  });

  // Bus dropdown listener
  document.getElementById('spatmap-bus-select').addEventListener('change', function() {
    const vid = this.value ? parseInt(this.value) : null;
    renderSpatialMap(activeSpatRun, vid);
    if (vid) this.value = vid;
  });
  // Checkbox listeners
  ['spatmap-show-corridor','spatmap-show-green'].forEach(id => {
    document.getElementById(id).addEventListener('change', () => {
      const vid = document.getElementById('spatmap-bus-select').value;
      renderSpatialMap(activeSpatRun, vid ? parseInt(vid) : null);
    });
  });
  if (runs.length) renderSpatialMap(initialRunIdx);
}

// ── Coordination Example chart ────────────────────────────────────────────
// Shows a detailed per-bus view: signal phase bands at each junction over time,
// overlaid with pre-arm events, bus arrival dots, and TSP grant markers.
{
  let activeCoordExRun = initialRunIdx;
  let activeCoordExVid = null;

  const coordExCanvas  = document.getElementById('coordex-canvas');
  const coordExCtx     = coordExCanvas ? coordExCanvas.getContext('2d') : null;
  const coordExNoData  = document.getElementById('coordex-no-data');
  const coordExBusSel  = document.getElementById('coordex-bus-select');
  const coordExBusInfo = document.getElementById('coordex-bus-info');

  // Ordered junctions for the coord-ex chart (S→N, same as journey map)
  const coordExJcts = jcts.slice().sort((a, b) => {
    const jp = DATA.jct_positions || {};
    return (jp[a] ? jp[a].y : 0) - (jp[b] ? jp[b].y : 0);
  });

  function _populateCoordExBusSelect(ri) {
    const r = runs[ri];
    const allJ = (r.bus_journeys || []).filter(j => (j.stops || []).length >= 2);
    coordExBusSel.innerHTML = '<option value="">— select a bus —</option>';
    allJ.sort((a,b) => (a.stops[0]?.t||0) - (b.stops[0]?.t||0)).forEach(j => {
      const opt = document.createElement('option');
      opt.value = j.vid;
      const gc = j.stops.filter(s => s.on_green).length;
      const nPrearm = (j.wave||[]).filter(w => w.event === 'prearm_fired').length;
      const nActions = ((r.phase_samples || []).concat(r.objective_trace || [])).filter(p =>
        Number(p.vid) === Number(j.vid)
        && ((p.tier === 'harmony-ge-local' || p.tier === 'harmony-ins-local')
            || String(p.mode || '').toUpperCase() === 'GE'
            || String(p.mode || '').toUpperCase() === 'INS')
        && (p.prearm_status === 'action' || String(p.decision || '').toUpperCase() === 'ACTION')
      ).length;
      opt.textContent = `Bus ${j.vid}  (${j.cls}, ${j.n_jcts} jcts, ${gc}/${j.stops.length} green, ${nPrearm} prearms, ${nActions} actions)`;
      coordExBusSel.appendChild(opt);
    });
    // Auto-select first bus with wave events
    if (allJ.length && !activeCoordExVid) {
      coordExBusSel.value = allJ[0].vid;
      activeCoordExVid = allJ[0].vid;
    } else if (!allJ.length) {
      activeCoordExVid = null;
    }
  }

  function renderCoordExample(ri, vidOverride) {
    if (!coordExCtx) return;
    const r = runs[ri];
    const allJ = r.bus_journeys || [];
    const vid  = vidOverride !== undefined ? vidOverride : activeCoordExVid;
    const journey = vid ? allJ.find(j => String(j.vid) === String(vid)) : null;

    if (!journey) {
      if (coordExNoData) { coordExNoData.textContent = allJ.length ?
        'Select a bus above.' :
        'No bus journey data available for this run.';
        coordExNoData.style.display = ''; }
      coordExCanvas.style.display = 'none';
      if (coordExBusInfo) coordExBusInfo.textContent = '';
      const _wrap = document.getElementById('coordex-reward-wrap');
      if (_wrap) _wrap.style.display = 'none';
      return;
    }
    if (coordExNoData) coordExNoData.style.display = 'none';
    coordExCanvas.style.display = '';

    const stops    = journey.stops || [];
    const wave     = (journey.wave || []).slice().sort((a,b) => a.t - b.t);
    const focusRows = (r.focus_history || []).filter(f => Number(f.veh_id) === Number(journey.vid));
    const allFocusRows = (r.focus_history || []);
    const jctSet   = new Set(stops.map(s => String(s.jct)));
    const drawJcts = coordExJcts.filter(j => jctSet.has(String(j)));
    if (!drawJcts.length) { coordExCanvas.style.display = 'none'; return; }

    // Time window: earliest prearm or stop, to latest stop + 30s
    let tMin = Infinity, tMax = -Infinity;
    stops.forEach(s  => { tMin = Math.min(tMin, s.t); tMax = Math.max(tMax, s.t); });
    wave.forEach(w   => { tMin = Math.min(tMin, w.t); tMax = Math.max(tMax, w.t); });
    if (!isFinite(tMin)) { coordExCanvas.style.display = 'none'; return; }
    tMin = Math.max(0, tMin - 30);
    tMax = tMax + 45;

    // Canvas sizing
    const dpr = window.devicePixelRatio || 1;
    const W   = coordExCanvas.clientWidth || 900;
    const ROW_H = 44;
    const H   = Math.max(200, drawJcts.length * ROW_H + 70);
    coordExCanvas.width  = W * dpr;
    coordExCanvas.height = H * dpr;
    coordExCanvas.style.height = H + 'px';
    coordExCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    coordExCtx.clearRect(0, 0, W, H);

    const hasFocusBand = focusRows.length > 0;
    const padL = 74, padR = 24, padT = 30, padB = hasFocusBand ? 68 : 38;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;

    const xOf = t  => padL + (t - tMin) / (tMax - tMin) * plotW;
    const yOf = ji => padT + (ji + 0.5) / drawJcts.length * plotH;

    // Background
    coordExCtx.fillStyle = '#0a0a1a';
    coordExCtx.fillRect(0, 0, W, H);

    // Row backgrounds
    drawJcts.forEach((jid, ji) => {
      const y0 = padT + (ji / drawJcts.length) * plotH;
      const y1 = padT + ((ji + 1) / drawJcts.length) * plotH;
      coordExCtx.fillStyle = ji % 2 === 0 ? '#0d0d22' : '#101030';
      coordExCtx.fillRect(padL, y0, plotW, y1 - y0);
      // Junction label
      coordExCtx.fillStyle = '#8888bb';
      coordExCtx.font = '11px system-ui, sans-serif';
      coordExCtx.textAlign = 'right';
      coordExCtx.textBaseline = 'middle';
      coordExCtx.fillText('jct ' + jid, padL - 6, yOf(ji));
    });

    // Time axis
    coordExCtx.strokeStyle = '#1a1a3a';
    coordExCtx.lineWidth = 1;
    const tRange = tMax - tMin;
    const nTicks = Math.min(Math.floor(plotW / 70), 12);
    for (let i = 0; i <= nTicks; i++) {
      const t = tMin + i * (tRange / nTicks);
      const x = xOf(t);
      coordExCtx.beginPath(); coordExCtx.moveTo(x, padT); coordExCtx.lineTo(x, H - padB); coordExCtx.stroke();
      const mins = Math.floor(t / 60), secs = Math.floor(t % 60);
      coordExCtx.fillStyle = '#7777aa';
      coordExCtx.font = '10px system-ui';
      coordExCtx.textAlign = 'center';
      coordExCtx.textBaseline = 'top';
      coordExCtx.fillText(mins + ':' + String(secs).padStart(2,'0'), x, H - padB + 3);
    }
    coordExCtx.fillStyle = '#9999bb';
    coordExCtx.font = '11px system-ui';
    coordExCtx.textAlign = 'center';
    coordExCtx.fillText('Simulation time (mm:ss)', padL + plotW/2, H - 6);

    // Vertical 'now' line at bus arrival per junction
    const arrivalByJct = {};
    stops.forEach(s => { arrivalByJct[String(s.jct)] = s; });

    // ── Per-junction decision data from phase_samples + objective trace ───
    // Build a lookup: jct -> list of harmony decision rows for this bus,
    // sorted by sim time so we can find the latest decision before arrival.
    const decisionsByJct = {};
    const objectiveByJct = {};
    (r.phase_samples || []).forEach(p => {
      if (Number(p.vid) !== Number(journey.vid)) return;
      if (typeof p.tier !== 'string' || !p.tier.startsWith('harmony-')) return;
      const key = String(p.jct);
      if (!decisionsByJct[key]) decisionsByJct[key] = [];
      decisionsByJct[key].push(p);
    });
    (r.objective_trace || []).forEach(p => {
      if (Number(p.vid) !== Number(journey.vid)) return;
      const mode = String(p.mode || '').toUpperCase();
      const decision = String(p.decision || '').toUpperCase();
      if (mode !== 'GE' && mode !== 'INS') return;
      const key = String(p.jct);
      if (!objectiveByJct[key]) objectiveByJct[key] = [];
      const savedPax = Number(p.delay_saved_pax_s);
      const savedTxt = Number.isFinite(savedPax) ? ` | saved=${savedPax.toFixed(1)} pax-s` : '';
      objectiveByJct[key].push({
        t: Number(p.t) || 0,
        jct: Number(p.jct) || 0,
        vid: Number(p.vid) || 0,
        tier: mode === 'GE'
          ? (decision === 'ACTION' ? 'harmony-ge-local' : 'harmony-no-ge-local')
          : (decision === 'ACTION' ? 'harmony-ins-local' : 'harmony-no-ins-local'),
        prearm_status: decision === 'ACTION' ? 'action' : 'skip',
        prearm_note: [String(p.reason || '').trim(), String(p.note || '').trim(), savedTxt].filter(Boolean).join(' | '),
        delay_saved_pax_s: Number.isFinite(savedPax) ? savedPax : null,
      });
    });
    Object.keys(objectiveByJct).forEach(key => {
      if (!decisionsByJct[key]) decisionsByJct[key] = [];
      decisionsByJct[key] = decisionsByJct[key].concat(objectiveByJct[key]);
    });
    Object.values(decisionsByJct).forEach(arr =>
      arr.sort((a, b) => (Number(a.t) || 0) - (Number(b.t) || 0)));

    // Helper: format seconds as mm:ss
    function fmtT(s) {
      const m = Math.floor(s / 60), sec = Math.floor(s % 60);
      return m + ':' + String(sec).padStart(2, '0');
    }

    function _decisionReasonToken(note, prefix) {
      const raw = String(note || '');
      let body = raw;
      if (prefix && body.startsWith(prefix)) body = body.slice(prefix.length);
      const head = body.split(';')[0] || body;
      return head.trim();
    }

    function _decisionReasonText(tok, isGe) {
      const t = String(tok || '').trim();
      if (!t) return isGe ? 'GE not applied (unspecified)' : 'INS not applied (unspecified)';
      if (t === 'natural_green_future_bus_phase') return 'Natural future bus phase catchable; no forced action';
      if (t === 'natural_green_current_phase') return 'Current phase already serves bus movement; no intervention needed';
      if (t === 'impractical_upper_bound') return 'Bus ETA exceeds insertion upper bound; insertion not practical';
      if (t === 'not_optimal' || t === 'not_optimal_too_short' || t === 'too_short') return 'Objective evaluated but rejected as not beneficial';
      if (t === 'harmony_nan') return 'Optimizer returned NaN; action skipped for safety';
      if (t === 'no_bus_detected') return 'No valid bus detected at decision step';
      if (t === 'cooldown') return 'Junction cooldown active after recent serve';
      return t.replaceAll('_', ' ');
    }

    // Draw signal-phase bands: green band around each prearm target junction's
    // green window (estimated from prearm ETA), red on either side.
    // For each junction we also draw explicit harmony decisions, GE/INS windows,
    // and start/end time labels.
    drawJcts.forEach((jid, ji) => {
      const y0 = padT + (ji / drawJcts.length) * plotH + 2;
      const y1 = padT + ((ji+1) / drawJcts.length) * plotH - 2;
      const midY = (y0 + y1) / 2;
      const rowH = (y1 - y0);
      const bandH = Math.max(6, rowH * 0.35);

      // Find prearm/wave events targeting this junction
      const jWave = wave.filter(w => String(w.jct) === String(jid));
      const jPrearms = jWave.filter(w => w.event === 'prearm_fired');
      const arrSt = arrivalByJct[String(jid)];
      const arrIsFocusAtJct = arrSt ? allFocusRows.some(f =>
        Number(f.veh_id) === Number(journey.vid)
        && Number(f.jct_id) === Number(jid)
        && Number(arrSt.t) >= (Number(f.start_t) - 1.0)
        && Number(arrSt.t) <= (Number(f.end_t) + 1.0)
      ) : false;
      const otherFocusRow = arrSt ? allFocusRows.find(f =>
        Number(f.veh_id) !== Number(journey.vid)
        && Number(arrSt.t) >= (Number(f.start_t) - 1.0)
        && Number(arrSt.t) <= (Number(f.end_t) + 1.0)
      ) : null;

      // Decision rows for this junction
      const jDecisions = decisionsByJct[String(jid)] || [];
      // Pick the last decision before the bus arrival (or last overall)
      const arrT_jct = arrSt ? arrSt.t : Infinity;
      const decisionsBeforeArr = jDecisions.filter(d => Number(d.t) <= arrT_jct + 2);
      const latestDecision = decisionsBeforeArr.length
        ? decisionsBeforeArr[decisionsBeforeArr.length - 1]
        : (arrSt
            ? (jDecisions
                .filter(d => Math.abs(Number(d.t) - arrT_jct) <= 30)
                .sort((a, b) => Math.abs(Number(a.t) - arrT_jct) - Math.abs(Number(b.t) - arrT_jct))[0] || null)
            : (jDecisions.length ? jDecisions[jDecisions.length - 1] : null));

      const hasPrearmChain = jWave.some(w =>
        w.event === 'prearm_fired' ||
        w.event === 'prearm_success' ||
        w.event === 'prearm_missed' ||
        w.event === 'prearm_expired'
      );

      // Draw a thin horizontal guide line
      coordExCtx.strokeStyle = '#1a1a3a';
      coordExCtx.lineWidth = 1;
      coordExCtx.beginPath();
      coordExCtx.moveTo(padL, midY); coordExCtx.lineTo(W - padR, midY);
      coordExCtx.stroke();

      // ── GE / INS action window ────────────────────────────────────────
      // For GE: use harmony-ge-local detection row as GE-start; bus arrival
      // or arrival + grace as GE-end.  Draw a filled green band over the row.
      // For INS: use harmony-ins-local row time and mark with a cyan band.
      if (latestDecision) {
        const dn = String(latestDecision.prearm_note || '');
        const dt = Number(latestDecision.t) || 0;
        const dTier = String(latestDecision.tier || '');
        const isGe = dTier === 'harmony-ge-local';
        const isIns = dTier === 'harmony-ins-local';
        if (isGe || isIns) {
          // Action window: start = decision time, end = bus arrival (or +30s estimate)
          const windowEnd = arrSt ? arrSt.t : dt + 30;
          const wx0 = xOf(dt);
          const wx1 = xOf(Math.min(windowEnd, tMax - 1));
          const wColor = isIns ? 'rgba(0,188,212,0.13)' : 'rgba(46,204,113,0.13)';
          const wBorder = isIns ? 'rgba(0,188,212,0.55)' : 'rgba(46,204,113,0.55)';
          coordExCtx.fillStyle = wColor;
          coordExCtx.fillRect(wx0, y0, wx1 - wx0, y1 - y0);
          // Left border = action start
          coordExCtx.strokeStyle = wBorder;
          coordExCtx.lineWidth = 2;
          coordExCtx.beginPath(); coordExCtx.moveTo(wx0, y0); coordExCtx.lineTo(wx0, y1); coordExCtx.stroke();
          // Right border = action end
          coordExCtx.strokeStyle = wBorder;
          coordExCtx.lineWidth = 1.5;
          coordExCtx.setLineDash([3, 2]);
          coordExCtx.beginPath(); coordExCtx.moveTo(wx1, y0); coordExCtx.lineTo(wx1, y1); coordExCtx.stroke();
          coordExCtx.setLineDash([]);
          // Parse action duration from prearm_note (e.g. 'DCTSP INS_10s r=4.84s' or 'DCTSP GE_15s r=23.80s')
          const _noteStr = String(latestDecision.prearm_note || '');
          const _durMatch = _noteStr.match(/(INS|GE)_(\d+)s/);
          const _actDurSuffix = _durMatch ? ` [${_durMatch[2]}s]` : '';
          // Start time label above left border
          coordExCtx.fillStyle = isIns ? '#00bcd4' : '#2ecc71';
          coordExCtx.font = 'bold 9px system-ui';
          coordExCtx.textAlign = 'left';
          coordExCtx.textBaseline = 'bottom';
          coordExCtx.fillText((isIns ? 'INS ▶' : 'GE ▶') + _actDurSuffix + ' ' + fmtT(dt), wx0 + 2, midY - bandH/2 - 1);
          // End time label above right border
          coordExCtx.textAlign = 'right';
          coordExCtx.fillText('◀' + fmtT(windowEnd), wx1 - 2, midY - bandH/2 - 1);
        }
      }

      // ── Arrival marker ───────────────────────────────────────────────
      if (arrSt) {
        const ax = xOf(arrSt.t);
        const arrIsFocus = arrIsFocusAtJct;
        const phaseW = Math.max(4, plotW * (20 / tRange));
        coordExCtx.fillStyle = arrSt.on_green ? 'rgba(46,204,113,0.18)' : 'rgba(231,76,60,0.18)';
        coordExCtx.fillRect(ax - phaseW/2, midY - bandH/2, phaseW, bandH);
        coordExCtx.strokeStyle = arrSt.on_green ? '#2ecc71' : '#e74c3c';
        coordExCtx.lineWidth = 1.5;
        coordExCtx.setLineDash([3,2]);
        coordExCtx.beginPath();
        coordExCtx.moveTo(ax, y0); coordExCtx.lineTo(ax, y1);
        coordExCtx.stroke();
        coordExCtx.setLineDash([]);
        coordExCtx.beginPath();
        coordExCtx.arc(ax, midY, 5, 0, Math.PI*2);
        coordExCtx.fillStyle = arrSt.on_green ? '#2ecc71' : '#e74c3c';
        coordExCtx.fill();
        coordExCtx.strokeStyle = '#000';
        coordExCtx.lineWidth = 1;
        coordExCtx.stroke();
        if (arrIsFocus) {
          coordExCtx.beginPath();
          coordExCtx.arc(ax, midY, 8, 0, Math.PI * 2);
          coordExCtx.strokeStyle = '#f1c40f';
          coordExCtx.lineWidth = 1.6;
          coordExCtx.stroke();
        }
        coordExCtx.fillStyle = '#ccc';
        coordExCtx.font = '9px system-ui';
        coordExCtx.textAlign = 'center';
        coordExCtx.textBaseline = 'bottom';
        coordExCtx.fillText((arrIsFocus ? 'focus ' : 'arr ') + fmtT(arrSt.t), ax, midY - bandH/2 - 1);
      }

      // ── Decision label (right-hand side of row) ─────────────────────
      // Show what the Harmony controller decided at this junction.
      // Priority: explicit local action rows > prearm chain > grant/detected.
      {
        let decLabel = '';
        let decColor = '#7777aa';
        if (latestDecision) {
          const dn = String(latestDecision.prearm_note || '');
          const dTier = String(latestDecision.tier || '');
          const dStatus = String(latestDecision.prearm_status || '');
          const dSaved = Number(latestDecision.delay_saved_pax_s);
          const savedTail = Number.isFinite(dSaved) ? ` (saved ${dSaved.toFixed(1)} pax-s)` : '';
          if (dTier === 'harmony-ge-local')  { decLabel = '→ GE applied' + savedTail; decColor = '#2ecc71'; }
          else if (dTier === 'harmony-ins-local') {
            const _insDurM = String(latestDecision.prearm_note || '').match(/INS_(\d+)s/);
            const _insDurStr = _insDurM ? ` [${_insDurM[1]}s insertion]` : '';
            decLabel = '→ INS applied' + _insDurStr + savedTail; decColor = '#00bcd4';
          }
          else if (dTier === 'harmony-no-ge-local')  {
            const reason = _decisionReasonText(_decisionReasonToken(dn, 'NO_GE '), true);
            decLabel = 'no GE: ' + reason.substring(0, 46);
            decColor = '#f1c40f';
          } else if (dTier === 'harmony-no-ins-local') {
            const reason = _decisionReasonText(_decisionReasonToken(dn, 'NO_INS '), false);
            decLabel = 'no INS: ' + reason.substring(0, 46);
            decColor = '#e67e22';
          } else if (dTier === 'focus_suppress') {
            const fb = dn.replace('focus_bus=', '');
            decLabel = `focus suppressed — bus ${fb} held corridor priority`;
            decColor = '#9b59b6';
          } else if (dTier === 'IC-detect-far') {
            const etaStr = dn.replace('eta_too_far=', '').replace('s', '');
            decLabel = `bus too far (ETA ${Number(etaStr).toFixed(0) || '?'}s > horizon) — detection only`;
            decColor = '#888888';
          } else if (dStatus === 'skip') {
            decLabel = 'detected, skipped by local controller';
            decColor = '#f39c12';
          }
        }
        if (!decLabel && otherFocusRow && !arrIsFocusAtJct) {
          decLabel = `not focus (bus ${otherFocusRow.veh_id} held corridor priority)`;
          decColor = '#9b59b6';
        }
        if (!decLabel && hasPrearmChain) {
          const hadPrearmFired = jWave.some(w => w.event === 'prearm_fired');
          const hadPrearmSuccess = jWave.some(w => w.event === 'prearm_success');
          const hadPrearmMissed = jWave.some(w => w.event === 'prearm_missed' || w.event === 'prearm_expired');
          if (hadPrearmSuccess) {
            decLabel = 'prearm accepted; bus still arrived late';
          } else if (hadPrearmMissed) {
            decLabel = 'prearm fired but window missed/expired';
          } else if (hadPrearmFired) {
            decLabel = 'prearm fired; no local GE/INS decision row';
          } else {
            decLabel = 'coordinator observed bus; no local action row';
          }
          decColor = '#9b59b6';
        }
        if (!decLabel) {
          const firstGrant = jWave.find(w => w.event === 'grant');
          if (firstGrant) { decLabel = 'detected at stopline; no GE/INS row'; decColor = '#7f8c8d'; }
        }
        if (!decLabel && arrSt) {
          decLabel = arrSt.on_green
            ? 'natural green; no intervention required'
            : 'arrived on red; no eligible GE/INS decision near arrival';
          decColor = arrSt.on_green ? '#2ecc71' : '#e74c3c';
        }
        if (!decLabel && !arrSt) { decLabel = 'not visited'; decColor = '#444466'; }
        if (decLabel) {
          coordExCtx.fillStyle = decColor;
          coordExCtx.font = '9px system-ui';
          coordExCtx.textAlign = 'right';
          coordExCtx.textBaseline = 'top';
          coordExCtx.fillText(decLabel, W - padR - 2, y0 + 2);
        }
      }

      // ── Prearm markers ───────────────────────────────────────────────
      jPrearms.forEach(w => {
        const px = xOf(w.t);
        const arrT = arrSt ? arrSt.t : (w.t + 30);
        const arrX = xOf(Math.min(arrT, tMax - 1));
        coordExCtx.strokeStyle = 'rgba(241,196,15,0.5)';
        coordExCtx.lineWidth = 1;
        coordExCtx.setLineDash([4,3]);
        coordExCtx.beginPath();
        coordExCtx.moveTo(px, midY); coordExCtx.lineTo(arrX, midY);
        coordExCtx.stroke();
        coordExCtx.setLineDash([]);
        // Diamond
        coordExCtx.fillStyle = '#f1c40f';
        coordExCtx.beginPath();
        coordExCtx.moveTo(px, midY - 7); coordExCtx.lineTo(px + 6, midY);
        coordExCtx.lineTo(px, midY + 7); coordExCtx.lineTo(px - 6, midY);
        coordExCtx.closePath(); coordExCtx.fill();
        // Label: 'prearm Xm:Ys'
        coordExCtx.fillStyle = '#f1c40f';
        coordExCtx.font = '9px system-ui';
        coordExCtx.textAlign = 'center';
        coordExCtx.textBaseline = 'top';
        coordExCtx.fillText('prearm ' + fmtT(w.t), px, midY + 8);
      });

      // prearm_success star
      jWave.filter(w => w.event === 'prearm_success').forEach(w => {
        const sx = xOf(w.t);
        coordExCtx.fillStyle = '#2ecc71';
        coordExCtx.font = 'bold 15px sans-serif';
        coordExCtx.textAlign = 'center'; coordExCtx.textBaseline = 'middle';
        coordExCtx.fillText('★', sx, midY - 12);
      });

      // prearm_missed / expired (only for junctions that had a prearm_fired)
      jWave.filter(w => (w.event === 'prearm_missed' || w.event === 'prearm_expired')).forEach(w => {
        const mx = xOf(w.t);
        coordExCtx.strokeStyle = '#e74c3c'; coordExCtx.lineWidth = 2;
        coordExCtx.beginPath(); coordExCtx.moveTo(mx-5,midY-5); coordExCtx.lineTo(mx+5,midY+5); coordExCtx.stroke();
        coordExCtx.beginPath(); coordExCtx.moveTo(mx+5,midY-5); coordExCtx.lineTo(mx-5,midY+5); coordExCtx.stroke();
        coordExCtx.fillStyle = '#e74c3c';
        coordExCtx.font = '9px system-ui';
        coordExCtx.textAlign = 'center';
        coordExCtx.textBaseline = 'top';
        coordExCtx.fillText(w.event === 'prearm_missed' ? 'missed' : 'expired', mx, midY + 8);
      });

      // grant marker (blue triangle)
      const _grantEvts = jWave.filter(w => w.event === 'grant');
      (_grantEvts.length > 0 ? [_grantEvts[0]] : []).forEach(w => {
        const gx = xOf(w.t);
        if (hasPrearmChain) {
          coordExCtx.fillStyle = '#3498db';
          coordExCtx.beginPath();
          coordExCtx.moveTo(gx, midY - 7); coordExCtx.lineTo(gx + 6, midY + 4);
          coordExCtx.lineTo(gx - 6, midY + 4); coordExCtx.closePath(); coordExCtx.fill();
        } else {
          coordExCtx.strokeStyle = '#f39c12'; coordExCtx.lineWidth = 2;
          coordExCtx.beginPath(); coordExCtx.arc(gx, midY - 10, 5, 0, Math.PI * 2); coordExCtx.stroke();
          coordExCtx.fillStyle = '#f39c12';
          coordExCtx.font = '9px system-ui';
          coordExCtx.textAlign = 'center'; coordExCtx.textBaseline = 'top';
          coordExCtx.fillText('detected', gx, midY + 8);
        }
      });
    });

    // ── Focus + Unfocused time bars ───────────────────────────────────────
    if (hasFocusBand) {
      const focusY    = H - padB + 14;
      const unfocusY  = H - padB + 32;

      // Focus label
      coordExCtx.fillStyle = '#f1c40f';
      coordExCtx.font = '10px system-ui';
      coordExCtx.textAlign = 'right';
      coordExCtx.textBaseline = 'middle';
      coordExCtx.fillText('focus', padL - 6, focusY);

      // Unfocused label
      coordExCtx.fillStyle = '#7777aa';
      coordExCtx.textBaseline = 'middle';
      coordExCtx.fillText('unfocused', padL - 6, unfocusY);

      // Thin guide lines
      coordExCtx.strokeStyle = 'rgba(241,196,15,0.10)';
      coordExCtx.lineWidth = 1;
      coordExCtx.beginPath(); coordExCtx.moveTo(padL, focusY); coordExCtx.lineTo(W - padR, focusY); coordExCtx.stroke();
      coordExCtx.strokeStyle = 'rgba(119,119,170,0.10)';
      coordExCtx.beginPath(); coordExCtx.moveTo(padL, unfocusY); coordExCtx.lineTo(W - padR, unfocusY); coordExCtx.stroke();

      // Draw focus intervals
      focusRows.forEach(f => {
        const segStart = Math.max(tMin, Number(f.start_t));
        const segEnd = Math.min(tMax, Number(f.end_t));
        if (!(segEnd > segStart)) return;
        const x0 = xOf(segStart), x1 = xOf(segEnd);
        coordExCtx.strokeStyle = '#f1c40f';
        coordExCtx.lineWidth = 4;
        coordExCtx.lineCap = 'round';
        coordExCtx.beginPath(); coordExCtx.moveTo(x0, focusY); coordExCtx.lineTo(x1, focusY); coordExCtx.stroke();
        // Start dot
        coordExCtx.fillStyle = '#f1c40f';
        coordExCtx.beginPath(); coordExCtx.arc(x0, focusY, 3, 0, Math.PI * 2); coordExCtx.fill();
        // End open circle
        coordExCtx.fillStyle = '#0a0a1a';
        coordExCtx.beginPath(); coordExCtx.arc(x1, focusY, 4, 0, Math.PI * 2); coordExCtx.fill();
        coordExCtx.strokeStyle = '#f1c40f'; coordExCtx.lineWidth = 2;
        coordExCtx.beginPath(); coordExCtx.arc(x1, focusY, 4, 0, Math.PI * 2); coordExCtx.stroke();
        // Outcome label
        coordExCtx.fillStyle = '#f1c40f';
        coordExCtx.font = '9px system-ui';
        coordExCtx.textAlign = 'left'; coordExCtx.textBaseline = 'bottom';
        coordExCtx.fillText(String(f.outcome || 'focus off'), Math.min(x1 + 6, W - padR - 42), focusY - 4);
      });

      // Draw UN-focused intervals (gaps between focus segments within [tMin,tMax])
      // Collect sorted focus intervals clipped to plot range
      const fSegs = focusRows
        .map(f => [Math.max(tMin, Number(f.start_t)), Math.min(tMax, Number(f.end_t))])
        .filter(([a,b]) => b > a)
        .sort((a,b) => a[0] - b[0]);
      // Build complement segments
      let cursor = tMin;
      fSegs.forEach(([a, b]) => {
        if (cursor < a) {
          // unfocused gap [cursor, a]
          const ux0 = xOf(cursor), ux1 = xOf(a);
          coordExCtx.strokeStyle = '#555577';
          coordExCtx.lineWidth = 3;
          coordExCtx.lineCap = 'round';
          coordExCtx.beginPath(); coordExCtx.moveTo(ux0, unfocusY); coordExCtx.lineTo(ux1, unfocusY); coordExCtx.stroke();
        }
        cursor = Math.max(cursor, b);
      });
      if (cursor < tMax) {
        const ux0 = xOf(cursor), ux1 = xOf(tMax);
        coordExCtx.strokeStyle = '#555577'; coordExCtx.lineWidth = 3; coordExCtx.lineCap = 'round';
        coordExCtx.beginPath(); coordExCtx.moveTo(ux0, unfocusY); coordExCtx.lineTo(ux1, unfocusY); coordExCtx.stroke();
      }
    }

    // Title
    const nPrearms = wave.filter(w => w.event === 'prearm_fired').length;
    const nSuccess = wave.filter(w => w.event === 'prearm_success').length;
    const nGreen   = stops.filter(s => s.on_green).length;
    coordExCtx.fillStyle = '#bbbbdd';
    coordExCtx.font = 'bold 12px system-ui, sans-serif';
    coordExCtx.textAlign = 'left'; coordExCtx.textBaseline = 'top';
    coordExCtx.fillText(
      `Bus ${journey.vid} — ${stops.length} junctions, ${nGreen}/${stops.length} on green, ` +
      `${nPrearms} prearms issued, ${nSuccess} succeeded`,
      padL, 6);

    // Bus info summary
    if (coordExBusInfo) {
      coordExBusInfo.textContent =
        `${r.label} | cls=${journey.cls} | ` +
        `${nPrearms} prearm(s) issued | ${nSuccess} success | ` +
        `${nGreen}/${stops.length} arrived on green`;
    }
    // Populate reward breakdown table for this bus
    renderCoordRewardTable(ri, vid);
  }

  // Reward breakdown table: per-junction, all candidates
  function renderCoordRewardTable(ri, vid) {
    const wrap   = document.getElementById('coordex-reward-wrap');
    const tbody  = document.getElementById('coordex-reward-tbody');
    const noData = document.getElementById('coordex-reward-no-data');
    if (!wrap || !tbody) return;
    const r = runs[ri];
    const allRows = (r.reward_cycle || []);

    if (!vid || !allRows.length) {
      wrap.style.display = 'none';
      return;
    }
    const vidNum = Number(vid);
    // Get all rows for this bus
    const busRows = allRows.filter(x => Number(x.vid) === vidNum);
    if (!busRows.length) {
      wrap.style.display = '';
      if (noData) { noData.style.display = ''; noData.textContent = `No reward_cycle data for bus ${vid}.`; }
      tbody.innerHTML = '';
      return;
    }
    if (noData) noData.style.display = 'none';
    wrap.style.display = '';

    // Group by junction + time (each detection event = one group)
    const groupMap = {};
    busRows.forEach(x => {
      const key = `${x.jct}_${Math.round(Number(x.t))}`;
      if (!groupMap[key]) groupMap[key] = { jct: x.jct, t: Number(x.t), rows: {} };
      groupMap[key].rows[String(x.action)] = x;
    });
    const groups = Object.values(groupMap).sort((a, b) => a.t - b.t);

    const ACTS = ['NO_ACTION','GE_5','GE_10','GE_15','GR_5','GR_10','GR_15','INS_10','INS_15','INS_20','ER_10','ER_20','ER_30','ER_BP_10','ER_BP_20','ER_BP_30'];
    const ACT_COLORS = {
      'NO_ACTION':'#a0a0c8','GE_5':'#3498db','GE_10':'#2980b9','GE_15':'#1a6090',
      'GR_5':'#a3e635','GR_10':'#84cc16','GR_15':'#65a30d',
      'INS_10':'#2ecc71','INS_15':'#27ae60','INS_20':'#1e8449',
      'ER_10':'#f39c12','ER_20':'#e67e22','ER_30':'#d35400',
      'ER_BP_10':'#c0392b','ER_BP_20':'#a93226','ER_BP_30':'#922b21',
    };

    tbody.innerHTML = '';
    groups.forEach(g => {
      const na = g.rows['NO_ACTION'];
      const naR = na ? Number(na.reward).toFixed(2) : '—';
      const naDelay    = na ? Number(na.no_act_delay_s          || 0).toFixed(1) : '—';
      const naNsdPax  = na ? Number(na.no_strategy_delay_pax_s || 0).toFixed(0) : '—';
      const sigmaIn = na ? Number(na.sigma_in_s || 0).toFixed(0) : '—';
      const eta = na ? Number(na.bus_eta_s || 0).toFixed(1) : '—';

      // Find chosen action
      const chosenRow = Object.values(g.rows).find(x => Number(x.is_chosen) === 1);
      const chosenAct = chosenRow ? String(chosenRow.action) : '—';

      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid #1a1a30';

      function cell(txt, color, bold) {
        const td = document.createElement('td');
        td.style.padding = '3px 6px';
        td.style.textAlign = 'right';
        if (color) td.style.color = color;
        if (bold) td.style.fontWeight = '600';
        td.textContent = txt;
        return td;
      }

      tr.appendChild(Object.assign(document.createElement('td'), {
        textContent: String(g.jct), style: 'padding:3px 6px;text-align:left;color:#8888bb'
      }));
      tr.appendChild(cell(g.t.toFixed(1), '#7070a0'));
      tr.appendChild(cell(eta, '#7070a0'));
      tr.appendChild(cell(sigmaIn + 's', '#9b59b6'));
      {
        const tdNaD = document.createElement('td');
        tdNaD.style.cssText = 'padding:3px 6px;text-align:right';
        const _dColor = Number(naDelay) > 0 ? '#e74c3c' : '#5a5a8a';
        tdNaD.innerHTML = `<span style="color:${_dColor}">${naDelay}s</span>` +
          (naNsdPax !== '—' ? `<br><span style="font-size:9px;color:#9070a0">${naNsdPax}&nbsp;pax·s</span>` : '');
        tr.appendChild(tdNaD);
      }
      // NO_ACTION cell: reward + pax breakdown (bus saved / car cost)
      {
        const tdNA = document.createElement('td');
        tdNA.style.cssText = 'padding:3px 6px;text-align:right';
        const naIsChosen = na && Number(na.is_chosen) === 1;
        if (naIsChosen) {
          tdNA.style.background = 'rgba(255,220,50,0.12)';
          tdNA.style.border = '1px solid rgba(255,220,50,0.4)';
        }
        if (na) {
          const naBps = Number(na.bus_saved_pax_s || 0);
          const naCpc = Number(na.other_inc_pax_s || 0);
          const bpsColor = naBps > 0.5 ? '#4ecdc4' : naBps < -0.5 ? '#e74c3c' : '#555';
          const cpcColor = naCpc > 0.5 ? '#e07070' : '#555';
          const starPfx = naIsChosen ? '<span style="color:#ffd632">★ </span>' : '';
          tdNA.innerHTML = starPfx +
            `<span style="color:#a0a0c8;font-weight:${naIsChosen ? 600 : 400}">${naR}</span>` +
            '<br>' +
            `<span style="font-size:9px;color:${bpsColor}">${naBps >= 0 ? '+' : ''}${Math.round(naBps)}</span>` +
            `<span style="font-size:9px;color:#444">/</span>` +
            `<span style="font-size:9px;color:${cpcColor}">−${Math.round(naCpc)}</span>`;
        } else {
          tdNA.textContent = '—'; tdNA.style.color = '#555';
        }
        tr.appendChild(tdNA);
      }

      // GE/INS/ER reward cells — show reward + bus pax saved + car pax cost
      ACTS.slice(1).forEach(act => {
        const row = g.rows[act];
        const rVal = row ? Number(row.reward) : null;
        const rTxt = rVal !== null ? rVal.toFixed(2) : '—';
        const isChosen = row && Number(row.is_chosen) === 1;
        const color = rVal !== null && rVal > 0.01 ? (ACT_COLORS[act] || '#cccccc') : (rVal !== null && rVal < -0.01 ? '#888' : '#555');

        const td = document.createElement('td');
        td.style.padding = '3px 6px';
        td.style.textAlign = 'right';
        if (isChosen) {
          td.style.background = 'rgba(255,220,50,0.12)';
          td.style.border = '1px solid rgba(255,220,50,0.4)';
        }

        if (row) {
          const bps = Number(row.bus_saved_pax_s || 0);
          const cpc = Number(row.other_inc_pax_s || 0);
          const bpsColor = bps > 0.5 ? '#4ecdc4' : bps < -0.5 ? '#e74c3c' : '#555';
          const cpcColor = cpc > 0.5 ? '#e07070' : '#555';
          const starPfx  = isChosen ? '<span style="color:#ffd632">★ </span>' : '';
          td.innerHTML = starPfx +
            `<span style="color:${color};font-weight:${isChosen ? 600 : 400}">${rTxt}</span>` +
            '<br>' +
            `<span style="font-size:9px;color:${bpsColor}">${bps >= 0 ? '+' : ''}${Math.round(bps)}</span>` +
            `<span style="font-size:9px;color:#444">/</span>` +
            `<span style="font-size:9px;color:${cpcColor}">−${Math.round(cpc)}</span>`;
        } else {
          td.textContent = '—';
          td.style.color = '#555';
        }
        tr.appendChild(td);
      });

      // Chosen action summary
      const tdChosen = document.createElement('td');
      tdChosen.style.cssText = 'padding:3px 6px;text-align:left;font-size:10px';
      if (chosenAct !== '—') {
        const cr = chosenRow ? Number(chosenRow.reward).toFixed(3) : '';
        const bps = chosenRow ? (Number(chosenRow.bus_saved_pax_s || 0)).toFixed(0) + ' pax·s' : '';
        tdChosen.innerHTML = `<span style="color:#ffd632;font-weight:600">${chosenAct}</span>`
                           + ` <span style="color:#9090a8">r=${cr}</span>`
                           + (bps ? ` <span style="color:#5a8a5a">saved=${bps}</span>` : '');
      } else {
        tdChosen.textContent = '—';
        tdChosen.style.color = '#555';
      }
      tr.appendChild(tdChosen);
      tbody.appendChild(tr);
    });
  }

  // Tab setup
  const coordExTabsDiv = document.getElementById('coordex-run-tabs');
  runs.forEach((r, i) => {
    const btn = document.createElement('button');
    btn.className = 'run-tab' + (i === initialRunIdx ? ' active' : '');
    btn.textContent = r.label;
    btn.onclick = () => {
      document.querySelectorAll('#coordex-run-tabs .run-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeCoordExRun = i;
      activeCoordExVid = null;
      _populateCoordExBusSelect(i);
      renderCoordExample(i);
    };
    coordExTabsDiv.appendChild(btn);
  });

  // Bus select listener
  coordExBusSel.addEventListener('change', function() {
    activeCoordExVid = this.value ? parseInt(this.value) : null;
    renderCoordExample(activeCoordExRun, activeCoordExVid);
  });

  // Initial render
  if (runs.length) {
    _populateCoordExBusSelect(initialRunIdx);
    renderCoordExample(initialRunIdx, activeCoordExVid);
  }
}

// ── Bus Position Tracking chart ───────────────────────────────────────────
{
  let activeBusTrackRun = 0;
  const btCanvas = document.getElementById('bustrack-canvas');
  const btCtx = btCanvas ? btCanvas.getContext('2d') : null;

  function renderBusTracking(ri, filterVid, filterJct) {
    if (!btCtx) return;
    const r = runs[ri];
    const data = r.bus_tracking || [];
    const summaryEl = document.getElementById('bustrack-summary');
    if (!data.length) {
      btCtx.clearRect(0, 0, btCanvas.width, btCanvas.height);
      btCtx.font = '13px sans-serif'; btCtx.fillStyle = '#999';
      btCtx.fillText('No bus tracking data for this run.', 20, 40);
      if (summaryEl) summaryEl.textContent = '';
      return;
    }

    // Populate dropdowns on first render
    const busSel = document.getElementById('bustrack-bus-select');
    const jctSel = document.getElementById('bustrack-jct-select');
    const refSel = document.getElementById('bustrack-ref-mode');
    const rangeSel = document.getElementById('bustrack-range-mode');
    const refMode = refSel ? refSel.value : 'nearest';
    const rangeMode = rangeSel ? rangeSel.value : 'relevant';
    const jctPos = DATA.jct_positions || {};
    const corridorJcts = (DATA.junctions || []).map(j => Number(j));

    function buildCorridorDistMap() {
      const out = {};
      let acc = 0;
      for (let i = 0; i < corridorJcts.length; i++) {
        const j = corridorJcts[i];
        if (i > 0) {
          const p0 = jctPos[String(corridorJcts[i - 1])] || null;
          const p1 = jctPos[String(j)] || null;
          if (p0 && p1) {
            const dx = Number(p1.x) - Number(p0.x);
            const dy = Number(p1.y) - Number(p0.y);
            const seg = Math.sqrt(dx * dx + dy * dy);
            if (Number.isFinite(seg) && seg > 0) acc += seg;
            else acc += 1;
          } else {
            acc += 1;
          }
        }
        out[String(j)] = acc;
      }
      return out;
    }
    const corridorDistMap = buildCorridorDistMap();

    function distToSelectedJct(p, jctId) {
      const jp = jctPos[String(jctId)] || null;
      if (!jp) return null;
      const dx = Number(p.x) - Number(jp.x);
      const dy = Number(p.y) - Number(jp.y);
      const d = Math.sqrt(dx * dx + dy * dy);
      return Number.isFinite(d) ? d : null;
    }
    if (!filterVid && !filterJct) {
      const vids = [...new Set(data.filter(d => d.event === 'track').map(d => d.vid))].sort((a,b) => a-b);
      busSel.innerHTML = '<option value="">All buses</option>';
      vids.forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = 'Bus ' + v; busSel.appendChild(o); });
      const jctIds = [...new Set(data.map(d => d.jct).filter(j => j > 0))].sort((a,b) => a-b);
      jctSel.innerHTML = '<option value="">Nearest</option>';
      jctIds.forEach(j => { const o = document.createElement('option'); o.value = j; o.textContent = 'Jct ' + j; jctSel.appendChild(o); });
    }

    // Filter
    let pts = data.filter(d => d.event === 'track');
    let events = data.filter(d => d.event !== 'track');
    if (filterVid) {
      pts = pts.filter(d => d.vid === filterVid);
      events = events.filter(d => d.vid === filterVid);
    }
    const useSelectedRef = (refMode === 'selected' && filterJct && (jctPos[String(filterJct)] != null));
    const useCorridorRef = (refMode === 'corridor');
    if (useSelectedRef) {
      pts = pts.map(p => {
        const dSel = distToSelectedJct(p, filterJct);
        if (dSel === null) return null;
        return {
          ...p,
          dist_plot: dSel,
          in_zone_plot: (p.zone_r > 0 && dSel <= p.zone_r) ? 1 : 0,
        };
      }).filter(Boolean);
      events = events.map(e => {
        const dSel = distToSelectedJct(e, filterJct);
        if (dSel === null) return null;
        return { ...e, dist_plot: dSel };
      }).filter(Boolean);
    } else {
      if (filterJct && !useCorridorRef) {
        pts = pts.filter(d => d.jct === filterJct);
        events = events.filter(d => String(d.jct) === String(filterJct));
      }
      if (useCorridorRef) {
        pts = pts.map(p => {
          const yCorr = corridorDistMap[String(p.jct)];
          if (yCorr == null) return null;
          return { ...p, dist_plot: yCorr, in_zone_plot: p.in_zone };
        }).filter(Boolean);
        events = events.map(e => {
          const yCorr = corridorDistMap[String(e.jct)];
          if (yCorr == null) return null;
          return { ...e, dist_plot: yCorr };
        }).filter(Boolean);
      } else {
        pts = pts.map(p => ({ ...p, dist_plot: p.dist, in_zone_plot: p.in_zone }));
        events = events.map(e => ({ ...e, dist_plot: e.dist }));
      }
    }

    if (rangeMode === 'relevant' && !useCorridorRef) {
      const _keepPt = (p) => {
        const zr = Number(p.zone_r || 0);
        const cap = Math.max(300, zr > 0 ? (2.0 * zr) : 0);
        return Number(p.dist_plot) <= cap;
      };
      const _keepEvt = (e) => {
        const zr = Number(e.zone_r || 0);
        const cap = Math.max(300, zr > 0 ? (2.0 * zr) : 0);
        return Number(e.dist_plot) <= cap;
      };
      const ptsRelevant = pts.filter(_keepPt);
      const eventsRelevant = events.filter(_keepEvt);
      if (ptsRelevant.length) {
        pts = ptsRelevant;
        events = eventsRelevant;
      }
    }

    if (!pts.length) {
      btCtx.clearRect(0, 0, btCanvas.width, btCanvas.height);
      btCtx.font = '13px sans-serif'; btCtx.fillStyle = '#999';
      btCtx.fillText('No data for selection.', 20, 40);
      return;
    }

    // Canvas sizing
    const dpr = window.devicePixelRatio || 1;
    btCanvas.width = btCanvas.clientWidth * dpr;
    btCanvas.height = 400 * dpr;
    btCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const W = btCanvas.clientWidth, H = 400;
    const pad = {l: 60, r: 20, t: 20, b: 35};
    const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;

    // Axes: y-range depends on reference mode
    const tMin = Math.min(...pts.map(d => d.t));
    const tMax = Math.max(...pts.map(d => d.t));
    let dMax;
    if (useCorridorRef && corridorJcts.length > 0) {
      // Use corridor total length (last junction's accumulated distance) as y-max.
      // This ensures junction bands are properly spaced over the full chart height
      // even when coordinate data gives real metric distances (100s of metres).
      const corridorTop = corridorDistMap[String(corridorJcts[corridorJcts.length - 1])] || 0;
      dMax = Math.max(corridorTop * 1.05, 1);
    } else {
      dMax = Math.max(...pts.map(d => d.dist_plot), 300);
    }

    function tx(t) { return pad.l + (t - tMin) / Math.max(tMax - tMin, 1) * pw; }
    function ty(dist) { return pad.t + ph - (dist / Math.max(dMax, 1)) * ph; }

    btCtx.clearRect(0, 0, W, H);
    btCtx.fillStyle = '#fafafa'; btCtx.fillRect(pad.l, pad.t, pw, ph);
    btCtx.strokeStyle = '#ddd'; btCtx.lineWidth = 1;
    btCtx.strokeRect(pad.l, pad.t, pw, ph);

    // Grid + axis labels
    btCtx.font = '10px sans-serif'; btCtx.fillStyle = '#999'; btCtx.textAlign = 'right';
    if (useCorridorRef) {
      corridorJcts.forEach(j => {
        const yv = corridorDistMap[String(j)];
        if (yv == null) return;
        const y = ty(yv);
        btCtx.beginPath(); btCtx.moveTo(pad.l, y); btCtx.lineTo(pad.l + pw, y);
        btCtx.strokeStyle = '#eee'; btCtx.stroke();
        btCtx.fillText('jct ' + j, pad.l - 4, y + 3);
      });
    } else {
      for (let d = 0; d <= dMax; d += Math.max(50, Math.round(dMax / 6 / 50) * 50)) {
        const y = ty(d);
        btCtx.beginPath(); btCtx.moveTo(pad.l, y); btCtx.lineTo(pad.l + pw, y);
        btCtx.strokeStyle = '#eee'; btCtx.stroke();
        btCtx.fillText(d + 'm', pad.l - 4, y + 3);
      }
    }
    btCtx.textAlign = 'center';
    const tStep = Math.max(60, Math.round((tMax - tMin) / 8 / 60) * 60);
    for (let t = Math.ceil(tMin / tStep) * tStep; t <= tMax; t += tStep) {
      const x = tx(t);
      btCtx.beginPath(); btCtx.moveTo(x, pad.t); btCtx.lineTo(x, pad.t + ph);
      btCtx.strokeStyle = '#eee'; btCtx.stroke();
      btCtx.fillText(Math.round(t) + 's', x, H - pad.b + 14);
    }
    btCtx.fillStyle = '#666'; btCtx.font = '11px sans-serif';
    btCtx.textAlign = 'center';
    btCtx.fillText('Simulation time (s)', pad.l + pw / 2, H - 2);
    btCtx.save(); btCtx.translate(12, pad.t + ph / 2); btCtx.rotate(-Math.PI/2);
    btCtx.fillText(
      useCorridorRef
        ? 'Corridor position (nearest junction order)'
        : (useSelectedRef ? `Distance to jct ${filterJct} (m)` : 'Distance to nearest junction (m)'),
      0,
      0
    );
    btCtx.restore();

    // Draw zone radius line if filtering by junction
    if (filterJct && pts.length) {
      const zr = pts[0].zone_r;
      if (zr > 0 && zr <= dMax) {
        btCtx.setLineDash([5, 5]); btCtx.strokeStyle = '#ccc'; btCtx.lineWidth = 1.5;
        btCtx.beginPath(); btCtx.moveTo(pad.l, ty(zr)); btCtx.lineTo(pad.l + pw, ty(zr));
        btCtx.stroke(); btCtx.setLineDash([]);
        btCtx.fillStyle = '#aaa'; btCtx.font = '10px sans-serif'; btCtx.textAlign = 'left';
        btCtx.fillText('zone radius ' + zr + 'm', pad.l + 4, ty(zr) - 4);
      }
    }

    // Group by vehicle
    const byVid = {};
    pts.forEach(d => { (byVid[d.vid] = byVid[d.vid] || []).push(d); });
    const colors = ['#3498db','#e74c3c','#2ecc71','#9b59b6','#f39c12','#1abc9c','#e67e22','#34495e'];
    let ci = 0;
    for (const [vid, vPts] of Object.entries(byVid)) {
      const col = colors[ci++ % colors.length];
      vPts.sort((a,b) => a.t - b.t);
      btCtx.strokeStyle = col; btCtx.lineWidth = 1.5;
      btCtx.beginPath();
      vPts.forEach((p, i) => {
        const x = tx(p.t), y = ty(p.dist_plot);
        if (i === 0) btCtx.moveTo(x, y); else btCtx.lineTo(x, y);
      });
      btCtx.stroke();
      // Dots coloured by in_zone
      vPts.forEach(p => {
        btCtx.fillStyle = p.in_zone_plot ? '#2ecc71' : '#e74c3c';
        btCtx.beginPath(); btCtx.arc(tx(p.t), ty(p.dist_plot), 2.5, 0, Math.PI * 2); btCtx.fill();
      });
    }

    // Zone enter/exit markers
    events.forEach(e => {
      if (filterJct && String(e.jct) !== String(filterJct)) return;
      const x = tx(e.t), y = ty(e.dist_plot);
      btCtx.fillStyle = e.event === 'zone_enter' ? '#f39c12' : '#9b59b6';
      btCtx.beginPath();
      if (e.event === 'zone_enter') {
        btCtx.moveTo(x, y - 5); btCtx.lineTo(x - 4, y + 3); btCtx.lineTo(x + 4, y + 3);
      } else {
        btCtx.moveTo(x, y + 5); btCtx.lineTo(x - 4, y - 3); btCtx.lineTo(x + 4, y - 3);
      }
      btCtx.fill();
    });

    // Nearest-junction change markers (helps explain why distance traces shift)
    if (!useCorridorRef) {
      const jchg = events.filter(e => e.event === 'nearest_jct_change');
      btCtx.strokeStyle = 'rgba(100,120,160,0.35)';
      btCtx.fillStyle = 'rgba(120,140,180,0.9)';
      btCtx.font = '10px sans-serif';
      btCtx.textAlign = 'left';
      jchg.forEach((e, i) => {
        const x = tx(e.t);
        btCtx.beginPath();
        btCtx.moveTo(x, pad.t);
        btCtx.lineTo(x, pad.t + ph);
        btCtx.stroke();
        if (i % 2 === 0) {
          btCtx.fillText(`near jct ${e.jct}`, Math.min(x + 2, pad.l + pw - 72), pad.t + 12 + (i % 4) * 11);
        }
      });
    }

    // Summary
    if (summaryEl) {
      const nBuses = Object.keys(byVid).length;
      const nEnter = events.filter(e => e.event === 'zone_enter').length;
      const nExit = events.filter(e => e.event === 'zone_exit').length;
      const nInZone = pts.filter(p => p.in_zone_plot).length;
      const scopeTxt = useCorridorRef
        ? 'full corridor'
        : (useSelectedRef
        ? `selected junction ${filterJct}`
        : (filterJct ? `nearest=junction ${filterJct}` : 'nearest junction'));
      const rangeTxt = useCorridorRef
        ? 'corridor mode'
        : ((rangeMode === 'relevant') ? 'relevant range' : 'all ranges');
      summaryEl.textContent = `${nBuses} bus(es) tracked · ${pts.length} position samples · ${scopeTxt} · ${rangeTxt} · ${nInZone} in-zone · ${nEnter} zone entries · ${nExit} zone exits`;
    }
  }

  // Tabs
  const btTabsDiv = document.getElementById('bustrack-run-tabs');
  runs.forEach((r, i) => {
    const btn = document.createElement('button');
    btn.className = 'run-tab' + (i === initialRunIdx ? ' active' : '');
    btn.textContent = r.label;
    btn.onclick = () => {
      document.querySelectorAll('#bustrack-run-tabs .run-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeBusTrackRun = i;
      renderBusTracking(i);
    };
    btTabsDiv.appendChild(btn);
  });
  document.getElementById('bustrack-bus-select').addEventListener('change', e => {
    renderBusTracking(activeBusTrackRun, e.target.value ? parseInt(e.target.value) : null,
                      document.getElementById('bustrack-jct-select').value || null);
  });
  document.getElementById('bustrack-jct-select').addEventListener('change', e => {
    const bv = document.getElementById('bustrack-bus-select').value;
    renderBusTracking(activeBusTrackRun, bv ? parseInt(bv) : null, e.target.value || null);
  });
  document.getElementById('bustrack-ref-mode').addEventListener('change', () => {
    const bv = document.getElementById('bustrack-bus-select').value;
    const jv = document.getElementById('bustrack-jct-select').value;
    renderBusTracking(activeBusTrackRun, bv ? parseInt(bv) : null, jv || null);
  });
  document.getElementById('bustrack-range-mode').addEventListener('change', () => {
    const bv = document.getElementById('bustrack-bus-select').value;
    const jv = document.getElementById('bustrack-jct-select').value;
    renderBusTracking(activeBusTrackRun, bv ? parseInt(bv) : null, jv || null);
  });
  if (runs.length) renderBusTracking(initialRunIdx);
}

// ── Queue Lengths Over Time ────────────────────────────────────────────────
{
  let queueChart = null;
  const queueColors = [
    '#29b6f6','#00e676','#ffb300','#ab47bc','#ff5252','#26c6da','#d4e157','#ff7043'
  ];

  function renderQueueChart() {
    const runSel = document.getElementById('queue-run-sel');
    const jctSel = document.getElementById('queue-jct-sel');
    const showBuses = document.getElementById('queue-show-buses').checked;
    const showDelay = (document.getElementById('queue-show-delay') || {}).checked;
    if (!runSel || !jctSel) return;
    const ri = parseInt(runSel.value || '0');
    const r  = runs[ri];
    const snaps = r.queue_snapshots || [];

    if (queueChart) { queueChart.destroy(); queueChart = null; }
    const ctx = document.getElementById('queue-canvas');
    if (!ctx) return;

    if (!snaps.length) {
      const c2d = ctx.getContext('2d');
      c2d.clearRect(0, 0, ctx.width, ctx.height);
      c2d.fillStyle = '#7070a0';
      c2d.font = '14px Segoe UI';
      c2d.fillText('No queue snapshot data for this run.', 20, 40);
      return;
    }

    // Filter by junction
    const filterJct = jctSel.value ? parseInt(jctSel.value) : null;
    const filteredSnaps = filterJct ? snaps.filter(s => s.jct === filterJct) : snaps;

    // Unique junctions in filtered data
    const jctSet = [...new Set(filteredSnaps.map(s => s.jct))].sort((a,b) => a-b);

    const timeSet = [...new Set(filteredSnaps.map(s => s.t))].sort((a,b) => a-b);

    const datasets = [];
    jctSet.forEach((jid, ci) => {
      const pts = filteredSnaps.filter(s => s.jct === jid)
                               .sort((a,b) => a.t - b.t);
      const col = queueColors[ci % queueColors.length];
      datasets.push({
        label: `jct ${jid} — queue`,
        data: pts.map(p => ({ x: p.t, y: p.queue_total })),
        borderColor: col,
        backgroundColor: col + '22',
        borderWidth: 2,
        pointRadius: 2,
        tension: 0.2,
        yAxisID: 'y',
      });
      if (showBuses) {
        datasets.push({
          label: `jct ${jid} — buses in zone`,
          data: pts.map(p => ({ x: p.t, y: p.buses_in_zone })),
          borderColor: col,
          backgroundColor: 'transparent',
          borderWidth: 1.5,
          borderDash: [4, 3],
          pointRadius: 1.5,
          tension: 0.2,
          yAxisID: 'y2',
        });
      }
      if (showDelay) {
        // Show cumulative pax-seconds delay ÷ 1000 so it fits on the same axis as buses-in-zone
        datasets.push({
          label: `jct ${jid} — delay (÷1000 pax-s)`,
          data: pts.map(p => ({ x: p.t, y: (p.delay_total_s || 0) / 1000 })),
          borderColor: col,
          backgroundColor: 'transparent',
          borderWidth: 2,
          borderDash: [2, 2],
          pointRadius: 0,
          tension: 0.2,
          yAxisID: 'y2',
        });
      }
    });

    // Corridor-wide bus count (all PT buses on the network at each snapshot)
    if (showBuses) {
      const corridorPts = snaps.filter(s => (s.corridor_bus_count || 0) > 0)
                               .filter((s, i, arr) => i === 0 || s.t !== arr[i-1].t)  // dedupe by time
                               .sort((a,b) => a.t - b.t);
      if (corridorPts.length) {
        datasets.push({
          label: 'Corridor total buses (all PT)',
          data: corridorPts.map(p => ({ x: p.t, y: p.corridor_bus_count })),
          borderColor: '#ffffff',
          backgroundColor: 'transparent',
          borderWidth: 2,
          borderDash: [8, 4],
          pointRadius: 0,
          tension: 0.2,
          yAxisID: 'y2',
        });
      }
    }

    // Background plugin: colour bands by tsp_state
    const tspBands = [];
    const stateSnaps = filterJct ? filteredSnaps : snaps;
    const bandByState = {};
    stateSnaps.forEach(s => {
      const st = s.tsp_state || 'NORMAL';
      bandByState[s.t] = st;
    });
    const sortedTimes = Object.keys(bandByState).map(Number).sort((a,b)=>a-b);
    let bandStart = null, bandState = null;
    sortedTimes.forEach(t => {
      const st = bandByState[t];
      if (st !== 'NORMAL' && st !== bandState) {
        if (bandState && bandStart !== null) tspBands.push({ t0: bandStart, t1: t, state: bandState });
        bandStart = t;
        bandState = st;
      } else if (st === 'NORMAL' && bandState) {
        tspBands.push({ t0: bandStart, t1: t, state: bandState });
        bandStart = null; bandState = null;
      }
    });
    if (bandState && bandStart !== null) {
      const lastT = sortedTimes[sortedTimes.length-1];
      tspBands.push({ t0: bandStart, t1: lastT, state: bandState });
    }

    const bandPlugin = {
      id: 'tspBands',
      beforeDraw(chart) {
        const { ctx: c, chartArea, scales } = chart;
        if (!chartArea) return;
        tspBands.forEach(b => {
          const x0 = scales.x.getPixelForValue(b.t0);
          const x1 = scales.x.getPixelForValue(b.t1);
          c.save();
          c.fillStyle = b.state.includes('GE') ? 'rgba(41,182,246,0.08)' : 'rgba(171,71,188,0.08)';
          c.fillRect(x0, chartArea.top, x1-x0, chartArea.bottom - chartArea.top);
          c.restore();
        });
      }
    };

    queueChart = new Chart(ctx.getContext('2d'), {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true,
        animation: false,
        parsing: false,
        plugins: {
          legend: { labels: { color:'#9090cc', font:{size:10}, filter: item => !item.text.includes('buses') || showBuses } },
          tooltip: {
            backgroundColor:'#0a0a22', titleColor:'#ccccee', bodyColor:'#9090cc',
            borderColor:'#2a2a50', borderWidth:1,
            callbacks: {
              title: items => `t=${items[0].raw.x}s`,
              label: item => `${item.dataset.label}: ${item.raw.y}`,
            }
          },
        },
        scales: {
          x: { type:'linear', position:'bottom', ticks:{color:'#9090cc',maxTicksLimit:12}, grid:{color:'#1e1e38'}, title:{display:true,text:'Simulation time (s)',color:'#7070a0'} },
          y: { ticks:{color:'#9090cc'}, grid:{color:'#1e1e38'}, title:{display:true,text:'Queue (veh)',color:'#7070a0'}, min:0 },
          y2: { position:'right', ticks:{color:'#9090cc'}, grid:{display:false}, title:{display:(showBuses||showDelay),text: showDelay ? 'Buses in zone / Delay (÷1000 pax-s)' : 'Buses in zone',color:'#7070a0'}, min:0, display:(showBuses||showDelay) },
        },
      },
      plugins: [bandPlugin],
    });
  }

  // Populate run selector
  const qRunSel = document.getElementById('queue-run-sel');
  const qJctSel = document.getElementById('queue-jct-sel');
  if (qRunSel) {
    runs.forEach((r,i) => {
      const opt = document.createElement('option');
      opt.value = i;
      opt.textContent = r.label;
      qRunSel.appendChild(opt);
    });
    qRunSel.addEventListener('change', () => { rebuildQueueJctSel(); renderQueueChart(); });
    document.getElementById('queue-show-buses').addEventListener('change', renderQueueChart);
    const _qDelayEl = document.getElementById('queue-show-delay');
    if (_qDelayEl) _qDelayEl.addEventListener('change', renderQueueChart);

    function rebuildQueueJctSel() {
      if (!qJctSel) return;
      const ri = parseInt(qRunSel.value || '0');
      const snaps = (runs[ri] || {}).queue_snapshots || [];
      const jctIds = [...new Set(snaps.map(s => s.jct))].sort((a,b)=>a-b);
      qJctSel.innerHTML = '<option value="">All</option>';
      jctIds.forEach(j => {
        const opt = document.createElement('option');
        opt.value = j;
        opt.textContent = `jct ${j}`;
        qJctSel.appendChild(opt);
      });
    }
    qJctSel.addEventListener('change', renderQueueChart);

    rebuildQueueJctSel();
    renderQueueChart();
  }
}

// ── Queue per Entry-Point Approach chart ──────────────────────────────────
{
  const EP_COLORS = ['#5599ff','#ff7755','#55cc88','#ffcc44','#cc55ff','#44ccff','#ff55aa','#88ff55','#ffaa33','#33aaff'];
  let _epCharts = [];

  function renderQueueEntryPoints(ri) {
    const r = runs[ri];
    const rows = (r.queue_entry_snapshots || []);
    const noData = document.getElementById('queue-entry-no-data');
    const container = document.getElementById('queue-entry-container');
    if (!container) return;

    // Destroy existing charts
    _epCharts.forEach(c => { try { c.destroy(); } catch(e){} });
    _epCharts = [];
    container.innerHTML = '';

    if (!rows.length) {
      if (noData) noData.style.display = '';
      return;
    }
    if (noData) noData.style.display = 'none';

    // Group by junction
    const jctSet = new Set();
    rows.forEach(r => jctSet.add(r.jct));
    const jcts = Array.from(jctSet).sort((a, b) => a - b);

    // Collect all side-section keys
    const allKeys = new Set();
    rows.forEach(r => Object.keys(r.sides || {}).forEach(k => allKeys.add(k)));
    const sideKeys = Array.from(allKeys).sort();

    jcts.forEach(function(jct) {
      const jrows = rows.filter(rr => rr.jct === jct).sort((a, b) => a.t - b.t);
      const datasets = [];
      const mainDir = (jrows[0] && jrows[0].main_dir) ? jrows[0].main_dir : 'main';
      // Main (bus) approach
      datasets.push({
        label: mainDir || 'main',
        data: jrows.map(rr => ({ x: rr.t, y: rr.main_veh })),
        borderColor: '#ffffff', backgroundColor: 'transparent',
        tension: 0.3, pointRadius: 0, borderWidth: 2
      });
      // Side approaches — already aggregated by direction bucket (NB/EB/SB/WB)
      sideKeys.forEach(function(k, ki) {
        datasets.push({
          label: k,
          data: jrows.map(rr => ({ x: rr.t, y: (rr.sides && rr.sides[k] != null) ? rr.sides[k] : 0 })),
          borderColor: EP_COLORS[ki % EP_COLORS.length],
          backgroundColor: 'transparent',
          tension: 0.3, pointRadius: 0, borderWidth: 1.5
        });
      });
      const cvs = document.createElement('canvas');
      cvs.style.cssText = 'width:100%;margin-bottom:14px';
      cvs.height = 180;
      container.appendChild(cvs);
      const ch = new Chart(cvs, {
        type: 'line',
        data: { datasets: datasets },
        options: {
          parsing: false, animation: false,
          responsive: true,
          plugins: {
            title: { display: true, color: '#9090cc', text: 'Queue per approach — junction ' + jct },
            legend: { labels: { color: '#9090cc', boxWidth: 12, font: { size: 10 } } },
            tooltip: { backgroundColor:'#0a0a22', titleColor:'#ccccee', bodyColor:'#9090cc', borderColor:'#2a2a50', borderWidth:1 }
          },
          scales: {
            x: { type: 'linear', ticks: { color: '#9090cc', maxTicksLimit: 10 },
                 grid: { color: '#1e1e38' },
                 title: { display: true, text: 'Sim time (s)', color: '#7070a0' } },
            y: { ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' }, min: 0,
                 title: { display: true, text: 'Queue (veh)', color: '#7070a0' } }
          }
        }
      });
      _epCharts.push(ch);
    });
  }

  buildRunTabs('queue-entry-run-tabs', (i) => renderQueueEntryPoints(i));
  if (runs.length) renderQueueEntryPoints(initialRunIdx);
}

// ── Global Bus Focus Priority table ───────────────────────────────────────
{
  let activeFocusRun = -1;
  function renderFocusTable(ri) {
    activeFocusRun = ri;
    const r = runs[ri];
    const fh = r.focus_history || [];
    const noData = document.getElementById('focus-no-data');
    const tbl = document.getElementById('focus-table');
    const summ = document.getElementById('focus-summary');
    if (!fh.length) {
      noData.textContent = 'No focus history data available for this run (loaded events: 0).';
      noData.style.display = '';
      tbl.style.display = 'none';
      summ.textContent = '';
      return;
    }
    noData.style.display = 'none';
    tbl.style.display = '';
    const thead = tbl.querySelector('thead');
    const tbody = tbl.querySelector('tbody');
    thead.innerHTML = '<tr><th>Start (s)</th><th>End (s)</th><th>Bus</th><th>Junction</th><th>Outcome</th><th>Held (s)</th></tr>';
    tbody.innerHTML = fh.map(f => {
      const cls = f.outcome === 'timeout' ? 'style="color:#e74c3c"' : (f.outcome.includes('done') || f.outcome.includes('completed') ? 'style="color:#2ecc71"' : '');
      return `<tr><td>${f.start_t.toFixed(1)}</td><td>${f.end_t.toFixed(1)}</td><td>${f.veh_id}</td><td>${f.jct_id}</td><td ${cls}>${f.outcome}</td><td>${f.held_s.toFixed(1)}</td></tr>`;
    }).join('');
    const nTimeout = fh.filter(f => f.outcome === 'timeout').length;
    const avgHeld = (fh.reduce((s, f) => s + f.held_s, 0) / fh.length).toFixed(1);
    summ.textContent = `${fh.length} focus events | avg held ${avgHeld}s | ${nTimeout} timeouts`;
  }
  buildRunTabs('focus-run-tabs', (i) => renderFocusTable(i));
  if (runs.length) renderFocusTable(initialRunIdx);
}

// ── Per-Bus Corridor KPI Comparison ──────────────────────────────────────────
{
  let _buscompChart = null;

  function renderBusCompChart(ri) {
    const r = runs[ri];
    const noDataEl = document.getElementById('buscomp-no-data');
    const summaryEl = document.getElementById('buscomp-summary');
    const ctx = document.getElementById('buscomp-canvas');
    if (_buscompChart) { _buscompChart.destroy(); _buscompChart = null; }

    const journeys = (r.bus_journeys || []).filter(j => j.n_jcts >= 2);
    const fh = r.focus_history || [];
    const phaseSamples = r.phase_samples || [];

    // Build focus_history junction count per bus: vid → Set of jct_ids
    // This is the authoritative grant count — sourced from ACTUAL GE/INS events
    // written by _acquire_focus(), not from wave-event CSV which can be spammed.
    const fhJctsByVid = {};
    fh.forEach(f => {
      if (f.veh_id > 0 && f.jct_id > 0) {
        if (!fhJctsByVid[f.veh_id]) fhJctsByVid[f.veh_id] = new Set();
        fhJctsByVid[f.veh_id].add(f.jct_id);
      }
    });

    // Fallback grant source: explicit local action rows in phase samples.
    // This covers runs where focus history is sparse or omitted.
    const actionJctsByVid = {};
    phaseSamples.forEach(p => {
      const vid = Number(p.vid || 0);
      const jid = Number(p.jct || 0);
      const tier = String(p.tier || '');
      const status = String(p.prearm_status || '');
      if (vid <= 0 || jid <= 0) return;
      if ((tier === 'harmony-ge-local' || tier === 'harmony-ins-local') && status === 'action') {
        if (!actionJctsByVid[vid]) actionJctsByVid[vid] = new Set();
        actionJctsByVid[vid].add(jid);
      }
    });

    const mergedGrantJctsByVid = {};
    const allGrantVidKeys = new Set([
      ...Object.keys(fhJctsByVid),
      ...Object.keys(actionJctsByVid),
    ]);
    allGrantVidKeys.forEach(k => {
      const vid = Number(k);
      const merged = new Set();
      (fhJctsByVid[vid] || new Set()).forEach(v => merged.add(v));
      (actionJctsByVid[vid] || new Set()).forEach(v => merged.add(v));
      mergedGrantJctsByVid[vid] = merged;
    });

    // grantedBusSet: any bus seen in focus_history (got at least one GE or INS)
    const grantedBusSet = new Set(Object.keys(mergedGrantJctsByVid).map(Number));
    // Also add buses whose journey wave events show an actual grant (COORD only)
    journeys.forEach(j => {
      const waves = j.wave || [];
      if (waves.some(w => w.event === 'grant')) {
        grantedBusSet.add(j.vid);
      }
    });

    if (!journeys.length) {
      if (noDataEl) noDataEl.style.display = '';
      if (ctx) ctx.style.display = 'none';
      if (summaryEl) summaryEl.textContent = '';
      return;
    }
    if (noDataEl) noDataEl.style.display = 'none';
    if (ctx) ctx.style.display = '';

    const showDelay = document.getElementById('buscomp-show-delay')?.checked;
    const showTT    = document.getElementById('buscomp-show-tt')?.checked;
    const showCount = document.getElementById('buscomp-show-count')?.checked;

    const grantedJourneys = journeys.filter(j => grantedBusSet.has(j.vid));
    const normalJourneys  = journeys.filter(j => !grantedBusSet.has(j.vid));

    function aggJourneys(list) {
      if (!list.length) return { delay_avg: 0, tt_avg: 0, priority_avg: 0 };
      let totalDelay = 0, totalTT = 0, totalPriority = 0;
      list.forEach(j => {
        const stops = j.stops || [];
        if (stops.length < 2) return;
        const tt = (stops[stops.length-1].t || 0) - (stops[0].t || 0);
        totalTT += Math.max(0, tt);
        // Priority grants: count unique junctions from focus_history for this bus.
        // Using fhJctsByVid avoids wave-event spam (prearm_success fired per step)
        // and works for both INDEP (no wave CSV) and COORD runs.
        const fhJcts = mergedGrantJctsByVid[j.vid];
        totalPriority += fhJcts ? fhJcts.size : 0;
        // Delay proxy: red arrivals × 30 s.  This is a rough lower-bound estimate —
        // actual red-phase wait depends on cycle timing, not a fixed 30 s.
        // Do NOT compare this per-bus figure to junction-level pax-hour totals.
        const nRed = stops.filter(s => !s.on_green).length;
        totalDelay += nRed * 30;
      });
      const n = list.length;
      return { delay_avg: totalDelay / n, tt_avg: totalTT / n, priority_avg: totalPriority / n };
    }

    const aggGranted = aggJourneys(grantedJourneys);
    const aggNormal  = aggJourneys(normalJourneys);

    // Same-bus baseline context for this selected run.
    // This avoids reading granted-vs-never-granted as a causal A/B split.
    let matchedBusCount = 0;
    let matchedTtDeltaS = null;
    let matchedDelayDeltaS = null;
    const noTspRun = runs.find(rr => (rr.strategy || '').toUpperCase() === 'NORMAL'
      || (rr.exp_name || '').toUpperCase() === 'NO_TSP');
    if (noTspRun && r !== noTspRun) {
      const noTspByVid = {};
      (noTspRun.bus_journeys || []).forEach(j => { noTspByVid[j.vid] = j; });
      let sumTtDelta = 0;
      let sumDelayDelta = 0;
      grantedJourneys.forEach(j => {
        const b = noTspByVid[j.vid];
        if (!b) return;
        const s = j.stops || [];
        const sb = b.stops || [];
        if (s.length < 2 || sb.length < 2) return;
        const tt = (s[s.length - 1].t || 0) - (s[0].t || 0);
        const ttBase = (sb[sb.length - 1].t || 0) - (sb[0].t || 0);
        const delay = s.filter(x => !x.on_green).length * 30;
        const delayBase = sb.filter(x => !x.on_green).length * 30;
        sumTtDelta += (tt - ttBase);
        sumDelayDelta += (delay - delayBase);
        matchedBusCount += 1;
      });
      if (matchedBusCount > 0) {
        matchedTtDeltaS = sumTtDelta / matchedBusCount;
        matchedDelayDeltaS = sumDelayDelta / matchedBusCount;
      }
    }

    if (summaryEl) {
      let txt =
        `Granted hard-case cohort: avg TT ${aggGranted.tt_avg.toFixed(1)}s, avg delay proxy ${aggGranted.delay_avg.toFixed(1)}s; ` +
        `Never-priority cohort: avg TT ${aggNormal.tt_avg.toFixed(1)}s, avg delay proxy ${aggNormal.delay_avg.toFixed(1)}s.`;
      txt += ' This split is not causal because granted buses are selected hard cases.';
      if (matchedBusCount > 0 && matchedTtDeltaS !== null && matchedDelayDeltaS !== null) {
        const ttDir = matchedTtDeltaS <= 0 ? 'better' : 'worse';
        const dDir = matchedDelayDeltaS <= 0 ? 'better' : 'worse';
        txt += ` Same-bus vs No-TSP (n=${matchedBusCount}): TT ${Math.abs(matchedTtDeltaS).toFixed(1)}s ${ttDir}, delay proxy ${Math.abs(matchedDelayDeltaS).toFixed(1)}s ${dDir}.`;
      }
      summaryEl.textContent = txt;
    }

    const labels = [];
    const grantedData = [];
    const normalData  = [];
    if (showDelay) {
      labels.push('Avg corridor delay (×30s/red)');
      grantedData.push(aggGranted.delay_avg);
      normalData.push(aggNormal.delay_avg);
    }
    if (showTT) {
      labels.push('Avg corridor travel time (s)');
      grantedData.push(aggGranted.tt_avg);
      normalData.push(aggNormal.tt_avg);
    }
    if (showCount) {
      labels.push('Avg junctions granted per bus');
      grantedData.push(aggGranted.priority_avg);
      normalData.push(aggNormal.priority_avg);
    }

    // Per-junction priority count breakdown (how many buses got a grant at each jct)
    const jctGrantCount = {};
    const jctNormalCount = {};
    jcts.forEach(j => { jctGrantCount[j] = 0; jctNormalCount[j] = 0; });
    if (showCount) {
      journeys.forEach(j => {
        const isGranted = grantedBusSet.has(j.vid);
        const waves = j.wave || [];
        const fhJcts = mergedGrantJctsByVid[j.vid] || new Set();
        (j.stops || []).forEach(s => {
          const jid = String(s.jct);
          if (isGranted) jctGrantCount[jid] = (jctGrantCount[jid]||0) + (fhJcts.has(Number(jid)) ? 1 : 0);
          else           jctNormalCount[jid] = (jctNormalCount[jid]||0) + (s.on_green ? 1 : 0);
        });
      });
    }

    const datasets = [
      {
        label: `Priority-granted hard cases (n=${grantedJourneys.length})`,
        data: grantedData,
        backgroundColor: 'rgba(41,182,246,0.7)',
        borderColor: '#29b6f6',
        borderWidth: 1,
      },
      {
        label: `Never-priority buses (n=${normalJourneys.length})`,
        data: normalData,
        backgroundColor: 'rgba(255,179,0,0.7)',
        borderColor: '#ffb300',
        borderWidth: 1,
      },
    ];

    _buscompChart = new Chart(ctx.getContext('2d'), {
      type: 'bar',
      data: { labels, datasets },
      options: {
        responsive: true,
        animation: false,
        plugins: {
          legend: { labels: { color: '#9090cc', font: { size: 10 } } },
          tooltip: {
            backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc',
            borderColor: '#2a2a50', borderWidth: 1,
          },
          title: {
            display: true,
            text: `${r.label} — ${grantedJourneys.length} priority buses, ${normalJourneys.length} normal buses`,
            color: '#7070a0', font: { size: 11 },
          },
        },
        scales: {
          x: { ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' } },
          y: { ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' }, min: 0 },
        },
      },
    });
  }

  buildRunTabs('buscomp-run-tabs', (i) => renderBusCompChart(i));
  ['buscomp-show-delay','buscomp-show-tt','buscomp-show-count'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', () => {
      const ri = runs.findIndex((r,i) => document.querySelector(`#buscomp-run-tabs .run-tab.active`)?.textContent === r.label);
      renderBusCompChart(ri >= 0 ? ri : initialRunIdx);
    });
  });
  if (runs.length) renderBusCompChart(initialRunIdx);
}

// ── Same-Bus Cross-Experiment Comparison ─────────────────────────────────
{
  // Identify the three run roles:
  //   noTspRun  — baseline (strategy=NORMAL / exp_name=NO_TSP)
  //   coordRun  — Phase-Based Coordinated (coordinated===true && not NORMAL)
  //   indepRun  — Phase-Based Uncoordinated (coordinated===false && not NORMAL)
  const noTspRun  = runs.find(r => (r.strategy || '').toUpperCase() === 'NORMAL'
                                || (r.exp_name  || '').toUpperCase() === 'NO_TSP');
  const _isRewardRun = (r) => {
    const s = `${(r && r.strategy) || ''} ${(r && r.exp_name) || ''}`.toUpperCase();
    return s.includes('REWARD_TSP') || s.includes('DRL_DENSITY');
  };
  const rewardRun = runs.find(r => _isRewardRun(r) && r !== noTspRun);
  const coordRun  = runs.find(r => r.coordinated === true && r !== noTspRun && r !== rewardRun) || rewardRun;
  const indepRun  = runs.find(r => r.coordinated === false && r !== noTspRun && r !== rewardRun);
  const noDataEl  = document.getElementById('xcomp-no-data');
  const ctx       = document.getElementById('xcomp-canvas');

  if (!noTspRun || !coordRun) {
    if (noDataEl) noDataEl.textContent = 'Requires a No-TSP baseline and a Coordinated run.';
  } else {
    // Build veh_id → journey maps keyed by run
    function _journeyMap(run) {
      const m = {};
      (run ? run.bus_journeys || [] : []).forEach(j => { m[j.vid] = j; });
      return m;
    }
    const noTspJMap  = _journeyMap(noTspRun);
    const coordJMap  = _journeyMap(coordRun);
    const indepJMap  = _journeyMap(indepRun);
    const rewardJMap = _journeyMap(rewardRun);

    // Buses granted GE or Phase Insertion in the COORDINATED run.
    // _acquire_focus() is called exactly when GE or INS fires, so the
    // focus_history contains only buses that received one of these actions.
    const coordFH = coordRun.focus_history || [];
    const grantedVids = new Set(coordFH.map(f => f.veh_id).filter(v => v > 0));
    // Also include buses whose journey wave-events show 'grant'/'prearm_success'
    (coordRun.bus_journeys || []).forEach(j => {
      if ((j.wave || []).some(w => w.event === 'grant' || w.event === 'prearm_success')) {
        grantedVids.add(j.vid);
      }
    });

    function _actionRows(run) {
      return ((run && run.objective_trace) || []).filter(r =>
        (r.mode === 'GE' || r.mode === 'INS') && r.decision === 'ACTION');
    }

    function _bucketKey(r) {
      const tBucket = Math.round((Number(r.t) || 0) / 30) * 30;
      return `${r.jct}|${tBucket}`;
    }

    function _delayValue(r) {
      if (!r) return null;
      const v = Number(r.strategy_min_delay_pax_s);
      if (Number.isFinite(v) && v > 0) return v;
      const v2 = Number(r.delay_with_strategy_pax_s);
      return Number.isFinite(v2) ? v2 : null;
    }

    function _delayBaseline(r) {
      if (!r) return null;
      const v = Number(r.no_strategy_delay_pax_s);
      if (Number.isFinite(v) && v > 0) return v;
      const v2 = Number(r.delay_base_pax_s);
      return Number.isFinite(v2) ? v2 : null;
    }

    function _nearestByJctTime(rows, jct, tRef) {
      let best = null;
      let bestDt = 1e9;
      rows.forEach(r => {
        if (Number(r.jct) !== Number(jct)) return;
        const dt = Math.abs((Number(r.t) || 0) - tRef);
        if (dt < bestDt) {
          bestDt = dt;
          best = r;
        }
      });
      return (bestDt <= 60.0) ? best : null;
    }

    const xcompLabels  = [];
    const noTspTTArr   = [];
    const indepTTArr   = [];
    const rewardTTArr  = [];
    const coordTTArr   = [];
    const ttSavCoordArr = [];  // noTsp_TT - coord_TT  (positive = coord faster)
    const ttSavIndepArr = [];  // noTsp_TT - indep_TT
    const ttSavRewardArr = []; // noTsp_TT - reward_TT
    let xcompMode = 'journey';

    function _journeyTT(journeyObj) {
      const stops = (journeyObj || {}).stops || [];
      if (stops.length < 2) return null;
      return (stops[stops.length-1].t || 0) - (stops[0].t || 0);
    }

    grantedVids.forEach(vid => {
      const coordJ  = coordJMap[vid];
      const noTspJ  = noTspJMap[vid];
      if (!coordJ || !noTspJ) return;   // must have journeys in both baseline and coordinated

      const coordTT = _journeyTT(coordJ);
      const noTspTT = _journeyTT(noTspJ);
      if (coordTT === null || noTspTT === null) return;

      const indepTT = _journeyTT(indepJMap[vid]);   // may be null if bus not seen
      const rewardTT = _journeyTT(rewardJMap[vid]); // may be null if bus not seen

      xcompLabels.push(`Bus ${vid}`);
      noTspTTArr.push(Math.max(0, noTspTT));
      coordTTArr.push(Math.max(0, coordTT));
      indepTTArr.push(indepTT !== null ? Math.max(0, indepTT) : null);
      rewardTTArr.push(rewardTT !== null ? Math.max(0, rewardTT) : null);
      ttSavCoordArr.push(Math.round(noTspTT - coordTT));
      ttSavIndepArr.push(indepTT !== null ? Math.round(noTspTT - indepTT) : null);
      ttSavRewardArr.push(rewardTT !== null ? Math.round(noTspTT - rewardTT) : null);
    });

    // Fallback for runs where vehicle IDs are not stable across experiments:
    // compare GE/INS ACTION events by (junction, time-bucket), then nearest time.
    if (!xcompLabels.length) {
      const coordActs = _actionRows(coordRun);
      const indepActs = _actionRows(indepRun);
      const rewardActs = _actionRows(rewardRun);
      coordActs.forEach(ca => {
        const jct = Number(ca.jct);
        const tRef = Number(ca.t) || 0;
        const inM = _nearestByJctTime(indepActs, jct, tRef);
        const rwM = _nearestByJctTime(rewardActs, jct, tRef);

        const dNo = _delayBaseline(ca);
        const dCoord = _delayValue(ca);
        const dInd = _delayValue(inM);
        const dReward = _delayValue(rwM);
        if (!(Number.isFinite(dNo) && Number.isFinite(dCoord))) return;

        xcompMode = 'objective';
        xcompLabels.push(`j${jct}@t${Math.round(tRef)}`);
        noTspTTArr.push(Math.max(0, dNo));
        coordTTArr.push(Math.max(0, dCoord));
        indepTTArr.push(Number.isFinite(dInd) ? Math.max(0, dInd) : null);
        rewardTTArr.push(Number.isFinite(dReward) ? Math.max(0, dReward) : null);
        ttSavCoordArr.push(Math.round(dNo - dCoord));
        ttSavIndepArr.push(Number.isFinite(dInd) ? Math.round(dNo - dInd) : null);
        ttSavRewardArr.push(Number.isFinite(dReward) ? Math.round(dNo - dReward) : null);
      });
    }

    const nLabel = noTspRun.label  || 'No TSP';
    const cLabel = coordRun.label  || 'Coordinated';
    const iLabel = indepRun ? (indepRun.label || 'Uncoordinated') : 'Uncoordinated';
    const rLabel = rewardRun ? (rewardRun.label || 'Reward-Based') : 'Reward-Based';

    if (xcompLabels.length && ctx) {
      if (noDataEl) noDataEl.style.display = 'none';
      ctx.style.display = '';
      const datasets = [
        { label: `${nLabel} — corridor TT (s)`,   data: noTspTTArr,   backgroundColor: 'rgba(255,82,82,0.7)',   yAxisID: 'y' },
        { label: `${iLabel} — corridor TT (s)`,   data: indepTTArr,   backgroundColor: 'rgba(255,179,0,0.7)',   yAxisID: 'y' },
        { label: `${cLabel} — corridor TT (s)`,   data: coordTTArr,   backgroundColor: 'rgba(41,182,246,0.7)',  yAxisID: 'y' },
        { label: `TT saving: ${cLabel} vs ${nLabel} (s)`,  data: ttSavCoordArr, backgroundColor: 'rgba(0,230,118,0.6)',  yAxisID: 'y2', borderWidth: 1, borderColor: 'rgba(0,230,118,0.9)' },
        { label: `TT saving: ${iLabel} vs ${nLabel} (s)`,  data: ttSavIndepArr, backgroundColor: 'rgba(255,235,59,0.4)',  yAxisID: 'y2', borderWidth: 1, borderColor: 'rgba(255,235,59,0.8)' },
      ];
      if (rewardRun) {
        datasets.splice(2, 0,
          { label: `${rLabel} — corridor TT (s)`, data: rewardTTArr, backgroundColor: 'rgba(139,195,74,0.7)', yAxisID: 'y' }
        );
        datasets.push(
          { label: `TT saving: ${rLabel} vs ${nLabel} (s)`, data: ttSavRewardArr, backgroundColor: 'rgba(174,213,129,0.35)', yAxisID: 'y2', borderWidth: 1, borderColor: 'rgba(174,213,129,0.8)' }
        );
      }
      new Chart(ctx.getContext('2d'), {
        type: 'bar',
        data: { labels: xcompLabels, datasets },
        options: {
          responsive: true,
          animation: false,
          plugins: {
            legend: { labels: { color: '#9090cc', font: { size: 10 } } },
            tooltip: { backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc', borderColor: '#2a2a50', borderWidth: 1 },
            title: {
              display: true,
              text: (xcompMode === 'journey')
                ? `Buses granted GE/INS in ${cLabel} run — corridor TT across all runs (${xcompLabels.length} buses)`
                : `Cross-experiment matched actions (jct/time) — objective delay across runs (${xcompLabels.length} matches)`,
              color: '#7070a0', font: { size: 11 },
            },
          },
          scales: {
            x:  { ticks: { color: '#9090cc', maxRotation: 60 }, grid: { color: '#1e1e38' } },
            y:  { ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' }, title: { display: true, text: 'Corridor total time (s)', color: '#7070a0' }, min: 0 },
            y2: { position: 'right', ticks: { color: '#00e676' }, grid: { display: false }, title: { display: true, text: 'Time saving vs baseline (s)', color: '#00e676' } },
          },
        },
      });
    } else if (noDataEl) {
      noDataEl.textContent = `No same-bus or matched objective-action pairs found for ${cLabel}.`;
    }

    // ── Delay comparison chart (same bus set, red-stop estimate) ──────────
    // Delay proxy: n_red_stops × 30s  (same approach as buscomp "red arrivals")
    const delayCtxEl  = document.getElementById('xcomp-delay-canvas');
    const delayNoData = document.getElementById('xcomp-delay-no-data');

    // Use red-stop COUNT (not reds×30s) — the 30s proxy created delay > corridor_time
    // which is physically impossible and misleading. Count is honest and directly shows
    // whether TSP reduced the number of red-phase arrivals for each bus.
    function _busRedStops(journeyMap, vid) {
      const j = journeyMap[vid];
      if (!j) return null;
      return (j.stops || []).filter(s => !s.on_green).length;
    }

    if (xcompMode === 'journey' && xcompLabels.length && delayCtxEl) {
      const grantedVidsArr = [...grantedVids];
      const noTspDelArr   = xcompLabels.map((_, i) => _busRedStops(noTspJMap, grantedVidsArr[i]));
      const coordDelArr   = xcompLabels.map((_, i) => _busRedStops(coordJMap, grantedVidsArr[i]));
      const indepDelArr   = xcompLabels.map((_, i) => _busRedStops(indepJMap, grantedVidsArr[i]));
      const rewardDelArr  = xcompLabels.map((_, i) => _busRedStops(rewardJMap, grantedVidsArr[i]));
      // Saving = baseline reds - strategy reds (positive = fewer reds = improvement)
      const delSavCoord   = noTspDelArr.map((d, i) => d !== null && coordDelArr[i] !== null ? d - coordDelArr[i] : null);
      const delSavIndep   = noTspDelArr.map((d, i) => d !== null && indepDelArr[i] !== null ? d - indepDelArr[i] : null);
      const delSavReward  = noTspDelArr.map((d, i) => d !== null && rewardDelArr[i] !== null ? d - rewardDelArr[i] : null);
      const delayDatasets = [
        { label: `${nLabel} — red stops`,   data: noTspDelArr,  backgroundColor: 'rgba(255,82,82,0.7)',  yAxisID: 'y' },
        { label: `${iLabel} — red stops`,   data: indepDelArr,  backgroundColor: 'rgba(255,179,0,0.7)',  yAxisID: 'y' },
        { label: `${cLabel} — red stops`,   data: coordDelArr,  backgroundColor: 'rgba(41,182,246,0.7)', yAxisID: 'y' },
        { label: `Red stops saved: ${cLabel} vs ${nLabel}`, data: delSavCoord, backgroundColor: 'rgba(0,230,118,0.6)', yAxisID: 'y2', borderWidth: 1, borderColor: 'rgba(0,230,118,0.9)' },
        { label: `Red stops saved: ${iLabel} vs ${nLabel}`, data: delSavIndep, backgroundColor: 'rgba(255,235,59,0.4)', yAxisID: 'y2', borderWidth: 1, borderColor: 'rgba(255,235,59,0.8)' },
      ];
      if (rewardRun) {
        delayDatasets.splice(2, 0,
          { label: `${rLabel} — red stops`, data: rewardDelArr, backgroundColor: 'rgba(139,195,74,0.7)', yAxisID: 'y' }
        );
        delayDatasets.push(
          { label: `Red stops saved: ${rLabel} vs ${nLabel}`, data: delSavReward, backgroundColor: 'rgba(174,213,129,0.35)', yAxisID: 'y2', borderWidth: 1, borderColor: 'rgba(174,213,129,0.8)' }
        );
      }

      delayCtxEl.style.display = '';
      if (delayNoData) delayNoData.style.display = 'none';
      new Chart(delayCtxEl.getContext('2d'), {
        type: 'bar',
        data: {
          labels: xcompLabels,
          datasets: delayDatasets,
        },
        options: {
          responsive: true,
          animation: false,
          plugins: {
            legend: { labels: { color: '#9090cc', font: { size: 10 } } },
            tooltip: {
              backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc',
              borderColor: '#2a2a50', borderWidth: 1,
              callbacks: {
                afterBody: () => ['Note: these are buses that received GE/INS in the coordinated run.',
                                  'They are inherently the "hard cases" — comparing the SAME bus',
                                  'across strategies (right axis saving) is the fair measure.']
              }
            },
            title: {
              display: true,
              text: `Same-bus comparison — red-phase arrivals per corridor journey (${xcompLabels.length} buses granted priority in ${cLabel})`,
              color: '#7070a0', font: { size: 11 },
            },
          },
          scales: {
            x:  { ticks: { color: '#9090cc', maxRotation: 60 }, grid: { color: '#1e1e38' } },
            y:  { ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' }, title: { display: true, text: 'Red-phase arrivals (count)', color: '#7070a0' }, min: 0 },
            y2: { position: 'right', ticks: { color: '#00e676' }, grid: { display: false }, title: { display: true, text: 'Red stops saved vs baseline', color: '#00e676' } },
          },
        },
      });
    } else if (xcompMode !== 'journey' && delayNoData) {
      delayNoData.style.display = '';
      delayNoData.textContent = 'Red-stop chart requires same bus IDs across runs; objective-match mode is shown in the chart above.';
    }
  }
}

// ── Reward State-Action Diagnostics ─────────────────────────────────────
{
  let _rewardChart = null;
  let _rewardMode = 'jct';   // 'jct' | 'bus'
  let _rewardRi   = null;

  // Colour palette for action types (consistent across both modes)
  const ACTION_COLORS = {
    'NO_ACTION': 'rgba(120,120,180,0.70)',
    'GE_5':      'rgba(0,200,100,0.75)',
    'GE_10':     'rgba(0,230,140,0.75)',
    'GE_15':     'rgba(80,255,160,0.75)',
    'INS_10':    'rgba(41,182,246,0.75)',
    'INS_15':    'rgba(100,200,255,0.75)',
    'INS_20':    'rgba(160,220,255,0.75)',
  };
  function actionColor(a) {
    return ACTION_COLORS[a] || 'rgba(180,140,60,0.70)';
  }

  function renderRewardChart(ri) {
    _rewardRi = ri;
    if (_rewardMode === 'bus') {
      renderRewardBusJourney(ri);
    } else {
      renderRewardJct(ri);
    }
  }

  // ── Mode: By Junction (original view) ───────────────────────────────────
  function renderRewardJct(ri) {
    const r = runs[ri];
    const rows0 = (r.reward_cycle || []);
    const noDataEl = document.getElementById('reward-no-data');
    const ctx = document.getElementById('reward-canvas');
    const jctSel = document.getElementById('reward-jct-sel');
    const onlyChosen = document.getElementById('reward-only-chosen')?.checked;

    if (_rewardChart) { _rewardChart.destroy(); _rewardChart = null; }
    if (!ctx) return;

    if (!rows0.length) {
      if (noDataEl) noDataEl.style.display = '';
      ctx.style.display = 'none';
      if (jctSel) jctSel.innerHTML = '<option value="">All</option>';
      return;
    }

    const allJcts = [...new Set(rows0.map(x => Number(x.jct)).filter(v => Number.isFinite(v) && v > 0))].sort((a,b)=>a-b);
    if (jctSel) {
      const prev = jctSel.value;
      jctSel.innerHTML = '<option value="">All</option>';
      allJcts.forEach(j => {
        const o = document.createElement('option');
        o.value = String(j);
        o.textContent = `jct ${j}`;
        jctSel.appendChild(o);
      });
      if (prev && allJcts.includes(Number(prev))) jctSel.value = prev;
    }

    const selJ = jctSel && jctSel.value ? Number(jctSel.value) : null;
    let rows = rows0.filter(x => !selJ || Number(x.jct) === selJ);
    if (onlyChosen) rows = rows.filter(x => Number(x.is_chosen) === 1);

    if (!rows.length) {
      if (noDataEl) {
        noDataEl.style.display = '';
        noDataEl.textContent = 'No reward rows for this filter (try turning off "chosen only" or selecting All junctions).';
      }
      ctx.style.display = 'none';
      return;
    }

    if (noDataEl) noDataEl.style.display = 'none';
    ctx.style.display = '';

    // All candidate rows shown (NO_ACTION included).  Each row is one candidate
    // evaluated for one (bus, junction, time) decision cycle.
    const chartRows = rows;

    // Group rows by decision cycle (junction × sim_time) so X-axis shows one
    // group per bus-arrival event regardless of how many candidates were tested.
    const cycleKeys = [];
    const cycleMap  = {};
    chartRows.forEach(x => {
      const key = `j${x.jct}|t${Math.round(Number(x.t)||0)}|v${x.vid}`;
      if (!cycleMap[key]) {
        cycleMap[key] = { jct: x.jct, t: Number(x.t), vid: x.vid, rows: [] };
        cycleKeys.push(key);
      }
      cycleMap[key].rows.push(x);
    });
    const cycles = cycleKeys.map(k => cycleMap[k]);
    cycles.sort((a,b) => a.t - b.t || a.jct - b.jct);

    const labels = cycles.map(c => `j${c.jct}\nt=${Math.round(c.t)}s`);

    // One dataset per action type so the legend is colour-coded
    const actionTypes = ['NO_ACTION','GE_5','GE_10','GE_15','INS_10','INS_15','INS_20'];
    const datasets = actionTypes.map(act => ({
      label: act,
      data: cycles.map(c => {
        const row = c.rows.find(x => x.action === act);
        return row ? (Number(row.reward) || 0) : null;
      }),
      backgroundColor: actionColor(act),
      borderColor:     act === 'NO_ACTION' ? 'rgba(180,180,255,0.6)' : actionColor(act),
      borderWidth:     act === 'NO_ACTION' ? 1 : 0,
      borderSkipped:   false,
      spanGaps:        false,
    }));

    // Overlay: star = chosen action raw reward value
    const chosenReward = cycles.map(c => {
      const chosen = c.rows.find(x => Number(x.is_chosen) === 1);
      return chosen ? (Number(chosen.reward) || 0) : null;
    });
    datasets.push({
      label: '★ chosen',
      data: chosenReward,
      type: 'line',
      borderColor: 'rgba(255,220,50,1)',
      backgroundColor: 'rgba(255,220,50,0.3)',
      pointStyle: 'star',
      pointRadius: 9,
      pointHoverRadius: 12,
      borderWidth: 0,
      fill: false,
      yAxisID: 'y',
      order: 0,
    });

    // Robust y-axis bounds: clip to 2nd–98th percentile of all rewards so a
    // handful of extreme outliers (from old data with mc_mult bug) don't
    // collapse the chart scale and make normal values appear as blanks.
    const allRewardVals = chartRows.map(x => Number(x.reward)).filter(v => Number.isFinite(v));
    let yMin = undefined, yMax = undefined;
    if (allRewardVals.length > 10) {
      const rv = [...allRewardVals].sort((a, b) => a - b);
      const p02 = rv[Math.floor(rv.length * 0.02)];
      const p98 = rv[Math.floor(rv.length * 0.98)];
      const margin = Math.max(Math.abs(p98 - p02) * 0.10, 1.0);
      yMin = p02 - margin;
      yMax = p98 + margin;
    }

    _rewardChart = new Chart(ctx.getContext('2d'), {
      type: 'bar',
      data: { labels, datasets },
      options: {
        responsive: true, animation: false,
        plugins: {
          legend: { labels: { color: '#9090cc', font: { size: 10 } } },
          tooltip: {
            backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc',
            borderColor: '#2a2a50', borderWidth: 1,
            callbacks: {
              afterBody: (items) => {
                const ci   = items[0]?.dataIndex;
                const act  = items[0]?.dataset?.label;
                if (ci == null) return [];
                const c = cycles[ci];
                const row = c.rows.find(x => x.action === act);
                if (!row) return [];
                const naRow = c.rows.find(x => x.action === 'NO_ACTION');
                const naR = naRow ? Number(naRow.reward||0) : Number(row.no_action_reward||0);
                const delta = Number(row.reward_delta || (Number(row.reward||0) - naR));
                return [
                  `reward (raw):    ${Number(row.reward||0).toFixed(4)}`,
                  `NO_ACTION r:     ${naR.toFixed(4)}`,
                  `Δ (vs NO_ACTION): ${delta >= 0 ? '+' : ''}${delta.toFixed(4)}`,
                  `σ_in=${Number(row.sigma_in_s||0).toFixed(1)}s  σ_out=${Number(row.sigma_out_s||0).toFixed(1)}s`,
                  `chosen: ${Number(row.is_chosen)===1 ? 'YES ★' : 'no'}`,
                ];
              },
            },
          },
          title: {
            display: true,
            text: `${r.label} — by junction (${cycles.length} decision cycles, ${chartRows.length} candidates)` + (onlyChosen ? ' [chosen filter]' : '') + (yMin !== undefined ? '  [y-axis clipped to 2–98%ile]' : ''),
            color: '#7070a0', font: { size: 11 },
          },
        },
        scales: {
          x: { ticks: { color: '#9090cc', maxRotation: 70, minRotation: 30 }, grid: { color: '#1e1e38' } },
          y: {
            min: yMin, max: yMax,
            ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' },
            title: { display: true, text: 'actual reward  (INV_DELAY/V2X: 0–1 · MARL: pax·s)', color: '#7070a0' },
          },
        },
      },
    });
  }

  // ── Mode: By Bus Journey ─────────────────────────────────────────────────
  // Shows, for a selected bus, its sequence of junctions and what action was
  // chosen (or all candidates) at each stop — X-axis = junction visit order.
  function renderRewardBusJourney(ri) {
    const r = runs[ri];
    const rows0 = (r.reward_cycle || []);
    const noDataEl = document.getElementById('reward-no-data');
    const ctx = document.getElementById('reward-canvas');
    const busSel = document.getElementById('reward-bus-sel');
    const showAll = document.getElementById('reward-bus-all-cands')?.checked;

    if (_rewardChart) { _rewardChart.destroy(); _rewardChart = null; }
    if (!ctx) return;

    if (!rows0.length) {
      if (noDataEl) noDataEl.style.display = '';
      ctx.style.display = 'none';
      return;
    }

    // Populate bus selector
    const allBuses = [...new Set(rows0.map(x => Number(x.vid)).filter(v => Number.isFinite(v) && v > 0))].sort((a,b)=>a-b);
    if (busSel) {
      const prev = busSel.value;
      busSel.innerHTML = '<option value="">All buses (chosen only)</option>';
      allBuses.forEach(v => {
        const o = document.createElement('option');
        o.value = String(v);
        o.textContent = `Bus ${v}`;
        busSel.appendChild(o);
      });
      if (prev && allBuses.includes(Number(prev))) busSel.value = prev;
    }

    const selBus = busSel && busSel.value ? Number(busSel.value) : null;

    if (selBus !== null) {
      // ── Single bus: stacked bar per junction, one bar per action candidate ─
      // Get all rows for this bus, sorted by sim time
      let busRows = rows0.filter(x => Number(x.vid) === selBus);
      if (!showAll) busRows = busRows.filter(x => Number(x.is_chosen) === 1);
      busRows = busRows.sort((a, b) => Number(a.t) - Number(b.t));

      if (!busRows.length) {
        if (noDataEl) {
          noDataEl.style.display = '';
          noDataEl.textContent = `No data for bus ${selBus}.`;
        }
        ctx.style.display = 'none';
        return;
      }

      if (noDataEl) noDataEl.style.display = 'none';
      ctx.style.display = '';

      // X labels: "jct XXXXX @ t=NNN"
      // If showing all candidates, group by (jct, t) → one group per junction visit
      if (showAll) {
        // Group rows by junction visit (sim_time + jct)
        const groups = [];
        const groupMap = {};
        busRows.forEach(x => {
          const key = `${x.jct}@${Math.round(Number(x.t))}`;
          if (!groupMap[key]) {
            groupMap[key] = { jct: x.jct, t: Number(x.t), rows: [] };
            groups.push(groupMap[key]);
          }
          groupMap[key].rows.push(x);
        });
        groups.sort((a,b) => a.t - b.t);

        const labels = groups.map(g => `j${g.jct}\nt=${Math.round(g.t)}s`);
        const actionTypes = ['NO_ACTION','GE_5','GE_10','GE_15','INS_10','INS_15','INS_20'];

        const datasets = actionTypes.map(act => ({
          label: act,
          data: groups.map(g => {
            const row = g.rows.find(x => x.action === act);
            return row ? (Number(row.reward) || 0) : null;
          }),
          backgroundColor: actionColor(act),
          borderColor: act === 'NO_ACTION' ? 'rgba(200,200,255,0.4)' : undefined,
          borderWidth: act === 'NO_ACTION' ? 1 : 0,
          // Highlight chosen with solid border
          borderSkipped: false,
        }));

        // Overlay markers for chosen actions
        const chosenReward = groups.map(g => {
          const chosen = g.rows.find(x => Number(x.is_chosen) === 1);
          return chosen ? Number(chosen.reward) : null;
        });

        datasets.push({
          label: '★ chosen',
          data: chosenReward,
          type: 'line',
          borderColor: 'rgba(255,220,50,1)',
          backgroundColor: 'rgba(255,220,50,0.3)',
          pointStyle: 'star',
          pointRadius: 10,
          pointHoverRadius: 12,
          borderWidth: 0,
          fill: false,
          yAxisID: 'y',
          order: 0,
        });

        _rewardChart = new Chart(ctx.getContext('2d'), {
          type: 'bar',
          data: { labels, datasets },
          options: {
            responsive: true, animation: false,
            plugins: {
              legend: { labels: { color: '#9090cc', font: { size: 10 } } },
              title: {
                display: true,
                text: `Bus ${selBus} corridor journey — all action candidates at each junction`,
                color: '#7070a0', font: { size: 11 },
              },
              tooltip: {
                backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc',
                borderColor: '#2a2a50', borderWidth: 1,
                callbacks: {
                  afterBody: (items) => {
                    const gi = items[0]?.dataIndex;
                    const act = items[0]?.dataset?.label;
                    if (gi == null) return [];
                    const g = groups[gi];
                    const row = g.rows.find(x => x.action === act);
                    if (!row) return [];
                    return [
                      `σ_in=${Number(row.sigma_in_s||0).toFixed(1)}s  σ_out=${Number(row.sigma_out_s||0).toFixed(1)}s`,
                      `no-act delay: ${Number(row.no_strategy_delay_pax_s||0).toFixed(0)} pax·s`,
                      `with-action:  ${Number(row.strategy_min_delay_pax_s||0).toFixed(0)} pax·s`,
                      `chosen: ${Number(row.is_chosen)===1 ? 'YES ★' : 'no'}`,
                    ];
                  },
                },
              },
            },
            scales: {
              x: { ticks: { color: '#9090cc', maxRotation: 60, minRotation: 30 }, grid: { color: '#1e1e38' } },
              y: {
                ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' },
                title: { display: true, text: 'actual reward  (INV_DELAY/V2X: 0–1 · MARL: pax·s)', color: '#7070a0' },
              },
            },
          },
        });

      } else {
        // Chosen-only: line chart of reward along the journey
        const labels = busRows.map(x => `j${x.jct}\nt=${Math.round(Number(x.t))}s`);
        const rewards = busRows.map(x => Number(x.reward) || 0);
        const saves   = busRows.map(x => {
          const base = Number(x.no_strategy_delay_pax_s) || 0;
          const strat = Number(x.strategy_min_delay_pax_s) || 0;
          return Math.max(0, base - strat);
        });
        const colors = busRows.map(x => actionColor(x.action));

        _rewardChart = new Chart(ctx.getContext('2d'), {
          type: 'bar',
          data: {
            labels,
            datasets: [
              {
                label: 'pax delay saved (chosen)',
                data: saves,
                backgroundColor: colors,
                yAxisID: 'y',
                order: 2,
              },
              {
                label: 'reward (chosen)',
                data: rewards,
                type: 'line',
                borderColor: 'rgba(255,193,7,1)',
                borderWidth: 2,
                pointRadius: 4,
                pointBackgroundColor: colors,
                fill: false,
                yAxisID: 'y',
                order: 1,
              },
            ],
          },
          options: {
            responsive: true, animation: false,
            plugins: {
              legend: { labels: { color: '#9090cc', font: { size: 10 } } },
              title: {
                display: true,
                text: `Bus ${selBus} corridor journey — chosen actions (${busRows.length} junctions visited)`,
                color: '#7070a0', font: { size: 11 },
              },
              tooltip: {
                backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc',
                borderColor: '#2a2a50', borderWidth: 1,
                callbacks: {
                  afterBody: (items) => {
                    const idx = items[0]?.dataIndex;
                    if (idx == null) return [];
                    const x = busRows[idx];
                    return [
                      `action: ${x.action}`,
                      `σ_in=${Number(x.sigma_in_s||0).toFixed(1)}s  σ_out=${Number(x.sigma_out_s||0).toFixed(1)}s`,
                      `no-act: ${Number(x.no_strategy_delay_pax_s||0).toFixed(0)} pax·s → ${Number(x.strategy_min_delay_pax_s||0).toFixed(0)} pax·s`,
                    ];
                  },
                },
              },
            },
            scales: {
              x: { ticks: { color: '#9090cc', maxRotation: 60, minRotation: 30 }, grid: { color: '#1e1e38' } },
              y: {
                ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' },
                title: { display: true, text: 'reward / pax delay saved', color: '#7070a0' },
              },
            },
          },
        });
      }

    } else {
      // ── All buses: one bar per bus, showing total reward across the corridor ─
      if (noDataEl) noDataEl.style.display = 'none';
      ctx.style.display = '';

      const chosenRows = rows0.filter(x => Number(x.is_chosen) === 1);
      const totalByBus = {};
      chosenRows.forEach(x => {
        const vid = Number(x.vid);
        if (!totalByBus[vid]) totalByBus[vid] = { total_reward: 0, total_saved: 0, jct_count: 0, actions: {} };
        totalByBus[vid].total_reward += Number(x.reward) || 0;
        const base  = Number(x.no_strategy_delay_pax_s) || 0;
        const strat = Number(x.strategy_min_delay_pax_s) || 0;
        totalByBus[vid].total_saved += Math.max(0, base - strat);
        totalByBus[vid].jct_count++;
        const act = x.action || 'NO_ACTION';
        totalByBus[vid].actions[act] = (totalByBus[vid].actions[act] || 0) + 1;
      });

      const sortedBuses = Object.entries(totalByBus).sort((a,b) => b[1].total_saved - a[1].total_saved);
      const labels  = sortedBuses.map(([vid]) => `Bus ${vid}`);
      const rewards = sortedBuses.map(([,v]) => v.total_reward);
      const saves   = sortedBuses.map(([,v]) => v.total_saved);
      const jcounts = sortedBuses.map(([,v]) => v.jct_count);

      // Colour by dominant action type
      const domColors = sortedBuses.map(([,v]) => {
        const top = Object.entries(v.actions).sort((a,b)=>b[1]-a[1])[0]?.[0] || 'NO_ACTION';
        return actionColor(top);
      });

      _rewardChart = new Chart(ctx.getContext('2d'), {
        type: 'bar',
        data: {
          labels,
          datasets: [
            { label: 'total pax delay saved (corridor)', data: saves, backgroundColor: domColors, yAxisID: 'y', order: 2 },
            { label: 'total reward',                     data: rewards, type: 'line', borderColor: 'rgba(255,193,7,1)', borderWidth: 2, pointRadius: 3, fill: false, yAxisID: 'y', order: 1 },
          ],
        },
        options: {
          responsive: true, animation: false,
          plugins: {
            legend: { labels: { color: '#9090cc', font: { size: 10 } } },
            title: {
              display: true,
              text: `${r.label} — all buses, total corridor reward (sorted by pax-delay saved)`,
              color: '#7070a0', font: { size: 11 },
            },
            tooltip: {
              backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc',
              borderColor: '#2a2a50', borderWidth: 1,
              callbacks: {
                afterBody: (items) => {
                  const idx = items[0]?.dataIndex;
                  if (idx == null) return [];
                  const [vid, v] = sortedBuses[idx];
                  const actSummary = Object.entries(v.actions).map(([a,n])=>`${a}×${n}`).join(' ');
                  return [
                    `Junctions: ${v.jct_count}`,
                    `Actions: ${actSummary}`,
                  ];
                },
              },
            },
          },
          scales: {
            x: { ticks: { color: '#9090cc', maxRotation: 60, minRotation: 30 }, grid: { color: '#1e1e38' } },
            y: {
              ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' },
              title: { display: true, text: 'pax·s', color: '#7070a0' },
            },
          },
        },
      });
    }
  }

  const rewardRuns = runs
    .map((r, i) => ({ r, i }))
    .filter(x => (x.r.reward_cycle || []).length > 0)
    .map(x => x.i);

  const rewardTabHost = document.getElementById('reward-run-tabs');
  if (rewardTabHost) {
    rewardTabHost.innerHTML = '';
    rewardRuns.forEach((ri, idx) => {
      const btn = document.createElement('button');
      btn.className = 'run-tab' + (idx === 0 ? ' active' : '');
      btn.textContent = runs[ri].label;
      btn.onclick = () => {
        rewardTabHost.querySelectorAll('.run-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderRewardChart(ri);
      };
      rewardTabHost.appendChild(btn);
    });

    // Mode toggle buttons
    const modeJctBtn = document.getElementById('reward-mode-jct');
    const modeBusBtn = document.getElementById('reward-mode-bus');
    const jctCtrl    = document.getElementById('reward-jct-controls');
    const busCtrl    = document.getElementById('reward-bus-controls');
    const modeHint   = document.getElementById('reward-mode-hint');

    function setRewardMode(mode) {
      _rewardMode = mode;
      modeJctBtn?.classList.toggle('active', mode === 'jct');
      modeBusBtn?.classList.toggle('active', mode === 'bus');
      if (jctCtrl) jctCtrl.style.display = mode === 'jct' ? 'flex' : 'none';
      if (busCtrl) busCtrl.style.display = mode === 'bus' ? 'flex' : 'none';
      if (modeHint) modeHint.textContent = mode === 'jct'
        ? 'Reward = wh×Δheadway + (1-wh)×ΔNetPaxDelay. Positive = net-beneficial.'
        : 'Bus Journey: X-axis = corridor junction sequence for the selected bus. Bar colour = action type.';
      if (_rewardRi !== null) renderRewardChart(_rewardRi);
    }

    modeJctBtn?.addEventListener('click', () => setRewardMode('jct'));
    modeBusBtn?.addEventListener('click', () => setRewardMode('bus'));

    // Event listeners for filters
    const jsel = document.getElementById('reward-jct-sel');
    if (jsel) jsel.addEventListener('change', () => { if (_rewardRi !== null) renderRewardChart(_rewardRi); });
    const chk = document.getElementById('reward-only-chosen');
    if (chk) chk.addEventListener('change', () => { if (_rewardRi !== null) renderRewardChart(_rewardRi); });
    const bsel = document.getElementById('reward-bus-sel');
    if (bsel) bsel.addEventListener('change', () => { if (_rewardRi !== null) renderRewardChart(_rewardRi); });
    const bchk = document.getElementById('reward-bus-all-cands');
    if (bchk) bchk.addEventListener('change', () => { if (_rewardRi !== null) renderRewardChart(_rewardRi); });

    if (rewardRuns.length) renderRewardChart(rewardRuns[0]);
  }
}

// ── MDN Delay Calibration chart ───────────────────────────────────────────
// Shows per-decision-cycle: MDN-predicted total delay (no-action and chosen
// action) vs the Aimsun-measured cumulative car delay increment.
// Only populated for runs with MDN data (no_strategy_delay_pax_s > 0 in CSV).
{
  let _mdnCalibChart = null;
  let _mdnCalibRi    = null;

  // Build time-bucketed series from reward_cycle rows.
  // Calibration: compare predicted bus delay (no_act_delay_s, seconds) with
  // actual headway change at the intersection (sigma_out - sigma_in, seconds).
  // Both are in seconds → same scale.  For NO_ACTION rows the predicted and
  // actual delays should align when the model is well-calibrated.
  // For TSP-action rows (INS/GE/ER), sigma_out − sigma_in ≈ 0 (bus was saved).
  function _buildMdnCalibSeries(rows, jctFilter, chosenOnly) {
    const pred = [];   // {t, pred_na_s, actual_delta_s, action, jct}

    // Filter by junction
    const filtered = jctFilter
      ? rows.filter(r => Number(r.jct) === Number(jctFilter))
      : rows;

    // Build from chosen-action rows (each represents one decision cycle).
    const chosenRows = filtered.filter(r => Number(r.is_chosen) === 1);
    chosenRows.sort((a, b) => Number(a.t) - Number(b.t));
    chosenRows.forEach(r => {
      const sigma_in  = Number(r.sigma_in_s)  || 0;
      const sigma_out = Number(r.sigma_out_s) || 0;
      pred.push({
        t:            Number(r.t),
        pred_na_s:    Number(r.no_act_delay_s) || 0,   // predicted bus delay (s)
        actual_delta: sigma_out - sigma_in,             // actual headway change (s)
        sigma_in:     sigma_in,                         // incoming headway state (s)
        jct:          Number(r.jct),
        action:       r.action,
      });
    });

    return { pred };
  }

  function renderMdnCalibChart(ri) {
    _mdnCalibRi = ri;
    const r        = runs[ri];
    const rows0    = r.reward_cycle || [];
    const noDataEl = document.getElementById('mdn-calib-no-data');
    const ctx      = document.getElementById('mdn-calib-canvas');
    const jctSel   = document.getElementById('mdn-calib-jct-sel');
    const chosenOnly = document.getElementById('mdn-calib-chosen-only')?.checked ?? true;

    if (_mdnCalibChart) { _mdnCalibChart.destroy(); _mdnCalibChart = null; }
    if (!ctx) return;

    // Detect data: any chosen row with no_act_delay_s present
    const hasData = rows0.some(x => Number(x.is_chosen) === 1);
    if (!hasData || !rows0.length) {
      if (noDataEl) noDataEl.style.display = '';
      ctx.style.display = 'none';
      return;
    }
    if (noDataEl) noDataEl.style.display = 'none';
    ctx.style.display = '';

    // Populate junction selector
    const allJcts = [...new Set(rows0.map(x => Number(x.jct)).filter(Number.isFinite))].sort((a,b)=>a-b);
    if (jctSel) {
      const prev = jctSel.value;
      jctSel.innerHTML = '<option value="">All junctions</option>';
      allJcts.forEach(j => {
        const o = document.createElement('option');
        o.value = j; o.textContent = `Junction ${j}`;
        jctSel.appendChild(o);
      });
      jctSel.value = prev || '';
    }

    const jctFilter = jctSel?.value || '';
    const { pred } = _buildMdnCalibSeries(rows0, jctFilter, chosenOnly);

    // Build point arrays for Chart.js — all in seconds (same scale).
    const labels     = pred.map(p => `t=${Math.round(p.t)}s`);
    const predNaY    = pred.map(p => p.pred_na_s);        // model predicted bus delay (s)
    const actualDY   = pred.map(p => p.actual_delta);     // sigma_out − sigma_in (s)
    const sigmaInY   = pred.map(p => p.sigma_in);         // incoming headway state (s)

    // Colour-code actual_delta by action type: NO_ACTION grey, INS green, GE teal, ER orange.
    const ptColors = pred.map(p => {
      const a = (p.action || '').toLowerCase();
      if (a === 'no_action') return 'rgba(160,160,200,0.7)';
      if (a.startsWith('ins')) return 'rgba(100,220,120,0.85)';
      if (a.startsWith('ge'))  return 'rgba(78,205,196,0.85)';
      if (a.startsWith('er') || a.startsWith('early')) return 'rgba(255,159,67,0.85)';
      return 'rgba(200,180,100,0.7)';
    });

    if (_mdnCalibChart) _mdnCalibChart.destroy();
    _mdnCalibChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Predicted bus delay — no action (s)',
            data: predNaY,
            borderColor: '#4ecdc4', backgroundColor: 'rgba(78,205,196,0.15)',
            borderWidth: 2, pointRadius: 3, tension: 0.2, fill: false,
          },
          {
            label: 'Actual headway change σ_out − σ_in (s, colour = action)',
            data: actualDY,
            borderColor: 'transparent',
            backgroundColor: ptColors,
            borderWidth: 0, pointRadius: 5, pointStyle: 'circle',
            showLine: false, type: 'scatter',
          },
          {
            label: 'Incoming headway deviation σ_in (s)',
            data: sigmaInY,
            borderColor: '#9b59b6', backgroundColor: 'rgba(155,89,182,0.08)',
            borderWidth: 1.5, pointRadius: 0, tension: 0.2, fill: false,
            borderDash: [4, 4],
          },
        ],
      },
      options: {
        animation: false,
        plugins: {
          legend: { labels: { color: '#9090cc', font: { size: 10 } } },
          title: {
            display: true,
            text: `${r.label} — delay calibration (predicted bus delay vs actual headway change)`,
            color: '#7070a0', font: { size: 11 },
          },
          tooltip: {
            backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc',
            borderColor: '#2a2a50', borderWidth: 1,
            callbacks: {
              afterBody: (items) => {
                const idx = items[0]?.dataIndex;
                if (idx == null) return [];
                const p = pred[idx];
                if (!p) return [];
                return [
                  `junction: ${p.jct}`,
                  `action: ${p.action}`,
                  `predicted no-action delay: ${p.pred_na_s.toFixed(1)}s`,
                  `actual Δheadway (σ_out − σ_in): ${p.actual_delta.toFixed(1)}s`,
                  `σ_in: ${p.sigma_in.toFixed(1)}s`,
                ];
              },
            },
          },
        },
        scales: {
          x: { ticks: { color: '#9090cc', maxRotation: 70, minRotation: 30 }, grid: { color: '#1e1e38' } },
          y: {
            ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' },
            title: { display: true, text: 'bus delay / headway deviation (s)', color: '#7070a0' },
          },
        },
      },
    });
  }

  // Initialise delay calibration panel — show for any run with chosen reward_cycle rows.
  const mdnCalibSection  = document.getElementById('mdn-calib-section');
  const mdnCalibTabHost  = document.getElementById('mdn-calib-run-tabs');
  const mdnCalibRuns     = runs.filter((r, ri) =>
    (r.reward_cycle || []).some(x => Number(x.is_chosen) === 1));

  if (!mdnCalibRuns.length && mdnCalibSection) {
    mdnCalibSection.style.display = 'none';
  } else {
    mdnCalibRuns.forEach((r, idx) => {
      const ri  = runs.indexOf(r);
      const btn = document.createElement('button');
      btn.className = 'run-tab' + (idx === 0 ? ' active' : '');
      btn.textContent = r.label;
      btn.onclick = () => {
        mdnCalibTabHost.querySelectorAll('.run-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderMdnCalibChart(ri);
      };
      mdnCalibTabHost.appendChild(btn);
    });

    const jsel = document.getElementById('mdn-calib-jct-sel');
    const chk  = document.getElementById('mdn-calib-chosen-only');
    if (jsel) jsel.addEventListener('change', () => { if (_mdnCalibRi !== null) renderMdnCalibChart(_mdnCalibRi); });
    if (chk)  chk.addEventListener('change',  () => { if (_mdnCalibRi !== null) renderMdnCalibChart(_mdnCalibRi); });

    if (mdnCalibRuns.length) renderMdnCalibChart(runs.indexOf(mdnCalibRuns[0]));
  }
}

// ── MDN Phase Delay Decomposition chart ───────────────────────────────────
// ── Delay Method Validation chart ───────────────────────────────────────────
// Two scatter sub-plots stacked in one canvas (simulated via two Chart.js charts):
//
//   TOP  – Cross-traffic model validation (car delay pax·s):
//     X = Δ measured_car_pax_s_cumul between consecutive NO_ACTION events at
//         the same junction (= actual Aimsun-measured car delay for that interval).
//     Y = other_delay_model_pax_s (UpFlowList-based cross-traffic cost model:
//         _dctsp_cross_traffic_delay_s(bus_phase_duration), or _mdn_na_pax_s for MDN mode).
//     This validates the cross-traffic cost model against the Aimsun ground truth.
//
//   BOTTOM – Bus delay method comparison (bus delay seconds):
//     X = no_act_delay_s (kinematic model — reference baseline).
//     Y = dd1_delay_s / mb_delay_s (alternative methods).
//     Shows how D/D/1 queue and moving-bottleneck compare to the kinematic model.
//     (True bus ground-truth requires downstream detectors; kinematic is the
//      best proxy available in-controller.)
{
  let _delayValChart  = null;
  let _delayValChart2 = null;
  let _delayValRi     = null;

  function renderDelayValChart(ri) {
    _delayValRi = ri;
    const r        = runs[ri];
    const rows0    = r.reward_cycle || [];
    const noDataEl = document.getElementById('delay-val-no-data');
    const ctx      = document.getElementById('delay-val-canvas');
    const ctx2     = document.getElementById('delay-val-canvas2');
    const jctSel   = document.getElementById('delay-val-jct-sel');
    const showDd1  = document.getElementById('delay-val-dd1')?.checked ?? true;
    const showMb   = document.getElementById('delay-val-mb')?.checked ?? true;

    if (_delayValChart)  { _delayValChart.destroy();  _delayValChart  = null; }
    if (_delayValChart2) { _delayValChart2.destroy(); _delayValChart2 = null; }
    if (!ctx) return;

    // Only rows where the agent chose NO_ACTION
    const noActRows = rows0.filter(x =>
      Number(x.is_chosen) === 1 && x.action === 'NO_ACTION');

    const hasNewCols = noActRows.some(x => x.dd1_delay_s !== undefined && x.dd1_delay_s !== '');
    if (!noActRows.length || !hasNewCols) {
      if (noDataEl) noDataEl.style.display = '';
      if (ctx)  ctx.style.display  = 'none';
      if (ctx2) ctx2.style.display = 'none';
      return;
    }
    if (noDataEl) noDataEl.style.display = 'none';
    if (ctx)  ctx.style.display  = '';
    if (ctx2) ctx2.style.display = '';

    // Populate junction selector
    const allJcts = [...new Set(noActRows.map(x => Number(x.jct)).filter(Number.isFinite))].sort((a,b)=>a-b);
    if (jctSel) {
      const prev = jctSel.value;
      jctSel.innerHTML = '<option value="">All junctions</option>';
      allJcts.forEach(j => { const o = document.createElement('option'); o.value = j; o.textContent = `Junction ${j}`; jctSel.appendChild(o); });
      jctSel.value = prev || '';
    }
    const jctFilter = jctSel?.value || '';
    const filtered = jctFilter ? noActRows.filter(x => String(x.jct) === jctFilter) : noActRows;

    // ── TOP chart: cross-traffic measured delta vs model predicted ──────────
    // If the CSV contains the newer per-event delta columns (interval_s > 0), use
    // them directly and time-normalise both sides to the same bus-phase window so
    // they are directly comparable (pax·s per bp_dur_s):
    //   X_norm = measured_delta × (bp_dur_s / interval_s)
    //   Y      = other_delay_model_pax_s_nf1  (raw triangle, NF removed)
    //
    // NOTE: We use the NF=1 column (other_delay_model_pax_s_nf1) so the 45° line
    // is interpretable. The NF-amplified column (other_delay_model_pax_s) was the
    // Y-axis in older dashboards and caused apparent 4-5× over-prediction for
    // INV_DELAY/ZIG because NF is a decision bias, not a calibration target.
    // Newer CSVs have both columns; older CSVs fall back to dividing by NF.
    const crossPts = [];
    const hasNewDelta = filtered.some(row => Number(row.interval_s) > 0);
    if (hasNewDelta) {
      filtered.forEach(row => {
        const delta  = Number(row.measured_car_pax_s_delta || 0);
        const intv   = Number(row.interval_s) || 0;
        const bpDur  = Number(row.bp_dur_s) || 30;
        // Use NF=1 prediction for validation; fall back gracefully for old CSVs.
        const predNF  = Number(row.other_delay_model_pax_s || 0);
        const nf      = Math.max(Number(row.network_factor || 1), 1);
        const pred    = (row.other_delay_model_pax_s_nf1 !== undefined &&
                         row.other_delay_model_pax_s_nf1 !== '')
                        ? Number(row.other_delay_model_pax_s_nf1)
                        : predNF / nf;
        if (intv > 1 && pred >= 0) {
          const measNorm = delta * bpDur / intv;
          crossPts.push({ x: measNorm, y: pred,
                          _jct: String(row.jct), _t: Number(row.t),
                          _delta: delta, _intv: intv, _bpDur: bpDur,
                          _nf: nf });
        }
      });
    } else {
      // Old CSV: compute delta from cumulative column per junction.
      const jctPrevCumul = {};
      const sortedForDelta = [...filtered].sort((a, b) => {
        const jc = String(a.jct).localeCompare(String(b.jct));
        return jc !== 0 ? jc : Number(a.t) - Number(b.t);
      });
      sortedForDelta.forEach(row => {
        const jct    = String(row.jct);
        const cumul  = Number(row.measured_car_pax_s_cumul || 0);
        const predNF = Number(row.other_delay_model_pax_s  || 0);
        const nf     = Math.max(Number(row.network_factor || 1), 1);
        const pred   = predNF / nf;
        if (jctPrevCumul[jct] !== undefined) {
          const delta = cumul - jctPrevCumul[jct];
          if (delta >= 0 && pred >= 0) {
            crossPts.push({ x: delta, y: pred,
                            _jct: jct, _t: Number(row.t), _cumul: cumul, _nf: nf });
          }
        }
        jctPrevCumul[jct] = cumul;
      });
    }
    const xLabel = hasNewDelta
      ? 'Measured car delay × (bp_dur/interval) pax·s (time-normalised)'
      : 'Actual total car delay Δ pax·s (Aimsun measured, per interval)';
    const yLabel = 'Cross-traffic cost model pax·s (NF=1 raw triangle)';

    // Cap axis at 95th percentile to prevent outliers from collapsing the scale.
    function _pct95(arr) {
      if (!arr.length) return 10;
      const s = [...arr].sort((a, b) => a - b);
      return s[Math.min(Math.floor(s.length * 0.95), s.length - 1)] || 10;
    }
    const _allC = crossPts.flatMap(p => [p.x, p.y]).filter(v => v > 0);
    let maxC = Math.max(100, Math.ceil(_pct95(_allC) * 1.2 / 100) * 100);

    _delayValChart = new Chart(ctx, {
      type: 'scatter',
      data: { datasets: [
        { label: 'Perfect (45°)', data: [{x:0,y:0},{x:maxC,y:maxC}],
          type: 'line', borderColor: '#ffffff44', borderDash: [6,4],
          borderWidth: 1.5, pointRadius: 0, fill: false },
        { label: 'Cross-traffic model vs measured car delay (pax·s)', data: crossPts,
          backgroundColor: '#4ecdc488', borderColor: '#4ecdc4', borderWidth: 1, pointRadius: 4 },
      ]},
      options: {
        animation: false,
        plugins: {
          legend: { labels: { color: '#ccc', font: { size: 11 } } },
          tooltip: { callbacks: { label: c => {
            const d = c.raw;
            const detail = hasNewDelta
              ? `  raw_Δ=${d._delta?.toFixed(0)} pax·s  intv=${d._intv?.toFixed(0)}s  bp=${d._bpDur?.toFixed(0)}s`
              : `  cumul=${d._cumul?.toFixed(0)}`;
            return `jct=${d._jct} t=${d._t?.toFixed(0)}s  norm_actual=${d.x?.toFixed(0)} pax·s  model=${d.y?.toFixed(0)} pax·s${detail}`;
          }}},
        },
        scales: {
          x: { type: 'linear', min: 0, max: maxC,
               title: { display: true, text: xLabel, color: '#aaa', font: { size: 11 } },
               ticks: { color: '#aaa', font: { size: 10 } }, grid: { color: '#444' } },
          y: { type: 'linear', min: 0, max: maxC,
               title: { display: true, text: yLabel, color: '#aaa', font: { size: 11 } },
               ticks: { color: '#aaa', font: { size: 10 } }, grid: { color: '#444' } },
        },
      },
    });

    // ── BOTTOM chart: bus delay methods vs kinematic reference ──────────────
    // Exclude rows where kinematic delay = 0 (bus was already on green — no
    // delay expected, so D/D/1 and MB can't be validated against the reference).
    // These "on-green" events are annotated separately in the legend count.
    const dd1Pts = [], mbPts = [];
    let maxB = 10;
    let zeroKinCount = 0;
    filtered.forEach(row => {
      const kin = Math.max(0, Number(row.no_act_delay_s || 0));
      const dd1 = Math.max(0, Number(row.dd1_delay_s || 0));
      const mb  = Math.max(0, Number(row.mb_delay_s  || 0));
      if (kin === 0) { zeroKinCount++; return; }   // bus on green – skip from scatter
      if (showDd1) dd1Pts.push({ x: kin, y: dd1 });
      if (showMb)  mbPts.push({ x: kin, y: mb  });
      maxB = Math.max(maxB, kin, dd1, mb);
    });
    maxB = Math.ceil(_pct95([...dd1Pts.flatMap(p=>[p.x,p.y]), ...mbPts.flatMap(p=>[p.x,p.y])].filter(v=>v>0)) * 1.2 / 10) * 10 || Math.ceil(maxB * 1.1 / 10) * 10;

    if (ctx2) {
      const dsBus = [
        { label: `Perfect (45°) — ${zeroKinCount} on-green events excluded (kinematic=0)`, data: [{x:0,y:0},{x:maxB,y:maxB}],
          type: 'line', borderColor: '#ffffff44', borderDash: [6,4],
          borderWidth: 1.5, pointRadius: 0, fill: false },
      ];
      if (showDd1) dsBus.push({
        label: `D/D/1 queue (n=${dd1Pts.length})`, data: dd1Pts, type: 'scatter',
        backgroundColor: '#ffd63288', borderColor: '#ffd632', borderWidth: 1, pointRadius: 4,
      });
      if (showMb) dsBus.push({
        label: `Moving bottleneck (n=${mbPts.length})`, data: mbPts, type: 'scatter',
        backgroundColor: '#ff9f4388', borderColor: '#ff9f43', borderWidth: 1, pointRadius: 4,
      });
      _delayValChart2 = new Chart(ctx2, {
        type: 'scatter',
        data: { datasets: dsBus },
        options: {
          animation: false,
          plugins: {
            legend: { labels: { color: '#ccc', font: { size: 11 } } },
            tooltip: { callbacks: { label: c => `kinematic=${c.raw.x.toFixed(1)}s  method=${c.raw.y.toFixed(1)}s` } },
          },
          scales: {
            x: { type: 'linear', min: 0, max: maxB,
                 title: { display: true, text: 'Kinematic bus delay (s) — reference', color: '#aaa', font: { size: 11 } },
                 ticks: { color: '#aaa', font: { size: 10 } }, grid: { color: '#444' } },
            y: { type: 'linear', min: 0, max: maxB,
                 title: { display: true, text: 'D/D/1 or MB bus delay estimate (s)', color: '#aaa', font: { size: 11 } },
                 ticks: { color: '#aaa', font: { size: 10 } }, grid: { color: '#444' } },
          },
        },
      });
    }
  }

  // Wire controls
  function _reDelayVal() { if (_delayValRi != null) renderDelayValChart(_delayValRi); }
  document.addEventListener('DOMContentLoaded', () => {
    const jctSel = document.getElementById('delay-val-jct-sel');
    if (jctSel) jctSel.addEventListener('change', _reDelayVal);
    ['delay-val-dd1','delay-val-mb'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('change', _reDelayVal);
    });
  });

  // Tab wiring
  function _buildDelayValRunTabs(runs) {
    const tabsEl = document.getElementById('delay-val-run-tabs');
    if (!tabsEl) return;
    tabsEl.innerHTML = '';
    runs.forEach((r, i) => {
      const btn = document.createElement('button');
      btn.className = 'run-tab' + (i === 0 ? ' active' : '');
      btn.textContent = r.name;
      btn.addEventListener('click', () => {
        tabsEl.querySelectorAll('.run-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderDelayValChart(i);
      });
      tabsEl.appendChild(btn);
    });
    if (runs.length > 0) renderDelayValChart(0);
  }
  window._buildDelayValRunTabs = _buildDelayValRunTabs;
}

// Shows per-detection: bus-phase contribution (no_act_delay_s × bus_occ) and
// cross-traffic contribution (NA_total − bus_phase) as stacked bars, plus the
// chosen-action bus saving and car cost.  Helps validate the reward signal.
{
  let _mdnPhaseChart = null;
  let _mdnPhaseRi    = null;

  function renderMdnPhaseChart(ri) {
    _mdnPhaseRi = ri;
    const r        = runs[ri];
    const rows0    = r.reward_cycle || [];
    const noDataEl = document.getElementById('mdn-phase-no-data');
    const ctx      = document.getElementById('mdn-phase-canvas');
    const jctSel   = document.getElementById('mdn-phase-jct-sel');

    if (_mdnPhaseChart) { _mdnPhaseChart.destroy(); _mdnPhaseChart = null; }
    if (!ctx) return;

    const hasData = rows0.some(x => Number(x.is_chosen) === 1 && Number(x.no_strategy_delay_pax_s) > 0);
    if (!hasData || !rows0.length) {
      if (noDataEl) noDataEl.style.display = '';
      ctx.style.display = 'none';
      return;
    }
    if (noDataEl) noDataEl.style.display = 'none';
    ctx.style.display = '';

    // Populate junction selector
    const allJcts = [...new Set(rows0.map(x => Number(x.jct)).filter(Number.isFinite))].sort((a,b)=>a-b);
    if (jctSel) {
      const prev = jctSel.value;
      jctSel.innerHTML = '<option value="">All junctions</option>';
      allJcts.forEach(j => {
        const o = document.createElement('option');
        o.value = j; o.textContent = `Junction ${j}`;
        jctSel.appendChild(o);
      });
      jctSel.value = prev || '';
    }

    const jctFilter = jctSel?.value ? Number(jctSel.value) : null;
    // Use only chosen-action rows (one per detection event)
    let chosen = rows0.filter(x => Number(x.is_chosen) === 1);
    if (jctFilter) chosen = chosen.filter(x => Number(x.jct) === jctFilter);
    chosen = chosen.sort((a, b) => Number(a.t) - Number(b.t));

    if (!chosen.length) {
      if (noDataEl) { noDataEl.style.display = ''; noDataEl.textContent = 'No chosen-action rows for this junction.'; }
      ctx.style.display = 'none';
      return;
    }

    // Per detection: decompose NA_total into bus phase vs cross-traffic
    const labels = chosen.map(x => `j${x.jct}\nt=${Math.round(Number(x.t))}s`);
    const busPhasePax = chosen.map(x => {
      const bo = Number(x.bus_occ) || 20;
      return Number(x.no_act_delay_s) * bo;
    });
    const xtraffPax = chosen.map(x => {
      const bo = Number(x.bus_occ) || 20;
      const total = Number(x.no_strategy_delay_pax_s) || 0;
      const bus   = Number(x.no_act_delay_s) * bo;
      return Math.max(0, total - bus);
    });
    const busSaved  = chosen.map(x => Number(x.bus_saved_pax_s)  || 0);
    const carCost   = chosen.map(x => -Math.abs(Number(x.other_inc_pax_s) || 0));

    _mdnPhaseChart = new Chart(ctx.getContext('2d'), {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: 'Bus phase (NA) pax·s',
            data: busPhasePax,
            backgroundColor: 'rgba(78,205,196,0.75)',
            stack: 'na',
          },
          {
            label: 'Cross-traffic (NA) pax·s',
            data: xtraffPax,
            backgroundColor: 'rgba(100,100,140,0.65)',
            stack: 'na',
          },
          {
            label: 'Bus saved pax·s (chosen)',
            data: busSaved,
            backgroundColor: 'rgba(46,204,113,0.8)',
            stack: 'chosen',
          },
          {
            label: 'Car cost pax·s (chosen)',
            data: carCost,
            backgroundColor: 'rgba(231,76,60,0.7)',
            stack: 'chosen',
          },
        ],
      },
      options: {
        responsive: true, animation: false,
        plugins: {
          legend: { labels: { color: '#9090cc', font: { size: 10 } } },
          title: {
            display: true,
            text: `${r.label} — phase delay decomposition (chosen action, per detection)`,
            color: '#7070a0', font: { size: 11 },
          },
          tooltip: {
            backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc',
            borderColor: '#2a2a50', borderWidth: 1,
            callbacks: {
              afterBody: (items) => {
                const i = items[0]?.dataIndex;
                if (i == null) return [];
                const x = chosen[i];
                const bo = Number(x.bus_occ) || 20;
                const na = Number(x.no_strategy_delay_pax_s) || 0;
                const busPs = Number(x.no_act_delay_s) * bo;
                return [
                  `action: ${x.action}`,
                  `no_act_delay_s: ${Number(x.no_act_delay_s).toFixed(2)}s`,
                  `bus_occ: ${bo} pax`,
                  `bus-phase pax·s: ${busPs.toFixed(1)}`,
                  `cross-traffic pax·s: ${Math.max(0, na - busPs).toFixed(1)}`,
                  `NA_total: ${na.toFixed(1)}`,
                  `reward: ${Number(x.reward).toFixed(3)}`,
                ];
              },
            },
          },
        },
        scales: {
          x: { stacked: true, ticks: { color: '#9090cc', maxRotation: 70, minRotation: 30 }, grid: { color: '#1e1e38' } },
          y: {
            stacked: true,
            ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' },
            title: { display: true, text: 'pax·s', color: '#7070a0' },
          },
        },
      },
    });
  }

  const mdnPhaseSection = document.getElementById('mdn-phase-section');
  const mdnPhaseTabHost = document.getElementById('mdn-phase-run-tabs');
  const mdnPhaseRuns    = runs.filter(r =>
    (r.reward_cycle || []).some(x => Number(x.is_chosen) === 1 && Number(x.no_strategy_delay_pax_s) > 0));

  if (!mdnPhaseRuns.length && mdnPhaseSection) {
    mdnPhaseSection.style.display = 'none';
  } else {
    mdnPhaseRuns.forEach((r, idx) => {
      const ri  = runs.indexOf(r);
      const btn = document.createElement('button');
      btn.className = 'run-tab' + (idx === 0 ? ' active' : '');
      btn.textContent = r.label;
      btn.onclick = () => {
        mdnPhaseTabHost.querySelectorAll('.run-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderMdnPhaseChart(ri);
      };
      mdnPhaseTabHost.appendChild(btn);
    });

    const jsel = document.getElementById('mdn-phase-jct-sel');
    if (jsel) jsel.addEventListener('change', () => { if (_mdnPhaseRi !== null) renderMdnPhaseChart(_mdnPhaseRi); });

    if (mdnPhaseRuns.length) renderMdnPhaseChart(runs.indexOf(mdnPhaseRuns[0]));
  }

  // ── Delay Validation chart wiring ────────────────────────────────────────
  const delayValSection = document.getElementById('delay-val-section');
  const delayValTabHost = document.getElementById('delay-val-run-tabs');
  // Show for any run with reward_cycle data containing dd1_delay_s column
  const delayValRuns = runs.filter(r =>
    (r.reward_cycle || []).some(x =>
      Number(x.is_chosen) === 1 && x.dd1_delay_s !== undefined && x.dd1_delay_s !== ''));

  if (!delayValRuns.length && delayValSection) {
    delayValSection.style.display = 'none';
  } else if (delayValSection) {
    delayValSection.style.display = '';
    delayValRuns.forEach((r, idx) => {
      const ri  = runs.indexOf(r);
      const btn = document.createElement('button');
      btn.className = 'run-tab' + (idx === 0 ? ' active' : '');
      btn.textContent = r.label;
      btn.onclick = () => {
        delayValTabHost.querySelectorAll('.run-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderDelayValChart(ri);
      };
      delayValTabHost.appendChild(btn);
    });
    if (delayValRuns.length) renderDelayValChart(runs.indexOf(delayValRuns[0]));
  }
}

// ── DYNAOPAC Phase Optimisation chart ─────────────────────────────────────
{
  let _dynChart = null;

  function renderDynChart(ri) {
    const r = runs[ri];
    const decisions = r.dynaropac_decisions || [];
    const noDataEl = document.getElementById('dyn-no-data');
    const ctx = document.getElementById('dyn-canvas');
    const jctSel = document.getElementById('dyn-jct-sel');
    const showApplied = document.getElementById('dyn-show-applied')?.checked;
    if (_dynChart) { _dynChart.destroy(); _dynChart = null; }

    if (!decisions.length) {
      if (noDataEl) noDataEl.style.display = '';
      if (ctx) ctx.style.display = 'none';
      return;
    }
    if (noDataEl) noDataEl.style.display = 'none';
    if (ctx) ctx.style.display = '';

    // Populate junction selector
    const allJcts = [...new Set(decisions.map(d => d.jct))].sort((a,b)=>a-b);
    if (jctSel) {
      const prevVal = jctSel.value;
      jctSel.innerHTML = '<option value="">All (scatter)</option>';
      allJcts.forEach(j => {
        const o = document.createElement('option');
        o.value = j; o.textContent = `jct ${j}`;
        jctSel.appendChild(o);
      });
      jctSel.value = prevVal;
    }
    const filterJct = jctSel && jctSel.value ? parseInt(jctSel.value) : null;
    const filtered = filterJct ? decisions.filter(d => d.jct === filterJct) : decisions;

    // Build scatter data: one point per (extension, delay) candidate
    const allPts    = [];  // {x: ext_s, y: delay, applied, jct, t, baseline}
    const appliedPts = [];
    const baselinePts = [];
    filtered.forEach(d => {
      (d.extensions || []).forEach((ext, i) => {
        const pt = { x: ext, y: (d.delays || [])[i] ?? 0, jct: d.jct, t: d.t, baseline: d.baseline_delay };
        if (ext === 0) baselinePts.push(pt);
        if (d.applied && ext === d.best_ext) appliedPts.push(pt);
        else allPts.push(pt);
      });
    });

    const datasets = [
      {
        label: 'Candidate delays',
        data: allPts,
        backgroundColor: 'rgba(41,182,246,0.25)',
        pointRadius: 2,
        pointHoverRadius: 4,
      },
      {
        label: 'No-action baseline',
        data: baselinePts,
        backgroundColor: 'rgba(255,179,0,0.7)',
        pointRadius: 4,
        pointStyle: 'dash',
      },
    ];
    if (showApplied) {
      datasets.push({
        label: 'Applied (selected best)',
        data: appliedPts,
        backgroundColor: 'rgba(0,230,118,0.9)',
        pointRadius: 7,
        pointStyle: 'star',
      });
    }

    _dynChart = new Chart(ctx.getContext('2d'), {
      type: 'scatter',
      data: { datasets },
      options: {
        responsive: true,
        animation: false,
        plugins: {
          legend: { labels: { color: '#9090cc', font: { size: 10 } } },
          tooltip: {
            backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc',
            borderColor: '#2a2a50', borderWidth: 1,
            callbacks: {
              label: item => {
                const d = item.raw;
                return `ext=${d.x}s delay=${d.y?.toFixed(1)}pax-s jct=${d.jct} t=${d.t}s`;
              },
            },
          },
          title: {
            display: true,
            text: `${r.label} — DYNAOPAC phase extension candidates (${filtered.length} decisions, ${allJcts.length} junctions)`,
            color: '#7070a0', font: { size: 11 },
          },
        },
        scales: {
          x: { title: { display: true, text: 'Extension searched (s)', color: '#7070a0' }, ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' } },
          y: { title: { display: true, text: 'Person-delay (pax-s)', color: '#7070a0' }, ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' } },
        },
      },
    });
  }

  buildRunTabs('dyn-run-tabs', (i) => renderDynChart(i));
  const dynJctSel = document.getElementById('dyn-jct-sel');
  if (dynJctSel) dynJctSel.addEventListener('change', () => {
    const ri = parseInt(document.querySelector('#dyn-run-tabs .run-tab.active')?.dataset?.ri ?? '0');
    renderDynChart(ri >= 0 ? ri : initialRunIdx);
  });
  const dynApplied = document.getElementById('dyn-show-applied');
  if (dynApplied) dynApplied.addEventListener('change', () => {
    const ri = parseInt(document.querySelector('#dyn-run-tabs .run-tab.active')?.dataset?.ri ?? '0');
    renderDynChart(ri >= 0 ? ri : initialRunIdx);
  });
  if (runs.length) renderDynChart(initialRunIdx);
}

// ── Decision Space — TSP corridor timeline (Gantt) ─────────────────────────
{
  let _dsChart = null;
  let _activeDsRun = -1;

  function renderDecisionSpace(ri) {
    _activeDsRun = ri;
    const r = runs[ri];
    const fh = (r.focus_history || []).filter(f => f.held_s > 0);
    const phaseSamples = r.phase_samples || [];
    const journeys = r.bus_journeys || [];
    const focusBusSet = new Set((r.focus_bus_ids || []).map(v => Number(v)));
    const focusWindows = fh.map(f => ({
      veh: Number(f.veh_id),
      jct: Number(f.jct_id),
      t0: Number(f.start_t),
      t1: Number(f.end_t),
    })).filter(f => f.veh > 0 && f.jct > 0 && Number.isFinite(f.t0) && Number.isFinite(f.t1));
    function inFocusWindow(sample) {
      const sv = Number(sample.vid);
      const sj = Number(sample.jct);
      const st = Number(sample.t);
      return focusWindows.some(f =>
        f.veh === sv && f.jct === sj && st >= (f.t0 - 1.0) && st <= (f.t1 + 1.0)
      );
    }
    const noData = document.getElementById('decision-no-data');
    const summ = document.getElementById('decision-summary');
    const canvas = document.getElementById('decision-chart');
    const showPhase = !!document.getElementById('decision-show-phase')?.checked;
    const showFocus = !!document.getElementById('decision-show-focus')?.checked;
    const showLines = !!document.getElementById('decision-show-lines')?.checked;

    if (!fh.length && !phaseSamples.length) {
      noData.textContent = 'No TSP focus history available for this run (loaded events: 0).';
      noData.style.display = '';
      if (summ) summ.textContent = '';
      canvas.style.display = 'none';
      if (_dsChart) { _dsChart.destroy(); _dsChart = null; }
      return;
    }
    noData.style.display = 'none';
    canvas.style.display = '';
    if (summ) {
      const nJctsFocus = new Set(fh.map(f => f.jct_id)).size;
      const nJctsPhase = new Set(phaseSamples.map(p => p.jct)).size;
      const avgHeld = (fh.reduce((s, f) => s + (f.held_s || 0), 0) / Math.max(fh.length, 1)).toFixed(1);
      let summaryTxt = `Loaded ${fh.length} focus segments across ${nJctsFocus || nJctsPhase} junctions`;
      if (fh.length) summaryTxt += ` | avg held ${avgHeld}s`;
      if (phaseSamples.length) {
        const focusPhase = phaseSamples.filter(p => inFocusWindow(p));
        const g = focusPhase.filter(p => Number(p.on_green) === 1).length;
        const tot = focusPhase.length;
        summaryTxt += ` | focus-bus green hits ${g}/${tot}`;
      }
      summaryTxt += ` | prearm: fired ${r.prearm_fired||0}, success ${r.prearm_success||0}, missed ${r.prearm_missed||0}, expired ${r.prearm_expired||0}`;
      summ.textContent = summaryTxt;
    }

    // Build per-junction segments for Chart.js floating bar chart
    // Each segment: {x: [start_t, end_t], y: jct_label}
    const jctIds = fh.length
      ? [...new Set(fh.map(f => f.jct_id))].sort((a,b) => a - b)
      : [...new Set(phaseSamples.map(p => Number(p.jct)).filter(v => v > 0))].sort((a,b) => a - b);
    const jctLabels = jctIds.map(j => String(j));

    // Colour by outcome
    function segColour(outcome) {
      if (!outcome) return 'rgba(120,120,180,0.7)';
      const o = outcome.toLowerCase();
      if (o.includes('ge') || o.includes('ext')) return 'rgba(41,182,246,0.82)';
      if (o.includes('ins'))   return 'rgba(171,71,188,0.82)';
      return 'rgba(255,160,0,0.82)';
    }

    // Build one dataset per outcome type so legend works
    const outcomeKeys = [...new Set(fh.map(f => f.outcome))];
    const datasets = fh.length ? outcomeKeys.map(oc => ({
      label: oc,
      backgroundColor: segColour(oc),
      borderColor: 'transparent',
      borderWidth: 0,
      data: fh
        .filter(f => f.outcome === oc)
        .map(f => ({
          x: [f.start_t, f.end_t],
          y: String(f.jct_id),
        })),
    })) : [];

    // Cooldown indicator dataset — show gap to next event as a faint bar
    if (fh.length) {
      const gapDs = { label: 'normal (gap)', backgroundColor: 'rgba(200,200,200,0.18)',
                      borderColor: 'transparent', borderWidth: 0, data: [] };
      jctIds.forEach(jid => {
        const events = fh.filter(f => f.jct_id === jid).sort((a,b) => a.start_t - b.start_t);
        for (let i = 0; i < events.length - 1; i++) {
          const gapStart = events[i].end_t;
          const gapEnd   = events[i+1].start_t;
          if (gapEnd - gapStart > 1) {
            gapDs.data.push({ x: [gapStart, gapEnd], y: String(jid) });
          }
        }
      });
      datasets.push(gapDs);
    }

    // Phase snapshot overlays from detection points (not continuous signal timeline)
    if (showPhase && phaseSamples.length) {
      const phaseInJcts = phaseSamples.filter(p => jctIds.includes(Number(p.jct)));
      const phaseGreen = phaseInJcts.filter(p => Number(p.on_green) === 1).map(p => ({
        x: Number(p.t),
        y: String(p.jct),
        _vid: Number(p.vid),
        _sig: Number(p.signal_phase),
        _bus: Number(p.bus_phase),
      }));
      const phaseRed = phaseInJcts.filter(p => Number(p.on_green) !== 1).map(p => ({
        x: Number(p.t),
        y: String(p.jct),
        _vid: Number(p.vid),
        _sig: Number(p.signal_phase),
        _bus: Number(p.bus_phase),
      }));

      datasets.push({
        type: 'scatter',
        label: 'signal snapshot green',
        data: phaseGreen,
        pointRadius: 2.2,
        pointHoverRadius: 4,
        pointBackgroundColor: 'rgba(46,204,113,0.85)',
        pointBorderColor: 'rgba(22,160,133,0.85)',
        pointBorderWidth: 0.5,
      });
      datasets.push({
        type: 'scatter',
        label: 'signal snapshot red',
        data: phaseRed,
        pointRadius: 2.2,
        pointHoverRadius: 4,
        pointBackgroundColor: 'rgba(231,76,60,0.85)',
        pointBorderColor: 'rgba(192,57,43,0.85)',
        pointBorderWidth: 0.5,
      });
    }

    if (showFocus && phaseSamples.length && focusWindows.length) {
      const focusPts = phaseSamples.filter(p => inFocusWindow(p) && jctIds.includes(Number(p.jct)));
      const focusGreen = focusPts.filter(p => Number(p.on_green) === 1).map(p => ({
        x: Number(p.t), y: String(p.jct), _vid: Number(p.vid), _sig: Number(p.signal_phase), _bus: Number(p.bus_phase),
      }));
      const focusRed = focusPts.filter(p => Number(p.on_green) !== 1).map(p => ({
        x: Number(p.t), y: String(p.jct), _vid: Number(p.vid), _sig: Number(p.signal_phase), _bus: Number(p.bus_phase),
      }));

      datasets.push({
        type: 'scatter',
        label: 'focus bus arrival green',
        data: focusGreen,
        pointStyle: 'triangle',
        pointRotation: 0,
        pointRadius: 4,
        pointHoverRadius: 6,
        pointBackgroundColor: 'rgba(0,230,118,0.95)',
        pointBorderColor: '#0d7a48',
        pointBorderWidth: 1,
      });
      datasets.push({
        type: 'scatter',
        label: 'focus bus arrival red',
        data: focusRed,
        pointStyle: 'triangle',
        pointRotation: 180,
        pointRadius: 4,
        pointHoverRadius: 6,
        pointBackgroundColor: 'rgba(255,82,82,0.95)',
        pointBorderColor: '#8b2f2f',
        pointBorderWidth: 1,
      });
    }

    if (showLines && journeys.length) {
      const sourceJourneys = focusBusSet.size
        ? journeys.filter(j => focusBusSet.has(Number(j.vid)))
        : journeys.slice(0, 25);
      sourceJourneys.forEach((j, idx) => {
        const pts = (j.stops || [])
          .filter(s => jctIds.includes(Number(s.jct)))
          .map(s => ({ x: Number(s.t), y: String(s.jct) }));
        if (pts.length < 2) return;
        const hue = (idx * 47) % 360;
        datasets.push({
          type: 'line',
          label: `bus ${j.vid} trajectory`,
          data: pts,
          showLine: true,
          tension: 0,
          borderWidth: 1.2,
          borderColor: `hsla(${hue}, 72%, 58%, 0.38)`,
          borderDash: [4, 3],
          pointRadius: 0,
          pointHoverRadius: 0,
        });
      });
    }

    const tCandidates = [];
    fh.forEach(f => { tCandidates.push(Number(f.start_t), Number(f.end_t)); });
    phaseSamples.forEach(p => { tCandidates.push(Number(p.t)); });
    const tMin = Math.min(...tCandidates);
    const tMax = Math.max(...tCandidates);

    if (_dsChart) _dsChart.destroy();
    _dsChart = new Chart(canvas, {
      type: 'bar',
      data: { datasets },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { position: 'top', labels: { font: { size: 11 }, boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: ctx => {
                const d = ctx.raw;
                if (d && Array.isArray(d.x)) {
                  const dur = (d.x[1] - d.x[0]).toFixed(1);
                  return `${ctx.dataset.label} | ${d.x[0].toFixed(0)}s - ${d.x[1].toFixed(0)}s (${dur}s)`;
                }
                if (d && typeof d.x === 'number') {
                  const sig = (d._sig !== undefined && d._sig !== null) ? d._sig : '?';
                  const bus = (d._bus !== undefined && d._bus !== null) ? d._bus : '?';
                  const vid = (d._vid !== undefined && d._vid !== null) ? d._vid : '?';
                  return `${ctx.dataset.label} | t=${d.x.toFixed(1)}s jct=${d.y} veh=${vid} sig=${sig} bus=${bus}`;
                }
                const dur = (d.x[1] - d.x[0]).toFixed(1);
                return `${ctx.dataset.label} | ${d.x[0].toFixed(0)}s - ${d.x[1].toFixed(0)}s (${dur}s)`;
              }
            }
          }
        },
        scales: {
          x: {
            type: 'linear',
            min: Math.max(0, tMin - 30),
            max: tMax + 30,
            title: { display: true, text: 'Simulation time (s)', font: { size: 11 } },
            ticks: { font: { size: 10 } },
          },
          y: {
            type: 'category',
            labels: jctLabels,
            title: { display: true, text: 'Junction ID', font: { size: 11 } },
            ticks: { font: { size: 10 } },
          }
        }
      }
    });
    // Set canvas height dynamically based on number of junctions
    canvas.parentElement.style.height = Math.max(200, jctIds.length * 45 + 80) + 'px';
  }

  buildRunTabs('decision-run-tabs', (i) => renderDecisionSpace(i));
  document.getElementById('decision-show-phase').addEventListener('change', () => {
    if (_activeDsRun >= 0) renderDecisionSpace(_activeDsRun);
  });
  document.getElementById('decision-show-focus').addEventListener('change', () => {
    if (_activeDsRun >= 0) renderDecisionSpace(_activeDsRun);
  });
  document.getElementById('decision-show-lines').addEventListener('change', () => {
    if (_activeDsRun >= 0) renderDecisionSpace(_activeDsRun);
  });
  if (runs.length) renderDecisionSpace(initialRunIdx);
}

// ── Per-intersection breakdown table ──────────────────────────────────────
{
  const interCols = [
    {key:'iid',          hdr:'Junction'},
    {key:'distinct_buses', hdr:'Distinct buses (stats)', lb:false, dec:0},
    {key:'tracked_buses', hdr:'Known buses',           lb:false, dec:0},
    {key:'position_tracked_buses', hdr:'Position-tracked buses', lb:false, dec:0},
    {key:'detected_buses',hdr:'Detected buses',        lb:false, dec:0},
    {key:'tracked_only_buses', hdr:'Tracked-only buses', lb:true, dec:0},
    {key:'coverage_pct',  hdr:'Detection coverage %', lb:false, dec:1},
    {key:'focus_buses',   hdr:'Focus buses',          lb:false, dec:0},
    {key:'bus_passages',  hdr:'Bus passages',         lb:false, dec:0},
    {key:'total_delay',  hdr:'Total delay (hrs)', lb:true,  dec:3},
    {key:'main_delay',   hdr:'Main (hrs)',         lb:true,  dec:3},
    {key:'side_delay',   hdr:'Side (hrs)',         lb:true,  dec:3},
    {key:'bus_tt',       hdr:'Bus TT (hrs)',       lb:true,  dec:3},
    {key:'avg_bus_delay',          hdr:'Avg bus (s)',          lb:true,  dec:1},
    {key:'avg_car_delay',          hdr:'Avg car (s)',          lb:true,  dec:1},
    {key:'avg_truck_delay',        hdr:'Avg truck (s)',        lb:true,  dec:1},
    {key:'avg_main_delay_per_hr',  hdr:'Main delay/h (pax·h)',lb:true,  dec:3},
    {key:'avg_side_delay_per_hr',  hdr:'Side delay/h (pax·h)',lb:true,  dec:3},
    {key:'avg_total_delay_per_hr', hdr:'Total delay/h (pax·h)',lb:true, dec:3},
    {key:'sim_duration_hrs',       hdr:'Sim duration (h)',    lb:false, dec:2},
    {key:'tsp_det',                hdr:'Det (raw)',            lb:false, dec:0},
    {key:'tsp_ext',      hdr:'Ext (raw)',          lb:false, dec:0},
    {key:'tsp_ins',      hdr:'Ins (raw)',          lb:false, dec:0},
    {key:'tsp_natural_green',hdr:'Nat green (raw)', lb:false, dec:0},
    {key:'tsp_skip_ge',  hdr:'GE skip (raw)',      lb:false, dec:0},
    {key:'tsp_skip_ins', hdr:'INS skip (raw)',     lb:false, dec:0},
    {key:'tsp_no_action',hdr:'No action (raw)',    lb:false, dec:0},
    {key:'avg_extension_s', hdr:'Avg GE (s)',      lb:false, dec:1},
    {key:'avg_insertion_s', hdr:'Avg INS (s)',     lb:false, dec:1},
    {key:'avg_insertion_wait_s', hdr:'Avg INS lead (s)', lb:false, dec:1},
    {key:'avg_density',  hdr:'Density (veh/km/lane)',    lb:false, dec:2},
    {key:'avg_speed',    hdr:'Speed (km/h)',       lb:false, dec:1},
    {key:'avg_flow',     hdr:'Flow (v/h)',         lb:false, dec:0},
    {key:'avg_queue',    hdr:'Queue (veh)',        lb:true,  dec:1},
  ];

  let activeInterRun = initialRunIdx;

  function renderInterTable(ri) {
    const r     = runs[ri];
    const table = document.getElementById('inter-table');
    const noDataEl = document.getElementById('inter-no-data');
    const thead = table.querySelector('thead');
    const tbody = table.querySelector('tbody');
    thead.innerHTML = '';
    tbody.innerHTML = '';

    const piRows = r.per_inter || [];
    if (!piRows.length) {
      if (noDataEl) noDataEl.style.display = 'block';
      table.style.display = 'none';
      return;
    }
    if (noDataEl) noDataEl.style.display = 'none';
    table.style.display = '';

    // Build header
    const hrow = document.createElement('tr');
    // First col = label; then one col per run for each metric, or just this run
    const th0 = document.createElement('th'); th0.textContent = 'Junction'; hrow.appendChild(th0);
    interCols.slice(1).forEach(c => {
      const th = document.createElement('th'); th.textContent = c.hdr; hrow.appendChild(th);
    });
    thead.appendChild(hrow);

    // Per-column bests for highlighting
    const colBests = {};
    interCols.slice(1).forEach(c => {
      const vals = piRows.map(row => {
        const v = row[c.key];
        return (v !== null && v !== undefined && !isNaN(v)) ? v : null;
      }).filter(v => v !== null);
      if (!vals.length) return;
      colBests[c.key] = {
        best:  c.lb ? Math.min(...vals) : Math.max(...vals),
        worst: c.lb ? Math.max(...vals) : Math.min(...vals),
      };
    });

    piRows.forEach(pi => {
      const tr = document.createElement('tr');
      // Junction ID cell
      const td0 = document.createElement('td');
      td0.textContent = 'jct ' + pi.iid;
      td0.style.fontWeight = '600';
      tr.appendChild(td0);

      interCols.slice(1).forEach(c => {
        const td  = document.createElement('td');
        const v   = pi[c.key];
        if (v === null || v === undefined || isNaN(v)) {
          td.textContent = '—';
          td.style.color = 'var(--muted)';
        } else {
          td.textContent = c.dec === 0 ? Math.round(v) : v.toFixed(c.dec);
          if (colBests[c.key]) {
            if (v === colBests[c.key].best)  td.classList.add('best');
            if (v === colBests[c.key].worst) td.classList.add('worst');
          }
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  }

  // Run tabs for per-intersection table
  const interTabsDiv = document.getElementById('inter-run-tabs');
  runs.forEach((r, i) => {
    const btn = document.createElement('button');
    btn.className = 'run-tab' + (i === initialRunIdx ? ' active' : '');
    btn.textContent = r.label;
    btn.onclick = () => {
      document.querySelectorAll('#inter-run-tabs .run-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeInterRun = i;
      renderInterTable(i);
    };
    interTabsDiv.appendChild(btn);
  });
  if (runs.length) renderInterTable(initialRunIdx);
}

// ── Delay-by-Junction bar chart (all runs) ────────────────────────────────
{
  const jdCanvas  = document.getElementById('jct-delay-canvas');
  const jdCtx     = jdCanvas ? jdCanvas.getContext('2d') : null;
  const jdMetric  = document.getElementById('jct-delay-metric');
  const jdCompare = document.getElementById('jct-delay-compare');

  // Ordered set of all junctions with per-inter data across all runs
  function _jdOrderedJcts() {
    const allJIds = new Set();
    runs.forEach(r => (r.per_inter || []).forEach(pi => allJIds.add(String(pi.iid))));
    const jp = DATA.jct_positions || {};
    const arr = Array.from(allJIds).sort((a,b) => {
      const ya = jp[parseInt(a)] ? jp[parseInt(a)].y : 0;
      const yb = jp[parseInt(b)] ? jp[parseInt(b)].y : 0;
      return ya - yb;
    });
    return arr;
  }

  const runColors = [
    '#3498db','#2ecc71','#e74c3c','#f39c12','#9b59b6',
    '#1abc9c','#e67e22','#95a5a6','#d35400',
  ];

  function renderJctDelayChart() {
    if (!jdCtx) return;
    const metric   = jdMetric ? jdMetric.value : 'total_delay';
    const compareAll = jdCompare ? jdCompare.checked : true;
    const ordJcts  = _jdOrderedJcts();
    if (!ordJcts.length) { return; }

    const displayRuns = compareAll ? runs : [runs[0]];
    const metricLabel = {
      total_delay: 'Total delay (hrs)', main_delay: 'Main delay (hrs)',
      side_delay: 'Side delay (hrs)', avg_bus_delay: 'Avg bus delay (s)',
      avg_car_delay: 'Avg car delay (s)', avg_truck_delay: 'Avg truck delay (s)',
      avg_main_delay_per_hr: 'Main avg delay/sim-hr (pax·h/h)',
      avg_side_delay_per_hr: 'Side avg delay/sim-hr (pax·h/h)',
      avg_total_delay_per_hr: 'Total avg delay/sim-hr (pax·h/h)',
      distinct_buses: 'Distinct buses (stats)',
      tracked_buses: 'Known buses (all sources)',
      position_tracked_buses: 'Position-tracked buses',
      detected_buses: 'Detected buses',
      tracked_only_buses: 'Tracked-only buses', coverage_pct: 'Detection coverage (%)',
      focus_buses: 'Focus buses', bus_passages: 'Bus passages',
      avg_density: 'Density (veh/km/lane)', avg_speed: 'Speed (km/h)',
      avg_flow: 'Flow (v/h)', avg_queue: 'Queue (veh)',
    }[metric] || metric;

    const dpr = window.devicePixelRatio || 1;
    const W   = jdCanvas.clientWidth || 900;
    const H   = 280;
    jdCanvas.width  = W * dpr;
    jdCanvas.height = H * dpr;
    jdCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    jdCtx.clearRect(0, 0, W, H);

    const padL = 56, padR = 10, padT = 28, padB = 52;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;

    // Background
    jdCtx.fillStyle = '#0a0a1a';
    jdCtx.fillRect(0, 0, W, H);

    // Build data: {jct_str: [val_per_run]}
    const dataByJct = {};
    ordJcts.forEach(j => { dataByJct[j] = []; });
    displayRuns.forEach(r => {
      const piMap = {};
      (r.per_inter || []).forEach(pi => { piMap[String(pi.iid)] = pi; });
      ordJcts.forEach(j => {
        const pi = piMap[j];
        const v = pi ? (pi[metric] ?? null) : null;
        dataByJct[j].push(v);
      });
    });

    // Y scale
    let maxVal = 0;
    ordJcts.forEach(j => {
      dataByJct[j].forEach(v => { if (v !== null) maxVal = Math.max(maxVal, v); });
    });
    if (maxVal <= 0) maxVal = 1;
    const yScale = v => padT + plotH - (v / maxVal) * plotH;

    // Y axis grid + labels
    const nYTicks = 5;
    jdCtx.strokeStyle = '#1a1a3a'; jdCtx.lineWidth = 1;
    jdCtx.fillStyle = '#7777aa'; jdCtx.font = '10px system-ui'; jdCtx.textAlign = 'right';
    for (let i = 0; i <= nYTicks; i++) {
      const v = maxVal * i / nYTicks;
      const y = yScale(v);
      jdCtx.beginPath(); jdCtx.moveTo(padL, y); jdCtx.lineTo(W - padR, y); jdCtx.stroke();
      jdCtx.textBaseline = 'middle';
      jdCtx.fillText(v >= 100 ? Math.round(v) : v.toFixed(v < 1 ? 3 : 1), padL - 4, y);
    }
    // Y label
    jdCtx.save();
    jdCtx.fillStyle = '#9999bb'; jdCtx.font = '11px system-ui'; jdCtx.textAlign = 'center';
    jdCtx.translate(12, padT + plotH / 2);
    jdCtx.rotate(-Math.PI / 2);
    jdCtx.fillText(metricLabel, 0, 0);
    jdCtx.restore();

    // Bars
    const nJcts   = ordJcts.length;
    const nRuns   = displayRuns.length;
    const groupW  = plotW / Math.max(nJcts, 1);
    const barW    = Math.max(2, (groupW * 0.75) / Math.max(nRuns, 1));
    const groupGap = groupW * 0.125;

    ordJcts.forEach((j, ji) => {
      const gx = padL + ji * groupW + groupGap;
      displayRuns.forEach((r, ri) => {
        const v = dataByJct[j][ri];
        if (v === null) return;
        const x  = gx + ri * (barW + 1);
        const y0 = padT + plotH;
        const bh = (v / maxVal) * plotH;
        jdCtx.fillStyle = runColors[ri % runColors.length];
        jdCtx.fillRect(x, y0 - bh, barW, bh);
        // Value label on top of bar if tall enough
        if (bh > 14) {
          jdCtx.fillStyle = '#fff';
          jdCtx.font = '8px system-ui';
          jdCtx.textAlign = 'center';
          jdCtx.textBaseline = 'bottom';
          const label = v >= 10 ? v.toFixed(1) : v.toFixed(3);
          jdCtx.fillText(label, x + barW / 2, y0 - bh - 1);
        }
      });
      // Junction label on x axis
      jdCtx.fillStyle = '#8888bb'; jdCtx.font = '9px system-ui';
      jdCtx.textAlign = 'center'; jdCtx.textBaseline = 'top';
      const lx = padL + ji * groupW + groupW / 2;
      jdCtx.fillText('jct ' + j, lx, H - padB + 4);
    });

    // Legend
    jdCtx.font = '10px system-ui'; jdCtx.textBaseline = 'middle';
    let lx = padL;
    displayRuns.forEach((r, ri) => {
      jdCtx.fillStyle = runColors[ri % runColors.length];
      jdCtx.fillRect(lx, 8, 12, 10);
      jdCtx.fillStyle = '#ccc';
      jdCtx.textAlign = 'left';
      jdCtx.fillText(r.label, lx + 15, 13);
      lx += jdCtx.measureText(r.label).width + 28;
    });
  }

  // Wire events
  if (jdMetric)  jdMetric.addEventListener('change', renderJctDelayChart);
  if (jdCompare) jdCompare.addEventListener('change', renderJctDelayChart);

  // Render after initial table render
  window.addEventListener('load', renderJctDelayChart);
  setTimeout(renderJctDelayChart, 50);  // fallback
}

// ── Per-section table ─────────────────────────────────────────────────────
{
  const secCols = [
    {key:'sec_id',   hdr:'Section'},
    {key:'iid',      hdr:'Junction'},
    {key:'is_main',  hdr:'Main?',        dec:0},
    {key:'length_km',hdr:'Length (km)',   dec:3},
    {key:'density',  hdr:'Density (veh/km/lane)',dec:2},
    {key:'speed',    hdr:'Speed (km/h)',  dec:1},
    {key:'flow',     hdr:'Flow (v/h)',    dec:0},
    {key:'queue',    hdr:'Queue (veh)',   dec:1},
    {key:'samples',  hdr:'Samples',      dec:0},
  ];

  let activeSecRun = initialRunIdx;

  function renderSecTable(ri) {
    const r     = runs[ri];
    const table = document.getElementById('sec-table');
    const noDataEl = document.getElementById('sec-no-data');
    const thead = table.querySelector('thead');
    const tbody = table.querySelector('tbody');
    thead.innerHTML = '';
    tbody.innerHTML = '';

    const secRows = r.per_section || [];
    if (!secRows.length) {
      if (noDataEl) noDataEl.style.display = 'block';
      table.style.display = 'none';
      return;
    }
    if (noDataEl) noDataEl.style.display = 'none';
    table.style.display = '';

    const hrow = document.createElement('tr');
    secCols.forEach(c => {
      const th = document.createElement('th');
      th.textContent = c.hdr;
      hrow.appendChild(th);
    });
    thead.appendChild(hrow);

    secRows.forEach(s => {
      const tr = document.createElement('tr');
      if (s.is_main) tr.style.fontWeight = '600';
      secCols.forEach(c => {
        const td = document.createElement('td');
        let v = s[c.key];
        if (v == null) v = '';
        else if (c.key === 'is_main') v = v ? 'Y' : '';
        else if (c.dec != null && typeof v === 'number') v = v.toFixed(c.dec);
        td.textContent = v;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  }

  const secTabsDiv = document.getElementById('sec-run-tabs');
  runs.forEach((r, i) => {
    const btn = document.createElement('button');
    btn.className = 'run-tab' + (i === initialRunIdx ? ' active' : '');
    btn.textContent = r.label;
    btn.onclick = () => {
      document.querySelectorAll('#sec-run-tabs .run-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeSecRun = i;
      renderSecTable(i);
    };
    secTabsDiv.appendChild(btn);
  });
  if (runs.length) renderSecTable(initialRunIdx);
}

// ── Aimsun-format network stats table ────────────────────────────────────
{
  const sigTable = document.getElementById('signal-timing-table');
  if (sigTable) {
    const sigHead = sigTable.querySelector('thead');
    const sigBody = sigTable.querySelector('tbody');
    sigHead.innerHTML = '<tr><th>Junction</th><th>Run</th><th>Main entry cycle</th><th>Side entry cycle</th><th>Green / red samples</th><th>TSP actions</th></tr>';
    const byJct = {};
    SIGNAL_PLANS.forEach(p => { byJct[String(p.jct)] = p; });
    const planJcts = SIGNAL_PLANS.length ? SIGNAL_PLANS.map(p => String(p.jct)) : jcts.slice();
    const sampleStats = (run, jid) => {
      const rows = (run.phase_samples || []).filter(p => String(p.jct) === String(jid));
      const g = rows.filter(p => Number(p.on_green) === 1).length;
      return { g, r: rows.length - g, n: rows.length };
    };
    const actionStats = (run, jid) => {
      const acts = (run.objective_trace || []).filter(x =>
        String(x.jct) === String(jid) && String(x.decision || '').toUpperCase() === 'ACTION');
      const objGe = acts.filter(x => String(x.mode || '').toUpperCase() === 'GE').length;
      const objIns = acts.filter(x => String(x.mode || '').toUpperCase() === 'INS').length;
      const chosenReward = (run.reward_cycle || []).filter(x =>
        String(x.jct) === String(jid) && Number(x.is_chosen) === 1 &&
        String(x.action || '').toUpperCase() !== 'NO_ACTION');
      const rewGe = chosenReward.filter(x => String(x.action || '').toUpperCase().startsWith('GE')).length;
      const rewIns = chosenReward.filter(x => String(x.action || '').toUpperCase().startsWith('INS')).length;
      const actionSamples = (run.phase_samples || []).filter(p =>
        String(p.jct) === String(jid) && String(p.prearm_status || '').toLowerCase() === 'action');
      const detGe = actionSamples.filter(p => String(p.tier || '').toLowerCase().includes('ge')).length;
      const detIns = actionSamples.filter(p => String(p.tier || '').toLowerCase().includes('ins')).length;
      return {
        ge: Math.max(objGe, rewGe, detGe),
        ins: Math.max(objIns, rewIns, detIns),
        rew: chosenReward.length,
      };
    };
    const cycleBar = (greenS, redS, cycleS, flip) => {
      const gPct = Math.max(0, Math.min(100, 100 * greenS / Math.max(cycleS, 1)));
      const rPct = Math.max(0, 100 - gPct);
      const firstPct = flip ? rPct : gPct;
      const secondPct = flip ? gPct : rPct;
      const firstGreen = !flip;
      const firstTxt = flip ? `${redS.toFixed(0)}s red` : `${greenS.toFixed(0)}s green`;
      const secondTxt = flip ? `${greenS.toFixed(0)}s green` : `${redS.toFixed(0)}s red`;
      return `<div style="min-width:210px">
        <div style="display:flex;height:18px;border:1px solid #2a2a50;border-radius:4px;overflow:hidden;background:#191933">
          <div style="width:${firstPct}%;background:${firstGreen ? 'rgba(0,230,118,0.65)' : 'rgba(255,82,82,0.58)'};font-size:10px;line-height:18px;color:#f0f0ff;text-align:center;white-space:nowrap">${firstTxt}</div>
          <div style="width:${secondPct}%;background:${firstGreen ? 'rgba(255,82,82,0.58)' : 'rgba(0,230,118,0.65)'};font-size:10px;line-height:18px;color:#f0f0ff;text-align:center;white-space:nowrap">${secondTxt}</div>
        </div>
        <div style="display:flex;justify-content:space-between;color:#7070a0;font-size:10px;margin-top:2px"><span>0s</span><span>${greenS.toFixed(0)}s</span><span>${cycleS.toFixed(0)}s</span></div>
      </div>`;
    };
    planJcts.forEach(jid => {
      const p = byJct[String(jid)] || { jct: jid, cycle_s: 135, main_green_s: 0, main_red_s: 135, side_green_s: 135, side_red_s: 0 };
      runs.forEach(run => {
        const ss = sampleStats(run, jid);
        const as = actionStats(run, jid);
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>jct ${jid}<br><span style="color:var(--muted);font-size:10px">cycle ${Number(p.cycle_s).toFixed(0)}s, bus phase ${p.bus_phase || '-'}</span></td>
          <td>${run.label}</td>
          <td>${cycleBar(Number(p.main_green_s)||0, Number(p.main_red_s)||0, Number(p.cycle_s)||135, false)}</td>
          <td>${cycleBar(Number(p.side_green_s)||0, Number(p.side_red_s)||0, Number(p.cycle_s)||135, true)}</td>
          <td><span style="color:#00e676">${ss.g} green</span> / <span style="color:#ff8a80">${ss.r} red</span><br><span style="color:var(--muted);font-size:10px">${ss.n} detection samples</span></td>
          <td>GE ${as.ge} · INS ${as.ins}<br><span style="color:var(--muted);font-size:10px">chosen reward actions ${as.rew}</span></td>`;
        sigBody.appendChild(tr);
      });
    });
  }

  const table = document.getElementById('aimsun-stats-table');
  if (table) {
    const thead = table.querySelector('thead');
    const tbody = table.querySelector('tbody');

    // Rows matching Aimsun's "Time Series" statistics output
    // key: field name in run object (or null if not collected)
    // label: Aimsun display name
    // unit: Aimsun unit string
    // dec: decimal places
    // Aimsun 26 statistical output format — NORMAL reference values shown in notes.
    //   All: Density=24.05, Flow=10946, Speed=6.15, Delay=247.76
    //   Car: Density=23.15, Flow=10521, Speed=6.14, Delay=248.40
    //   Truck: Density=0.62, Flow=298, Speed=6.61, Delay=246.31
    //   Bus: Density=0.29, Flow=127, Speed=5.51, Delay=194.07
    // Entry-Based Delay Time in Aimsun is average delay per vehicle per kilometer and excludes virtual queue time.
    // Pax delay (s/pax) = pax·s of delay / passenger-passages — DIFFERENT metric (shown below).
    // Car occupancy: 1.2 pax/car  |  Bus occupancy: 40 pax/bus
    // Build dynamic NO_TSP reference values from the actual NO_TSP run in this batch
    const noTspRef = runs.find(r => (r.strategy||'').toUpperCase() === 'NORMAL'
                                  || (r.exp_name||'').toUpperCase().includes('NO_TSP')
                                  || (r.label||'').toUpperCase().includes('NO_TSP'));
    const _ref = (key, fallback) => {
      if (!noTspRef) return fallback;
      const v = noTspRef[key];
      return (v !== null && v !== undefined && Number(v) > 0) ? `NO_TSP: ${Number(v).toFixed(2)}` : fallback;
    };
    const _refN = (key, unit, fallback) => {
      if (!noTspRef) return fallback;
      const v = noTspRef[key];
      if (v === null || v === undefined || Number(v) === 0) return fallback;
      return `NO_TSP this run: ${Number(v).toFixed(2)} ${unit}`;
    };

    // Actual NO_TSP values from Aimsun Statistics panel (user-provided reference)
    // These are correct when Aimsun statistics collection is enabled in the scenario.
    const NO_TSP_AIMSUN = {
      density_all: 14.34, density_car: 6.90, density_hov: 6.87, density_bus: 0.16, density_truck: 0.41,
      entry_delay_all: 80.14, entry_delay_car: 78.58, entry_delay_hov: 81.82, entry_delay_bus: 90.09, entry_delay_truck: 76.32,
      exit_delay_all: 82.23,  exit_delay_car: 84.67,  exit_delay_hov: 80.58,  exit_delay_bus: 85.46,  exit_delay_truck: 79.10,
      flow_all: 8962.5, flow_car: 3633.09, flow_hov: 5066.33, flow_bus: 40.54, flow_truck: 222.54,
      speed_all: 25.71, speed_car: 26.08, speed_hov: 25.56, speed_bus: 16.81, speed_truck: 25.69,
    };
    // Compute total pax delay for NO_TSP from delay(s/km) × distance(km) × occupancy
    const NO_TSP_DIST = { bus: 130.39, car: 8569.94, hov: 8361.57, truck: 506.37 };
    const NO_TSP_OCC  = { bus: 40, car: 1.2, hov: 1.5, truck: 1.0 };
    const _noTspPaxDelay = (t) => {
      const d = NO_TSP_AIMSUN[`entry_delay_${t}`] || 0;
      const dist = NO_TSP_DIST[t] || 0;
      const occ  = NO_TSP_OCC[t]  || 1;
      return d * dist * occ / 3600;  // pax-hours
    };
    const noTspTotalPaxDelay_h = ['bus','car','hov','truck'].reduce((s,t) => s + _noTspPaxDelay(t), 0);
    const _ref2 = (aimsunKey, unit) => {
      const v = NO_TSP_AIMSUN[aimsunKey];
      return v != null ? `NO_TSP: ${Number(v).toFixed(2)} ${unit} (Aimsun Stats panel)` : `Requires Aimsun stats API`;
    };

    const AIMSUN_ROWS = [
      // ── Density (veh/km) ─────────────────────────────────────────────────────
      { label:'Density - All',              key:'density_all',    unit:'veh/km', dec:2, note:_ref2('density_all','veh/km') },
      { label:'Density - Car',              key:'net_dens_car',   unit:'veh/km', dec:2, note:_ref2('density_car','veh/km') },
      { label:'Density - HOV Car',          key:'net_dens_hov',   unit:'veh/km', dec:2, note:_ref2('density_hov','veh/km') },
      { label:'Density - Truck',            key:'net_dens_truck', unit:'veh/km', dec:2, note:_ref2('density_truck','veh/km') },
      { label:'Density - Std Bus',          key:'net_dens_bus',   unit:'veh/km', dec:2, note:_ref2('density_bus','veh/km') },
      // ── Entry-Based Delay Time ────────────────────────────────────────────────
      { label:'Entry-Based Delay Time - All',      key:'net_entry_delay_all',   unit:'sec/km', dec:2, note:_ref2('entry_delay_all','sec/km') },
      { label:'Entry-Based Delay Time - Car',      key:'net_entry_delay_car',   unit:'sec/km', dec:2, note:_ref2('entry_delay_car','sec/km') },
      { label:'Entry-Based Delay Time - HOV Car',  key:'net_entry_delay_hov',   unit:'sec/km', dec:2, note:_ref2('entry_delay_hov','sec/km') },
      { label:'Entry-Based Delay Time - Truck',    key:'net_entry_delay_truck', unit:'sec/km', dec:2, note:_ref2('entry_delay_truck','sec/km') },
      { label:'Entry-Based Delay Time - Std Bus',  key:'net_entry_delay_bus',   unit:'sec/km', dec:2, note:_ref2('entry_delay_bus','sec/km') },
      // ── Exit-Based Delay Time ─────────────────────────────────────────────────
      { label:'Exit-Based Delay Time - All',       key:'net_exit_delay_all',   unit:'sec/km', dec:2, note:_ref2('exit_delay_all','sec/km') },
      { label:'Exit-Based Delay Time - Car',       key:'net_exit_delay_car',   unit:'sec/km', dec:2, note:_ref2('exit_delay_car','sec/km') },
      { label:'Exit-Based Delay Time - HOV Car',   key:'net_exit_delay_hov',   unit:'sec/km', dec:2, note:_ref2('exit_delay_hov','sec/km') },
      { label:'Exit-Based Delay Time - Truck',     key:'net_exit_delay_truck', unit:'sec/km', dec:2, note:_ref2('exit_delay_truck','sec/km') },
      { label:'Exit-Based Delay Time - Std Bus',   key:'net_exit_delay_bus',   unit:'sec/km', dec:2, note:_ref2('exit_delay_bus','sec/km') },
      // ── Entry-Based Travel Time ───────────────────────────────────────────────
      { label:'Entry-Based Travel Time - All',      key:'net_entry_tt_all',   unit:'sec/km', dec:2, note:'Mean travel time (entry-based) across network; count-weighted avg of TTa/L_km' },
      { label:'Entry-Based Travel Time - Car',      key:'net_entry_tt_car',   unit:'sec/km', dec:2, note:'Entry-based mean TT per vehicle per km — car' },
      { label:'Entry-Based Travel Time - HOV Car',  key:'net_entry_tt_hov',   unit:'sec/km', dec:2, note:'Entry-based mean TT per vehicle per km — HOV car' },
      { label:'Entry-Based Travel Time - Truck',    key:'net_entry_tt_truck', unit:'sec/km', dec:2, note:'Entry-based mean TT per vehicle per km — truck' },
      { label:'Entry-Based Travel Time - Std Bus',  key:'net_entry_tt_bus',   unit:'sec/km', dec:2, note:'Entry-based mean TT per vehicle per km — bus' },
      // ── Exit-Based Travel Time ────────────────────────────────────────────────
      { label:'Exit-Based Travel Time - All',       key:'net_exit_tt_all',   unit:'sec/km', dec:2, note:'Mean travel time (exit-based) = TotalTravelTime/count/L_km; count-weighted avg' },
      { label:'Exit-Based Travel Time - Car',       key:'net_exit_tt_car',   unit:'sec/km', dec:2, note:'Exit-based mean TT per vehicle per km — car' },
      { label:'Exit-Based Travel Time - HOV Car',   key:'net_exit_tt_hov',   unit:'sec/km', dec:2, note:'Exit-based mean TT per vehicle per km — HOV car' },
      { label:'Exit-Based Travel Time - Truck',     key:'net_exit_tt_truck', unit:'sec/km', dec:2, note:'Exit-based mean TT per vehicle per km — truck' },
      { label:'Exit-Based Travel Time - Std Bus',   key:'net_exit_tt_bus',   unit:'sec/km', dec:2, note:'Exit-based mean TT per vehicle per km — bus' },
      // ── Exit-Based Speed ──────────────────────────────────────────────────────
      { label:'Exit-Based Speed - All',    key:'net_exit_spd_all',   unit:'km/h', dec:2, note:'Exit-based mean speed (Sd field); count-weighted avg across sections' },
      { label:'Exit-Based Speed - Car',    key:'net_exit_spd_car',   unit:'km/h', dec:2, note:'Exit-based speed — car' },
      { label:'Exit-Based Speed - HOV Car',key:'net_exit_spd_hov',   unit:'km/h', dec:2, note:'Exit-based speed — HOV car' },
      { label:'Exit-Based Speed - Truck',  key:'net_exit_spd_truck', unit:'km/h', dec:2, note:'Exit-based speed — truck' },
      { label:'Exit-Based Speed - Std Bus',key:'net_exit_spd_bus',   unit:'km/h', dec:2, note:'Exit-based speed — bus' },
      // ── Stop Time ─────────────────────────────────────────────────────────────
      { label:'Stop Time - All',     key:'net_stop_time_all',   unit:'sec/km', dec:2, note:'Mean stop time per vehicle per km (entry-based STa/L_km); count-weighted avg' },
      { label:'Stop Time - Car',     key:'net_stop_time_car',   unit:'sec/km', dec:2, note:'Stop time — car' },
      { label:'Stop Time - Truck',   key:'net_stop_time_truck', unit:'sec/km', dec:2, note:'Stop time — truck' },
      { label:'Stop Time - Std Bus', key:'net_stop_time_bus',   unit:'sec/km', dec:2, note:'Stop time — bus' },
      // ── Number of Stops ───────────────────────────────────────────────────────
      { label:'Number of Stops - All',     key:'net_num_stops_all',   unit:'#/veh/km', dec:3, note:'Mean stops per vehicle per km (NumStops field); count-weighted avg' },
      { label:'Number of Stops - Car',     key:'net_num_stops_car',   unit:'#/veh/km', dec:3, note:'Stops — car' },
      { label:'Number of Stops - Truck',   key:'net_num_stops_truck', unit:'#/veh/km', dec:3, note:'Stops — truck' },
      { label:'Number of Stops - Std Bus', key:'net_num_stops_bus',   unit:'#/veh/km', dec:3, note:'Stops — bus' },
      // ── Total Distance Traveled ───────────────────────────────────────────────
      { label:'Total Distance - All',   key:'net_total_dist_all',   unit:'km',  dec:1, note:'Σ TotalTravel across sections — total vehicle-km traveled' },
      { label:'Total Distance - Car',   key:'net_total_dist_car',   unit:'km',  dec:1, note:'Total vehicle-km — car' },
      { label:'Total Distance - Bus',   key:'net_total_dist_bus',   unit:'km',  dec:1, note:'Total vehicle-km — bus' },
      { label:'Total Distance - Truck', key:'net_total_dist_truck', unit:'km',  dec:1, note:'Total vehicle-km — truck' },
      // ── Total Travel Time ─────────────────────────────────────────────────────
      { label:'Total Travel Time - All',   key:'net_total_tt_h_all',   unit:'veh·h', dec:2, note:'Σ TotalTravelTime/3600 across sections — total vehicle-hours' },
      { label:'Total Travel Time - Car',   key:'net_total_tt_h_car',   unit:'veh·h', dec:2, note:'Total vehicle-hours — car' },
      { label:'Total Travel Time - Bus',   key:'net_total_tt_h_bus',   unit:'veh·h', dec:2, note:'Total vehicle-hours — bus' },
      { label:'Total Travel Time - Truck', key:'net_total_tt_h_truck', unit:'veh·h', dec:2, note:'Total vehicle-hours — truck' },
      // ── Exit Count & Flow ─────────────────────────────────────────────────────
      { label:'Exit Count - All',    key:'net_exit_count_all',   unit:'veh',   dec:0, note:'Σ count across sections — total exit-based vehicle count' },
      { label:'Exit Count - Car',    key:'net_exit_count_car',   unit:'veh',   dec:0, note:'Exit count — car' },
      { label:'Exit Count - Bus',    key:'net_exit_count_bus',   unit:'veh',   dec:0, note:'Exit count — bus' },
      { label:'Exit Flow - All',     key:'net_exit_flow_all',    unit:'veh/h', dec:0, note:'Exit count / sim_h — exit-based flow' },
      { label:'Exit Flow - Car',     key:'net_exit_flow_car',    unit:'veh/h', dec:0, note:'Exit flow — car' },
      { label:'Input Flow - All',    key:'net_input_flow_all',   unit:'veh/h', dec:0, note:'Σ inputCount / sim_h — input flow rate' },
      { label:'Input Flow - Bus',    key:'net_input_flow_bus',   unit:'veh/h', dec:0, note:'Input flow — bus' },
      // ── Lane Changes ─────────────────────────────────────────────────────────
      { label:'Total Lane Changes - All',   key:'net_total_lc_all',   unit:'count', dec:0, note:'Σ totalLaneChanges across sections' },
      { label:'Total Lane Changes - Car',   key:'net_total_lc_car',   unit:'count', dec:0, note:'Lane changes — car' },
      { label:'Total Lane Changes - Truck', key:'net_total_lc_truck', unit:'count', dec:0, note:'Lane changes — truck' },
      // ── Queue Statistics ──────────────────────────────────────────────────────
      { label:'Mean Queue - All',    key:'net_mean_queue_all',   unit:'veh', dec:1, note:'Σ LongQueueAvg across sections — mean queued vehicles in network' },
      { label:'Mean Queue - Car',    key:'net_mean_queue_car',   unit:'veh', dec:1, note:'Mean queue — car' },
      { label:'Mean Queue - Bus',    key:'net_mean_queue_bus',   unit:'veh', dec:1, note:'Mean queue — bus' },
      { label:'Max Queue - All',     key:'net_max_queue_all',    unit:'veh', dec:1, note:'Σ LongQueueMax across sections' },
      { label:'Max Queue - Car',     key:'net_max_queue_car',    unit:'veh', dec:1, note:'Max queue — car' },
      { label:'Max Queue - Bus',     key:'net_max_queue_bus',    unit:'veh', dec:1, note:'Max queue — bus' },
      // ── Virtual Queue ─────────────────────────────────────────────────────────
      { label:'Virtual Queue Avg - All', key:'net_vq_avg_all',  unit:'veh', dec:1, note:'Σ virtualQueueAvg across sections' },
      { label:'Virtual Queue Avg - Bus', key:'net_vq_avg_bus',  unit:'veh', dec:1, note:'Virtual queue avg — bus' },
      { label:'Virtual Queue Max - All', key:'net_vq_max_all',  unit:'veh', dec:1, note:'Σ virtualQueueMax across sections' },
      { label:'Waiting Time in VQ - All',key:'net_wait_vq_all', unit:'sec', dec:1, note:'VQ-count-weighted avg waitingTimeVirtualQueue across sections' },
      { label:'Waiting Time in VQ - Bus',key:'net_wait_vq_bus', unit:'sec', dec:1, note:'VQ waiting time — bus' },
      // ── Entry-Based Flow ──────────────────────────────────────────────────────
      { label:'Entry-Based Flow - All',     key:'flow',           unit:'veh/h',  dec:0, note:_ref2('flow_all','veh/h') },
      { label:'Entry-Based Flow - Car',     key:'net_flow_car',   unit:'veh/h',  dec:0, note:_ref2('flow_car','veh/h') },
      { label:'Entry-Based Flow - HOV Car', key:'net_flow_hov',   unit:'veh/h',  dec:0, note:_ref2('flow_hov','veh/h') },
      { label:'Entry-Based Flow - Truck',   key:'net_flow_truck', unit:'veh/h',  dec:0, note:_ref2('flow_truck','veh/h') },
      { label:'Entry-Based Flow - Std Bus', key:'net_flow_bus',   unit:'veh/h',  dec:0, note:_ref2('flow_bus','veh/h') },
      // ── Entry-Based Speed ─────────────────────────────────────────────────────
      { label:'Entry-Based Speed - All',    key:'speed',          unit:'km/h',   dec:2, note:_ref2('speed_all','km/h') },
      { label:'Entry-Based Speed - Car',    key:'net_spd_car',    unit:'km/h',   dec:2, note:_ref2('speed_car','km/h') },
      { label:'Entry-Based Speed - HOV Car',key:'net_spd_hov',    unit:'km/h',   dec:2, note:_ref2('speed_hov','km/h') },
      { label:'Entry-Based Speed - Truck',  key:'net_spd_truck',  unit:'km/h',   dec:2, note:_ref2('speed_truck','km/h') },
      { label:'Entry-Based Speed - Std Bus',key:'net_spd_bus',    unit:'km/h',   dec:2, note:_ref2('speed_bus','km/h') },
      // ── GE / INS event counts (from detection_points CSV) ────────────────────
      { label:'TSP GE Extensions (count)',  key:'tsp_ext',        unit:'events', dec:0, note:'Count of harmony-ge-local actions from detection_points CSV' },
      { label:'TSP Insertions (count)',     key:'tsp_ins',        unit:'events', dec:0, note:'Count of harmony-ins-local actions from detection_points CSV' },
      { label:'TSP Detections (count)',     key:'tsp_det',        unit:'events', dec:0, note:'Count of IC-detect events (bus arrivals in detection zone)' },
      { label:'Mean Green (bus phase %)',   key:'mean_green',     unit:'%',      dec:1, note:'Average % time bus phase is green across monitored junctions' },
      // ── Total pax delay — from per-type delay × distance × occupancy ─────────
      // NO_TSP computed: bus=130.5 pax-h + car=224.4 + hov=284.4 + truck=10.7 = ~650 pax-h total
      // Requires Aimsun statistics enabled; entry_delay(s/km)×distance(km)×occupancy
      { label:'Avg Bus Pax Delay',          key:'avg_bus_delay',  unit:'s/pax',  dec:2, note:'bus pax·s ÷ bus passages — requires Aimsun stats collection (N/A if stats disabled)' },
      { label:'Avg Car Pax Delay',          key:'avg_car_delay',  unit:'s/pax',  dec:2, note:'car pax·s ÷ car passages — requires Aimsun stats collection (N/A if stats disabled)' },
      { label:'Total Pax Delay — corridor', key:'total_delay',    unit:'pax·h',  dec:3, note:`Total pax delay from car/bus/truck delay×distance×occ. NO_TSP ref: ${noTspTotalPaxDelay_h.toFixed(1)} pax-h. Requires Aimsun stats.` },
      { label:'Main-street Pax Delay',      key:'main_delay',     unit:'pax·h',  dec:3, note:'bus-approach sections only (corridor-monitored subset)' },
      { label:'Side-street Pax Delay',      key:'side_delay',     unit:'pax·h',  dec:3, note:'cross-street sections' },
    ];

    const runCols = runs.map(r => r.label);
    const hrow = document.createElement('tr');
    const thStat = document.createElement('th'); thStat.textContent = 'Statistic'; hrow.appendChild(thStat);
    const thUnit = document.createElement('th'); thUnit.textContent = 'Units';     hrow.appendChild(thUnit);
    runCols.forEach(lbl => {
      const th = document.createElement('th'); th.textContent = lbl; hrow.appendChild(th);
    });
    const thNote = document.createElement('th'); thNote.textContent = 'Notes'; hrow.appendChild(thNote);
    thead.appendChild(hrow);

    AIMSUN_ROWS.forEach(row => {
      const tr = document.createElement('tr');
      const tdLabel = document.createElement('td');
      tdLabel.textContent = row.label;
      tdLabel.style.fontWeight = '500';
      tr.appendChild(tdLabel);
      const tdUnit = document.createElement('td');
      tdUnit.textContent = row.unit;
      tdUnit.style.color = 'var(--muted)';
      tr.appendChild(tdUnit);
      // Find best/worst across runs
      const vals = runs.map(r => {
        const v = r[row.key];
        return (v !== null && v !== undefined) ? Number(v) : null;
      });
      const numVals = vals.filter(v => v !== null);
      // For delay/density metrics lower is better; for speed/flow higher is better
      const lowerBetter = [
        'avg_car_delay','avg_bus_delay','total_delay','main_delay','side_delay','density','density_all',
        'net_dens_car','net_dens_bus','net_dens_truck',
        'net_delay_all','net_delay_car','net_delay_bus','net_delay_truck',
        'net_entry_delay_all','net_entry_delay_car','net_entry_delay_bus','net_entry_delay_truck',
        'net_exit_delay_all','net_exit_delay_car','net_exit_delay_bus','net_exit_delay_truck',
        'net_entry_tt_all','net_entry_tt_car','net_entry_tt_bus','net_entry_tt_hov','net_entry_tt_truck',
        'net_exit_tt_all','net_exit_tt_car','net_exit_tt_bus','net_exit_tt_hov','net_exit_tt_truck',
        'net_stop_time_all','net_stop_time_car','net_stop_time_bus','net_stop_time_truck',
        'net_num_stops_all','net_num_stops_car','net_num_stops_bus','net_num_stops_truck',
        'net_mean_queue_all','net_mean_queue_car','net_mean_queue_bus','net_mean_queue_truck',
        'net_max_queue_all','net_max_queue_car','net_max_queue_bus','net_max_queue_truck',
        'net_vq_avg_all','net_vq_avg_bus','net_vq_max_all',
        'net_wait_vq_all','net_wait_vq_bus',
        'net_total_tt_h_all','net_total_tt_h_car','net_total_tt_h_bus','net_total_tt_h_truck',
      ].includes(row.key);
      const best  = numVals.length ? (lowerBetter ? Math.min(...numVals) : Math.max(...numVals)) : null;
      const worst = numVals.length ? (lowerBetter ? Math.max(...numVals) : Math.min(...numVals)) : null;

      vals.forEach(v => {
        const td = document.createElement('td');
        if (v === null) {
          td.textContent = 'N/A';
          td.style.color = 'var(--muted)';
        } else {
          td.textContent = v.toFixed(row.dec);
          if (v === best)  { td.classList.add('best'); }
          if (v === worst) { td.classList.add('worst'); }
        }
        tr.appendChild(td);
      });
      const tdNote = document.createElement('td');
      tdNote.textContent = row.note || '';
      tdNote.style.color = 'var(--muted)';
      tdNote.style.fontSize = '11px';
      tr.appendChild(tdNote);
      tbody.appendChild(tr);
    });
  }
}

// ── Results table ─────────────────────────────────────────────────────────
{
  const table = document.getElementById('results-table');
  const thead = table.querySelector('thead');
  const tbody = table.querySelector('tbody');

  const cols = [
    {key:'label',       hdr:'Run'},
    {key:'strategy',    hdr:'Strategy'},
    {key:'coordinated', hdr:'Coord?'},
    {key:'seed',        hdr:'Seed'},
    {key:'total_delay', hdr:'Total pax (hrs)', lb:true},
    {key:'main_delay',  hdr:'Main (hrs)',       lb:true},
    {key:'side_delay',  hdr:'Side (hrs)',       lb:true},
    {key:'bus_tt',      hdr:'Bus TT (hrs)',     lb:true},
    {key:'avg_bus_delay',  hdr:'Avg bus (s)',   lb:true},
    {key:'avg_car_delay',  hdr:'Avg car (s)',   lb:true},
    {key:'avg_truck_delay',hdr:'Avg truck (s)', lb:true},
    {key:'tracked_bus_count', hdr:'Position-tracked buses (unique)', lb:false},
    {key:'tsp_det_bus_count', hdr:'TSP-detected buses (unique)', lb:false},
    {key:'tracked_only_bus_count', hdr:'Pos-tracked only (not TSP-detected)', lb:true},
    {key:'tracking_coverage_pct', hdr:'TSP coverage of pos-tracked (%)', lb:false},
    {key:'focus_bus_count', hdr:'Focus (global-tracked) buses', lb:false},
    {key:'tsp_det_unique',   hdr:'Proximity detections unique (bus×jct)', lb:false},
    {key:'tsp_det_max_pairs',hdr:'Max possible bus×jct pairs',    lb:false},
    {key:'tsp_det',          hdr:'TSP trigger events (raw)',       lb:false},
    {key:'tsp_green_unique', hdr:'Green arrivals unique (bus×jct)',      lb:false},
    {key:'tsp_nongreen_unique', hdr:'Non-green arrivals unique (bus×jct)', lb:false},
    {key:'tsp_ext',          hdr:'Extensions (raw)',            lb:false},
    {key:'tsp_ins',          hdr:'Insertions (raw)',            lb:false},
    {key:'tsp_natural_green',hdr:'Natural green (raw)',         lb:false},
    {key:'tsp_natural_green_rate_pct',hdr:'Natural green % (unique)', lb:false},
    {key:'avg_extension_s', hdr:'Avg GE (s)',             lb:false},
    {key:'avg_insertion_s', hdr:'Avg INS (s)',            lb:false},
    {key:'avg_insertion_wait_s', hdr:'Avg INS lead (s)',  lb:false},
    {key:'tsp_skip_ge',      hdr:'GE skipped (raw diag)',       lb:false},
    {key:'tsp_skip_ins',     hdr:'INS skipped (raw diag)',      lb:false},
    {key:'tsp_no_action',    hdr:'No action (raw diag)',        lb:false},
    {key:'mean_green',       hdr:'Mean green %',            lb:false},
    {key:'flow',             hdr:'Flow (veh/h)',             lb:false},
    {key:'density',          hdr:'Density (veh/km/lane)',          lb:true},
    {key:'speed',            hdr:'Speed (km/h)',             lb:false},
    {key:'prearm_fired',     hdr:'Prearm fired',             lb:false},
    {key:'prearm_success',   hdr:'Prearm success',           lb:false},
    {key:'prearm_success_rate_pct', hdr:'Prearm success %',  lb:false},
    {key:'prearm_late_success', hdr:'Prearm late success',   lb:false},
    {key:'prearm_late_delay_s', hdr:'Prearm late delay (s)', lb:false},
    {key:'prearm_missed',    hdr:'Prearm missed',            lb:false},
    {key:'prearm_expired',   hdr:'Prearm expired',           lb:false},
    {key:'prearm_discarded', hdr:'Prearm discarded',         lb:false},
    {key:'elapsed',          hdr:'Run time (s)'},
    {key:'success',          hdr:'OK?'},
  ];

  // Header
  const hrow = document.createElement('tr');
  cols.forEach(c => { const th=document.createElement('th'); th.textContent=c.hdr; hrow.appendChild(th); });
  thead.appendChild(hrow);

  // Column bests/worsts
  const bests = {};
  cols.forEach(c => {
    if (c.lb === undefined) return;
    const vals = runs.map(r=>r[c.key]).filter(v=>typeof v==='number'&&!isNaN(v));
    if (!vals.length) return;
    bests[c.key] = {
      best:  c.lb ? Math.min(...vals) : Math.max(...vals),
      worst: c.lb ? Math.max(...vals) : Math.min(...vals),
    };
  });

  runs.forEach(r => {
    const tr = document.createElement('tr');
    cols.forEach(c => {
      const td = document.createElement('td');
      const v  = r[c.key];
      if (c.key === 'coordinated') {
        td.innerHTML = v
          ? '<span class="tag tag-coord">Coord</span>'
          : '<span class="tag tag-indep">Indep</span>';
      } else if (c.key === 'success') {
        td.textContent = v ? '✓' : '✗';
        td.style.color = v ? 'var(--green)' : 'var(--red)';
      } else if (typeof v === 'number' && bests[c.key]) {
        const decimals = Number.isInteger(v) ? 0 : 2;
        let txt = v.toFixed(decimals);
        // Append delta vs normal if available
        const dv = r.delta && r.delta[c.key] !== undefined ? r.delta[c.key] : null;
        const deltaHtml = dv !== null
          ? ` <span class="${dv>0?'delta-pos':dv<0?'delta-neg':'delta-na'}">${dv>0?'+':''}${dv}%</span>`
          : '';
        td.innerHTML = txt + deltaHtml;
        if (v === bests[c.key].best)  td.classList.add('best');
        if (v === bests[c.key].worst) td.classList.add('worst');
      } else {
        td.textContent = v !== null && v !== undefined ? v : '—';
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}
</script>
</body>
</html>
"""


# =============================================================================
# Main entry point
# =============================================================================

def _build_static_fallback_html(data: dict) -> str:
  """
  Build a server-rendered fallback block so the dashboard still shows core
  run data when JavaScript is disabled or blocked.
  """
  runs = data.get("runs") or []
  if not runs:
    return (
      '<div class="card" style="margin-bottom:12px">'
      '<h2>Static Summary</h2>'
      '<div style="font-size:12px;color:#b08080">No run rows available.</div>'
      '</div>'
    )

  rows = []
  for r in runs:
    label = _html.escape(str(r.get("label", "—")))
    strategy = _html.escape(str(r.get("strategy", "—")))
    coordinated = "Coord" if r.get("coordinated") else "Indep"

    def _fmt_num(v, dec=1):
      try:
        return f"{float(v):.{dec}f}"
      except Exception:
        return "—"

    rows.append(
      "<tr>"
      f"<td>{label}</td>"
      f"<td>{strategy}</td>"
      f"<td>{coordinated}</td>"
      f"<td>{_fmt_num(r.get('total_delay'), 1)}</td>"
      f"<td>{_fmt_num(r.get('avg_bus_delay'), 1)}</td>"
      f"<td>{_fmt_num(r.get('mean_green'), 1)}</td>"
      f"<td>{_fmt_num(r.get('flow'), 0)}</td>"
      "</tr>"
    )

  return (
    '<div class="card" style="margin-bottom:12px">'
    '<h2>Static Summary (No JavaScript Required)</h2>'
    '<div style="font-size:11px;color:var(--muted);margin-bottom:8px">'
    'If charts are blank, this confirms the dashboard data is present.'
    '</div>'
    '<div class="tbl-wrap">'
    '<table><thead><tr>'
    '<th>Run</th><th>Strategy</th><th>Mode</th>'
    '<th>Total Delay (hrs)</th><th>Bus Delay (s)</th><th>Mean Green (%)</th><th>Flow (veh/h)</th>'
    '</tr></thead><tbody>'
    + "".join(rows) +
    '</tbody></table></div></div>'
  )

def generate(batch_csv: str = None, out_html: str = None,
             log_dir: str = None) -> str:
    """
    Generate and write the HTML dashboard.
    Returns the output path, or None on failure.
    """
    if log_dir is None:
        log_dir = os.path.join(_SCRIPT_DIR, "logs")

    if batch_csv is None:
        for candidate in [
            os.path.join(_SCRIPT_DIR, "batch_results.csv"),
            os.path.join(log_dir, "batch_results.csv"),
        ]:
            if os.path.isfile(candidate):
                batch_csv = candidate
                break

    if batch_csv is None or not os.path.isfile(batch_csv):
        print("[dashboard] No batch_results.csv found. "
              "Run batch_runner.py first, or pass path explicitly.")
        return None

    batch_rows = _read_batch_csv(batch_csv)
    if not batch_rows:
        print(f"[dashboard] batch_results.csv is empty: {batch_csv}")
        return None

    print(f"[dashboard] {len(batch_rows)} raw row(s) from {batch_csv}")

    data = build_dashboard_data(batch_rows, log_dir)
    print(f"[dashboard] {len(data['runs'])} unique experiment(s) after dedup")

    if out_html is None:
        out_html = os.path.join(os.path.dirname(batch_csv), "tsp_dashboard.html")

    html = _HTML_TEMPLATE.replace("TEMPLATE_DATA_JSON", json.dumps(data, indent=2))
    html = html.replace("TEMPLATE_FALLBACK_HTML", _build_static_fallback_html(data))

    out_dir = os.path.dirname(out_html)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[dashboard] HTML dashboard -> {out_html}")
    print(f"[dashboard] Open in browser: file://{os.path.abspath(out_html)}")
    return out_html


if __name__ == "__main__":
    import argparse, subprocess
    ap = argparse.ArgumentParser(
        description="Generate HTML comparison dashboard from batch_results.csv")
    ap.add_argument("batch_csv", nargs="?", help="batch_results.csv path")
    ap.add_argument("out_html",  nargs="?", help="output HTML path")
    ap.add_argument("--log_dir", default=None, help="logs/ directory")
    args = ap.parse_args()
    main_html = generate(args.batch_csv, args.out_html, args.log_dir)

    # ── Auto-run companion plots ────────────────────────────────────────────
    _batch = args.batch_csv or os.path.join(_SCRIPT_DIR, "batch_results.csv")
    _logs  = args.log_dir   or os.path.join(_SCRIPT_DIR, "logs")
    for _script, _extra_args in [
        ("plot_saturation.py",    [_batch, os.path.join(_SCRIPT_DIR, "saturation_mfd.html")]),
        ("plot_signal_timing.py", [_logs,  os.path.join(_SCRIPT_DIR, "signal_timing_diagram.html")]),
    ]:
        _path = os.path.join(_SCRIPT_DIR, _script)
        if not os.path.isfile(_path):
            continue
        try:
            import sys as _sys
            _r = subprocess.run(
                [_sys.executable, _path] + _extra_args,
                capture_output=True, text=True, timeout=60)
            if _r.returncode == 0:
                print(f"[dashboard] {_script}: {_r.stdout.strip()}")
            else:
                print(f"[dashboard] {_script} error: {_r.stderr.strip()[:200]}")
        except Exception as _e:
            print(f"[dashboard] {_script} skipped: {_e}")
