"""Q&A 응답 스키마 회귀 테스트 (Step 3 작업 1) — DB 없이 순수 단위.

실행:
    cd backend
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_qna_schemas.py -v

목적: GET /qna 응답(QnaStateOut)이 api-spec §4.4 예시와 **필드 단위로 일치**하는지 잠근다.
팀원1 폴링이 이 형태에 의존하므로, 스키마가 바뀌면 여기서 먼저 깨져야 한다.
"""

import pytest
from pydantic import ValidationError

from app.schemas.qna import (
    AnswerOut,
    EvidenceOut,
    PassRequest,
    QnaStateOut,
    QnaStatus,
    QuestionOut,
    TranscriptRefOut,
    TtsOut,
)


def _spec_example_state() -> QnaStateOut:
    """api-spec §4.4 GET /qna 응답 예시를 그대로 조립."""
    return QnaStateOut(
        status=QnaStatus.in_progress,
        current_question_id="q_2",
        ended_reason=None,
        questions=[
            QuestionOut(
                id="q_1", order=1, persona="kkondae", strategy="detail_probe",
                parent_id=None, follow_up_depth=0,
                text="측정 환경이 뭐였는지 설명해봐요.",
                evidence=EvidenceOut(slides=[3], transcript_refs=[TranscriptRefOut(ts="04:12")]),
                tts=TtsOut(status="ready", audio_url="https://.../q1.mp3"),
                answer=AnswerOut(
                    status="ready",
                    text="사내 서버 A100 1대에서 3회 평균으로 측정했습니다.",
                    audio_url="https://.../a1.m4a",
                    follow_up_status="none",
                ),
            ),
            QuestionOut(
                id="q_2", order=2, persona="egen", strategy="big_picture",
                parent_id=None, follow_up_depth=0,
                text="경쟁 서비스 대비 차별점이 뭔가요?",
                evidence=EvidenceOut(),  # slides=[], transcript_refs=[]
                tts=TtsOut(status="ready", audio_url="https://.../q2.mp3"),
                answer=AnswerOut(
                    status="processing", text=None,
                    audio_url="https://.../a2.m4a", follow_up_status="pending",
                ),
            ),
        ],
    )


class TestSpecShape:
    def test_dump_matches_spec_example(self):
        dumped = _spec_example_state().model_dump()
        assert dumped == {
            "status": "in_progress",
            "current_question_id": "q_2",
            "ended_reason": None,
            "questions": [
                {
                    "id": "q_1", "order": 1, "persona": "kkondae", "strategy": "detail_probe",
                    "parent_id": None, "follow_up_depth": 0,
                    "text": "측정 환경이 뭐였는지 설명해봐요.",
                    "evidence": {"slides": [3], "transcript_refs": [{"ts": "04:12"}]},
                    "tts": {"status": "ready", "audio_url": "https://.../q1.mp3"},
                    "answer": {
                        "status": "ready",
                        "text": "사내 서버 A100 1대에서 3회 평균으로 측정했습니다.",
                        "audio_url": "https://.../a1.m4a",
                        "follow_up_status": "none", "error": None,
                    },
                },
                {
                    "id": "q_2", "order": 2, "persona": "egen", "strategy": "big_picture",
                    "parent_id": None, "follow_up_depth": 0,
                    "text": "경쟁 서비스 대비 차별점이 뭔가요?",
                    "evidence": {"slides": [], "transcript_refs": []},
                    "tts": {"status": "ready", "audio_url": "https://.../q2.mp3"},
                    "answer": {
                        "status": "processing", "text": None,
                        "audio_url": "https://.../a2.m4a",
                        "follow_up_status": "pending", "error": None,
                    },
                },
            ],
        }

    def test_top_level_keys_exact(self):
        keys = set(_spec_example_state().model_dump().keys())
        assert keys == {"status", "current_question_id", "ended_reason", "questions"}

    def test_question_keys_exact(self):
        q = _spec_example_state().model_dump()["questions"][0]
        assert set(q.keys()) == {
            "id", "order", "persona", "strategy", "parent_id",
            "follow_up_depth", "text", "evidence", "tts", "answer",
        }


class TestAnswerStatusStrings:
    """status는 출력 전용 str — DB enum에 없는 'pending'도 서빙되고, enum 입력도 문자열로."""

    def test_pending_via_string(self):
        a = AnswerOut(status="pending")
        assert a.model_dump()["status"] == "pending"
        # 미답변 기본값: 텍스트·오디오 없음, follow_up none, error 없음
        assert a.model_dump() == {
            "status": "pending", "text": None, "audio_url": None,
            "follow_up_status": "none", "error": None,
        }

    def test_accepts_answer_status_enum(self):
        from app.db.enums import AnswerStatus
        # 라우터가 ORM의 AnswerStatus를 그대로 넘겨도 문자열로 직렬화돼야 한다.
        assert AnswerOut(status=AnswerStatus.failed).model_dump()["status"] == "failed"

    def test_failed_error_populated(self):
        from app.schemas.session import ErrorInfo
        a = AnswerOut(status="failed", error=ErrorInfo(code="STT_FAILED", message="STT 서버 오류"))
        assert a.model_dump()["error"] == {"code": "STT_FAILED", "message": "STT 서버 오류"}


class TestQnaStatus:
    def test_values(self):
        assert QnaStatus.in_progress == "in_progress"
        assert QnaStatus.ended == "ended"

    def test_ended_reason_serializes_value(self):
        s = QnaStateOut(status=QnaStatus.ended, current_question_id=None,
                        ended_reason="count_reached", questions=[])
        d = s.model_dump()
        assert d["status"] == "ended"
        assert d["ended_reason"] == "count_reached"
        assert d["current_question_id"] is None


class TestEvidenceFormatting:
    def test_transcript_ref_shape(self):
        e = EvidenceOut(slides=[3, 7], transcript_refs=[TranscriptRefOut(ts="00:12"),
                                                        TranscriptRefOut(ts="04:12")])
        assert e.model_dump() == {
            "slides": [3, 7],
            "transcript_refs": [{"ts": "00:12"}, {"ts": "04:12"}],
        }

    def test_empty_evidence_defaults(self):
        assert EvidenceOut().model_dump() == {"slides": [], "transcript_refs": []}


class TestPassRequest:
    def test_default_reason_user(self):
        assert PassRequest().reason == "user"

    def test_timeout_reason(self):
        assert PassRequest(reason="timeout").reason == "timeout"

    def test_invalid_reason_rejected(self):
        with pytest.raises(ValidationError):
            PassRequest(reason="whatever")
