@echo off
REM Watch the Logan Road corridor in SUMO-GUI with the engine attached (NO_TSP).
REM Swap --strategy NO_TSP for any arm (CELLQLEARN, MAXPRESSURE_FIX, ...).
cd /d C:\Users\ahernz\github_for_aimsun\sumo_bridge
python -u run_sumo_hpc.py --corridor logan_road_new --scenario logan_scenario --gui ^
  --strategy NO_TSP --experiment logan_gui_watch --seed 300 ^
  --demand-scalar 1.0 --end 3600 ^
  --controller C:\Users\ahernz\github_for_aimsun\logan_road_new\intersection_controller.py
pause
