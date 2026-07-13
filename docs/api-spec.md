# Rehearsal.io — API 명세서 (v0.4-draft)

> LLM 기반 프레젠테이션 질의응답 생성/분석 서비스의 백엔드(FastAPI) ↔ 프론트(Flutter Web/iOS/Android) API 계약.
> 기능명세서(Google Sheets) + 와이어프레임 28화면(`design/wireframes/`) 기준으로 작성. **이 문서는 "의도된 최종 API" 설계이며, 현재 스캐폴드는 일부만 구현(Mock)되어 있습니다.** (§0.3 참고)

작성일: 2026-07-11 · 개정: 2026-07-11 (v0.3) · 상태: **초안(가정 기반)** — §0.2 가정값은 팀 논의 후 확정 필요.

---

## 0. 개요

### 0.1 핵심 파이프라인

발표 1회 = **세션(Session)** 하나. 세션은 아래 단계를 거치며, 무거운 단계는 모두 비동기로 처리됩니다.

```
PDF 업로드 ──(파싱)──▶ slides.json
                                   ╲
발표 녹음/업로드 ──(STT+정렬)──▶ transcript.json(원문) ──▶ AI 질문 생성 ──▶ 질의응답 루프 ──▶ 세션 저장 ──▶ 분석 리포트
                                   /
                          (TTS·답변 STT·꼬리질문)
```

> **비동기 원칙(중요):** 답변 STT와 꼬리질문 생성은 **답변 오디오 업로드 시점에 완료될 수 없습니다**(꼬리질문은 전사된 답변 내용에 의존). 따라서 답변 제출은 `202`로 접수만 하고, 꼬리질문/다음 질문은 `GET /qna` 폴링으로 확정됩니다. (§4.4, 에러 A 수정)

### 0.2 가정한 기본값 (⚠️ 확정 필요)

| #   | 항목           | 기본값(가정)                                                   | 비고                                                                                       |
| --- | ------------ | --------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| A1  | 인증 방식        | JWT (access 짧은 수명 + refresh) + 소셜 OAuth                   | **refresh 토큰 전달은 클라이언트별로 분기**: Web = `Set-Cookie`(httpOnly), Native(iOS/Android) = 응답 본문. `X-Client-Platform` 헤더로 구분 (§2). |
| A2  | 비동기 처리 모델    | **리소스 내 상태 필드 + 클라이언트 폴링**(1~2s)                          | 별도 `/jobs` 서브시스템 대신 리소스 GET으로 상태 확인. SSE는 선택적 확장(§7)                                       |
| A3  | PDF 파싱       | 비동기 (`material.status`)                                   | 실패/재업로드 UI 필요 → 비동기                                                                       |
| A4  | STT (발표·답변)  | 비동기 (`transcript.status`, `answer.status`)               | 원문(raw) 전사만 수행 — LLM 정제 패스 없음(v0.3). 답변 STT 상태 필드명은 answer.status로 통일. 타임스탬프는 ForcedAligner 산출                                            |
| A5  | AI 질문 생성     | 비동기 (`session.status = generating_questions`)            | 동기 가능하나 STT 의존이라 비동기로 통일                                                                  |
| A6  | TTS (질문 음성)  | 비동기 (`question.tts.status`)                               | self-hosted(VoxCPM2) 동시성 한계 → 큐 가정                                                        |
| A7  | 분석 리포트       | 비동기 + **세션 종료 시 자동 생성**                                   | 세션이 `completed`가 되기 전에는 `report`가 존재하지 않음(§4.1 예시 참고)                                      |
| A8  | 발표 녹음 방식     | 클라이언트가 로컬 녹음 → **종료 시 파일 업로드**. 실시간/파일업로드 모드가 업로드 지점에서 수렴 | 서버 실시간 스트리밍 미사용                                                                            |
| A9  | 타이머          | 클라이언트 권위. 서버는 `started_at/ended_at`만 저장                   |                                                                                          |
| A10 | 파일 저장        | 오브젝트 스토리지 + 서명 URL(`*_url`)로 재생                           | 보관 정책 미정(§8)                                                                              |
| A11 | 꼬리질문 최대 깊이   | **1**                                                     | 명세 준수                                                                                     |
| A12 | 질의응답 종료 우선순위 | 사용자 종료 > 질의 수 도달 > 답변 시간초과                                | 명세 준수                                                                                     |
| A13 | 마이크 권한       | **클라이언트 전용**(API 없음)                                      | 브라우저/OS 권한                                                                                |

### 0.3 현재 스캐폴드와의 차이

- 스캐폴드는 `Team` / `Speech`(단일 `audienceType`) / Mock 인증만 존재.
- 본 명세는 `Speech` → **`Session`**(멀티 페르소나, slides/transcript/qna/report 포함)으로 확장.
- 스캐폴드의 `MockAuthRepository`·`InMemoryStore`·`LLMProvider` 추상화는 그대로 재사용 가능.

### 0.4 변경 이력 (v0.1 → v0.2)

정합성 오류 A–I 수정.

| ID | 문제                                                        | 조치                                                                                                       |
| -- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| A  | `POST /answer` 응답이 (아직 전사되지 않은) 답변 기반 꼬리질문을 즉시 반환 — 시간 모순 | 답변 제출은 `202`(processing)만 반환. 꼬리질문·다음 질문은 `GET /qna` 폴링으로 확정. `answer.follow_up_status` 추가 (§4.4)          |
| B  | 로그인 응답 본문에 `refresh_token` — A1의 httpOnly 쿠키와 모순          | Web은 `Set-Cookie`(httpOnly), Native는 본문. `X-Client-Platform` 헤더 도입 (§1·§2)                               |
| C  | 성장 리포트의 per-type 점수를 세션 리포트가 노출하지 않음                       | `GET /report`에 `type_scores`(전략별 수치) 추가. 성장 시리즈는 이 값에서 파생 (§5.2)                                          |
| D  | §1.2 async 계약(`succeeded`)이 다수 리소스(`ready`)와 불일치          | 종료 상태를 **`ready`로 단일화**. `transcript`·`answer`도 `ready` 사용 (§1.2·§6.1)                                    |
| E  | 성장 리포트가 팀 스코프라 발표자별 성장이 섞임                                 | **유저 스코프**로 이동: `GET /users/me/report/growth` (§5.2)                                                      |
| F  | 세션 엔드포인트에 권한 명세 없음 / 삭제 cascade 미정                         | 세션에 `owner_id` + 권한 열 추가. 삭제 cascade 범위 **확정** (§4.1·§6.2)                                                |
| G  | 링크 초대 revoke/list가 `inviteId` 기반과 어긋남                      | 링크 초대 전용 엔드포인트 분리(`/invites/link` GET/DELETE), 회전 시 이전 링크 무효화 명시 (§3.1)                                   |
| H  | `/invites/{token}` 인증 경계 불명확                               | 미리보기(`GET`)는 인증 불필요, 수락/거절은 인증 필요로 명시 (§2 note·§3.1)                                                      |
| I  | `recording`이 SessionStatus 값이자 서브리소스 상태로 중복               | SessionStatus 값 `recording` → **`recording_in_progress`**로 개명 (§4·§6.1)                                  |

