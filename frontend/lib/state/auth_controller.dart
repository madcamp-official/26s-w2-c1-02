import 'package:flutter/foundation.dart';

import '../data/models/app_user.dart';
import '../data/models/enums.dart';
import '../data/repositories/auth_repository.dart';

/// 로그인 상태 보관 + go_router redirect의 refreshListenable.
class AuthController extends ChangeNotifier {
  AuthController(this._repo);

  final AuthRepository _repo;

  AppUser? _user;
  bool _loading = false;

  AppUser? get user => _user;
  bool get isLoggedIn => _user != null;
  bool get loading => _loading;

  Future<void> login({required String username, required String password}) =>
      _guard(() async {
        final tokens = await _repo.login(username: username, password: password);
        _user = tokens.user;
      });

  Future<void> loginWithSocial(SocialProvider provider) => _guard(() async {
        // 실제 OAuth SDK 연동 전까지 id_token은 mock 값.
        final tokens = await _repo.loginWithSocial(provider, 'mock-id-token');
        _user = tokens.user;
      });

  Future<void> signup({
    required String name,
    required String username,
    required String password,
    required String email,
  }) =>
      _guard(() => _repo.signup(
          name: name, username: username, password: password, email: email));

  Future<void> logout() async {
    await _repo.logout();
    _user = null;
    notifyListeners();
  }

  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) =>
      _repo.changePassword(
          currentPassword: currentPassword, newPassword: newPassword);

  /// 회원 탈퇴(익명화, db-schema §7.1). 성공 시 로그아웃 상태로 전환.
  Future<void> deleteAccount() async {
    await _repo.deleteAccount();
    _user = null;
    notifyListeners();
  }

  /// 인터셉터가 세션 만료를 통지했을 때 (재로그인 유도).
  void handleAuthExpired() {
    if (_user == null) return;
    _user = null;
    notifyListeners();
  }

  Future<void> _guard(Future<void> Function() action) async {
    _loading = true;
    notifyListeners();
    try {
      await action();
    } finally {
      _loading = false;
      notifyListeners();
    }
  }
}
