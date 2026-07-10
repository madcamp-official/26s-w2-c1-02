import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rehearsal/features/team/create_team_page.dart';

void main() {
  testWidgets(
    '단계가 순차적으로 나타나고, "프레젠테이션 팀 만들기" 버튼은 마지막 단계에서만 보인다',
    (tester) async {
      // 모든 단계가 한 화면에 보이도록 넉넉한 뷰포트로 설정.
      tester.view.physicalSize = const Size(1200, 2600);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(const MaterialApp(home: CreateTeamPage()));

      // 처음: 팀 이름 단계만. 유형/만들기 버튼은 아직 없음.
      expect(find.text('어떤 프레젠테이션인가요?'), findsNothing);
      expect(find.text('프레젠테이션을 함께할 팀원이 있나요?'), findsNothing);
      expect(find.text('프레젠테이션 팀 만들기'), findsNothing);

      // 팀 이름 입력 후 확인 → 2단계(유형 선택) 등장.
      await tester.enterText(find.byType(TextField).first, '우리팀');
      await tester.tap(find.text('확인'));
      await tester.pumpAndSettle();

      expect(find.text('어떤 프레젠테이션인가요?'), findsOneWidget);
      // 아직 마지막 단계가 아니므로 만들기 버튼은 없어야 함.
      expect(find.text('프레젠테이션 팀 만들기'), findsNothing);

      // 유형 선택 후 확인 → 3단계(팀원 초대 + 만들기 버튼) 등장.
      await tester.tap(find.text('기업 PT 면접'));
      await tester.pump();
      await tester.tap(find.text('확인').last);
      await tester.pumpAndSettle();

      expect(find.text('프레젠테이션을 함께할 팀원이 있나요?'), findsOneWidget);
      // 마지막 단계에서만 만들기 버튼 등장.
      expect(find.text('프레젠테이션 팀 만들기'), findsOneWidget);
    },
  );
}
