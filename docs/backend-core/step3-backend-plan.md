# Step 3 (Day 5) — 팀원2 Backend Core 상세 작업 계획

> 기준 문서: [api-spec.md](../api-spec.md) §4.4·§6 · [db-schema.md](../db-schema.md) §3.5·§3.6·§5·§8.2 · [workflow.md](../workflow.md) Step 3 · [ai-pipeline/qna-prompt-workflow.md](../ai-pipeline/qna-prompt-workflow.md)
> 대상: 질의응답(Q&A) 루프 백엔드 — **프로젝트의 심장**. Step 1(인증·팀·스토리지)·Step 2(세션·자료·녹음/STT)는 완료 상태.

---

## 0. 시작 전 — 이미 있는 재사용 자산 (새로 만들지 말 것)

Step 3도 "부품을 조립"하는 작업이다. 질문 생성(LLM)·음성 합성(TTS)·답변 전사(STT) 무거운 부품은 이미 만들어져 있다:

| 부품 | 위치 | 인터페이스 | 누가 만듦 |
|---|---|---|---|

| LLM 질문/꼬리질문 | `app/services/llm/base.py` · `factory.py` | `get_llm_provider()` → `generate_questions(speech_name, slides, transcript, personas, count) → [QuestionDraft]` / `follow_up(question, answer, depth) → QuestionDraft \| None` (둘 다 **async**) | 팀원3 |
| 질문 TTS 클라이언트 | `app/services/tts.py` | `synthesize_question(text, persona=, client=) → wav bytes` / `TtsError` · `list_voices()` (**동기**, 미등록 페르소나는 default 폴백) | 팀원3 |
| 답변 STT 클라이언트 | `app/services/stt.py` | `transcribe_recording(path) → [{"start","end","text"}]` / `UnsupportedMediaError` · `seconds_to_ts(sec)` | 팀원3 |
| STT 직렬 큐 | `app/services/stt_queue.py` | `enqueue(session_id)`, 단일 워커 · `recover()` — **답변 STT도 이 워커 하나를 공유**(작업 4) | 팀원2 |
| 질문 초안 스키마 | `app/schemas/qna.py` | `QuestionDraft(text, persona, strategy, evidence, follow_up_depth)`, `Evidence`, `TranscriptRef` | 팀원2/3 |
| 파일 저장/서명 URL | `app/core/storage.py` | `tts_key(ses, qid)`, `answer_key(ses, qid, ext)`, `save`, `signed_url`, `delete` | 팀원2 |
| 세션 상태머신 | `app/services/session_state.py` | `advance_status(session, to)` — `transcribing→generating_questions→qna→completed` 전이표 **이미 있음** | 팀원2 |
| 세션 권한 Depends | `app/api/deps.py` | `require_session_member`, `require_session_owner` | 팀원2 |
| 에러 포맷 | `app/core/errors.py` | `ApiError(status, code, message)` | 팀원2 |

> **핵심 원칙 (api-spec §0.1·§4.4 A 수정):** 질문 생성·TTS·답변 STT·꼬리질문은 전부 몇 초~수십 초 걸린다. 특히 **답변 제출은 절대 꼬리질문을 즉시 반환하지 않는다** — `202`로 접수만 하고, 꼬리질문/다음 질문 이동은 `GET /qna` 폴링으로 확정한다. (spec §4.4, 가장 흔히 어기는 지점)

> **정리(중요):** `schemas/qna.py`의 `QnaItem`·`QnaAnswer`는 구버전(Team/Speech) 잔재다. Step 3 응답에는 쓰지 않으며, 새 스키마(작업 1)로 대체하고 정리한다.

---

## 작업 0. STT 워커 공유 준비 — 답변 전사 잡 추가 (먼저, 작음)

**왜 먼저인가:** STT 서버(GPU)는 한 번에 하나만 처리(infra 제약 2). Step 2에서 만든 발표 전사 워커와 **같은 단일 워커**를 답변 전사도 공유해야, 발표 전사와 답변 전사가 GPU에서 겹치지 않는다. 큐를 새로 만들면 워커가 2개가 되어 직렬 보장이 깨진다.

### 0-1. 큐에 잡 종류 실어 보내기 (`app/services/stt_queue.py` 확장)
- 현재 큐는 `session_id: str`만 넣고 워커가 `_run_stt`(발표 전사)를 실행한다.
- 잡을 `(kind, id)` 형태로 확장: `("recording", session_id)` / `("answer", question_id)`.
  - `enqueue_recording(session_id)` (기존 `enqueue` 개명·호환 유지) / `enqueue_answer(question_id)` 추가.
  - 워커 루프가 `kind`로 분기: `recording → _run_stt` / `answer → _run_answer_stt`(작업 4-2).