### 0.5 변경 이력 (v0.2 → v0.3) — transcript 정제 제거
 
로컬 정제 LLM(`Qwen3-4B`) 삭제로 상주 모델이 STT·TTS 2개로 축소됨(§8.1). **API 계약(엔드포인트·상태·스키마)은 변경 없음** — 정제는 원래도 별도 상태/엔드포인트가 아니라 STT 내부 단계였기 때문. 달라지는 것은 텍스트의 성격과 문서 주석뿐.
 
| 항목                | 변화                                                                                     |
| ----------------- | -------------------------------------------------------------------------------------- |
| `transcript` 텍스트   | 정제본 → **원문(raw) ASR**. 간투사·비문 포함 가능 (§4.3)                                              |
| `answer.text`      | 동일하게 원문(raw) (§4.4)                                                                     |
| 타임스탬프 `ts`         | **영향 없음** — ForcedAligner(잔류) 산출                                                        |
| 리포트 filler/WPM     | 원문 기준 집계 → 필러 검출 정확도 ↑, WPM 소폭 상승 가능 (§5.2)                                             |
| 질문 생성/리포트 LLM      | **영향 없음** — 외부 API. 단 입력이 원문이라 노이즈 견디는 프롬프트 필요 (§8)                                     |
| 상태 머신·enum         | **변경 없음**(`transcribing → ready` 흐름 그대로)                                                |
| 지연(latency)        | 모델 홉 1개 감소 → transcript `ready` 도달 소폭 빨라짐(A4 폴링 간격 영향 없음)                               |
 
> **가정:** 질문 생성·리포트 분석 LLM은 v0.2 이전부터 **외부 API**였다고 가정. 만약 이 작업들이 로컬 `Qwen3-4B`에 의존했다면(정제 전용이 아니었다면), 별도의 외부 LLM 이전 결정이 필요하며 이는 위 표의 "영향 없음" 항목을 뒤집습니다 — 팀 확인 요망.

### 0.6 변경 이력 (v0.3 → v0.4-draft) — 실시간 녹음 청크 계약 (⚠️ BE 합의 필요)

README 아키텍처("녹음 중 60초+4초 겹침 청크 전송", STT 실측으로 청크 크기 확정)에 대응하는 API 계약이 spec에 없어 FE(팀원1)가 초안 추가. **BE(팀원2) 합의 후 -draft 제거.**

| 항목 | 변화 |
|---|---|
| `POST /recording/chunks` · `/recording/complete` | **신설** (§4.3.1) — 실시간 모드 전용 |
| `POST /recording` | 파일 모드(d3)·폴백 전용으로 역할 축소 (§4.3) |
| 파일 형식 | 녹음 산출물에 `webm` 허용 추가 (§1.3) — 웹 폴백 경로용 |
| 상태 머신·enum | 변경 없음 (`recording_in_progress` 중 청크 수신, `complete` → `transcribing`) |

### 0.7 변경 이력 (v0.4-draft) — Q&A 답변 시작 제한시간 (⚠️ BE 합의 필요)

질문을 **텍스트로도 표시**하므로 FE는 TTS "다시 듣기" UI를 제공하지 않는다. 또한 §4.4의 모호했던 "답변 시간초과"를 **재생 완료 후 답변 시작까지 30초**로 구체화(FE 제안). 30초 내 미시작 시 클라이언트가 `pass`로 처리한다. **BE(팀원2) 합의 후 -draft 제거.**

| 항목 | 변화 |
|---|---|
| `POST .../pass` | 선택 바디 `{ "reason": "user" \| "timeout" }` 추가(기본 `user`) — 서버가 `ended_reason` 확정에 사용 (§4.4) |
| 답변 시작 흐름 | "tts ready 후 자동 녹음"(구) → "재생 완료 후 **30초 카운트다운**, 사용자가 답변 시작(녹음). 미시작 시 자동 `pass(reason=timeout)`"(신) (§4.4) |
| TTS 다시 듣기 | **UI 미제공**(질문 텍스트 병기). `tts.audio_url`·재생 계약 자체는 변화 없음 |
| 상태 머신·enum·기타 엔드포인트 | 변경 없음 (녹음 타이밍은 클라이언트 전용 — "API는 결과 오디오만 수신") |

---

## 1. 공통 규약

- **Base URL**: `/api/v1`
- **인증**: `Authorization: Bearer <access_token>` (§2 예외 제외)
- **클라이언트 구분**: 모든 요청에 `X-Client-Platform: web | ios | android` 권장(인증 토큰 전달 방식 분기에 사용, B)
- **직렬화**: 요청/응답 `application/json`, 파일 업로드 `multipart/form-data`
- **시간**: ISO 8601 UTC (`2026-07-11T08:30:00Z`)
- **ID**: 문자열(`ses_...`, `team_...` prefix)
- **페이지네이션**: `?limit=20&cursor=<opaque>` → `{ items, next_cursor }`
- **멱등성**: 파일 업로드/생성 트리거는 `Idempotency-Key` 헤더 지원(선택)

### 1.1 에러 포맷

```
{ "error": { "code": "TEAM_NOT_FOUND", "message": "팀을 찾을 수 없어요.", "details": {} } }
```

