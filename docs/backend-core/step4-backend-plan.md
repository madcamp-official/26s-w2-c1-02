# Step 4 (Day 6) — 팀원2 Backend Core 상세 작업 계획 (`/users/me`)

> 기준 문서: [api-spec.md](../api-spec.md) §2.1·§6.2 · [db-schema.md](../db-schema.md) §3.1·§7.1·§7.2 · [workflow.md](../workflow.md) Step 4
> 대상: **마이페이지 계정 관리 API (`/users/me` 4종)**. Step 1(인증·팀·스토리지)·Step 2(세션·자료·녹음)·Step 3(Q&A 루프)는 완료 상태.
> 범위 한정: Step 4 팀원2 항목 중 리포트 라우트·KCLOUD 배포는 이 문서 밖. **여기서는 `/users/me`만** 다룬다 — 마이페이지(와이어프레임 09)가 호출하는데 아직 라우트가 없어 mock-off 시 404가 나는 구간.

---

## 0. 시작 전 — 이미 있는 재사용 자산 (새로 만들지 말 것)

`/users/me`도 "부품을 조립"하는 작업이다. 인증·해시·모델·팀장 승계는 이미 만들어져 있다:

| 부품 | 위치 | 인터페이스 | 누가 만듦 |
|---|---|---|---|
| 현재 유저 Depends | `app/api/deps.py` | `get_current_user(...) → models.User` — 토큰 검증 + **탈퇴(`deleted_at`) 유저 차단 내장** | 팀원2 |
| 비밀번호 해시·검증 | `app/core/security.py` | `hash_password(plain) → str` / `verify_password(plain, hash) → bool` | 팀원2 |
| 응답 스키마 | `app/schemas/auth.py` | `AuthUser(id, name, username, email)` · `UserOut(+email_verified)` — GET 응답에 재사용 | 팀원2 |
| 유저 모델 | `app/db/models.py` | `User(username, password_hash, name, email, email_verified_at, deleted_at)` · `RefreshToken`·`SocialAccount`·`TeamMember` | 팀원2 |
| 팀장 자동 승계 | `app/api/routes/teams.py` `leave_team` 내부 | 후임 선출(`ORDER BY joined_at, user_id LIMIT 1`) + `leader_id` 갱신 / 마지막 1인이면 팀 삭제 (§7.2) — **DELETE에서 재사용, 헬퍼로 추출** | 팀원2 |
| 에러 포맷 | `app/core/errors.py` | `ApiError(status, code, message)` | 팀원2 |

> **핵심 원칙 (db-schema §7.1, D4):** **회원 탈퇴는 하드삭제가 아니라 익명화**다. `users` row는 보존하고 PII(`username`·`password_hash`·`name`·`email`)만 NULL로 지운 뒤 `deleted_at`을 찍는다. 본인이 owner인 세션·녹음·Q&A·리포트는 **팀 자산으로 유지**되고 owner는 "탈퇴한 사용자"로 표기된다(`sessions.owner_id ON DELETE RESTRICT`). 탈퇴를 `DELETE FROM users`로 구현하면 안 된다.

> **정리(중요):** `GET /auth/me`(§2 — 자동 로그인 확인용)와 `GET /users/me`(§2.1 — 마이페이지 계정 정보)는 **다른 엔드포인트**다. auth/me는 이미 있고, 여기서 만드는 건 `/users/*` 4종이다. 둘의 응답 스키마는 재사용하되 라우트는 별도.

---

## 작업 1. 마이페이지 스키마 (`app/schemas/user.py` 신규)

api-spec §2.1이 계약. 4개 엔드포인트의 요청/응답 모델을 먼저 고정한다.

### 1-1. 응답·요청 모델
- `MeOut` — 계정 정보 응답. `{ id, name, username, email, email_verified: bool }`.
  - `email_verified`는 `user.email_verified_at is not None`로 파생(§3.1). `UserOut`(schemas/auth.py)과 동형이므로 그대로 재사용해도 됨.
- `ProfileUpdateRequest` — 프로필 수정. `{ name: str }`(1~30자, 앞뒤 공백 strip — `SignupRequest`의 `strip_name` 검증기 재사용).
  - **스코프 한정:** 닉네임(`name`)만 수정 대상. `username`·`email` 변경은 유니크·재인증 이슈가 커서 이번 범위 밖(§8 후속). spec 문구도 "프로필(닉네임 등)".
- `PasswordChangeRequest` — `{ current_password: str, new_password: str }`(new는 8~128자, `SignupRequest.password`와 동일 제약).

### 1-2. 검증
- `name` 공백/길이 초과 → 422 / `new_password` 8자 미만 → 422 (Pydantic 단계).

