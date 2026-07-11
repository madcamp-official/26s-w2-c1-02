/// 토큰 보관 추상화.
///
/// - access 토큰: 항상 메모리 (짧은 수명).
/// - refresh 토큰: Web은 httpOnly 쿠키(브라우저 관리 — 앱은 저장 안 함),
///   Native는 향후 flutter_secure_storage 구현으로 교체 (Step 4, 팀 협의).
abstract class TokenStore {
  String? get accessToken;
  String? get refreshToken;

  Future<void> saveAccessToken(String token);

  /// Native에서만 호출됨 (Web은 refresh가 본문에 없음).
  Future<void> saveRefreshToken(String token);

  Future<void> clear();
}

/// 기본 구현: 전부 메모리. Mock 단계 + Web(쿠키 방식)에서는 이걸로 충분.
class InMemoryTokenStore implements TokenStore {
  String? _access;
  String? _refresh;

  @override
  String? get accessToken => _access;

  @override
  String? get refreshToken => _refresh;

  @override
  Future<void> saveAccessToken(String token) async => _access = token;

  @override
  Future<void> saveRefreshToken(String token) async => _refresh = token;

  @override
  Future<void> clear() async {
    _access = null;
    _refresh = null;
  }
}
