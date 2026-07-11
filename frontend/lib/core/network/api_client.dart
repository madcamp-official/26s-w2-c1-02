import 'package:flutter/foundation.dart';

import '../../data/models/auth.dart';
import '../../data/models/enums.dart';
import 'http_backend.dart';
import 'token_store.dart';

/// FastAPI 백엔드와 통신하는 클라이언트.
///
/// 인터셉터(spec §2, workflow Step 1):
/// - 모든 요청에 `Authorization: Bearer <access>` + `X-Client-Platform` 부착
/// - `401 TOKEN_EXPIRED` 수신 시 `/auth/refresh` 호출 후 **1회 재시도**
/// - refresh 동시 호출 방지(진행 중이면 같은 Future 공유)
///
/// backend를 [MockBackend]로 주입하면 이 코드 경로 전체가 Mock에서도 동작한다.
class ApiClient {
  ApiClient({
    required HttpBackend backend,
    TokenStore? tokenStore,
    ClientPlatform? platform,
  })  : _backend = backend,
        tokenStore = tokenStore ?? InMemoryTokenStore(),
        platform = platform ?? _detectPlatform();

  final HttpBackend _backend;
  final TokenStore tokenStore;
  final ClientPlatform platform;

  Future<AuthTokens>? _refreshing;

  /// 로그아웃/세션 만료로 재로그인이 필요할 때 호출됨 (라우터가 구독).
  VoidCallback? onAuthExpired;

  static ClientPlatform _detectPlatform() {
    if (kIsWeb) return ClientPlatform.web;
    switch (defaultTargetPlatform) {
      case TargetPlatform.iOS:
        return ClientPlatform.ios;
      case TargetPlatform.android:
        return ClientPlatform.android;
      default:
        return ClientPlatform.web; // 데스크톱 등은 web 취급
    }
  }

  Map<String, String> _headers({bool withAuth = true}) => {
        'X-Client-Platform': platform.wire,
        if (withAuth && tokenStore.accessToken != null)
          'Authorization': 'Bearer ${tokenStore.accessToken}',
      };

  // -------------------------------------------------------------------
  // 공개 API
  // -------------------------------------------------------------------

  Future<dynamic> get(String path) => _sendWithRetry('GET', path);

  Future<dynamic> post(String path, {Map<String, dynamic>? body}) =>
      _sendWithRetry('POST', path, jsonBody: body);

  Future<dynamic> patch(String path, {Map<String, dynamic>? body}) =>
      _sendWithRetry('PATCH', path, jsonBody: body);

  Future<dynamic> delete(String path) => _sendWithRetry('DELETE', path);

  Future<dynamic> upload(
    String path, {
    required String fileName,
    required List<int> bytes,
    Map<String, String> fields = const {},
  }) =>
      _sendWithRetry('POST', path,
          multipart:
              MultipartPayload(fileName: fileName, bytes: bytes, fields: fields));

  /// 로그인 계열 — 성공 시 토큰 저장까지 처리.
  Future<AuthTokens> login(String path, Map<String, dynamic> body) async {
    final res = await _backend.send(BackendRequest(
      method: 'POST',
      path: path,
      headers: _headers(withAuth: false),
      jsonBody: body,
    ));
    if (!res.isSuccess) throw ApiException.fromResponse(res);
    final tokens = AuthTokens.fromJson(res.json as Map<String, dynamic>);
    await _storeTokens(tokens);
    return tokens;
  }

  Future<void> logout() async {
    try {
      await post('/auth/logout');
    } finally {
      await tokenStore.clear();
    }
  }

  // -------------------------------------------------------------------
  // 인터셉터 코어
  // -------------------------------------------------------------------

  Future<dynamic> _sendWithRetry(
    String method,
    String path, {
    Map<String, dynamic>? jsonBody,
    MultipartPayload? multipart,
  }) async {
    BackendRequest build() => BackendRequest(
          method: method,
          path: path,
          headers: _headers(),
          jsonBody: jsonBody,
          multipart: multipart,
        );

    var res = await _backend.send(build());

    // 401 TOKEN_EXPIRED → refresh → 1회 재시도 (spec §2 /auth/me 주석)
    if (res.statusCode == 401 && res.errorCode == 'TOKEN_EXPIRED') {
      final refreshed = await _tryRefresh();
      if (refreshed) {
        res = await _backend.send(build()); // 새 토큰으로 재시도
      }
    }

    if (res.statusCode == 401) {
      await tokenStore.clear();
      onAuthExpired?.call();
      throw ApiException.fromResponse(res);
    }
    if (!res.isSuccess) throw ApiException.fromResponse(res);
    return res.json;
  }

  /// refresh 성공 여부. 동시 요청은 하나의 refresh Future를 공유한다.
  Future<bool> _tryRefresh() async {
    try {
      _refreshing ??= _doRefresh();
      await _refreshing;
      return true;
    } catch (_) {
      return false;
    } finally {
      _refreshing = null;
    }
  }

  Future<AuthTokens> _doRefresh() async {
    // Web: 쿠키가 자동 전송되므로 본문 없음 / Native: 저장한 refresh 토큰 전송.
    final body = <String, dynamic>{
      if (platform != ClientPlatform.web &&
          tokenStore.refreshToken != null)
        'refresh_token': tokenStore.refreshToken,
    };
    final res = await _backend.send(BackendRequest(
      method: 'POST',
      path: '/auth/refresh',
      headers: _headers(withAuth: false),
      jsonBody: body,
    ));
    if (!res.isSuccess) throw ApiException.fromResponse(res);
    final tokens = AuthTokens.fromJson(res.json as Map<String, dynamic>);
    await _storeTokens(tokens);
    return tokens;
  }

  Future<void> _storeTokens(AuthTokens tokens) async {
    await tokenStore.saveAccessToken(tokens.accessToken);
    // Web은 refresh를 앱이 저장하지 않음 (httpOnly 쿠키 — 브라우저 관리).
    if (platform != ClientPlatform.web && tokens.refreshToken != null) {
      await tokenStore.saveRefreshToken(tokens.refreshToken!);
    }
  }
}

class ApiException implements Exception {
  ApiException(this.statusCode, this.code, this.message);

  final int statusCode;
  final String? code;
  final String? message;

  factory ApiException.fromResponse(BackendResponse res) => ApiException(
        res.statusCode,
        res.errorCode,
        res.errorMessage ?? '요청에 실패했어요.',
      );

  @override
  String toString() => 'ApiException($statusCode, $code): $message';
}
