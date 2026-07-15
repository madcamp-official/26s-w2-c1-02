import 'package:http/http.dart' as http;

/// 기본(네이티브·테스트) HTTP 클라이언트.
///
/// 네이티브는 refresh 토큰을 응답 본문으로 받아 저장하고 요청 본문으로 되보내므로
/// 쿠키 설정이 필요 없다. 웹에서는 [http_client_web.dart]가 대신 쓰인다.
http.Client createHttpClient() => http.Client();
