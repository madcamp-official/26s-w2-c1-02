"""리포트 정성 평가(LLM) 회귀 테스트 — mock 결정론 + 집계/클램프 (report-eval-workflow.md §B·§C).

실제 LLM은 값이 흔들리므로 gemini 경로는 여기서 검증하지 않는다(라이브 육안 검수 몫).
mock 제공자는 결정론이라 스냅샷 일치로 검증한다.

실행:
    cd backend
    .venv/bin/python -m pytest tests/test_report_llm.py -v
"""

import asyncio

from app.db.enums import QuestionStrategy
from app.schemas.report import ReportDraft
from app.services.llm.base import build_type_scores
from app.services.llm.mock_provider import MockLLMProvider

DP = QuestionStrategy.detail_probe
BP = QuestionStrategy.big_picture


def _run(coro):
    return asyncio.run(coro)


def test_mock_report_deterministic_snapshot():
    # _mock_score = round(min(0.9, 0.3 + len/200), 2): len100→0.8, len20→0.4, len200→0.9
    answers = [
        {"strategy": "detail_probe", "question": "q1", "answer": "a" * 100},
        {"strategy": "detail_probe", "question": "q2", "answer": "a" * 20},
        {"strategy": "big_picture", "question": "q3", "answer": "a" * 200},
    ]
    draft = _run(MockLLMProvider().generate_report(answers=answers))
    # detail_probe = avg(0.8, 0.4) = 0.6 (코드 집계), big_picture = 0.9
    assert draft.type_scores == {DP: 0.6, BP: 0.9}
    assert draft.insight  # 비어있지 않음


def test_mock_report_no_answers():
    draft = _run(MockLLMProvider().generate_report(answers=[]))
    assert draft.type_scores == {}
    assert "없습니다" in draft.insight


def test_mock_report_skips_empty_and_invalid():
    answers = [
        {"strategy": "detail_probe", "question": "q", "answer": "   "},   # 공백 → 스킵
        {"strategy": "bogus", "question": "q", "answer": "내용 있음"},      # 전략 무효 → 스킵
        {"strategy": "big_picture", "question": "q", "answer": "a" * 200}, # 유효 → 0.9
    ]
    draft = _run(MockLLMProvider().generate_report(answers=answers))
    assert draft.type_scores == {BP: 0.9}


def test_build_type_scores_averages_and_skips():
    scores = build_type_scores([(DP, 0.4), (DP, 0.6), (BP, 1.0)])
    assert scores == {DP: 0.5, BP: 1.0}
    assert build_type_scores([]) == {}


def test_build_type_scores_clamps_out_of_range():
    # 범위 밖 입력은 [0,1]로 잘라 평균 (DDL CHECK 방어)
    assert build_type_scores([(DP, 1.5), (DP, -0.5)]) == {DP: 0.5}


def test_report_draft_clamps_scores():
    d = ReportDraft(type_scores={"detail_probe": 1.5, "big_picture": -0.2}, insight="x")
    assert d.type_scores == {DP: 1.0, BP: 0.0}
