"""plan_select_env.py -- the 3-layer stack the project is after:

    Layer 0  BASE: coordinated signal plans that already work (never re-derived
             from scratch -- that is what gridlocks a coordinated corridor).
    Layer 1  DEEP LEARNING: each decision PERIOD the agent selects WHICH plan
             from a per-junction LIBRARY of coordinated plans runs next
             ("cycles between the planned cycles"). Every action is a
             coordinated plan, so it CANNOT break coordination / gridlock.
    Layer 2  BUS PRIORITY: a pax-weighted green-extension overlay on whichever
             plan is active (bus-pax is already in the state + reward; the GE
             overlay hooks on top).

A learned adaptive PLAN-SELECTOR (SCATS-style plan library, trained) with
passenger weighting. Contrast lightsim_pax_env (free phase-select, breaks
coordination -- keep that one for the uncoordinated SUMO GRID).

PLAN LIBRARY (per junction, default 6 members):
  commissioned  the network's own program (base).
  cycle:0.8 / cycle:1.2  cycle-length variants (green phases scaled, clearance
                fixed, splits proportional -> internally coordinated).
  webster       Webster optimal cycle C=(1.5L+5)/(1-Y) with green split
                proportional to the measured flow ratio y_i (recomputed when
                selected). [Webster 1958]
  scats_ds      the SCATS degree-of-saturation plan we ran: keep the
                commissioned cycle, rebalance the green split to EQUALISE DS
                across approaches (g_i proportional to measured demand), holding
                offsets -> stays coordinated. Adapts each period.
  greenwave     offset member: shifts the program's phase pointer by the
                supplied offset (d/v_f along the arterial). Single-junction =>
                ~commissioned (offset is a corridor-level lever); pass an offset
                via `offsets`.

webster/scats_ds are DYNAMIC (measure demand, re-split on activation); the rest
are static programs registered once. All hold the commissioned phase ORDER and
clearance phases, so every member is coordinated.

Deps: gymnasium, pettingzoo, numpy, SUMO traci. v1: needs a SUMO smoke.
"""
import os
import sys
from typing import Dict, List, Optional

import numpy as np


def _ensure_traci():
    try:
        import traci  # noqa: F401
        return
    except Exception:
        pass
    sh = os.environ.get("SUMO_HOME")
    if sh:
        tools = os.path.join(sh, "tools")
        if os.path.isdir(tools) and tools not in sys.path:
            sys.path.append(tools)


_ensure_traci()
import traci  # noqa: E402

try:
    from pettingzoo import ParallelEnv
except Exception:
    ParallelEnv = object
import gymnasium as gym                 # noqa: E402
from gymnasium import spaces            # noqa: E402

DEFAULT_PLANS = ("commissioned", "cycle:0.8", "cycle:1.2",
                 "webster", "scats_ds", "greenwave")


def _is_green(state):
    return ('G' in state or 'g' in state) and 'y' not in state