---

## 작업 2. 라우터 골격 (`app/api/routes/users.py` 신규)

api-spec §2.1. 전부 **본인 스코프** — 경로 파라미터 없이 `get_current_user`가 대상 유저를 결정한다(남의 계정 건드릴 여지 없음).

| Method | Path | 권한 | 처리 |
|---|---|---|---|
| GET    | `/users/me`          | 본인 | 계정 정보 반환(작업 3) |
| PATCH  | `/users/me`          | 본인 | 닉네임 수정(작업 4) |
| PATCH  | `/users/me/password` | 본인 | 비밀번호 변경(작업 5) |
| DELETE | `/users/me`          | 본인 | 회원 탈퇴 = 익명화(작업 6) |

- `main.py`에 `include_router(users.router, prefix=API_V1)` 추가. 경로 `/users/*`는 기존 라우터와 안 겹침.
- 모든 핸들러 시그니처: `current_user: models.User = Depends(get_current_user)`. `deleted_at` 차단은 Depends가 이미 처리하므로 핸들러에서 재검사 불필요.

---

## 작업 3. `GET /users/me` — 계정 조회 (먼저, 가장 작음)

- `current_user` → `MeOut`으로 직렬화만. 새 쿼리 없음(Depends가 이미 로드).
- 응답 예시(§2.1):
  ```
  { "id": "usr_1", "name": "박준서", "username": "junseo",
    "email": "bjsbest0326@gmail.com", "email_verified": true }
  ```
- **검증:** 로그인 유저 200 + 필드 일치 / 토큰 없음 → 401 UNAUTHORIZED / access 만료 → 401 TOKEN_EXPIRED(Depends 규약).

---

## 작업 4. `PATCH /users/me` — 프로필(닉네임) 수정

- 바디 `ProfileUpdateRequest` → `current_user.name = body.name` → commit → `MeOut` 반환.
- `username`·`email`은 요청 바디에 없으므로 변경 불가(작업 1 스코프). 소셜 전용 가입자도 `name`은 항상 있으니(DDL CHECK: 활성 유저 `name` 필수) 분기 불필요.
- **검증:** 닉네임 변경 200 + 반영 / 공백·31자 → 422 / 비로그인 401.

---

## 작업 5. `PATCH /users/me/password` — 비밀번호 변경

api-spec §2.1. `{ current_password, new_password }`.

- 처리 순서:
  1. **소셜 전용 계정 차단:** `current_user.password_hash is None`이면 `400 NO_PASSWORD_SET`("소셜 로그인 계정은 비밀번호가 없어요."). 로컬 비밀번호가 없는 유저는 변경 대상 아님.
  2. **현재 비밀번호 확인:** `verify_password(body.current_password, current_user.password_hash)` 실패 → `400 INVALID_CREDENTIALS`("현재 비밀번호가 일치하지 않아요.").
  3. **갱신:** `current_user.password_hash = hash_password(body.new_password)` → commit.
  4. (권장) **다른 세션 로그아웃:** 비밀번호가 바뀌었으니 본인의 다른 `refresh_tokens`를 `revoked_at = now()`로 무효화 → 재로그인 유도. 데모 스코프에선 선택.
- 응답 `204`(본문 없음) 또는 `{ "ok": true }` — FE와 합의(기존 `logout`이 204라 204 권장).
- **검증:** 정상 변경 후 옛 비번 로그인 실패·새 비번 성공 / current 틀림 → 400 / new 8자 미만 → 422 / 소셜 전용 → 400 NO_PASSWORD_SET.

---

## 작업 6. `DELETE /users/me` — 회원 탈퇴 = 익명화 (⚠️ 최난도, §7.1·D4)

**하드삭제 아님.** db-schema §7.1의 **단일 트랜잭션**을 그대로 옮긴다. 순서가 중요하다(팀장 승계 먼저, 그다음 익명화).

### 6-1. 트랜잭션 절차 (§7.1)
```
1. 소속 각 팀에 대해:
   - 내가 팀장이면 → §7.2 승계(후임 선출 → teams.leader_id 갱신, 후임 없으면 팀 삭제)
   - 팀장 아니면 → 그냥 진행
2. DELETE FROM team_members WHERE user_id = :me      # 팀 활동 종료
3. DELETE FROM social_accounts WHERE user_id = :me
   UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = :me AND revoked_at IS NULL
4. UPDATE users SET username=NULL, password_hash=NULL, name=NULL, email=NULL,
                    deleted_at=now() WHERE id = :me
5. 보존: 내가 owner인 세션·녹음·Q&A·리포트는 건드리지 않음 (팀 자산 유지)
```
- 전 과정을 **하나의 트랜잭션**으로 묶고 마지막에 commit. 중간 실패 시 전체 롤백.

