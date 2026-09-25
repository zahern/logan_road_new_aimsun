#!/usr/bin/env python3
"""
node_flow_export.py -- node turning-flow export for shockwave analysis.

Port of the TSS (2006-2009) node-flow script to Aimsun Next 26 / Python 3:
    node_flow = sum of turning flows over all turnings of the node.

The original only wrote the total back into a GKNode::totalFlow model column.
This port ALSO writes two CSVs (the actual deliverable for shockwave math):
    node_flows_<corridor>.csv     NodeID | NodeName | TotalFlow_veh | n_turnings | n_ok
    turning_flows_<corridor>.csv  NodeID | FromObj | ToObj | Flow_veh

Flow source: the turning-flow time series
    "DYNAMIC::SRC_GKTurning_turning flow_0", .getMean(0)
i.e. the mean over aggregation interval 0 -- the same window Aimsun's own
time-series reports use. Every (node, turning) value in the CSV therefore
comes from ONE source and ONE window, so upstream/downstream pairs stay
mutually consistent for w = (q2-q1)/(k2-k1).

HOW TO RUN (Aimsun console, corridor model open, AFTER a replication run --
turning time series only exist once statistics have been generated):
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\node_flow_export.py").read())
or run as a script from the Run Script menu.

Writes back the GKNode::totalFlow column too (WRITE_COLUMN=True), like the
original, and commits the undo buffer.
"""

import os as _os
import sys as _sys
import csv as _csv
import traceback as _tb

try:
    from PyANGKernel import GKSystem
except ImportError:
    print("ERROR: run inside the Aimsun Python console with the model open.")
    raise SystemExit(1)

# QVariant / GKColumn live in different places across Aimsun versions.
# Next 26 uses Qt6 (QVariant no longer exists as such -- raw values pass
# straight through); older builds exposed it via PyQt4/5.
_QVariant = None
for _imp in ("PySide6.QtCore", "PyQt5.QtCore", "PyQt4.QtCore"):
    try:
        _ns = __import__(_imp, fromlist=["QVariant"])
        _QVariant = getattr(_ns, "QVariant", None)
        if _QVariant is not None:
            break
    except Exception:
        pass

_GKColumn = None
try:
    from PyANGKernel import GKColumn as _GKColumn
except Exception:
    pass

_HERE = _os.path.dirname(_os.path.abspath(__file__)) \
    if "__file__" in dir() else _os.getcwd()

FLOW_COL_NAME = "DYNAMIC::SRC_GKTurning_turning flow_0"
WRITE_COLUMN = True  # also write back GKNode::totalFlow like the original


def _as_list(objs):
    if objs is None:
        return []
    if isinstance(objs, dict):
        return list(objs.values())
    try:
        return list(objs)
    except Exception:
        return []


def _resolve_flow_column(model):
    """Exact TSS name first, then substring search over GKColumn objects."""
    try:
        _col = model.getColumn(FLOW_COL_NAME)
        if _col is not None:
            print("[NODEFLOW] using column: " + FLOW_COL_NAME)
            return _col
    except Exception as _e:
        print("[NODEFLOW] getColumn(exact) failed: {!r}".format(_e))
    try:
        _ctype = model.getType("GKColumn")
        for _c in _as_list(model.getCatalog().getObjectsByType(_ctype)):
            try:
                _n = _c.getName()
            except Exception:
                continue
            _ln = (_n or "").lower()
            if "turning" in _ln and "flow" in _ln:
                print("[NODEFLOW] fallback column: " + str(_n))
                return _c
    except Exception as _e:
        print("[NODEFLOW] column scan failed: {!r}".format(_e))
    raise RuntimeError("turning-flow time-series column not found; run a "
                       "replication first so statistics exist.")


def _ts_mean(ts):
    """Mean of a turning time series. Original semantics: .getMean(0)."""
    for _call in (lambda: ts.getMean(0), lambda: ts.getMean()):
        try:
            _v = _call()
            if _v is not None:
                return float(_v)
        except Exception:
            pass
    return None


