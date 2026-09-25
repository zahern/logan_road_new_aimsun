"""
pt_inject.py -- runtime PT-frequency scaling via vehicle injection.

WHY: mutating GKPublicLine departure objects provably does NOT reach the
simulation (2026-08-25 probes: catalog verified correct, replications
byte-identical across levels; historical Logan BUSx2/x3 produced ZERO buses).
The simulator generates transit vehicles from its own internal snapshot, so
schedule edits never take effect.

This module scales frequency the way the simulator itself does: by creating
real PT vehicles with AKIPTEnterVeh() at synthesized departure times.

Design
------
CALIBRATE (scalar == 1.0): natural bus entries are observed via
AAPIEnterVehicle on each line's FIRST section and persisted to
<corridor>/pt_entry_calibration.csv.

INJECT  (scalar > 1.0): the calibrated per-line pattern is replayed and extra
vehicles are synthesized -- uniformly re-spaced across the original service
span at round(D * scalar) departures -- then created with AKIPTEnterVeh() at
their due times. Natural departures run as usual.

SUPPRESS (scalar < 1.0): natural departures are REMOVED at entry
(AKIRemoveVehicle on the line's first section) using a Bresenham keep/remove
sequence so the retained set is evenly distributed: 0.5 keeps every 2nd bus,
0.75 keeps 3 of every 4, etc.

Nothing touches the model catalog, so nothing can leak into saved files and
every replication is independently reproducible.
"""

import heapq
import os


