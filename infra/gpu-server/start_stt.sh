#!/usr/bin/env bash
# STT 서버 시작 — Qwen3-ASR 1.7B + ForcedAligner 0.6B (FastAPI), 포트 8200
# VRAM 예산: vLLM(ASR) 25% (~6GB) + Aligner ~2GB = 합계 ~8GB
# 사용법: bash start_stt.sh
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
source .venv-stt/bin/activate

export CUDA_VISIBLE_DEVICES=0

python stt_server.py
