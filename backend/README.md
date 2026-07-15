# Rehearsal.io — Backend (FastAPI)

AI 청중과 음성으로 발표를 리허설하는 서비스의 API 서버.
인증(JWT)·팀·세션 관리부터 자료 파싱, 녹음 청크 STT, LLM 질문·꼬리질문 생성, 질문 TTS, 분석 리포트까지 전체 파이프라인을 담당한다.

| 분류 | 기술 |
|---|---|
| 프레임워크 | FastAPI + Uvicorn (Python 3.10+) |
| DB | PostgreSQL 16 (SQLAlchemy 2 + psycopg3) — 테이블 18개, [docs/db-schema.md](../docs/db-schema.md) |
| 인증 | JWT (access 15분 / refresh 14일 회전), bcrypt, 이메일 인증(SMTP), 아이디 찾기·비밀번호 재설정 |
| LLM | Google Gemini (`google-genai`, 기본 `gemini-flash-latest`) — `LLMProvider` 추상화 뒤에서 mock ↔ gemini 전환 |
| 음성 | GPU 서버 연동 — STT `:8200 /transcribe`(Qwen3-ASR + ForcedAligner), TTS `:8100 /v1/audio/speech`(VoxCPM2) |
| 자료 파싱 | PyMuPDF(PDF)·python-pptx(PPTX) → 페이지별 텍스트(slides JSONB) |
| 파일 저장 | VM 로컬 디스크 + HMAC 서명 URL (`GET /files/{key}?expires=&sig=`) |

## 실행 방법

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 1) DB 준비 — PostgreSQL 16에 마이그레이션을 번호 순서대로 적용 (자동 러너 없음)
psql -U rehearsal -h localhost -d rehearsal_dev -v ON_ERROR_STOP=1 -f migrations/001_init.sql
psql -U rehearsal -h localhost -d rehearsal_dev -v ON_ERROR_STOP=1 -f migrations/002_recording_chunks.sql
psql -U rehearsal -h localhost -d rehearsal_dev -v ON_ERROR_STOP=1 -f migrations/003_password_resets.sql

# 2) 환경변수
cp .env.example .env   # DATABASE_URL·JWT_SECRET 등 채우기 (아래 표 참고)

# 3) 서버
uvicorn app.main:app --reload --port 8000
```

- API 문서(Swagger): http://localhost:8000/docs
- 헬스체크: http://localhost:8000/health (LLM 제공자 표시) · http://localhost:8000/health/db (DB 연결·테이블 수)

### 환경변수 (.env)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | localhost:5432/rehearsal_dev | PostgreSQL 접속 URL (`postgresql+psycopg://…`) |
| `JWT_SECRET` | (개발용 임시값) | **반드시 각자 생성** — `python -c "import secrets; print(secrets.token_hex(32))"` |
| `EMAIL_PROVIDER` | `mock` | `mock`=발송 대신 서버 로그에 인증코드 출력(로컬·CI) / `smtp`=Gmail 실발송(배포 VM만) |
| `SMTP_USER` / `SMTP_PASSWORD` | — | `smtp`일 때 보내는 gmail 주소 / 앱 비밀번호 (커밋 금지) |
| `LLM_PROVIDER` | `mock` | `mock`=결정론적 더미 질문·리포트 / `gemini`=실 API |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — / `gemini-flash-latest` | 버전 고정 금지 — 게이팅되면 404로 전면 실패한 전례 있음 |
| `STORAGE_DIR` | `storage` | 업로드 파일 저장 디렉터리 (상대경로면 backend/ 기준) |

> mock 모드 조합(`EMAIL_PROVIDER=mock` + `LLM_PROVIDER=mock`)이면 **SMTP·Gemini·GPU 서버 없이** 전체 API가 동작한다 (STT/TTS 호출 잡만 실패로 흡수됨).

### 데모 시드

```bash
.venv/bin/python -m scripts.seed_demo
```

계정 `demo / demo-pass-1234` + 완료 세션 4개(성장 리포트 상승 곡선, failed 리포트 "다시 생성" 시연 포함)를 만든다. 재실행하면 기존 데모 데이터를 지우고 다시 만든다(멱등). GPU 서버 없이 리포트·성장 리포트 화면을 바로 볼 수 있다.

## 구조

```
app/
├── main.py              # 엔트리포인트 — 라우터 마운트, CORS, 에러 핸들러, 재시작 잡 복구(lifespan)
├── core/
│   ├── config.py        # 환경설정 (.env, pydantic-settings)
│   ├── security.py      # JWT 발급/검증, bcrypt
│   ├── storage.py       # 로컬 디스크 저장 + HMAC 서명 URL (S3 presigned 흉내)
│   ├── errors.py        # ApiError → api-spec §1.1 에러 JSON 변환
│   └── ids.py           # prefix + base62 ID 생성 (usr_, ses_, q_ …)
├── db/
│   ├── models.py        # SQLAlchemy 모델 18개 (migrations/*.sql과 1:1)
│   ├── enums.py         # ENUM 12종
│   └── session.py       # 엔진·SessionLocal·get_db
├── schemas/             # Pydantic 요청/응답 모델 (api-spec 계약)
├── api/
│   ├── deps.py          # 인증·권한 가드 (get_current_user, require_team_member/leader, require_session_member/owner)
│   └── routes/          # auth · users · teams · invites · sessions · materials · recordings · qna · reports · files
└── services/
    ├── llm/             # LLMProvider 추상화 — mock_provider / gemini_provider / factory
    ├── stt.py           # 업로드 녹음 청크 분할(60s+4s) + 직렬 전사 + 오프셋 병합
    ├── stt_queue.py     # 단일 워커 스레드 직렬 STT 큐 (발표 전사·답변 전사 공유)
    ├── qna_jobs.py      # 질문 생성 → TTS → 답변 STT → 꼬리질문 판정 백그라운드 잡
    ├── report_jobs.py   # 리포트 잡 (정량=코드, 정성=LLM)
    ├── report.py        # WPM(필러 제외)·필러워드 정량 지표
    ├── material.py      # PDF·PPTX → slides.json 파서
    ├── session_state.py # 세션 상태머신 (허용 외 전이 = 409)
    ├── tts.py           # GPU TTS 클라이언트 (페르소나 voice 매핑, 실패 시 default 폴백)
    ├── email.py / email_verification.py / password_reset.py
    └── team_membership.py / storage_cleanup.py
```