class _PlanLib:
    """A junction's library of coordinated plans, derived from its commissioned
    SUMO program. Dynamic members (webster/scats_ds) re-split from live demand
    on activation; static members are registered once."""

    def __init__(self, tls_id, conn, plans, min_green, bus_occ, car_occ, offset=0.0):
        self.id = tls_id
        self.min_green = float(min_green)
        self.bus_occ = float(bus_occ)
        self.car_occ = float(car_occ)
        self.offset = float(offset)
        # The ACTIVE program, not [0]: on KG several TLS run a program whose
        # phase list differs from the first one returned, and setPhase with an
        # index from the wrong program is rejected ("phase index N is not in the
        # allowed range [0,0]") -- the junction then silently never switches.
        _logics = conn.trafficlight.getAllProgramLogics(tls_id)
        _active = conn.trafficlight.getProgram(tls_id)
        base = next((L for L in _logics if L.programID == _active), _logics[0])
        self.base = base
        self.base_pid = base.programID
        self.phases = list(base.phases)
        self.green_idx = [i for i, p in enumerate(self.phases) if _is_green(p.state)]
        if not self.green_idx:
            self.green_idx = list(range(len(self.phases)))
        self.total_green = sum(float(self.phases[i].duration)
                               for i in self.green_idx) or 1.0
        self.cycle = sum(float(p.duration) for p in self.phases) or 1.0
        # incoming lanes served (green) by each green phase
        links = conn.trafficlight.getControlledLinks(tls_id)
        self.links = links                     # for the live bus-GE overlay
        self._ge_used = 0.0                     # GE seconds spent this phase instance
        self._ge_phase = -1
        self.phase_lanes = {}
        for gi in self.green_idx:
            st = self.phases[gi].state
            served = set()
            for sig, lk in enumerate(links):
                if sig < len(st) and st[sig] in ('G', 'g') and lk:
                    served.add(lk[0][0])
            self.phase_lanes[gi] = served
        seen, lanes = set(), []
        for ln in conn.trafficlight.getControlledLanes(tls_id):
            if ln and ln not in seen:
                seen.add(ln); lanes.append(ln)
        self.lanes = lanes
        self.lane_len = {ln: max(conn.lane.getLength(ln), 1.0) for ln in lanes}
        # parse member specs
        self.members = []                      # (name, kind, param)
        for spec in plans:
            if spec.startswith("cycle:"):
                self.members.append((spec, "cycle", float(spec.split(":")[1])))
            elif spec in ("webster", "scats_ds", "greenwave"):
                self.members.append((spec, spec, None))
            else:
                self.members.append((spec, "static", None))
        # pre-build static members (commissioned + cycle variants)
        self.static_pid = {}
        for mi, (name, kind, param) in enumerate(self.members):
            if kind == "static":
                self.static_pid[mi] = self.base_pid
            elif kind == "cycle":
                pid = "lib_%s_c%d" % (tls_id, mi)
                self._register(conn, pid, self._scaled_phases(param))
                self.static_pid[mi] = pid
        self.n_plans = len(self.members)
        self.cur = -1                          # nothing applied yet

    # -- plan builders ------------------------------------------------------ #
    def _scaled_phases(self, s):
        out = []
        for p in self.phases:
            d = max(self.min_green, round(float(p.duration) * s)) if _is_green(p.state) \
                else float(p.duration)
            out.append(traci.trafficlight.Phase(
                d, p.state, getattr(p, "minDur", d), getattr(p, "maxDur", d)))
        return out

    def _green_phases(self, greens):
        """Base phases with green_idx[k] set to greens[k] s (floored), clearances kept."""
        pos = {gi: k for k, gi in enumerate(self.green_idx)}
        out = []
        for i, p in enumerate(self.phases):
            d = max(self.min_green, round(greens[pos[i]])) if i in pos else float(p.duration)
            out.append(traci.trafficlight.Phase(
                d, p.state, getattr(p, "minDur", d), getattr(p, "maxDur", d)))
        return out

    def _register(self, conn, pid, phases):
        """Register a program WITHOUT restarting the cycle: currentPhaseIndex is
        the phase the junction is on right now, so setProgram continues from
        where it is instead of snapping back to phase 0 (which would destroy the
        coordination the whole library exists to preserve)."""
        sub = getattr(self.base, "subParameter", None) or {}
        try:
            cur = int(conn.trafficlight.getPhase(self.id))
        except Exception:
            cur = 0
        if not (0 <= cur < len(phases)):
            cur = 0
        try:
            logic = traci.trafficlight.Logic(
                pid, getattr(self.base, "type", 0), cur, phases, sub)
            conn.trafficlight.setProgramLogic(self.id, logic)
            return True
        except Exception:
            return False

    def _apply_offset(self, conn, offset):
        """SUMO has no runtime program-offset setter, so apply the offset the way
        a controller would: jump the phase pointer to the phase that should be
        active `offset` seconds into the cycle and trim its remaining duration.
        A no-op offset leaves the running program untouched."""
        if abs(float(offset)) < 1e-6 or self.cycle <= 0:
            return
        shift = float(offset) % self.cycle
        acc = 0.0
        for i, p in enumerate(self.phases):
            d = float(p.duration)
            if acc + d > shift:
                try:
                    conn.trafficlight.setPhase(self.id, i)
                    conn.trafficlight.setPhaseDuration(
                        self.id, max(0.1, acc + d - shift))
                except Exception:
                    pass
                return
            acc += d

    def _phase_demand(self, conn):
        """pax-weighted vehicle count on each green phase's served lanes."""
        dem = []
        for gi in self.green_idx:
            d = 0.0
            for ln in self.phase_lanes.get(gi, ()):
                try:
                    for v in conn.lane.getLastStepVehicleIDs(ln):
                        try:
                            occ = self.bus_occ if conn.vehicle.getVehicleClass(v) == "bus" \
                                else self.car_occ
                        except Exception:
                            occ = self.car_occ
                        d += occ
                except Exception:
                    pass
            dem.append(max(d, 1e-3))
        return dem

    # -- activation --------------------------------------------------------- #
    def activate(self, conn, idx):
        idx = int(idx) % self.n_plans
        name, kind, param = self.members[idx]
        # Re-applying a static program every period would call setProgram on the
        # plan that is already running, restarting its cycle at phase 0 -- the
        # commissioned plan would never actually run as commissioned. Dynamic
        # members DO re-measure each period, but _register keeps the phase.
        if idx == self.cur and kind in ("static", "cycle"):
            return
        try:
            if kind in ("static", "cycle"):
                conn.trafficlight.setProgram(self.id, self.static_pid[idx])

            elif kind == "scats_ds":
                # SCATS DS plan: hold the commissioned cycle, split the green to
                # EQUALISE degree-of-saturation (g_i ~ demand_i), offsets intact.
                dem = self._phase_demand(conn)
                sd = sum(dem) or 1.0
                greens = [self.total_green * d / sd for d in dem]
                pid = "lib_%s_ds" % self.id
                if self._register(conn, pid, self._green_phases(greens)):
                    conn.trafficlight.setProgram(self.id, pid)

            elif kind == "webster":
                # Webster: optimal cycle from the flow ratio, green ~ y_i.
                dem = self._phase_demand(conn)
                sd = sum(dem) or 1.0
                L = max(0.0, self.cycle - self.total_green)            # lost time
                y = min(0.9, sd / (sd + self.total_green)) if (sd + self.total_green) > 0 else 0.5
                C = min(180.0, max(0.6 * self.cycle, (1.5 * L + 5.0) / max(1e-3, 1.0 - y)))
                tg = max(self.total_green, C - L)
                greens = [tg * d / sd for d in dem]
                pid = "lib_%s_web" % self.id
                if self._register(conn, pid, self._green_phases(greens)):
                    conn.trafficlight.setProgram(self.id, pid)

            elif kind == "greenwave":
                # Offset member: shift the base program by the corridor offset.
                # Single junction with offset 0 -> identical to commissioned.
                conn.trafficlight.setProgram(self.id, self.base_pid)
                self._apply_offset(conn, self.offset)
        except Exception:
            pass
        self.cur = idx
        self._ge_phase = -1                    # new plan instance -> fresh GE budget


