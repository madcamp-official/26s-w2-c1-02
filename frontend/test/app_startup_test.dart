import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehearsal/app.dart';

/// 앱 시작 배선 (Step 3·4): startup에서 restoreSession()을 호출해 저장된 세션
/// (Web=httpOnly 쿠키)으로 로그인 상태를 되살리고, 복원 중에는 스플래시를 띄워
/// 로그인 화면 깜빡임을 막는지 end-to-end 검증.
///
/// USE_MOCK 기본값(true) → MockBackend. Mock은 쿠키를 흉내내 refresh를 항상
/// 성공시키므로, 시작 직후 자동 로그인되어 홈 화면으로 진입해야 한다.
///
/// Mock latency는 FakeAsync 가짜 타이머라 pump(Duration)으로 시계를 전진시켜야
/// fire된다 (pumpAndSettle은 애니메이션만, runAsync는 실시간이라 안 맞음).
void main() {
  testWidgets('복원 중엔 스플래시(로그인 깜빡임 없음), 복원 완료 후 홈으로 진입',
      (tester) async {
    await tester.pumpWidget(const RehearsalApp());
    await tester.pump(); // 초기 redirect 처리 → /splash

    // Phase 1: 세션 복원 중 → 스플래시(로딩). 로그인 화면은 절대 보이면 안 된다.
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('당신의 발표를 더 완벽하게'), findsNothing);
    expect(find.textContaining('반가워요'), findsNothing);

    // 가짜 시계를 전진시켜 restore(refresh→me) + 홈 로딩 타이머를 fire.
    for (var i = 0; i < 8; i++) {
      await tester.pump(const Duration(milliseconds: 300));
    }

    // Phase 2: 복원 완료 → 홈 화면(인사말). 여전히 로그인 화면 아님.
    expect(find.textContaining('반가워요'), findsOneWidget);
    expect(find.text('당신의 발표를 더 완벽하게'), findsNothing);
  });
}
