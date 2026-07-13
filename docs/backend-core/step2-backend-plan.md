# Step 2 (Day 4) — 팀원2 Backend Core 상세 작업 계획

> 기준 문서: [api-spec.md](api-spec.md) §4 · [db-schema.md](db-schema.md) §3.3~3.5·§5·§6 · [workflow.md](workflow.md) Step 2 · [infra/gpu-server/README.md](../infra/gpu-server/README.md)
> 대상: 발표 자료(PDF)·녹음 파이프라인 백엔드. Step 1(인증·팀·스토리지)은 완료 상태.

---

## 0. 시작 전 — 이미 있는 재사용 자산 (새로 만들지 말 것)

Step 2는 "부품을 조립"하는 작업이다. 무거운 부품은 이미 만들어져 있다:

| 부품 | 위치 | 인터페이스 | 누가 만듦 |
|---|---|---|---|
| 파일 저장/서명 URL | `app/core/storage.py` | `material_key(ses)`, `recording_key(ses, ext)`, `save(key, bytes)`, `signed_url(key)`, `delete(key)` | 팀원2 (작업 5) |
| PDF 파서 | `app/services/material.py` | `parse_pdf_to_slides(bytes) → [{"page":1,"text":"..."}]` / `UnprocessablePdfError`·`PdfParseError` | 팀원3 |
| STT 클라이언트 | `app/services/stt.py` | `transcribe_recording(path) → [{"start","end","text"}]` / `SttError`·`UnsupportedMediaError` / `seconds_to_ts(sec)` | 팀원3 |
| 인증·권한 Depends | `app/api/deps.py` | `get_current_user`, `load_team_as_member`, `require_team_member`, `require_team_leader` | 팀원2 |
| 에러 포맷 | `app/core/errors.py` | `ApiError(status, code, message)` → `{"error":{code,message}}` | 팀원2 |

> **핵심 원칙 (api-spec §0.1·§1.2):** PDF 파싱·STT는 몇 초~몇 분 걸린다. 요청은 **즉시 `202`로 접수만** 하고, 실제 처리는 백그라운드에서 하며, 리소스 상태(`queued→processing→ready→failed`)를 클라이언트가 폴링해 완료를 확인한다.

---

## 작업 1. 권한 공통화 — owner 검사 추가 (먼저, 작음)

세션은 "발표자(owner)"만 수정·삭제할 수 있다. 팀 멤버/팀장 가드(작업 4-2)를 세션 스코프로 확장한다.

### 1-1. 세션 로더 + owner 가드 Depends (`app/api/deps.py`)
- `load_session_as_member(session_id, user, db) → Session`
  - 세션을 로드하고, 요청자가 **그 세션이 속한 팀의 멤버**인지 확인. 아니면 `404 SESSION_NOT_FOUND` (비멤버에게 존재를 숨김 — 팀 로더와 같은 규칙).
  - 내부적으로 `session.team_id`로 `load_team_as_member` 재사용.
- `require_session_owner(session, user)` → owner 아니면 `403 FORBIDDEN_NOT_OWNER` (§6.2).
- 삭제는 **owner 또는 팀장** 허용 (api-spec §4.1) → `require_session_owner_or_leader(session, user, db)`.

### 1-2. 검증
- 멤버 조회 OK / 비멤버 404 / owner 아닌 멤버가 PATCH → 403 / 팀장이 삭제 → OK.

> 이 Depends들이 작업 2~4의 모든 세션 하위 엔드포인트(material·recording·transcript)에서 재사용된다. 먼저 만들어야 나머지가 한 줄로 권한을 얻는다.

---

## 작업 2. 세션 CRUD + 상태머신 (`/teams/{id}/sessions`, `/sessions/{id}`)

api-spec §4.1이 계약. 상태머신(§4): `draft → recording_in_progress → transcribing → generating_questions → qna → completed`(+`failed`).

### 2-1. Pydantic 스키마 (`app/schemas/session.py` 신규)
- `SessionCreateRequest` — `name`(1~50), `personas: list[QuestionerPersona]`(≥1, **중복 제거**), `question_count`(1~20), `time_limit_minutes`(1~120), `mode`(realtime|upload). enum은 `app/db/enums.py` 재사용.
  - **협의사항 (6) 반영**: personas는 중복 없는 집합으로 저장. 질의 수에 걸친 페르소나 배분(2/2/1 등)은 Step 3 질문 생성 때 처리 — 여기선 저장만.
- `SessionDetail` — 세션 요약 + 하위 리소스 상태(§4.1 응답 예시와 필드 단위 일치):
  ```
  { id, team_id, owner_id, name, status, personas, question_count,
    time_limit_minutes, mode,
    material: { status, slide_count } | null,
    recording: { status, duration_seconds, audio_url } | null,
    transcript: { status } | null,
    report: null,          # qna 종료 전엔 항상 null (A7)
    created_at }
  ```
  - `audio_url`은 `storage.signed_url(recording.storage_key)`로 파생(A10). 저장은 storage_key만.
- `SessionCardOut` — 목록용 요약(name, status, created_at, persona 수 등).

