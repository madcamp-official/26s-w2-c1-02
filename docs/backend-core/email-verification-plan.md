# 이메일 인증 — 팀원2 Backend Core + 팀원1 Frontend 상세 작업 계획

> 기준 문서: [api-spec.md](../api-spec.md) §2(auth)·§6.2(에러) · [db-schema.md](../db-schema.md) §3.1(users·email_verifications) · [workflow.md](../workflow.md) 공통 가이드라인 2(Mock으로 병렬화)
> 대상: **회원가입 이메일 인증(로그인 강제)** — `POST /auth/email/verify-request`, `POST /auth/email/verify` 신규 + `POST /auth/signup`에 코드 발송 추가 + `POST /auth/login`에 미인증 차단 추가 + **팀 초대 초대코드 통일**(§11).
> 작성일: 2026-07-14 · 상태: **설계 확정, 구현 전**

---

## 팀 결정 사항 (2026-07-14 확정)

| 항목 | 결정 |
|---|---|
| 발송 수단 | **Gmail SMTP** (앱 비밀번호). 단, 기본은 mock 모드 — SMTP 없이 전체 개발·테스트 가능 |
| 미인증 유저 차단 지점 | **로그인 자체 차단** — 미인증 유저의 `POST /auth/login`은 403 `EMAIL_NOT_VERIFIED`. 가입 → 인증 → 로그인이 필수 순서가 된다. **기존 가입자 전원이 미인증이므로 배포 시 일괄 인증 처리(§7-2) 필수** — 안 하면 전원 잠긴다 |
| 초대 UX | 이메일 초대는 스코프 컷 유지(발송 없음, 프론트 미사용). 팀 초대는 **초대코드**로 통일 — 이 문서 §11에서 함께 다룬다 |

---

## 0. 시작 전 — 이미 있는 재사용 자산 (새로 만들지 말 것)

이 기능도 "부품 조립"이다. **DB 마이그레이션 불필요** — 테이블·컬럼이 001부터 준비돼 있다.

| 부품 | 위치 | 인터페이스 | 비고 |
|---|---|---|---|
| 인증코드 테이블 | `app/db/models.py` `EmailVerification` | `id(emv_) · user_id FK · code_hash · expires_at · consumed_at · attempt_count · created_at` | **attempt_count까지 이미 있음** — 시도 제한용 |
| 코드 해시·대조 | `app/core/security.py` | `hash_password(plain)` / `verify_password(plain, hash)` | 비밀번호용 bcrypt를 인증코드에 재사용 (평문 저장 금지) |
| 설정 로드 | `app/core/config.py` `Settings` | pydantic-settings, `.env` 자동 로드 | `llm_provider` 패턴 복제 |
| 에러 포맷 | `app/core/errors.py` | `ApiError(status, code, message)` | 에러 코드는 §6.2 표에 맞춤 |
| provider 전환 관례 | `services/llm/factory.py` | `LLM_PROVIDER=mock\|gemini` | `EMAIL_PROVIDER=mock\|smtp`로 동일 패턴 |
| 테스트 mock 고정 | `tests/conftest.py` | `os.environ.setdefault("LLM_PROVIDER", "mock")` | `EMAIL_PROVIDER` 한 줄 추가 |
| 백그라운드 실행 | FastAPI `BackgroundTasks` | 라우트 파라미터로 주입 | SMTP 지연(수 초)이 응답을 막지 않게 |

> **api-spec은 이미 이 기능을 예약해뒀다** (§2: `/auth/email/verify-request`·`/auth/email/verify`, §6.2: `EMAIL_NOT_VERIFIED`). 계약 변경 없이 구현만 하면 된다. 계약 우선 원칙 위반 아님.

---

## 작업 1. 설정 (`app/core/config.py`)

`Settings`에 5개 필드 추가. 기본값 `mock`이라 아무 설정 없어도 기존 동작 무영향.

```python
# 이메일 발송: mock(발송 대신 로그에 코드 출력) | smtp(실발송)
email_provider: str = "mock"
smtp_host: str = "smtp.gmail.com"
smtp_port: int = 587            # STARTTLS
smtp_user: str = ""             # 보내는 gmail 주소
smtp_password: str = ""         # gmail 앱 비밀번호 — .env에만, 커밋 금지
```

