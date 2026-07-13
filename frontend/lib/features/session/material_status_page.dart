import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/files/file_constraints.dart';
import '../../core/theme/app_colors.dart';
import '../../data/models/enums.dart';
import '../../data/models/material_info.dart';
import '../../data/repositories/session_repository.dart';
import '../../state/session_controller.dart';
import '../common/app_back_button.dart';
import '../common/polling_builder.dart';
import '../common/responsive_page.dart';

/// 자료 전처리 상태 (와이어프레임 d2) — **공통 폴링 위젯 실사용 예시**.
/// POST /material(202) 후 GET /material을 1.5초 폴링, ready|failed에서 멈춘다.
class MaterialStatusPage extends StatelessWidget {
  const MaterialStatusPage({super.key, required this.sessionId});
  final String sessionId;

  /// 진행 방식에 맞춘 CTA 문구. upload 모드는 다음 단계가 파일 업로드다.
  String _startLabel({required bool ready, required SessionMode? mode}) {
    if (mode == SessionMode.upload) {
      return ready ? '녹음 파일 올리기' : '파싱은 두고 녹음 파일 올리기';
    }
    return ready ? '발표 시작하기' : '파싱은 두고 발표 시작하기';
  }

  @override
  Widget build(BuildContext context) {
    final repo = context.read<SessionRepository>();
    // 자료 준비 후 이동할 화면은 세션 진행 방식에 따라 갈린다:
    // upload 모드는 파일 업로드(d3), 그 외(realtime)는 실시간 녹음(e1).
    // 세션은 생성 직후 SessionController에 캐시돼 있다(create → load).
    final mode = context.watch<SessionController>().byId(sessionId)?.mode;
    final nextRoute = mode == SessionMode.upload
        ? '/sessions/$sessionId/upload-recording'
        : '/sessions/$sessionId/present';

    return Scaffold(
      appBar: AppBar(leading: const AppBackButton()),
      body: SafeArea(
        child: ResponsivePage(
          child: PollingBuilder<MaterialInfo>(
            fetch: () => repo.getMaterial(sessionId),
            isDone: (m) => m.status.isDone,
            builder: (context, snap, retry) {
              final m = snap.data;
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SizedBox(height: 8),
                  const Text('발표 자료를 준비하고',
                      style:
                          TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
                  const Text('있어요',
                      style:
                          TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 32),
                  if (m == null)
                    const Center(child: CircularProgressIndicator())
                  else
                    _StatusCard(
                      info: m,
                      // 스캔본 등 실패 → 새 PDF 재선택 후 재업로드 (spec §4.2)
                      onRetry: () async {
                        final picked = await FilePicker.platform.pickFiles(
                          type: FileType.custom,
                          allowedExtensions: ['pdf'],
                          withData: true,
                        );
                        final file = picked?.files.single;
                        if (file == null || file.bytes == null) return;
                        final error = FileConstraints.validatePdf(
                          fileName: file.name,
                          sizeBytes: file.size,
                          bytes: file.bytes,
                        );
                        if (error != null) {
                          if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(content: Text(error)));
                          }
                          return;
                        }
                        await repo.uploadMaterial(sessionId,
                            fileName: file.name, bytes: file.bytes!);
                        retry();
                      },
                    ),
                  if (snap.error != null) ...[
                    Text('오류: ${snap.error}',
                        style: const TextStyle(color: AppColors.danger)),
                    TextButton(onPressed: retry, child: const Text('다시 시도')),
                  ],
                  const Spacer(),
                  SizedBox(
                    width: double.infinity,
                    height: 56,
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: AppColors.accent,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14)),
                      ),
                      // 자료는 세션과 독립 파싱 — 준비 전에도 발표는 시작 가능 (spec §4).
                      onPressed: () => context.pushReplacement(nextRoute),
                      child: Text(
                          _startLabel(
                              ready: m?.status == AsyncStatus.ready,
                              mode: mode),
                          style:
                              const TextStyle(fontWeight: FontWeight.w700)),
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

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.info, required this.onRetry});
  final MaterialInfo info;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    switch (info.status) {
      case AsyncStatus.queued:
      case AsyncStatus.processing:
        return _card(
          leading: const SizedBox(
              width: 28, height: 28,
              child: CircularProgressIndicator(
                  strokeWidth: 3, color: AppColors.accent)),
          title: '슬라이드 텍스트 추출 중…',
          subtitle: info.status == AsyncStatus.queued
              ? '대기열에 있어요'
              : '${(info.progress * 100).round()}% · ${info.fileName ?? ''}',
          extra: LinearProgressIndicator(
            value: info.status == AsyncStatus.queued ? null : info.progress,
            color: AppColors.accent,
            backgroundColor: AppColors.surface,
          ),
        );
      case AsyncStatus.ready:
        return _card(
          leading: const CircleAvatar(
              radius: 14,
              backgroundColor: Color(0xFFE6F9F1),
              child: Icon(Icons.check, size: 18, color: Color(0xFF00915A))),
          title: '추출 완료',
          subtitle: '${info.pageCount ?? info.slides.length}개 슬라이드 · slides.json 생성됨',
        );
      case AsyncStatus.failed:
        return _card(
          color: const Color(0xFFFFECEE),
          leading: const CircleAvatar(
              radius: 14,
              backgroundColor: Colors.white,
              child: Text('!',
                  style: TextStyle(
                      color: AppColors.danger, fontWeight: FontWeight.w800))),
          title: info.error?.message ?? '텍스트를 읽을 수 없어요',
          subtitle: '스캔본·이미지 PDF는 지원하지 않아요.',
          extra: Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton(
                onPressed: onRetry, child: const Text('다시 업로드')),
          ),
        );
    }
  }

  Widget _card({
    required Widget leading,
    required String title,
    required String subtitle,
    Widget? extra,
    Color color = const Color(0xFFF7F8FA),
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
          color: color, borderRadius: BorderRadius.circular(16)),
      child: Row(
        children: [
          leading,
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: const TextStyle(
                        fontSize: 15, fontWeight: FontWeight.w700)),
                const SizedBox(height: 4),
                Text(subtitle,
                    style: const TextStyle(
                        fontSize: 12.5, color: AppColors.textSecondary)),
                if (extra != null) ...[const SizedBox(height: 10), extra],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
