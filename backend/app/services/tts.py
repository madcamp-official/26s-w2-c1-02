"""질문 TTS 클라이언트 — 페르소나 음색 합성 + default 폴백.

질문 텍스트를 TTS 서버(vllm-omni VoxCPM2, POST /v1/audio/speech)로 보내
wav 바이트를 받아온다. 서버는 wav/pcm만 지원하므로 산출물은 **wav**
(storage.tts_key 기본 확장자와 일치).

persona → voice 매핑은 1:1(README A10 확정: `egen→egen` …). **페르소나
레퍼런스가 아직 서버에 등록돼 있지 않으면** `default` 외 voice는
`400 Invalid voice`로 거부되므로(persona_voices.md 주의), 그 경우 자동으로
`voice="default"`로 폴백해 합성한다 — 자산 확보 전에도 파이프라인이 돈다.

팀원2의 TTS 잡에서 호출 (질문 N개는 client를 공유해 직렬 처리):

    with httpx.Client(base_url=TTS_BASE_URL, timeout=tts.REQUEST_TIMEOUT) as c:
        for q in questions:                       # 한 번에 하나씩 (A6 큐)
            try:
                wav = tts.synthesize_question(q.text, persona=q.persona, client=c)
                key = storage.tts_key(session_id, q.id)   # sessions/{sid}/tts/{qid}.wav
                storage.save(key, wav)
                # → tts_storage_key=key, tts_status=ready
            except tts.TtsError as e:
                # → tts_status=failed, tts_error_code="TTS_FAILED", message=str(e)
                ...

동기(블로킹) 함수 — async 잡에서는 run_in_executor로 감싼다.
TTS 서버는 동시성 한계가 있으므로(A6) 세션 여러 개에 동시 실행하지 말 것.
"""

from __future__ import annotations

import os
import time

import httpx

from app.db.enums import QuestionerPersona

TTS_MODEL = "openbmb/VoxCPM2"
DEFAULT_VOICE = "default"
MAX_RETRIES = 2          # 일시 오류(네트워크·5xx) 재시도 횟수 (총 3회 시도)
REQUEST_TIMEOUT = 120.0  # 합성 자체는 수 초, 직렬 큐 대기까지 여유

# 이번 프로세스에서 미등록으로 확인된 voice — 질문마다 400 왕복을 반복하지 않기 위한
# 캐시. 서버에 페르소나가 등록되면(재기동) 백엔드도 재기동되므로 무효화 문제 없음.
_unavailable_voices: set[str] = set()


class TtsError(Exception):
    """TTS 실패(서버 오류·재시도 소진). 잡에서 tts_status='failed' 처리."""


class _VoiceRejectedError(TtsError):
    """서버가 voice를 거부(4xx) — 미등록 페르소나. default 폴백 트리거."""


def synthesize_question(
    text: str,
    *,
    persona: QuestionerPersona | str,
    base_url: str | None = None,
    client: httpx.Client | None = None,
) -> bytes:
    """질문 텍스트를 페르소나 음색의 wav 바이트로 합성한다.

    페르소나 voice가 서버에 없으면(400) default로 폴백한다. 폴백조차 실패하면
    TtsError. 멱등 — 실패 시 부분 결과 없이 예외만 던지므로 그대로 재실행 가능.
    """
    text = text.strip()
    if not text:
        raise TtsError("빈 질문 텍스트")
    voice = persona.value if isinstance(persona, QuestionerPersona) else str(persona)

    own_client = client is None
    if own_client:
        base_url = base_url or os.environ.get("TTS_BASE_URL", "http://localhost:8100")
        client = httpx.Client(base_url=base_url, timeout=REQUEST_TIMEOUT)
    try:
        if voice != DEFAULT_VOICE and voice not in _unavailable_voices:
            try:
                return _synth(client, text, voice)
            except _VoiceRejectedError:
                data = _synth(client, text, DEFAULT_VOICE)
                # default가 성공했으므로 거부 원인은 voice 미등록으로 확정 → 캐시.
                _unavailable_voices.add(voice)
                return data
        return _synth(client, text, DEFAULT_VOICE)
    finally:
        if own_client:
            client.close()


def list_voices(*, base_url: str | None = None) -> list[str]:
    """서버에 등록된 voice 이름 목록(GET /v1/audio/voices).

    잡 시작 시/운영 점검용 — 페르소나 5종이 등록됐는지 확인할 때 쓴다.
    """
    base_url = base_url or os.environ.get("TTS_BASE_URL", "http://localhost:8100")
    try:
        resp = httpx.get(f"{base_url}/v1/audio/voices", timeout=10.0)
        resp.raise_for_status()
        return [str(v) for v in resp.json().get("voices", [])]
    except (httpx.HTTPError, ValueError) as e:
        raise TtsError(f"voice 목록 조회 실패: {e}") from e


# ── 합성 요청 + 일시 오류 재시도 ────────────────────────────────────────────


def _synth(client: httpx.Client, text: str, voice: str) -> bytes:
    """단일 voice로 합성. 4xx는 즉시 _VoiceRejectedError(재시도 없음),
    네트워크·5xx는 백오프 재시도, 소진 시 TtsError."""
    last_err: Exception | None = None
    for attempt in range(1 + MAX_RETRIES):
        if attempt:
            time.sleep(2**attempt)  # 2s, 4s
        try:
            resp = client.post(
                "/v1/audio/speech",
                json={
                    "model": TTS_MODEL,
                    "input": text,
                    "voice": voice,
                    "response_format": "wav",
                },
            )
            if 400 <= resp.status_code < 500:  # 잘못된 요청은 재시도 무의미
                raise _VoiceRejectedError(
                    f"TTS 요청 거부(voice={voice}, {resp.status_code}): {resp.text[:200]}"
                )
            resp.raise_for_status()
            data = resp.content
            if not data.startswith(b"RIFF"):  # JSON 오류 본문 등이 200으로 오는 경우 방어
                raise TtsError(f"응답이 wav가 아님(voice={voice}): {data[:80]!r}")
            return data
        except (httpx.HTTPError,) as e:  # 네트워크 오류·5xx → 재시도
            last_err = e
    raise TtsError(f"TTS 합성 실패(voice={voice}, {1 + MAX_RETRIES}회 시도): {last_err}") from last_err