`.env.example`에도 주석과 함께 추가할 것 (JWT_SECRET 안내와 같은 톤으로 "커밋 금지" 명시).

---

## 작업 2. 발송 서비스 (`app/services/email.py` 신규)

표준 라이브러리 `smtplib`만 사용 — **requirements 추가 0**.

```python
class EmailSendError(Exception): ...

def send_verification_email(to_email: str, code: str) -> None:
    """인증코드 메일 발송. mock 모드는 로그로 대체. 실패 시 EmailSendError."""
```

- `mock`: `logger.info("[MOCK 메일] to=%s code=%s", ...)` 후 즉시 반환. 개발 중엔 서버 로그(tmux)에서 코드를 읽어 인증한다.
- `smtp`: `MIMEText` 본문("Rehearsal.io 인증코드: {code}\n10분 안에 입력해주세요.") → `SMTP(host, port, timeout=10)` → `starttls()` → `login()` → `send_message()`.
- 예외는 `EmailSendError`로 감싼다. **호출부는 BackgroundTasks라 예외가 응답에 영향 없음** — 로그만 남기고 유저는 "재발송"으로 복구.

> tts.py의 폴백·에러 래핑 스타일(`TtsError`)과 동일한 결로 작성.

---

## 작업 3. 스키마 (`app/schemas/auth.py`에 추가)

```python
class VerifyRequestBody(BaseModel):
    email: EmailStr

class VerifyBody(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
```

- 형식 위반(5자리, 문자 포함 등)은 Pydantic 단계에서 422 — 라우트까지 안 온다.

---

## 작업 4. 코드 발급·검증 헬퍼 (auth 라우트 파일 내부 함수 or `services/email_verification.py`)

### 4-1. 발급 `issue_verification_code(db, user) -> str`

```
1. 해당 유저의 유효 코드 전부 무효화:
   UPDATE email_verifications SET consumed_at = now()
   WHERE user_id = :uid AND consumed_at IS NULL
   → 재발송 후 옛 코드로 인증되는 구멍 차단
2. code = f"{secrets.randbelow(1_000_000):06d}"   ← CSPRNG. random 모듈 금지
3. INSERT EmailVerification(user_id, code_hash=hash_password(code),
                            expires_at=now()+10분)
4. return code   ← 평문은 메일로만 나감. DB엔 해시만. 응답에도 절대 노출 금지
```

### 4-2. TTL·제한 상수

| 상수 | 값 | 근거 |
|---|---|---|
| `CODE_TTL` | 10분 | 메일 지연 감안 + 방치된 코드 최소화 |
| `MAX_ATTEMPTS` | 5회 | 6자리 숫자(100만 경우) ÷ 5회 = 무차별 대입 기대성공률 0.0005% |
| `RESEND_COOLDOWN` | 60초 | 발송 스팸·SMTP 쿼터(Gmail 일 500통) 보호 |

---

## 작업 5. 라우트 (`app/api/routes/auth.py`)

### 5-1. `POST /auth/email/verify-request` → 204

```
1. email로 유저 조회.
   ├─ 없음 → 그래도 204  ← 계정 열거(enumeration) 방지. 절대 404 내지 말 것
   └─ 이미 인증됨 → 그래도 204 (멱등·정보 비노출)
2. 쿨다운: 최신 코드 created_at이 60초 이내 → 429 RATE_LIMITED
   (§6.2 표의 기존 429 코드 재사용, Retry-After 헤더 포함)
3. issue_verification_code() → background_tasks.add_task(send_verification_email, ...)
4. 204 No Content
```

### 5-2. `POST /auth/email/verify` → 200

```
1. email로 유저 조회 — 없으면 400 INVALID_CODE (여기도 존재 여부 숨김)
2. user.email_verified_at 있음 → 200 {"email_verified": true} (멱등)
3. 최신 유효 코드 조회: consumed_at IS NULL AND expires_at > now()
   ORDER BY created_at DESC LIMIT 1
   └─ 없음 → 400 CODE_EXPIRED ("만료됐어요. 재발송해주세요")
4. row.attempt_count >= 5 → 400 CODE_EXPIRED (코드 소진 취급)
5. verify_password(body.code, row.code_hash)
   └─ 불일치 → row.attempt_count += 1; commit → 400 INVALID_CODE
6. 일치 → row.consumed_at = now(); user.email_verified_at = now(); commit
   → 200 {"email_verified": true}
```

