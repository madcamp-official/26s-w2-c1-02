import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_colors.dart';
import '../../data/models/team.dart';
import '../../data/repositories/team_repository.dart';
import '../../state/auth_controller.dart';
import '../../state/team_controller.dart';
import '../common/responsive_page.dart';

/// 초대 수락 (와이어프레임 c2).
/// 미리보기는 인증 불필요, 수락/거절은 로그인 필요 (spec §3.1 H).
class InviteAcceptPage extends StatelessWidget {
  const InviteAcceptPage({super.key, required this.token});
  final String token;

  @override
  Widget build(BuildContext context) {
    final repo = context.read<TeamRepository>();
    final loggedIn = context.watch<AuthController>().isLoggedIn;

    return Scaffold(
      body: SafeArea(
        child: ResponsivePage(
          child: FutureBuilder<InvitePreview>(
            future: repo.previewInvite(token),
            builder: (context, snap) {
              if (!snap.hasData) {
                if (!snap.hasError) {
                  return const Center(child: CircularProgressIndicator());
                }
                // §11-2 에러 문구: 404=존재하지 않는 코드, 410=만료된 코드.
                final e = snap.error;
                final message = switch (e) {
                  ApiException(statusCode: 404) => '존재하지 않는 코드예요',
                  ApiException(statusCode: 410) =>
                    '만료된 코드예요.\n팀장에게 새 코드를 요청하세요',
                  _ => '유효하지 않거나 만료된 초대예요',
                };
                return Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(message,
                          textAlign: TextAlign.center,
                          style: const TextStyle(fontSize: 16, height: 1.5)),
                      const SizedBox(height: 16),
                      TextButton(
                        onPressed: () => context.go('/'),
                        child: const Text('홈으로 돌아가기'),
                      ),
                    ],
                  ),
                );
              }
              final p = snap.data!;
              return Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  CircleAvatar(
                    radius: 40,
                    backgroundColor: AppColors.accent.withValues(alpha: 0.15),
                    child: Text(p.teamName.characters.first,
                        style: const TextStyle(
                            fontSize: 28,
                            fontWeight: FontWeight.w800,
                            color: AppColors.accent)),
                  ),
                  const SizedBox(height: 24),
                  if (p.inviterName != null)
                    Text('${p.inviterName}님이 초대했어요',
                        style:
                            const TextStyle(color: AppColors.textSecondary)),
                  const SizedBox(height: 8),
                  Text("'${p.teamName}' 팀에 참여할까요?",
                      style: const TextStyle(
                          fontSize: 20, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 20),
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: AppColors.surface,
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Text(
                        '팀원 ${p.memberCount}명 · 발표 ${p.sessionCount}회',
                        style:
                            const TextStyle(color: AppColors.textSecondary)),
                  ),
                  const Spacer(),
                  if (!loggedIn)
                    const Padding(
                      padding: EdgeInsets.only(bottom: 12),
                      child: Text('수락하려면 먼저 로그인해주세요',
                          style: TextStyle(
                              fontSize: 13, color: AppColors.textSecondary)),
                    ),
                  SizedBox(
                    width: double.infinity,
                    height: 56,
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: AppColors.accent,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14)),
                      ),
                      onPressed: () async {
                        if (!loggedIn) {
                          context.go('/login');
                          return;
                        }
                        final teams = context.read<TeamController>();
                        await repo.acceptInvite(token);
                        // go('/')는 스택에 이미 있는 홈 인스턴스로 돌아가므로
                        // initState의 load()가 다시 돌지 않는다 — 여기서 갱신.
                        await teams.load();
                        if (context.mounted) context.go('/');
                      },
                      child: Text(loggedIn ? '수락하기' : '로그인하고 수락하기',
                          style:
                              const TextStyle(fontWeight: FontWeight.w700)),
                    ),
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    height: 56,
                    child: TextButton(
                      style: TextButton.styleFrom(
                        backgroundColor: AppColors.surface,
                        foregroundColor: AppColors.textPrimary,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14)),
                      ),
                      onPressed: () async {
                        if (loggedIn) await repo.declineInvite(token);
                        if (context.mounted) context.go('/');
                      },
                      child: const Text('거절하기'),
                    ),
                  ),
                  const SizedBox(height: 24),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}
