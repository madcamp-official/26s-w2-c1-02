#!/usr/bin/env bash
# TTS(VoxCPM2 + vLLM-Omni) 환경 설치 스크립트
# 사용법: bash setup_tts.sh
set -euo pipefail
cd "$(dirname "$0")"

# 1) uv (파이썬 환경 관리 도구) 설치 — 이미 있으면 건너뜀
if ! command -v uv >/dev/null 2>&1; then
  echo "[setup_tts] uv 설치 중..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

# 2) TTS 전용 가상환경 생성 (STT와 의존성 충돌 방지를 위해 분리)
uv venv .venv-tts --python 3.12
source .venv-tts/bin/activate

# 3) vLLM + vLLM-Omni 설치 (VoxCPM2 공식 문서 기준)
uv pip install vllm==0.19.0 --torch-backend=auto
if [ ! -d vllm-omni ]; then
  git clone https://github.com/vllm-project/vllm-omni.git
fi
cd vllm-omni
uv pip install -e .

echo ""
echo "[setup_tts] 완료. 다음 명령으로 서버를 시작하세요:"
echo "  bash start_tts.sh"
