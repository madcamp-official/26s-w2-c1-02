import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/enums.dart';
import '../../data/models/transcript.dart';
import '../../data/repositories/session_repository.dart';
import '../common/app_back_button.dart';
import '../common/polling_builder.dart';
import '../common/responsive_page.dart';

/// STT 변환 로딩 (와이어프레임 e2) — transcript 폴링, ready 시 질의응답 확인으로.
class ProcessingPage extends StatelessWidget {
  const ProcessingPage({super.key, required this.sessionId});
  final String sessionId;

  @override
  Widget build(BuildContext context) {
    final repo = context.read<SessionRepository>();

    return Scaffold(
      appBar: AppBar(leading: const AppBackButton()),
      body: SafeArea(
        child: ResponsivePage(
          child: PollingBuilder<Transcript>(
            fetch: () => repo.getTranscript(sessionId),
            isDone: (t) => t.status.isDone,
            onDone: (t) {
              if (t.status == AsyncStatus.ready) {
                WidgetsBinding.instance.addPostFrameCallback((_) {
                  if (context.mounted) {
                    context.pushReplacement('/sessions/$sessionId/qna-confirm');
                  }
                });
              }
            },
            builder: (context, snap, retry) {
              final failed = snap.data?.status == AsyncStatus.failed;
              return Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  if (!failed) ...[
                    const CircularProgressIndicator(color: AppColors.accent),
                    const SizedBox(height: 32),
                    const Text('발표 내용을 텍스트로 정리하고 있어요',
                        style: TextStyle(
                            fontSize: 17, fontWeight: FontWeight.w700)),
                    const SizedBox(height: 12),
                    const Text('보통 1~2분 정도 걸려요.\n화면을 닫아도 진행 상황은 저장돼요.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: AppColors.textSecondary)),
                  ] else ...[
                    const Icon(Icons.error_outline,
                        size: 48, color: AppColors.danger),
                    const SizedBox(height: 16),
                    Text(snap.data?.error?.message ?? '변환에 실패했어요',
                        style: const TextStyle(
                            fontSize: 17, fontWeight: FontWeight.w700)),
                    const SizedBox(height: 16),
                    FilledButton(
                      onPressed: () {
                        repo.retryTranscript(sessionId);
                        retry();
                      },
                      child: const Text('다시 시도'),
                    ),
                  ],
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}
