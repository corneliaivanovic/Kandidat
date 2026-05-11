#!/usr/bin/env bash
#SBATCH -A TIFX11VT2602A
#SBATCH -p vera
#SBATCH --gpus-per-node=A40:1
#SBATCH -t 00:30:00
#SBATCH -J test_llm
#SBATCH -o test_output_%j.log

export HF_HOME=/cephyr/NOBACKUP/courses/TIFX11VT2602A/filer/hf_cache
export HUGGINGFACE_HUB_CACHE=$HF_HOME/hub
export TRANSFORMERS_CACHE=$HF_HOME/transformers
export TMPDIR=/cephyr/NOBACKUP/courses/TIFX11VT2602A/filer/tmp

mkdir -p $HF_HOME
mkdir -p $HUGGINGFACE_HUB_CACHE
mkdir -p $TRANSFORMERS_CACHE
mkdir -p $TMPDIR

module purge
module load Python/3.11.3-GCCcore-12.3.0

source /cephyr/NOBACKUP/courses/TIFX11VT2602A/filer/coach_env/bin/activate

cd /cephyr/NOBACKUP/courses/TIFX11VT2602A/filer

python test_llm.py