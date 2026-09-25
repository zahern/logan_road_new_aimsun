# export_aimsun_network.py
# Run INSIDE Aimsun Next (PyANGKernel binding - verified against live probe).
#
#   import importlib.util
#   spec = importlib.util.spec_from_file_location(
#       "ex", r"C:\Users\ahernz\github_for_aimsun\sumo_bridge\export_aimsun_network.py")
#   ex = importlib.util.module_from_spec(spec); spec.loader.exec_module(ex)
#   ex.export(r"C:\Users\ahernz\github_for_aimsun\sumo_bridge\kg_aimsun_dump.json",
#             model=GKSystem.getSystem().getActiveModel())
#
# Confirmed API (aimsun_api_probe.txt):
#   GKSection : nbPoints/getPoint(i), length2D, getSpeed, getLanes,
#               getOrigin/getDestination (-> GKNode), getTotalNbLanes
#   GKTurning : getNode, getOrigin/getDestination (-> GKSection),
#               getOriginFromLane/getOriginToLane/
#               getDestinationFromLane/getDestinationToLane
#   GKNode    : getPosition, getEntranceSections, getSignals
#   GKDetector: getSection, getPosition, getLength, getFromLane/getToLane/allLanes

import json
import math
import traceback


def _log(msg):
    print("[EXPORT] %s" % msg)


# ------------------------------------------------------------------ model
_MODEL = None


def resolve_model(explicit=None):
    """Aimsun Next injects GKSystem/GK* objects into the scripting namespace."""
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
        "    ex.export(r'<out>', model=GKSystem.getSystem().getActiveModel())")


def iter_objects(model, type_name):
    """All live objects of a GK type (model.getType + catalog path verified)."""
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


def _pt(p):
    try:
        return [float(p.getX()), float(p.getY())]
    except Exception:
        try:
            return [float(p.x), float(p.y)]
        except Exception:
            return None


def _polyline_points(sec):
    """Geometry via nbPoints/getPoint(i), falling back to getPoints()."""
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
        arr = sec.getPoints()
        for p in list(arr):
            q = _pt(p)
            if q:
                pts.append(q)
    except Exception:
        pass
    return pts


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