> **4·5 순서 주의**: attempt 검사를 대조보다 먼저. 아니면 5회 초과 후에도 계속 대조 시도를 허용하게 된다.

### 5-3. `POST /auth/signup` 수정 (2줄)

기존 유저 생성 commit 후:

```python
code = issue_verification_code(db, user)
background_tasks.add_task(send_verification_email, user.email, code)
```

- 시그니처에 `background_tasks: BackgroundTasks` 추가.
- **발송 실패해도 가입은 성공** — 응답을 바꾸지 않는다. spec §2의 "미인증 유저 생성 + 인증코드 발송" 그대로.

### 5-4. `POST /auth/login` 수정 — 미인증 로그인 차단

비밀번호 대조 **성공 후**에 인증 여부를 검사한다:

```python
if user.email_verified_at is None:
    raise ApiError(403, "EMAIL_NOT_VERIFIED", "이메일 인증을 완료해주세요.")
```

- **순서 중요**: 비밀번호가 틀리면 기존대로 401. 403은 "비밀번호는 맞는데 미인증"일 때만 —
  이래야 프론트가 403을 받고 곧바로 코드 입력 화면으로 보낼 수 있다(비밀번호 재입력 불필요).
- 검사 위치는 login **한 곳뿐**. refresh는 로그인을 통과한 유저만 도달하므로 추가 검사 불필요.
  (단, 이미 로그인돼 있던 기존 세션은 차단되지 않는다 — §7-2 일괄 처리로 실질 영향 없음)
- 소셜 로그인(`/auth/login/{provider}`)은 스코프 컷 상태라 이번 범위 밖.

### 5-5. 에러 코드 (§6.2 정합)

| HTTP | code | 상황 |
|---|---|---|
| 400 | `INVALID_CODE` | 코드 불일치 / (verify에서) 유저 없음 |
| 400 | `CODE_EXPIRED` | 유효 코드 없음·만료·5회 소진 |
| 403 | `EMAIL_NOT_VERIFIED` | 미인증 유저의 로그인 시도 (§6.2에 이미 있음) |
| 429 | `RATE_LIMITED` | 재발송 60초 쿨다운 |

> `INVALID_CODE`·`CODE_EXPIRED`는 §6.2 표에 아직 없음 → **api-spec에 두 줄 추가 필요 (계약 우선: 구현 전에 spec 먼저 갱신 + 팀 합의)**. login의 403 응답도 §2 표의 login 행에 명시할 것.

---

## 작업 6. 테스트 (`tests/test_email_verify.py` 신규)

관례 준수: `TestClient(app)` + 실DB + 접두사(`emv_test_%`) 유저 생성·정리, `conftest.py`에 `EMAIL_PROVIDER=mock` 고정 추가.

| # | 케이스 | 기대 |
|---|---|---|
| 1 | 가입 → email_verifications row 생성 | code_hash는 평문 코드와 다름(해시 확인) |
| 2 | 올바른 코드 verify | 200 + `users.email_verified_at` 설정 + `consumed_at` 설정 |
| 3 | 틀린 코드 | 400 INVALID_CODE + attempt_count 1 증가 |
| 4 | 5회 실패 후 맞는 코드 | 400 CODE_EXPIRED (거부) |
| 5 | 만료 코드 (expires_at 과거로 직접 UPDATE) | 400 CODE_EXPIRED |
| 6 | 재발송 → 옛 코드로 verify | 400 (무효화 확인) + 새 코드는 성공 |
| 7 | verify-request: 없는 이메일 | 204 (열거 방지) |
| 8 | verify-request: 60초 내 재요청 | 429 |
| 9 | 이미 인증된 유저 verify | 200 멱등 |
| 10 | verify-request: 이미 인증된 유저 | 204 (발송 안 함) |
| 11 | **미인증 유저 로그인** | **403 EMAIL_NOT_VERIFIED** |
| 12 | **인증 완료 후 로그인** | **200 + 토큰 발급 (기존과 동일)** |
| 13 | 미인증 + 비밀번호도 틀림 | 401 (403보다 비밀번호 검사가 먼저) |

