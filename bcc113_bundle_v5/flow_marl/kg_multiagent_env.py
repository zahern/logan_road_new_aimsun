"""RLlib multi-agent signal-control env for the KG SUMO corridor.

Flow tutorial14 pattern: one agent per signalised intersection, local
observation, discrete action, shared/local reward, one policy per agent.

Actions are wired to the same contract as the Aimsun component
`shared_tsp_engine/flow_policy.py`:

    0 NONE  keep the current plan
    1 GE    extend the current green
    2 ER    shorten (truncate) the current green
    3 INS   insert / advance a bus phase

Observation (per agent), fixed size:
    [queue_0/maxq, speed_0/maxspeed, ..., queue_3/maxq, speed_3/maxspeed,
     phase/n_phases, time_to_switch/horizon, n_phases/10]
Reward: -sum(halting vehicles on incoming approaches); optionally shared.
"""
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from ray.rllib.env.multi_agent_env import MultiAgentEnv
import traci

from configs import kg as K


class KGMultiAgentEnv(MultiAgentEnv):
    def __init__(self, config=None):
        super().__init__()
        self.cfg = dict(config or {})
        self.scenario = self.cfg.get("sumocfg", K.SUMOCFG)
        self.sumo_binary = self.cfg.get("sumo_binary", K.SUMO_BINARY)
        self.agents = list(self.cfg.get("agents", K.AGENTS))
        self.agent_ids = list(self.agents)
        self.horizon = int(self.cfg.get("horizon", K.HORIZON_S))
        self.warmup = int(self.cfg.get("warmup", K.WARMUP_S))
        self.action_every = int(self.cfg.get("action_every", K.ACTION_EVERY_S))
        self.shared_reward = bool(self.cfg.get("shared_reward", K.SHARED_REWARD))
        self.gui = bool(self.cfg.get("gui", False))
        self.ge_extend = float(self.cfg.get("ge_extend_s", K.GE_EXTEND_S))
        self.er_trunc = float(self.cfg.get("er_trunc_s", K.ER_TRUNC_S))
        self.min_green = float(self.cfg.get("min_green_s", K.MIN_GREEN_S))
        self._n_phases = {a: 4 for a in self.agents}
        self._last_wait = {}
        self._last_bus_ids = {}
        self._veh_ids = set()
        self._parts = {}

        n_obs = 2 * K.MAX_APPROACHES + 3
        _obs_box = spaces.Box(
            low=0.0, high=1.0, shape=(n_obs,), dtype=np.float32)
        # Discrete(4) = NONE / GE / ER / INS (matches flow_policy.py).
        _act_box = spaces.Discrete(len(K.ACTION_NAMES))
        # Ray >=2.3 new API stack: per-agent space dicts.
        self.observation_spaces = {a: _obs_box for a in self.agents}
        self.action_spaces = {a: _act_box for a in self.agents}
        # Old API stack still reads the singular attributes.
        self.observation_space = _obs_box
        self.action_space = _act_box
        self._connected = False

    # ------------------------------------------------------------------ SUMO
    def _start(self):
        if self._connected:
            try:
                traci.close()
            except Exception:
                pass
            self._connected = False
        cmd = [self.sumo_binary, "-c", self.scenario,
               "--start", "--no-step-log", "true",
               "--duration-log.disable", "true",
               "--end", str(self.horizon)]
        if self.gui:
            cmd = [c.replace("sumo.exe", "sumo-gui.exe") for c in cmd]
        traci.start(cmd)
        self._connected = True
        for a in self.agents:
            try:
                progs = traci.trafficlight.getAllProgramLogics(a)
                self._n_phases[a] = max(1, len(progs[0].phases)) if progs else 4
            except Exception:
                self._n_phases[a] = 4
        for _ in range(self.warmup):
            traci.simulationStep()

    def _approaches(self, agent):
        try:
            lanes = traci.trafficlight.getControlledLanes(agent)
        except Exception:
            return []
        edges = []
        for ln in lanes:
            e = ln.rsplit("_", 1)[0]
            if e not in edges:
                edges.append(e)
        return edges[:K.MAX_APPROACHES]

    def _obs(self, agent):
        vals = []
        for e in self._approaches(agent):
            try:
                q = traci.edge.getLastStepHaltingNumber(e)
                v = traci.edge.getLastStepMeanSpeed(e)
            except Exception:
                q, v = 0, 0.0
            vals += [min(1.0, float(q) / K.MAX_QUEUE),
                     min(1.0, max(0.0, float(v)) / K.MAX_SPEED)]
        while len(vals) < 2 * K.MAX_APPROACHES:
            vals.append(0.0)
        try:
            ph = int(traci.trafficlight.getPhase(agent))
            nxt = float(traci.trafficlight.getNextSwitch(agent))
            now = float(traci.simulation.getTime())
            tts = max(0.0, nxt - now)
        except Exception:
            ph, tts = 0, 0.0
        n = self._n_phases.get(agent, 4)
        vals += [ph / max(1, n), min(1.0, tts / max(1.0, self.horizon)),
                 min(1.0, n / 10.0)]
        return np.asarray(vals, dtype=np.float32)

    def _reward(self, agent):
        """Passenger-equivalent reward that sees the bus green/red difference.

        - bus occupant delay  x BUS_OCC
        - car/truck delay     x CAR_OCC
        - a bus sitting still on the approach costs BUS_STOP_PENALTY
        - a bus that clears the approach earns BUS_CLEAR_BONUS
        """
        bus_now = car_now = 0.0
        bus_waiting = 0
        bus_ids = set()
        for e in self._approaches(agent):
            try:
                vids = traci.edge.getLastStepVehicleIDs(e)
            except Exception:
                vids = []
            for v in vids:
                try:
                    tid = str(traci.vehicle.getTypeID(v)).lower()
                    w = float(traci.vehicle.getAccumulatedWaitingTime(v))
                    spd = float(traci.vehicle.getSpeed(v))
                except Exception:
                    continue
                if "bus" in tid:
                    bus_now += w
                    bus_ids.add(v)
                    if spd < 0.5:
                        bus_waiting += 1
                else:
                    car_now += w
        pb, pc = self._last_wait.get(agent, (0.0, 0.0))
        self._last_wait[agent] = (bus_now, car_now)
        dbus = max(0.0, bus_now - pb)
        dcar = max(0.0, car_now - pc)
        cleared = [v for v in (self._last_bus_ids.get(agent, set()) - bus_ids)
                   if v not in self._veh_ids]
        self._last_bus_ids[agent] = bus_ids
        r = (-(dbus * K.BUS_OCC + dcar * K.CAR_OCC)
             - bus_waiting * K.BUS_STOP_PENALTY
             + len(cleared) * K.BUS_CLEAR_BONUS)
        self._parts[agent] = {
            "bus_delay_pax_s": dbus * K.BUS_OCC,
            "car_delay_pax_s": dcar * K.CAR_OCC,
            "bus_waiting": bus_waiting,
            "bus_cleared": len(cleared),
            "reward": r * K.REWARD_SCALE,
        }
        return r * K.REWARD_SCALE

    # --------------------------------------------------------------- actions
    def _is_yellow(self, agent):
        try:
            st = traci.trafficlight.getRedYellowGreenState(agent)
            return ("y" in st) or ("Y" in st)
        except Exception:
            return True

    def _apply_action(self, agent, act):
        """Apply NONE / GE / ER / INS (same contract as flow_policy.py)."""
        act = int(act)
        if act <= 0 or self._is_yellow(agent):
            return
        try:
            now = float(traci.simulation.getTime())
            nxt = float(traci.trafficlight.getNextSwitch(agent))
            remaining = max(0.0, nxt - now)
            if act == 1:  # GE
                traci.trafficlight.setPhaseDuration(
                    agent, remaining + self.ge_extend)
            elif act == 2:  # ER
                traci.trafficlight.setPhaseDuration(
                    agent, max(self.min_green, remaining - self.er_trunc))
            elif act == 3:  # INS: advance one phase (bus-phase insertion stub)
                ph = int(traci.trafficlight.getPhase(agent))
                n = self._n_phases.get(agent, 4)
                traci.trafficlight.setPhase(agent, (ph + 1) % n)
        except Exception:
            pass

    # --------------------------------------------------------------- RLlib
    def reset(self, *, seed=None, options=None):
        self._start()
        self._last_wait.clear()
        self._last_bus_ids.clear()
        obs = {a: self._obs(a) for a in self.agents}
        infos = {a: {} for a in self.agents}
        return obs, infos

    def step(self, action_dict):
        try:
            self._veh_ids = set(traci.vehicle.getIDList())
        except Exception:
            self._veh_ids = set()
        for a, act in action_dict.items():
            if a in self.agents:
                self._apply_action(a, act)
        for _ in range(self.action_every):
            traci.simulationStep()

        obs = {a: self._obs(a) for a in self.agents}
        local = {a: self._reward(a) for a in self.agents}
        if self.shared_reward:
            s = float(sum(local.values()))
            rewards = {a: s for a in self.agents}
        else:
            rewards = local
        now = float(traci.simulation.getTime())
        done = now >= self.horizon or traci.simulation.getMinExpectedNumber() == 0
        terminateds = {a: bool(done) for a in self.agents}
        terminateds["__all__"] = bool(done)
        truncateds = {a: False for a in self.agents}
        truncateds["__all__"] = False
        infos = {a: {"action": K.ACTION_NAMES[int(action_dict.get(a, 0))]
                     if 0 <= int(action_dict.get(a, 0)) < len(K.ACTION_NAMES)
                     else "NONE"} for a in self.agents}
        return obs, rewards, terminateds, truncateds, infos

    def close(self):
        if self._connected:
            try:
                traci.close()
            except Exception:
                pass
            self._connected = False
        try:
            super().close()
        except AttributeError:
            pass
