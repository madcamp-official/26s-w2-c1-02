import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../features/auth/account_recovery_page.dart';
import '../../features/auth/login_page.dart';
import '../../features/auth/signup_page.dart';
import '../../features/home/home_page.dart';
import '../../features/profile/change_password_page.dart';
import '../../features/profile/my_page.dart';
import '../../features/report/growth_report_page.dart';
import '../../features/session/create_session_page.dart';
import '../../features/session/material_status_page.dart';
import '../../features/session/presenting_page.dart';
import '../../features/session/processing_page.dart';
import '../../features/session/qna_complete_page.dart';
import '../../features/session/qna_confirm_page.dart';
import '../../features/session/qna_page.dart';
import '../../features/session/session_detail_page.dart';
import '../../features/session/upload_recording_page.dart';
import '../../features/team/create_team_page.dart';
import '../../features/team/invite_accept_page.dart';
import '../../features/team/team_detail_page.dart';
import '../../state/auth_controller.dart';

/// 앱 라우팅 — 와이어프레임 28화면 ↔ 라우트 매핑 (workflow Step 1).
///
/// 다이얼로그/바텀시트류(c4 팀관리, g3 삭제확인, i3 탈퇴확인, j1 마이크권한,
/// j2 오류·이탈)는 라우트가 아니라 해당 화면에서 띄우는 오버레이로 구현한다.
/// variants(d2 상태 3종, e1 시간초과, f1~f3 질문 상태)는 한 라우트의 상태다.
class AppRouter {
  AppRouter(this.auth);

  final AuthController auth;

  late final GoRouter router = GoRouter(
    initialLocation: '/',
    refreshListenable: auth,
    redirect: (context, state) {
      final loc = state.matchedLocation;
      // 초대 미리보기는 인증 불필요 (spec §3.1 H)
      final isPublic = loc == '/login' ||
          loc == '/signup' ||
          loc == '/account-recovery' ||
          loc.startsWith('/invites/');
      if (!auth.isLoggedIn && !isPublic) return '/login';
      if (auth.isLoggedIn && (loc == '/login' || loc == '/signup')) return '/';
      return null;
    },
    routes: [
      // ---- 01 인증 ----
      GoRoute(path: '/login', builder: (_, _) => const LoginPage()),
      GoRoute(path: '/signup', builder: (_, _) => const SignupPage()),
      GoRoute(
          path: '/account-recovery',
          builder: (_, _) => const AccountRecoveryPage()),

      // ---- 02 메인 ----
      GoRoute(path: '/', builder: (_, _) => const HomePage()),

      // ---- 09 마이페이지 ----
      GoRoute(path: '/me', builder: (_, _) => const MyPage()),
      GoRoute(
        path: '/me/password',
        builder: (_, _) => const ChangePasswordPage(),
      ),
      // ---- 08 분석 (성장 리포트) ----
      GoRoute(
        path: '/me/growth',
        builder: (_, _) => const GrowthReportPage(),
      ),

      // ---- 03 팀 ----
      GoRoute(path: '/teams/new', builder: (_, _) => const CreateTeamPage()),
      GoRoute(
        path: '/teams/:teamId',
        builder: (_, s) => TeamDetailPage(teamId: s.pathParameters['teamId']!),
      ),
      GoRoute(
        path: '/invites/:token',
        builder: (_, s) => InviteAcceptPage(token: s.pathParameters['token']!),
      ),

      // ---- 04 발표 준비 ----
      GoRoute(
        path: '/teams/:teamId/sessions/new',
        builder: (_, s) =>
            CreateSessionPage(teamId: s.pathParameters['teamId']!),
      ),
      GoRoute(
        path: '/sessions/:sessionId/material',
        builder: (_, s) =>
            MaterialStatusPage(sessionId: s.pathParameters['sessionId']!),
      ),
      GoRoute(
        path: '/sessions/:sessionId/upload-recording',
        builder: (_, s) =>
            UploadRecordingPage(sessionId: s.pathParameters['sessionId']!),
      ),

      // ---- 05 발표 진행 ----
      GoRoute(
        path: '/sessions/:sessionId/present',
        builder: (_, s) =>
            PresentingPage(sessionId: s.pathParameters['sessionId']!),
      ),
      GoRoute(
        path: '/sessions/:sessionId/processing',
        builder: (_, s) =>
            ProcessingPage(sessionId: s.pathParameters['sessionId']!),
      ),
      GoRoute(
        path: '/sessions/:sessionId/qna-confirm',
        builder: (_, s) =>
            QnaConfirmPage(sessionId: s.pathParameters['sessionId']!),
      ),

      // ---- 06 질의응답 ----
      GoRoute(
        path: '/sessions/:sessionId/qna',
        builder: (_, s) => QnaPage(sessionId: s.pathParameters['sessionId']!),
      ),
      GoRoute(
        path: '/sessions/:sessionId/qna/complete',
        builder: (_, s) =>
            QnaCompletePage(sessionId: s.pathParameters['sessionId']!),
      ),

      // ---- 07 이전 발표 (상세: 스크립트/Q&A/리포트 탭) ----
      GoRoute(
        path: '/sessions/:sessionId',
        builder: (_, s) =>
            SessionDetailPage(sessionId: s.pathParameters['sessionId']!),
      ),
    ],
    errorBuilder: (context, state) => Scaffold(
      body: Center(child: Text('페이지를 찾을 수 없어요: ${state.uri}')),
    ),
  );
}
