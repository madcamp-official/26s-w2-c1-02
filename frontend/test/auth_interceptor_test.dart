import 'package:flutter_test/flutter_test.dart';
import 'package:rehearsal/core/network/api_client.dart';
import 'package:rehearsal/core/network/mock_backend.dart';
import 'package:rehearsal/data/models/enums.dart';

/// 인증 인터셉터 검증 (workflow Step 1).
/// MockBackend가 HTTP 레벨을 흉내내므로 401 TOKEN_EXPIRED → refresh → 재시도가
/// 실서버와 동일한 코드 경로로 동작한다.
void main() {
  MockBackend backend() => MockBackend(latency: Duration.zero);

  test('로그인하면 access 토큰이 저장되고 인증 API가 동작한다', () async {
    final api = ApiClient(backend: backend(), platform: ClientPlatform.web);
    final tokens =
        await api.login('/auth/login', {'username': 'junseo', 'password': 'x'});

    expect(tokens.accessToken, isNotEmpty);
    expect(api.tokenStore.accessToken, tokens.accessToken);

    // /auth/me는 user 래핑 없이 평평한 형태 (실서버 계약과 동일).
    final me = await api.get('/auth/me') as Map<String, dynamic>;
    expect(me['username'], 'junseo');
  });

  test('Native: 401 TOKEN_EXPIRED → refresh(본문 토큰) → 원요청 자동 재시도', () async {
    final mock = backend();
    final api = ApiClient(backend: mock, platform: ClientPlatform.ios);
    await api.login('/auth/login', {'username': 'junseo', 'password': 'x'});

    // Native는 refresh 토큰을 TokenStore에 보관해야 함 (spec §2 B).
    expect(api.tokenStore.refreshToken, isNotNull);

    final oldAccess = api.tokenStore.accessToken;
    mock.expireAccessTokens(); // 서버측 강제 만료

    // 인터셉터가 refresh 후 재시도 → 예외 없이 성공해야 한다.
    final res = await api.get('/teams') as Map<String, dynamic>;
    expect(res['items'], isNotEmpty);

    // 새 access 토큰으로 교체됐는지 확인.
    expect(api.tokenStore.accessToken, isNot(oldAccess));
  });

  test('Web: refresh 본문 없이(쿠키 흉내) 만료 복구 + refresh 토큰은 저장 안 함', () async {
    final mock = backend();
    final api = ApiClient(backend: mock, platform: ClientPlatform.web);
    await api.login('/auth/login', {'username': 'junseo', 'password': 'x'});

    // Web은 refresh를 앱이 저장하지 않음 (httpOnly 쿠키 — spec §2 B).
    expect(api.tokenStore.refreshToken, isNull);

    mock.expireAccessTokens();
    final res = await api.get('/teams') as Map<String, dynamic>;
    expect(res['items'], isNotEmpty);
  });

  test('Web: tryRestoreSession() — access 토큰 없이도 쿠키로 세션 복원 (새로고침 시나리오)',
      () async {
    final api = ApiClient(backend: backend(), platform: ClientPlatform.web);

    // 새로고침 직후 상태: 메모리가 비어 access 토큰이 없다.
    expect(api.tokenStore.accessToken, isNull);

    // httpOnly refresh 쿠키(Mock이 흉내냄)로 세션을 되살린다.
    final ok = await api.tryRestoreSession();
    expect(ok, isTrue); // 복원 성공
    expect(api.tokenStore.accessToken, isNotNull); // 새 access 발급됨

    // 복원된 토큰으로 인증 API가 곧바로 동작한다 (평평한 응답 형태).
    final me = await api.get('/auth/me') as Map<String, dynamic>;
    expect(me['username'], isNotEmpty);
  });

  test('유효하지 않은 토큰(만료 아님)은 재시도 없이 세션 종료 통지', () async {
    final api = ApiClient(backend: backend(), platform: ClientPlatform.web);
    await api.login('/auth/login', {'username': 'junseo', 'password': 'x'});

    var expired = false;
    api.onAuthExpired = () => expired = true;

    // 서버가 모르는 토큰 → 401 UNAUTHORIZED (TOKEN_EXPIRED 아님) → refresh 안 함.
    await api.tokenStore.saveAccessToken('acc_invalid');

    await expectLater(api.get('/teams'), throwsA(isA<ApiException>()));
    expect(expired, isTrue);
    expect(api.tokenStore.accessToken, isNull); // 토큰 정리됨
  });

  test('X-Client-Platform 헤더가 요청에 실린다', () async {
    final api = ApiClient(backend: backend(), platform: ClientPlatform.android);
    final tokens =
        await api.login('/auth/login', {'username': 'junseo', 'password': 'x'});
    // MockBackend가 받은 플랫폼을 에코해줌.
    expect(tokens.user.id, 'usr_1');
    final raw = await api.post('/auth/refresh',
        body: {'refresh_token': api.tokenStore.refreshToken});
    expect((raw as Map<String, dynamic>)['_platform_echo'], 'android');
  });
}