class PTInjectionManager:
    def __init__(self):
        self.armed = False
        self.scalar = 0.0
        self.calibrating = False
        self.corridor_dir = ""
        self.bus_pos = -1
        # line_id -> set(first-section ids) for entry attribution
        self.line_first_secs = {}
        self.sec_to_lines = {}
        # calibration: line_id -> sorted list of natural entry times
        self.base_entries = {}
        self.session_entries = {}       # live capture during this run
        # injection plan: line_id -> sorted list of ALL target times
        self.plan = {}
        self.cursor = {}                # line_id -> next index into plan
        self.injected_count = 0
        self.skipped_no_type_until = -1.0
        self.errors_logged = 0
        # suppression state -- MUST exist before configure() so disarmed
        # corridors (Logan) never hit AttributeError on per-tick access
        self.pending_removals = []
        self.removed_count = 0
        self.natural_count = 0
        self.suppressing = False
        self._suppress_counter = {}

    # ── configuration ────────────────────────────────────────────────────────
    def configure(self, scalar, corridor_dir):
        """Arm the manager for this run. scalar < 1 => suppress; 1 => calibrate;
        > 1 => inject extras."""
        self.scalar = float(scalar or 0.0)
        self.corridor_dir = corridor_dir or ""
        self.calibrating = abs(self.scalar - 1.0) < 1e-9
        self.suppressing = self.scalar < 1.0 - 1e-9
        self.armed = True
        self.reset_run_state()

    def reset_run_state(self):
        self.session_entries = {}
        self.plan = {}
        self.cursor = {}
        self.injected_count = 0
        self.removed_count = 0
        self.natural_count = 0
        # Bresenham keep/remove state per line for suppression mode
        self._suppress_counter = {}
        # Deferred removals (section_id, veh_id, line_id): AKIRemoveVehicle is
        # NOT safe inside the AAPIEnterVehicle callback (kernel reentrancy) --
        # queued here, executed on the next PostManage tick.
        self.pending_removals = []

    def should_remove(self, line_id):
        """Suppression decision (scalar < 1 only): deterministic even thinning.
        Returns True when THIS entry should be removed from service."""
        if not self.suppressing:
            return False
        lid = int(line_id)
        n = self._suppress_counter.get(lid, 0) + 1
        self._suppress_counter[lid] = n
        # keep if floor(n*scalar) advanced past floor((n-1)*scalar)
        keep = int(n * self.scalar) > int((n - 1) * self.scalar)
        return not keep

    def queue_removal(self, section_id, veh_id, line_id):
        self.pending_removals.append((int(section_id), int(veh_id), int(line_id)))

    def pop_pending_removals(self):
        out = list(getattr(self, "pending_removals", None) or [])
        self.pending_removals = []
        return out

    def note_removed(self):
        self.removed_count += 1

    def note_natural(self, line_id, time_s):
        self.natural_count += 1
        if self.calibrating:
            self.session_entries.setdefault(int(line_id), []).append(float(time_s))

    def set_bus_pos(self, pos):
        self.bus_pos = int(pos)

    # ── line registry (engine fills this at lazy-init) ───────────────────────
    def register_line(self, line_id, first_section_ids):
        self.line_first_secs[int(line_id)] = set(int(s) for s in first_section_ids)
        for s in self.line_first_secs[int(line_id)]:
            self.sec_to_lines.setdefault(int(s), set()).add(int(line_id))

    # ── entry capture (called from AAPIEnterVehicle) ─────────────────────────
    def on_enter(self, section_id, time_s, veh_is_bus):
        if not self.armed:
            return
        if not veh_is_bus:
            return
        lines = self.sec_to_lines.get(int(section_id))
        if not lines:
            return
        for lid in lines:
            self.session_entries.setdefault(lid, []).append(float(time_s))

    # ── calibration persistence ──────────────────────────────────────────────
    def calibration_path(self):
        return os.path.join(self.corridor_dir or "", "pt_entry_calibration.csv")

    def save_calibration(self):
        path = self.calibration_path()
        if not path or not self.session_entries:
            return 0
        n = 0
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("line_id,entry_time_s\n")
                for lid in sorted(self.session_entries):
                    for t in sorted(self.session_entries[lid]):
                        f.write("%d,%d\n" % (lid, int(round(t))))
                        n += 1
        except Exception:
            return -1
        return n

    def load_calibration(self):
        """Load most-recent calibration into self.base_entries. Returns count."""
        path = self.calibration_path()
        self.base_entries = {}
        if not path or not os.path.isfile(path):
            return 0
        try:
            with open(path, encoding="utf-8") as f:
                for row in f.read().splitlines()[1:]:
                    parts = row.split(",")
                    if len(parts) != 2:
                        continue
                    lid = int(parts[0].strip())
                    t = float(parts[1].strip())
                    self.base_entries.setdefault(lid, []).append(t)
        except Exception:
            self.base_entries = {}
            return -1
        for lid in self.base_entries:
            self.base_entries[lid].sort()
        return sum(len(v) for v in self.base_entries.values())

    # ── planning ─────────────────────────────────────────────────────────────
    @staticmethod
    def synthesize(base_times, scalar):
        """Target departure list for this frequency multiple.

        Natural departures are IMMOVABLE (the simulator generates them itself),
        so scaling means KEEPING all originals and inserting exactly
        round(D*scalar) - D extras, allocated across the gaps proportionally
        to gap length (largest-remainder rounding so the total is exact) and
        placed evenly inside their gap.
        """
        cur = sorted(float(t) for t in base_times)
        d = len(cur)
        if d < 2:
            return list(cur)
        target = max(d, int(round(d * float(scalar))))
        extras = target - d
        if extras <= 0:
            return list(cur)
        gaps = [cur[i + 1] - cur[i] for i in range(d - 1)]
        span = sum(gaps)
        if span <= 0:
            return list(cur)
        # largest-remainder allocation of extras across gaps
        raw = [g / span * extras for g in gaps]
        alloc = [int(x) for x in raw]
        rem = extras - sum(alloc)
        order = sorted(range(len(gaps)), key=lambda i: raw[i] - int(raw[i]),
                       reverse=True)
        for i in range(rem):
            alloc[order[i % len(order)]] += 1
        out = []
        for i, t in enumerate(cur):
            out.append(t)
            a, b = cur[i], cur[i + 1] if i + 1 < d else None
            if b is None or alloc[i] <= 0:
                continue
            step = (b - a) / (alloc[i] + 1)
            for k in range(1, alloc[i] + 1):
                out.append(a + k * step)
        return sorted(out)

    def build_plans(self):
        """Create per-line injection plans for this run's scalar."""
        self.plan = {}
        self.cursor = {}
        if self.calibrating or self.suppressing:
            return 0
        total = 0
        for lid, base in self.base_entries.items():
            base_sorted = sorted(base)
            base_set = set(base_sorted)
            tgt = self.synthesize(base_sorted, self.scalar)
            # inject ONLY the extras (natural departures happen by themselves)
            extras = sorted(t for t in tgt if t not in base_set)
            if extras:
                self.plan[lid] = extras
                self.cursor[lid] = 0
                total += len(extras)
        return total

    # ── runtime ──────────────────────────────────────────────────────────────
    def due_injections(self, time_s):
        """Advance cursors and return line_ids whose extra bus is due now."""
        out = []
        for lid, times in self.plan.items():
            ci = self.cursor.get(lid, 0)
            while ci < len(times) and times[ci] <= time_s:
                out.append(lid)
                ci += 1
            self.cursor[lid] = ci
        return out

    def note_injected(self, line_id):
        self.injected_count += 1

    def summary(self):
        return ("injected=%d removed=%d natural=%d | calibrating=%s | "
                "suppressing=%s | scalar=%.2f | base_lines=%d | plan_lines=%d"
                % (self.injected_count, self.removed_count, self.natural_count,
                   self.calibrating, self.suppressing, self.scalar,
                   len(self.base_entries), len(self.plan)))


MANAGER = PTInjectionManager()
