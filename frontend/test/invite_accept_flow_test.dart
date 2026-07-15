import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rehearsal/core/network/api_client.dart';
import 'package:rehearsal/core/network/mock_backend.dart';
import 'package:rehearsal/core/router/app_router.dart';
import 'package:rehearsal/data/models/enums.dart';
import 'package:rehearsal/data/repositories/auth_repository.dart';
import 'package:rehearsal/data/repositories/team_repository.dart';
import 'package:rehearsal/state/auth_controller.dart';
import 'package:rehearsal/state/team_controller.dart';

void main() {
  testWidgets('초대 수락: 홈으로 돌아오면 재로그인 없이 합류한 팀이 바로 보인다', (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = ApiClient(
      backend: MockBackend(latency: Duration.zero),
      platform: ClientPlatform.web,
    );
    final teamRepo = TeamRepository(api);
    final auth = AuthController(AuthRepository(api));
    final teams = TeamController(teamRepo);
    final appRouter = AppRouter(auth);

    // fake-async 존 밖에서 실행 — mock의 Future.delayed 타이머는 pump 전에는
    // 발화하지 않으므로, 직접 await하면 테스트가 영원히 멈춘다.
    await tester.runAsync(() => auth.login(username: 'junseo', password: 'pw'));

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          Provider.value(value: api),
          Provider.value(value: teamRepo),
          ChangeNotifierProvider.value(value: auth),
          ChangeNotifierProvider.value(value: teams),
        ],
        child: MaterialApp.router(routerConfig: appRouter.router),
      ),
    );
    await tester.pumpAndSettle();

    // 홈: 기존 팀만 보인다.
    expect(find.text('teamname1'), findsOneWidget);
    expect(find.text('teamname3'), findsNothing);

    // 초대코드 화면으로 이동(홈에서 push — 홈 인스턴스가 스택에 남는 경로).
    appRouter.router.push('/invites/A2B3C4D5');
    await tester.pumpAndSettle();
    expect(find.text("'teamname3' 팀에 참여할까요?"), findsOneWidget);

    // 수락 → 홈 복귀 시 합류한 팀이 목록에 있어야 한다 (재로그인 불필요).
    await tester.tap(find.text('수락하기'));
    await tester.pumpAndSettle();

    expect(find.text('teamname1'), findsOneWidget);
    expect(find.text('teamname3'), findsOneWidget);
  });
}
