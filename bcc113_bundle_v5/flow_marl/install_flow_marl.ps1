# Create an isolated conda env for the Flow/RLlib training side.
# Do NOT install Ray/torch into Aimsun's embedded Python: train here, export a
# rules policy, and let Aimsun load kg/flow_policy.json via CHAMP_FIXED_FLOW_RL.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

conda create -n flowmarl python=3.10 -y
conda run -n flowmarl python -m pip install --upgrade pip
conda run -n flowmarl python -m pip install -r (Join-Path $here "requirements.txt")

Write-Host ""
Write-Host "Installed. Activate with:  conda activate flowmarl"
Write-Host "Smoke:                     python run_smoke.py"
Write-Host "Export policy:             python export_flow_policy.py --example"
