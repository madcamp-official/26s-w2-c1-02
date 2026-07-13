# 리포트·평가 미니 워크플로우 — 정량 지표 + LLM 채점

> [workflow.md](../workflow.md) Step 4 팀원3 항목 "정량 지표 / 리포트 LLM / 회귀 테스트 고정 입력"의 세부 계획.
> 작성일: 2026-07-13 · 담당: 팀원3
> 계약: [api-spec.md](../api-spec.md) §5.2 · [db-schema.md](../db-schema.md) §3.6·§6.4·§8.1 · enums [db/enums.py](../../backend/app/db/enums.py)

## 핵심 원칙 — 숫자는 코드, 판단은 LLM

리포트는 **두 반쪽**이 합쳐진 것이다. 섞으면 안 된다.

| 반쪽 | 담당 로직 | 산출 | 근거 |
|---|---|---|---|
| **A. 정량 지표** | 순수 파이썬(결정론적) | `words_per_minute`, `filler_words[]`, `over_time` | 재현 가능·검증 가능해야 하므로 **LLM에 숫자 계산을 시키지 않는다** (Step 4 명시) |
| **B. 정성 평가** | 외부 LLM (1콜) | `type_scores`(전략별 0~1), `insight` | 답변 품질은 채점 판단이라 LLM 몫 |

경계 규칙(Step 0)대로 팀원3은 **서비스 모듈만** 제공하고, 저장·상태전이·응답 조립은
팀원2의 `POST /report/generate` 잡이 한다. 아래 산출물은 전부 `services/`의 순수 함수/프로바이더 메서드다.

---

## A. 정량 지표 — 순수 코드 (`services/report.py`)

> ✅ **구현됨(2026-07-13):** `compute_speaking_metrics()` + 필러 사전 `FILLER_WORDS`.
> 회귀 스냅샷 8케이스 통과([tests/test_report_metrics.py](../../backend/tests/test_report_metrics.py)).
> WPM은 **필러 제외가 기본**(`exclude_fillers=True`, 팀 결정) — 아래 열린 질문 1 참고.

### 입력
- **transcript**: `transcripts.segments` = `[{start, end, text}]` — **타임스탬프 포함 원본**
  (질문 생성에 넘긴 텍스트-온리 버전이 아니라 이쪽. 팀 합의: 시간 근거는 리포트에서만 사용)
- **recording.duration_seconds**, **session.time_limit_minutes** — WPM 분모·over_time 판정용

### 산출 (함수 3개, 전부 동기·부작용 없음)

```
compute_speaking_metrics(segments, duration_seconds, time_limit_minutes)
  -> { words_per_minute: float, filler_words: [{word, count}], over_time: bool }
```

1. **WPM** = 전체 단어 수 ÷ (발화시간/60). 발화시간은 `duration_seconds`(권위) 사용.
   - **v0.3 기준: 원문(raw) transcript로 집계.** 정제 패스가 없어 간투사가 그대로 남으므로
     WPM이 소폭 높게 나올 수 있다(api-spec §5.2). → 열린 질문 1.
2. **filler_words** = 간투사 사전(`음/어/그/저/뭐/이제/약간 …`) 카운트. **원문 기준이라 검출 정확도 ↑.**
   - 한국어 토크나이즈 주의: 공백 분리로는 "음," "어…" 등을 놓친다 → 정규식/형태 정규화 필요.
   - 사전은 상수로 노출해 회귀 테스트가 고정값을 검증하게 한다.
3. **over_time** = `actual_seconds > time_limit_seconds`. 사실상 1줄 파생.

> **저장 안 하는 값 주의(db-schema §3.6):** `time_limit_seconds`·`actual_seconds`·`over_time`·
> `filler_word_count`(합계)는 `reports`에 **컬럼이 없다**. sessions·recordings에서 파생되고
> FE/BE가 응답 조립 시 계산한다. 팀원3이 DB에 넣는 정량값은 `words_per_minute`·`filler_words`뿐.
> `over_time`은 함수가 편의로 돌려주되 저장은 팀원2 판단.

---

## B. 정성 평가 — 리포트 LLM (`services/llm/` 확장, 1콜)

`LLMProvider`에 세 번째 메서드를 추가한다(현재 `generate_questions`·`follow_up` 2개).

```
generate_report(*, answers, slides, transcript_text) -> ReportDraft
  ReportDraft = { type_scores: {QuestionStrategy: float 0~1}, insight: str }
```

### 입력 (Q&A 로그)
- **answers**: 질문별 `{strategy, question_text, answer_text(raw STT), evidence}` 목록.
  - `strategy`가 채점 축이다 — 질문 생성 때 반드시 채워둔 값(qna-workflow 격차 5)을 여기서 회수.
  - `answer_text`는 **raw STT**(간투사·비문 포함) — 프롬프트가 노이즈를 견디게 지시.
- slides·transcript(텍스트)는 답변이 근거에 부합하는지 대조용(선택).

### 산출
1. **type_scores**: `QuestionStrategy` 4종(`detail_probe·big_picture·basic_concept·numeric_verification`)
   각각 0.0~1.0. 한 전략에 질문이 여러 개면 **평균**으로 집계. 해당 전략 질문이 0개면 그 키는 생략.
   - → `report_type_scores`(정규화 테이블, PK `(session_id, strategy)`)로 저장(팀원2).
   - **`answer_quality`(strong/weak_types)는 저장하지 않는다** — 임계값 분류로 응답 시 파생(api-spec §5.2).
