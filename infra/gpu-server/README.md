# GPU 서버 셋업 가이드 (STT + TTS)

RTX 3090 24GB 한 장에 Rehearsal.io의 음성 모델 두 개를 올리는 가이드.

| 서버 | 모델 | 포트 | VRAM (실측, 동시 구동 시) |
|---|---|---|---|
| TTS | VoxCPM2 (vLLM-Omni) | 8100 | **~11.2GB** (`--kv-cache-memory-bytes 4GiB`) |
| STT | Qwen3-ASR 1.7B + ForcedAligner 0.6B | 8200 | **~10.2GB** (vLLM 8.1 `util=0.40` + Aligner 2.1) |
| 여유분 | — | — | **~2.6GB** |

> ⚠️ **TTS VRAM은 `--gpu-memory-utilization`가 아니라 KV 캐시 크기로 조정한다.**
> README 최초 작성 시 가정(TTS 10GB + STT 8GB)과 달랐던 이유:
> 1. **TTS 점유 = 가중치(~4.86GB) + KV 캐시(고정) + 디퓨전 side-path(~2.3GB).**
>    VoxCPM2 deploy YAML이 KV 캐시를 `kv_cache_memory_bytes`로 **고정**하기 때문에
>    `gpu_memory_utilization`을 낮춰도 실점유가 줄지 않는다(상한선일 뿐). 실제로
>    줄이려면 `--kv-cache-memory-bytes`를 낮춘다. 디퓨전 오디오 컴포넌트
>    (AudioVAE·LocDiT·code2wav 등 ~2.3GB)는 KV 예산 밖에서 별도로 잡힌다.
>    `start_tts.sh`는 KV를 6GiB(YAML 기본)→4GiB로 낮춰 실점유 ~11.2GB.
> 2. **STT는 기본값 `util=0.25`로는 TTS와 공존 불가** — TTS가 먼저 VRAM을 쥐면
>    남은 자유 메모리가 부족해 KV 캐시 할당에 실패한다. 반드시
>    `STT_GPU_MEM_UTIL=0.40`으로 올려 실행할 것(아래 [서버 실행](#서버-실행) 참조).
> 메모리 재분배 여지는 [VRAM 조정](#vram-조정) 참고. TTS KV는 동시성 1건 앱 대비
> 과할당이라 `--kv-cache-memory-bytes 3GiB`까지 낮춰도 안전하다.

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

- **TTS 캡: `--gpu-memory-utilization`가 아니라 `--kv-cache-memory-bytes`로 조정한다.**
  `start_tts.sh`의 `TTS_KV_CACHE_BYTES`(기본 4GiB)를 수정하거나
  환경변수로 넘긴다 → `TTS_KV_CACHE_BYTES=3221225472 bash start_tts.sh`(3GiB).
- STT 캡: 환경변수로 조정 → `STT_GPU_MEM_UTIL=0.40 bash start_stt.sh`

> ⚠️ **`--gpu-memory-utilization`를 낮춰도 TTS VRAM은 줄지 않는다 (중요).**
> VoxCPM2 deploy YAML(`vllm_omni/deploy/voxcpm2.yaml`)이 KV 캐시를
> `kv_cache_memory_bytes: 6GiB`로 **고정**해 두기 때문이다. vLLM-Omni 워커의
> `determine_available_memory()`(`vllm_omni/worker/base.py:110`)는 이 값이 설정돼
> 있으면 `gpu_memory_utilization` 기반 계산을 통째로 건너뛰고 고정값을 그대로
> 쓴다. 즉 `gpu_memory_utilization`은 프로세스 상한선일 뿐, util을 낮춰도 실제
> 점유(가중치 + 고정 KV + 디퓨전 side-path)는 그대로다.
> **실제로 VRAM을 줄이려면 KV 캐시 크기(`--kv-cache-memory-bytes`)를 낮춰야 한다.**

**메모리 산식 (실측 기반):**

- TTS 실점유 ≈ `가중치(~4.86GB) + KV 캐시(--kv-cache-memory-bytes) + 디퓨전 side-path(~2.3GB)`.
  디퓨전 side-path(LocDiT/AudioVAE/code2wav)는 KV 예산 밖에서 추론 중 잡히는
  고정 오버헤드다. **KV 캐시를 Δ만큼 줄이면 실점유가 거의 Δ만큼 줄어든다.**
  `gpu_memory_utilization`은 이 셋에 영향을 주지 않는다(위 경고 참고).
- STT 실점유 ≈ vLLM(`util × 24GB`, 단 자유 메모리로 상한) + Aligner 2.1GB(별도).
  (STT는 `kv_cache_memory_bytes` 고정이 없어 `STT_GPU_MEM_UTIL`이 정상적으로 먹는다.)

**TTS `--kv-cache-memory-bytes` 조정 시 예상:**

| TTS KV 캡 | TTS 실점유(≈4.86 가중치 + KV + 2.3 디퓨전) | KV admission 여유(@8seq×4096) |
|---|---|---|
| 6GiB (YAML 기본) | ~13.2GB | 매우 넉넉 |
| **4GiB (start_tts.sh 기본, 권장)** | **~11.2GB** | 32k 토큰 admission 충분 |
| 3GiB | ~10.2GB | 여전히 충분(동시성 ~1건 앱) |
| 2GiB (하한 근처) | ~9.2GB | 빠듯 — 긴 요청 시 admission 지연 가능 |

TTS는 리허설 앱 특성상 동시 합성이 사실상 1건(`max_num_seqs=8`, `max_model_len=4096`)이라
KV 6GiB는 과할당이다. **4GiB로 내려도 admission working set(최대 8×4096=32k 토큰)을
충분히 담으며 ~2GB를 절약**, STT에 여유를 넘기거나 안전 마진으로 둘 수 있다.

OOM이나 admission 지연이 나면 KV 캡을 1GiB씩 올리고, TTS+STT 합이 ~0.85×24GB를
넘지 않게 유지.

## STT 실측 & 청크 크기 결정 (Day 3, 팀원3)

한국어 STT 변환 소요시간 실측 → **폴링 간격(spec §8, A2)·청크 길이 확정** 근거.

측정 조건: RTX 3090, TTS(VoxCPM2)·STT **동시 상주**(실배포와 동일), STT는 직렬
처리. 입력은 TTS로 생성한 한국어 발표체 음성을 이어붙여 길이별로 만든 뒤
`/transcribe`(language=Korean, timestamps=true)로 각 3회 측정한 중앙값(왕복 벽시계,
업로드+전사+타임스탬프 정렬 포함). 측정일 2026-07-11.

| 오디오 길이 | 전사 소요(중앙값) | RTF(소요/길이) | 비고 |
|---|---|---|---|
| 30s | 1.1s | 0.036 | |
| 60s | 2.1s | 0.034 | **청크 후보** |
| 120s | 6.4s | 0.053 | 관측된 최악 RTF |
| 180s | 8.5s | 0.047 | |
| 300s (ForcedAligner 상한) | 9.7s | 0.032 | 5분 1건도 <10s |

**결론: STT는 실시간 대비 ~20–30배 빠르다(RTF ≤ ~0.05).**

### 청크 크기 결정 → **60초 + 4초 겹침(overlap)**

불변 조건 "청크 STT 처리시간 < 청크 길이"(루트 README 발표 녹음 파이프라인)를
60초 청크는 **2.1s ≪ 60s(약 30배 여유)**로 크게 만족 → 60분 발표에서도 직렬 큐에
백로그가 쌓이지 않는다(총 STT 부하 ≈ 60min×RTF ≈ 3분, 발표 시간에 분산). 60초를
고른 이유:

- ForcedAligner 5분 상한 대비 5배 여유(겹침 포함해도 안전).
- 발표 종료 직후 마지막 청크(≤60s)만 남아 전사 완료까지 **~2s** → 전사 tail latency 최소.
- "발표 끝나기 전 대부분 전사"(설계 목표)에 맞는 증분 진행. 더 키우면(120–180s)
  병합 이음새는 줄지만 첫 전사·tail이 늦어지고 5분 상한 여유가 준다.
- 겹침 4초는 경계 단어 잘림 방지(병합에서 겹침 구간 중복 제거).

### 폴링 간격 근거 (spec §8, A2 = 1~2초)

- **답변 STT**(단발, 청크 없음): 답변은 짧아(수초~30s) 전사 ~1–2s → `POST /answer`(202)
  후 `GET /qna` 1~2초 폴링이면 1~2회 안에 `ready` 관측.
- **발표 전사**(청크): 청크당 ~2s에 완료되어 상태가 청크 주기로 갱신 → 1~2초 폴링
  적정. 최악(5분 단일)이라도 <10s.
- 즉 **A2의 1~2초 폴링은 STT 지연(≈1–2s)과 정합**하며 과도한 폴링 부하도 없다.

> 재현: `scratchpad/stt_bench/`의 방식(TTS로 발표체 음성 생성 → `wave`로 길이별
> 연결 → `/transcribe` 3회 측정). ffmpeg 없이 stdlib `wave`만 사용.

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
3. **TTS 음성(voice) 파라미터**: 페르소나별 음성 매핑(에겐/테토/꼰대/멍청/잼민)은 voice design 작업 후 확정. **지금은 `default` 하나뿐**(서버가 그 외 voice는 `400 Invalid voice`로 거부). 설계·설치법은 [persona_voices.md](persona_voices.md). VoxCPM2는 지시(instruction)로 말투를 못 바꾸는 **레퍼런스 오디오 클로닝 전용**이라 페르소나 5종은 각각 레퍼런스 wav가 있어야 만들 수 있다(자산 미확보 상태).

## 참고 문서

- [VoxCPM vLLM-Omni 배포 문서](https://voxcpm.readthedocs.io/en/latest/deployment/vllm_omni.html)
- [Qwen3-ASR GitHub](https://github.com/QwenLM/Qwen3-ASR)
- [Qwen3-ASR-1.7B (HuggingFace)](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) · [Qwen3-ForcedAligner-0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)
