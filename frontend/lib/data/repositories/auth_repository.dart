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

  Future<AppUser> me() async {
    final json = await _api.get('/auth/me') as Map<String, dynamic>;
    return AppUser.fromJson(json['user'] as Map<String, dynamic>);
  }

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
