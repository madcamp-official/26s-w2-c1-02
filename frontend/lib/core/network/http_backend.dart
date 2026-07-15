import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

// 웹에서는 refresh 쿠키를 실어보내는 BrowserClient(withCredentials=true)를,
// 그 외에는 기본 클라이언트를 쓴다 (http 패키지와 동일한 조건부 임포트 규칙).
import 'http_client_io.dart'
    if (dart.library.js_interop) 'http_client_web.dart';

/// ApiClient가 실제로 요청을 보내는 대상의 추상화.
///
/// - [RealHttpBackend]: 실서버 (package:http)
/// - MockBackend(mock_backend.dart): FE의 "가짜 서버" — spec 응답 JSON 반환
///
/// 인터셉터(401→refresh→재시도)는 ApiClient에 있으므로
/// Mock 모드에서도 동일한 코드 경로로 검증된다.
abstract class HttpBackend {
  Future<BackendResponse> send(BackendRequest request);
}

class BackendRequest {
  const BackendRequest({
    required this.method,
    required this.path,
    this.headers = const {},
    this.jsonBody,
    this.multipart,
  });

  final String method; // GET | POST | PATCH | DELETE
  final String path; // '/auth/login' (base URL 제외)
  final Map<String, String> headers;
  final Map<String, dynamic>? jsonBody;

  /// 파일 업로드용. Mock에서는 파일명·크기만 의미 있음.
  final MultipartPayload? multipart;
}

class MultipartPayload {
  const MultipartPayload({
    required this.fileName,
    required this.bytes,
    this.fields = const {},
  });

  final String fileName;
  final List<int> bytes;
  final Map<String, String> fields;
}

class BackendResponse {
  const BackendResponse({required this.statusCode, this.json});

  final int statusCode;
  final dynamic json;

  bool get isSuccess => statusCode >= 200 && statusCode < 300;

  /// 에러 응답 `{error: {code, message}}`에서 code 추출.
  String? get errorCode {
    final j = json;
    if (j is Map<String, dynamic>) {
      final err = j['error'];
      if (err is Map<String, dynamic>) return err['code'] as String?;
    }
    return null;
  }

  String? get errorMessage {
    final j = json;
    if (j is Map<String, dynamic>) {
      final err = j['error'];
      if (err is Map<String, dynamic>) return err['message'] as String?;
    }
    return null;
  }

  /// 에러 응답 `{error: {details: {...}}}`에서 details 추출.
  /// 예: 429 RATE_LIMITED의 `retry_after_seconds` (재발송 쿨다운 안내).
  Map<String, dynamic>? get errorDetails {
    final j = json;
    if (j is Map<String, dynamic>) {
      final err = j['error'];
      if (err is Map<String, dynamic>) {
        final details = err['details'];
        if (details is Map<String, dynamic>) return details;
      }
    }
    return null;
  }
}

/// 요청이 [RealHttpBackend]의 타임아웃을 넘겨 중단됨.
/// 폴링·업로드가 응답 없는 연결에 영원히 매달리지 않게 한다.
class RequestTimeoutException implements Exception {
  RequestTimeoutException(this.message);
  final String message;

  @override
  String toString() => message;
}

/// 실서버 백엔드 (Mock-off 전환 시 사용).
class RealHttpBackend implements HttpBackend {
  RealHttpBackend({
    required this.baseUrl,
    http.Client? client,
    this.requestTimeout = const Duration(seconds: 30),
    this.uploadTimeout = const Duration(minutes: 10),
  }) : _client = client ?? createHttpClient();

  final String baseUrl;
  final http.Client _client;

  /// 일반(JSON) 요청 상한. 없으면 응답 없는 연결에 폴링이 조용히 영구 정지한다
  /// (PollingBuilder는 이전 요청이 안 끝나면 다음 틱을 건너뛰므로).
  final Duration requestTimeout;

  /// 업로드(multipart) 상한 — 녹음 파일은 수십 MB라 넉넉하게 잡는다.
  final Duration uploadTimeout;

  Never _onTimeout(Duration limit) =>
      throw RequestTimeoutException(
          '서버 응답이 ${limit.inSeconds}초 안에 오지 않았어요. 네트워크를 확인해주세요.');

  @override
  Future<BackendResponse> send(BackendRequest request) async {
    final uri = Uri.parse('$baseUrl${request.path}');

    http.Response res;
    if (request.multipart != null) {
      final m = request.multipart!;
      final multi = http.MultipartRequest(request.method, uri)
        ..headers.addAll(request.headers)
        ..fields.addAll(m.fields)
        ..files.add(
            http.MultipartFile.fromBytes('file', m.bytes, filename: m.fileName));
      res = await multi
          .send()
          .then(http.Response.fromStream)
          .timeout(uploadTimeout, onTimeout: () => _onTimeout(uploadTimeout));
    } else {
      final headers = {
        ...request.headers,
        if (request.jsonBody != null) 'Content-Type': 'application/json',
      };
      final body =
          request.jsonBody == null ? null : jsonEncode(request.jsonBody);
      final future = switch (request.method) {
        'GET' => _client.get(uri, headers: headers),
        'POST' => _client.post(uri, headers: headers, body: body),
        'PATCH' => _client.patch(uri, headers: headers, body: body),
        'DELETE' => _client.delete(uri, headers: headers),
        _ => throw ArgumentError('unsupported method ${request.method}'),
      };
      res = await future.timeout(requestTimeout,
          onTimeout: () => _onTimeout(requestTimeout));
    }

    dynamic decoded;
    if (res.body.isNotEmpty) {
      try {
        decoded = jsonDecode(utf8.decode(res.bodyBytes));
      } catch (_) {
        decoded = null;
      }
    }
    return BackendResponse(statusCode: res.statusCode, json: decoded);
  }
}