| HTTP                              | 사용                                     |
| --------------------------------- | -------------------------------------- |
| 200 / 201 / 204                   | 성공 / 생성 / 본문 없음                        |
| 202                               | 비동기 작업 접수(처리 시작)                       |
| 400 / 401 / 403 / 404 / 409 / 410 | 검증 실패 / 미인증 / 권한 / 없음 / 충돌(중복) / 만료됨   |
| 413 / 415                         | 파일 용량 초과 / 지원하지 않는 형식                  |
| 422                               | 처리 불가(예: 스캔본 PDF)                      |
| 429 / 500 / 503                   | 레이트리밋 / 서버 오류 / 모델·외부 API 일시 오류        |

주요 에러 코드는 §6.

### 1.2 비동기 상태 규약 (A2, D)

무거운 작업은 즉시 `202`로 접수되고, 결과는 부모 리소스의 상태 필드에 반영됩니다. 클라이언트는 해당 리소스를 폴링합니다.

```
status ∈ { queued, processing, ready, failed }   // 모든 async 리소스 공통(단일화)
```

- 종료(성공) 상태는 **`ready` 하나로 통일**합니다(`material`, `transcript`, `recording`, `question.tts`, `answer`, `report` 모두 동일).
- 실패 시 같은 리소스에 `error: { code, message }`가 채워지고, 해당 리소스의 `retry` 엔드포인트로 재시도합니다.

### 1.3 파일 제약 (기본값)

| 종류       | 형식               | 최대             |
| -------- | ---------------- | -------------- |
| 발표 자료    | PDF (텍스트 추출 가능본) | 20 MB · 50 페이지 |
| 발표/답변 녹음 | mp3 · wav · m4a · **webm**(v0.4-draft) | 60 분 · 200 MB  |

스캔본/이미지 PDF는 `422 UNPROCESSABLE_PDF`로 거부(기본값; OCR은 후속).

> **webm 추가(v0.4-draft, FE 제안 · BE 합의 필요):** 브라우저 MediaRecorder는 m4a를 만들 수 없어 웹 폴백 녹음의 산출물이 webm/opus. STT는 ffmpeg 디코딩이라 추가 비용 없음. FE 기본 경로는 PCM 스트림 → **wav** 생성이므로 webm은 스트리밍 미지원 브라우저 폴백에서만 발생.

---

## 2. 인증 · 계정 (`/auth`, `/users`)

> **인증 경계(H 포함):** `/auth/*`는 기본적으로 인증 불필요. **단, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`는 인증(토큰/쿠키) 필요.** 초대 토큰 미리보기 `GET /invites/{token}`는 인증 불필요, 수락/거절은 인증 필요(§3.1).

| Method | Path                            | 인증 | 설명                                                            |
| ------ | ------------------------------- | -- | ------------------------------------------------------------- |
| POST   | `/auth/signup`                  | ✗  | 회원가입: 이름·아이디·비밀번호·이메일 → 미인증 유저 생성 + 인증코드 발송(비번확인은 클라이언트 검증)   |
| POST   | `/auth/email/verify-request`    | ✗  | 인증코드 재발송 `{ email }`                                          |
| POST   | `/auth/email/verify`            | ✗  | 이메일 인증 `{ email, code }`                                      |
| POST   | `/auth/login`                   | ✗  | 로그인 `{ username, password }` → 토큰 + 유저                        |
| POST   | `/auth/login/social/{provider}` | ✗  | 소셜 로그인 `provider ∈ {google, kakao, naver}`, `{ id_token }` 교환 |
| POST   | `/auth/refresh`                 | ✓  | refresh → 새 access (자동 로그인). Web=쿠키 자동전송 / Native=본문 `{ refresh_token }` |
| POST   | `/auth/logout`                  | ✓  | 세션/refresh 무효화 (Web=쿠키 삭제)                                    |
| GET    | `/auth/me`                      | ✓  | 현재 유저(자동 로그인 확인용). access 만료 시 `401 TOKEN_EXPIRED` → refresh  |

> **아이디/비밀번호 찾기**(와이어프레임 `a3`)는 "관리자에게 문의하세요" 정적 화면 → **엔드포인트 없음**.

**로그인 응답 — Native(iOS/Android), `X-Client-Platform: ios|android`**

```
{
  "access_token": "eyJhbGci...",
  "refresh_token": "eyJhbGci...",     // Native 전용: 앱 secure storage에 저장
  "token_type": "Bearer",
  "expires_in": 900,
  "user": { "id": "usr_1", "name": "박준서", "username": "junseo", "email": "bjsbest0326@gmail.com" }
}
```

**로그인 응답 — Web, `X-Client-Platform: web`** (B 수정: refresh는 본문에 없음)

```
HTTP/1.1 200 OK
Set-Cookie: refresh_token=eyJhbGci...; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth

