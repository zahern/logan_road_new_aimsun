@echo off
REM Watch the KG corridor in SUMO-GUI with CellQLearn driving the signals.
REM Close the SUMO window to stop the experiment.
cd /d C:\Users\ahernz\github_for_aimsun\sumo_bridge
python -u run_sumo_hpc.py --corridor kg --scenario kg_scenario --gui ^
  --strategy CELLQLEARN --experiment gui_watch_cellq --seed 300 ^
  --demand-scalar 0.6 --end 3600 ^
  --controller C:\Users\ahernz\github_for_aimsun\sumo_bridge\_gui_sb ^
  --set GLOBAL_REWARD_MODE=True --set BXT_MODE=True ^
  --set BXT_EPSILON=0.15 --set DECIDER_COST_VETO_RATIO=1.3 ^
  --set BUS_PAX_WEIGHT=1.3 --set GREEN_KEEP_CREDIT_S=3.0 ^
  --set CORRIDOR_REWARD_NEIGHBOR_W=0.5 --set MULTIBUS_MAX_FACTOR=1.0 ^
  --set BXT_SOLVER=deficit
pause
