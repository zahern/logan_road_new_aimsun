"""Make GAME_CTM2_ROLLOUT diagnosable.

Two states currently look identical in a log: the flag is off (scalar path
runs) and the rollout ran but returned {} (empty subnet / no adjacency), since
[SPILLROLL] only fires when values exist. This adds:

  [SPILLROLL-ENV]  once per junction: the flag value the payoff actually read
  [SPILLROLL-NA]   first few empty returns per junction, with the reason

Both gated on SPILL_BLOCK_LOG so a normal run is unchanged. Idempotent.
"""
import io
import os
import sys

PATH = "shared_tsp_engine/engine.py"

EDITS = [
    # 1) the reason helper, right after the rollout docstring
    (
        [
            "        Costs ~1 ms: 30 steps x ~30 sections. Never raises.",
            '        """',
            "        try:",
        ],
        [
            "        Costs ~1 ms: 30 steps x ~30 sections. Never raises.",
            '        """',
            "",
            "        def _na(_why):",
            "            try:",
            "                if os.environ.get('SPILL_BLOCK_LOG'):",
            "                    _n = int(getattr(self, '_spillroll_na', 0) or 0)",
            "                    if _n < 4:",
            "                        self._spillroll_na = _n + 1",
            "                        log_to_file(\"[SPILLROLL-NA] jct=%s why=%s\"",
            "                                    % (getattr(self, 'id', '?'), _why),",
            "                                    force=True)",
            "            except Exception:",
            "                pass",
            "            return {}",
            "",
            "        try:",
        ],
    ),
    (
        ["            if not _ring:", "                return {}"],
        ["            if not _ring:", "                return _na('no ring')"],
    ),
    (
        ["            if not _po:", "                return {}"],
        ["            if not _po:", "                return _na('no phase origins')"],
    ),
    (
        ["            if not _adj:", "                return {}"],
        ["            if not _adj:", "                return _na('no turning adjacency')"],
    ),
    (
        ["            if not _orig:", "                return {}"],
        ["            if not _orig:", "                return _na('no origin sections')"],
    ),
    (
        ["            if not _n or sum(_n.values()) <= 0.0:", "                return {}"],
        ["            if not _n or sum(_n.values()) <= 0.0:",
         "                return _na('subnet empty of vehicles')"],
    ),
    # 2) the flag value the payoff actually saw
    (
        ["            if bool(globals().get('GAME_CTM2_ROLLOUT', False)):"],
        [
            "            _roll_on = bool(globals().get('GAME_CTM2_ROLLOUT', False))",
            "            if not getattr(self, '_roll_env_logged', False):",
            "                self._roll_env_logged = True",
            "                try:",
            "                    if os.environ.get('SPILL_BLOCK_LOG'):",
            "                        log_to_file(",
            "                            \"[SPILLROLL-ENV] jct=%s rollout=%r spill=%r\"",
            "                            % (getattr(self, 'id', '?'), _roll_on, _spill),",
            "                            force=True)",
            "                except Exception:",
            "                    pass",
            "            if _roll_on:",
        ],
    ),
]


def main() -> int:
    with io.open(PATH, encoding="utf-8", newline="") as fh:
        src = fh.read()
    if "SPILLROLL-ENV" in src:
        print("ALREADY_PATCHED")
        return 0
    nl = "\r\n" if "\r\n" in src[:4000] else "\n"

    def blk(lines):
        return "".join(l + nl for l in lines)

    pairs = [(blk(o), blk(n)) for o, n in EDITS]
    for i, (old, _new) in enumerate(pairs):
        c = src.count(old)
        print("edit %d anchor_matches=%d" % (i, c))
        if c != 1:
            print("REFUSING: edit %d anchor is not unique" % i)
            return 1
    out = src
    for old, new in pairs:
        out = out.replace(old, new, 1)
    tmp = PATH + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(out)
    os.replace(tmp, PATH)
    print("PATCHED size %d -> %d" % (len(src), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