{
  "access_token": "eyJhbGci...",
  "token_type": "Bearer",
  "expires_in": 900,
  "user": { "id": "usr_1", "name": "박준서", "username": "junseo", "email": "bjsbest0326@gmail.com" }
}
```

### 2.1 마이페이지 (`/users`)

| Method | Path                 | 설명                                           |
| ------ | -------------------- | -------------------------------------------- |
| GET    | `/users/me`          | 계정 정보                                        |
| PATCH  | `/users/me`          | 프로필(닉네임 등) 수정                                |
| PATCH  | `/users/me/password` | 비밀번호 변경 `{ current_password, new_password }` |
| DELETE | `/users/me`          | 회원 탈퇴(연관 데이터 처리 방침 §8)                       |

---

## 3. 팀 (`/teams`, `/invites`)

| Method | Path                               | 설명                      | 권한 |
| ------ | ---------------------------------- | ----------------------- | --- |
| GET    | `/teams`                           | 내 팀 목록(멤버 미리보기·발표 수 포함) | 멤버 |
| POST   | `/teams`                           | 팀 생성 `{ name }`         | -  |
| GET    | `/teams/{teamId}`                  | 팀 상세(팀원 목록 포함)          | 멤버 |
| PATCH  | `/teams/{teamId}`                  | 팀 이름 변경                 | 팀장 |
| DELETE | `/teams/{teamId}`                  | 팀 삭제                    | 팀장 |
| POST   | `/teams/{teamId}/leave`            | 팀 나가기                   | 멤버 |
| GET    | `/teams/{teamId}/members`          | 팀원 목록                   | 멤버 |
| DELETE | `/teams/{teamId}/members/{userId}` | 팀원 내보내기                 | 팀장 |

### 3.1 초대 (이메일 / 링크)

이메일 초대는 `inviteId`로, 링크 초대는 팀당 단일 활성 링크(`token`)로 관리합니다. (G 수정)

**이메일 초대**

| Method | Path                                 | 설명                          | 권한 |
| ------ | ------------------------------------ | --------------------------- | --- |
| POST   | `/teams/{teamId}/invites`            | 이메일 초대 `{ email }` → 메일 발송 | 멤버 |
| GET    | `/teams/{teamId}/invites`            | 대기 중 **이메일** 초대 목록         | 멤버 |
| DELETE | `/teams/{teamId}/invites/{inviteId}` | 이메일 초대 취소                   | 멤버 |

**링크 초대** (팀당 활성 링크 1개; 생성/회전 시 이전 토큰 즉시 무효화)

| Method | Path                            | 설명                                              | 권한 |
| ------ | ------------------------------- | ----------------------------------------------- | --- |
| POST   | `/teams/{teamId}/invites/link`  | 링크 생성/회전 → `{ token, url, expires_at }` (이전 링크 무효) | 팀장 |
| GET    | `/teams/{teamId}/invites/link`  | 현재 활성 링크 조회 → `{ token, url, expires_at }` 또는 `null` | 멤버 |
| DELETE | `/teams/{teamId}/invites/link`  | 링크 비활성화(토큰 무효화)                                 | 팀장 |

**토큰 기반(수락 화면용)** — H: 미리보기는 인증 불필요, 수락/거절은 인증 필요

| Method | Path                       | 인증 | 설명                            |
| ------ | -------------------------- | -- | ----------------------------- |
| GET    | `/invites/{token}`         | ✗  | 초대 미리보기(팀명·인원·발표 수)          |
| POST   | `/invites/{token}/accept`  | ✓  | 초대 수락 → 팀 합류(로그인/회원가입 후 호출)  |
| POST   | `/invites/{token}/decline` | ✓  | 초대 거절                         |

- 무효/만료 토큰: `409 INVITE_INVALID` / `410 INVITE_EXPIRED`.

---

## 4. 발표 세션 (`/teams/{teamId}/sessions`, `/sessions/{sessionId}`)

핵심 리소스. 상태 머신 (I: `recording` → `recording_in_progress`):

```
stateDiagram-v2
    [*] --> draft: POST /sessions
    draft --> recording_in_progress: recording/start (실시간)
    draft --> transcribing: recording 업로드 (파일모드)
    recording_in_progress --> transcribing: recording 업로드(발표 마치기)
    transcribing --> generating_questions: STT 완료 → qna/generate
    generating_questions --> qna: 질문 생성 완료
    qna --> completed: qna/end (or 종료조건 충족)
    completed --> [*]
    transcribing --> failed: STT 실패(재시도 가능)
    generating_questions --> failed: 생성 실패(재시도 가능)
