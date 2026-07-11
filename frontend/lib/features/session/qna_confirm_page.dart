import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/repositories/session_repository.dart';
import '../../state/session_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 질의응답 전환 확인 (와이어프레임 e3).
class QnaConfirmPage extends StatelessWidget {
  const QnaConfirmPage({super.key, required this.sessionId});
  final String sessionId;

  @override
  Widget build(BuildContext context) {
    final session = context.watch<SessionController>().byId(sessionId);

    return Scaffold(
      appBar: AppBar(leading: const AppBackButton()),
      body: SafeArea(
        child: ResponsivePage(
          child: Column(
            children: [
              const Spacer(),
              Text(session?.name ?? '발표',
                  style: const TextStyle(
                      fontSize: 20, fontWeight: FontWeight.w800)),
              const SizedBox(height: 24),
              const Text('발표를 마쳤어요.',
                  style: TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.w800,
                      color: AppColors.accent)),
              const Text('질의응답으로 넘어갈까요?',
                  style: TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.w800,
                      color: AppColors.accent)),
              const SizedBox(height: 12),
              const Text('발표 기록은 자동으로 저장돼요.',
                  style: TextStyle(color: AppColors.textSecondary)),
              const Spacer(flex: 2),
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
                    // 질문 생성 시작(202) → Q&A 화면에서 생성 완료를 폴링.
                    await context
                        .read<SessionRepository>()
                        .generateQna(sessionId);
                    if (context.mounted) {
                      context.pushReplacement('/sessions/$sessionId/qna');
                    }
                  },
                  child: const Text('질의응답 시작하기',
                      style: TextStyle(
                          fontSize: 17, fontWeight: FontWeight.w800)),
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
                  onPressed: () => session != null
                      ? context.go('/teams/${session.teamId}')
                      : context.go('/'),
                  child: const Text('안 할게요',
                      style: TextStyle(fontWeight: FontWeight.w700)),
                ),
              ),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }
}
