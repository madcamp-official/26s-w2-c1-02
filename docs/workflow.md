# Rehearsal.io — 역할 분담 & 워크플로우

> 기준 문서: [api-spec.md](api-spec.md) v0.3 · [db-schema.md](db-schema.md) v1.0 · [infra/gpu-server/README.md](../infra/gpu-server/README.md) · [design/wireframes/README.md](../design/wireframes/README.md)
> 작성일: 2026-07-11

---

## 역할 분담 (3인)

| 역할 | 담당 | 담당 영역 | 기준 문서 |
|---|---|---|---|
| **팀원1 — Frontend** | 팀원1 | Flutter 28화면, 상태관리, 폴링 UX, 오디오 녹음/재생, Mock→API 전환 | api-spec v0.3 + 와이어프레임 |
| **팀원2 — Backend Core** | 팀원2 | FastAPI + PostgreSQL, 인증(JWT)/팀/초대/세션 CRUD, 상태머신, 파일 스토리지, 배포 | api-spec v0.3 + db-schema v1.0 |
| **팀원3 — AI Pipeline** | 팀원3 | GPU 서버(STT/TTS) 운영·연동, PDF 파싱, LLM(외부 API) 질문 생성·꼬리질문·리포트 프롬프트, 정량 지표 | gpu-server README + api-spec §4~5 |

**경계 규칙:**

- 팀원1 ↔ 팀원2 사이 계약 = **api-spec v0.3**
- 팀원2 ↔ 팀원3 사이 계약 = BE가 호출하는 내부 서비스 인터페이스 (STT `/transcribe`, TTS `/v1/audio/speech`, LLM 함수 시그니처)
- 팀원3은 라우터를 만들지 않고 **서비스 모듈**(`services/stt.py`, `services/tts.py`, `services/llm/`)만 제공, 팀원2가 라우터에서 조립한다. → 두 백엔드 담당이 같은 저장소에서 충돌 없이 병렬 작업 가능

---

## 공통 가이드라인 (전원)

1. **계약 우선** — API를 바꾸고 싶으면 코드가 아니라 api-spec.md를 먼저 고치고 팀 합의 → 그다음 구현. FE는 spec만 보고 개발하고 BE 완성을 기다리지 않는다.
2. **Mock으로 병렬화** — FE는 `MockRepository`, BE는 STT/TTS/LLM mock 모드를 유지해서 GPU 서버나 상대 파트 없이도 각자 E2E가 돌게 유지한다. "내 파트만 실물로 교체"가 항상 가능해야 한다.
3. **비동기 규약 준수** — 모든 무거운 작업은 `202` 접수 → `queued|processing|ready|failed` 폴링. 특히 답변 제출은 절대 꼬리질문을 즉시 반환하지 않는다 (spec §4.4 A 수정 — 가장 흔히 어길 부분).
4. **매일 통합** — 하루 끝에 `main`에 머지하고 FE mock-off로 스모크 테스트 1회. 통합을 마지막 날로 미루는 게 최대 리스크.
5. **스코프 컷 합의 (권장)** — 소셜 로그인 3종·이메일 인증(SMTP)·SSE는 **선택**으로 내리고, 핵심 루프(PDF→STT→질문→TTS→답변→꼬리질문→리포트)를 필수로. 과제 평가 기준은 "LLM Wrapper + Cross-Platform 동작"이다.

---

## Step 1 — 기반 구축 (Day 3)

### 팀원1 (Frontend)

- [x] 데이터 모델을 `Team/Speech` → `Session` 구조로 교체 (spec §6.1 enum 전부: persona 5종, strategy 4종, AsyncStatus 등)
- [x] `MockSessionRepository`를 spec 응답 예시 JSON과 동일한 형태로 재작성 (FE의 "가짜 서버")
- [x] 28화면 라우트 골격 + 공통 폴링 위젯(1~2초 간격, `ready|failed` 종료) 1개 구현
- [x] 인증 플로우: access 토큰 보관, 401 `TOKEN_EXPIRED` → refresh 재시도 인터셉터 (Web/Native 분기 `X-Client-Platform`)

### 팀원2 (Backend Core)

- [x] PostgreSQL 16 기동 + db-schema DDL 전체 적용 (ENUM 12종, 테이블 16개, 트리거)
- [x] SQLAlchemy(또는 선택 ORM) 모델 + prefix ID 생성기 (`usr_` + base62)
- [x] `/auth/signup·login·refresh·logout·me` — JWT + refresh 해시 저장, Web=httpOnly 쿠키 / Native=본문 분기
- [x] `/teams`, `/teams/{id}/members·leave`, 초대(이메일은 발송 없이 토큰만이라도), 팀장 승계 트랜잭션 (db-schema §7.2) — `teams.py`(members·leave·승계)·`invites.py`(이메일/링크·accept/decline) 완료
- [x] 파일 스토리지 결정(로컬 디스크 + 서명 URL 흉내도 가능) — `storage_key` 규약 확정 (README A10 확정)