```

> `material`(PDF)은 세션 상태와 **독립적으로** 파싱됩니다(`session.material.status`). 질문 생성 시 자료가 있으면 `material.status = ready`를 대기합니다.
> **꼬리질문**은 세션 상태를 바꾸지 않고 `qna` 내부에서 비동기로 처리됩니다(§4.4).

### 4.1 세션 CRUD (F: 권한 + owner)

| Method | Path                       | 설명                   | 권한                 |
| ------ | -------------------------- | -------------------- | ------------------ |
| GET    | `/teams/{teamId}/sessions` | 세션(발표) 목록            | 멤버                 |
| POST   | `/teams/{teamId}/sessions` | 세션 생성(발표 설정)         | 멤버 (생성자=`owner`)   |
| GET    | `/sessions/{sessionId}`    | 세션 상세(요약·상태)         | 멤버                 |
| PATCH  | `/sessions/{sessionId}`    | 설정 수정(`draft`일 때)    | owner              |
| DELETE | `/sessions/{sessionId}`    | 발표 삭제(아래 cascade)    | owner 또는 팀장        |

> **삭제 cascade 범위(확정, F):** 세션 삭제 시 `slides.json`, `recording` 오디오, `transcript`, Q&A 로그(질문/답변/TTS/답변 오디오), `report`가 **모두 함께 삭제**됩니다. (§8의 "미정" 해소)

**세션 생성 요청**

```
{
  "name": "1차 발표",
  "personas": ["egen", "teto", "kkondae"],
  "question_count": 5,
  "time_limit_minutes": 10,
  "mode": "realtime"
}
```

`personas`(중복 선택, 1개 이상), `mode ∈ {realtime, upload}`.
> `question_count`는 **1차(primary) 질문 수**만 의미합니다. 꼬리질문은 포함하지 않으며, `count_reached` 종료 판정도 1차 질문 기준입니다.

**세션 상세 응답(요약)** — A7 정합: `qna` 상태에서는 `report`가 아직 `null`

```
{
  "id": "ses_1", "team_id": "team_1", "owner_id": "usr_1", "name": "1차 발표",
  "status": "qna",
  "personas": ["egen","teto","kkondae"],
  "question_count": 5, "time_limit_minutes": 10, "mode": "realtime",
  "material": { "status": "ready", "slide_count": 10 },
  "recording": { "status": "ready", "duration_seconds": 663, "audio_url": "https://.../rec.m4a" },
  "transcript": { "status": "ready" },
  "report": null,
  "created_at": "2026-07-08T02:10:00Z"
}
```
> `report`는 `qna/end` 이후 `{ "status": "queued|processing|ready|failed" }`로 채워집니다.

### 4.2 발표 자료 (PDF → slides.json)

| Method | Path                                   | 설명                                        |
| ------ | -------------------------------------- | ----------------------------------------- |
| POST   | `/sessions/{sessionId}/material`       | PDF 업로드(multipart) → **비동기 파싱 시작**(`202`) |
| GET    | `/sessions/{sessionId}/material`       | 파싱 상태 + 슬라이드(페이지·텍스트)                     |
| POST   | `/sessions/{sessionId}/material/retry` | 파싱 재시도                                    |
| DELETE | `/sessions/{sessionId}/material`       | 자료 삭제(자료 없이 진행 허용)                        |

**GET material 응답**

```
{
  "status": "ready",          // queued | processing | ready | failed
  "progress": 1.0,
  "file_name": "deck.pdf", "page_count": 10,
  "slides": [ { "page": 1, "text": "표지 …" }, { "page": 2, "text": "문제 정의 …" } ],
  "error": null
}
```

스캔본 등 실패: `status:"failed"`, `error:{ code:"UNPROCESSABLE_PDF", message:"텍스트를 읽을 수 없어요." }`.

### 4.3 발표 녹음 & STT (→ transcript.json)

| Method | Path                                     | 설명                                                                        |
| ------ | ---------------------------------------- | ------------------------------------------------------------------------- |
| POST   | `/sessions/{sessionId}/recording/start`  | (실시간·선택) 녹음 시작 표시 → `status=recording_in_progress`, `started_at`. 이어하기용   |
| POST   | `/sessions/{sessionId}/recording`        | 녹음 파일 업로드(multipart, **파일 모드(d3) 전용**·v0.4에서 실시간 종료 겸용 해제) → **STT 시작**(`202`) |
| POST   | `/sessions/{sessionId}/recording/chunks` | **(v0.4-draft)** 실시간 녹음 청크 업로드(60초+4초 겹침) → 청크별 STT 잡 큐 적재(`202`)        |
| POST   | `/sessions/{sessionId}/recording/complete` | **(v0.4-draft)** 실시간 녹음 종료: 재생용 전체 파일 업로드 + 병합 트리거 → `transcribing`(`202`) |
| GET    | `/sessions/{sessionId}/transcript`       | STT 상태 + 세그먼트                                                             |
| POST   | `/sessions/{sessionId}/transcript/retry` | STT 재시도                                                                   |

**녹음 업로드(multipart 필드)**: `file`(audio), `started_at`, `ended_at`, `duration_seconds`.

#### 4.3.1 실시간 녹음 청크 파이프라인 (v0.4-draft, FE 제안 · BE 합의 필요)

루트 README "발표 녹음 → STT 청크 파이프라인" 아키텍처(청크 60초+4초 겹침, STT 실측으로 확정)의 API 계약. 발표가 끝나기 전에 전사가 대부분 진행되게 한다.

**`POST /recording/chunks`** — multipart 필드:

| 필드 | 타입 | 설명 |
|---|---|---|
| `file` | audio (wav 권장) | 청크 오디오. FE는 PCM 16kHz 모노 스트림을 잘라 wav로 인코딩 |
| `seq` | int (0-base) | 청크 순번. BE는 순서 보장 직렬 큐에 적재 (infra 제약 2) |
| `offset_seconds` | float | 녹음 시작 기준 이 청크의 시작 오프셋 (겹침 포함, `max(0, 60·seq − 4)`) |
| `overlap_seconds` | float | 앞 청크와의 겹침 (첫 청크 0, 이후 4) |
| `duration_seconds` | float | 이 청크의 길이 |

응답 `202 { "received_seq": n }`. 청크 수신 중 세션 상태는 `recording_in_progress` 유지, `transcript.status = processing`.

**`POST /recording/complete`** — multipart 필드: `file`(재생용 전체 오디오), `total_chunks`, `started_at`, `ended_at`, `duration_seconds`.
응답 `202`. BE는 누락 청크 검증(수신 seq ⊂ 0..total_chunks−1) 후 병합(오프셋 보정 + 겹침 이음새 처리, 팀원3 담당)을 마무리하고 세션을 `transcribing` → 완료 시 `transcript.ready`로 전이.

- **답변 오디오는 청크 없이** 기존 단발 업로드(§4.4) 유지 (짧아서 불필요, README 불변 조건).
- 청크 일부 유실 시: `complete`의 전체 파일이 원본이므로 BE가 누락 구간만 재전사 가능 (폴백 안전망).
- 스트리밍 미지원 클라이언트(구형 브라우저)는 청크 없이 `POST /recording` 단발 경로 사용 가능(파일 모드와 동일 처리).

**GET transcript 응답** (D: `ready`)

```
{
  "status": "ready",           // queued | processing | ready | failed
  "segments": [
    { "ts": "00:12", "text": "안녕하세요, 어… 오늘 발표를 맡은 박준서입니다." },
    { "ts": "04:12", "text": "성능은 기존 대비 2배 개선되었습니다." }
  ],
  "error": null
}
```
> **원문(raw) 전사(v0.3):** `segments[].text`는 로컬 LLM 정제를 거치지 않은 **ASR 원문**입니다. 간투사·비문·구어체가 그대로 포함될 수 있습니다(예: "어…"). `ts`는 ForcedAligner가 산출하므로 정제 제거와 무관하게 유지됩니다. 답변 전사(`answer.text`, §4.4)도 동일하게 원문입니다. 화면 표시용 후처리(간투사 숨김 등)가 필요하면 **클라이언트에서** 처리합니다.

### 4.4 질의응답 (Q&A) — A 수정: 답변·꼬리질문 완전 비동기

STT 완료 후 질문 생성 → 질문별 TTS 재생 → 답변 녹음 → (선택)꼬리질문 루프.

| Method | Path                                                      | 설명                                                                         |
| ------ | --------------------------------------------------------- | -------------------------------------------------------------------------- |
| POST   | `/sessions/{sessionId}/qna/generate`                      | slides+transcript+personas 기반 질문 생성(`202`) → `status=generating_questions` |
| GET    | `/sessions/{sessionId}/qna`                               | Q&A 전체 상태(질문 목록·현재 인덱스·종료 여부) — **꼬리질문/다음 질문 확정의 단일 소스**                    |
| GET    | `/sessions/{sessionId}/qna/questions/{questionId}`        | 질문 상세(텍스트·페르소나·전략·근거·TTS)                                                  |
| POST   | `/sessions/{sessionId}/qna/questions/{questionId}/answer` | 답변 녹음 업로드(multipart) → **`202` 접수**. STT+꼬리질문은 비동기                          |
| POST   | `/sessions/{sessionId}/qna/questions/{questionId}/pass`   | 답변 스킵/패스 → 다음 질문(꼬리질문 생략). 선택 바디 `{ reason: "user" \| "timeout" }`(기본 `user`) |
| POST   | `/sessions/{sessionId}/qna/end`                           | 질의응답 종료 → `completed` + 리포트 자동 생성                                          |

**GET /qna 응답** (C: `strategy` 노출, A: `answer.follow_up_status`, D: `answer.status=ready`)

```
{
  "status": "in_progress",       // in_progress | ended
  "current_question_id": "q_2",
  "ended_reason": null,          // user_end | count_reached | timeout
  "questions": [
    {
      "id": "q_1", "order": 1, "persona": "kkondae", "strategy": "detail_probe",
      "parent_id": null, "follow_up_depth": 0,
      "text": "측정 환경이 뭐였는지 설명해봐요.",
      "evidence": { "slides": [3], "transcript_refs": [ { "ts": "04:12" } ] },
      "tts": { "status": "ready", "audio_url": "https://.../q1.mp3" },
      "answer": {
        "status": "ready",           // pending | processing | ready | failed
        "text": "사내 서버 A100 1대에서 3회 평균으로 측정했습니다.",
        "audio_url": "https://.../a1.m4a",
        "follow_up_status": "none"   // pending | generated | none
      }
    },
    {
      "id": "q_2", "order": 2, "persona": "egen", "strategy": "big_picture",
      "parent_id": null, "follow_up_depth": 0,
      "text": "경쟁 서비스 대비 차별점이 뭔가요?",
      "evidence": { "slides": [], "transcript_refs": [] },
      "tts": { "status": "ready", "audio_url": "https://.../q2.mp3" },
      "answer": {
        "status": "processing",      // 답변 STT 진행 중
        "text": null,
        "audio_url": "https://.../a2.m4a",
        "follow_up_status": "pending"  // 꼬리질문 생성 여부 판정 중
      }
    }
  ]
}
```

**답변 제출 응답(POST /answer)** — `202`, 접수만. 꼬리질문/다음 질문은 반환하지 않음 (A 수정)

```
HTTP/1.1 202 Accepted