2. **insight**: 세션 1개용 한국어 코칭 한두 문장(예: "필러가 도입부에 몰려 있어요…").
   - **숫자를 지어내지 말 것** — WPM/filler 수치는 A의 결과를 프롬프트에 넣어 인용만 시키거나,
     아예 정성 코멘트만 시키고 수치는 A에서 붙인다(권장: LLM에 계산 금지).

### 채점 루브릭 (프롬프트에 고정)
- 각 전략이 "무엇을 잘한 답변인가"를 명시(detail=구체 근거, numeric=수치 검증, big_picture=맥락 연결, basic=개념 정확성).
- JSON 스키마 강제(질문 생성과 동일 방식) + 후처리 검증: 키가 QuestionStrategy인지, 값이 [0,1]인지.
- gemini prompt-caching 재사용(꼬리질문 C단계와 동일) — 루브릭·시스템 프롬프트는 캐시 대상.

---

## C. 회귀 테스트 — 고정 입력 1세트

프롬프트를 만지면 채점이 흔들린다. **샘플 세션 1개**(slides + transcript + Q&A 로그)를 픽스처로 박제한다.

- `tests/fixtures/report_sample_session.json` — 결정론 입력.
- **정량(A)**: 스냅샷 **완전 일치** 검증(순수 코드라 값이 고정). WPM·filler 사전 카운트까지.
- **정성(B)**: 외부 LLM이라 값이 흔들리므로 **범위/구조 검증**(키 집합 = 등장 전략, 값 ∈ [0,1],
  insight 비어있지 않음). Mock 프로바이더로는 완전 일치, 실제 프로바이더로는 스키마·범위만.
- mock_provider에도 `generate_report` 결정론 구현을 추가해 오프라인 CI가 돌게 한다.

---

## 현재 구현과의 격차 (overlay)

리포트 계층은 **아직 존재하지 않는다.** 착수 전 아래를 먼저 세운다.

| # | 격차 | 현재 | 필요 |
|---|---|---|---|
| 1 | **정량 서비스 없음** | `services/report.py` 미존재 | `compute_speaking_metrics(...)` 순수 함수 |
| 2 | **LLM 리포트 메서드 없음** | `LLMProvider`에 2개 메서드뿐 | `generate_report(...)` 추가(base·gemini·mock 3곳) |
| 3 | **ReportDraft 스키마 없음** | `schemas/`에 report 없음 | `ReportDraft{type_scores, insight}` + 검증기 |
| 4 | **회귀 픽스처 없음** | 없음 | 고정 세션 JSON + 스냅샷 테스트 |
| 5 | **필러 사전 미정** | 없음 | 한국어 간투사 사전 상수(팀 리뷰 1회) |

---

## 경계 (팀원3 ↔ 팀원2)

- **팀원3 제공**: `compute_speaking_metrics()`, `LLMProvider.generate_report()`, `ReportDraft`, 필러 사전, 픽스처/테스트.
- **팀원2 조립**: `POST /report/generate` 잡에서 두 서비스 호출 →
  `reports`(wpm·filler·insight, status 전이) + `report_type_scores`(전략별) 저장 →
  `GET /report`가 `answer_quality`·`over_time`·`filler_word_count` 파생(§5.2) →
  `GET /users/me/report/growth`는 `report_type_scores` **SQL 한 방**(§8.1, 팀원3 무관).
- 자동 생성 트리거: `qna/end` 시 리포트 잡 자동 큐(A7) — 팀원2 몫.

## 평가 방법 (어떻게 검증하나)

1. **오프라인**: 픽스처로 A=스냅샷 일치, B=스키마/범위(mock 완전 일치).
2. **라이브 1콜**: 실제 세션 1개로 `generate_report` 실측 — type_scores 4키 합리성·insight 한국어 품질 육안 검수.
3. **결정론 회귀**: 프롬프트 수정 전후 mock 스냅샷 diff = 0 확인(정성 회귀 가드).
4. **통합(전원 데이)**: 실제 PDF→발표→Q&A→리포트까지 논스톱 1회에서 리포트가 `ready`로 뜨는지(Step 4 통합).

## 열린 질문

1. ~~**WPM에서 필러 제외?**~~ → **결정(2026-07-13): 제외**(`exclude_fillers=True` 기본). 필러는
   별도 축이라 이중 계산을 피하고 WPM을 "콘텐츠 발화 속도"로 둔다. 같은 사전(`FILLER_WORDS`)이
   제외·카운트 단일 진실원. `False`로 원문 포함 전환 가능. ✅ 문서 정합 완료: db-schema §3.6 주석·
   §9 항목, api-spec §5.2 노트 모두 "콘텐츠 기준(간투사 제외)"으로 갱신.
2. **성장 리포트 insight**(§5.2 growth 응답의 `insight`)를 누가 만드나 — 세션 insight와 별개(회차 비교).
   LLM 재사용(type_scores 시계열 입력) vs 템플릿. **스트레치**로 두고 세션 insight 먼저.
3. **필러 사전 범위** — 지역·말투 편차. 최소 셋으로 시작하고 실측 로그로 확장.
