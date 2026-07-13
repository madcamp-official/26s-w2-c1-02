# Q&A 프롬프트 미니 워크플로우 — 질문 생성 + 꼬리질문

> [workflow.md](../workflow.md) Step 3 팀원3 항목 "질문 생성 프롬프트 / 꼬리질문 프롬프트"의 세부 계획.
> 작성일: 2026-07-13 · 담당: 팀원3
> 계약: [api-spec.md](../api-spec.md) §4.4 · [db-schema.md](../db-schema.md) §6.1·§6.3 · enums [db/enums.py](../../backend/app/db/enums.py)

## 계약 (입출력)

두 함수 모두 `services/llm/` 의 `LLMProvider` 뒤에 있고, 팀원2의 `POST /qna/generate`·
`POST .../answer` 잡에서 호출한다. 라우터가 결과를 `questions` 테이블에 적재하므로
**출력은 questions 컬럼과 1:1로 매핑되어야 한다** (id·order_index·tts는 팀원2 몫).

### 1. 질문 생성 — `generate_questions(...) -> list[QuestionDraft]`

- **입력**: 발표 제목 · **slides**(`materials.slides` = `[{page,text}]`) · **transcript**
  (`transcripts.segments`의 **텍스트만** — 타임스탬프 제외, 아래 팀 합의) · **세션 선택 personas**(≥1, 5종) · 질문 수
- **출력**: 질문 초안 목록. 각 초안 =
  ```
  { text, persona, strategy, evidence: { slides: [int], transcript_refs: [] } }
  ```
  - `persona` ∈ 세션이 고른 personas (egen·teto·kkondae·mungcheong·jammin) — 질문마다 하나씩 배정, 선택 목록을 고르게 순환
  - `strategy` ∈ QuestionStrategy (detail_probe·big_picture·basic_concept·numeric_verification) — 리포트 `type_scores` 집계 축이므로 **반드시 채운다**
  - `evidence.slides` = 근거 슬라이드 `page` 번호(슬라이드는 `[p{page}]`로 라벨링해 LLM이 되짚음)
  - `evidence.transcript_refs`는 **생성 단계에서 비운다(`[]`)** — 외부 LLM에 타임스탬프를 주지 않으므로 시간 근거를 만들 수 없다(아래 팀 합의)
- **팀 합의(2026-07-13)**: 외부 LLM 제공자에 보내는 transcript는 **텍스트만**(타임스탬프 없음). 타임스탬프 포함 원본은
  `transcripts.segments`에 저장돼 **리포트 분석**(WPM·필러·구간 참조)에서 쓰인다. → 질문 evidence의 `transcript_refs`는
  이 계약상 생성 시점에 채우지 않는다(필요해지면 LLM 인용문↔세그먼트 매핑으로 사후 부여, 후속 논의).
- **타게팅(핵심)**: slides와 transcript(텍스트)를 **대조**해
  ① 슬라이드에 있으나 발표에서 **말하지 않은** 지점, ② 말했으나 **근거·수치가 약한** 주장을 우선 겨냥.
  → 두 입력을 모두 받아야 성립한다(아래 격차 1).

### 2. 꼬리질문 — `follow_up(...) -> QuestionDraft | None`

- **입력**: 원 질문 · 발표자 답변(**raw STT** — 간투사·비문 포함) · 현재 질문의 `follow_up_depth`
- **출력**: 꼬리질문 초안 1개(부모의 persona 유지, 자체 strategy·evidence) **또는 None**
  - **깊이 1 제한(A11)**: 부모가 이미 꼬리질문(depth 1)이면 무조건 None. 1차 질문(depth 0)에만 depth 1 자식 1개.
  - "생성 안 함" 판정: 답변이 충분히 구체적이면 None (억지 꼬리질문 금지)

## 현재 구현과의 격차 (overlay)

`services/llm/gemini_provider.py`·`mock_provider.py`·`base.py`·`schemas/qna.py`는 Step 1
"헬로월드" 수준이라 §4.4 계약과 **구조적으로 어긋난다.** 프롬프트를 손대기 전에 먼저 맞춰야 한다.

| # | 격차 | 현재 | 필요 | 영향 |
|---|---|---|---|---|
| 1 | **transcript 입력 없음** | `generate_questions`는 `material_text`(slides)만 받음 | slides + **transcript** 둘 다 | 타게팅(①②)이 transcript 없이는 불가 — 최우선 |
| 2 | **출력 스키마 빈약** | `QnaItem{index, question}` — 텍스트뿐 | `persona·strategy·evidence` 포함 초안 | questions 테이블 컬럼 대부분이 비어 저장 불가 |
| 3 | **evidence 미생성** | 없음 | `{slides:[page], transcript_refs:[]}` (슬라이드 근거만; transcript_refs는 팀 합의로 생성 시점 비움) | 근거 배지(FE)·리포트 근거 추적 불가 |
| 4 | **persona 불일치** | `AudienceType`(4종: teto·egen·kkondae·etc) 1개를 전체에 적용 | `QuestionerPersona`(5종) 질문별 배정 | mungcheong·jammin 누락, 질문별 persona 없음 |
| 5 | **strategy 없음** | 없음 | 질문마다 QuestionStrategy 1개 | 리포트 `type_scores`(§5.2) 집계축 소실 |
| 6 | **꼬리 깊이 상수 오류** | `_MAX_FOLLOW_UP_DEPTH = 3` (gemini·mock 양쪽) | **1** (A11·DDL `CHECK depth IN (0,1)`) | depth 2 생성 시 DB 제약 위반 — **버그** |

