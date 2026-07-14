"""STT 청크·병합 파이프라인 회귀 테스트 — GPU·DB 없이 순수 함수 단위로.

실행:
    cd backend
    .venv/bin/python -m pytest tests/test_stt.py -v

`transcribe_recording`의 어려운 부분(청크 분할·오프셋 합산·겹침 dedup·형태소→문장급
그룹화·표시 텍스트 정렬)은 그동안 소비 측 테스트(test_recordings.py 등)가 함수를 통째로
monkeypatch로 대체해 한 번도 실행되지 않았다. 여기서 각 헬퍼를 직접 고정한다.

핵심 불변식(TestChunkBoundaryGlue): **겹침(OVERLAP) 구간 덕분에 청크 경계를 가로지르는
붙여쓰기(glue)가 보존된다** — 각 청크가 겹침 영역을 다시 전사하므로 경계 단어의 glue는
청크 내부 문자 인접성으로 정확히 계산되고, 겹침 단어는 이후 trim으로 제거된다. 이 동작이
겹침 로직 리팩터로 조용히 깨지지 않도록 잠근다.
"""

import wave

import pytest

from app.services import stt


# ── seconds_to_ts (내림 포맷) ────────────────────────────────────────

class TestSecondsToTs:
    @pytest.mark.parametrize("seconds,expected", [
        (0.0, "00:00"),
        (59.9, "00:59"),      # 내림 — 세그먼트 시작 이전을 가리키지 않게
        (252.0, "04:12"),
        (3600.0, "60:00"),    # 60분 = "60:00" (시 단위 없음)
    ])
    def test_floor_format(self, seconds, expected):
        assert stt.seconds_to_ts(seconds) == expected


# ── _group_words (형태소 → 문장급) ───────────────────────────────────

def _w(start, end, text, *, glue=False, display=None):
    d = {"start": start, "end": end, "text": text, "glue": glue}
    if display is not None:
        d["display"] = display
    return d


class TestGroupWords:
    def test_glued_pair_joins_without_space(self):
        words = [_w(0.0, 0.4, "발표"), _w(0.5, 0.8, "를", glue=True)]
        assert [s["text"] for s in stt._group_words(words)] == ["발표를"]

    def test_non_glue_small_gap_joins_with_space(self):
        # gap 0.1s < GROUP_GAP_SEC(0.35) → 같은 세그먼트, 공백 조인
        words = [_w(0.0, 0.4, "안녕"), _w(0.5, 0.9, "하세요")]
        assert [s["text"] for s in stt._group_words(words)] == ["안녕 하세요"]

    def test_pause_gap_splits_segment(self):
        # gap 0.4s >= GROUP_GAP_SEC(0.35) → 문장 경계로 분할
        words = [_w(0.0, 0.4, "끝"), _w(0.8, 1.2, "새문장")]
        assert [s["text"] for s in stt._group_words(words)] == ["끝", "새문장"]

    def test_too_long_forces_split_without_pause(self):
        # 쉼 없이 이어져도 GROUP_MAX_SEC(15) 초과 시 강제 분할
        words = [_w(0.0, 0.4, "가"), _w(0.5, 16.0, "나")]
        assert len(stt._group_words(words)) == 2

    def test_glue_true_never_splits_even_past_max(self):
        # glue=True는 분할 가드 자체를 건너뛴다
        words = [_w(0.0, 0.4, "가"), _w(0.5, 16.0, "나", glue=True)]
        assert [s["text"] for s in stt._group_words(words)] == ["가나"]

    def test_prefers_display_over_raw_text(self):
        words = [_w(0.0, 0.4, "발표", display="발표"),
                 _w(0.5, 0.8, "를", glue=True, display="를.")]
        assert [s["text"] for s in stt._group_words(words)] == ["발표를."]


# ── _attach_display_text (punctuated 정렬 + glue/구두점) ──────────────

class TestAttachDisplayText:
    def test_recovers_spacing_and_glue(self):
        stamps = [{"start": 0, "end": 1, "text": "발표"},
                  {"start": 1, "end": 2, "text": "를"},
                  {"start": 2, "end": 3, "text": "했습니다"}]
        out = stt._attach_display_text(stamps, "발표를 했습니다")
        assert [w["glue"] for w in out] == [False, True, False]
        assert [w["display"] for w in out] == ["발표", "를", "했습니다"]

    def test_trailing_punctuation_attaches_to_word(self):
        stamps = [{"start": 0, "end": 1, "text": "발표"},
                  {"start": 1, "end": 2, "text": "를"}]
        out = stt._attach_display_text(stamps, "발표를.")
        assert out[-1]["display"] == "를."

    def test_misalignment_falls_back_to_space_join(self):
        # 스탬프가 텍스트와 어긋나면 해당 청크 나머지는 원문·비붙임으로 강등
        stamps = [{"start": 0, "end": 1, "text": "가나"},
                  {"start": 1, "end": 2, "text": "다라"}]
        out = stt._attach_display_text(stamps, "가나마바")  # 다라 매칭 실패
        assert out[0]["display"] == "가나"
        assert out[1]["display"] == "다라" and out[1]["glue"] is False


# ── _shift_and_trim (오프셋 + 중점 dedup) ────────────────────────────

