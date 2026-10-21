"""scats_det_dump.py -- ONE-SESSION Aimsun dump for the KG SCATS detector map.

Run ONCE inside Aimsun Next (PyANGKernel), e.g. from the scripting console:

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sd", r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\scats_det_dump.py")
    sd = importlib.util.module_from_spec(spec); spec.loader.exec_module(sd)
    sd.dump(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\kg_scats_geom_dump.json",
            model=GKSystem.getSystem().getActiveModel())

WHY a live session is required: the offline model export
(kg_aimsun_dump_fresh.json) carries detector geometry and the SCATS site number
(node name) but NOT the phase -> origin-section link, because the exporter
emits control-plan `signal_groups` empty (GKControlJunction exposes phases, not
getSignalGroups). This script recovers that link from each phase's
getSignalGroupStates() keys -> signal-group turnings -> origin sections, which
is exactly the derivation the engine uses in _phase_origin_sections() /
_auto_place_detectors(). Cross this with scats_state_map.py (SCATS classes) via
build_scats_det_map.py to fill the SCATS#->Aimsun-detector-ID gap for the 11 KG
junctions that were previously unmapped.

Output schema (kg_scats_geom_dump.json):
    {
      "model_name": str,
      "junctions": {
        "<junction_id>": {
          "node_name": str,            # SCATS site number, when numeric
          "phases": [
            {"phase": int, "origin_sections": [int, ...],
             "green_sgs": [int, ...],
             "detectors": [{"id": int, "section": int, "lane": int,
                            "pos": float, "name": str}, ...]}, ...],
          "incoming_sections": {
            "<sec_id>": {"from_node": int|None, "to_node": int|None,
                         "n_lanes": int, "length_m": float,
                         "bearing_deg": float|None,
                         "detectors": [int, ...]}, ...}
        }, ...}
    }

API surface mirrors export_aimsun_network.py (verified live): GKSection
nbPoints/getPoint/length2D/getLanes/getOrigin/getDestination, GKNode
getName/getPosition, GKDetector getSection/getPosition/getFromLane/getLength,
GKControlJunction getPhases. Signal-group turnings are probed defensively
because the accessor names vary across Aimsun builds.
"""

import json
import math
import traceback

_LOG = []


def _log(msg):
    print("[SCATS_DUMP] %s" % msg)
    _LOG.append(str(msg))


_MODEL = None


def resolve_model(explicit=None):
    global _MODEL
    if explicit is not None:
        _MODEL = explicit
        return _MODEL
    if _MODEL is not None:
        return _MODEL
    import builtins
    gks = getattr(builtins, "GKSystem", None)
    if gks is not None and hasattr(gks, "getSystem"):
        _MODEL = gks.getSystem().getActiveModel()
        return _MODEL
    try:
        import inspect
        frame = inspect.currentframe().f_back
        while frame is not None:
            gks = frame.f_globals.get("GKSystem")
            if gks is not None and hasattr(gks, "getSystem"):
                _MODEL = gks.getSystem().getActiveModel()
                return _MODEL
            frame = frame.f_back
    except Exception:
        pass
    try:
        from GKSystem import GKSystem as _gks   # noqa
        _MODEL = _gks.getSystem().getActiveModel()
        return _MODEL
    except Exception:
        pass
    raise RuntimeError(
        "Could not reach the active Aimsun model. Run instead:\n"
        "    sd.dump(r'<out>', model=GKSystem.getSystem().getActiveModel())")


def iter_objects(model, type_name):
    cat = model.getCatalog()
    try:
        t = model.getType(type_name)
        if t is not None:
            got = cat.getObjectsByType(t)
            if got:
                vals = list(got.values()) if isinstance(got, dict) else list(got)
                if vals:
                    return vals
    except Exception:
        pass
    return []


def _safe(fn, default=None):
    try:
        v = fn()
        return default if v is None else v
    except Exception:
        return default


def _obj_id(o):
    if o is None:
        return None
    return _safe(lambda: o.getId())


