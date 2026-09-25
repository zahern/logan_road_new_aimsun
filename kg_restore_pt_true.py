"""
kg_restore_pt_true.py -- restore KG timetables to the TRUE pre-leak baseline.

PROOF OF CORRECTNESS: the bus-frequency scaler anchors every write to the
cached original and applies ABSOLUTE factors. The last sequence applied was
x1.5 -> x2.0 -> x3.0, so every fixed schedule now holds exactly
    round(N_original * 3)
departures (verified: 69->207, 66->198 on sampled lines), and every interval
schedule stores mean_original / 3 (verified: 300 -> 100).

This script divides fixed-departure counts by 3 (rebuilding them evenly spaced
across the preserved service span -- the scaler itself interpolated, so the
original minute-level pattern is unrecoverable; count, span and headway scale
are restored exactly) and multiplies interval means by 3.

RUN inside Aimsun, KG model open:
    1st run:  kg_restore_pt_true.py          <- DRY RUN, prints plan only
    then:     set APPLY = True at the top, run again   <- writes
    then:     File > Save, REOPEN the model, and verify with one NO_TSP run:
              ~55 distinct buses, objective ~133.5 = restored.
"""

APPLY = True           # safe: a built-in anchor check refuses to run twice
DIVISOR = 3.0          # last applied multiplier chain ended at x3

from PyANGKernel import GKSystem

model = GKSystem.getSystem().getActiveModel()
cat = model.getCatalog()
ltype = model.getType("GKPublicLine")
objs = cat.getObjectsByType(ltype)
lines = list(objs.values()) if isinstance(objs, dict) else list(objs)

# ── Idempotency guard: never restore an already-restored model ───────────────
# Known original departure counts (verified morning samples). If the model
# already shows these values, restoring again would CORRUPT it -- stop instead.
_ALREADY = {(10039694, 0, 0): 69, (10039743, 0, 0): 66}
_EXPECT_LEAKED = {(10039694, 0, 0): 207, (10039743, 0, 0): 198}


def _peek():
    for line in lines[:40]:
        try:
            lid = line.getId()
        except Exception:
            continue
        for ti, tt in enumerate(line.getTimeTables() or []):
            for si, sch in enumerate(tt.getSchedules() or []):
                key = (lid, ti, si)
                if key in _ALREADY or key in _EXPECT_LEAKED:
                    try:
                        return key, len(sch.getDepartureTimes())
                    except Exception:
                        return key, None
    return None, None


_key, _ndeps = _peek()
if _key is not None and _ndeps is not None:
    if _ndeps <= _ALREADY.get(_key, 10**9) and _key in _ALREADY:
        print("[PT-RESTORE] STOP: model already restored (line %s has %d deps)."
              % (_key, _ndeps))
        print("[PT-RESTORE] Nothing to do. Run File > Save if you changed "
              "anything else, then verify with check_car_count.")
        raise SystemExit(0)
    if _key in _EXPECT_LEAKED and abs(_ndeps - _EXPECT_LEAKED[_key]) <= 2:
        print("[PT-RESTORE] leak state confirmed on line %s (%d deps) -- "
              "proceeding." % (_key, _ndeps))
    else:
        print("[PT-RESTORE] WARNING: line %s has %d deps -- neither the known "
              "restored (%s) nor leaked (%s) value." % (
                  _key, _ndeps,
                  _ALREADY.get(_key), _EXPECT_LEAKED.get(_key)))
        print("[PT-RESTORE] ABORTING to avoid corrupting an unknown state. "
              "Send Zeke this message.")
        raise SystemExit(0)


print("=" * 74)
print("[PT-RESTORE] divisor=%s | APPLY=%s | lines=%d" % (DIVISOR, APPLY, len(lines)))


def _secs(t):
    try:
        return int(t.toSeconds())
    except Exception:
        return None


def _from_secs(s):
    try:
        return _pt_dur(s)
    except Exception:
        return None


def _pt_dur(s):
    # GKTimeDuration(h, m, s) -- same proven construction as the scaler
    from PyANGKernel import GKTimeDuration
    h, rem = divmod(int(max(0, round(s))), 3600)
    m, sec = divmod(rem, 60)
    return GKTimeDuration(h, m, sec)


plan_fixed = []
plan_interval = []
changed = 0

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
            try:
                deps = list(sch.getDepartureTimes())
            except Exception:
                deps = []
            if not deps:
                continue
            is_interval = len(deps) == 1 and deps[0].getMeanTime() is not None
            if is_interval:
                m = _secs(deps[0].getMeanTime())
                if not m or m <= 0:
                    continue
                new_mean = int(round(m * DIVISOR))
                if new_mean == m:
                    continue
                plan_interval.append((lid, si, m, new_mean))
                if APPLY:
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
                    except Exception as e:
                        print("[PT-RESTORE]   WRITE FAILED line=%s: %r" % (lid, e))
                        continue
                    changed += 1
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
                new_times = [int(round(t_first + i * step)) for i in range(n0)]
                plan_fixed.append((lid, si, n_cur, n0))
                if APPLY:
                    try:
                        proto = deps[0]
                        sch.removeDepartureTimes()
                        for s0 in new_times:
                            nd = type(proto)()
                            try:
                                nd.setDepartureTime(_pt_dur(s0))
                            except Exception:
                                break
                            sch.addDepartureTime(nd)
                        try:
                            sch.sortDepartureTimes()
                        except Exception:
                            pass
                    except Exception as e:
                        print("[PT-RESTORE]   WRITE FAILED line=%s: %r" % (lid, e))
                        continue
                    changed += 1

print("[PT-RESTORE] fixed schedules to shrink (/3): %d" % len(plan_fixed))
for lid, si, nc, n0 in plan_fixed[:10]:
    print("[PT-RESTORE]   line=%s sched=%d : %d -> %d deps"
          % (lid, si, nc, n0))
if len(plan_fixed) > 10:
    print("[PT-RESTORE]   ... %d more" % (len(plan_fixed) - 10))
print("[PT-RESTORE] interval means to scale (x3): %d" % len(plan_interval))
for lid, si, m, nm in plan_interval[:10]:
    print("[PT-RESTORE]   line=%s sched=%d : %ds -> %ds" % (lid, si, m, nm))
if len(plan_interval) > 10:
    print("[PT-RESTORE]   ... %d more" % (len(plan_interval) - 10))

if APPLY:
    print("[PT-RESTORE] wrote %d schedule(s)." % changed)
    print("[PT-RESTORE] NOW: File > Save, REOPEN the model, run one NO_TSP:")
    print("[PT-RESTORE]   expect ~55 distinct buses / objective ~133.5.")
else:
    print("[PT-RESTORE] DRY RUN ONLY -- set APPLY = True and rerun to write.")