## 설계 원칙

- **비동기 = `202` + 폴링**: 자료 파싱·STT·질문 생성·TTS·리포트 등 무거운 작업은 즉시 202로 접수하고, 클라이언트가 상태(`queued|processing|ready|failed`)를 폴링한다. ([docs/api-spec.md](../docs/api-spec.md) §1.2)
- **직렬 STT 큐**: GPU STT 서버는 한 번에 하나만 처리하므로, 백엔드의 단일 워커 스레드가 발표 전사와 답변 전사를 같은 큐에서 하나씩 처리한다.
- **재시작 잡 복구**: 서버가 재시작되면 lifespan에서 미완료 STT·리포트·자료 파싱·TTS 잡을 자동으로 다시 큐에 넣는다 — 인메모리 큐가 비어도 FE가 무한 대기에 갇히지 않는다.
- **세션 상태머신**: `draft → recording_in_progress → transcribing → generating_questions → qna → completed` (+ `failed` → retry). 허용되지 않은 전이는 409로 차단.
- **권한 가드**: 비멤버에게는 팀/세션 존재 자체를 숨긴다(403 대신 404). 팀장·발표자(owner) 전용 작업은 403 + 코드 문자열로 구분.
- **에러 계약**: 모든 오류는 `{"error": {"code", "message"}}` 형식 — FE 인터셉터가 `TOKEN_EXPIRED` 코드로 자동 refresh를 판단한다.
- **파일은 DB 밖**: DB에는 `storage_key`만 저장, 재생 URL은 요청 시 만료시각+HMAC 서명을 붙여 발급.

## 주요 엔드포인트 (Base URL `/api/v1`)

전체 계약은 [docs/api-spec.md](../docs/api-spec.md) 참고. 표기: `†` = 202 접수 후 폴링.

| 도메인 | 엔드포인트 |
|---|---|
| 인증 | `POST /auth/signup·login·refresh·logout`, `GET /auth/me` |
| 이메일 인증 | `POST /auth/email/verify-request`, `POST /auth/email/verify` (미인증 유저는 로그인 403) |
| 계정 찾기 | `POST /auth/username/find`, `POST /auth/password/reset-request`, `POST /auth/password/reset` |
| 내 계정 | `GET·PATCH /users/me`, `PATCH /users/me/password`, `DELETE /users/me` (탈퇴=익명화) |
| 팀 | `GET·POST /teams`, `GET·PATCH·DELETE /teams/{id}`, `POST /teams/{id}/leave` (팀장 자동 승계), `GET /teams/{id}/members`, `DELETE /teams/{id}/members/{uid}` |
| 초대 | `POST·GET /teams/{id}/invites` (이메일), `POST·GET·DELETE /teams/{id}/invites/link`, `GET /invites/{token}` (미리보기, 인증 불필요), `POST /invites/{token}/accept·decline` |
| 세션 | `GET·POST /teams/{id}/sessions`, `GET·PATCH·DELETE /sessions/{id}` |
| 자료 | `POST /sessions/{id}/material`† (PDF·PPTX ≤20MB·50p), `GET …/material`, `POST …/material/retry`†, `DELETE …/material` |
| 녹음 | `POST /sessions/{id}/recording/start`, `POST …/recording/chunks` (60s+4s 겹침, seq 멱등), `POST …/recording/complete`†, `POST …/recording`† (파일 일괄 업로드 ≤200MB·60분) |
| 전사 | `GET /sessions/{id}/transcript`, `POST …/transcript/retry`† |
| Q&A | `POST /sessions/{id}/qna/generate`†, `GET …/qna`, `GET …/qna/questions/{qid}`, `POST …/questions/{qid}/answer`† (답변 STT→꼬리질문), `POST …/questions/{qid}/pass`, `POST …/qna/end` |
| 리포트 | `GET /sessions/{id}/report`, `POST …/report/generate`†, `GET /users/me/report/growth?range=all|recent5&team_id=` |
| 파일 | `GET /files/{key}?expires=&sig=` (서명 URL 다운로드) |
| 기타 | `POST /auth/login/{provider}` — **소셜 로그인 미구현(Mock 응답)**. `/speeches/*`는 초기 스캐폴드 잔재 |

## 테스트

```bash
cd backend
.venv/bin/python -m pytest tests/ -v
```

- 테스트 약 40개 파일. `DATABASE_URL`이 가리키는 **실제 PostgreSQL**(마이그레이션 적용됨)을 사용한다.
- conftest가 `LLM_PROVIDER`·`EMAIL_PROVIDER`를 `mock`으로 고정하므로 실 API·SMTP를 때리지 않는다 (셸에서 명시하면 라이브 검수도 가능).

## 마이그레이션 · 배포

- 마이그레이션은 수동 적용(numbered SQL) — 절차·주의사항은 [migrations/README.md](migrations/README.md).
- 배포는 VM에서 systemd 서비스(`rehearsal-backend`, 포트 8000)로 구동하며, 루트의 [update.sh](../update.sh)가 pull → pip install → 재시작 → 헬스체크까지 처리한다. 로그: `journalctl -u rehearsal-backend -f`
