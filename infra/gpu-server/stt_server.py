"""Rehearsal.io STT 서버.

Qwen3-ASR 1.7B(vLLM 백엔드) + Qwen3-ForcedAligner-0.6B(타임스탬프)를 올리고
FastAPI로 /transcribe 엔드포인트를 제공한다.

기본 제공되는 qwen-asr-serve(vLLM 서버)는 타임스탬프를 반환하지 않기 때문에
transcript.json의 `ts` 필드를 만들려면 이 커스텀 서버가 필요하다.

엔드포인트:
    GET  /health      → {"status": "ok"}
    POST /transcribe  → multipart 필드:
        file       (필수) 오디오 파일 (wav/mp3/m4a)
        language   (선택) 예: "Korean". 생략하면 자동 감지
        timestamps (선택) "true"/"false", 기본 true
      응답: {"language": ..., "text": ..., "segments": [{"text","start","end"}, ...]}

주의:
    - ForcedAligner는 오디오 1건당 최대 5분까지 지원한다.
      더 긴 발표 녹음은 백엔드에서 5분 이하 청크로 잘라 보낼 것.
    - vLLM 엔진은 프로세스당 1개이므로 요청은 락으로 직렬화한다.
      (동시성이 필요해지면 백엔드 쪽에 큐를 두는 것을 권장)
"""

import os
import tempfile
import threading

import torch
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile

HOST = os.environ.get("STT_HOST", "0.0.0.0")
PORT = int(os.environ.get("STT_PORT", "8200"))
# 24GB 기준 25% ≈ 6GB (Aligner는 vLLM 예산 밖에서 ~2GB 추가 사용)
GPU_MEM_UTIL = float(os.environ.get("STT_GPU_MEM_UTIL", "0.25"))

app = FastAPI(title="Rehearsal.io STT")
model = None
_lock = threading.Lock()


def _to_segment(stamp):
    """qwen_asr 타임스탬프 객체 → JSON 직렬화 가능한 dict."""
    return {
        "text": getattr(stamp, "text", None),
        "start": getattr(stamp, "start_time", None),
        "end": getattr(stamp, "end_time", None),
    }


def _flatten_stamps(time_stamps):
    """time_stamps가 중첩 리스트일 수 있어 방어적으로 평탄화."""
    segments = []
    for item in time_stamps or []:
        if isinstance(item, (list, tuple)):
            segments.extend(_to_segment(s) for s in item)
        else:
            segments.append(_to_segment(item))
    return segments


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/transcribe")
def transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    timestamps: bool = Form(default=True),
):
    suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file.file.read())
        path = tmp.name
    try:
        with _lock:
            results = model.transcribe(
                audio=path,
                language=language,
                return_time_stamps=timestamps,
            )
        r = results[0]
        return {
            "language": r.language,
            "text": r.text,
            "segments": _flatten_stamps(getattr(r, "time_stamps", None)) if timestamps else [],
        }
    finally:
        os.unlink(path)


if __name__ == "__main__":
    # vLLM은 multiprocessing spawn을 쓰므로 모델 초기화는 반드시 __main__ 안에서.
    from qwen_asr import Qwen3ASRModel

    print(f"[stt_server] 모델 로딩 중... (gpu_memory_utilization={GPU_MEM_UTIL})")
    model = Qwen3ASRModel.LLM(
        model="Qwen/Qwen3-ASR-1.7B",
        gpu_memory_utilization=GPU_MEM_UTIL,
        max_inference_batch_size=8,
        max_new_tokens=4096,  # 긴 오디오 대비
        forced_aligner="Qwen/Qwen3-ForcedAligner-0.6B",
        forced_aligner_kwargs=dict(
            dtype=torch.bfloat16,
            device_map="cuda:0",
        ),
    )
    print(f"[stt_server] 준비 완료 → http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