> ⚠️ **기존 테스트 전면 수정 필요**: 현재 모든 테스트가 `signup → login` 2단계로 유저를 만든다
> (`_mkuser` 헬퍼 등). 로그인 차단이 들어가면 **전부 깨진다** — 헬퍼에 "가입 직후 DB에서
> `email_verified_at` 직접 설정" 한 줄을 추가해 signup→verify→login 3단계를 우회시킬 것.
> 헬퍼가 파일마다 복붙돼 있으므로 conftest로 공용화하는 김에 정리 권장.

mock 모드에서 코드 평문을 얻는 법: `issue_verification_code`를 monkeypatch로 캡처하거나, 테스트에서 직접 호출해 반환값 사용 (기존 `mock_stt` monkeypatch 스타일).

---

## 작업 7. Gmail 준비 + 배포 반영 (팀원2, 코드 완성 후)

### 7-1. Gmail 앱 비밀번호

1. Google 계정 → 보안 → **2단계 인증** 켜기 (앱 비밀번호의 전제조건)
2. 보안 → "앱 비밀번호" 검색 → 생성 → 16자리 복사
3. **VM** `backend/.env`에 추가 (커밋 금지 — .env는 gitignore):
   ```
   EMAIL_PROVIDER=smtp
   SMTP_USER=<발신 gmail>
   SMTP_PASSWORD=<앱 비밀번호 16자리>
   ```
4. 서버 재시작(tmux) → 실계정으로 가입해 수신 확인 (스팸함도 확인)
5. 한도: Gmail 일 500통 — 캠프 규모에선 충분. 초과 시 발송 실패 → mock 전환으로 임시 대응

> 로컬 개발·CI·테스트는 계속 `EMAIL_PROVIDER=mock`(기본값). smtp는 **배포 VM에서만** 켠다.

### 7-2. 기존 유저 일괄 인증 처리 — **배포와 반드시 한 세트** ⚠️

로그인 차단이 켜진 코드가 배포되는 순간, `email_verified_at IS NULL`인 유저는 **전부 로그인 불가**가 된다.
현재 배포 DB의 가입자 전원(데모·E2E 계정 포함)이 미인증이므로, **신 코드 배포 직전에** 아래를 실행한다:

```sql
-- 배포 DB에서 1회 실행 (migrations/README.md의 002 절차와 같은 요령)
UPDATE users SET email_verified_at = now()
WHERE email_verified_at IS NULL AND deleted_at IS NULL;
```

- 근거: 기존 유저는 인증 기능이 없던 시절의 가입자다. 소급 잠금은 부당하고, 특히
  `e2e_*@rehearsal.io`·`demo@rehearsal.io`는 **실재하지 않는 메일 주소라 영원히 인증 불가**.
- 순서: **SQL 먼저 → 신 코드 배포** (002 마이그레이션의 "미리 적용해도 안전" 원칙과 동일 —
  구 코드는 `email_verified_at`을 읽지 않으므로 먼저 UPDATE해도 무해).
- 이후 시드/E2E 계정을 새로 만들 땐 생성 스크립트에서 `email_verified_at`을 함께 넣을 것.

---

## 8. 프론트 작업 (팀원1) — 화면·상태·에러 처리

### 8-1. 가입 화면 (`signup_page.dart`) 개편

현재: "인증요청" 버튼 = mock 스낵바("이메일 발송은 추후 연동"). 이를 실제 플로우로 교체.

```
[가입 폼] --가입 201--> [인증코드 입력 화면] --verify 200--> [로그인 화면 (또는 자동 로그인)]
                             │ 재발송 (60초 쿨다운)
                             ✗ "나중에 하기" 없음 — 인증 없이는 로그인이 403이므로 필수 단계
```

- 가입 폼에서 별도 "인증요청" 버튼 **제거** — signup 자체가 코드를 발송하므로 불필요.
- 가입 201 응답 후 자동으로 코드 입력 화면 전환. 이메일 주소를 화면에 표시("aa@gmail.com로 코드를 보냈어요").
- verify 200 후: 로그인 화면으로 보내며 "인증 완료! 로그인해주세요" 안내.
  (UX를 더 매끄럽게 하려면 가입 폼의 비밀번호를 메모리에 들고 있다가 verify 200 직후
  자동 `POST /auth/login` — 선택 사항, 팀원1 재량)

### 8-2. 인증코드 입력 화면 (신규)