- `recover()`도 두 종류 모두 복구: `transcripts.status ∈ {queued,processing}` + `answers.status = processing` 재적재.

> 큐 자료구조·워커·직렬성 보장은 그대로 재사용하고 **잡 디스패치만** 넓힌다. 워커는 여전히 1개 = STT 서버 직렬 계약 유지.

---

## 작업 1. Q&A 응답 스키마 (`app/schemas/qna.py` 확장)

api-spec §4.4 `GET /qna` 응답이 계약. **팀원1 폴링이 필드 단위로 의존**하므로 예시와 정확히 맞춘다.

### 1-1. 응답 모델
- `TtsOut` — `{ status: AsyncStatus, audio_url: str | None }` (`tts_storage_key → signed_url` 파생).
- `AnswerOut` — `{ status: "pending|processing|ready|failed", text: str | None, audio_url: str | None, follow_up_status: "pending|generated|none", error: ErrorInfo | None }`.
  - **`status="pending"`은 `answers` row 부재로 표현**(db-schema §5) — 아직 답 안 한 질문은 `answer: null`이 아니라 `answer.status="pending"`으로 서빙(§4.4 예시). 라우터에서 row 없으면 pending으로 채운다.
- `EvidenceOut` — `{ slides: [int], transcript_refs: [{ ts: "MM:SS" }] }`. 저장은 `{"start": 252.0}`(초), **응답 시 `seconds_to_ts`로 포맷**(db-schema §6.3).
- `QuestionOut` — `{ id, order, persona, strategy, parent_id, follow_up_depth, text, evidence, tts, answer }`.
- `QnaStateOut` — `{ status: "in_progress|ended", current_question_id: str | None, ended_reason: "user_end|count_reached|timeout" | null, questions: [QuestionOut] }`.
  - `status`는 `sessions.status` 파생(`qna→in_progress`, `completed→ended`, db-schema §5).
- `PassRequest` — `{ reason: "user" | "timeout" = "user" }` (§4.4 v0.4-draft).

### 1-2. 정렬 규칙
- `questions[]`는 **`ORDER BY order_index, follow_up_depth`** (꼬리질문은 부모 바로 뒤). db-schema §8.2 쿼리 그대로.

---

## 작업 2. 질문 생성 + TTS 큐 (`POST /qna/generate`)

api-spec §4.4. STT 완료(`transcript.ready`) 후 slides+transcript+personas로 질문 생성 → 질문별 TTS.

### 2-1. 라우터 `POST /sessions/{id}/qna/generate` → `202`
- 권한: owner. 선행조건 검증:
  - `transcript.status == ready` 아니면 `409`(전사 먼저). 자료는 있으면 `material.ready` 대기, 없으면 그냥 진행(§4 note).
  - 상태 전이 `advance_status(session, generating_questions)` (transcribing에서만 허용 — 재생성은 별도 협의).
- 처리 순서: 세션 전이 커밋 → **백그라운드 잡 등록** → 즉시 `202`.
- 중복 방지: 이미 `generating_questions`/`qna`면 `409`(재생성 요청 무시 — 데모 스코프).

### 2-2. 백그라운드 질문 생성 잡 (별도 DB 세션)
```
advance → generating_questions (2-1에서 이미)
try:
    slides = materials.slides (있으면) · segments = transcripts.segments
    drafts = await get_llm_provider().generate_questions(
        speech_name=session.name, slides=slides, transcript=segments,
        personas=session.personas, count=session.question_count)
    → questions 행 N개 insert:
        order_index = 1..N, follow_up_depth=0, parent_id=None,
        persona/strategy/text/evidence = draft, tts_status=queued
    → session.current_question_id = 첫 질문(order_index=1)
    → advance_status(session, qna)   # 질문 생성 완료
    → 각 질문 TTS 잡 enqueue (작업 3)
except (LLM 오류):
    → advance_status(session, failed)  # generating_questions → failed (재시도 경로)
```
- **페르소나 배분:** `generate_questions`가 personas 목록 안에서 질문마다 배정(계약). 라우터는 draft의 persona/strategy를 그대로 저장만 한다(협의사항 6 — 배분은 LLM 몫).
- `evidence`는 `QuestionDraft.evidence`(Pydantic) → `model_dump()`로 JSONB 저장. `transcript_refs`는 `{"start": float}` 형태 유지(포맷은 서빙 시).

### 2-3. 검증
- mock LLM으로 질문 N개 생성 → `qna` 전이 · order_index 1..N · current=첫 질문 / LLM 실패 → failed(재시도 가능) / transcript 없는데 generate → 409 / 비owner → 403.

---

## 작업 3. 질문 TTS 잡 (A6 큐)

