"""transcripts.segments JSONB 저장 왕복 + ts 변환 검증 (workflow Step 2 팀원3, stt-client-workflow 7단계).

실행:
    cd backend
    python -m pytest tests/test_transcript_roundtrip.py -v

두 계약을 검증한다:
1. transcribe_recording() 출력 형태의 segments가 JSONB에 저장 후 **그대로**
   돌아오는지 (float 유지, 소수 3자리 정밀도, 한국어 텍스트, 키 보존) — db-schema §6.2
2. start(초 float) → ts:"MM:SS" 변환 (seconds_to_ts) — api-spec §4.3.
   팀원2 라우터는 이 함수를 import해서 쓰면 된다.

GPU 서버 불필요 — segments는 실측(2026-07-11 E2E, 2.7분 발표) 출력을 고정한 것.
"""

import pytest
from sqlalchemy import delete, select

from app.db.enums import QuestionerPersona
from app.db.models import RehearsalSession, Team, Transcript, User
from app.db.session import SessionLocal
from app.services.stt import seconds_to_ts

# transcribe_recording() 실측 출력 형태 고정본: 초 단위 float(소수 ≤3자리),
# 문장급 텍스트(ASR 원문 — 간투사 포함), 60s 청크 경계(1분) 이후 세그먼트 포함
FROZEN_SEGMENTS = [
    {"start": 0.0, "end": 3.44, "text": "안녕하세요, 어… 오늘 발표를 맡은 박준서입니다."},
    {"start": 3.86, "end": 9.12, "text": "저희 팀은 발표 리허설 서비스 리허설 아이오를 만들었습니다."},
    {"start": 58.375, "end": 63.9, "text": "청크 경계에 걸친 문장도 중복 없이 한 번만 나옵니다."},
    {"start": 71.9, "end": 75.0, "text": "성능은 기존 대비 30배 개선되었습니다."},
    {"start": 161.483, "end": 164.02, "text": "이상으로 발표를 마치겠습니다. 감사합니다."},
]


class TestSecondsToTs:
    """api-spec §4.3: ts는 MM:SS, 내림(반올림 아님), 60분 상한."""

    @pytest.mark.parametrize(("seconds", "expected"), [
        (0.0, "00:00"),        # 제로패딩
        (12.0, "00:12"),       # spec 예시
        (71.9, "01:11"),       # 내림 — 반올림이면 01:12로 어긋남
        (252.0, "04:12"),      # spec 예시
        (3599.5, "59:59"),     # 상한 직전
        (3600.0, "60:00"),     # 60분 녹음 최대 — 시간 단위로 넘어가지 않음
    ])
    def test_format(self, seconds, expected):
        assert seconds_to_ts(seconds) == expected

    def test_frozen_segments_all_convertible(self):
        for seg in FROZEN_SEGMENTS:
            ts = seconds_to_ts(seg["start"])
            assert len(ts) == 5 and ts[2] == ":"


def _purge_sttrt() -> None:
    """sttrt 유저와 그가 리더인 팀 정리 (세션·전사는 팀 CASCADE로 함께 삭제)."""
    with SessionLocal() as db:
        team_ids = db.scalars(select(Team.id).join(
            User, User.id == Team.leader_id).where(User.username == "sttrt_owner")).all()
        for tid in team_ids:
            db.delete(db.get(Team, tid))
        db.commit()
        db.execute(delete(User).where(User.username == "sttrt_owner"))
        db.commit()


@pytest.fixture()
def session_id():
    """User → Team → RehearsalSession 최소 체인 (Transcript의 FK 사슬)."""
    _purge_sttrt()
    with SessionLocal() as db:
        user = User(username="sttrt_owner", name="전사테스트")
        db.add(user)
        db.flush()
        team = Team(name="전사왕복팀", leader_id=user.id)
        db.add(team)
        db.flush()
        ses = RehearsalSession(
            team_id=team.id, owner_id=user.id, name="JSONB 왕복 세션",
            personas=[QuestionerPersona.teto], question_count=3, time_limit_minutes=10,
        )
        db.add(ses)
        db.commit()
        sid = ses.id
    yield sid
    _purge_sttrt()


class TestSegmentsJsonbRoundtrip:
    def test_roundtrip_exact(self, session_id):
        with SessionLocal() as db:
            db.add(Transcript(session_id=session_id, segments=FROZEN_SEGMENTS))
            db.commit()

        # 새 DB 세션에서 재조회 — identity map이 아니라 Postgres가 저장한 값을 읽는다
        with SessionLocal() as db:
            loaded = db.get(Transcript, session_id).segments

        assert loaded == FROZEN_SEGMENTS

        for seg in loaded:
            # db-schema §6.2 계약: 키는 정확히 start/end/text
            assert set(seg) == {"start", "end", "text"}
            # JSONB 숫자가 Decimal/str로 돌아오면 라우터의 ts 변환·비교가 깨진다
            assert type(seg["start"]) is float and type(seg["end"]) is float
            assert isinstance(seg["text"], str)
            assert seg["start"] <= seg["end"]

    def test_roundtrip_empty_segments(self, session_id):
        """무음 녹음: segments=[]도 정상 저장·조회 (stt-client-workflow 엣지케이스)."""
        with SessionLocal() as db:
            db.add(Transcript(session_id=session_id, segments=[]))
            db.commit()
        with SessionLocal() as db:
            assert db.get(Transcript, session_id).segments == []
