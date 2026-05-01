"""
Pipeline path configuration
============================
All HPC absolute paths live here.  Edit only this file when data locations change.

On the HPC the network share //hpc-fs/ahernz/ maps to /home/ahernz/.
On Windows the same share is accessed as \\hpc-fs\ahernz\ or //hpc-fs/ahernz/.
"""

import os

# ---------------------------------------------------------------------------
# Root directories on the HPC
# ---------------------------------------------------------------------------
HPC_HOME = "/home/ahernz"

POP_SYNTH_DIR    = os.path.join(HPC_HOME, "Population_Synth")
HH_MATCH_DIR     = os.path.join(HPC_HOME, "Household_Match")
SA_DIR           = os.path.join(HPC_HOME, "sa_run_again_n")
REPO_DIR         = os.path.join(HPC_HOME, "github_for_aimsun", "logan_road_new")
SYNTH_POP_DIR    = os.path.join(REPO_DIR, "synth_pop")

# ---------------------------------------------------------------------------
# Key input files
# ---------------------------------------------------------------------------
CENSUS_DWELLING  = os.path.join(POP_SYNTH_DIR, "CENSUS_2021_BASIC_dwelling.csv")
CENSUS_FAMILY    = os.path.join(POP_SYNTH_DIR, "CENSUS_2021_BASIC_family.csv")
CENSUS_PERSON    = os.path.join(POP_SYNTH_DIR, "CENSUS_2021_BASIC_person.csv")

LINKED_DATA      = os.path.join(POP_SYNTH_DIR, "LINKED_DATA_dropped.csv")
DATGAN_OUTPUT    = os.path.join(POP_SYNTH_DIR, "core_brisbane", "data", "DATGAN.csv")

HH_MATCH_INPUT   = os.path.join(HH_MATCH_DIR,  "DATGAN_samples.csv")
HH_MATCH_OUTPUT  = os.path.join(HH_MATCH_DIR,  "cleaned_dataset_hhid.csv")

CENSUS_MICRODATA = os.path.join(SA_DIR, "microdata_for_exp.csv")
SA_CONTROL_IND   = os.path.join(SA_DIR, "data_sa2_controls", "individual")
SA_CONTROL_HH    = os.path.join(SA_DIR, "data_sa2_controls", "household")

# ---------------------------------------------------------------------------
# Output directories (written by each stage)
# ---------------------------------------------------------------------------
GAN_VALIDATION_DIR   = os.path.join(SYNTH_POP_DIR, "outputs", "gan_validation")
SA_ONLY_RESULTS_DIR  = os.path.join(SYNTH_POP_DIR, "outputs", "sa_only_results")
RSSZ_OUTLIER_DIR     = os.path.join(SYNTH_POP_DIR, "outputs", "rssz_outlier")
SA_GAN_RESULTS_DIR   = os.path.join(SA_DIR, "zones_sa_5_main")   # existing SA-GAN output

# ---------------------------------------------------------------------------
# HPC environment
# ---------------------------------------------------------------------------
CONDA_PROFILE    = "/home/ahernz/miniconda3/etc/profile.d/conda.sh"
ENV_GAN          = "popgangpu"    # GPU env used for GAN training
ENV_SA           = "syn_env"      # CPU env used for SA / analysis

# ---------------------------------------------------------------------------
# SA run parameters (override via CLI where scripts accept --args)
# ---------------------------------------------------------------------------
SA_MAX_ITER      = 1000
SA_INITIAL_TEMP  = 100.0
SA_COOLING_RATE  = 0.95
SA_TOLERANCE     = 0.05

GAN_EPOCHS       = 100
GAN_BATCH_SIZE   = 128
GAN_SAMPLE_MULT  = 50
GAN_DATA_SOURCE  = "census"
