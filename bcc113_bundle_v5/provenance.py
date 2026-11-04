"""provenance.py -- trust labels for every Aimsun results row.

Two problems made the 2026-10-30 ladder CSV untrustworthy:

1. `stats_ExperimentID` / `stats_ScenarioID` / `stats_ReplicationID` were
   constant across all 30 rows. That is not a bug in the sense of wrong data:
   they come from `ANGConnGet*Id()`, i.e. the MODEL's ids, and every arm/seed
   re-runs the SAME replication with a new random seed. But a reader cannot tell
   that from the file, so adjacent rows look like duplicates. `IdScope=model`
   plus a per-run UTC stamp and the applied seed make each row identifiable.

2. Every `stats_Net_*` and `aimsun_*` aggregate was exactly 0.0, because the
   network-scope collectors returned no usable section state (0 of 217 sections
   in `aimsun_flow_sections_ok`). A 0.0 there means "not measured", NOT "zero
   delay"; averaging it fabricated a result. Those columns are now written as
   NaN and the scope is flagged, so pandas skips them instead of treating them
   as zeros.

Use `stamp_row(dict)` before writing a results row. Pure stdlib, no Aimsun
imports, so it is unit-testable outside the simulator.
"""
from __future__ import annotations

import datetime
import math
import os


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def _any_positive(row, keys):
    for k in keys:
        v = _num(row.get(k))
        if v is not None and v > 0.0:
            return True
    return False


# Keys that prove the network-scope collector actually measured something.
NET_PROBES = ("stats_Net_Delay_All", "stats_Net_TotalTT_h_All",
              "stats_Net_Flow_Car", "stats_Net_Flow_All")
# Keys that must keep their raw value even when the scope is dead.
AIMSUN_KEEP = ("aimsun_n_sections", "aimsun_error", "aimsun_scope_ok")


def stamp_row(row, now=None):
    """Return a copy of `row` with provenance and scope stamps applied.

    Adds:
        run_utc            ISO-8601 UTC timestamp of the write
        run_pid            process id (distinguishes concurrent runs)
        run_seed_applied   the seed the row was produced with (if known)
        stats_IdScope      'model' -> Experiment/Scenario/Replication ids are
                           the model's, not per-run identifiers
        stats_NetScope_ok  1/0 -> did the network-scope collector measure?
        aimsun_scope_ok    1/0 -> did the section-scope collector measure?

    Behaviour:
        * `stats_Net_*` columns become NaN when the net scope did not measure.
        * `aimsun_*` aggregates become NaN when no section returned usable flow.
        * Everything else is passed through untouched.
    """
    out = dict(row)
    ts = now or datetime.datetime.utcnow()
    out.setdefault("run_utc", ts.strftime("%Y-%m-%dT%H:%M:%SZ"))
    out.setdefault("run_pid", os.getpid())
    if "run_seed_applied" not in out and out.get("run_seed") is not None:
        out["run_seed_applied"] = out.get("run_seed")
    if any(k in out for k in ("stats_ExperimentID", "stats_ScenarioID",
                              "stats_ReplicationID")):
        out.setdefault("stats_IdScope", "model")

    net_ok = 1 if _any_positive(out, NET_PROBES) else 0
    out.setdefault("stats_NetScope_ok", net_ok)
    if not net_ok:
        for k in list(out):
            if k.startswith("stats_Net_"):
                out[k] = float("nan")

    try:
        flow_ok = int(float(out.get("aimsun_flow_sections_ok") or 0))
    except (TypeError, ValueError):
        flow_ok = 0
    aim_ok = 1 if flow_ok > 0 else 0
    out.setdefault("aimsun_scope_ok", aim_ok)
    if not aim_ok:
        for k in list(out):
            if k.startswith("aimsun_") and k not in AIMSUN_KEEP:
                out[k] = float("nan")

    return out


def scope_warning(row):
    """One-line warning for the run log, or None when both scopes measured."""
    msgs = []
    if int(row.get("stats_NetScope_ok", 1) or 0) == 0:
        msgs.append("stats_Net_* not measured (written as NaN)")
    if int(row.get("aimsun_scope_ok", 1) or 0) == 0:
        msgs.append("aimsun_* not measured: 0/%s sections returned flow "
                    "(written as NaN)" % (row.get("aimsun_n_sections", "?"),))
    return ("[PROVENANCE] " + "; ".join(msgs)) if msgs else None
