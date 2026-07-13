"""리포트 통합 회귀 — 고정 샘플 세션 1개로 A(정량) + B(정성)를 함께 검증 (report-eval-workflow.md §C).

- 정량(A): 순수 코드라 스냅샷 **완전 일치**.
- 정성(B): mock은 결정론이라 완전 일치. 실제 프로바이더용 검증은 구조/범위 체크로 문서화
  (키 ⊆ 등장 전략, 값 ∈ [0,1], insight 비어있지 않음) — 프롬프트 수정 시 이 계약이 회귀 가드.

실행:
    cd backend
    .venv/bin/python -m pytest tests/test_report_fixture.py -v
"""

import asyncio
import json
from pathlib import Path

from app.db.enums import QuestionStrategy
from app.services.llm.mock_provider import MockLLMProvider
from app.services.report import compute_speaking_metrics

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "report_sample_session.json").read_text(encoding="utf-8")
)


def test_quantitative_metrics_snapshot():
    m = compute_speaking_metrics(
        FIXTURE["transcript"], FIXTURE["duration_seconds"], FIXTURE["time_limit_minutes"]
    )
    # 39 어절 − 필러 4(음2·어2) = 콘텐츠 35 → 35 / (25/60) = 84.0
    assert m == {
        "words_per_minute": 84.0,
        "filler_words": [{"word": "어", "count": 2}, {"word": "음", "count": 2}],
        "over_time": False,
    }


def test_mock_report_snapshot():
    draft = asyncio.run(
        MockLLMProvider().generate_report(answers=FIXTURE["qna"], speech_name=FIXTURE["speech_name"])
    )
    # mock 점수 = round(min(0.9, 0.3 + 답변길이/200), 2), 전략별 1건씩이라 평균=자기 값
    assert {k.value: v for k, v in draft.type_scores.items()} == {
        "basic_concept": 0.51,
        "detail_probe": 0.52,
        "numeric_verification": 0.51,
        "big_picture": 0.56,
    }
    assert draft.insight.strip()


def test_qualitative_structure_contract():
    """실제 프로바이더에도 적용되는 구조/범위 계약(값은 프로바이더마다 달라도 이건 불변)."""
    draft = asyncio.run(MockLLMProvider().generate_report(answers=FIXTURE["qna"]))
    present = {QuestionStrategy(a["strategy"]) for a in FIXTURE["qna"]}
    assert set(draft.type_scores) <= present            # 등장한 전략만
    assert all(0.0 <= v <= 1.0 for v in draft.type_scores.values())  # DDL CHECK 범위
    assert isinstance(draft.insight, str) and draft.insight.strip()
