@echo off
REM MILP-MPC Environment Setup Script
REM Run this in a conda-enabled terminal (Anaconda Prompt or Miniconda Prompt)

echo Creating MILP-MPC environment with Python 3.10...
conda create -y -n milp-mpc python=3.10

echo Activating environment...
call conda activate milp-mpc

echo Installing ortools (has cp310 wheel for win-64)...
conda install -c conda-forge -y ortools

REM If conda fails, try pip
if errorlevel 1 (
    echo Conda install failed, trying pip...
    pip install ortools
)

echo Installing other dependencies...
pip install numpy pandas

echo.
echo Environment setup complete!
echo.
echo To use the MILP-MPC controller:
echo 1. Activate environment: conda activate milp-mpc
echo 2. Set environment variables:
echo    set PYTHONPATH=C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v4_20260825_cleanKG\shared_tsp_engine;%%PYTHONPATH%%
echo    set CONTROL_MODE=MILP_MPC
echo 3. Run Aimsun with kg/intersection_controller.py as API script
echo.
echo The controller will automatically initialize when CONTROL_MODE=MILP_MPC

pause