def export(out_path, model=None):
    model = resolve_model(model)

    dump = {
        "model_name": str(_safe(lambda: model.getName(), "?")),
        "sections": {}, "nodes": {}, "turnings": {},
        "detectors": [], "control_plans": [], "pt_lines": [],
        "od_matrices": [], "centroids": {}, "vehicle_types": [],
    }
    _log("model: %s" % dump["model_name"])
    _log("exporter v8: bidirectional-sections + centroids + OD getTrips + GKPTLine")

    # ------------------------------------------------------------- sections
    n_ok = n_bad = 0
    for sec in iter_objects(model, "GKSection"):
        sid = _obj_id(sec)
        if sid is None:
            continue
        try:
            shape = _polyline_points(sec)
            length = _safe(lambda: float(sec.length2D()))
            if not length and len(shape) > 1:
                length = sum(math.dist(shape[i], shape[i + 1])
                             for i in range(len(shape) - 1))
            lanes = []
            for i, ln in enumerate(_safe(sec.getLanes, []) or []):
                w = _safe(lambda: float(ln.getWidth()), 3.5)
                idx = _safe(lambda: int(ln.getNumber()), i)
                lanes.append({"index": idx, "width": w})
            nl = _safe(sec.getTotalNbLanes) or \
                 _safe(sec.getNbFullLanes) or len(lanes) or 1
            dump["sections"][str(sid)] = {
                "id": sid,
                "name": str(_safe(sec.getName, "")),
                "from_node": _obj_id(_safe(sec.getOrigin)),
                "to_node": _obj_id(_safe(sec.getDestination)),
                "speed_kmh": _safe(lambda: float(sec.getSpeed()), 50.0),
                "length_m": length,
                "shape": shape,
                "lanes": lanes,
                "n_lanes": int(nl),
            }
            n_ok += 1
        except Exception as e:
            n_bad += 1
            if n_bad <= 5:
                _log("section %s skipped: %r" % (sid, e))
    if n_bad > 5:
        _log("... %d sections skipped in total" % n_bad)
    _log("sections exported: %d (skipped %d)" % (n_ok, n_bad))

    # ------------------------------------------------- bidirectional sections
    # Aimsun models two-way roads either as two GKSection objects (both already
    # captured above) or as ONE GKSectionBidirectional holding both directions.
    # The bidirectional type is NOT returned by getObjectsByType(GKSection),
    # which is why every corridor link previously exported one-way (measured:
    # 38 one-way links near managed KG junctions, no reverse sections in dump).
    n_bi = 0
    for bi_type_name in ("GKSectionBidirectional", "GKBidirectionalSection"):
        try:
            t_bi = model.getType(bi_type_name)
        except Exception:
            t_bi = None
        if t_bi is None:
            continue
        objs = []
        try:
            got = model.getCatalog().getObjectsByType(t_bi)
            objs = list(got.values()) if isinstance(got, dict) else list(got)
        except Exception:
            pass
        _log("bidirectional probe %s: %d objects" % (bi_type_name, len(objs)))
        for obj in objs:
            sid = _obj_id(obj)
            if sid is None:
                continue
            shape = _polyline_points(obj)
            length = _safe(lambda: float(obj.length2D()), 0.0) or 100.0
            speed = _safe(lambda: float(obj.getSpeed()), 50.0)
            # Direction 1 = origin->destination of the base section; direction
            # 2 = the reverse.  Probe several known API shapes defensively and
            # log which one worked so we can tighten this later.
            d1_lanes = d2_lanes = None
            for getter1, getter2 in (
                    ("getLanesDirection1", "getLanesDirection2"),
                    ("getLanesDir1", "getLanesDir2")):
                f1 = getattr(obj, getter1, None)
                f2 = getattr(obj, getter2, None)
                if callable(f1) and callable(f2):
                    try:
                        l1 = _safe(f1, []) or []
                        l2 = _safe(f2, []) or []
                        d1_lanes = max(len(l1), 1)
                        d2_lanes = max(len(l2), 0)
                        break
                    except Exception:
                        continue
            if d1_lanes is None:
                d1_lanes = _safe(lambda: int(obj.getNbLanesDirection1()), 1) or 1
                d2_lanes = _safe(lambda: int(obj.getNbLanesDirection2()), 0) or 0
            node_a = _obj_id(_safe(getattr(obj, "getOrigin", obj.getOrigin)))
            node_b = _obj_id(_safe(getattr(obj, "getDestination",
                                           obj.getDestination)))

            def _emit(direction, frm, to, nl, uid):
                if frm is None or to is None or not shape or nl <= 0:
                    return False
                if len(shape) >= 2 and direction == 2:
                    use_shape = list(reversed(shape))
                else:
                    use_shape = shape
                dump["sections"][str(uid)] = {
                    "id": uid,
                    "name": "%s dir%d" % (_safe(lambda: str(obj.getName()), "")
                                          or sid, direction),
                    "from_node": frm,
                    "to_node": to,
                    "speed_kmh": speed,
                    "length_m": length,
                    "shape": use_shape,
                    "lanes": [{"index": i, "width": 3.5} for i in range(nl)],
                    "n_lanes": int(nl),
                }
                return True

            # unique int ids that cannot collide with real section ids
            uid1 = 900000000 + sid * 2
            uid2 = 900000000 + sid * 2 + 1
            ok1 = _emit(1, node_a, node_b, d1_lanes or 1, uid1)
            ok2 = _emit(2, node_b, node_a, d2_lanes, uid2)
            if ok1 or ok2:
                n_bi += 1
            else:
                _log("bidirectional section %s: both directions unusable "
                     "(nodes=%r,%r lanes=%r,%r)" % (sid, node_a, node_b,
                                                    d1_lanes, d2_lanes))
        if objs:
            _log("bidirectional sections exported: %d" % n_bi)
            break

    # ---------------------------------------------------------------- nodes
    n_ok = 0
    for node in iter_objects(model, "GKNode"):
        nid = _obj_id(node)
        if nid is None:
            continue
        try:
            xy = None
            p = _safe(node.getPosition)
            if p is not None:
                xy = _pt(p)
            dump["nodes"][str(nid)] = {"id": nid,
                                       "name": str(_safe(node.getName, "")),
                                       "xy": xy}
            n_ok += 1
        except Exception as e:
            _log("node %s skipped: %r" % (nid, e))
    _log("nodes exported: %d" % n_ok)

    # ------------------------------------------------------------- turnings
    n_ok = 0
    for tur in iter_objects(model, "GKTurning"):
        tid = _obj_id(tur)
        if tid is None:
            continue
        try:
            fs = _obj_id(_safe(tur.getOrigin))
            ts = _obj_id(_safe(tur.getDestination))
            nd = _obj_id(_safe(tur.getNode))
            if fs is None or ts is None:
                continue
            df = _safe(tur.getDestinationFromLane, -1)
            dt = _safe(tur.getDestinationToLane, -1)
            n_lanes = (dt - df + 1) if (isinstance(df, int) and isinstance(dt, int)
                                        and dt >= df >= 0) else 1
            dump["turnings"][str(tid)] = {
                "id": tid,
                "node": nd,
                "from_section": fs,
                "to_section": ts,
                "n_lanes": max(1, int(n_lanes)),
            }
            n_ok += 1
        except Exception as e:
            _log("turning %s skipped: %r" % (tid, e))
    _log("turnings exported: %d" % n_ok)

    # ------------------------------------------------------------ detectors
    seen_det = set()
    for dtype_name in ("GKDetector", "GKControlDetector"):
        for det in iter_objects(model, dtype_name):
            did = _obj_id(det)
            if did is None or did in seen_det:
                continue
            try:
                sec_id = _obj_id(_safe(det.getSection))
                pos = _safe(lambda: float(det.getPosition()), None)
                if sec_id is None or pos is None:
                    continue
                ln = _safe(lambda: float(det.getLength()), 2.0)
                fl = _safe(det.getFromLane, None)
                tl = _safe(det.getToLane, None)
                lane = 0
                if isinstance(fl, int) and fl >= 0:
                    lane = fl
                elif isinstance(tl, int) and tl >= 0:
                    lane = tl
                dump["detectors"].append({
                    "id": did,
                    "name": str(_safe(det.getName, "")),
                    "type": dtype_name,
                    "section": sec_id,
                    "lane": lane,
                    "initial_pos": pos,
                    "final_pos": pos + (ln if ln and ln > 0 else 2.0),
                    "all_lanes": bool(_safe(det.allLanes, False)),
                })
                seen_det.add(did)
            except Exception as e:
                _log("detector %s skipped: %r" % (did, e))
    _log("detectors exported: %d" % len(dump["detectors"]))

    # -------------------------------------------------------- control plans
    def _phase_states(ph, groups):
        st = {}
        try:
            d = ph.getSignalGroupStates()
            if isinstance(d, dict):
                for k, v in d.items():
                    key = k.getId() if hasattr(k, "getId") else k
                    st[str(key)] = int(v)
                return st
            if isinstance(d, (list, tuple)):
                for sg, v in zip(groups, d):
                    sgi = sg.getId() if sg is not None else None
                    st[str(sgi)] = int(v)
                return st
        except Exception:
            pass
        for sg in groups:
            for meth in ("getStateOfSignalGroup", "getState", "getColour"):
                f = getattr(ph, meth, None)
                if f is None:
                    continue
                try:
                    st[str(sg.getId())] = int(f(sg))
                    break
                except TypeError:
                    try:
                        st[str(sg.getId())] = int(f())
                        break
                    except Exception:
                        pass
                except Exception:
                    pass
        return st

    def _junction_phases(jc, groups):
        out = []
        try:
            phs = list(jc.getPhases())
            for ph in phs:
                dur = _safe(lambda: float(ph.getDuration()), 30.0)
                out.append({"duration": dur,
                            "sg_states": _phase_states(ph, groups)})
            if out:
                return out
        except Exception:
            pass
        try:
            ring = jc.getRing()
            for cyc in (ring.getCycles() if ring else []):
                for ph in cyc.getPhases():
                    out.append({"duration": _safe(lambda: float(ph.getDuration()), 30.0),
                                "sg_states": _phase_states(ph, groups)})
        except Exception:
            pass
        return out

    total_junc = 0
    cat_cp = model.getCatalog()
    # Cache control-junction objects once (type may be GKControlJunction)
    _cj_objs = {}
    try:
        for cjo in iter_objects(model, "GKControlJunction"):
            jid = _obj_id(_safe(cjo.getNode)) or _obj_id(_safe(
                getattr(cjo, "getJunction", None)))
            nid = _obj_id(getattr(cjo, "getNode", None))
            key = jid or nid
            if key is not None:
                _cj_objs[int(key)] = cjo
    except Exception:
        pass
    _log("control-junction objects found: %d" % len(_cj_objs))

    for cp in iter_objects(model, "GKControlPlan"):
        try:
            plan = {"id": _obj_id(cp), "name": str(_safe(cp.getName, "")),
                    "junctions": {}}
            jcs_raw = _safe(cp.getControlJunctions, []) or []
            # This build returns a dict {node_id: ...} or list of ints.
            # Convert each to a GKNode object via catalog.find(), then call
            # cp.getControlJunction(GKNode) to get the control-junction data.
            if isinstance(jcs_raw, dict):
                j_ids = [int(k) for k in jcs_raw.keys()]
            else:
                j_ids = [int(j) for j in jcs_raw]
            fn_cj = getattr(cp, "getControlJunction", None)
            cat_cp = model.getCatalog()
            for nid_j in j_ids:
                node_obj = _safe(lambda: cat_cp.find(nid_j))
                if node_obj is None:
                    continue
                jc = None
                if callable(fn_cj):
                    try:
                        jc = fn_cj(node_obj)
                    except Exception:
                        pass
                if jc is None:
                    jc = _cj_objs.get(nid_j)
                if jc is None or not hasattr(jc, "getPhases"):
                    continue
                jid = nid_j
                # GKControlJunction has getPhases(), NOT getSignalGroups().
                # Signal group states are embedded in each phase.
                groups = []  # not needed — phases carry their own sg_states
                sgs = []
                for sg in groups:
                    turns = []
                    for t in (_safe(sg.getTurnings, []) or []):
                        tid = _obj_id(t)
                        if tid is not None:
                            turns.append(tid)
                    sgs.append({"id": _obj_id(sg), "name": str(_safe(sg.getName, "")),
                                "turnings": turns})
                plan["junctions"][str(jid)] = {
                    "junction_id": jid,
                    "control_type": _safe(lambda: int(jc.getControlType())),
                    "phases": _junction_phases(jc, groups),
                    "signal_groups": sgs,
                }
            total_junc += len(plan["junctions"])
            if plan["junctions"]:
                dump["control_plans"].append(plan)
        except Exception as e:
            _log("control plan skipped: %r" % e)
    _log("control plans exported: %d (%d junction entries)"
         % (len(dump["control_plans"]), total_junc))

    # -------------------------------------------------------------- PT lines
    # Aimsun Next stores transit as GKPTLine (folder "Transit Lines") with
    # GKPTLineRouteItem routes, plus GKPTPlan (folder "Transit Plans") holding
    # per-line departures/headways.  GKPublicLine is the legacy type — probed
    # as fallback.  Measured on KG: GKPublicLine returned 57 objects all with
    # 0 route sections; the real network lives under GKPTLine.
    dump["pt_plans"] = []
    seen_pt_ids = set()

    def _export_pt_line(line, source_type):
        lid = _obj_id(line)
        if lid is None or lid in seen_pt_ids:
            return
        seen_pt_ids.add(lid)
        route_sections = []
        stops = []
        # ── Route sections via getRoute() ──────────────────────────────────
        # Measured on Logan: getRoute() returns section IDs directly as ints
        # (e.g. [16188, 9923, 12031, ...]).  getSections() needs 2 args.
        try:
            got = _safe(line.getRoute, []) or []
            for s0 in got:
                sid = int(s0) if isinstance(s0, (int, float)) else \
                    (_obj_id(s0) if hasattr(s0, "getId") else None)
                if sid is not None:
                    route_sections.append(int(sid))
        except Exception:
            pass
        # Fallback: getRouteIds()
        if not route_sections:
            fn = getattr(line, "getRouteIds", None)
            if callable(fn):
                got = _safe(fn, []) or []
                for s0 in got:
                    try:
                        route_sections.append(int(s0))
                    except (TypeError, ValueError):
                        continue
        # ── Stops via GKBusStop catalog + line.getStopIndex() mapping ───────
        # getStops() returns placeholder Nones; the real stops are GKBusStop
        # catalog objects.  We export ALL of them once globally so the builder
        # can match them to sections by proximity.
        try:
            got_stops = _safe(line.getStops, []) or []
            for st in got_stops:
                if st is None:
                    stops.append({"id": None, "name": "", "dwell_s": 20.0})
                else:
                    sid = _obj_id(st)
                    stops.append({"id": sid,
                                  "name": str(_safe(getattr(st, "getName",
                                                            lambda: "") or "")),
                                  "dwell_s": 20.0})
        except Exception:
            pass
        rec = {"id": lid,
               "name": str(_safe(line.getName, "")),
               "type": source_type,
               "route_sections": route_sections,
               "stops": stops,
               "headway_min": _safe(lambda: float(line.getHeadway()), None)}
        if route_sections or stops:
            dump["pt_lines"].append(rec)
        elif lid == sorted(seen_pt_ids)[0]:
            meths = [a for a in dir(line)
                     if any(k in a.lower() for k in
                            ("route", "item", "section", "stop", "station"))
                     and not a.startswith("_")]
            _log("PT diag %s (%s): accessors: %s"
                 % (lid, rec["name"][:40], sorted(meths)[:30]))

    n_pt = 0
    for pt_type in ("GKPTLine", "GKPublicLine"):
        objs = iter_objects(model, pt_type)
        _log("PT probe %s: %d objects" % (pt_type, len(objs)))
        for line in objs:
            before = len(dump["pt_lines"])
            _export_pt_line(line, pt_type)
            if len(dump["pt_lines"]) > before:
                n_pt += 1
        if objs and n_pt > 0:
            break
    _log("PT lines exported: %d" % len(dump["pt_lines"]))

    # ------------------------------------------------------- GKBusStop catalog
    # Real bus stop positions — used by the builder to place SUMO <busStop>
    # elements at the correct lane/pos instead of synthetic spacing.
    dump["bus_stops"] = []
    for st in iter_objects(model, "GKBusStop"):
        sid = _obj_id(st)
        if sid is None:
            continue
        xy = None
        p = _safe(st.getPosition)
        if p is not None:
            xy = _pt(p)
        dump["bus_stops"].append({
            "id": sid,
            "name": str(_safe(st.getName, "")),
            "xy": xy,
            "section": _obj_id(_safe(getattr(st, "getSection", lambda: None))),
            "pos": _safe(lambda: float(getattr(st, "getPosition", lambda: 0)()),
                         None),
        })
    _log("bus stops exported: %d" % len(dump["bus_stops"]))

    # ------------------------------------------------------------ Transit Plans
    for plan in iter_objects(model, "GKPTPlan"):
        pid = _obj_id(plan)
        if pid is None:
            continue
        prec = {"id": pid, "name": str(_safe(plan.getName, "")), "lines": []}
        # Probe line-schedule accessors
        for getter in ("getLines", "getPTLines", "getPublicLines"):
            fn = getattr(plan, getter, None)
            if callable(fn):
                try:
                    for pl in (_safe(fn, []) or []):
                        lid = _obj_id(pl)
                        if lid is not None:
                            prec["lines"].append(lid)
                    break
                except Exception:
                    continue
        # Departures: probe common accessors, store raw if found
        deps = []
        for getter in ("getDepartures", "getLineDepartures"):
            fn = getattr(plan, getter, None)
            if callable(fn):
                try:
                    deps = list(_safe(fn, []) or [])
                    break
                except Exception:
                    continue
        prec["_n_departures"] = len(deps)
        if deps:
            sample = deps[0]
            prec["_departure_sample_dir"] = [
                a for a in dir(sample) if not a.startswith("_")][:20]
        dump["pt_plans"].append(prec)
    _log("transit plans exported: %d" % len(dump["pt_plans"]))

    # ------------------------------------------------------------ OD demand
    # Centroids + centroid→section connectors are REQUIRED for a true
    # od2trips-style demand build: each centroid maps to its entry/exit
    # sections, so an OD cell (origin, destination, trips) becomes a flow
    # between two real edges.  Without them the matrices cannot be grounded.
    cat = model.getCatalog()
    n_cen = 0
    for cen in iter_objects(model, "GKCentroid"):
        cid = _obj_id(cen)
        if cid is None:
            continue
        xy = None
        p = _safe(cen.getPosition)
        if p is not None:
            xy = _pt(p)
        dump["centroids"][str(cid)] = {"id": cid,
                                       "name": str(_safe(cen.getName, "")),
                                       "xy": xy,
                                       "in_sections": [],
                                       "out_sections": []}
        n_cen += 1
    _log("centroids exported: %d" % n_cen)
    # Centroid connectors: probe known types/APIs, attribute in/out sections
    n_conn = 0
    for conn_type in ("GKCenConnection", "GKCentroidConnection"):
        for conn in iter_objects(model, conn_type):
            cid_o = _obj_id(_safe(getattr(conn, "getCentroid",
                                          getattr(conn, "getOrigin", None))))
            sec = _obj_id(_safe(getattr(conn, "getSection",
                                        getattr(conn, "getDestinationSection",
                                                None))))
            if cid_o is None or sec is None:
                continue
            rec = dump["centroids"].get(str(cid_o))
            if rec is None:
                continue
            direction = str(_safe(getattr(conn, "getDirection", lambda: "") or ""))
            # Heuristic: 'to'/'in' connectors feed the network from the
            # centroid; 'from'/'out' drain it.  Store both lists and let the
            # builder decide by checking which end of the section touches the
            # corridor.
            if ("out" in direction.lower()) or ("from" in direction.lower()):
                rec["out_sections"].append(sec)
            else:
                rec["in_sections"].append(sec)
            n_conn += 1
    _log("centroid connections exported: %d" % n_conn)

    for odm in iter_objects(model, "GKODMatrix"):
        mid = _obj_id(odm)
        if mid is None:
            continue
        mname = str(_safe(odm.getName, "") or "")
        rec = {"id": mid, "name": mname, "trips": {}, "_n_cells": 0}
        # User class (each matrix holds ONE class × time window)
        uc_obj = _safe(getattr(odm, "getUserClass", None))
        if uc_obj is not None:
            rec["user_class"] = str(_safe(uc_obj.getName, "") or "")
        # Sanity: total trips in the matrix — skip empties BEFORE any O(n²) work
        tot = _safe(getattr(odm, "getTotalTrips", None))
        rec["total_trips"] = float(tot) if tot is not None else None
        if not rec["total_trips"]:
            dump["od_matrices"].append(rec)
            continue
        # Centroid OBJECTS resolved ONCE (cached) — the previous per-cell
        # catalog.find() pair made this loop ~98k scripted calls and froze
        # Aimsun's main thread ("Not Responding") on the larger Logan model.
        cen_ids = sorted(dump.get("centroids", {}).keys())
        cen_objs = {}
        for cid in cen_ids:
            o = _safe(lambda: cat.find(int(cid)))
            if o is not None:
                cen_objs[cid] = o
        _log("OD %s | '%s' | total_trips=%s — probing %d centroids"
             % (mid, mname[:40], rec["total_trips"], len(cen_objs)))
        trips_fn = getattr(odm, "getTrips", None)
        n_cells = 0
        if callable(trips_fn):
            for oc in cen_ids:
                o_obj = cen_objs.get(oc)
                if o_obj is None:
                    continue
                for dc in cen_ids:
                    d_obj = cen_objs.get(dc)
                    if d_obj is None:
                        continue
                    v = None
                    try:
                        v = _safe(lambda: float(trips_fn(o_obj, d_obj)))
                    except Exception:
                        try:
                            v = _safe(lambda: float(
                                trips_fn(int(oc), int(dc))))
                        except Exception:
                            v = None
                    if v is not None and v > 0:
                        key = "%s->%s" % (oc, dc)
                        rec["trips"][key] = \
                            rec["trips"].get(key, 0.0) + v
                        n_cells += 1
        # Fallback: getTripsToList()
        if not rec["trips"]:
            fn = getattr(odm, "getTripsToList", None)
            if callable(fn):
                try:
                    for tr in (_safe(fn, []) or []):
                        try:
                            o_obj = _safe(tr.getFrom)
                            d_obj = _safe(tr.getTo)
                            v = _safe(lambda: float(tr.getValue()
                                                    if hasattr(tr, "getValue")
                                                    else tr.getTrips()), None)
                            oid = _obj_id(o_obj) if o_obj is not None else None
                            did = _obj_id(d_obj) if d_obj is not None else None
                            if oid and did and v and v > 0:
                                key = "%s->%s" % (oid, did)
                                rec["trips"][key] = \
                                    rec["trips"].get(key, 0.0) + v
                                n_cells += 1
                        except Exception:
                            continue
                except Exception:
                    pass
        rec["_n_cells"] = n_cells
        dump["od_matrices"].append(rec)
        _log("OD %s | '%s' | cells=%d trips=%d"
             % (mid, mname[:40], n_cells,
                round(sum(rec["trips"].values()), 0)))
    _log("OD matrices exported: %d (non-empty: %d)"
         % (len(dump["od_matrices"]),
            sum(1 for m in dump["od_matrices"] if m.get("trips"))))
    _log("OD matrices exported: %d (non-empty: %d)"
         % (len(dump["od_matrices"]),
            sum(1 for m in dump["od_matrices"] if m.get("trips"))))

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dump, f, indent=1)
    _log("dump written -> %s" % out_path)
    return out_path


if __name__ == "__main__":
    export("aimsun_dump.json")