> 격차 4의 `AudienceType`(청중=팀 유형, 4종)과 `QuestionerPersona`(질문자 페르소나, 5종)는
> 별개 enum이다. 질문 생성은 **세션의 `personas`(QuestionerPersona[])** 를 써야 한다.
> `_AUDIENCE_STYLE` 말투 사전도 5종 페르소나 기준으로 재작성([persona_voices.md](../../infra/gpu-server/persona_voices.md) 참고).

## 작업 단계

### A. 스키마·시그니처 확장 (프롬프트 전 선행) — ✅ 완료 (2026-07-13)

- [x] `schemas/qna.py`: 질문 초안 스키마 신설 — `QuestionDraft{ text, persona, strategy, evidence, follow_up_depth }`,
  `Evidence{ slides: list[int], transcript_refs: list[TranscriptRef] }`, `TranscriptRef{ start: float }`.
  (팀원2가 `id/order_index/tts_status`를 붙여 questions 행으로 저장. 기존 `QnaItem`은 레거시용 유지)
- [x] `base.py`·양쪽 provider 시그니처 교체: `generate_questions(*, speech_name, slides, transcript, personas, count)`,
  `follow_up(*, question, answer, depth)`. 깊이 상수는 `base.MAX_FOLLOW_UP_DEPTH = 1`로 통일(격차 6 해소).
- [x] `mock_provider.py`도 새 스키마로 — persona 라운드로빈·strategy 순환·evidence 더미(첫 슬라이드/전사)로 채워
  FE/BE가 mock으로 전체 형태를 받게 유지(공통 가이드 2).
- [x] `gemini_provider.py`: 새 시그니처 + slides(page 번호)·transcript(ts) 주입 프롬프트, `response_schema`로
  persona/strategy/evidence 강제, **evidence 사후검증**(범위 밖 page·ts 제거)·persona 라운드로빈 교정까지 구현.
  → B의 프롬프트·evidence 검증 상당 부분이 여기서 선행 완료됨.
- [x] 레거시 `routes/speeches.py` 어댑터(AudienceType→persona)로 앱 빌드 유지. 오프라인 검증: mock 계약·깊이
  가드·evidence 사후검증·프롬프트 포맷 통과, 앱 import·251 테스트 수집 정상.

### B. 질문 생성 프롬프트

- [x] slides는 `[p{page}]`로 라벨링해 주입(모델이 evidence로 되짚게). transcript는 **텍스트만**(타임스탬프 제외, 팀 합의)
- [x] 출력 강제: `response_schema`에 persona(세션 personas로 enum 제한)·strategy·evidence(slides만) 포함.
  persona는 프롬프트에서 "선택된 목록 안에서만, 고르게 배분"으로 지시 + 코드에서 라운드로빈 보정
- [x] 타게팅 규칙 문장화: "슬라이드에 있으나 transcript에 없음 / 있으나 근거·수치 약함"을 우선순위로
- [x] evidence 사후검증: `slides`는 실제 `page` 집합 안으로 필터(환각 페이지 제거). `transcript_refs`는 생성 단계에서 `[]`

### C. 꼬리질문 프롬프트

- [ ] depth ≥ 1 이면 즉시 None (A11) — 프롬프트 호출 전 코드 가드
- [ ] raw STT 견딤: "간투사·비문은 무시하고 내용으로만 판단", 답변이 근거·수치 빈약할 때만 그 지점 파고들기
- [ ] "생성 안 함" 명시 경로: `follow_up: null` 스키마로 강제, 빈/공백이면 None
- [ ] 부모 persona 유지, strategy는 답변 약점 유형에 맞게 재선택, evidence는 원 질문 근거 승계 가능

### D. 검증

- [ ] 회귀 고정 입력: 샘플 세션 1개(slides+transcript)로 질문 N개 생성 → persona 전량 세션 목록 내,
  strategy 전량 유효 enum, evidence.slides 전량 실제 page — 스냅샷 테스트 (Step 4 "프롬프트 회귀 테스트"와 공유)
- [ ] 꼬리질문: depth 0 답변 2종(구체/빈약)으로 각각 None / depth-1 생성 확인. depth 1 입력은 항상 None
- [ ] 팀원2 합류: `POST /qna/generate` → questions 저장 → `GET /qna` 응답이 §4.4 예시와 필드 일치

## 엣지케이스

| 케이스 | 처리 |
|---|---|
| 자료 없음(slides 빈 배열) | 제목+transcript만으로 생성, evidence.slides=[] |
| transcript 없음(STT 실패 후 진행) | slides만으로, transcript_refs=[] · 타게팅은 ①만 |
| personas 1개만 선택 | 전 질문 동일 persona (라운드로빈이 1종으로 수렴) |
| 모델이 count 초과/미달 | count로 잘라내고, 부족하면 있는 만큼(라우터가 order_index 부여) |
| evidence 환각(없는 page·ts) | 사후검증에서 범위 밖 제거 → 빈 배열 (질문 텍스트는 유지) |
| 답변이 "패스"/빈 답변 | 라우터가 `pass` 경로로 처리 → `follow_up` 미호출 |

## 예상 작업량

A(스키마 정렬)가 실제 병목 — 여기서 provider 인터페이스가 확정돼야 팀원2 라우터가 붙는다.
B·C 프롬프트 자체는 반나절, **evidence 사후검증과 persona 배분 보정이 품질의 실체.**
격차 6(깊이 상수)은 한 줄 수정이지만 안 고치면 꼬리질문에서 DB 제약 위반으로 잡히니 A에서 같이 처리.
