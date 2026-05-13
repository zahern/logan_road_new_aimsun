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
    Keep only the LAST (most recent) row per run_experiment name.
    batch_results.csv accumulates rows across multiple batch_runner sessions;
    showing all of them creates a cluttered 26-bar chart instead of 6.
    """
    seen: dict = {}
    for row in batch_rows:
        exp = row.get("run_experiment") or row.get("run_strategy", "UNKNOWN")
        seen[exp] = row   # later rows overwrite earlier -> keep last
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
        return []

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
        avg_car_delay   = _pick(row, ["stats_AvgCarPassDelay_s",
                                      "inter_avg_AvgCarPassDelay_s"])
        avg_truck_delay = _pick(row, ["stats_AvgTruckPassDelay_s",
                                      "inter_avg_AvgTruckPassDelay_s"])
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
        sim_row = _load_simulation_results_row(row, log_dir)

        # Network stats — prefer batch_results values, then per-run simulation_results.csv,
        # then older PyANGKernel fallback keys.
        density = _first_valid_metric(
            _pick(row, ["stats_Net_AvgDensity_vkm", "aimsun_avg_density_vkm"]),
            _pick(sim_row, ["Net_AvgDensity_vkm"]),
            allow_zero=False,
        )
        speed = _first_valid_metric(
            _pick(row, ["stats_Net_AvgSpeed_kmh", "aimsun_avg_speed_kmh"]),
            _pick(sim_row, ["Net_AvgSpeed_kmh"]),
            allow_zero=False,
        )
        flow = _first_valid_metric(
            _pick(row, ["stats_Net_TotalFlowVeh", "aimsun_total_flow_veh"]),
            _pick(sim_row, ["Net_TotalFlowVeh"]),
            allow_zero=False,
        )
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
        net_delay_all = _first_valid_metric(
            _pick(row, ["stats_Net_Delay_All", "aimsun_avg_delay_s_km"]),
            _pick(sim_row, ["Net_Delay_All"]),
            allow_zero=False,
        )
        net_delay_car = _first_valid_metric(
            _pick(row, ["stats_Net_Delay_Car", "aimsun_delay_car"]),
            _pick(sim_row, ["Net_Delay_Car"]),
            allow_zero=False,
        )
        net_delay_bus = _first_valid_metric(
            _pick(row, ["stats_Net_Delay_Bus", "aimsun_delay_bus"]),
            _pick(sim_row, ["Net_Delay_Bus"]),
            allow_zero=False,
        )
        net_delay_truck = _first_valid_metric(
            _pick(row, ["stats_Net_Delay_Truck", "aimsun_delay_truck"]),
            _pick(sim_row, ["Net_Delay_Truck"]),
            allow_zero=False,
        )

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
            "avg_bus_delay":   _rnd(avg_bus_delay,   2),
            "avg_car_delay":   _rnd(avg_car_delay,   2),
            "avg_truck_delay":        _rnd(avg_truck_delay,       2),
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
            # continuous bus position tracking (list of {t,vid,x,y,jct,dist,in_zone,zone_r,event})
            "bus_tracking": bus_tracking,
            # focus priority history (list of {start_t, end_t, veh_id, jct_id, outcome, held_s})
            "focus_history": focus_history,
            "focus_bus_ids": sorted(focus_bus_ids),
            # queue snapshots (list of {t, jct, buses_in_zone, queue_main, queue_side, queue_total, tsp_state})
            "queue_snapshots": queue_snapshots,
            # DYNAOPAC decisions (list of {t, jct, before_dur, extensions, delays, best_ext, applied, ...})
            "dynaropac_decisions": dynaropac_decisions,
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
                        "avg_bus_delay", "avg_car_delay", "avg_truck_delay", "density",
                        "net_delay_all", "net_delay_car", "net_delay_bus", "net_delay_truck",
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

<!-- ── Charts row 1: Delays ──────────────────────────────────────────── -->
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
  </div>
  <div class="card">
    <h2>Per-Passenger Delays (seconds)</h2>
    <canvas id="chart-delay-s" height="240"></canvas>
  </div>
</div>

<!-- ── Charts row 2: Delta vs NORMAL ─────────────────────────────────── -->
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
    <h3 style="font-size:13px;color:var(--muted);margin:0 0 6px">Per-Bus Corridor Delay Comparison (stops at red × 30 s estimate)</h3>
    <div style="font-size:11px;color:var(--muted);margin-bottom:6px">
      Each bar = estimated total delay for one bus journey (number of red-phase arrivals × 30 s).
      Lower = fewer red arrivals. Saving lines (right axis) show delay saved vs No-TSP baseline.
    </div>
    <canvas id="xcomp-delay-canvas" height="200" style="width:100%;min-width:420px;display:none"></canvas>
    <div id="xcomp-delay-no-data" style="font-size:11px;color:var(--muted);display:none"></div>
  </div>
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

// ── Delay chart (hrs) ────────────────────────────────────────────────────
barChart('chart-delay-hrs',
  ['Total pax delay', 'Main-street delay', 'Side-street delay'],
  runs.map((r,i) => ({
    label: r.label,
    data: [r.total_delay, r.main_delay, r.side_delay],
    backgroundColor: color(i), borderColor: colorEdge(i), borderWidth:1,
  }))
);

// ── Per-passenger delays (seconds) ───────────────────────────────────────
barChart('chart-delay-s',
  ['Avg bus delay (s)', 'Avg car delay (s)'],
  runs.map((r,i) => ({
    label: r.label,
    data: [r.avg_bus_delay, r.avg_car_delay],
    backgroundColor: color(i), borderColor: colorEdge(i), borderWidth:1,
  }))
);

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

    buildRunTabs('noaction-run-tabs', (i) => renderNoActionReasons(i));
    renderNoActionReasons(initialRunIdx);
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
      const nActions = (r.phase_samples || []).filter(p =>
        Number(p.vid) === Number(j.vid)
        && (p.tier === 'harmony-ge-local' || p.tier === 'harmony-ins-local')
        && p.prearm_status === 'action'
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

    // ── Per-junction decision data from phase_samples ────────────────────
    // Build a lookup: jct -> list of harmony decision rows for this bus,
    // sorted by sim time so we can find the latest decision before arrival.
    const decisionsByJct = {};
    (r.phase_samples || []).forEach(p => {
      if (Number(p.vid) !== Number(journey.vid)) return;
      if (typeof p.tier !== 'string' || !p.tier.startsWith('harmony-')) return;
      const key = String(p.jct);
      if (!decisionsByJct[key]) decisionsByJct[key] = [];
      decisionsByJct[key].push(p);
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
        : (jDecisions.length ? jDecisions[jDecisions.length - 1] : null);

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
          // Start time label above left border
          coordExCtx.fillStyle = isIns ? '#00bcd4' : '#2ecc71';
          coordExCtx.font = 'bold 9px system-ui';
          coordExCtx.textAlign = 'left';
          coordExCtx.textBaseline = 'bottom';
          coordExCtx.fillText((isIns ? 'INS ▶' : 'GE ▶') + fmtT(dt), wx0 + 2, midY - bandH/2 - 1);
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
          if (dTier === 'harmony-ge-local')  { decLabel = '→ GE applied'; decColor = '#2ecc71'; }
          else if (dTier === 'harmony-ins-local') { decLabel = '→ INS applied'; decColor = '#00bcd4'; }
          else if (dTier === 'harmony-no-ge-local')  {
            const reason = _decisionReasonText(_decisionReasonToken(dn, 'NO_GE '), true);
            decLabel = 'no GE: ' + reason.substring(0, 46);
            decColor = '#f1c40f';
          } else if (dTier === 'harmony-no-ins-local') {
            const reason = _decisionReasonText(_decisionReasonToken(dn, 'NO_INS '), false);
            decLabel = 'no INS: ' + reason.substring(0, 46);
            decColor = '#e67e22';
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
            : 'arrived on red; no controller decision row found';
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
        // Approximate delay: junctions arrived on red (not on_green)
        totalDelay += stops.filter(s => !s.on_green).length * 30; // rough 30s per red arrival
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
  const coordRun  = runs.find(r => r.coordinated === true && r !== noTspRun);
  const indepRun  = runs.find(r => r.coordinated === false && r !== noTspRun);
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

    const xcompLabels  = [];
    const noTspTTArr   = [];
    const indepTTArr   = [];
    const coordTTArr   = [];
    const ttSavCoordArr = [];  // noTsp_TT - coord_TT  (positive = coord faster)
    const ttSavIndepArr = [];  // noTsp_TT - indep_TT

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

      const indepTT = _journeyTT(indepJMap[vid]);  // may be null if bus not seen

      xcompLabels.push(`Bus ${vid}`);
      noTspTTArr.push(Math.max(0, noTspTT));
      coordTTArr.push(Math.max(0, coordTT));
      indepTTArr.push(indepTT !== null ? Math.max(0, indepTT) : null);
      ttSavCoordArr.push(Math.round(noTspTT - coordTT));
      ttSavIndepArr.push(indepTT !== null ? Math.round(noTspTT - indepTT) : null);
    });

    const nLabel = noTspRun.label  || 'No TSP';
    const cLabel = coordRun.label  || 'Coordinated';
    const iLabel = indepRun ? (indepRun.label || 'Uncoordinated') : 'Uncoordinated';

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
              text: `Buses granted GE/INS in ${cLabel} run — corridor TT across all runs (${xcompLabels.length} buses)`,
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
      noDataEl.textContent = `No buses found that were granted GE/INS in the ${cLabel} run.`;
    }

    // ── Delay comparison chart (same bus set, red-stop estimate) ──────────
    // Delay proxy: n_red_stops × 30s  (same approach as buscomp "red arrivals")
    const delayCtxEl  = document.getElementById('xcomp-delay-canvas');
    const delayNoData = document.getElementById('xcomp-delay-no-data');

    function _busDelay(journeyMap, vid) {
      const j = journeyMap[vid];
      if (!j) return null;
      const reds = (j.stops || []).filter(s => !s.on_green).length;
      return reds * 30;   // s  (rough 30s per red-phase arrival)
    }

    if (xcompLabels.length && delayCtxEl) {
      const noTspDelArr   = xcompLabels.map((_, i) => { const vid = [...grantedVids][i]; return _busDelay(noTspJMap, vid); });
      const coordDelArr   = xcompLabels.map((_, i) => { const vid = [...grantedVids][i]; return _busDelay(coordJMap, vid); });
      const indepDelArr   = xcompLabels.map((_, i) => { const vid = [...grantedVids][i]; return _busDelay(indepJMap, vid); });
      const delSavCoord   = noTspDelArr.map((d, i) => d !== null && coordDelArr[i] !== null ? Math.round(d - coordDelArr[i]) : null);
      const delSavIndep   = noTspDelArr.map((d, i) => d !== null && indepDelArr[i] !== null ? Math.round(d - indepDelArr[i]) : null);

      delayCtxEl.style.display = '';
      if (delayNoData) delayNoData.style.display = 'none';
      new Chart(delayCtxEl.getContext('2d'), {
        type: 'bar',
        data: {
          labels: xcompLabels,
          datasets: [
            { label: `${nLabel} — est. delay (s)`,   data: noTspDelArr,  backgroundColor: 'rgba(255,82,82,0.7)',  yAxisID: 'y' },
            { label: `${iLabel} — est. delay (s)`,   data: indepDelArr,  backgroundColor: 'rgba(255,179,0,0.7)',  yAxisID: 'y' },
            { label: `${cLabel} — est. delay (s)`,   data: coordDelArr,  backgroundColor: 'rgba(41,182,246,0.7)', yAxisID: 'y' },
            { label: `Delay saving: ${cLabel} vs ${nLabel} (s)`, data: delSavCoord, backgroundColor: 'rgba(0,230,118,0.6)', yAxisID: 'y2', borderWidth: 1, borderColor: 'rgba(0,230,118,0.9)' },
            { label: `Delay saving: ${iLabel} vs ${nLabel} (s)`, data: delSavIndep, backgroundColor: 'rgba(255,235,59,0.4)', yAxisID: 'y2', borderWidth: 1, borderColor: 'rgba(255,235,59,0.8)' },
          ],
        },
        options: {
          responsive: true,
          animation: false,
          plugins: {
            legend: { labels: { color: '#9090cc', font: { size: 10 } } },
            tooltip: { backgroundColor: '#0a0a22', titleColor: '#ccccee', bodyColor: '#9090cc', borderColor: '#2a2a50', borderWidth: 1 },
            title: {
              display: true,
              text: `Same buses — estimated corridor delay (red-stop × 30s proxy, ${xcompLabels.length} buses)`,
              color: '#7070a0', font: { size: 11 },
            },
          },
          scales: {
            x:  { ticks: { color: '#9090cc', maxRotation: 60 }, grid: { color: '#1e1e38' } },
            y:  { ticks: { color: '#9090cc' }, grid: { color: '#1e1e38' }, title: { display: true, text: 'Est. delay (s)', color: '#7070a0' }, min: 0 },
            y2: { position: 'right', ticks: { color: '#00e676' }, grid: { display: false }, title: { display: true, text: 'Delay saving vs baseline (s)', color: '#00e676' } },
          },
        },
      });
    }
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
    const AIMSUN_ROWS = [
      // ── Density (veh/km/lane) — Aimsun network density is per kilometer of lane ──
      { label:'Density - All',              key:'density',        unit:'veh/km/lane', dec:2, note:'Aimsun network density; NORMAL ref: 24.05' },
      { label:'Density - Car',              key:'net_dens_car',   unit:'veh/km/lane', dec:2, note:'Aimsun network density by type; NORMAL ref: 23.15' },
      { label:'Density - Truck',            key:'net_dens_truck', unit:'veh/km/lane', dec:2, note:'Aimsun network density by type; NORMAL ref: 0.62' },
      { label:'Density - Std Bus',          key:'net_dens_bus',   unit:'veh/km/lane', dec:2, note:'Aimsun network density by type; NORMAL ref: 0.29' },
      // ── Entry-Based Delay Time — average delay per vehicle per kilometer; excludes virtual queue ──
      { label:'Entry-Based Delay Time - All',      key:'net_delay_all',   unit:'sec/km', dec:2, note:'Aimsun entry-based delay; excludes virtual queue. NORMAL ref: 247.76' },
      { label:'Entry-Based Delay Time - Car',      key:'net_delay_car',   unit:'sec/km', dec:2, note:'Aimsun entry-based delay by type. NORMAL ref: 248.40' },
      { label:'Entry-Based Delay Time - Truck',    key:'net_delay_truck', unit:'sec/km', dec:2, note:'Aimsun entry-based delay by type. NORMAL ref: 246.31' },
      { label:'Entry-Based Delay Time - Std Bus',  key:'net_delay_bus',   unit:'sec/km', dec:2, note:'Aimsun entry-based delay by type. NORMAL ref: 194.07' },
      // ── Entry-Based Flow — vehicles that entered during the interval, with Aimsun including vehicles still inside at interval end ──
      { label:'Entry-Based Flow - All',     key:'flow',           unit:'veh/h',  dec:0, note:'Aimsun entry-based flow. NORMAL ref: 10946' },
      { label:'Entry-Based Flow - Car',     key:'net_flow_car',   unit:'veh/h',  dec:0, note:'Aimsun entry-based flow by type. NORMAL ref: 10521' },
      { label:'Entry-Based Flow - Truck',   key:'net_flow_truck', unit:'veh/h',  dec:0, note:'Aimsun entry-based flow by type. NORMAL ref: 298' },
      { label:'Entry-Based Flow - Std Bus', key:'net_flow_bus',   unit:'veh/h',  dec:0, note:'Aimsun entry-based flow by type. NORMAL ref: 127' },
      // ── Entry-Based Speed — total distance travelled divided by total travel time ──
      { label:'Entry-Based Speed - All',    key:'speed',          unit:'km/h',   dec:2, note:'Aimsun entry-based speed. NORMAL ref: 6.15' },
      { label:'Entry-Based Speed - Car',    key:'net_spd_car',    unit:'km/h',   dec:2, note:'Aimsun entry-based speed by type. NORMAL ref: 6.14' },
      { label:'Entry-Based Speed - Truck',  key:'net_spd_truck',  unit:'km/h',   dec:2, note:'Aimsun entry-based speed by type. NORMAL ref: 6.61' },
      { label:'Entry-Based Speed - Std Bus',key:'net_spd_bus',    unit:'km/h',   dec:2, note:'Aimsun entry-based speed by type. NORMAL ref: 5.51' },
      // ── Pax-weighted delay (s/pax) — different from Aimsun sec/km ─────────
      { label:'Avg Bus Pax Delay',          key:'avg_bus_delay',  unit:'s/pax',  dec:2, note:'bus pax·s ÷ bus passengers — NOT sec/km' },
      { label:'Avg Car Pax Delay',          key:'avg_car_delay',  unit:'s/pax',  dec:2, note:'car pax·s ÷ car passengers — NOT sec/km' },
      { label:'Avg Truck Pax Delay',        key:'avg_truck_delay',unit:'s/pax',  dec:2, note:'truck pax·s ÷ truck passengers' },
      { label:'Bus Total Travel Time',      key:'bus_tt',         unit:'h',      dec:3, note:'bus TT across monitored sections' },
      { label:'Total Pax Delay — corridor', key:'total_delay',    unit:'pax·h',  dec:3, note:'occupancy-weighted (car×1.2 + bus×40)' },
      { label:'Main-street Pax Delay',      key:'main_delay',     unit:'pax·h',  dec:3, note:'bus-approach sections' },
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
        'avg_car_delay','avg_bus_delay','total_delay','main_delay','side_delay','density',
        'net_dens_car','net_dens_bus','net_dens_truck',
        'net_delay_all','net_delay_car','net_delay_bus','net_delay_truck'
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
      f"<td>{_fmt_num(r.get('bus_delay'), 1)}</td>"
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
    import argparse
    ap = argparse.ArgumentParser(
        description="Generate HTML comparison dashboard from batch_results.csv")
    ap.add_argument("batch_csv", nargs="?", help="batch_results.csv path")
    ap.add_argument("out_html",  nargs="?", help="output HTML path")
    ap.add_argument("--log_dir", default=None, help="logs/ directory")
    args = ap.parse_args()
    generate(args.batch_csv, args.out_html, args.log_dir)
