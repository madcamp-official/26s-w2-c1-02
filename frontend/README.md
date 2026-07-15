# Rehearsal.io "말꼬리" — Frontend (Flutter)

크로스플랫폼(Web / Android / iOS) 발표 리허설 & AI 질의응답 앱.
자료 업로드 → 발표 녹음(실시간 청크 업로드) → AI 질문 TTS 듣고 음성으로 답변 → 분석·성장 리포트까지 전체 플로우를 단일 Flutter 코드베이스로 구현.

| 분류 | 기술 |
|---|---|
| 라우팅 | go_router (웹 URL 딥링크·초대 링크 지원) |
| 상태관리 | provider + ChangeNotifier 컨트롤러 |
| 오디오 | record(녹음) + just_audio(재생), 자체 PCM 청커·WAV 코덱 |
| 네트워킹 | http + 자체 `ApiClient` 인터셉터 (Mock ↔ 실서버 주입 전환) |
| 파일 | file_picker (PDF·PPTX 업로드) |
| 폰트/테마 | Pretendard · NanumSquareRound, Figma 팔레트 |

## 실행 방법

```bash
cd frontend
flutter pub get

# 웹
flutter run -d chrome

# 모바일 (에뮬레이터/기기 연결 후)
flutter run
```

기본은 **Mock 모드**(`USE_MOCK=true`)라 백엔드 없이도 전체 플로우가 동작한다.
실제 FastAPI 백엔드에 붙이려면:

```bash
flutter run -d chrome \
  --dart-define=USE_MOCK=false \
  --dart-define=API_BASE_URL=http://localhost:8000
```

> 프로덕션 웹 배포는 VM에서 루트의 [update.sh](../update.sh)가 처리한다 — `flutter build web --release` (+ `API_BASE_URL=https://horsetail.madcamp-kaist.org`) → nginx `/var/www/rehearsal` 동기화 + 캐시버스트.

## Android 배포용 APK 빌드 & 업데이트

테스터에게 파일을 직접 전달하는 방식(사설 배포). **Flutter·Android SDK 가 설치된 본인 개발 머신**에서 진행한다. 상세 절차는 [docs/android-apk-release.md](../docs/android-apk-release.md) 참고.

### 최초 1회 — 서명 키 만들기

업데이트를 매끄럽게 하려면(같은 키로 서명해야 앱을 덮어쓰기 설치 가능) 고정 키가 필요하다.

```bash
# 1) 키스토어 생성 (비밀번호는 본인이 정하고 잘 보관/백업)
keytool -genkey -v -keystore ~/rehearsal-release.jks \
  -keyalg RSA -keysize 2048 -validity 10000 -alias rehearsal

# 2) key.properties 작성
cp android/key.properties.example android/key.properties
#    → storeFile 경로/비밀번호/alias 채우기
```

`android/key.properties` 와 `.jks` 파일은 **절대 커밋 금지**(.gitignore 등록됨).
`.jks` 를 잃어버리면 기존 앱에 업데이트를 설치할 수 없으니 안전하게 백업할 것.

### 빌드

```bash
./build-apk.sh   # 프로덕션 서버 주소(horsetail.madcamp-kaist.org)를 박아 빌드
# → build/app/outputs/flutter-apk/app-release.apk
```

이 파일을 테스터에게 직접 전달(카톡/드라이브/이메일)하면, 탭 → 설치로 끝난다.

### 업데이트 낼 때

1. `pubspec.yaml` 의 `version` 을 올린다 — **`+` 뒤 숫자(versionCode)는 반드시 증가**: `0.1.0+1` → `0.1.1+2`
2. `./build-apk.sh` 다시 실행.
3. 새 APK 를 다시 전달 → 테스터가 탭하면 **덮어쓰기 업데이트**(데이터 유지).

> 같은 서명 키를 쓰는 한 덮어쓰기 설치가 되고, 키가 바뀌면 "기존 앱 삭제 후 재설치" 를 해야 한다.

## 화면 ↔ 라우트

다이얼로그·바텀시트류(팀 관리, 삭제 확인, 마이크 권한, 오류·이탈 확인)는 라우트가 아니라 해당 화면의 오버레이로 구현.