{
  "answer": { "status": "processing", "text": null, "audio_url": "https://.../a2.m4a", "follow_up_status": "pending" }
}
```

**이후 흐름 (클라이언트가 `GET /qna` 폴링):**

1. 답변 STT 완료 → 해당 질문 `answer.status = ready`, `answer.text` 채워짐.
2. 서버가 꼬리질문 생성 판정:
   - 생성됨 → `answer.follow_up_status = "generated"`, `questions[]`에 자식 질문(`parent_id`, `follow_up_depth: 1`, 자체 `tts` 비동기)이 추가되고 `current_question_id`가 그 자식으로 이동.
   - 생성 안 함(깊이 1 도달·불필요·`pass`) → `answer.follow_up_status = "none"`, `current_question_id`가 다음 1차 질문으로 이동(또는 `status: "ended"`).
3. 답변 STT 실패 → `answer.status = "failed"`, `answer.error` 채워짐. 동일 질문에 **재제출**(`POST .../answer` 재호출)로 재시도.

- **질문 근거 표시**: `evidence.slides` / `evidence.transcript_refs`.
- **질문 전략(C)**: 각 질문은 `strategy`(§6.1 `QuestionStrategy`)를 가지며, 리포트의 `type_scores`가 이 값으로 집계됩니다.
- **질문 표시/음성**: 질문은 **텍스트로 화면에 표시**하고 `tts.audio_url`을 1회 재생한다. 텍스트를 병기하므로 **"다시 듣기" UI는 제공하지 않는다**(동일 `audio_url` 재생 계약 자체는 유지). `tts.status = failed` 시 질문 상세를 폴링하며, 재생성이 필요하면 별도 협의(후속).
- **답변 시작 제한시간(30초)**: 질문 음성 재생이 끝나면 클라이언트가 **30초 카운트다운**을 띄우고, 사용자가 답변을 시작(녹음 시작)하면 카운트다운을 멈춘다. 30초 내 미시작 시 클라이언트가 자동으로 `pass`(`reason=timeout`) 처리한다. 녹음 지속시간 상한은 없으며, **API는 결과 오디오만 수신**한다.

> **종료 조건**(A12): 사용자 `qna/end` > 설정 질의 수(1차 질문 기준) 도달 > 답변 시작 시간초과(재생 완료 후 30초 내 미시작 → 자동 다음). 시간초과는 클라이언트가 감지해 `pass(reason=timeout)`로 처리하고, 서버가 `ended_reason`(마지막 질문이 시간초과면 `timeout`)을 확정.

### 4.5 세션 저장

별도 저장 엔드포인트 없음 — 세션은 파이프라인 진행에 따라 **자동 영속화**. 발표 1회 = `slides.json + transcript.json + Q&A 로그(질문/답변/페르소나/전략/스킵) + 설정값`이 세션 리소스로 저장됩니다(A7·명세 준수).

---

## 5. 이전 발표 열람 & 분석 리포트

### 5.1 열람 (탭 = 위 세션 하위 리소스 재사용)

| 탭      | 데이터                                                                 |
| ------ | ------------------------------------------------------------------- |
| 스크립트   | `GET /sessions/{id}/transcript`                                     |
| Q&A 로그 | `GET /sessions/{id}/qna`                                            |
| 리포트    | `GET /sessions/{id}/report`                                         |
| 재생     | `recording.audio_url`, `question.tts.audio_url`, `answer.audio_url` |

### 5.2 분석 리포트 (C: `type_scores`, E: 성장은 유저 스코프)

| Method | Path                                            | 설명                     | 권한 |
| ------ | ----------------------------------------------- | ---------------------- | --- |
| GET    | `/sessions/{sessionId}/report`                  | 단일 세션 리포트(답변 품질·발표 습관) | 멤버 |
| POST   | `/sessions/{sessionId}/report/generate`         | 수동 재생성(기본은 종료 시 자동)    | owner |
| GET    | `/users/me/report/growth?range=all\|recent5&team_id=` | **내** 성장 리포트(회차 비교). `team_id`로 팀 필터(선택) | 본인 |

**GET /report 응답** (C: `type_scores` 추가 — 성장 시리즈가 이 값에서 파생)

```
{
  "status": "ready",           // queued | processing | ready | failed
  "type_scores": {             // QuestionStrategy별 답변 점수 0.0~1.0 (성장 리포트의 원천)
    "detail_probe": 0.40,
    "big_picture": 0.85,
    "basic_concept": 0.80,
    "numeric_verification": 0.35
  },
  "answer_quality": {          // type_scores에서 파생된 상/하위 분류(임계값 기준)
    "strong_types": ["big_picture", "basic_concept"],
    "weak_types": ["detail_probe", "numeric_verification"]
  },
  "speaking_habits": {
    "words_per_minute": 182,
    "filler_words": [ { "word": "음", "count": 9 }, { "word": "어", "count": 5 } ],
    "time_limit_seconds": 600, "actual_seconds": 663, "over_time": true
  },
  "insight": "필러 워드가 도입부에 몰려 있어요. 첫 1분 대본을 미리 정해두면 좋아요."
}
```
> `filler_word_count`(합계)와 `over_time`(`actual_seconds > time_limit_seconds`)은 클라이언트에서 파생 가능하므로 응답에서 제외.
> **v0.3 영향(정제 제거):** `filler_words`·`words_per_minute`는 이제 **원문 transcript** 기준으로 집계됩니다. 정제 패스가 간투사를 지우지 않으므로 필러 검출이 오히려 정확해집니다(원문에 간투사가 그대로 남음). `words_per_minute`는 **콘텐츠 어절 기준(간투사 제외)** 으로 집계됩니다(팀 결정 2026-07-13) — 필러는 `filler_words`로 별도 측정하므로 이중 계산을 피합니다. 리포트/질문 생성용 LLM은 외부 API이므로 로컬 정제 LLM 제거의 영향을 받지 않습니다.

**GET /users/me/report/growth 응답** (E: 유저 스코프 — `type_scores`에서 파생)

```
{
  "range": "all",
  "user_id": "usr_1",
  "team_id": null,             // 필터 없으면 내 전체 세션
  "series": [
    { "session_id": "ses_1", "name": "1차 발표", "date": "2026-07-08", "type_scores": { "detail_probe": 0.40 } },
    { "session_id": "ses_2", "name": "2차 발표", "date": "2026-07-09", "type_scores": { "detail_probe": 0.62 } }
  ],
  "insight": "디테일 추궁형 점수가 2회차 연속 올랐어요. 수치 검증형은 아직 준비가 필요해요."
}
```

---

## 6. 열거형 & 에러 코드

### 6.1 Enums

| Enum                | 값                                                                                                        |
| ------------------- | -------------------------------------------------------------------------------------------------------- |
| `QuestionerPersona` | `egen`(에겐) · `teto`(테토) · `kkondae`(꼰대) · `mungcheong`(멍청) · `jammin`(잼민)                                |
| `QuestionStrategy`  | `detail_probe`(디테일 추궁형) · `big_picture`(큰그림형) · `basic_concept`(기초 개념형) · `numeric_verification`(수치 검증형) |
| `SessionStatus`     | `draft · recording_in_progress · transcribing · generating_questions · qna · completed · failed`         |
| `AsyncStatus`       | `queued · processing · ready · failed` (모든 async 리소스 공통, D)                                              |
| `AnswerStatus`      | `pending · processing · ready · failed`                                                                   |
| `FollowUpStatus`    | `pending · generated · none`                                                                              |
| `QnaStatus`         | `in_progress · ended`                                                                                     |
| `SessionMode`       | `realtime · upload`                                                                                       |

### 6.2 주요 에러 코드

| code                                              | HTTP    | 의미                     |
| ------------------------------------------------- | ------- | ---------------------- |
| `UNAUTHORIZED` / `TOKEN_EXPIRED`                  | 401     | 미인증 / 액세스 만료(→refresh) |
| `FORBIDDEN_NOT_LEADER`                            | 403     | 팀장 전용 작업               |
| `FORBIDDEN_NOT_OWNER`                             | 403     | 세션 소유자 전용 작업(F)        |
| `TEAM_NOT_FOUND` / `SESSION_NOT_FOUND`            | 404     | 리소스 없음                 |
| `INVITE_INVALID`                                  | 409     | 초대 무효(회전/취소됨 등)        |
| `INVITE_EXPIRED`                                  | 410     | 초대 만료                  |
| `FILE_TOO_LARGE`                                  | 413     | 용량 초과                  |
| `UNSUPPORTED_MEDIA`                               | 415     | 형식 미지원                 |
| `UNPROCESSABLE_PDF`                               | 422     | 스캔본/텍스트 추출 불가          |
| `STT_FAILED` / `TTS_FAILED` / `GENERATION_FAILED` | 503     | 모델·외부 API 오류(재시도)      |
| `EMAIL_NOT_VERIFIED`                              | 403     | 이메일 인증 미완료             |

---

## 7. 실시간/진행률 (선택적 확장)

폴링(A2)이 기본이나, 진행률 UX가 중요한 화면은 아래를 선택 적용 가능:

- **SSE**: `GET /sessions/{id}/events` → `material`, `transcript`, `qna`(꼬리질문 생성 포함), `report` 상태 변화 스트림
- **WebSocket**: 실시간 Q&A 세션(질문 push, 답변 결과·꼬리질문 push)을 단일 커넥션으로 처리
- 도입 시 위 폴링 엔드포인트는 폴백으로 유지.

---

## 8. 미결정 · 후속 논의

- **데이터 보관 정책**(A10): 녹음/음성 원본 보관 기간·용량 상한. (세션 삭제 cascade 범위는 §4.1에서 **확정**됨)
- **TTS 엔진 확정**(VoxCPM2 self-hosted): 동시성 한계 → 큐 깊이/대기시간 SLA, 페르소나별 음성 매핑, `tts.status=failed` 재생성 정책.
- **STT 엔진**: `Qwen3-ASR 1.7B` + `Qwen3-ForcedAligner 0.6B`. 한국어 지원·변환 소요시간(A2 폴링 간격 근거) — **실측 완료(2026-07-11)**: RTF ≈ 0.03~0.05(실시간 대비 ~20–30배 빠름), 5분 오디오 전사 ~9.7s, 답변(단발) 전사 ~1–2s. → **A2 폴링 1~2초 확정 근거**. 발표 녹음 청크 길이 **60초 + 4초 겹침**으로 확정(불변 조건 처리시간<청크길이를 ~30배 여유로 만족). 상세: [infra/gpu-server README — STT 실측 & 청크 크기 결정](../infra/gpu-server/README.md#stt-실측--청크-크기-결정-day-3-팀원3).
- **질문 생성 프롬프트 전략**: '슬라이드에 있으나 미언급' / '언급했으나 근거 약함' 타게팅(명세) — 서버 내부 로직, API 계약엔 영향 없음.
- **레이트리밋/쿼터**: 외부 LLM 비용 기반 상한.

### 8.1 로컬 추론 구성 (참고 — API 계약 아님, v0.3)
 
정제용 로컬 LLM(`Qwen3-4B`) 제거로 상주 모델이 2개(STT·TTS)로 축소됨. 질문 생성·리포트 분석용 LLM은 **외부 API**라 이 예산에 포함되지 않음.
 
| 구성                              | 무게(실제) | 상한(캡) | util |
| ------------------------------- | ------ | ----- | ---- |
| VoxCPM2 — TTS (vLLM-Omni)       | ~5 GB  | 10 GB | 0.42 |
| Qwen3-ASR 1.7B + Aligner 0.6B — STT | ~4 GB  | 8 GB  | 0.33 |
| CUDA 컨텍스트 ×2 프로세스              | ~1 GB  | 1 GB  | —    |
| 여유분                             | ~5 GB  | —     | —    |
 
> RTX 3090 24GB 전부 상주 기준. 정제 LLM 제거로 확보된 VRAM은 TTS/STT 동시성(캡·KV 캐시)에 재배분.

---

## 부록 A. 기능명세서 ↔ 엔드포인트 추적표

| 명세 대분류    | 기능                      | 엔드포인트                                                                         |
| --------- | ----------------------- | ----------------------------------------------------------------------------- |
| 애플리케이션 접속 | 로그인/소셜/자동로그인            | `POST /auth/login`, `/auth/login/social/{p}`, `/auth/refresh`, `GET /auth/me` |
|           | 회원가입(이메일 인증)            | `POST /auth/signup`, `/auth/email/verify`                                     |
|           | 아이디·비번 찾기               | (정적 화면, 엔드포인트 없음)                                                             |
| 메인        | 팀 목록/추가                 | `GET/POST /teams`                                                             |
|           | 마이페이지                   | `GET/PATCH/DELETE /users/me`                                                  |
| 프레젠테이션 팀  | 팀 만들기·초대(이메일/링크)·수락     | `POST /teams`, `/teams/{id}/invites`, `/teams/{id}/invites/link`, `/invites/{token}/accept` |
|           | 팀 선택/탈퇴/삭제              | `GET /teams/{id}`, `POST /teams/{id}/leave`, `DELETE /teams/{id}`             |
| 발표 & 질의응답 | 발표자료 업로드/슬라이드 추출/전처리 상태 | `POST/GET /sessions/{id}/material` (+retry)                                   |
|           | 발표 설정(페르소나·질의수·제한시간)    | `POST /teams/{id}/sessions`                                                   |
|           | 발표하기(녹음)/녹음파일 업로드       | `POST /sessions/{id}/recording(/start)`                                       |
|           | STT 변환                  | `GET /sessions/{id}/transcript`                                               |
|           | AI 질의 생성/페르소나 스타일       | `POST /sessions/{id}/qna/generate`                                            |
|           | 질의 TTS 출력·재생/근거 표시      | `GET /qna/questions/{qid}` (`tts`, `evidence`, `strategy`)                    |
|           | 질의 답변(STT)/꼬리질문/종료/스킵   | `POST /answer`(202) → `GET /qna` 폴링, `/pass`, `/qna/end`                      |
|           | 세션 저장                   | (자동 영속화)                                                                      |
| 이전 발표     | 상세 열람/삭제/보관정책           | `GET /sessions/{id}` 하위, `DELETE /sessions/{id}`                              |
| 내 발표 분석   | 답변품질/발표습관/성장리포트/생성시점    | `GET /sessions/{id}/report`, `GET /users/me/report/growth`                    |
| 마이페이지     | 계정 관리                   | `/users/me`                                                                   |
| 공통        | 마이크 권한                  | (클라이언트 전용)                                                                    |
|           | 오류·이탈 처리                | 에러 포맷 §1.1, 이어하기 = 세션 상태 재조회                                                  |

## 부록 B. 와이어프레임 ↔ 엔드포인트

| 화면(그룹)   | 주요 호출                                                                             |
| -------- | --------------------------------------------------------------------------------- |
| 01 인증    | `/auth/*`                                                                         |
| 02 메인    | `GET /teams`                                                                      |
| 03 팀     | `POST /teams`, `/teams/{id}/invites*`, `/teams/{id}/invites/link`, `/invites/{token}/*`, `DELETE /teams/{id}` |
| 04 발표 준비 | `POST /teams/{id}/sessions`, `POST/GET /sessions/{id}/material`                   |
| 05 발표 진행 | `POST /sessions/{id}/recording*`, `GET /sessions/{id}/transcript`                 |
| 06 질의응답  | `POST /qna/generate`, `GET /qna`, `POST /qna/questions/{qid}/answer`, `POST /qna/end` |
| 07 이전 발표 | `GET /sessions/{id}` (transcript·qna 탭), `DELETE /sessions/{id}`                  |
| 08 분석    | `GET /sessions/{id}/report`, `GET /users/me/report/growth`                        |
| 09 마이페이지 | `/users/me*`                                                                      |
| 10 공통    | 에러/권한/이어하기                                                                        |