def _pt(p):
    try:
        return [float(p.getX()), float(p.getY())]
    except Exception:
        try:
            return [float(p.x), float(p.y)]
        except Exception:
            return None


def _polyline_points(sec):
    pts = []
    try:
        n = int(sec.nbPoints())
        for i in range(n):
            q = _pt(sec.getPoint(i))
            if q:
                pts.append(q)
    except Exception:
        pass
    if len(pts) >= 2:
        return pts
    try:
        for p in list(sec.getPoints()):
            q = _pt(p)
            if q:
                pts.append(q)
    except Exception:
        pass
    return pts


def _bearing_deg(shape):
    """Compass bearing (0=N, 90=E) from the first->last geometry point."""
    if not shape or len(shape) < 2:
        return None
    (x0, y0), (x1, y1) = shape[0], shape[-1]
    dx, dy = x1 - x0, y1 - y0
    if dx == 0.0 and dy == 0.0:
        return None
    ang = math.degrees(math.atan2(dx, dy))   # dx east, dy north -> 0=N
    return round((ang + 360.0) % 360.0, 1)


def _sec2det(model):
    """section id -> [detector ids] for every reporting detector in the model."""
    out = {}
    seen = set()
    for dtype in ("GKDetector", "GKControlDetector"):
        for det in iter_objects(model, dtype):
            did = _obj_id(det)
            if did is None or did in seen:
                continue
            sec = _obj_id(_safe(det.getSection))
            if sec is None:
                continue
            seen.add(did)
            out.setdefault(int(sec), []).append(int(did))
    return out


def _sg_turnings_sections(jc, phase, groups):
    """Origin section ids whose turning is green in `phase`.

    Primary: the phase's getSignalGroupStates() keys are signal-group objects;
    for each, read its turnings and take turning.getOrigin() sections. Falls back
    to (a) phase.getSignalGroups()/getGroups(), (b) the cached `groups` list.
    Returns (set(section_ids), set(green_sg_ids))."""
    secs = set()
    greens = set()

    def _sgs_from_phase():
        for meth in ("getSignalGroupStates", "getSignalGroupsAndStates",
                     "getSignalGroupState"):
            fn = getattr(phase, meth, None)
            if not callable(fn):
                continue
            try:
                d = fn()
            except Exception:
                continue
            if isinstance(d, dict):
                vals = list(d.items())
            elif isinstance(d, (list, tuple)):
                vals = list(d)
            else:
                continue
            out = []
            for it in vals:
                if isinstance(it, tuple) and len(it) == 2:
                    sg, st = it
                else:
                    sg, st = it, 1
                try:
                    if int(st) <= 0:
                        continue
                except Exception:
                    pass
                out.append(sg)
            if out:
                return out
        return []

    cand = _sgs_from_phase()
    if not cand:
        for meth in ("getSignalGroups", "getGroups"):
            fn = getattr(phase, meth, None)
            if callable(fn):
                cand = list(_safe(fn, []) or [])
                if cand:
                    break
    if not cand:
        cand = list(groups or [])
    for sg in cand:
        sgid = _obj_id(sg)
        if sgid is not None:
            greens.add(int(sgid))
        for tm in ("getTurnings", "getTurns"):
            fn = getattr(sg, tm, None)
            if not callable(fn):
                continue
            for t in (_safe(fn, []) or []):
                o = _obj_id(_safe(getattr(t, "getOrigin", None)))
                if o is not None:
                    secs.add(int(o))
            break
    return secs, greens