api-spec §4.4·A6. 질문 텍스트 → 페르소나 wav. **TTS 서버도 동시성 한계**(A6)라 세션 내 질문은 직렬 처리.

### 3-1. TTS 잡
- 세션의 질문들을 **httpx.Client 하나를 공유**해 한 번에 하나씩(`tts.py` 주석 패턴):
  ```
  for q in questions(session, tts_status=queued):
      q.tts_status = processing
      try:
          wav = tts.synthesize_question(q.text, persona=q.persona, client=c)  # 동기 → run_in_executor
          key = storage.tts_key(session_id, q.id); storage.save(key, wav)
          → q.tts_storage_key=key, tts_status=ready
      except tts.TtsError as e:
          → q.tts_status=failed, tts_error_code="TTS_FAILED", tts_error_message=str(e)
  ```
- 실행 방식: 데모 스코프에선 `BackgroundTasks` + 세션 단위 순차로 충분(TTS 서버 직렬은 클라이언트 공유로 자연 보장). STT 큐처럼 별도 워커까진 불필요.
- 꼬리질문(작업 4)이 새로 생기면 그 질문 1개에 대해서도 같은 TTS 잡을 태운다.

### 3-2. 검증
- mock TTS로 질문별 `tts.status queued→ready` + `audio_url` 발급 / TtsError → failed(폴링으로 노출) / 미등록 페르소나 default 폴백(tts.py 내부).

---

## 작업 4. 답변 제출 + 꼬리질문 (`POST /answer`) — **최난도**

api-spec §4.4 A 수정. **답변 제출은 `202`만**, 꼬리질문·다음 질문은 `GET /qna` 폴링으로 확정.

### 4-1. 라우터 `POST /sessions/{id}/qna/questions/{qid}/answer` (multipart) → `202`
- 권한: owner. 필드: `file`(audio), `duration_seconds`.
- 검증: 세션 `status == qna` 아니면 `409` / `qid`가 이 세션 질문인지 / 오디오 형식(§1.3, recordings와 동일 mime 세트).
- 처리 순서:
  1. `key = storage.answer_key(session_id, qid, ext)` → `storage.save(key, bytes)`
  2. `answers` 행 upsert: `kind=answered`, `status=processing`, `audio_storage_key=key`, `follow_up_status=pending`, `text=NULL`. **재제출(실패 재시도)은 같은 행 덮어쓰기**.
  3. **답변 STT 잡 큐 적재**(`stt_queue.enqueue_answer(qid)`, 작업 0) → 즉시 `202`.
- 응답 본문: `{ "answer": { "status": "processing", "text": null, "audio_url": ..., "follow_up_status": "pending" } }` (§4.4).

### 4-2. 답변 STT + 꼬리질문 판정 잡 (`_run_answer_stt`, 워커에서 실행)
```
answer.status = processing (이미)
try:
    segments = transcribe_recording(answer_audio) → answer.text = join(segments), status=ready
except: answer.status=failed, error_code="STT_FAILED"  # 재제출로 재시도, 종료
# --- 꼬리질문 판정 (깊이 1 제한, A11) ---
parent = question(qid)
if parent.follow_up_depth >= 1 or parent.kind==passed:
    answer.follow_up_status = none → 다음 질문으로 current 이동
else:
    draft = await follow_up(question=parent.text, answer=answer.text, depth=parent.follow_up_depth)
    if draft is None:
        answer.follow_up_status = none → 다음 1차 질문(또는 종료)
    else:
        child = questions insert(parent_id=qid, follow_up_depth=1,
                                 order_index=parent.order_index, persona/strategy/text/evidence=draft,
                                 tts_status=queued)
        answer.follow_up_status = generated
        session.current_question_id = child.id      # 꼬리질문으로 이동
        child 1개 TTS 잡 enqueue (작업 3)
```
- **current_question_id 이동 로직**(공통 헬퍼 `advance_current_question(session)`):
  - 꼬리질문이 생겼으면 → 그 자식.
  - 아니면 → 다음 1차 질문(`order_index+1`, parent_id NULL). 없으면 종료 판정(작업 5, `count_reached`).
- 잡은 **절대 예외를 밖으로 던지지 않는다**(워커 보호) — STT 큐 `_run_stt`와 동일 규약.

### 4-3. `POST .../pass` (스킵)
- `answers` 행 `kind=passed`, `status=ready`, `audio_storage_key=NULL`, `follow_up_status=none`(DDL CHECK 강제) → `current_question_id`를 다음 1차 질문으로 이동. 없으면 종료(`count_reached`).
- 바디 `{ reason: "user" | "timeout" }` 저장(마지막 질문이 timeout이면 `qna/end`의 `ended_reason` 판정에 사용).

