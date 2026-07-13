"""리포트 정량 지표 — 순수 코드(결정론).

발표 습관 지표(WPM·필러·over_time)를 **원문 transcript**에서 계산한다.
LLM에 숫자 계산을 시키지 않는다(workflow Step 4 원칙: 숫자는 코드, 판단은 LLM).
정성 평가(type_scores·insight)는 별도 — services/llm/ (report-eval-workflow.md B).

팀원2의 리포트 생성 잡(POST /sessions/{id}/report/generate)에서 호출:

    from app.services.report import compute_speaking_metrics

    m = compute_speaking_metrics(segments, duration_seconds, time_limit_minutes)
    # → reports.words_per_minute = m["words_per_minute"]
    #   reports.filler_words     = m["filler_words"]
    # over_time·filler_word_count(합계)는 응답 조립 시 파생 — 저장 컬럼 없음(db-schema §3.6)

동기·부작용 없는 순수 함수. 같은 입력이면 항상 같은 출력(회귀 스냅샷 대상).
세부 계약: docs/ai-pipeline/report-eval-workflow.md §A
"""

from __future__ import annotations

# ── 한국어 필러(간투사) 사전 ────────────────────────────────────────────────
#
# WPM 제외와 filler_words 카운트가 **같은 사전**을 쓴다(단일 진실원).
# 원문(raw) transcript 기준이라 간투사가 그대로 남아 검출된다(api-spec §5.2).
#
# ⚠️ 보수적 기본값: 발성 망설임(음/어/으/흠 …)만 넣는다. 지시어·부사와 겹치는
# 그·저·뭐·이제·막·좀·약간은 **의도적으로 제외** — 단독 어절이어도 "그 사람"의
# '그'까지 필러로 세면 대량 오검출된다. 팀 리뷰 후 확장은 열린 질문 3
# (report-eval-workflow.md). FILLER_WORDS에 토큰만 추가하면 WPM·카운트에 동시 반영.
FILLER_WORDS: frozenset[str] = frozenset(
    {
        "음", "으음", "음음", "흠", "흠흠",   # 비음 망설임
        "어", "어어", "어어어",               # 모음 연장 망설임
        "으", "으으", "으어",
        "에", "에에",
        "그니까", "그러니까",                 # 담화표지(연결어와 혼동 가능하나 통상 군말)
        "뭐랄까",
    }
)

# 어절 앞뒤에서 벗겨낼 문장부호·기호(내부는 보존: "3.5%"는 한 어절로 카운트)
_STRIP = " \t\r\n.,!?…·;:\"'`()[]{}«»<>~-–—%"


def compute_speaking_metrics(
    segments: list[dict],
    duration_seconds: float,
    time_limit_minutes: float | int,
    *,
    exclude_fillers: bool = True,
) -> dict:
    """발표 습관 정량 지표를 계산한다.

    Args:
        segments: 원문 전사 `[{"start","end","text"}]` (transcripts.segments).
            타임스탬프 없이 text만 있어도 동작한다.
        duration_seconds: 녹음 길이(WPM 분모의 권위값 = recordings.duration_seconds).
        time_limit_minutes: 세션 제한시간(over_time 판정 = sessions.time_limit_minutes).
        exclude_fillers: True(기본)면 WPM에서 필러 어절을 제외해 **콘텐츠 발화 속도**로
            측정한다. filler_words는 별도 축이므로 이중 계산을 피한다(팀 결정 2026-07-13).
            False면 원문 전체 어절 기준(간투사 포함).

    Returns:
        {
          "words_per_minute": float,               # 소수 1자리
          "filler_words": [{"word": str, "count": int}],  # count 내림차순, 동수는 word 오름차순
          "over_time": bool,                       # actual > limit
        }
    """
    counts: dict[str, int] = {}
    total_words = 0
    filler_total = 0

    for seg in segments:
        for token in _tokens(seg.get("text", "")):
            total_words += 1
            if token in FILLER_WORDS:
                counts[token] = counts.get(token, 0) + 1
                filler_total += 1

    content_words = total_words - filler_total if exclude_fillers else total_words
    minutes = duration_seconds / 60.0
    wpm = round(content_words / minutes, 1) if minutes > 0 else 0.0

    # count 내림차순, 동수는 word 오름차순 — 스냅샷 안정성
    filler_words = [
        {"word": w, "count": c}
        for w, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    over_time = duration_seconds > time_limit_minutes * 60

    return {"words_per_minute": wpm, "filler_words": filler_words, "over_time": over_time}


def _tokens(text: str) -> list[str]:
    """어절 토큰화 — 공백 분리 후 앞뒤 문장부호 제거. 빈 토큰은 버린다."""
    out: list[str] = []
    for raw in text.split():
        token = raw.strip(_STRIP)
        if token:
            out.append(token)
    return out
