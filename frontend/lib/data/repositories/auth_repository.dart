import '../../core/network/api_client.dart';
import '../models/app_user.dart';
import '../models/auth.dart';

/// 인증 리포지토리 — ApiClient(백엔드 추상화) 경유 단일 구현.
/// Mock/실서버 전환은 백엔드 주입으로 결정되므로 별도 Mock 클래스가 없다.
class AuthRepository {
  AuthRepository(this._api);

  final ApiClient _api;

  Future<AuthTokens> login({
    required String username,
    required String password,
  }) =>
      _api.login('/auth/login', {'username': username, 'password': password});

  Future<void> signup({
    required String name,
    required String username,
    required String password,
    required String email,
  }) =>
      _api.post('/auth/signup', body: {
        'name': name,
        'username': username,
        'password': password,
        'email': email,
      });

  Future<void> verifyEmail(String email, String code) =>
      _api.post('/auth/email/verify', body: {'email': email, 'code': code});

  /// 인증코드 재발송 — 유저가 없어도 204 (계정 존재 노출 방지, §9).
  Future<void> requestEmailVerification(String email) =>
      _api.post('/auth/email/verify-request', body: {'email': email});

  /// 아이디 찾기 — 가입된 이메일이면 아이디를 메일로 보낸다. 유저가 없어도 204
  /// (계정 존재 노출 방지). 아이디는 응답 본문에 오지 않는다 (§2).
  Future<void> findUsername(String email) =>
      _api.post('/auth/username/find', body: {'email': email});

  /// 비밀번호 재설정 코드 발송 — 유저가 없어도 204. 60초 쿨다운은 429 (§2).
  Future<void> requestPasswordReset(String email) =>
      _api.post('/auth/password/reset-request', body: {'email': email});

  /// 비밀번호 재설정 — 코드 + 새 비밀번호. 성공 시 기존 세션은 서버에서 폐기된다 (§2).
  Future<void> resetPassword({
    required String email,
    required String code,
    required String newPassword,
  }) =>
      _api.post('/auth/password/reset', body: {
        'email': email,
        'code': code,
        'new_password': newPassword,
      });

  /// 현재 유저 조회 — 응답은 user 래핑 없이 평평한 형태 (backend /auth/me,
  /// test_auth_me.py 계약: {id, name, username, email}).
  Future<AppUser> me() async {
    final json = await _api.get('/auth/me') as Map<String, dynamic>;
    return AppUser.fromJson(json);
  }

  /// 앱 시작 시 저장된 세션으로 로그인 상태를 복원한다 (새로고침 후 유지).
  /// Web은 httpOnly 쿠키로 새 access 토큰을 발급받는다. 성공 여부를 반환하며,
  /// 성공 시 호출자는 [me]로 사용자 정보를 다시 받아온다.
  Future<bool> restoreSession() => _api.tryRestoreSession();

  Future<void> logout() => _api.logout();

  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) =>
      _api.patch('/users/me/password', body: {
        'current_password': currentPassword,
        'new_password': newPassword,
      });

  Future<void> deleteAccount() => _api.delete('/users/me');
}
