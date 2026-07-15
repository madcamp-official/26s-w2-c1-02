import 'package:flutter/foundation.dart';

import '../data/models/app_user.dart';
import '../data/repositories/auth_repository.dart';

/// 로그인 상태 보관 + go_router redirect의 refreshListenable.
class AuthController extends ChangeNotifier {
  AuthController(this._repo);

  final AuthRepository _repo;

  AppUser? _user;
  bool _loading = false;
  bool _booting = true;

  AppUser? get user => _user;
  bool get isLoggedIn => _user != null;
  bool get loading => _loading;

  /// 앱 시작 직후 세션 복원이 아직 진행 중인지. true인 동안 라우터는
  /// 로그인 판단을 미루고 스플래시를 보여줘야 한다 ([restoreSession] 참고).
  bool get booting => _booting;

  /// 앱 시작 시 1회 호출 — 저장된 세션(Web=httpOnly 쿠키)으로 로그인 상태를
  /// 되살린다. 새로고침으로 메모리의 access 토큰이 사라져도 여기서 복구한다.
  ///
  /// 성공하면 사용자 정보를 채워 로그인 상태를 유지하고, 실패(쿠키 없음·만료)하면
  /// 로그아웃 상태로 둔다. 어느 쪽이든 끝나면 [booting]을 false로 내린다.
  Future<void> restoreSession() async {
    try {
      final restored = await _repo.restoreSession();
      if (restored) _user = await _repo.me();
    } catch (_) {
      _user = null;
    } finally {
      _booting = false;
      notifyListeners();
    }
  }

  Future<void> login({required String username, required String password}) =>
      _guard(() async {
        final tokens = await _repo.login(username: username, password: password);
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

  /// 이메일 인증코드 확인 (email-verification-plan §8-2).
  Future<void> verifyEmail(String email, String code) =>
      _repo.verifyEmail(email, code);

  /// 인증코드 재발송 (§8-2 — 60초 쿨다운은 화면 몫).
  Future<void> requestEmailVerification(String email) =>
      _repo.requestEmailVerification(email);

  /// 아이디 찾기 — 이메일로 아이디 안내 (§2). 결과는 항상 성공 취급(열거 방지).
  Future<void> findUsername(String email) => _repo.findUsername(email);

  /// 비밀번호 재설정 코드 발송 (§2 — 60초 쿨다운은 화면 몫).
  Future<void> requestPasswordReset(String email) =>
      _repo.requestPasswordReset(email);

  /// 비밀번호 재설정 — 코드 + 새 비밀번호 (§2).
  Future<void> resetPassword({
    required String email,
    required String code,
    required String newPassword,
  }) =>
      _repo.resetPassword(email: email, code: code, newPassword: newPassword);

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
