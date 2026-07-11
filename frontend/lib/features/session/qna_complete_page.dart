import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/enums.dart';
import '../../data/models/report.dart';
import '../../data/repositories/session_repository.dart';
import '../common/app_back_button.dart';
import '../common/polling_builder.dart';
import '../common/responsive_page.dart';

/// 질의응답 종료 + 리포트 자동 생성 대기 (와이어프레임 f4).
/// spec A7: 세션 종료 시 리포트가 자동 생성됨 → 폴링으로 준비 확인.
class QnaCompletePage extends StatelessWidget {
  const QnaCompletePage({super.key, required this.sessionId});
  final String sessionId;

  @override
  Widget build(BuildContext context) {
    final repo = context.read<SessionRepository>();

    return Scaffold(
      appBar: AppBar(leading: const AppBackButton()),
      body: SafeArea(
        child: ResponsivePage(
          child: PollingBuilder<Report>(
            fetch: () => repo.getReport(sessionId),
            isDone: (r) => r.status.isDone,
            builder: (context, snap, retry) {
              final ready = snap.data?.status == AsyncStatus.ready;
              return Column(
                children: [
                  const Spacer(),
                  const Text('질의응답이 끝났어요 👏',
                      style:
                          TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 32),
                  if (!ready) ...[
                    const CircularProgressIndicator(color: AppColors.accent),
                    const SizedBox(height: 20),
                    const Text('리포트를 만들고 있어요…',
                        style: TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w700)),
                    const SizedBox(height: 8),
                    const Text('답변 품질과 발표 습관을 분석 중이에요.',
                        style: TextStyle(color: AppColors.textSecondary)),
                  ] else ...[
                    const Icon(Icons.check_circle,
                        size: 56, color: AppColors.accent),
                    const SizedBox(height: 16),
                    const Text('리포트가 준비됐어요!',
                        style: TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w700)),
                    if (snap.data?.insight != null) ...[
                      const SizedBox(height: 12),
                      Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: AppColors.accent.withValues(alpha: 0.1),
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: Text(snap.data!.insight!,
                            style: const TextStyle(fontSize: 13)),
                      ),
                    ],
                  ],
                  const Spacer(flex: 2),
                  if (ready)
                    SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: FilledButton(
                        style: FilledButton.styleFrom(
                          backgroundColor: AppColors.accent,
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(14)),
                        ),
                        onPressed: () =>
                            context.pushReplacement('/sessions/$sessionId'),
                        child: const Text('리포트 보기',
                            style: TextStyle(fontWeight: FontWeight.w800)),
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
                      onPressed: () => context.go('/'),
                      child: const Text('홈으로'),
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
