import 'package:http/browser_client.dart';
import 'package:http/http.dart' as http;

/// 웹 전용 HTTP 클라이언트.
///
/// httpOnly refresh 쿠키(SameSite=Strict, Path=/api/v1/auth)가 `/auth/refresh`
/// 요청에 반드시 실려가도록 credentials를 포함시킨다(withCredentials=true →
/// fetch credentials: 'include'). 이 설정이 없으면 브라우저 기본값('same-origin')에
/// 의존하게 되는데, 오리진이 조금이라도 어긋나면 쿠키가 빠져 새로고침 후 세션 복원이
/// 실패하고 로그인 화면으로 튕긴다. 백엔드 CORS도 allow_credentials=True로 맞춰져 있다.
http.Client createHttpClient() => BrowserClient()..withCredentials = true;
