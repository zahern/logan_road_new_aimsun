#!/bin/bash
# Create an isolated conda env for the Flow/RLlib training side (HPC/Linux).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

conda create -n flowmarl python=3.10 -y
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate flowmarl
python -m pip install --upgrade pip
python -m pip install -r "${HERE}/requirements.txt"

echo
echo "Installed. Activate with:  conda activate flowmarl"
echo "Smoke:                     python run_smoke.py"
echo "Export policy:             python export_flow_policy.py --example"
