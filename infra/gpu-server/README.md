# GPU 서버 셋업 가이드 (STT + TTS)

RTX 3090 24GB 한 장에 Rehearsal.io의 음성 모델 두 개를 올리는 가이드.

| 서버 | 모델 | 포트 | VRAM 예산 |
|---|---|---|---|
| TTS | VoxCPM2 (vLLM-Omni) | 8100 | 42% (~10GB) |
| STT | Qwen3-ASR 1.7B + ForcedAligner 0.6B | 8200 | ~8GB (vLLM 25% + Aligner ~2GB) |
| 여유분 | — | — | ~5GB |

## 사전 확인 (서버에서)

```bash
nvidia-smi          # GPU와 드라이버 확인. CUDA Version 12.0 이상이면 OK
python3 --version   # 3.10 이상 (없어도 uv가 3.12를 받아줌)
git --version
df -h ~             # 여유 디스크 30GB 이상 권장 (모델 가중치 다운로드용)
```

## 설치 순서

이 폴더(`infra/gpu-server/`)를 통째로 GPU 서버에 복사한 뒤:

```bash
# 1. 프로젝트 클론 또는 폴더 복사 후 이동
cd infra/gpu-server

# 2. 실행 권한 부여
chmod +x *.sh

# 3. 환경 설치 (각각 5~15분, 인터넷 속도에 따라 다름)
bash setup_tts.sh
bash setup_stt.sh
```

TTS와 STT는 **별도 가상환경**(.venv-tts / .venv-stt)을 씀. vLLM 버전 요구사항이 서로 달라 한 환경에 섞으면 깨진다.

## 서버 실행

터미널을 닫아도 서버가 계속 돌게 `tmux`를 쓰는 걸 추천:

```bash
# TTS 서버 (첫 실행 시 모델 ~5GB 자동 다운로드)
tmux new -s tts
bash start_tts.sh
# Ctrl+B 누르고 D → tmux에서 빠져나옴 (서버는 계속 돌아감)

# STT 서버 (첫 실행 시 모델 ~5GB 자동 다운로드)
tmux new -s stt
bash start_stt.sh
# Ctrl+B, D

# 다시 들어가려면: tmux attach -t tts (또는 stt)
```

기동 순서는 상관없지만 **하나가 완전히 뜬 뒤 다음을 시작**하는 게 안전함 (동시에 뜨면 VRAM 프로파일링이 겹칠 수 있음). "Uvicorn running" / "Application startup complete" 로그가 뜨면 준비 완료.

## 동작 확인

```bash
bash test_servers.sh                  # TTS 합성 + STT 헬스체크 + VRAM 확인
bash test_servers.sh /tmp/tts_test.wav  # TTS가 만든 음성을 STT로 전사 (왕복 테스트)
```

## API 사용법 (백엔드에서 호출)

**TTS** — OpenAI 호환 `/v1/audio/speech`:

```bash
curl http://<서버IP>:8100/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"openbmb/VoxCPM2","input":"질문 텍스트","voice":"default"}' \
  --output question.wav
```

**STT** — 커스텀 `/transcribe` (타임스탬프 포함):

```bash
curl http://<서버IP>:8200/transcribe \
  -F "file=@recording.m4a" \
  -F "language=Korean" \
  -F "timestamps=true"
# → {"language":"Korean","text":"...","segments":[{"text":"안녕하세요","start":0.5,"end":1.2},...]}
```

> 기본 제공 서버(`qwen-asr-serve`)는 타임스탬프를 안 주기 때문에 `stt_server.py`를 직접 만들었음. transcript.json의 `ts` 필드가 여기서 나온다.

## VRAM 조정

실행 후 `nvidia-smi`로 실측하고, 필요하면:

- TTS 캡: `start_tts.sh`의 `--gpu-memory-utilization 0.42` 수정
- STT 캡: 환경변수로 조정 → `STT_GPU_MEM_UTIL=0.30 bash start_stt.sh`

OOM이 나면 캡을 0.05씩 낮추고, 합이 0.85를 넘지 않게 유지.

## 트러블슈팅

| 증상 | 원인/해결 |
|---|---|
| `CUDA out of memory` | 위 VRAM 조정 참고. 다른 프로세스가 GPU를 쓰고 있는지 `nvidia-smi`로 확인 |
| 포트 이미 사용 중 | `lsof -i :8100` 으로 점유 프로세스 확인 후 종료 |
| 모델 다운로드가 느림/실패 | HuggingFace 접속 문제. 재시도하거나 `HF_ENDPOINT=https://hf-mirror.com` 설정 |
| `spawn` 관련 에러 (STT) | `python stt_server.py`로 실행했는지 확인 (uvicorn 직접 실행 금지) |
| vllm-omni 설치 실패 | 저장소가 빠르게 변하는 중. `cd vllm-omni && git pull` 후 재설치 |

## 알려진 제약 (백엔드 설계 시 반영)

1. **ForcedAligner는 오디오 1건당 최대 5분.** 60분 발표 녹음은 백엔드에서 5분 이하 청크로 잘라 `/transcribe`에 순차 요청하고, 각 청크의 타임스탬프에 오프셋을 더해 합칠 것.
2. **STT 서버는 요청을 직렬 처리** (락 사용). 발표 전사(긴 작업) 중에 답변 전사(짧은 작업)가 오면 대기함. 명세의 비동기 폴링 구조(§1.2)와는 잘 맞지만, 동시 사용자가 늘면 백엔드에 작업 큐 필요.
3. **TTS 음성(voice) 파라미터**: 페르소나별 음성 매핑(에겐/테토/꼰대/멍청/잼민)은 voice design 작업 후 확정. 지금은 `default` 하나.

## 참고 문서

- [VoxCPM vLLM-Omni 배포 문서](https://voxcpm.readthedocs.io/en/latest/deployment/vllm_omni.html)
- [Qwen3-ASR GitHub](https://github.com/QwenLM/Qwen3-ASR)
- [Qwen3-ASR-1.7B (HuggingFace)](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) · [Qwen3-ForcedAligner-0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)
