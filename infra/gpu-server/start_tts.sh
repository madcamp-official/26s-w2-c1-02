#!/usr/bin/env bash
# TTS 서버 시작 — VoxCPM2 (vLLM-Omni), 포트 8100
# VRAM 예산: 전체 24GB의 42% (~10GB)
# 사용법: bash start_tts.sh
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
source .venv-tts/bin/activate

export CUDA_VISIBLE_DEVICES=0

vllm serve openbmb/VoxCPM2 --omni \
  --host 0.0.0.0 \
  --port 8100 \
  --gpu-memory-utilization 0.42
