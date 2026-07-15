import 'package:flutter_test/flutter_test.dart';
import 'package:rehearsal/core/network/api_client.dart';
import 'package:rehearsal/core/network/http_backend.dart';
import 'package:rehearsal/core/network/mock_backend.dart';
import 'package:rehearsal/data/models/enums.dart';
import 'package:rehearsal/data/repositories/auth_repository.dart';
import 'package:rehearsal/state/auth_controller.dart';

/// 새로고침 후 세션 복원 (Step 2): AuthController.restoreSession().
/// 앱 시작 시 저장된 세션(Web=httpOnly 쿠키)으로 로그인 상태를 되살린다.
void main() {
  AuthController controllerWith(HttpBackend backend) => AuthController(
      AuthRepository(ApiClient(backend: backend, platform: ClientPlatform.web)));

  test('시작 직후엔 booting=true, 아직 로그인 아님', () {
    final auth = controllerWith(MockBackend(latency: Duration.zero));
    expect(auth.booting, isTrue);
    expect(auth.isLoggedIn, isFalse);
  });

  test('쿠키가 살아있으면 restoreSession()으로 로그인 복원 + booting 내려감', () async {
    final auth = controllerWith(MockBackend(latency: Duration.zero));

    var notified = 0;
    auth.addListener(() => notified++);

    await auth.restoreSession();

    expect(auth.booting, isFalse); // 복원 절차 종료
    expect(auth.isLoggedIn, isTrue); // 쿠키로 세션 되살아남
    expect(auth.user, isNotNull);
    expect(notified, greaterThan(0)); // 라우터가 다시 계산하도록 통지됨
  });

  test('세션이 없으면(refresh 401) 로그아웃 상태 유지 + booting 내려감', () async {
    final auth = controllerWith(_NoSessionBackend());

    await auth.restoreSession();

    expect(auth.booting, isFalse);
    expect(auth.isLoggedIn, isFalse); // 복원 실패 → 재로그인 필요
    expect(auth.user, isNull);
  });
}

/// refresh가 항상 401을 내는 백엔드 — 쿠키/세션이 없는 상태를 흉내낸다.
class _NoSessionBackend implements HttpBackend {
  @override
  Future<BackendResponse> send(BackendRequest request) async {
    return const BackendResponse(
      statusCode: 401,
      json: {
        'error': {'code': 'UNAUTHORIZED', 'message': '세션이 없어요.'}
      },
    );
  }
}