| 요소 | 동작 |
|---|---|
| 6자리 입력 | 숫자 키패드, 6자리 채우면 자동 제출 권장 |
| 제출 | `POST /auth/email/verify {email, code}` |
| 재발송 버튼 | `POST /auth/email/verify-request {email}` → 성공 시 60초 카운트다운 표시, 카운트다운 중 비활성 |
| 진입 경로 | ① 가입 직후 자동 진입 ② **로그인 403 시 리다이렉트** (8-4) — 두 경로 모두 email을 파라미터로 받는다 |

### 8-3. 에러 → 사용자 문구 매핑

| 응답 | 문구 | UI 동작 |
|---|---|---|
| 400 `INVALID_CODE` | "코드가 올바르지 않아요" | 입력 초기화 + 흔들림 등 피드백 |
| 400 `CODE_EXPIRED` | "코드가 만료됐어요. 재발송해주세요" | 재발송 버튼 강조 |
| 403 `EMAIL_NOT_VERIFIED` (로그인 시) | "이메일 인증이 필요해요" | **코드 입력 화면으로 이동** (8-4) |
| 429 `RATE_LIMITED` | "잠시 후 다시 시도해주세요" | Retry-After 초 만큼 재발송 비활성 |
| 네트워크 오류 | 공통 재시도 UX | 기존 패턴 |

### 8-4. 로그인 403 처리 (핵심 신규 흐름)

로그인 차단 확정에 따라 **로그인 화면에 403 분기가 필수**다:

```
POST /auth/login
 ├─ 200 → 기존대로 홈
 ├─ 401 → "아이디 또는 비밀번호가 올바르지 않아요" (기존)
 └─ 403 EMAIL_NOT_VERIFIED → 코드 입력 화면으로 이동(입력한 email 전달)
        + 진입 시 자동으로 verify-request 1회 호출해 새 코드 발송해주면 UX 최상
        (가입 직후 코드는 10분 만료라, 나중에 로그인하는 유저는 새 코드가 필요)
```

- `GET /auth/me`의 `email_verified: bool`은 이미 내려가고 있음(`UserOut`) — 마이페이지 배지 등 보조 표시에 사용 가능하나, 강제 흐름의 주 신호는 **로그인 403**이다.

### 8-5. Mock 개발 순서 (백엔드 완성 전에 시작 가능)

`MockBackend`에 추가: verify-request → 항상 204, verify → 코드 `"000000"`만 성공, **login → 미인증 mock 유저면 403** (미인증 상태의 mock 유저 1명 추가). 백엔드 merge 후 mock-off로 전환 검증 — workflow 공통 가이드라인 2 그대로.

---

## 9. 계약 요약 (프론트·백 공용 — 이 표가 인터페이스의 전부)

| 메서드 | 경로 | 인증 | 요청 | 성공 | 실패 |
|---|---|---|---|---|---|
| POST | `/auth/signup` | ✗ | (기존과 동일) | 201 (기존과 동일) + **메일 발송 부수효과** | (기존과 동일) |
| POST | `/auth/email/verify-request` | ✗ | `{email}` | **204** (유저 없어도·이미 인증돼도) | 429 RATE_LIMITED |
| POST | `/auth/email/verify` | ✗ | `{email, code(6자리 숫자)}` | 200 `{"email_verified": true}` (멱등) | 400 INVALID_CODE · 400 CODE_EXPIRED |
| POST | `/auth/login` | ✗ | (기존과 동일) | 200 (기존과 동일) | 401 (기존) · **403 EMAIL_NOT_VERIFIED (신규)** |

---

## 10. 작업 순서 & 예상 소요

| 순서 | 작업 | 담당 | 예상 |
|---|---|---|---|
| 1 | api-spec 갱신(§6.2 에러 2종 + login 403 + §3.1 초대코드) + 팀 합의 | 팀원2 | 15분 |
| 2 | 작업 1~5 구현 (mock 모드) + 작업 6 테스트(기존 헬퍼 수정 포함) 통과 | 팀원2 | 반나절~하루 |
| 3 | §11-1 초대코드 백엔드 (토큰 생성 교체) | 팀원2 | 1시간 |
| 4 | 8-5 Mock 개발 → 8-1~8-4 화면 + §11-2 초대코드 UI | 팀원1 | 반나절~하루 (2·3과 병렬) |
| 5 | mock-off 통합 확인 (개발 환경) | 둘 다 | 30분 |
| 6 | **§7-2 기존 유저 일괄 인증 SQL (배포 DB)** → 신 코드 배포 | 팀원2 | 15분 |
| 7 | 작업 7-1 Gmail 연동 + 실메일 수신 확인 | 팀원2 | 1시간 |

