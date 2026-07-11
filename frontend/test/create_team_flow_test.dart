import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rehearsal/core/network/api_client.dart';
import 'package:rehearsal/core/network/mock_backend.dart';
import 'package:rehearsal/data/models/enums.dart';
import 'package:rehearsal/data/repositories/team_repository.dart';
import 'package:rehearsal/features/team/create_team_page.dart';
import 'package:rehearsal/state/team_controller.dart';

void main() {
  testWidgets('팀 만들기: 이름 확정 후에만 초대 섹션과 팀 만들기 버튼이 나타난다 (spec §3: 유형 선택 없음)',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = ApiClient(
      backend: MockBackend(latency: Duration.zero),
      platform: ClientPlatform.web,
    );
    final repo = TeamRepository(api);

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          Provider.value(value: repo),
          ChangeNotifierProvider(create: (_) => TeamController(repo)),
        ],
        child: const MaterialApp(home: CreateTeamPage()),
      ),
    );

    // 처음: 초대 섹션·만들기 버튼 없음. (v0.3: 유형 선택 단계는 제거됨)
    expect(find.text('팀원 초대'), findsNothing);
    expect(find.text('팀 만들기'), findsNothing);
    expect(find.text('어떤 프레젠테이션인가요?'), findsNothing);

    // 이름 입력 + 확인 → 초대 섹션 + 만들기 버튼 등장.
    await tester.enterText(find.byType(TextField).first, '우리팀');
    await tester.tap(find.text('확인'));
    await tester.pumpAndSettle();

    expect(find.text('팀원 초대'), findsOneWidget);
    expect(find.text('팀 만들기'), findsOneWidget);
  });
}
