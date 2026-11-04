"""RLlib multi-agent signal-control env for the KG SUMO corridor.

This mirrors the Flow tutorial14 pattern:
  * one agent per signalised intersection,
  * a partially observed local state,
  * a discrete action (keep / advance the phase),
  * a configurable shared or local reward.

It talks to SUMO through traci directly (no Flow install needed), so the
same KG scenario used by the HPC sweeps can be used for MARL experiments.

Observation (per agent), fixed size:
    [queue_0/maxq, speed_0/maxspeed, ..., queue_3/maxq, speed_3/maxspeed,
     phase/n_phases, time_to_switch/horizon, n_phases/10]
Action: Discrete(2) -> 0 keep, 1 advance one phase.
Reward: -sum(queue on incoming approaches); shared across agents if
        KG_SHARED_REWARD=1.
"""
import os
import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError:  # older stacks
    try:
        import gym
        from gym import spaces
    except ImportError:  # smoke-only fallback (no Ray/gym installed)
        class _Space:
            def __init__(self, *a, **k):
                self.shape = k.get("shape")
                self.n = k.get("n")
        class _Spaces:
            Box = _Space
            Discrete = _Space
        spaces = _Spaces()

try:
    from ray.rllib.env.multi_agent_env import MultiAgentEnv
except ImportError:  # smoke-only fallback
    class MultiAgentEnv(object):
        pass

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
        self._n_phases = {a: 4 for a in self.agents}

        n_obs = 2 * K.MAX_APPROACHES + 3
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(n_obs,), dtype=np.float32)
        self.action_space = spaces.Discrete(2)
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
        """Up to MAX_APPROACHES incoming edges for this TLS."""
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
        q = 0.0
        for e in self._approaches(agent):
            try:
                q += float(traci.edge.getLastStepHaltingNumber(e))
            except Exception:
                pass
        return -q

    # --------------------------------------------------------------- RLlib
    def reset(self, *, seed=None, options=None):
        self._start()
        obs = {a: self._obs(a) for a in self.agents}
        infos = {a: {} for a in self.agents}
        return obs, infos

    def step(self, action_dict):
        for a, act in action_dict.items():
            if a not in self.agents:
                continue
            if int(act) == 1:
                try:
                    ph = int(traci.trafficlight.getPhase(a))
                    n = self._n_phases.get(a, 4)
                    traci.trafficlight.setPhase(a, (ph + 1) % n)
                except Exception:
                    pass
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
        infos = {a: {} for a in self.agents}
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
