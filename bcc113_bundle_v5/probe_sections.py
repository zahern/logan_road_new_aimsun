"""probe_sections.py -- static section/detector probe for Logan side approaches.

WHY: five side sections (13079, 16090, 5880, 3161, 16064) sit on the OD seed
(1800/2911 vph) until live measurement arrives, and the rolling counter
(roll_ctr) never ticks for them. From the offline dump they are all REAL
1-lane approaches (not centroid connectors, not self-loops), so this probe
confirms live-model truth: section type, geometry, node types, and which
detectors sit on each section.

RUN from the Aimsun Python console with Logan_RD_for_QUT_with_detectors.ang
open (no simulation needed -- read-only, changes nothing):
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\probe_sections.py").read())

Self-diagnosing: every API call is guarded; if a lookup pattern fails it
prints the available attributes so the exact call can be fixed from the
pasted output.
"""
import traceback as _tb

_SECS = [13079, 16090, 5880, 3161, 16064, 16488, 3690, 60499]


def _say(msg):
    try:
        print("[PROBE] " + str(msg))
    except Exception:
        pass


def _try(obj, names):
    out = {}
    for n in names:
        try:
            f = getattr(obj, n, None)
            out[n] = f() if callable(f) else f
        except Exception as e:
            out[n] = "ERR:%r" % (e,)
    return out


def _run():
    from PyANGKernel import GKSystem
    _m = GKSystem.getSystem().getActiveModel()
    if _m is None:
        _say("no active model -- open the Logan .ang first.")
        return
    try:
        _say("model=" + str(_m.getName()))
    except Exception:
        pass
    _cat = _m.getCatalog()

    def _find(sid):
        for meth in ("find", "findById"):
            try:
                o = getattr(_cat, meth)(int(sid))
                if o is not None:
                    return o, meth
            except Exception:
                pass
        return None, "not-found"

    for sid in _SECS:
        o, how = _find(sid)
        if o is None:
            _say("sec %s: NOT FOUND in catalog (%s)" % (sid, how))
            continue
        _say("sec %s: via=%s pytype=%s" % (sid, how, type(o).__name__))
        _say("   attrs=" + str(_try(o, (
            "getName", "getLength", "getLanes", "nbLanes",
            "getSpeed", "getCapacity", "isVirtual", "isConnector",
            "isCentroidConnection", "getTypeName", "getId"))))
        for nm in ("getOriginNode", "getDestinationNode",
                   "getOrigin", "getDestination"):
            try:
                nd = getattr(o, nm)()
                if nd is not None:
                    _say("   %s -> id=%s name=%s pytype=%s" % (
                        nm, _try(nd, ("getId",)) .get("getId"),
                        _try(nd, ("getName",)).get("getName"),
                        type(nd).__name__))
                    break
            except Exception:
                pass

    # detectors: try catalog enumeration, report what exists per section
    _dets = None
    for meth in ("getObjectsByType", "findAllByType", "getObjects"):
        try:
            _dets = list(getattr(_cat, meth)("GKDetector"))
            _say("detectors via %s: %d" % (meth, len(_dets)))
            break
        except Exception as e:
            continue
    if not _dets:
        _say("detector enumeration unsupported here; catalog attrs sample: "
             + str([a for a in dir(_cat) if "etect" in a or "bject" in a][:20]))
        _say("fallback: check detectors manually (View > Detectors) on secs "
             + ",".join(str(s) for s in _SECS))
        return
    _by_sec = {}
    for d in _dets:
        try:
            _sec = None
            for meth in ("getSection", "getSectionId"):
                try:
                    _sec = getattr(d, meth)()
                    break
                except Exception:
                    pass
            _sid = getattr(_sec, "getId", lambda: _sec)()
            _by_sec.setdefault(int(_sid), []).append(d)
        except Exception:
            pass
    for sid in _SECS:
        _dd = _by_sec.get(int(sid), [])
        _say("sec %s: %d detector(s)" % (sid, len(_dd)))
        for d in _dd:
            _say("   det attrs=" + str(_try(d, (
                "getId", "getName", "getInitialPosition", "getFinalPosition",
                "getLane", "getExternalId", "getTypeName"))))


try:
    _run()
    _say("finished.")
except Exception:
    _say("FAILED -- traceback below (paste this back):")
    _tb.print_exc()
