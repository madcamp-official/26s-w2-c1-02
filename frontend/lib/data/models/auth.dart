import 'app_user.dart';

/// 로그인/refresh 응답 (spec §2).
/// Web: refresh_token은 본문에 없음(httpOnly 쿠키).
/// Native: refresh_token 본문 포함 → TokenStore에 보관.
class AuthTokens {
  const AuthTokens({
    required this.accessToken,
    this.refreshToken,
    required this.expiresIn,
    required this.user,
  });

  final String accessToken;
  final String? refreshToken;

  /// access 토큰 수명 (초).
  final int expiresIn;
  final AppUser user;

  factory AuthTokens.fromJson(Map<String, dynamic> json) => AuthTokens(
        accessToken: json['access_token'] as String,
        refreshToken: json['refresh_token'] as String?,
        expiresIn: json['expires_in'] as int? ?? 900,
        user: AppUser.fromJson(json['user'] as Map<String, dynamic>),
      );
}
