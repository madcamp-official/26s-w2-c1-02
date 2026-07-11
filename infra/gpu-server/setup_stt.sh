#!/usr/bin/env bash
# STT(Qwen3-ASR 1.7B + ForcedAligner 0.6B) 환경 설치 스크립트
# 사용법: bash setup_stt.sh
set -euo pipefail
cd "$(dirname "$0")"

# 1) uv 설치 — 이미 있으면 건너뜀
if ! command -v uv >/dev/null 2>&1; then
  echo "[setup_stt] uv 설치 중..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

# 2) STT 전용 가상환경 생성 (TTS와 분리)
uv venv .venv-stt --python 3.12
source .venv-stt/bin/activate

# 3) qwen-asr(vLLM 백엔드 포함) + API 서버용 패키지 설치
uv pip install -U "qwen-asr[vllm]" fastapi uvicorn python-multipart

echo ""
echo "[setup_stt] 완료. 다음 명령으로 서버를 시작하세요:"
echo "  bash start_stt.sh"