### 팀원3 (AI Pipeline)

- [x] GPU 서버 셋업: `setup_tts.sh` / `setup_stt.sh` → `test_servers.sh` 왕복 테스트 통과 — 두 서버 가동 확인(STT `/transcribe` 실측·TTS 합성 모두 이 서버로 수행, 2026-07-11)
- [x] 한국어 STT 실측: 5분 오디오 변환 소요시간 기록 (→ 폴링 간격·UX 근거, spec §8) — 실측 완료(2026-07-11): 5분 ~9.7s, RTF≈0.03~0.05. 청크 **60s+4s 겹침** 확정. 표: [infra README](../infra/gpu-server/README.md#stt-실측--청크-크기-결정-day-3-팀원3)
- [x] VoxCPM2 페르소나 voice design — 5종(에겐/테토/꼰대/멍청/잼민) 설계([persona_voices.md](../infra/gpu-server/persona_voices.md)) + **레퍼런스 차단 해소**: `build_persona_voices.sh`가 default 음성 합성 → 피치/템포 변형으로 캐리커처 레퍼런스 자체 생성(외부 자산 0). `voices/refs·profiles·out` 5종 빌드 완료, 사람 레퍼런스 확보 시 refs wav 교체 후 (3)단계만 재실행
- [x] 외부 LLM API 키 발급 + `LLMProvider` 추상화에 실제 제공자 1개 연결 — Gemini 연결 완료(`services/llm/gemini_provider.py`, 질문 생성·꼬리질문 JSON 스키마 강제까지 구현). `factory.py`에서 `LLM_PROVIDER=mock|gemini` 전환, 키는 `backend/.env`

---

## Step 2 — 자료·녹음 파이프라인 (Day 4)

### 팀원2 (Backend Core)

- [x] `/teams/{id}/sessions` CRUD + 세션 상태머신 (`draft → transcribing → …`, `recording_in_progress` 개명 반영)
- [x] `POST /material` 202 → 백그라운드 파싱 잡 → `materials` 갱신 / `retry` / 스캔본 `UNPROCESSABLE_PDF`
- [x] `POST /recording` 202 → STT 잡 큐 (STT 서버가 **직렬 처리**이므로 백엔드에 단순 큐 필수 — infra 제약 2)
- [x] 권한 검사 공통화: 멤버/팀장/owner (`FORBIDDEN_NOT_OWNER` 등) — `deps.py` `require_team_member`·`require_team_leader`(FORBIDDEN_NOT_LEADER) 완료, 세션 owner 가드(`require_session_owner`)는 세션 라우터와 함께 TODO

### 팀원3 (AI Pipeline)

- [x] PDF → `slides.json` 파서 (PyMuPDF, 페이지별 텍스트) — 팀원2의 잡에서 호출할 함수로
  - `backend/app/services/material.py` `parse_pdf_to_slides(bytes|경로) → [{"page":1,"text":"..."}]`
  - 스캔본·암호화·50p 초과 → `UnprocessablePdfError`(→ `UNPROCESSABLE_PDF`), 손상 파일 → `PdfParseError`(→ retry)
  - 동기 함수 — 잡에서 `run_in_executor`로 감쌀 것. `PyMuPDF>=1.25.0` requirements 추가됨
- [x] STT 클라이언트: **5분 청크 분할 + 타임스탬프 오프셋 합산 병합** (ForcedAligner 제약 — 이 스텝 최난도) → [stt-client-workflow.md](ai-pipeline/stt-client-workflow.md)
  - `backend/app/services/stt.py` `transcribe_recording(경로) → [{"start","end","text"}]` (초 float, 문장급)
  - E2E 실측: 2.7분 발표 전사 5.4s(RTF 0.033), 경계 중복 0, CER 0.96%. 팀원2 합류 검증(7단계)만 남음
- [~] `transcripts.segments` JSONB 형식(초 단위 float)으로 저장되는지 팀원2와 함께 검증 — STT 큐 통합으로 저장 경로는 라이브(업로드→`stt_queue`→`transcripts.segments`, 커밋 707797e). 남은 것: `ts:"MM:SS"` 변환 라우터 연결(현재 `SessionDetail`은 `transcript.status`만 노출, `seconds_to_ts`는 아직 라우터 미연결) → stt-client-workflow §7

### 팀원1 (Frontend)

- [x] 발표 준비 화면(04-prep): PDF 업로드 + 전처리 상태 3종 + 페르소나/질의수/제한시간 설정
- [x] 발표중 화면(05-present): 타이머(클라이언트 권위), 로컬 녹음, 종료 시 파일 업로드, STT 로딩/실패 화면 — 청크 파이프라인(60s+4s)까지 구현
- [x] 파일 제약 클라이언트 검증 (20MB/50p, 200MB/60분)

---

## Step 3 — Q&A 루프 (Day 5, 프로젝트의 심장)

### 팀원3 (AI Pipeline)

- [x] 질문 생성 프롬프트: slides+transcript+persona 입력 → `text, persona, strategy, evidence{slides, transcript_refs}` JSON 강제. "슬라이드에 있으나 미언급 / 언급했으나 근거 약함" 타게팅 → 세부 계획·격차: [qna-prompt-workflow.md](ai-pipeline/qna-prompt-workflow.md)
- [x] 꼬리질문 프롬프트: 답변 원문(raw STT — 간투사 포함이니 노이즈 견디게) 입력, 깊이 1 제한, "생성 안 함" 판정 포함 → 동상
  - ✅ 완료(2026-07-13): overlay 단계 A(스키마·시그니처 §4.4 정렬)·B(질문 생성 프롬프트)·C(꼬리질문 프롬프트 + gemini prompt-caching으로 토큰 절약) 구현·커밋. 각 단계 오프라인 검증(persona 라운드로빈·evidence 사후검증·깊이 가드·needed 분기) 통과.
  - 🔜 남음: overlay 단계 **D(회귀 스냅샷 테스트)** + 팀원2 라우터 합류 검증(`POST /qna/generate`→저장→`GET /qna` 필드 일치)
- [x] TTS 연동: 질문 텍스트 → 페르소나 음색 wav (서버는 wav/pcm만 지원 — mp3 아님) — `services/tts.py` 완료(2026-07-13)
  - `synthesize_question(text, persona) → wav bytes`: persona→voice 1:1, **미등록 voice(400) → `default` 자동 폴백**(+프로세스 캐시)
    · 일시 오류(5xx) 백오프 재시도 · 실패 시 `TtsError`(→ `tts_status='failed'`). `list_voices()`로 등록 점검.
  - 검증: 오프라인 9종(`tests/test_tts.py`, MockTransport) + **라이브 E2E 통과** — teto 합성 285KB wav, 미등록 voice 400→default 폴백 실측
  - ✅ 음색 갱신(2026-07-13, voice-design): 캐리커처 → **VoxCPM2 셀프 캐스팅 세트**(팀 청취 픽, 클로닝 출력 실측
    CER 0%·최소 MFCC 거리 137) 배포 완료. 라우트 이력(B-2 moss 폐기 · B-3 edge-tts 미채택 · C 셀프 캐스팅 채택)·
    실측·교체 절차: [persona_voices.md](../infra/gpu-server/persona_voices.md). 사람 레퍼런스(Path A) 확보 시
    refs wav 교체 → 프로파일 재계산 → 재기동으로 품질만 갱신 — voice 이름이 유지되므로 **백엔드 수정 0**
  - 🔜 저장(`storage.tts_key`)·직렬 큐·`tts_status` 갱신은 팀원2 TTS 잡 몫(경계 규칙) — 조립 스니펫은 tts.py docstring에

### 팀원2 (Backend Core)

- [ ] `POST /qna/generate` 202 → 팀원3 서비스 호출 → `questions` 저장 + 질문별 TTS 잡
- [ ] `POST /answer` **202만 반환** → 답변 STT → `answer.status=ready` → 꼬리질문 판정 → `follow_up_status` + 자식 질문 삽입 + `current_question_id` 이동
  - **꼬리질문 persona = 부모 질문 persona (라우터가 승계)**: `follow_up()`이 반환하는 `QuestionDraft.persona`는
    placeholder(`egen` 기본값)다. 팀원3의 서비스는 원 질문의 persona를 인자로 받지 않으므로(시그니처 `follow_up(*, question, answer, depth)`),
    자식 질문 행을 삽입할 때 **부모 질문의 `persona`로 덮어써야** 한다(전략·evidence는 자식 자체 값 사용, evidence는 필요 시 부모 근거 승계 가능).
    안 덮으면 전 꼬리질문이 egen 말투/음성으로 나가는 버그. → 계약: [qna-prompt-workflow.md](ai-pipeline/qna-prompt-workflow.md) C단계
- [ ] `pass`(꼬리 생략), `qna/end`(종료 우선순위 A12), 종료 시 리포트 잡 자동 큐
- [ ] `GET /qna`가 폴링 단일 소스로 spec 예시와 필드 단위 일치하는지 확인

### 팀원1 (Frontend)

- [ ] 질의응답 화면(06-qna): TTS 재생(다시 듣기 = 같은 URL), 재생 완료 → **자동 답변 녹음**, 제한시간/패스
- [ ] 답변 업로드 후 `GET /qna` 폴링 → 꼬리질문 등장/다음 질문 이동/종료 처리
- [ ] 근거 배지(evidence 슬라이드 번호·ts) 표시, 마이크 권한 요청/거부 화면(10-common)

---

## Step 4 — 리포트 + 실물 통합 (Day 6)

### 팀원3 (AI Pipeline)

> 세부 계획·경계·평가 방법: [report-eval-workflow.md](ai-pipeline/report-eval-workflow.md) (숫자=순수 코드 / 판단=LLM 분리)

- [x] 정량 지표는 **순수 코드**로: WPM, 필러 카운트(원문 기준), over_time — LLM에 숫자 계산 시키지 않기 — `services/report.py` `compute_speaking_metrics()` 완료(WPM 필러 제외 기본, 회귀 8케이스 통과)
- [x] 리포트 LLM: 답변별 strategy 채점(`type_scores` 0~1) + `insight` 생성 — `LLMProvider.generate_report()`(base·gemini·mock), 전략별 집계는 코드(`build_type_scores`), mock 스냅샷 6케이스 통과
- [x] 프롬프트 회귀 테스트용 고정 입력(샘플 세션 1개) 저장 — `tests/fixtures/report_sample_session.json` + `test_report_fixture.py`(A+B 통합 스냅샷) 통과

### 팀원2 (Backend Core)

- [ ] `GET /report`, `POST /report/generate`, `GET /users/me/report/growth` (db-schema §8.1 쿼리 그대로)
- [ ] 세션 삭제 cascade + 스토리지 파일 삭제 (커밋 후 삭제, db-schema §7.3)
- [ ] KCLOUD VM 배포 + 터널(허용 포트 주의 — 루트 README 표 참고), GPU 서버와 사설망 연결 확인

### 팀원1 (Frontend)

- [ ] 이전 발표(07-history: 스크립트/Q&A 로그 탭), 리포트(08-report: 강약점·습관·성장 그래프), 마이페이지(09)
- [ ] **Mock-off 전환**: `USE_MOCK=false`로 실서버 대상 전체 플로우 통과
- [ ] 크로스플랫폼 검증: Web + 모바일(에뮬레이터/실기기) 최소 2개 타깃에서 핵심 루프 동작

### 전원 (통합 데이)

- [ ] 실제 PDF + 실제 발표 녹음으로 E2E 1회: 업로드→질문→음성 티키타카→리포트까지 논스톱
- [ ] 실패 지점 목록화 → Day 7 백로그

---

## Step 5 — 안정화 + 시연 준비 (Day 7)

- [ ] (전원) 에러/재시도 UX: STT 실패 재시도, TTS failed, 이어하기(세션 상태 재조회)
- [ ] (팀원1) 로딩·폴링 중 UX 다듬기 (질문 생성 대기, TTS 대기가 체감 지연 최대 지점)
- [ ] (팀원2) 시드 데이터 + 데모 계정 준비, 레이트리밋 최소 방어
- [ ] (팀원3) 시연용 발표자료·녹음 리허설 — STT/TTS 실측 지연 기준으로 시연 대본 타이밍 설계
- [ ] (전원) **루트 README 빈칸 채우기**: 핵심 구현 요소, 아키텍처 다이어그램, 구현 명세서, 기술 구성, 실행 방법 — 과제 제출물 자체이므로 필수. backend/frontend README도 구버전(Gemini·Team/Speech 기준)이라 현행화 필요
- [ ] 시연 영상 녹화

---

## 리스크 & 미리 정할 것

| 항목 | 내용 | 액션 |
|---|---|---|
| STT 직렬 처리 | 발표 전사(수 분) 중 답변 전사가 대기 | 시연은 "발표 전사 완료 후 Q&A 시작" 순서라 실제로는 OK. 데모 중 재업로드가 겹치지 않게 주의 |
| api-spec §0.2 가정값 (A1~A13) | 문서상 "확정 필요" 상태 | Step 1 시작 전 30분 회의로 전부 확정하고 spec의 ⚠️ 표시 제거. WPM 필러 제외 여부(db-schema §9)도 이때 결정 |
| 실존 인물 목소리 클로닝 (Qwen3-TTS) | 2-모델 TTS 계획은 현재 infra 문서에 없음 (VoxCPM2 단일) | v0.3 구성(상주 모델 2개)에 맞춰 **스트레치 골**로 유지 |
| 이메일 발송 / 소셜 OAuth | 외부 의존이 커서 마지막 날 발목 잡기 쉬움 | 초반에 "선택" 확정하고 mock 유지 |
