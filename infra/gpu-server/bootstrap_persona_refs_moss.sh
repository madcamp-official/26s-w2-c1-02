#!/usr/bin/env bash
# 페르소나 레퍼런스 부트스트랩 — MOSS-VoiceGenerator 1회성 기동 (Path B-2)
#
# 3090 24GB에는 VoxCPM2(8100)+STT(8200)가 상주해 여유가 없으므로, 두 서버를
# 잠시 내린 상태에서 MOSS-VoiceGenerator(zero-shot voice design)를 8101에 띄워
# 페르소나 레퍼런스 5종을 생성하고(voices/refs_moss/) 즉시 종료한다.
# 첫 실행은 모델 다운로드(~5GB)가 있어 오래 걸릴 수 있다(디스크 39GB 여유 확인됨).
#
# 사용법:
#   bash bootstrap_persona_refs_moss.sh            # VRAM 부족 시 안내만 하고 중단
#   STOP_SERVERS=1 bash bootstrap_persona_refs_moss.sh   # 기존 서버 자동 중단 포함
#
# 끝나면 기존 서버 복구: bash start_tts.sh / bash start_stt.sh (각자 세션에서)
set -euo pipefail
cd "$(dirname "$0")"

PORT=8101
MODEL="OpenMOSS-Team/MOSS-VoiceGenerator"
NEED_MIB=18000   # stage0 0.60 + stage1 0.12 of 24GB ≈ 17.7GB 예약
WAIT_MAX="${WAIT_MAX:-2400}"  # 최대 대기(s) — 첫 실행은 다운로드 포함
LOG=/tmp/moss_voicegen_bootstrap.log

free_mib() {
  nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1
}

if [ "$(free_mib)" -lt "$NEED_MIB" ]; then
  if [ "${STOP_SERVERS:-0}" = "1" ]; then
    echo "[bootstrap] VRAM 부족 → 기존 서버 중단 (복구: start_tts.sh / start_stt.sh)"
    pkill -f "vllm serve openbmb/VoxCPM2" 2>/dev/null || true
    pkill -f "stt_server" 2>/dev/null || true
    for _ in $(seq 30); do
      [ "$(free_mib)" -ge "$NEED_MIB" ] && break
      sleep 2
    done
  fi
  if [ "$(free_mib)" -lt "$NEED_MIB" ]; then
    cat <<EOF
[bootstrap] VRAM 여유 부족: $(free_mib)MiB < ${NEED_MIB}MiB
  기존 서버를 내리고 다시 실행하세요:
    pkill -f "vllm serve openbmb/VoxCPM2"   # TTS(8100)
    pkill -f "stt_server"                    # STT(8200)
  또는: STOP_SERVERS=1 bash bootstrap_persona_refs_moss.sh
EOF
    exit 1
  fi
fi

export PATH="$HOME/.local/bin:$PATH"
source .venv-tts/bin/activate
export CUDA_HOME="$(python -c 'import nvidia.cu13; print(nvidia.cu13.__path__[0])')"
export PATH="$CUDA_HOME/bin:$PATH"
export CUDA_VISIBLE_DEVICES=0

echo "[bootstrap] $MODEL 기동 (포트 $PORT, 로그 $LOG)"
vllm serve "$MODEL" --omni --host 127.0.0.1 --port "$PORT" >"$LOG" 2>&1 &
SERVER_PID=$!
trap 'echo "[bootstrap] 서버 종료(pid=$SERVER_PID)"; kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true' EXIT

elapsed=0
until curl -sf "http://127.0.0.1:$PORT/v1/audio/voices" >/dev/null 2>&1; do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "[bootstrap] 서버 프로세스 조기 종료 — 로그 마지막 30줄:"; tail -30 "$LOG"; exit 1
  fi
  if [ "$elapsed" -ge "$WAIT_MAX" ]; then
    echo "[bootstrap] ${WAIT_MAX}s 내 미기동 — 로그 마지막 30줄:"; tail -30 "$LOG"; exit 1
  fi
  sleep 10; elapsed=$((elapsed + 10))
  [ $((elapsed % 60)) -eq 0 ] && echo "[bootstrap] 대기 ${elapsed}s… ($(tail -1 "$LOG" | cut -c1-90))"
done
echo "[bootstrap] 서버 준비 완료 (${elapsed}s)"

MOSS_TTS_URL="http://127.0.0.1:$PORT" python3 build_persona_refs_moss.py

echo "[bootstrap] 완료. 기존 서버 복구를 잊지 마세요: bash start_tts.sh / bash start_stt.sh"