def dump(out_path, model=None):
    model = resolve_model(model)
    out = {"model_name": str(_safe(lambda: model.getName(), "?")),
           "junctions": {}}
    _log("model: %s" % out["model_name"])

    nodes = {}
    for node in iter_objects(model, "GKNode"):
        nid = _obj_id(node)
        if nid is not None:
            nodes[int(nid)] = str(_safe(node.getName, "") or "")

    secs = {}
    for sec in iter_objects(model, "GKSection"):
        sid = _obj_id(sec)
        if sid is None:
            continue
        shape = _polyline_points(sec)
        secs[int(sid)] = {
            "from_node": _obj_id(_safe(sec.getOrigin)),
            "to_node": _obj_id(_safe(sec.getDestination)),
            "n_lanes": int(_safe(sec.getTotalNbLanes)
                           or _safe(sec.getNbFullLanes) or 1),
            "length_m": _safe(lambda: float(sec.length2D()), 0.0),
            "bearing_deg": _bearing_deg(shape),
        }
    _log("sections: %d, nodes: %d" % (len(secs), len(nodes)))

    det_by_id = {}
    for dtype in ("GKDetector", "GKControlDetector"):
        for det in iter_objects(model, dtype):
            did = _obj_id(det)
            if did is None or did in det_by_id:
                continue
            sec = _obj_id(_safe(det.getSection))
            if sec is None:
                continue
            ln = _safe(lambda: float(det.getLength()), 2.0) or 2.0
            fl = _safe(det.getFromLane, None)
            lane = int(fl) if isinstance(fl, int) and fl >= 0 else 0
            pos = _safe(lambda: float(det.getPosition()), None)
            if pos is None:
                continue
            det_by_id[int(did)] = {"id": int(did),
                                   "name": str(_safe(det.getName, "") or ""),
                                   "section": int(sec), "lane": lane,
                                   "pos": round(float(pos), 2),
                                   "final_pos": round(float(pos) + ln, 2)}
    s2d = {}
    for did, d in det_by_id.items():
        s2d.setdefault(d["section"], []).append(did)
    _log("detectors: %d" % len(det_by_id))

    segs = 0
    for name in ("GKRing", "GKControlPlan"):
        pass

    cjs = iter_objects(model, "GKControlJunction")
    _log("control junctions: %d" % len(cjs))
    for cj in cjs:
        jid = (_obj_id(_safe(getattr(cj, "getNode", None)))
               or _obj_id(_safe(getattr(cj, "getJunction", None)))
               or _obj_id(_safe(getattr(cj, "getOrigin", None))))
        if jid is None:
            jid = _obj_id(cj)
        if jid is None:
            continue
        jid = int(jid)
        rec = {"node_name": nodes.get(jid, ""), "phases": [],
               "incoming_sections": {}}
        groups = list(_safe(getattr(cj, "getSignalGroups", lambda: []), []) or [])
        try:
            phases = list(_safe(cj.getPhases, []) or [])
        except Exception:
            phases = []
        for pi, ph in enumerate(phases, start=1):
            sec_ids, greens = _sg_turnings_sections(cj, ph, groups)
            dets = []
            for s in sorted(sec_ids):
                for did in s2d.get(int(s), []):
                    dets.append(det_by_id[did])
            rec["phases"].append({
                "phase": pi,
                "duration_s": _safe(lambda: float(ph.getDuration()), None),
                "origin_sections": sorted(int(s) for s in sec_ids),
                "green_sgs": sorted(greens),
                "detectors": dets,
            })
            if dets:
                segs += 1
        inc = {}
        for sid, s in secs.items():
            if s["to_node"] is not None and int(s["to_node"]) == jid:
                inc[str(sid)] = {
                    "from_node": s["from_node"],
                    "to_node": s["to_node"],
                    "n_lanes": s["n_lanes"],
                    "length_m": s["length_m"],
                    "bearing_deg": s["bearing_deg"],
                    "detectors": sorted(s2d.get(sid, [])),
                }
        rec["incoming_sections"] = inc
        out["junctions"][str(jid)] = rec

    _log("junctions written: %d (phase groups with detectors: %d)"
         % (len(out["junctions"]), segs))
    if segs == 0:
        _log("WARNING: no phase->detector groups. The signal-group turnings "
             "accessor may differ on this build -- inspect `green_sgs` and "
             "`origin_sections` in the output, and re-probe the SG API.")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    _log("written -> %s" % out_path)
    return out_path


if __name__ == "__main__":
    dump("kg_scats_geom_dump.json")
