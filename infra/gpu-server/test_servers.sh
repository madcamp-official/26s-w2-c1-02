#!/usr/bin/env bash
# 스모크 테스트 — 두 서버가 정상 동작하는지 확인
# 사용법: bash test_servers.sh [오디오파일경로]
#   오디오 파일을 주면 STT 전사까지 테스트한다.
set -euo pipefail

TTS_URL="http://localhost:8100"
STT_URL="http://localhost:8200"

echo "=== 1. TTS 테스트 (VoxCPM2) ==="
curl -sf "$TTS_URL/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d '{"model":"openbmb/VoxCPM2","input":"안녕하세요, 리허설 아이오 테스트입니다.","voice":"default"}' \
  --output /tmp/tts_test.wav
echo "OK → /tmp/tts_test.wav 생성됨 ($(du -h /tmp/tts_test.wav | cut -f1))"

echo ""
echo "=== 2. STT 헬스체크 ==="
curl -sf "$STT_URL/health"
echo ""

if [ $# -ge 1 ]; then
  echo ""
  echo "=== 3. STT 전사 테스트 ($1) ==="
  curl -sf "$STT_URL/transcribe" \
    -F "file=@$1" \
    -F "language=Korean" \
    -F "timestamps=true"
  echo ""
else
  echo ""
  echo "(오디오 파일 경로를 인자로 주면 STT 전사까지 테스트: bash test_servers.sh sample.wav)"
  echo "팁: 방금 만든 TTS 출력으로 바로 테스트 가능 → bash test_servers.sh /tmp/tts_test.wav"
fi

echo ""
echo "=== 4. 현재 VRAM 사용량 ==="
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
