import 'package:flutter/foundation.dart';

import '../data/models/app_user.dart';
import '../data/repositories/auth_repository.dart';

/// 로그인 상태 보관 + go_router redirect의 refreshListenable로 사용.
class AuthController extends ChangeNotifier {
  AuthController(this._repo);

  final AuthRepository _repo;

  AppUser? _user;
  bool _loading = false;

  AppUser? get user => _user;
  bool get isLoggedIn => _user != null;
  bool get loading => _loading;

  Future<void> login({String? id, String? password}) async {
    _setLoading(true);
    try {
      _user = await _repo.login(id: id, password: password);
    } finally {
      _setLoading(false);
    }
  }

  Future<void> loginWithProvider(String provider) async {
    _setLoading(true);
    try {
      _user = await _repo.loginWithProvider(provider);
    } finally {
      _setLoading(false);
    }
  }

  Future<void> logout() async {
    await _repo.logout();
    _user = null;
    notifyListeners();
  }

  void _setLoading(bool value) {
    _loading = value;
    notifyListeners();
  }
}
