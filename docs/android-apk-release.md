# Android APK 배포 인수인계

말꼬리(Rehearsal) Flutter 앱을 안드로이드 테스터에게 **파일 직접 전달** 방식으로 배포하기 위한 안내서.

- **대상 독자**: APK 를 빌드할 **Flutter 개발 머신 담당자** (필수), 그리고 나중에 도메인에서 다운로드로 배포하고 싶을 때의 **서버 담당자** (선택).
- **전제**: 앱 코드에는 이미 서명·빌드 설정이 반영되어 있음(커밋 `d226b8c`). 이 문서의 명령들은 **Flutter·Android SDK 가 설치된 개발 머신**에서 실행한다. GPU 서버(`camp-2`)에는 안드로이드 툴체인이 없어 빌드 불가.
- **백엔드**: 앱은 빌드 시 `https://malggori.madcamp-kaist.org` 를 API 주소로 박아 넣는다(`build-apk.sh` 에 반영됨).

---

## A. Flutter 머신 담당자 — 여기만 하면 됨

### A-0. 사전 확인 (최초 1회)

```bash
flutter doctor        # Flutter + Android toolchain(✓) 확인
cd frontend
flutter pub get
```

`flutter doctor` 에서 Android SDK / cmdline-tools 가 빠져 있으면 먼저 설치해야 빌드가 된다.

### A-1. 서명 키 만들기 (최초 1회, 매우 중요)

업데이트를 **덮어쓰기 설치**로 매끄럽게 하려면 모든 버전을 **같은 키**로 서명해야 한다.
키가 바뀌면 테스터가 기존 앱을 삭제 후 재설치해야 한다(데이터 손실).

```bash
# 1) 키스토어 생성 — 비밀번호는 직접 정하고, 잊지 말고 안전하게 보관
keytool -genkey -v -keystore ~/rehearsal-release.jks \
  -keyalg RSA -keysize 2048 -validity 10000 -alias rehearsal

# 2) 서명 정보 파일 작성
cd frontend
cp android/key.properties.example android/key.properties
#   → android/key.properties 를 열어 값 채우기:
#       storePassword = 위에서 정한 키스토어 비밀번호
#       keyPassword   = 위와 동일(보통)
#       keyAlias      = rehearsal
#       storeFile     = /절대/경로/rehearsal-release.jks
```

> ⚠️ **절대 커밋 금지**: `android/key.properties`, `~/rehearsal-release.jks`
> (`.gitignore` 에 이미 등록돼 있음).
> ⚠️ **`.jks` 백업 필수**: 이 파일을 잃어버리면 **기존 설치 앱에 업데이트를 낼 수 없다.**
> 안전한 곳(비밀번호 매니저/암호화 저장소)에 백업할 것.

### A-2. APK 빌드

```bash
cd frontend
./build-apk.sh
```

결과물: `frontend/build/app/outputs/flutter-apk/app-release.apk`

### A-3. 전달

이 `app-release.apk` 파일을 테스터에게 직접 전달(카카오톡 / 구글 드라이브 / 이메일).
테스터는 파일을 탭 → "이 출처에서 설치 허용?" → 허용 → 설치 완료.

---

## B. 업데이트 내는 법

1. `frontend/pubspec.yaml` 의 버전을 올린다 — **`+` 뒤 숫자(versionCode)는 반드시 증가**:

   ```yaml
   version: 0.1.0+1   →   0.1.1+2
   ```

   `+` 뒤 숫자가 그대로거나 낮으면 안드로이드가 "업데이트 아님"으로 설치를 거부한다.

2. 다시 빌드:

   ```bash
   cd frontend && ./build-apk.sh
   ```

3. 새 `app-release.apk` 를 다시 전달 → 테스터가 탭하면 **덮어쓰기 업데이트**(로그인·데이터 유지).

> 사설 전달 방식은 **자동 업데이트가 없다.** 새 버전이 나오면 테스터에게 직접 알려줄 것.
> `pubspec.yaml` 의 버전 이름(`0.1.1`)은 휴대폰 앱 정보에 표시되니, 사람이 알아보게 올려두면 좋다.

---

## C. (선택) 서버 담당자 — 도메인에서 다운로드로 배포하고 싶을 때만

현재는 파일 직접 전달 방식이라 **서버 작업은 필요 없다.**
나중에 `https://malggori.madcamp-kaist.org` 에서 APK 를 내려받게 하고 싶다면:

```bash
# Flutter 담당자가 만든 app-release.apk 를 nginx 웹 루트로 복사
sudo cp app-release.apk /var/www/rehearsal/malggori.apk
```

그러면 `https://malggori.madcamp-kaist.org/malggori.apk` 로 다운로드 가능.

nginx 가 파일을 열어버리지 않고 다운로드하도록, APK MIME 타입을 확인/추가:

```
# mime.types 에 추가
application/vnd.android.package-archive  apk;
```

또는 해당 경로에 `add_header Content-Disposition attachment;` 설정.

---

## 참고 — 왜 이렇게 되어 있나 (빌드 설정 요약)

- API 주소는 빌드 시 `--dart-define=API_BASE_URL=...` 로 앱에 박힌다
  (`frontend/lib/core/config/env.dart`, 기본값은 `localhost` 라서 반드시 이 플래그로 빌드해야 함).
- 서명은 `frontend/android/app/build.gradle.kts` 가 `key.properties` 유무로 자동 분기:
  파일 있으면 release 키, 없으면 debug 키(개발용). **배포용은 반드시 release 키.**
- iOS 는 이 문서 범위 밖(별도 방법 사용 중).
