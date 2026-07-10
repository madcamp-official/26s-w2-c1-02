import '../models/app_user.dart';

/// 인증 데이터 소스 추상화.
///
/// 지금은 [MockAuthRepository]로 더미 로그인만 제공한다.
/// 추후 카카오/구글 OAuth 또는 이메일 로그인으로 교체 시
/// 이 인터페이스를 구현하는 ApiAuthRepository를 붙이면 된다.
abstract class AuthRepository {
  Future<AppUser> login({String? id, String? password});
  Future<AppUser> loginWithProvider(String provider);
  Future<void> logout();
}

class MockAuthRepository implements AuthRepository {
  @override
  Future<AppUser> login({String? id, String? password}) async {
    await Future<void>.delayed(const Duration(milliseconds: 250));
    return const AppUser(
      id: 'u_1',
      name: 'user',
      email: 'user@rehearsal.io',
    );
  }

  @override
  Future<AppUser> loginWithProvider(String provider) async {
    await Future<void>.delayed(const Duration(milliseconds: 250));
    return AppUser(
      id: 'u_$provider',
      name: 'user',
      email: 'user@$provider.com',
    );
  }

  @override
  Future<void> logout() async {
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
}