### 4-4. 검증 (GPU 없이 mock STT/LLM)
- 답변 업로드 → `202` + `answer.processing` / 폴링 → `ready` + `text` / 꼬리질문 생성 시 자식 추가 + current 이동 + 자식 TTS / follow_up None이면 다음 질문 / **깊이 1 도달 시 꼬리질문 안 생김** / STT 실패 → failed + 재제출 복구 / pass → 다음 질문 · 오디오 없음 / 비owner 403 / qna 아닌 상태 403·409.

---

## 작업 5. Q&A 폴링 소스 + 종료 (`GET /qna`, `qna/end`)

### 5-1. `GET /sessions/{id}/qna` — 폴링 단일 소스
- 권한: 멤버. db-schema §8.2 쿼리(questions LEFT JOIN answers, `ORDER BY order_index, follow_up_depth`).
- **spec §4.4 예시와 필드 단위 일치** 확인 — `status`·`current_question_id`·`ended_reason`·각 질문 `tts`/`answer`(pending 파생 포함).
- `GET /sessions/{id}/qna/questions/{qid}` — 질문 상세(같은 QuestionOut 1건).

### 5-2. `POST /sessions/{id}/qna/end` — 종료
- 권한: owner. `advance_status(session, completed)` + `qna_ended_reason` 확정.
- **종료 우선순위(A12):** 사용자 `qna/end`(`user_end`) > 1차 질문 수 도달(`count_reached`) > 답변 시작 시간초과(`timeout`).
  - 명시 호출은 `user_end`. 작업 4에서 마지막 1차 질문 답변/패스 후 자동 종료면 `count_reached`(마지막이 timeout pass면 `timeout`).
- 종료 시 **리포트 잡 자동 큐**(A7) — 리포트 생성 로직 실체는 **Step 4**(reports 테이블). 여기선 `reports` 행 `status=queued` 생성 + 잡 트리거 지점만 마련(Step 4가 채움).

### 5-3. 검증
- `GET /qna` 형태가 spec 예시와 일치 / `qna/end` → completed + ended_reason / 종료 후 answer 제출 409 / count 도달 자동 종료 시 reason=count_reached / reports 행 queued 생성.

---

## 라우터 등록

`app/api/routes/qna.py` 신규 → `main.py`에 `include_router(qna.router, prefix=API_V1)` 추가. 경로: `/sessions/{id}/qna*`.

---

## 권장 순서 & 오늘 할 일

```
작업 0 (STT 워커에 답변 잡 추가, 작음)
  → 작업 1 (Q&A 응답 스키마)              ← 폴링 계약 먼저 고정
  → 작업 2 (질문 생성 + qna 전이)          ← LLM 준비됨, 202+폴링
  → 작업 3 (질문 TTS 잡)                   ← TTS 준비됨, 세션 내 직렬
  → 작업 4 (답변 + 꼬리질문)               ← 최난도, 비동기 규약 절대 준수
  → 작업 5 (GET /qna 폴링 소스 + 종료)     ← 팀원1 폴링의 단일 진실
```

**한 줄 요약:** 질문을 생성해 TTS로 음성화하고, 답변은 `202`로 접수만 한 뒤 백그라운드에서 STT→꼬리질문 판정을 돌리며, 모든 확정은 **`GET /qna` 폴링 한 곳**으로 서빙한다.

## 공통 지침 (Step 1·2와 동일)

1. **계약 우선** — `GET /qna` 응답은 api-spec §4.4 예시와 필드 단위로 맞출 것(팀원1 폴링이 의존). `answer.status=pending`은 row 부재로 파생.
2. **비동기 규약** — 답변 제출은 절대 꼬리질문을 즉시 반환하지 말 것(§4.4 A 수정 — 가장 흔히 어기는 지점). `202` + `GET /qna` 폴링.
3. **STT 단일 워커** — 답변 전사는 발표 전사와 **같은 워커 하나**를 공유(GPU 직렬). 별도 큐 만들지 말 것.
4. **별도 DB 세션** — 백그라운드 잡(질문 생성·TTS·답변 STT)은 `SessionLocal()`로 자기 세션을 연다. 잡은 예외를 밖으로 던지지 않고 `failed`로 흡수.
5. **검증 필수** — mock LLM·mock TTS·mock STT로 GPU 없이 E2E(generate→TTS→answer→꼬리질문→end→리포트 큐)를 관통. 상태 전이·권한·폴링 형태·깊이 1 제한을 pytest로 확인.
6. **재검증** — 동시 답변 제출·재제출·pass 직후 종료·마지막 질문 꼬리질문 등 엣지를 적대적으로 한 번 더 찔러볼 것.