def _turning_endpoints(turning):
    _frm, _to = "?", "?"
    for _fn in ("getOrigin", "getOriginSection", "getFromSection", "getSrcSection"):
        try:
            _o = getattr(turning, _fn, None)
            if callable(_o):
                _v = _o()
                if _v is not None:
                    _frm = str(_v.getId() if hasattr(_v, "getId") else _v)
                    break
        except Exception:
            pass
    for _fn in ("getDestination", "getDestinationSection", "getToSection", "getDstSection"):
        try:
            _o = getattr(turning, _fn, None)
            if callable(_o):
                _v = _o()
                if _v is not None:
                    _to = str(_v.getId() if hasattr(_v, "getId") else _v)
                    break
        except Exception:
            pass
    return _frm, _to


def main():
    model = GKSystem.getSystem().getActiveModel()
    if model is None:
        raise RuntimeError("No active model -- open the corridor first.")
    try:
        _corr = _os.path.basename(model.getDocumentDirectory().absolutePath())
    except Exception:
        _corr = "model"
    if _corr not in ("kg", "logan_road_new"):
        _corr = "model"

    flow_col = _resolve_flow_column(model)
    node_type = model.getType("GKNode")
    nodes = _as_list(model.getCatalog().getObjectsByType(node_type))
    print("[NODEFLOW] corridor={} nodes={}".format(_corr, len(nodes)))
    if not nodes:
        raise RuntimeError("No GKNode objects found.")

    # Optional in-model column (original behaviour).
    node_col = None
    if WRITE_COLUMN and _GKColumn is not None:
        try:
            node_col = node_type.addColumn("GKNode::totalFlow", "Total Flow",
                                           _GKColumn.Double, _GKColumn.eExternal)
        except Exception as _e:
            print("[NODEFLOW] WARNING: addColumn failed (CSV still written): {!r}".format(_e))

    node_rows, turn_rows = [], []
    for node in nodes:
        try:
            _nid = node.getId()
        except Exception:
            _nid = "?"
        try:
            _nname = node.getName()
        except Exception:
            _nname = "?"
        try:
            _turnings = list(node.getTurnings() or [])
        except Exception:
            _turnings = []
        _flow, _n_ok = 0.0, 0
        for turning in _turnings:
            try:
                _ts = turning.getDataValueTS(flow_col)
            except Exception:
                continue
            if _ts is None:
                continue
            _v = _ts_mean(_ts)
            # Original rule: skip missing (-1) / non-positive entries.
            if _v is None or _v <= 0:
                continue
            _flow += _v
            _n_ok += 1
            _frm, _to = _turning_endpoints(turning)
            turn_rows.append((_nid, _frm, _to, round(_v, 3)))
        if node_col is not None:
            try:
                node.setDataValue(node_col,
                                  _QVariant(_flow) if _QVariant is not None else _flow)
            except Exception as _e:
                print("[NODEFLOW] WARNING: setDataValue failed for node {}: {!r}".format(_nid, _e))
        node_rows.append((_nid, _nname, round(_flow, 3), len(_turnings), _n_ok))

    try:
        model.getCommander().addCommand(None)
    except Exception as _e:
        print("[NODEFLOW] WARNING: undo-buffer commit failed: {!r}".format(_e))

    _nf = _os.path.join(_HERE, "node_flows_{}.csv".format(_corr))
    _tf = _os.path.join(_HERE, "turning_flows_{}.csv".format(_corr))
    with open(_nf, "w", newline="", encoding="utf-8") as _f:
        _w = _csv.writer(_f)
        _w.writerow(("NodeID", "NodeName", "TotalFlow_veh", "n_turnings", "n_ok"))
        _w.writerows(node_rows)
    with open(_tf, "w", newline="", encoding="utf-8") as _f:
        _w = _csv.writer(_f)
        _w.writerow(("NodeID", "FromObj", "ToObj", "Flow_veh"))
        _w.writerows(turn_rows)

    _net = sum(_r[2] for _r in node_rows)
    _top = sorted(node_rows, key=lambda _r: -_r[2])[:10]
    print("[NODEFLOW] wrote {} ({} nodes) + {} ({} turnings)".format(_nf, len(node_rows), _tf, len(turn_rows)))
    print("[NODEFLOW] network turning-flow sum = {:.1f} veh".format(_net))
    for _nid, _nn, _fl, _nt, _ok in _top:
        print("[NODEFLOW]   node {} ({}): {:.1f} veh over {}/{} turnings".format(_nid, _nn, _fl, _ok, _nt))
    return _nf, _tf


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _tb.print_exc()
