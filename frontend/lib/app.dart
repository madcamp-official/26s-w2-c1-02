import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/router/app_router.dart';
import 'core/theme/app_theme.dart';
import 'data/repositories/auth_repository.dart';
import 'data/repositories/speech_repository.dart';
import 'data/repositories/team_repository.dart';
import 'state/auth_controller.dart';
import 'state/speech_controller.dart';
import 'state/team_controller.dart';

/// 앱 루트: repository/controller 주입 + 라우터 구성.
///
/// 지금은 Mock repository를 주입한다. 백엔드 연동 시
/// 이 부분만 Api* repository로 교체하면 화면 코드는 그대로 동작한다.
class RehearsalApp extends StatefulWidget {
  const RehearsalApp({super.key});

  @override
  State<RehearsalApp> createState() => _RehearsalAppState();
}

class _RehearsalAppState extends State<RehearsalApp> {
  late final AuthController _auth;
  late final TeamController _teams;
  late final SpeechController _speeches;
  late final AppRouter _router;

  @override
  void initState() {
    super.initState();
    _auth = AuthController(MockAuthRepository());
    _teams = TeamController(MockTeamRepository());
    _speeches = SpeechController(MockSpeechRepository());
    _router = AppRouter(_auth);
  }

  @override
  void dispose() {
    _auth.dispose();
    _teams.dispose();
    _speeches.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: _auth),
        ChangeNotifierProvider.value(value: _teams),
        ChangeNotifierProvider.value(value: _speeches),
      ],
      child: MaterialApp.router(
        title: 'Rehearsal.io',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        routerConfig: _router.router,
      ),
    );
  }
}
