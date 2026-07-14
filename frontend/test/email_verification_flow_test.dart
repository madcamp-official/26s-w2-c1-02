import 'package:flutter_test/flutter_test.dart';
import 'package:rehearsal/core/network/api_client.dart';
import 'package:rehearsal/core/network/mock_backend.dart';
import 'package:rehearsal/data/models/enums.dart';
import 'package:rehearsal/data/repositories/auth_repository.dart';

/// 이메일 인증 플로우의 데이터 계약 (email-verification-plan §8·§9).
/// 가입 → 미인증 로그인 403 → verify(000000) → 로그인 성공.
/// verify_email_page·login_page(403 분기)가 의존하는 경로.
void main() {
  late AuthRepository repo;

  setUp(() {
    final mock = MockBackend(latency: Duration.zero);
    repo = AuthRepository(ApiClient(backend: mock, platform: ClientPlatform.web));
  });

  Future<void> signup(String email) => repo.signup(
      name: '테스터', username: 'verify_t', password: 'pw-12345678', email: email);

  test('가입 직후 로그인은 403 EMAIL_NOT_VERIFIED', () async {
    await signup('t@rehearsal.io');
    await expectLater(
      repo.login(username: 'verify_t', password: 'pw-12345678'),
      throwsA(isA<ApiException>()
          .having((e) => e.statusCode, 'statusCode', 403)
          .having((e) => e.code, 'code', 'EMAIL_NOT_VERIFIED')),
    );
  });

  test('잘못된 코드 → INVALID_CODE, 매직 코드 111111 → CODE_EXPIRED', () async {
    await signup('t@rehearsal.io');
    await expectLater(
      repo.verifyEmail('t@rehearsal.io', '999999'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'INVALID_CODE')),
    );
    await expectLater(
      repo.verifyEmail('t@rehearsal.io', '111111'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'CODE_EXPIRED')),
    );
  });

  test('verify(000000) 후 로그인 성공 — verify는 멱등', () async {
    await signup('t@rehearsal.io');
    await repo.requestEmailVerification('t@rehearsal.io'); // 204 — 예외 없으면 성공
    await repo.verifyEmail('t@rehearsal.io', MockBackend.verifyCode);
    await repo.verifyEmail('t@rehearsal.io', MockBackend.verifyCode); // 멱등(§9)
    final tokens = await repo.login(username: 'verify_t', password: 'pw-12345678');
    expect(tokens.accessToken, isNotEmpty);
  });

  test('5회 오입력 → 소진(CODE_EXPIRED), 재발송으로 복구 (§4-2)', () async {
    await signup('t@rehearsal.io');
    for (var i = 0; i < 5; i++) {
      await expectLater(
        repo.verifyEmail('t@rehearsal.io', '999999'),
        throwsA(isA<ApiException>()
            .having((e) => e.code, 'code', 'INVALID_CODE')),
      );
    }
    // 소진 후엔 정답이어도 CODE_EXPIRED (attempt 검사가 대조보다 먼저)
    await expectLater(
      repo.verifyEmail('t@rehearsal.io', MockBackend.verifyCode),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', 'CODE_EXPIRED')),
    );
    // 재발송 = 새 코드 → 카운터 리셋 → 정답 통과
    await repo.requestEmailVerification('t@rehearsal.io');
    await repo.verifyEmail('t@rehearsal.io', MockBackend.verifyCode);
    final tokens = await repo.login(username: 'verify_t', password: 'pw-12345678');
    expect(tokens.accessToken, isNotEmpty);
  });

  test('고정 시드 unverified 유저는 가입 없이 403 경로 재현', () async {
    await expectLater(
      repo.login(username: 'unverified', password: 'x'),
      throwsA(isA<ApiException>()
          .having((e) => e.code, 'code', 'EMAIL_NOT_VERIFIED')),
    );
  });
}
