"""
pt_baseline_guard.py -- KG-only safety net for the leaked PT timetable.

Detects whether the loaded KG model's public-line timetables are at the
leaked (~x3) supply or the true baseline, restores them when inflated, and
reports whether a save+reopen is required before simulations will see the
fix (the running session keeps its load-time PT snapshot -- probe-proven).

Anchors are the verified morning-baseline samples:
    fixed     (10039694,0,0)=69  (10039743,0,0)=66  (10042296,0,0)=24 deps
    interval  (10041703,0,0)=300 (10041703,0,1)=400 (10041752,0,0)=200 mean
"""

DIVISOR = 3.0

ANCHOR_FIXED = {
    (10039694, 0, 0): 69,
    (10039743, 0, 0): 66,
    (10042296, 0, 0): 24,
}
ANCHOR_INTERVAL = {
    (10041703, 0, 0): 300,
    (10041703, 0, 1): 400,
    (10041752, 0, 0): 200,
}


def _secs(t):
    try:
        return int(t.toSeconds())
    except Exception:
        return None


def _pt_dur(s):
    from PyANGKernel import GKTimeDuration
    h, rem = divmod(int(max(0, round(s))), 3600)
    m, sec = divmod(rem, 60)
    return GKTimeDuration(h, m, sec)


def _iter_schedules(model):
    ltype = model.getType("GKPublicLine")
    objs = model.getCatalog().getObjectsByType(ltype)
    lines = list(objs.values()) if isinstance(objs, dict) else list(objs or [])
    for line in lines:
        try:
            lid = line.getId()
            lname = line.getName()
        except Exception:
            continue
        for ti, tt in enumerate(line.getTimeTables() or []):
            try:
                schs = list(tt.getSchedules() or [])
            except Exception:
                continue
            for si, sch in enumerate(schs):
                yield lid, lname, ti, si, sch


def classify_state(model):
    """Return ('ok'|'inflated'|'unknown', details_str) using anchor samples."""
    ratios = []
    found = []
    for lid, lname, ti, si, sch in _iter_schedules(model):
        key = (lid, ti, si)
        try:
            deps = list(sch.getDepartureTimes())
        except Exception:
            continue
        if not deps:
            continue
        if len(deps) == 1:
            mt = None
            try:
                mt = deps[0].getMeanTime()
            except Exception:
                pass
            m = _secs(mt) if mt else None
            if key in ANCHOR_INTERVAL and m:
                found.append(key)
                ratios.append(m / float(ANCHOR_INTERVAL[key]))
        else:
            if key in ANCHOR_FIXED:
                found.append(key)
                ratios.append(len(deps) / float(ANCHOR_FIXED[key]))
    if len(found) < 3:
        return "unknown", "only %d anchor schedules found" % len(found)
    r = sum(ratios) / len(ratios)
    if all(x > 2.0 for x in ratios):
        return "inflated", "anchor ratios avg %.2f (expect ~%.0f)" % (r, DIVISOR)
    if all(0.8 < x < 1.25 for x in ratios):
        return "ok", "anchor ratios avg %.2f" % r
    return "unknown", "mixed anchor ratios %s" % [round(x, 2) for x in ratios]


def restore(model):
    """Write true baselines back (fixed /3 counts rebuilt evenly over the
    preserved span; interval means x3). Returns number of schedules written."""
    n = 0
    for lid, lname, ti, si, sch in _iter_schedules(model):
        try:
            deps = list(sch.getDepartureTimes())
        except Exception:
            continue
        if not deps:
            continue
        if len(deps) == 1:
            mt = None
            try:
                mt = deps[0].getMeanTime()
            except Exception:
                pass
            m = _secs(mt) if mt else None
            if not m or m <= 0:
                continue
            new_mean = int(round(m * DIVISOR))
            if new_mean == m:
                continue
            try:
                deps[0].setMeanTime(_pt_dur(new_mean))
                reread = None
                try:
                    rd = list(sch.getDepartureTimes())[0].getMeanTime()
                    reread = _secs(rd) if rd else None
                except Exception:
                    pass
                if reread is None or abs(reread - new_mean) > 1:
                    sch.removeDepartureTimes()
                    sch.addDepartureTime(deps[0])
                n += 1
            except Exception:
                continue
        else:
            n_cur = len(deps)
            n0 = int(round(n_cur / DIVISOR))
            if n0 >= n_cur or n_cur < 2:
                continue
            t_first = _secs(deps[0].getDepartureTime())
            t_last = _secs(deps[-1].getDepartureTime())
            if t_first is None or t_last is None or t_last <= t_first:
                continue
            step = (t_last - t_first) / (n0 - 1.0)
            proto = deps[0]
            try:
                sch.removeDepartureTimes()
                for i in range(n0):
                    nd = type(proto)()
                    nd.setDepartureTime(_pt_dur(t_first + i * step))
                    sch.addDepartureTime(nd)
                try:
                    sch.sortDepartureTimes()
                except Exception:
                    pass
                n += 1
            except Exception:
                continue
    return n


def ensure(model, log=print):
    """Classify -> restore if inflated -> attempt save. Returns status string.

    'needs-reopen' means the file was fixed and saved but the RUNNING session
    still generates the old supply: close & reopen the model, then rerun."""
    status, detail = classify_state(model)
    log("[PT-BASELINE] state=%s (%s)" % (status, detail))
    if status == "ok":
        return "ok"
    if status != "inflated":
        log("[PT-BASELINE] WARNING: cannot verify PT baseline -- continuing "
            "UNVERIFIED. Send Zeke the anchor details.")
        return "unknown"
    n = restore(model)
    saved = False
    try:
        saved = bool(model.save())
    except Exception:
        try:
            model.save()
            saved = True
        except Exception:
            saved = False
    log("[PT-BASELINE] restored %d schedules | model.save() -> %s"
        % (n, "OK" if saved else "FAILED -- use File > Save"))
    log("[PT-BASELINE] CLOSE & REOPEN the model now, then rerun this script.")
    return "needs-reopen"