### 6-2. 팀장 승계 재사용 (헬퍼 추출)
- 현재 승계 로직은 `teams.py` `leave_team`에 **인라인**으로 있다. DELETE에서도 팀마다 같은 로직이 필요하므로 **공통 헬퍼로 추출**한다:
  - `app/services/team_membership.py`(신규) 또는 `deps`/`teams` 내 함수: `leave_or_succeed(db, team_id, user_id)` — "후임 선출(`ORDER BY joined_at, user_id LIMIT 1`) → 후임 있으면 `leader_id` 갱신 + 멤버십 삭제 / 없으면 팀 CASCADE 삭제, 팀장이 아니면 멤버십만 삭제".
  - `leave_team`도 이 헬퍼를 호출하도록 리팩터(중복 제거). **주의:** 로직 자체는 검증된 코드이므로 동작을 바꾸지 말고 그대로 함수로 감싸기만 한다.
- 탈퇴 시엔 내가 속한 **모든 팀**을 순회하며 이 헬퍼를 호출.

### 6-3. 주의점
- `email`·`username`을 NULL로 지우면 유니크 인덱스(`WHERE ... IS NOT NULL`, 부분 유니크)와 충돌하지 않는다 → **재가입 허용**(§3.1 주석). 하드삭제하면 안 되는 이유.
- `sessions.owner_id`는 `ON DELETE RESTRICT`라 애초에 users를 하드삭제할 수 없다(실수 방어). 우리는 UPDATE만 하므로 무관.
- 응답 `204`. 이후 그 access 토큰으로 오는 요청은 `get_current_user`가 `deleted_at`을 보고 자동 차단(이미 구현됨).

### 6-4. 검증 (pytest)
- 일반 멤버 탈퇴 → `users` row 남고 name·email·username·password_hash NULL·`deleted_at` 세팅 / 소속 team_members 제거 / refresh 전부 revoked / **본인 owner 세션은 그대로 보존**.
- **팀장 탈퇴 + 후임 있음** → `teams.leader_id`가 최고참으로 승계 / 후임 없음(1인 팀) → 팀 CASCADE 삭제.
- 탈퇴 후 같은 access 토큰 재요청 → 401 / 탈퇴한 username·email로 재가입 → 성공(유니크 충돌 없음).
- 비로그인 DELETE → 401.

---

## 권장 순서 & 오늘 할 일

```
작업 1 (스키마)                       ← 계약 먼저 고정
  → 작업 2 (라우터 골격 + main 등록)
  → 작업 3 (GET /users/me)            ← 직렬화만, 가장 작음
  → 작업 4 (PATCH 프로필)             ← 필드 하나
  → 작업 5 (PATCH 비밀번호)           ← current 검증 + 소셜 차단
  → 작업 6 (DELETE 탈퇴=익명화)       ← 최난도, 트랜잭션 + 팀장 승계 재사용
```

**한 줄 요약:** 본인 스코프 4종을 만들되, 조회·수정은 `get_current_user`가 잡은 유저를 직렬화/갱신만 하고, **탈퇴는 하드삭제가 아니라 §7.1 익명화 트랜잭션**(팀장이면 승계 후 PII NULL화 + `deleted_at`)으로 구현한다.

## 공통 지침 (Step 1·2·3과 동일)

1. **계약 우선** — 응답 형태는 api-spec §2.1 예시와 필드 단위로 맞출 것(마이페이지 09가 의존). `email_verified`는 `email_verified_at`에서 파생.
2. **본인 스코프** — 4종 모두 경로에 `userId`를 두지 않는다. 대상은 항상 토큰의 유저(`get_current_user`). 남의 계정을 만질 표면 자체를 만들지 않는다.
3. **탈퇴 = 익명화** — `DELETE FROM users` 금지. §7.1 트랜잭션(승계 → 멤버십/소셜/refresh 정리 → PII NULL화 + `deleted_at`)으로. owner 세션은 보존.
4. **승계 재사용** — 팀장 승계는 `teams.leave_team`의 검증된 로직을 **헬퍼로 추출해 공유**(동작 변경 없이). 새로 짜서 규칙이 어긋나지 않게.
5. **검증 필수** — pytest로 4종의 상태·권한·에러 매핑을 실제 DB까지 관통. 특히 탈퇴는 익명화 결과·팀장 승계·재가입 허용·토큰 차단을 확인.
6. **재검증** — 팀장이면서 owner인 유저 탈퇴, 1인 팀 팀장 탈퇴, 소셜 전용 계정 비밀번호 변경 시도 등 엣지를 한 번 더 적대적으로 찔러볼 것.
