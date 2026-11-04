"""run_cellq_held_kg_panel.py -- stable shim for the Aimsun SCRIPT PANEL.

USE THIS FILE IN THE PANEL, NOT THE LAUNCHER ITSELF.

WHY. A script object saved into an Aimsun model carries its own copy of the
code (or at least its own recorded text). Editing the .py on disk then changes
nothing: the panel keeps running the text it was given. That is how the same
`REFUSING: ... cellq_held_kg.csv already exists` came back twice from object
11144668 after the launcher had been changed on disk.

This shim contains no logic and never needs to change. Every time it runs it
re-reads the launcher from disk, so any edit to the launcher -- including the
2026-11-02 output-name fix -- takes effect immediately, with no need to
re-import the script into the model.

HOW TO INSTALL IT IN THE PANEL (once)
  1. Open the existing Python Script object in the script panel.
  2. Select all of its body and replace it with the single statement below
     (the one starting `exec(open(`). Save the object.
  3. Press Run.

Or point the panel at this file directly (Add script -> from file). Either way
the object's own text is now just that delegation, so it can never go stale
again.

WHAT IT RUNS. run_cellq_held_kg.py, which is the KG CellQ held/downstream A/B:
seeds 300,400,500 x [NO_TSP + CHAMP_ADAPTIVE_DSW_CELLQ_GATED +
CHAMP_ADAPTIVE_DSW_CELLQ_GATED_OPEN] = 9 runs, ~1.5 h.

Its output name is timestamped when cellq_held_kg.csv already exists, so a
re-run needs no environment variable -- which matters here, because a panel
script cannot set one before it starts.

REQUIRES A FULL AIMSUN RESTART first if engine.py or specialized_modes.py
changed since the last launch (RULE 2: the modules are cached for the process
lifetime). Check the [LOAD] line's SOURCE_HASH against the value the launcher
prints at startup.
"""

exec(open(r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5\run_cellq_held_kg.py",
          encoding="utf-8").read())
