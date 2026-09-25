@echo off
setlocal EnableExtensions

REM Install both MILP solvers into an environment visible to Aimsun.
REM This script is intended to be run from anywhere by double-clicking it.

set "BUNDLE_DIR=%~dp0"
set "BUNDLE_PYTHON=%BUNDLE_DIR%logan_road_new\.venv\Scripts\python.exe"
set "WORKSPACE_PYTHON=%BUNDLE_DIR%..\logan_road_new\.venv\Scripts\python.exe"

if exist "%BUNDLE_PYTHON%" (
    set "PYTHON_EXE=%BUNDLE_PYTHON%"
) else if exist "%WORKSPACE_PYTHON%" (
    set "PYTHON_EXE=%WORKSPACE_PYTHON%"
) else (
    where py >nul 2>&1
    if errorlevel 1 (
        echo ERROR: No Python 3.12 launcher or existing project environment was found.
        echo Install Python 3.12, then run this file again.
        exit /b 1
    )
    echo Creating a bundle-local Python 3.12 environment...
    py -3.12 -m venv "%BUNDLE_DIR%logan_road_new\.venv"
    if errorlevel 1 (
        echo ERROR: Could not create the Python environment.
        exit /b 1
    )
    set "PYTHON_EXE=%BUNDLE_PYTHON%"
)

echo Using: "%PYTHON_EXE%"
"%PYTHON_EXE%" -m pip install --upgrade "scipy>=1.13,<2"
if errorlevel 1 (
    echo ERROR: SciPy installation failed.
    exit /b 1
)

"%PYTHON_EXE%" -m pip install --upgrade "ortools>=9.10"
if errorlevel 1 (
    echo ERROR: OR-Tools installation failed.
    exit /b 1
)

"%PYTHON_EXE%" -c "import scipy; from scipy.optimize import milp; import ortools; from ortools.sat.python import cp_model; print('SciPy ' + scipy.__version__ + ' and OR-Tools ' + ortools.__version__ + ' are ready.')"
if errorlevel 1 (
    echo ERROR: The MILP import check failed.
    exit /b 1
)

echo.
echo MILP dependencies are ready. Restart Aimsun before running the MILP arm.
exit /b 0