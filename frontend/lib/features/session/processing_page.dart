import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_colors.dart';
import '../../data/models/enums.dart';
import '../../data/models/material_info.dart';
import '../../data/models/transcript.dart';
import '../../data/repositories/session_repository.dart';
import '../common/app_back_button.dart';
import '../common/polling_builder.dart';
import '../common/responsive_page.dart';

/// 발표 준비 상태 (STT + 자료 파싱) 스냅샷.
///
/// 질의응답 생성(POST /qna/generate)은 전사가 ready이고, 자료가 **있으면** 그것도
/// ready여야 202를 준다(아니면 409 MATERIAL_NOT_READY). 자료 파싱은 STT와 독립 잡이라
/// STT가 먼저 끝나는 경우가 흔하므로, 확인 화면으로 넘어가기 전에 두 리소스를 함께
/// 기다린다. [material] == null은 자료가 없음(비차단)을 뜻한다.
class _PrepStatus {
  const _PrepStatus({required this.transcript, this.material});
  final Transcript transcript;
  final MaterialInfo? material; // null = 자료 없음(비차단)

  bool get transcriptReady => transcript.status == AsyncStatus.ready;
  bool get transcriptFailed => transcript.status == AsyncStatus.failed;
  bool get materialFailed => material?.status == AsyncStatus.failed;

  /// 확인 화면으로 넘어갈 수 있는가 (전사 ready + 자료 없음|ready).
  bool get canProceed =>
      transcriptReady &&
      (material == null || material!.status == AsyncStatus.ready);

  /// 폴링을 멈출 상태 — 전사 실패, 또는 전사 ready이고 자료가 종료(ready|failed).
  bool get isDone =>
      transcriptFailed ||
      (transcriptReady && (material == null || material!.status.isDone));
}

/// STT·자료 준비 로딩 (와이어프레임 e2) — 전사와 자료 파싱을 함께 폴링,
/// 둘 다 준비되면(자료는 없어도 됨) 질의응답 확인으로 넘어간다.
class ProcessingPage extends StatelessWidget {
  const ProcessingPage({super.key, required this.sessionId});
  final String sessionId;

  /// 전사가 ready면 자료 상태도 확인한다. 자료가 없으면 404(MATERIAL_NOT_FOUND)라
  /// 비차단(material=null)으로 처리한다. 전사가 아직이면 자료는 굳이 조회하지 않는다.
  Future<_PrepStatus> _fetch(SessionRepository repo) async {
    final transcript = await repo.getTranscript(sessionId);
    if (transcript.status != AsyncStatus.ready) {
      return _PrepStatus(transcript: transcript);
    }
    try {
      final material = await repo.getMaterial(sessionId);
      return _PrepStatus(transcript: transcript, material: material);
    } on ApiException catch (e) {
      if (e.code == 'MATERIAL_NOT_FOUND') {
        return _PrepStatus(transcript: transcript); // 자료 없음 → 비차단
      }
      rethrow;
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = context.read<SessionRepository>();

    return Scaffold(
      appBar: AppBar(leading: const AppBackButton()),
      body: SafeArea(
        child: ResponsivePage(
          child: PollingBuilder<_PrepStatus>(
            fetch: () => _fetch(repo),
            isDone: (s) => s.isDone,
            onDone: (s) {
              if (s.canProceed) {
                WidgetsBinding.instance.addPostFrameCallback((_) {
                  if (context.mounted) {
                    context.pushReplacement('/sessions/$sessionId/qna-confirm');
                  }
                });
              }
            },
            builder: (context, snap, retry) {
              final s = snap.data;

              // 전사 실패 → 재전사
              if (s != null && s.transcriptFailed) {
                return _ProcessingError(
                  message: s.transcript.error?.message ?? '변환에 실패했어요',
                  primaryLabel: '다시 시도',
                  onPrimary: () {
                    repo.retryTranscript(sessionId);
                    retry();
                  },
                );
              }

              // 전사는 끝났는데 자료 파싱 실패 → 재파싱 또는 자료 없이 진행.
              // '자료 없이 계속'은 자료를 지운다 — 백엔드는 자료가 없으면 그냥 진행한다.
              if (s != null && s.transcriptReady && s.materialFailed) {
                return _ProcessingError(
                  message: s.material?.error?.message ?? '자료 분석에 실패했어요',
                  primaryLabel: '다시 시도',
                  onPrimary: () {
                    repo.retryMaterial(sessionId);
                    retry();
                  },
                  secondaryLabel: '자료 없이 계속',
                  onSecondary: () async {
                    await repo.deleteMaterial(sessionId);
                    if (context.mounted) {
                      context.pushReplacement(
                          '/sessions/$sessionId/qna-confirm');
                    }
                  },
                );
              }

              // 네트워크/서버 오류로 폴링이 멈춘 경우 (아직 데이터 없음) → 재시도.
              if (s == null && snap.error != null) {
                return _ProcessingError(
                  message: '준비 상태를 불러오지 못했어요',
                  primaryLabel: '다시 시도',
                  onPrimary: retry,
                );
              }

              // 진행 중 — 전사 정리 중 또는(전사 후) 자료 분석 중.
              final analyzingMaterial =
                  s != null && s.transcriptReady && !s.canProceed;
              return Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const CircularProgressIndicator(color: AppColors.accent),
                  const SizedBox(height: 32),
                  Text(
                      analyzingMaterial
                          ? '발표 자료를 분석하고 있어요'
                          : '발표 내용을 텍스트로 정리하고 있어요',
                      style: const TextStyle(
                          fontSize: 17, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 12),
                  const Text('보통 1~2분 정도 걸려요.\n화면을 닫아도 진행 상황은 저장돼요.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: AppColors.textSecondary)),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

/// 처리 실패 안내 + 재시도(필수)/보조 액션(선택).
class _ProcessingError extends StatelessWidget {
  const _ProcessingError({
    required this.message,
    required this.primaryLabel,
    required this.onPrimary,
    this.secondaryLabel,
    this.onSecondary,
  });

  final String message;
  final String primaryLabel;
  final VoidCallback onPrimary;
  final String? secondaryLabel;
  final VoidCallback? onSecondary;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const Icon(Icons.error_outline, size: 48, color: AppColors.danger),
        const SizedBox(height: 16),
        Text(message,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
        const SizedBox(height: 16),
        FilledButton(onPressed: onPrimary, child: Text(primaryLabel)),
        if (secondaryLabel != null && onSecondary != null) ...[
          const SizedBox(height: 8),
          TextButton(onPressed: onSecondary, child: Text(secondaryLabel!)),
        ],
      ],
    );
  }
}
