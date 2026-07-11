# GPU 서버 셋업 가이드 (STT + TTS)

RTX 3090 24GB 한 장에 Rehearsal.io의 음성 모델 두 개를 올리는 가이드.

| 서버 | 모델 | 포트 | VRAM (실측, 동시 구동 시) |
|---|---|---|---|
| TTS | VoxCPM2 (vLLM-Omni) | 8100 | **~12.3GB** (`--gpu-memory-utilization 0.42`) |
| STT | Qwen3-ASR 1.7B + ForcedAligner 0.6B | 8200 | **~10.2GB** (vLLM 8.1 `util=0.40` + Aligner 2.1) |
| 여유분 | — | — | **~1GB** |

> ⚠️ **실측 기준 합계 ~22.5GB / 24GB (94%)로 매우 빠듯함.** 아래 두 가지가
> README 최초 작성 시 가정(TTS 10GB + STT 8GB + 여유 5GB)과 달랐다:
> 1. **TTS 실측 12.3GB** — `util=0.42`는 vLLM KV 캐시 예산(~10GB)만 가리키고,
>    VoxCPM2의 오디오 컴포넌트(AudioVAE·feat encoder 등 ~2.3GB)는 그 예산 밖에서
>    별도로 잡힌다. 즉 실제 점유 = `util×24GB + ~2.3GB`.
> 2. **STT는 기본값 `util=0.25`로는 TTS와 공존 불가** — TTS가 먼저 12.3GB를 쥐면
>    남은 자유 메모리가 부족해 KV 캐시 할당에 실패한다. 반드시
>    `STT_GPU_MEM_UTIL=0.40`으로 올려 실행할 것(아래 [서버 실행](#서버-실행) 참조).
> 메모리 재분배 여지는 [VRAM 조정](#vram-조정) 참고. TTS는 동시성 42배로 크게
> 과할당돼 있어 `0.30`까지 낮춰도 안전하다.

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
STT_GPU_MEM_UTIL=0.40 bash start_stt.sh   # 기본값 0.25로는 TTS와 공존 불가 → 0.40 필수
# Ctrl+B, D

# 다시 들어가려면: tmux attach -t tts (또는 stt)
```

**기동 순서: 반드시 TTS를 먼저 완전히 띄운 뒤 STT를 시작할 것.** vLLM은 자기가
뜨는 시점의 "자유 메모리"를 기준으로 KV 캐시 크기를 정하기 때문에, 나중에 뜨는 쪽이
남은 메모리를 차지한다. TTS를 먼저 고정(12.3GB)해두고 STT가 나머지를 잡는 순서가
결정적(deterministic)이라 안전하다. 순서를 바꾸면 STT가 메모리를 과점해 TTS가
못 뜰 수 있다. "Uvicorn running" / "Application startup complete" 로그가 뜨면 준비 완료.

> STT 기본값 `STT_GPU_MEM_UTIL=0.25`는 TTS와 동시 구동 시 KV 캐시 할당에 실패한다
> (`No available memory for the cache blocks`). 위처럼 `0.40`으로 올려 실행한다.
> 또한 `stt_server.py`는 `STT_MAX_MODEL_LEN`(기본 16384)으로 KV 캐시 예산을 제한하는데,
> ForcedAligner가 오디오 1건당 5분 제한이라 이 길이면 충분하고, 모델 기본값 65536을
> 그대로 쓰면 co-resident 상황에서 KV 캐시가 못 맞는다.

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
- STT 캡: 환경변수로 조정 → `STT_GPU_MEM_UTIL=0.40 bash start_stt.sh`

**메모리 산식 (실측 기반):**

- TTS 실점유 ≈ `util × 24GB + 2.3GB`(오디오 컴포넌트 고정 오버헤드).
  KV 캐시 = `util × 24GB − 4.86GB`(가중치). util을 Δ만큼 낮추면 실점유가
  거의 `Δ × 24GB`만큼 줄고, 그만큼 KV 캐시(동시성)만 깎인다.
- STT 실점유 ≈ vLLM(`util × 24GB`, 단 자유 메모리로 상한) + Aligner 2.1GB(별도).

**TTS `util` 조정 시 예상 (측정치로 외삽):**

| TTS util | TTS 실점유 | TTS KV 동시성(@4096) | STT에 넘겨줄 여유 |
|---|---|---|---|
| 0.42 (현재) | ~12.3GB | 42.7x | 0 (현재 94% 포화) |
| 0.35 | ~10.6GB | ~30x | +1.7GB |
| **0.30 (권장)** | **~9.4GB** | **~20x** | **+2.9GB** |
| 0.25 | ~8.2GB | ~10x | +4.1GB |
| 0.22 (하한 근처) | ~7.5GB | ~4x | +4.8GB |

TTS는 리허설 앱 특성상 동시 합성이 사실상 1건이라 42.7x는 크게 과할당이다.
**`0.30`으로 낮추면 동시성 20x(여전히 충분)를 유지하면서 ~2.9GB를 확보**,
STT의 굶주린 KV 캐시(현재 1.09x, 요청 1건 겨우)를 3~5x로 키우거나 안전 여유로
남길 수 있다. 이 경우 합계가 ~85%로 내려가 README 최초 가정 상한과 맞는다.

OOM이 나면 캡을 0.05씩 낮추고, 합이 0.85를 넘지 않게 유지.

## 트러블슈팅

| 증상 | 원인/해결 |
|---|---|
| `CUDA out of memory` | 위 VRAM 조정 참고. 다른 프로세스가 GPU를 쓰고 있는지 `nvidia-smi`로 확인 |
| STT `No available memory for the cache blocks` | TTS와 공존 시 STT KV 캐시 부족. `STT_GPU_MEM_UTIL=0.40`으로 올리고, TTS를 먼저 띄웠는지 확인 |
| STT `... KV cache is needed, larger than available` | `max_model_len`이 너무 큼. `STT_MAX_MODEL_LEN=16384`(기본) 사용 — 기본 65536은 co-resident 시 안 맞음 |
| 포트 이미 사용 중 | `lsof -i :8100` 으로 점유 프로세스 확인 후 종료 |
| 모델 다운로드가 느림/실패 | HuggingFace 접속 문제. 재시도하거나 `HF_ENDPOINT=https://hf-mirror.com` 설정 |
| `spawn` 관련 에러 (STT) | `python stt_server.py`로 실행했는지 확인 (uvicorn 직접 실행 금지) |
| vllm-omni 설치 실패 | 저장소가 빠르게 변하는 중. `cd vllm-omni && git pull` 후 재설치 |
| TTS `libcudart.so.12` / `ptxas Unsupported .version` / `cannot find -lcudart` | vLLM(0.24.0)·torch(2.11+cu130)·vllm-omni(v0.24.1) 버전 정합 + CUDA JIT 툴체인 문제. `setup_tts.sh` 참고 — nvcc/nvvm/cuda-crt/cccl을 13.0으로 핀하고 `start_tts.sh`가 `CUDA_HOME`을 설정해야 FlashInfer JIT이 컴파일된다 |

## 알려진 제약 (백엔드 설계 시 반영)

1. **ForcedAligner는 오디오 1건당 최대 5분.** 60분 발표 녹음은 백엔드에서 5분 이하 청크로 잘라 `/transcribe`에 순차 요청하고, 각 청크의 타임스탬프에 오프셋을 더해 합칠 것.
2. **STT 서버는 요청을 직렬 처리** (락 사용). 발표 전사(긴 작업) 중에 답변 전사(짧은 작업)가 오면 대기함. 명세의 비동기 폴링 구조(§1.2)와는 잘 맞지만, 동시 사용자가 늘면 백엔드에 작업 큐 필요.
3. **TTS 음성(voice) 파라미터**: 페르소나별 음성 매핑(에겐/테토/꼰대/멍청/잼민)은 voice design 작업 후 확정. 지금은 `default` 하나.

## 참고 문서

- [VoxCPM vLLM-Omni 배포 문서](https://voxcpm.readthedocs.io/en/latest/deployment/vllm_omni.html)
- [Qwen3-ASR GitHub](https://github.com/QwenLM/Qwen3-ASR)
- [Qwen3-ASR-1.7B (HuggingFace)](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) · [Qwen3-ForcedAligner-0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)
