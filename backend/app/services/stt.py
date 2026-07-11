"""발표 녹음 STT 클라이언트 — 청크 분할 + 타임스탬프 오프셋 병합.

긴 녹음(≤60분)을 ForcedAligner 상한(5분/건) 아래의 청크로 잘라 STT 서버
(stt_server.py, POST /transcribe)에 직렬 요청하고, 청크별 타임스탬프에
오프셋을 더해 transcripts.segments JSONB 형식으로 병합한다.

    [{"start": 12.0, "end": 15.2, "text": "..."}]   # 초 단위 float

팀원2의 STT 잡에서 호출 (세부 계획: docs/stt-client-workflow.md):

    try:
        segments = transcribe_recording(audio_path)
    except UnsupportedMediaError:
        # → 415 UNSUPPORTED_MEDIA
    except SttError:
        # → transcript.status="failed" (STT_FAILED) / retry

동기(블로킹) 함수 — async 잡에서는 run_in_executor로 감싼다.
STT 서버가 직렬 처리이므로 이 함수를 세션 여러 개에 동시 실행하지 말 것
(백엔드 큐에서 한 번에 하나씩).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import httpx

# 청크 파라미터 — Day 3 실측 근거(60s→2.1s, RTF≈0.03). 경계 병합 품질이
# 나쁘면 CHUNK_SEC=290으로 전환 가능 (stt-client-workflow.md 재검토 표)
CHUNK_SEC = 60
OVERLAP_SEC = 4
SAMPLE_RATE = 16000
MAX_RETRIES = 2          # 청크당 재시도 횟수 (총 3회 시도)
REQUEST_TIMEOUT = 120.0  # 5분 청크 전환 시에도 여유 (300s 전사 ≈ 10s)

# 세그먼트 그룹화 — ForcedAligner는 형태소 단위 스탬프를 주므로(예: '발표'+'를')
# 쉼(pause) 기준으로 문장급 세그먼트로 묶는다. 실측(TTS 합성 발화):
# 어절 내부 갭 ≤0.24s, 문장 경계 ≥0.32s
GROUP_GAP_SEC = 0.35
GROUP_MAX_SEC = 15.0     # 쉼 없이 이어져도 강제 분할 (ts 참조 정밀도 확보)


class SttError(Exception):
    """STT 실패(서버 오류·재시도 소진). 잡에서 STT_FAILED/retry 처리."""


class UnsupportedMediaError(SttError):
    """오디오 디코드 불가(형식 미지원·손상). → 415 UNSUPPORTED_MEDIA."""


# stt_server(Qwen3-ASR)는 ISO 코드가 아니라 전체 언어명("Korean")을 요구한다
_LANGUAGE_NAMES = {"ko": "Korean", "ko-kr": "Korean", "en": "English", "en-us": "English"}


def transcribe_recording(
    audio_path: str | Path,
    *,
    language: str = "ko",
    base_url: str | None = None,
) -> list[dict]:
    """녹음 파일 전체를 전사해 병합된 세그먼트 목록을 반환한다.

    ≤64초 오디오(답변 STT 포함)는 분할 없이 단일 요청으로 처리된다.
    멱등 — 실패 시 부분 결과 없이 예외만 던지므로 그대로 재실행 가능.
    """
    base_url = base_url or os.environ.get("STT_BASE_URL", "http://localhost:8200")
    language = _LANGUAGE_NAMES.get(language.lower(), language)
    with tempfile.TemporaryDirectory(prefix="stt_chunks_") as td:
        tmp = Path(td)
        wav_path = _normalize_audio(Path(audio_path), tmp / "norm.wav")
        chunks = _split_wav(wav_path, tmp)

        words: list[dict] = []
        last_index = len(chunks) - 1
        with httpx.Client(base_url=base_url, timeout=REQUEST_TIMEOUT) as client:
            for i, (offset, chunk_path) in enumerate(chunks):
                text, stamps = _transcribe_chunk(client, chunk_path, language)
                aligned = _attach_display_text(stamps, text)
                words.extend(
                    _shift_and_trim(aligned, offset, is_first=(i == 0), is_last=(i == last_index))
                )
    words.sort(key=lambda w: (w["start"], w["end"]))
    return _group_words(words)


# ── 1. 오디오 정규화 (ffmpeg → 16kHz mono s16 wav) ──────────────────────────


def _ffmpeg_exe() -> str:
    if exe := shutil.which("ffmpeg"):
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as e:
        raise SttError("ffmpeg 없음: 시스템 설치 또는 pip install imageio-ffmpeg") from e


def _normalize_audio(src: Path, dst: Path) -> Path:
    if not src.exists():
        raise SttError(f"오디오 파일 없음: {src}")
    cmd = [
        _ffmpeg_exe(), "-y", "-v", "error",
        "-i", str(src),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not dst.exists():
        raise UnsupportedMediaError(f"오디오 디코드 실패: {proc.stderr.strip()[-300:]}")
    return dst


# ── 2. 분할: 청크 i = [i·CHUNK, i·CHUNK + CHUNK + OVERLAP) ──────────────────


def _split_wav(wav_path: Path, out_dir: Path) -> list[tuple[float, Path]]:
    """(오프셋 초, 청크 wav 경로) 목록. 오프셋은 stride(CHUNK_SEC) 배수."""
    with wave.open(str(wav_path), "rb") as w:
        rate = w.getframerate()
        params = w.getparams()
        total = w.getnframes()

        stride = CHUNK_SEC * rate
        length = (CHUNK_SEC + OVERLAP_SEC) * rate

        if total <= length:  # 답변 STT 등 짧은 오디오: 분할 없이 원본 그대로
            return [(0.0, wav_path)]

        chunks: list[tuple[float, Path]] = []
        i = 0
        while (start := i * stride) < total:
            # 새로 커버하는 구간이 없으면(직전 청크의 겹침이 이미 끝까지 도달) 종료
            if i > 0 and start + OVERLAP_SEC * rate >= total:
                break
            w.setpos(start)
            frames = w.readframes(min(length, total - start))
            chunk_path = out_dir / f"chunk_{i:04d}.wav"
            with wave.open(str(chunk_path), "wb") as cw:
                cw.setparams(params)
                cw.writeframes(frames)
            chunks.append((float(i * CHUNK_SEC), chunk_path))
            i += 1
        return chunks


# ── 3. 직렬 전송 + 청크 단위 재시도 ─────────────────────────────────────────


def _transcribe_chunk(client: httpx.Client, chunk_path: Path, language: str) -> tuple[str, list[dict]]:
    """(punctuated 전체 텍스트, 형태소 단위 타임스탬프 목록) 반환."""
    last_err: Exception | None = None
    for attempt in range(1 + MAX_RETRIES):
        if attempt:
            time.sleep(2**attempt)  # 2s, 4s
        try:
            with open(chunk_path, "rb") as f:
                resp = client.post(
                    "/transcribe",
                    files={"file": (chunk_path.name, f, "audio/wav")},
                    data={"language": language, "timestamps": "true"},
                )
            resp.raise_for_status()
            body = resp.json()
            stamps = [
                {"start": float(s["start"]), "end": float(s["end"]), "text": str(s["text"]).strip()}
                for s in body.get("segments") or []
                if str(s.get("text", "")).strip()
            ]
            return str(body.get("text", "")), stamps
        except (httpx.HTTPError, KeyError, ValueError) as e:
            last_err = e
    raise SttError(f"청크 전사 실패({chunk_path.name}, {1 + MAX_RETRIES}회 시도): {last_err}") from last_err


# ── 4·5. 오프셋 합산 + 겹침 중복 제거 ───────────────────────────────────────


def _shift_and_trim(segments: list[dict], offset: float, *, is_first: bool, is_last: bool) -> list[dict]:
    """청크 로컬 타임스탬프 → 절대 시간, 겹침 구간은 중점 절단 규칙으로 귀속.

    경계 b에서 절단점 cut = b + OVERLAP/2. 세그먼트는 중점(mid)이 속한
    쪽 청크가 채택한다 — 겹침 4s를 양쪽이 다 들었으므로, 세그먼트를
    온전히 들은 쪽(중점이 자기 영역인 쪽)만 남겨 중복·반토막을 방지.
    """
    half = OVERLAP_SEC / 2
    lo = float("-inf") if is_first else offset + half
    hi = float("inf") if is_last else offset + CHUNK_SEC + half
    out = []
    for s in segments:
        start, end = s["start"] + offset, s["end"] + offset
        mid = (start + end) / 2
        if lo <= mid < hi:
            out.append({**s, "start": round(start, 3), "end": round(end, 3)})
    return out


# ── 표시 텍스트 정렬 + 문장급 그룹화 ────────────────────────────────────────
#
# ForcedAligner 스탬프는 형태소 단위('발표'+'를')·무구두점이라 그대로 이으면
# 한국어 띄어쓰기가 깨진다. punctuated 전체 텍스트(body["text"])에 스탬프를
# 문자 단위로 정렬해 원래의 띄어쓰기·구두점을 물려받은 표시 텍스트를 만든다.

_TRAILING_PUNCT = set(".,!?…;:)]}\"'»%")


def _attach_display_text(stamps: list[dict], text: str) -> list[dict]:
    """각 스탬프에 display(원문 표기)·glue(앞 스탬프와 붙여쓰기) 부여.

    정렬 실패(스탬프·텍스트 불일치) 시 해당 청크는 스탬프 원문 그대로
    띄어쓰기 조인으로 강등된다 — 전사 유실보다 표기 열화를 택한다.
    """
    pos = 0
    n = len(text)
    for idx, w in enumerate(stamps):
        chars = [c for c in w["text"] if not c.isspace()]
        spans: list[int] = []
        p = pos
        try:
            for c in chars:
                while p < n and (text[p].isspace() or (not spans and text[p] in _TRAILING_PUNCT)):
                    p += 1
                if p >= n or text[p] != c:
                    raise ValueError
                spans.append(p)
                p += 1
        except ValueError:  # 정렬 실패 → 이 청크 나머지는 fallback
            for rest in stamps[idx:]:
                rest.setdefault("display", rest["text"])
                rest.setdefault("glue", False)
            return stamps
        start_idx, end_idx = spans[0], spans[-1] + 1
        while end_idx < n and text[end_idx] in _TRAILING_PUNCT:  # 붙은 구두점 포함
            end_idx += 1
        w["display"] = text[start_idx:end_idx]
        w["glue"] = start_idx == pos and pos != 0  # 앞 조각과 공백 없이 연속
        pos = end_idx
    return stamps


def _group_words(words: list[dict]) -> list[dict]:
    """쉼(pause) 기준으로 형태소 스탬프를 문장급 세그먼트로 묶는다."""
    segments: list[dict] = []
    cur: dict | None = None
    for w in words:
        glue = w.get("glue", False)
        if cur is not None and not glue:
            too_long = w["end"] - cur["start"] > GROUP_MAX_SEC
            if w["start"] - cur["end"] >= GROUP_GAP_SEC or too_long:
                segments.append(cur)
                cur = None
        piece = w.get("display", w["text"])
        if cur is None:
            cur = {"start": w["start"], "end": w["end"], "text": piece}
        else:
            cur["text"] += piece if glue else f" {piece}"
            cur["end"] = max(cur["end"], w["end"])
    if cur is not None:
        segments.append(cur)
    return segments
