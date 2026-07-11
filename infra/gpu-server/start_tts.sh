#!/usr/bin/env bash
# TTS 서버 시작 — VoxCPM2 (vLLM-Omni), 포트 8100
#
# VRAM 실측 조정은 --gpu-memory-utilization가 아니라 --kv-cache-memory-bytes로 한다.
# VoxCPM2 deploy YAML(vllm_omni/deploy/voxcpm2.yaml)이 KV 캐시를 고정 크기로
# 못박아 두기 때문에(kv_cache_memory_bytes), gpu-memory-utilization은 상한선일 뿐
# 실제 점유량을 좌우하지 못한다. 자세한 이유는 README의 [VRAM 조정] 참고.
#
# 실점유 ≈ 가중치(~4.86GB) + KV 캐시(아래 값) + 디퓨전 side-path(~2.3GB, KV 예산 밖).
# 아래 KV를 Δ만큼 줄이면 실점유가 거의 Δ만큼 줄어든다.
# 사용법: bash start_tts.sh
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
source .venv-tts/bin/activate

export CUDA_HOME="$(python -c 'import nvidia.cu13; print(nvidia.cu13.__path__[0])')"
export PATH="$CUDA_HOME/bin:$PATH"
export CUDA_VISIBLE_DEVICES=0

# KV 캐시 예산 (실제 VRAM 조정 knob). 기본 4GiB.
#   deploy YAML 기본값은 6GiB → 여기서 4GiB로 내려 ~2GB 절약.
#   max_num_seqs(8) × max_model_len(4096) = 32k 토큰 admission이므로 4GiB로 충분.
#   더 줄이려면 이 값을 낮추면 됨(예: 3GiB=3221225472). OOM이면 다시 올린다.
KV_CACHE_BYTES="${TTS_KV_CACHE_BYTES:-4294967296}"  # 4 GiB

vllm serve openbmb/VoxCPM2 --omni \
  --host 0.0.0.0 \
  --port 8100 \
  --gpu-memory-utilization 0.42 \
  --kv-cache-memory-bytes "$KV_CACHE_BYTES"
