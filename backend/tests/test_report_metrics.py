"""리포트 정량 지표 회귀 테스트 (report-eval-workflow.md §A·§C).

순수 코드라 스냅샷 완전 일치로 검증한다.

실행:
    cd backend
    .venv/bin/python -m pytest tests/test_report_metrics.py -v
"""

from app.services.report import FILLER_WORDS, compute_speaking_metrics

# 음 x2, 어 x1 = 필러 3어절 / 전체 10어절 / 콘텐츠 7어절
SEGMENTS = [
    {"start": 0.0, "end": 3.0, "text": "음 안녕하세요 발표를 시작하겠습니다"},
    {"start": 3.0, "end": 6.0, "text": "어 오늘 주제는 성능 개선입니다 음"},
]


def test_wpm_excludes_fillers_by_default():
    # 60초 = 1분 → 콘텐츠 7어절 / 1분 = 7.0
    m = compute_speaking_metrics(SEGMENTS, duration_seconds=60.0, time_limit_minutes=5)
    assert m["words_per_minute"] == 7.0


def test_wpm_include_fillers_flag():
    # 전체 10어절 / 1분 = 10.0
    m = compute_speaking_metrics(
        SEGMENTS, duration_seconds=60.0, time_limit_minutes=5, exclude_fillers=False
    )
    assert m["words_per_minute"] == 10.0


def test_filler_words_sorted_desc():
    m = compute_speaking_metrics(SEGMENTS, duration_seconds=60.0, time_limit_minutes=5)
    assert m["filler_words"] == [{"word": "음", "count": 2}, {"word": "어", "count": 1}]


def test_over_time_boundary():
    # 정확히 같으면 초과 아님(> 비교)
    assert compute_speaking_metrics(SEGMENTS, 300.0, 5)["over_time"] is False
    assert compute_speaking_metrics(SEGMENTS, 301.0, 5)["over_time"] is True


def test_punctuation_stripped_before_match():
    # "음," 과 "어..." 는 부호를 벗겨 필러로 잡히고, "그"(지시어)는 기본 사전에 없음
    segs = [{"start": 0, "end": 1, "text": "음, 그 결과는 어... 좋았습니다"}]
    m = compute_speaking_metrics(segs, duration_seconds=60.0, time_limit_minutes=5)
    assert m["filler_words"] == [{"word": "어", "count": 1}, {"word": "음", "count": 1}]
    # 전체 5어절(음/그/결과는/어/좋았습니다) - 필러 2 = 콘텐츠 3 → 3.0
    assert m["words_per_minute"] == 3.0


def test_demonstratives_not_counted():
    # 지시어 그·저, 부사 좀·약간은 기본 사전 제외(오검출 방지)
    for w in ("그", "저", "뭐", "이제", "막", "좀", "약간"):
        assert w not in FILLER_WORDS


def test_empty_and_zero_duration_edge():
    assert compute_speaking_metrics([], 0.0, 5) == {
        "words_per_minute": 0.0,
        "filler_words": [],
        "over_time": False,
    }
    # 텍스트는 있으나 duration 0 → 0으로 나누지 않고 0.0
    assert compute_speaking_metrics(SEGMENTS, 0.0, 5)["words_per_minute"] == 0.0


def test_text_only_segments_work():
    # 타임스탬프 없어도 동작(text 키만)
    m = compute_speaking_metrics([{"text": "음 결론입니다"}], duration_seconds=30.0, time_limit_minutes=5)
    assert m["words_per_minute"] == 2.0  # 콘텐츠 1어절 / 0.5분