## 리스크

| 리스크 | 대응 |
|---|---|
| **메일 발송 장애 = 신규 가입자 전원 로그인 불가** (로그인 차단의 대가) | ① 시연 계정은 사전 가입·인증 완료해 둘 것 ② 발송 장애 시 임시 우회: VM에서 `UPDATE users SET email_verified_at=now() WHERE email=...` 수동 인증 ③ 최악엔 `EMAIL_PROVIDER=mock`으로 내리고 서버 로그에서 코드 읽어 전달 |
| Gmail 발송 지연·스팸함 분류 | 발송은 BackgroundTasks(응답 무영향) + 재발송 버튼 + "스팸함을 확인해주세요" 문구 |
| §7-2를 빼먹고 배포 | **기존 유저 전원 잠김.** migrations/README의 002처럼 "신 코드 라이브 + SQL 미적용 상태가 한순간도 없게" — 배포 체크리스트에 포함할 것 |
| 기존 테스트 전면 파손 (signup→login 헬퍼) | 작업 6의 헬퍼 수정을 구현과 같은 커밋에서 처리 — 테스트 초록 확인 후 merge |
| SMTP 계정 정보 유출 | `.env`에만 저장(gitignore 확인됨), 채팅·커밋 금지 — JWT_SECRET과 동일 규율 |
| workflow.md의 "이메일은 마지막 날 발목" 경고 | mock 기본값 유지로 헤지 + 위 임시 우회 3종 문서화로 대응 |

---

## 11. 초대코드 통일 (같은 결정 묶음이라 이 문서에서 함께 관리)

### 11-1. 백엔드 (팀원2) — 변경 최소

기존 **링크 초대**(`team_invite_links`)를 그대로 "초대코드"로 재해석한다. 의미론이 이미 일치:
팀당 활성 1개 · 재생성 시 이전 무효 · `GET /invites/{token}` 미리보기 → accept/decline.

| 변경 | 내용 |
|---|---|
| 토큰 생성 | `secrets.token_urlsafe(32)`(43자) → **8자 코드** (대문자+숫자, 혼동 문자 `I O 0 1` 제외한 32자 알파벳). `''.join(secrets.choice(ALPHABET) for _ in range(8))` |
| 충돌 방어 | token 유니크 제약 위반 시 재생성 재시도 (32^8 ≈ 1.1조 — 실충돌 확률 무시 가능하나 방어적으로) |
| 엔드포인트 | **변경 없음** — 응답의 `token`이 짧아질 뿐. `url` 필드도 유지(웹 딥링크 겸용) |
| 기존 발급분 | 긴 토큰 링크도 계속 유효 (검증 로직은 문자열 대조라 길이 무관) — 마이그레이션 불필요 |
| 이메일 초대 | `/teams/{id}/invites`(email) 코드는 존치하되 프론트 미사용 — api-spec §3.1에 "미사용(스코프 컷)" 표기 |

보안 노트: 8자(1.1조 경우) + 만료 7일 + 팀당 1개 + 기존 레이트리밋 → 무차별 대입 비현실적. **6자로 줄이지 말 것**(3만 배 약해짐).

### 11-2. 프론트 (팀원1)

| 화면 | 변경 |
|---|---|
| 팀 생성 (`create_team_page.dart`) | **이메일 입력 UI 제거**. 생성 완료 화면에 초대코드 큼직하게 표시 + 복사 버튼 (`POST /teams/{id}/invites/link` 호출 → `token` 표시) |
| 팀 상세 (`team_detail_page.dart`) | "팀원 초대하기" = 링크 복사 → **코드 표시 + 복사**로 교체 (같은 API, 표시만 변경) |
| 홈/팀 목록 | **"초대코드로 참여" 입력창 신규** — 8자 입력 → `GET /invites/{code}` 미리보기(팀명·인원) → 수락(`POST /invites/{code}/accept`). 기존 `invite_accept_page.dart` 재사용 (경로 파라미터로 코드 전달) |
| 에러 | 404 → "존재하지 않는 코드예요" · 만료 → "만료된 코드예요. 팀장에게 새 코드를 요청하세요" |
