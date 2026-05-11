#!/usr/bin/env bash
#SBATCH -A TIFX11VT2602A
#SBATCH -p vera
#SBATCH --gpus-per-node=A40:1
#SBATCH -t 12:00:00
#SBATCH -J llama_coach
#SBATCH -o train_output_%j.log

set -euo pipefail

export HF_HOME=/cephyr/NOBACKUP/courses/TIFX11VT2602A/filer/hf_cache
export HUGGINGFACE_HUB_CACHE=$HF_HOME/hub
export TRANSFORMERS_CACHE=$HF_HOME/transformers
export TMPDIR=/cephyr/NOBACKUP/courses/TIFX11VT2602A/filer/tmp

mkdir -p "$HF_HOME" "$HUGGINGFACE_HUB_CACHE" "$TRANSFORMERS_CACHE" "$TMPDIR"

module purge
module load Python/3.11.3-GCCcore-12.3.0
source /cephyr/NOBACKUP/courses/TIFX11VT2602A/filer/coach_env/bin/activate

echo "===== JOB INFO ====="
echo "HOSTNAME: $(hostname)"
echo "PWD: $(pwd)"
echo "CUDA_VISIBLE_DEVICES: ${CUDA_VISIBLE_DEVICES:-unset}"
which python
python --version
nvidia-smi || true

cd /cephyr/NOBACKUP/courses/TIFX11VT2602A/filer
python train_llm.py