### 2-2. 세션 CRUD 라우터 (`app/api/routes/sessions.py` 신규)
| Method | Path | 권한 | 처리 |
|---|---|---|---|
| GET | `/teams/{team_id}/sessions` | 멤버 | 팀 세션 목록(`sessions_team_idx` 정렬: created_at DESC) |
| POST | `/teams/{team_id}/sessions` | 멤버 (생성자=owner) | `draft` 세션 생성, `owner_id=user.id` |
| GET | `/sessions/{session_id}` | 멤버 | 상세(2-1 SessionDetail) |
| PATCH | `/sessions/{session_id}` | owner + `draft`일 때만 | 설정 수정 |
| DELETE | `/sessions/{session_id}` | owner 또는 팀장 | 삭제(2-4) |

- `main.py`에 라우터 등록(`prefix=/api/v1`). teams 라우터와 경로 안 겹침(하위 `/sessions`는 팀 스코프, `/sessions/{id}`는 최상위).

### 2-3. 상태 전이 헬퍼
- `advance_status(session, to, allowed_from)` — 허용된 이전 상태가 아니면 `409 INVALID_STATE_TRANSITION`. 잘못된 순서(예: draft에서 바로 qna) 차단.
- PATCH는 `session.status == draft`가 아니면 `409`(설정 확정 후 수정 불가).

### 2-4. 삭제 cascade + 스토리지 정리 (db-schema §7.3)
- **커밋 전** 세션의 storage_key 목록 수집(material·recording·질문 TTS·답변 오디오) → `db.delete(session)` (DB CASCADE) → **커밋 성공 후** `storage.delete(key)` 순차 호출.
- 순서 중요: DB CASCADE는 파일을 못 지우므로, 키를 먼저 모으고 커밋 뒤 파일 삭제. (실패분은 나중에 청소 — 지금은 best-effort)

### 2-5. 검증 (pytest)
- 생성 시 owner 지정·status=draft / 목록은 팀 스코프 / 비owner PATCH 403 / draft 아닐 때 PATCH 409 / 팀장 삭제 OK / 삭제 시 하위 행 CASCADE + 스토리지 파일 제거 / enum 배열(personas) 왕복.

---

## 작업 3. 발표 자료 (PDF → slides.json)

api-spec §4.2. 무거운 파싱은 백그라운드, 요청은 `202`.

### 3-1. 업로드 라우터 `POST /sessions/{id}/material` (multipart)
- 권한: owner. 파일 검증(§1.3): **PDF만**, `≤20MB`, 초과 시 `413 FILE_TOO_LARGE` / 형식 아니면 `415`.
- 처리 순서:
  1. `key = storage.material_key(session_id)` → `storage.save(key, file_bytes)`
  2. `materials` 행 upsert: `status=queued`, `file_name`, `file_size_bytes`, `storage_key=key`
  3. **백그라운드 잡 등록** → 즉시 `202` 반환
- 재업로드는 기존 material 덮어쓰기(같은 key) + status 재설정.

### 3-2. 백그라운드 파싱 잡
- FastAPI `BackgroundTasks`로 충분(PDF 파싱은 로컬 CPU 작업, 세션 간 병렬 OK — STT와 달리 직렬 불필요).
- 잡 내부(요청과 **별도 DB 세션** `SessionLocal()` 사용 — 응답 후 실행되므로):
  ```
  status=processing
  try:
      slides = await run_in_executor(parse_pdf_to_slides, pdf_bytes)  # 동기 함수 감싸기
      → materials.slides=slides, page_count=len(slides), status=ready, progress=1.0
  except UnprocessablePdfError:
      → status=failed, error_code="UNPROCESSABLE_PDF" (422 성격)
  except PdfParseError:
      → status=failed, error_code="PDF_PARSE_ERROR" (retry 대상)
  ```

### 3-3. 조회·재시도·삭제
- `GET /sessions/{id}/material` — status + slides + error (멤버). 응답 예시 §4.2.
- `POST /sessions/{id}/material/retry` — status=queued로 되돌리고 잡 재등록(owner).
- `DELETE /sessions/{id}/material` — 자료 없이 진행 허용(owner). storage 파일도 삭제.

### 3-4. 검증
- 정상 PDF → ready + slides(page별 text) / 스캔본 → failed UNPROCESSABLE_PDF (500 아님) / 20MB 초과 → 413 / 폴링 흐름(queued→processing→ready) / retry로 재파싱 / 비owner 업로드 403.

---

## 작업 4. 발표 녹음 + STT (→ transcript.json) — **최난도**

api-spec §4.3 + infra 제약 2(STT 서버 **직렬 처리**). 여기가 오늘의 핵심 난관.

### 4-1. 업로드 라우터 `POST /sessions/{id}/recording` (multipart)
- 권한: owner. 필드: `file`(audio), `started_at`, `ended_at`, `duration_seconds`.
- 검증(§1.3): mime ∈ {audio/mpeg, audio/wav, audio/mp4} 아니면 `415`, `≤200MB` 초과 `413`, `duration≤3600`.
- 처리 순서:
  1. `key = storage.recording_key(session_id, ext)` → `storage.save(key, bytes)`
  2. `recordings` 행: `status=ready`(업로드 완료), 메타(duration·mime·started/ended_at)
  3. `transcripts` 행: `status=queued`
  4. `session.status = transcribing` (상태 전이)
  5. **STT 잡을 큐에 넣고** 즉시 `202` 반환

