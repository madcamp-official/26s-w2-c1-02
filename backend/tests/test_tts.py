"""질문 TTS 클라이언트 회귀 테스트 — 네트워크 없이 httpx.MockTransport로.

실행:
    cd backend
    .venv/bin/python -m pytest tests/test_tts.py -v

검증 축: persona→voice 1:1 매핑, 미등록 voice(400) → default 폴백 + 프로세스
캐시, 일시 오류(5xx) 재시도, wav 검증, 실패 시 TtsError (→ tts_status='failed').
"""

import httpx
import pytest

from app.db.enums import QuestionerPersona
from app.services import tts

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "  # RIFF 매직만 있으면 충분


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """프로세스 캐시 초기화 + 재시도 백오프 무력화(테스트 속도)."""
    tts._unavailable_voices.clear()
    monkeypatch.setattr(tts.time, "sleep", lambda _: None)


def make_client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="http://tts.test", transport=httpx.MockTransport(handler)
    )


class TestHappyPath:
    def test_persona_maps_to_voice_and_returns_wav(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            seen["body"] = json.loads(request.content)
            return httpx.Response(200, content=WAV)

        with make_client(handler) as c:
            data = tts.synthesize_question("측정 환경이 뭐였나요?", persona=QuestionerPersona.teto, client=c)

        assert data == WAV
        assert seen["body"]["voice"] == "teto"
        assert seen["body"]["model"] == tts.TTS_MODEL
        assert seen["body"]["response_format"] == "wav"

    def test_accepts_plain_string_persona(self):
        with make_client(lambda r: httpx.Response(200, content=WAV)) as c:
            assert tts.synthesize_question("q", persona="jammin", client=c) == WAV


class TestDefaultFallback:
    """페르소나 wav 미등록(현재 상태) — 400 Invalid voice → default 폴백."""

    def test_unregistered_voice_falls_back_to_default(self):
        voices = []

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            voice = json.loads(request.content)["voice"]
            voices.append(voice)
            if voice != tts.DEFAULT_VOICE:
                return httpx.Response(400, text="Invalid voice")
            return httpx.Response(200, content=WAV)

        with make_client(handler) as c:
            data = tts.synthesize_question("q1", persona=QuestionerPersona.egen, client=c)
            assert data == WAV
            assert voices == ["egen", "default"]

            # 같은 프로세스의 다음 질문은 400 왕복 없이 바로 default로.
            tts.synthesize_question("q2", persona=QuestionerPersona.egen, client=c)
            assert voices == ["egen", "default", "default"]

    def test_default_voice_skips_fallback_roundtrip(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(200, content=WAV)

        with make_client(handler) as c:
            tts.synthesize_question("q", persona="default", client=c)
        assert len(calls) == 1

    def test_both_rejected_raises_and_does_not_poison_cache(self):
        # 400 원인이 voice가 아니라 요청 자체일 때: default도 실패 → TtsError,
        # voice는 미등록으로 캐시되지 않아야 한다.
        with make_client(lambda r: httpx.Response(400, text="bad request")) as c:
            with pytest.raises(tts.TtsError):
                tts.synthesize_question("q", persona=QuestionerPersona.kkondae, client=c)
        assert "kkondae" not in tts._unavailable_voices


class TestTransientRetry:
    def test_5xx_retries_then_succeeds(self):
        n = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            n["count"] += 1
            if n["count"] < 3:
                return httpx.Response(503, text="busy")
            return httpx.Response(200, content=WAV)

        with make_client(handler) as c:
            assert tts.synthesize_question("q", persona="default", client=c) == WAV
        assert n["count"] == 3  # 1 + MAX_RETRIES

    def test_retries_exhausted_raises(self):
        with make_client(lambda r: httpx.Response(503, text="busy")) as c:
            with pytest.raises(tts.TtsError, match="3회 시도"):
                tts.synthesize_question("q", persona="default", client=c)


class TestGuards:
    def test_empty_text_raises_without_request(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("빈 텍스트는 요청하면 안 됨")

        with make_client(handler) as c:
            with pytest.raises(tts.TtsError):
                tts.synthesize_question("   ", persona="default", client=c)

    def test_non_wav_200_raises(self):
        with make_client(lambda r: httpx.Response(200, json={"error": "oops"})) as c:
            with pytest.raises(tts.TtsError, match="wav가 아님"):
                tts.synthesize_question("q", persona="default", client=c)