| 그룹 | 라우트 | 화면 파일 (`lib/features/`) |
|---|---|---|
| 부팅 | `/splash` | `common/splash_page.dart` — 새로고침 세션 복원 중 |
| 인증 | `/login` | `auth/login_page.dart` |
| | `/signup` | `auth/signup_page.dart` |
| | `/verify-email?email=&send=1` | `auth/verify_email_page.dart` — 이메일 인증코드 |
| | `/account-recovery` | `auth/account_recovery_page.dart` — 아이디 찾기·비밀번호 재설정 |
| 메인 | `/` | `home/home_page.dart` |
| 마이페이지 | `/me` | `profile/my_page.dart` |
| | `/me/password` | `profile/change_password_page.dart` |
| | `/me/growth` | `report/growth_report_page.dart` — 회차 비교 성장 리포트 |
| 팀 | `/teams/new` | `team/create_team_page.dart` |
| | `/teams/:teamId` | `team/team_detail_page.dart` |
| | `/invites/:token` | `team/invite_accept_page.dart` — 초대 수락 (미리보기는 인증 불필요) |
| 발표 준비 | `/teams/:teamId/sessions/new` | `session/create_session_page.dart` — 자료·페르소나·질의 수 설정 |
| | `/teams/:teamId/sessions/:sid/edit` | `session/create_session_page.dart` — draft 이어하기(옵션 프리필) |
| | `/sessions/:sid/material` | `session/material_status_page.dart` — 자료 파싱 폴링 |
| | `/sessions/:sid/upload-recording` | `session/upload_recording_page.dart` — 녹음 파일 업로드 모드 |
| 발표 진행 | `/sessions/:sid/present` | `session/presenting_page.dart` — 녹음 + 60초 청크 실시간 업로드 |
| | `/sessions/:sid/processing` | `session/processing_page.dart` — 전사·질문 생성 대기 |
| | `/sessions/:sid/qna-confirm` | `session/qna_confirm_page.dart` — 질의응답 진입 확인 |
| 질의응답 | `/sessions/:sid/qna` | `session/qna_page.dart` — 질문 TTS 재생 → 음성 답변 → 꼬리질문 |
| | `/sessions/:sid/qna/complete` | `session/qna_complete_page.dart` |
| 이전 발표 | `/sessions/:sid` | `session/session_detail_page.dart` — 스크립트/Q&A/리포트 탭 |

## 구조

```
lib/
├── main.dart / app.dart       # 엔트리포인트 — 백엔드·repository·controller·라우터 조립
├── core/
│   ├── config/env.dart        # USE_MOCK / API_BASE_URL (--dart-define)
│   ├── network/
│   │   ├── api_client.dart    # 인터셉터: Bearer + X-Client-Platform 부착, TOKEN_EXPIRED 시 refresh 후 1회 재시도
│   │   ├── http_backend.dart  # RealHttpBackend ↔ MockBackend 공용 인터페이스
│   │   ├── mock_backend.dart  # 백엔드 없이 전체 플로우 동작하는 인메모리 Mock
│   │   └── token_store.dart   # 플랫폼별 토큰 보관 (Web=httpOnly 쿠키 위임 / Native=메모리+refresh 본문)
│   ├── audio/
│   │   ├── recorder_service.dart   # record 기반 마이크 녹음
│   │   ├── pcm_chunker.dart        # 발표 녹음 60초+4초 겹침 청크 분할
│   │   ├── wav_codec.dart          # PCM → WAV 인코딩
│   │   └── audio_player_service.dart  # just_audio 기반 TTS/녹음 재생
│   ├── router/app_router.dart # go_router — 인증 리다이렉트·세션 복원(splash) 처리
│   ├── files/                 # 업로드 파일 제약 (크기·확장자)
│   └── theme/                 # 색상/테마 (Figma 팔레트)
├── data/
│   ├── models/                # User/Team/Session/Qna/Report/Transcript + enum (BE 스키마와 1:1)
│   └── repositories/          # Auth/Team/Session repository (ApiClient 사용)
├── state/                     # AuthController / TeamController / SessionController (ChangeNotifier)
└── features/                  # 화면별 위젯 (위 라우트 표) + common/ (폴링 빌더, 반응형 래퍼 등)
```

## 아키텍처 원칙

- **Mock ↔ 실서버 = 주입 한 곳**: `app.dart`에서 `HttpBackend` 구현체(Mock/Real) 하나만 갈아끼운다. 인터셉터·repository·화면 코드는 두 모드에서 완전히 동일한 경로를 탄다.
- **UI ↔ 데이터 분리**: 화면은 `state/*Controller`만 알고, 컨트롤러는 repository만 안다.
- **인증 인터셉터**: 모든 요청에 access 토큰 + `X-Client-Platform`을 부착하고, `401 TOKEN_EXPIRED`면 `/auth/refresh` 후 1회 재시도(동시 refresh는 Future 공유로 방지). 새로고침 시 저장된 세션(Web=httpOnly 쿠키)으로 자동 복원 — 복원이 끝날 때까지 라우터가 `/splash`에 고정한다.
- **비동기 폴링**: 자료 파싱·전사·질문 생성·답변 STT·리포트 등 백엔드 202 작업은 `common/polling_builder.dart`로 1~2초 간격 폴링.
- **크로스플랫폼**: 모바일 우선 디자인을 `ResponsivePage`로 감싸 웹/태블릿에서 가운데 정렬. 플랫폼 분기는 토큰 저장(쿠키 vs 본문)과 http 클라이언트(`http_client_io/web.dart`)에만 존재.