class PlanSelectPaxParallelEnv(ParallelEnv):
    metadata = {"name": "plan_select_pax_v1"}

    def __init__(self, sumocfg, seed=0, gui=False, step_length=1.0,
                 period_s=90.0, plans=DEFAULT_PLANS,
                 bus_occ=40.0, car_occ=1.2, jam_veh_per_m=0.14,
                 min_green=6.0, max_steps=3600,
                 offsets: Optional[Dict[str, float]] = None,
                 agent_ids: Optional[List[str]] = None,
                 scales=None,
                 sumo_args=None,
                 bus_priority=True, ge_max_s=15.0, ge_detect_s=6.0, ge_step_s=2.0):
        # back-compat: scales=(...) builds commissioned + cycle members
        if scales is not None:
            plans = ["commissioned"] + ["cycle:%s" % s for s in scales if abs(s - 1.0) > 1e-6]
        self.sumocfg = sumocfg
        self.seed_val = int(seed)
        self.gui = bool(gui)
        self.step_length = float(step_length)
        self.period_s = float(period_s)
        self.plans = list(plans)
        self.bus_occ = float(bus_occ)
        self.car_occ = float(car_occ)
        self.jam = float(jam_veh_per_m)
        self.min_green = float(min_green)
        self.max_steps = float(max_steps)
        self.offsets = offsets or {}
        self.sumo_args = list(sumo_args or [])
        self.bus_priority = bool(bus_priority)
        self._ge = {}                          # tls -> [fires, ge_seconds]
        self.ge_max_s = float(ge_max_s)
        self.ge_detect_s = float(ge_detect_s)
        self.ge_step_s = float(ge_step_s)
        self._agent_whitelist = agent_ids
        self.conn = None
        self._sim_t = 0.0
        self._K = len(self.plans)
        self._MAXL = None

    def _start(self):
        import shutil
        sh = os.environ.get("SUMO_HOME", "")
        name = "sumo-gui" if self.gui else "sumo"
        binary = os.path.join(sh, "bin", name)
        if not (os.path.exists(binary) or os.path.exists(binary + ".exe")):
            binary = shutil.which(name) or name
        label = "plansel_%d" % self.seed_val
        _cmd = [binary, "-c", self.sumocfg, "--seed", str(self.seed_val),
                "--step-length", str(self.step_length),
                "--no-step-log", "true", "--no-warnings", "true"]
        _cmd += list(self.sumo_args)          # tripinfo / statistic outputs
        traci.start(_cmd, label=label)
        self.conn = traci.getConnection(label)

    def _build(self):
        ids = list(self.conn.trafficlight.getIDList())
        if self._agent_whitelist:
            ids = [i for i in ids if i in set(self._agent_whitelist)]
        self.libs = {i: _PlanLib(i, self.conn, self.plans, self.min_green,
                                 self.bus_occ, self.car_occ,
                                 float(self.offsets.get(i, 0.0))) for i in ids}
        self.agents = list(self.libs.keys())
        self.possible_agents = list(self.agents)
        if self._MAXL is None:
            self._MAXL = max((len(l.lanes) for l in self.libs.values()), default=1)
        self._obs_dim = self._K + self._MAXL + self._MAXL + 1
        self._ge = {i: [0, 0.0] for i in self.libs}
        self._ge_trig = {i: 0 for i in self.libs}

    def observation_space(self, agent):
        return spaces.Box(0.0, 1e6, shape=(self._obs_dim,), dtype=np.float32)

    def action_space(self, agent):
        return spaces.Discrete(self._K)

    def _is_bus(self, vid):
        # The KG bus vType is <vType id="bus" .../> with NO vClass attribute, so
        # SUMO reports the default class "passenger". A class-only test therefore
        # never matches a bus: the pax weighting saw 1.2 instead of 40 for every
        # bus and the GE overlay could never fire. Match the vType id as well.
        try:
            if "bus" in str(self.conn.vehicle.getTypeID(vid)).lower():
                return True
        except Exception:
            pass
        try:
            return self.conn.vehicle.getVehicleClass(vid) == "bus"
        except Exception:
            return False

    def _lane_pax(self, lane):
        pax = pax_stop = nveh = 0.0
        try:
            vids = self.conn.lane.getLastStepVehicleIDs(lane)
        except Exception:
            vids = []
        for v in vids:
            nveh += 1.0
            occ = self.bus_occ if self._is_bus(v) else self.car_occ
            pax += occ
            try:
                if self.conn.vehicle.getSpeed(v) < 0.1:
                    pax_stop += occ
            except Exception:
                pass
        return pax, pax_stop, nveh

    def _obs_one(self, lib: _PlanLib):
        plan_oh = np.zeros(self._K, np.float32)
        if 0 <= lib.cur < self._K:
            plan_oh[lib.cur] = 1.0
        dens = np.zeros(self._MAXL, np.float32)
        queue = np.zeros(self._MAXL, np.float32)
        bus_pax = 0.0
        for j, ln in enumerate(lib.lanes):
            if j >= self._MAXL:
                break
            pax, pax_stop, nveh = self._lane_pax(ln)
            cap = self.jam * lib.lane_len[ln]
            dens[j] = min(nveh / cap, 2.0) if cap > 0 else 0.0
            queue[j] = 1.0 if pax_stop > 0 else 0.0
            try:
                for v in self.conn.lane.getLastStepVehicleIDs(ln):
                    if self._is_bus(v):
                        bus_pax += (self.bus_occ - self.car_occ)
            except Exception:
                pass
        bus_pax = min(bus_pax / max(self.bus_occ, 1.0), 20.0)
        return np.concatenate([plan_oh, dens, queue, [bus_pax]]).astype(np.float32)

    def _reward_one(self, lib: _PlanLib):
        tot = 0.0
        for ln in lib.lanes:
            _, pax_stop, _ = self._lane_pax(ln)
            tot += pax_stop
        return -float(tot) / 100.0

    # -- LAYER 2: pax bus-priority green-extension overlay ------------------ #
    def _bus_ge(self, lib: _PlanLib):
        """Hold the CURRENT green a little longer when a bus is still being
        served on it and the phase is about to end -- a bounded green extension
        (<= ge_max_s per phase) ON TOP of whichever plan the DQN selected. This
        is the explicit transit-priority nudge; the plan underneath is
        unchanged, so coordination is preserved (GE only borrows from the
        phase's own slack up to the cap). Buses are weighted implicitly: the GE
        fires only for a bus, never a car."""
        tls = lib.id
        try:
            cur = int(self.conn.trafficlight.getPhase(tls))
            state = self.conn.trafficlight.getRedYellowGreenState(tls)
            now = self.conn.simulation.getTime()
            nxt = self.conn.trafficlight.getNextSwitch(tls)
        except Exception:
            return
        if cur != lib._ge_phase:                 # new phase instance -> reset budget
            lib._ge_phase = cur
            lib._ge_used = 0.0
        if 'y' in state or ('G' not in state and 'g' not in state):
            return                               # not a green phase
        remaining = float(nxt) - float(now)
        if remaining > self.ge_detect_s or lib._ge_used >= self.ge_max_s:
            return                               # not near end, or GE spent
        # bus on an incoming lane this phase is currently serving green?
        served = set()
        for sig, ch in enumerate(state):
            if ch in ('G', 'g') and sig < len(lib.links) and lib.links[sig]:
                served.add(lib.links[sig][0][0])
        bus_here = False
        for ln in served:
            try:
                if any(self._is_bus(v) for v in self.conn.lane.getLastStepVehicleIDs(ln)):
                    bus_here = True
                    break
            except Exception:
                pass
        if not bus_here:
            return
        # Count the TRIGGER separately from the application: a trigger without a
        # fire means SUMO rejected setPhaseDuration, which is a different problem
        # from the overlay never seeing a bus.
        self._ge_trig[tls] = int(self._ge_trig.get(tls, 0)) + 1
        ext = min(self.ge_step_s, self.ge_max_s - lib._ge_used)
        try:
            self.conn.trafficlight.setPhaseDuration(tls, remaining + ext)
            lib._ge_used += ext
            st = self._ge.setdefault(tls, [0, 0.0])
            st[0] += 1
            st[1] += ext
        except Exception:
            pass

    def ge_report(self):
        """Layer-2 audit: how often the pax GE overlay fired and how many green
        seconds it borrowed, in total and per junction."""
        fires = sum(v[0] for v in self._ge.values())
        secs = sum(v[1] for v in self._ge.values())
        per = sorted(v[0] for v in self._ge.values())
        return {"ge_triggers": int(sum(self._ge_trig.values())),
                "ge_fires": int(fires), "ge_seconds": round(secs, 1),
                "ge_junctions": int(sum(1 for v in self._ge.values() if v[0])),
                "ge_fires_min": int(per[0]) if per else 0,
                "ge_fires_med": int(per[len(per) // 2]) if per else 0,
                "ge_fires_max": int(per[-1]) if per else 0}

    def reset(self, seed=None, options=None):
        if seed is not None:
            self.seed_val = int(seed)
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
        self._start()
        self._build()
        self._sim_t = 0.0
        for lib in self.libs.values():
            lib.activate(self.conn, 0)          # start on the commissioned plan
        obs = {a: self._obs_one(self.libs[a]) for a in self.agents}
        return obs, {a: {} for a in self.agents}

    def step(self, actions: Dict[str, int]):
        for a in self.agents:
            self.libs[a].activate(self.conn, actions.get(a, self.libs[a].cur))
        n = max(1, int(round(self.period_s / self.step_length)))
        for _ in range(n):
            if self.bus_priority:                 # Layer 2: pax GE overlay each tick
                for lib in self.libs.values():
                    self._bus_ge(lib)
            self.conn.simulationStep()
            self._sim_t += self.step_length
        obs = {a: self._obs_one(self.libs[a]) for a in self.agents}
        rew = {a: self._reward_one(self.libs[a]) for a in self.agents}
        done = self._sim_t >= self.max_steps
        terms = {a: False for a in self.agents}
        truncs = {a: done for a in self.agents}
        if done:
            self.agents = []
        return obs, rew, terms, truncs, {a: {} for a in list(rew)}

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None


class PlanSelectPaxSingleEnv(gym.Env):
    """Single-junction wrapper for a plain SB3 DQN (others keep commissioned)."""
    metadata = {"render_modes": []}

    def __init__(self, sumocfg, agent_id, **kw):
        # Build over ALL junctions so MAXL -- and therefore the obs width -- is
        # the NETWORK one, then expose a single agent. Building with
        # agent_ids=[agent_id] makes the width junction-specific, so a policy
        # trained here could not be applied to the parallel env at all (the
        # same trap lightsim_pax_env.LightSimPaxSingleEnv documents).
        self._p = PlanSelectPaxParallelEnv(sumocfg, **kw)
        self._aid = agent_id
        self._p.reset()
        self._p.agents = [agent_id]
        self.observation_space = self._p.observation_space(agent_id)
        self.action_space = self._p.action_space(agent_id)
        self._last_obs = None

    def reset(self, seed=None, options=None):
        obs, infos = self._p.reset(seed=seed)
        self._p.agents = [self._aid]
        self._last_obs = obs[self._aid]
        return obs[self._aid], infos[self._aid]

    def step(self, action):
        obs, rew, terms, truncs, infos = self._p.step({self._aid: int(action)})
        if not self._p.agents:
            return (self._last_obs, rew.get(self._aid, 0.0), True, True, {})
        self._last_obs = obs[self._aid]
        return (obs[self._aid], rew[self._aid], terms[self._aid],
                truncs[self._aid], infos[self._aid])

    def close(self):
        self._p.close()


if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "sumo_bridge", "kg_scenario", "kg.sumocfg")
    env = PlanSelectPaxParallelEnv(os.path.abspath(cfg), max_steps=900)
    obs, _ = env.reset()
    print("agents=%d  obs_dim=%d  library=%s" % (
        len(env.agents), env._obs_dim, list(env.plans)))
    tot = 0.0
    for k in range(10):
        acts = {a: env.action_space(a).sample() for a in env.agents}
        obs, rew, term, trunc, info = env.step(acts)
        tot += sum(rew.values())
        if not env.agents:
            break
    print("10 periods (random plans), sum reward = %.1f" % tot)
    env.close()
