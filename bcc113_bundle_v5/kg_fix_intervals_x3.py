"""
kg_fix_intervals_x3.py -- one-shot repair after the May-model misapply.

Multiplies every interval-schedule mean headway by 3 (undoing the shorter
headways accidentally written from the May model's sparse design), returning
KG to the 'restored v2' baseline: uniform fixed lists @ original counts +
interval means 300/400/200...

RUN inside Aimsun, KG open. Then File > Save, reopen, verify via
check_car_count.py (expect the same ~79 buses / obj ~137 state you measured
at 14:31, or very close).
"""

from PyANGKernel import GKSystem

model = GKSystem.getSystem().getActiveModel()
cat = model.getCatalog()
lines = cat.getObjectsByType(model.getType("GKPublicLine"))
lines = list(lines.values()) if isinstance(lines, dict) else list(lines or [])


def secs(t):
    try:
        return int(t.toSeconds())
    except Exception:
        return None


def dur(s):
    from PyANGKernel import GKTimeDuration
    h, rem = divmod(int(max(0, round(s))), 3600)
    m, sec = divmod(rem, 60)
    return GKTimeDuration(h, m, sec)


n = 0
for line in lines:
    try:
        lid = line.getId()
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
            if len(deps) != 1:
                continue          # only interval-type (single mean-time dep)
            mt = None
            try:
                mt = deps[0].getMeanTime()
            except Exception:
                pass
            m = secs(mt) if mt else None
            if not m or m <= 0:
                continue
            # Current state = May-model headways (900/1200/600...) written by
            # kg_pt_apply_true. Baseline v2 wants them /3 (300/400/200...).
            new_m = max(30, int(round(m / 3.0)))
            try:
                deps[0].setMeanTime(dur(new_m))
                reread = None
                try:
                    rd = list(sch.getDepartureTimes())[0].getMeanTime()
                    reread = secs(rd) if rd else None
                except Exception:
                    pass
                if reread is None or abs(reread - new_m) > 1:
                    sch.removeDepartureTimes()
                    sch.addDepartureTime(deps[0])
                print("[FIX] line=%s sched=%d mean %ds -> %ds"
                      % (lid, si, m, new_m))
                n += 1
            except Exception as e:
                print("[FIX] FAILED line=%s sched=%d: %r" % (lid, si, e))

print("[FIX] intervals repaired: %d" % n)
print("[FIX] NOW: File > Save, close & reopen, verify with check_car_count.")