class TestShiftAndTrim:
    def test_single_chunk_keeps_all_and_shifts(self):
        segs = [{"start": 1.0, "end": 2.0, "text": "x"}]
        out = stt._shift_and_trim(segs, offset=10.0, is_first=True, is_last=True)
        assert out == [{"start": 11.0, "end": 12.0, "text": "x"}]

    def test_boundary_word_goes_to_later_chunk_only(self):
        # OVERLAP=4 → half=2. cut = offset0 + CHUNK_SEC + 2 = lo of 다음 청크.
        cut = stt.CHUNK_SEC + stt.OVERLAP_SEC / 2   # 62 (기본값 기준)
        # 중점이 정확히 cut인 단어 (abs start=cut-0.1, end=cut+0.1)
        word = {"start": cut - 0.1, "end": cut + 0.1, "text": "b"}

        earlier = stt._shift_and_trim([dict(word)], offset=0.0,
                                      is_first=True, is_last=False)   # hi=cut
        later = stt._shift_and_trim([dict(word)], offset=float(stt.CHUNK_SEC),
                                    is_first=False, is_last=True)     # lo=cut
        assert earlier == []          # 앞 청크는 버림 (mid == cut, [lo,hi) 반개구간)
        assert len(later) == 1        # 뒤 청크만 채택 — 중복/탈락 없음


# ── _split_wav (청크 오프셋) ─────────────────────────────────────────

def _make_wav(path, seconds, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


class TestSplitWav:
    def test_short_audio_single_chunk_no_split(self, tmp_path, monkeypatch):
        monkeypatch.setattr(stt, "CHUNK_SEC", 2)
        monkeypatch.setattr(stt, "OVERLAP_SEC", 1)
        wav = tmp_path / "short.wav"
        _make_wav(wav, seconds=2)                  # <= (2+1)s → 단일 청크
        chunks = stt._split_wav(wav, tmp_path)
        assert len(chunks) == 1
        assert chunks[0][0] == 0.0

    def test_long_audio_stride_spaced_offsets(self, tmp_path, monkeypatch):
        monkeypatch.setattr(stt, "CHUNK_SEC", 2)
        monkeypatch.setattr(stt, "OVERLAP_SEC", 1)
        wav = tmp_path / "long.wav"
        _make_wav(wav, seconds=5)                  # 5s → stride 2s
        offsets = [off for off, _ in stt._split_wav(wav, tmp_path)]
        assert offsets == [0.0, 2.0]               # 꼬리 잔여 <overlap는 청크 생략


# ── 청크 경계 glue 보존 (핵심 불변식) ────────────────────────────────

class TestChunkBoundaryGlue:
    """겹침 재전사 + 청크별 punctuated 정렬이 경계 붙여쓰기를 보존하는지.

    실제 병합 경로(_attach_display_text → _shift_and_trim → sort → _group_words)를
    두 청크로 재현한다. CHUNK_SEC/OVERLAP_SEC 기본값(60/4) 기준 cut=62s.
    """

    def _merge(self, c0, c1):
        words = c0 + c1
        words.sort(key=lambda w: (w["start"], w["end"]))
        return " | ".join(s["text"] for s in stt._group_words(words))

    def test_glued_pair_across_boundary_stays_glued(self):
        # "발표"(chunk0 tail) + "를"(chunk1 first surviving) — 붙여쓰기 유지
        c0 = stt._shift_and_trim(
            stt._attach_display_text([{"start": 61.5, "end": 61.9, "text": "발표"}], "발표"),
            offset=0.0, is_first=True, is_last=False)
        # chunk1은 겹침으로 "발표"를 다시 듣고(trim됨) "를 했습니다"를 남긴다
        c1 = stt._shift_and_trim(
            stt._attach_display_text([
                {"start": 1.5, "end": 1.9, "text": "발표"},     # abs 61.7 mid → trim
                {"start": 2.0, "end": 2.3, "text": "를"},       # abs 62.15 mid → 첫 생존
                {"start": 2.5, "end": 3.0, "text": "했습니다"},
            ], "발표를 했습니다"),
            offset=60.0, is_first=False, is_last=True)
        assert self._merge(c0, c1) == "발표를 했습니다"      # 스퍼리어스 공백 없음

    def test_separate_eojeols_across_boundary_keep_space(self):
        # "했다" + "그리고" — 짧은 시간 간격이어도 원문 공백은 보존돼야 한다
        # (시간-간격 휴리스틱으로 붙이면 여기서 깨진다 — 문자 정렬이 정답)
        c0 = stt._shift_and_trim(
            stt._attach_display_text([{"start": 61.5, "end": 61.9, "text": "했다"}], "했다"),
            offset=0.0, is_first=True, is_last=False)
        c1 = stt._shift_and_trim(
            stt._attach_display_text([
                {"start": 1.5, "end": 1.9, "text": "했다"},     # abs 61.7 → trim
                {"start": 2.0, "end": 2.3, "text": "그리고"},    # abs 62.15 → 첫 생존
            ], "했다 그리고"),
            offset=60.0, is_first=False, is_last=True)
        assert self._merge(c0, c1) == "했다 그리고"          # 간격 0.1s여도 공백 유지
