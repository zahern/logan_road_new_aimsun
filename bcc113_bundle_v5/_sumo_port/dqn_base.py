"""Numpy DQN for the SUMO BASE_PLAN family (LightSim paper spec).

The LightSim paper (Su & Deng, arXiv:2602.21852) trains a DQN (Mnih et al.
2015) with Stable-Baselines3 on a Gymnasium env and reports, for the single
intersection, the agent configuration: MLP 2x64, Adam lr 1e-3, gamma 0.99,
replay buffer, batch 32, epsilon 1.0 -> 0.05, target sync every 500 updates,
one decision every k=5 simulated seconds, observation = one-hot current phase
+ normalised incoming densities + binary queue flags, reward = minus the total
queue on the incoming links.

Neither torch nor Stable-Baselines3 is installed on this machine, so this is a
dependency-free numpy implementation of the same agent with the same
observation, action and reward semantics. It is NOT the paper's trained
checkpoint: the paper trains in LightSim and replays the learned timing in
SUMO (Table 8), which needs a LightSim install this machine does not have.
Here the agent learns inside SUMO instead.
"""

import numpy as np


class NumpyDQN:
    """DQN: 2x64 ReLU MLP, replay, target net, epsilon-greedy, Adam."""

    def __init__(self, state_dim, n_actions, hidden=64, lr=1e-3, gamma=0.99,
                 batch=32, buffer=20000, eps_start=1.0, eps_end=0.05,
                 eps_steps=20000, target_every=500, train_every=4,
                 warmup=100, seed=0):
        self.sd = int(state_dim)
        self.na = int(n_actions)
        self.hidden = int(hidden)
        self.lr = float(lr)
        self.gamma = float(gamma)
        self.batch = int(batch)
        self.cap = int(buffer)
        self.eps_start = float(eps_start)
        self.eps_end = float(eps_end)
        self.eps_steps = max(1, int(eps_steps))
        self.target_every = max(1, int(target_every))
        self.train_every = max(1, int(train_every))
        self.warmup = max(1, int(warmup))
        self.rng = np.random.default_rng(int(seed))

        self.p = self._init_params()
        self.tgt = {k: v.copy() for k, v in self.p.items()}
        self._m = {k: np.zeros_like(v) for k, v in self.p.items()}
        self._v = {k: np.zeros_like(v) for k, v in self.p.items()}
        self._adam_t = 0

        self.buf_s = np.zeros((self.cap, self.sd), np.float32)
        self.buf_s2 = np.zeros((self.cap, self.sd), np.float32)
        self.buf_a = np.zeros(self.cap, np.int64)
        self.buf_r = np.zeros(self.cap, np.float32)
        self.buf_d = np.zeros(self.cap, np.float32)
        self.ptr = 0
        self.n = 0

        self.steps = 0
        self.updates = 0
        self.last_loss = 0.0
        self.last_eps = self.eps_start

    # -- params -------------------------------------------------------
    def _init_params(self):
        h, sd, na = self.hidden, self.sd, self.na
        return {
            "W1": (self.rng.standard_normal((sd, h)) * np.sqrt(2.0 / sd)).astype(np.float32),
            "b1": np.zeros(h, np.float32),
            "W2": (self.rng.standard_normal((h, h)) * np.sqrt(2.0 / h)).astype(np.float32),
            "b2": np.zeros(h, np.float32),
            "W3": (self.rng.standard_normal((h, na)) * np.sqrt(2.0 / h) * 0.1).astype(np.float32),
            "b3": np.zeros(na, np.float32),
        }

    @staticmethod
    def _forward(x, p):
        z1 = x @ p["W1"] + p["b1"]
        h1 = np.maximum(z1, 0.0)
        z2 = h1 @ p["W2"] + p["b2"]
        h2 = np.maximum(z2, 0.0)
        q = h2 @ p["W3"] + p["b3"]
        return q, (z1, h1, z2, h2)

    # -- acting -------------------------------------------------------
    def eps(self):
        f = min(1.0, float(self.steps) / float(self.eps_steps))
        return self.eps_start + f * (self.eps_end - self.eps_start)

    def act(self, state, explore=True):
        self.last_eps = self.eps()
        if explore and self.rng.random() < self.last_eps:
            return int(self.rng.integers(self.na))
        q, _ = self._forward(np.asarray(state, np.float32)[None, :], self.p)
        return int(np.argmax(q[0]))

    # -- learning -----------------------------------------------------
    def observe(self, s, a, r, s2, done=False):
        i = self.ptr
        self.buf_s[i] = s
        self.buf_s2[i] = s2
        self.buf_a[i] = int(a)
        self.buf_r[i] = float(r)
        self.buf_d[i] = 1.0 if done else 0.0
        self.ptr = (i + 1) % self.cap
        self.n = min(self.n + 1, self.cap)
        self.steps += 1
        if self.n >= self.warmup and self.steps % self.train_every == 0:
            self.train_step()

    def train_step(self):
        b = min(self.batch, self.n)
        idx = self.rng.integers(0, self.n, size=b)
        S = self.buf_s[idx]
        S2 = self.buf_s2[idx]
        A = self.buf_a[idx]
        R = self.buf_r[idx]
        D = self.buf_d[idx]

        q2, _ = self._forward(S2, self.tgt)
        y = R + self.gamma * (1.0 - D) * np.max(q2, axis=1)

        q, (z1, h1, z2, h2) = self._forward(S, self.p)
        qa = q[np.arange(b), A]
        self.last_loss = float(np.mean((qa - y) ** 2))
        dq = np.zeros_like(q)
        dq[np.arange(b), A] = (2.0 / b) * (qa - y)

        g = {}
        g["W3"] = h2.T @ dq
        g["b3"] = dq.sum(axis=0)
        dz2 = (dq @ self.p["W3"].T) * (z2 > 0.0)
        g["W2"] = h1.T @ dz2
        g["b2"] = dz2.sum(axis=0)
        dz1 = (dz2 @ self.p["W2"].T) * (z1 > 0.0)
        g["W1"] = S.T @ dz1
        g["b1"] = dz1.sum(axis=0)

        self._adam_t += 1
        b1, b2, eps = 0.9, 0.999, 1e-8
        for k in self.p:
            self._m[k] = b1 * self._m[k] + (1.0 - b1) * g[k]
            self._v[k] = b2 * self._v[k] + (1.0 - b2) * (g[k] ** 2)
            mhat = self._m[k] / (1.0 - b1 ** self._adam_t)
            vhat = self._v[k] / (1.0 - b2 ** self._adam_t)
            self.p[k] -= self.lr * mhat / (np.sqrt(vhat) + eps)

        self.updates += 1
        if self.updates % self.target_every == 0:
            self.tgt = {k: v.copy() for k, v in self.p.items()}

    def stats(self):
        return {"updates": self.updates, "steps": self.steps,
                "eps": self.last_eps, "loss": self.last_loss,
                "n": self.n}

    def save(self, path):
        np.savez(path, **{("p_" + k): v for k, v in self.p.items()},
                 **{("t_" + k): v for k, v in self.tgt.items()},
                 meta=np.array([self.steps, self.updates], np.int64))

    def load(self, path):
        z = np.load(path)
        for k in self.p:
            self.p[k] = z["p_" + k].astype(np.float32)
            self.tgt[k] = z["t_" + k].astype(np.float32)
        m = z["meta"]
        self.steps, self.updates = int(m[0]), int(m[1])
        return True