### 4-2. STT 직렬 큐 (⚠️ 이 스텝의 핵심)
- **왜 큐가 필요한가:** STT 서버(GPU)가 한 번에 하나만 처리(infra 제약 2). 세션 두 개가 동시에 STT를 돌리면 서로 막히거나 실패한다. 그래서 백엔드에서 **한 번에 하나씩** 꺼내 처리하는 단일 워커 큐가 필수.
- **최소 구현 (7일 스코프):**
  - 모듈 레벨 `asyncio.Queue` + **워커 1개**를 앱 시작 시(lifespan/startup) 실행.
  - 업로드 라우터는 `await queue.put(session_id)`만 하고 반환.
  - 워커 루프: `session_id = await queue.get()` → 별도 DB 세션으로 처리:
    ```
    transcript.status=processing
    try:
        segments = await run_in_executor(transcribe_recording, audio_path)
        → transcripts.segments=segments, status=ready
    except UnsupportedMediaError:
        → status=failed, error_code="UNSUPPORTED_MEDIA"
    except SttError:
        → status=failed, error_code="STT_FAILED"  (retry 대상)
    ```
  - 파일은 storage_key로 저장돼 있으니, 잡에서 임시 경로로 내려받아 `transcribe_recording(path)` 호출.
- **주의:** 서버 재시작 시 큐(메모리)가 비므로, `queued/processing`인데 워커가 없는 고아 잡은 재시작 시 다시 큐에 넣는 복구 로직을 시작 훅에 두면 좋다(선택 — 데모엔 없어도 됨).
- **대안(더 단순):** 잡 수가 적은 데모라면 `BackgroundTasks` + 모듈 레벨 `asyncio.Lock`으로 "한 번에 하나"를 강제해도 됨. 큐만큼 견고하진 않지만 코드가 짧다.

### 4-3. 조회·재시도
- `GET /sessions/{id}/transcript` — status + segments. **저장은 초 float(§6.2), 응답 시 `seconds_to_ts()`로 `ts:"MM:SS"` 변환**(§4.3). segments 예시:
  ```
  { "status":"ready",
    "segments":[ {"ts":"00:12","text":"안녕하세요, 어… 발표를 맡은…"} ], "error":null }
  ```
- `POST /sessions/{id}/transcript/retry` — status=queued로 되돌리고 큐 재투입(owner).
- (선택) `POST /sessions/{id}/recording/start` — 실시간 모드 표시용(`recording_in_progress`, started_at). 데모는 업로드 모드만이면 생략 가능.

### 4-4. 검증 (STT 서버 없이도 가능하게)
- STT 클라이언트를 **모킹**해 큐·상태 전이·에러 매핑을 검증(실 GPU 없이):
  - 정상 → transcribing → transcript.ready + segments / `ts` 포맷 변환 확인
  - 지원 안 되는 형식 → 415 / SttError → failed STT_FAILED + retry로 복구
  - **큐 직렬성:** 세션 2개 동시 업로드 → STT가 겹쳐 실행되지 않는지(워커 1개 보장) 확인
  - 비owner 업로드 403 / 200MB 초과 413

---

## 권장 순서 & 오늘 할 일

```
작업 1 (owner 권한, 30분)
  → 작업 2 (세션 CRUD + 상태머신)         ← 기존 팀 CRUD 패턴 반복, 수월
  → 작업 3 (material 업로드 + 파싱 잡)     ← 파서는 준비됨, 202+폴링 첫 적용
  → 작업 4 (recording + STT 직렬 큐)       ← 최난도, 큐가 관건
```

**한 줄 요약:** 세션 CRUD를 만들고, PDF·녹음 업로드를 `202`로 접수해 백그라운드에서 파싱·STT를 돌리되, **STT는 직렬 큐로 하나씩** 처리한다.

## 공통 지침 (Step 1과 동일)

1. **계약 우선** — 응답 형태는 api-spec §4 예시와 필드 단위로 맞출 것(팀원1 폴링이 의존).
2. **비동기 규약** — 무거운 작업은 `202` + 리소스 상태 폴링. 절대 업로드 응답에서 결과(slides·segments)를 바로 주지 말 것.
3. **별도 DB 세션** — 백그라운드 잡은 요청 세션이 아니라 `SessionLocal()`로 자기 세션을 연다(응답 후 실행되므로).
4. **검증 필수** — 각 작업마다 pytest로 상태 전이·에러 매핑·권한·폴링을 실제 DB까지 관통해 확인. STT는 모킹으로 GPU 없이 검증.
5. **재검증** — 구현 후 엣지 케이스(동시 업로드·큐 직렬성·잘못된 형식·재시도)를 한 번 더 적대적으로 찔러볼 것.
