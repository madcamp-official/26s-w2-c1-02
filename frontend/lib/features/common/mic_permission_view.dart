import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';

/// 마이크 권한 요청/거부 안내 (와이어프레임 10-common j1).
///
/// 발표 녹음(05)·답변 녹음(06)에서 공통으로 쓰는 인라인 뷰.
/// [onRetry]는 권한 재요청, [onFake]는 (개발용) 가짜 녹음 진행.
class MicPermissionView extends StatelessWidget {
  const MicPermissionView({
    super.key,
    this.title = '마이크 권한이 필요해요',
    this.message =
        '음성 녹음을 위해 마이크 접근을 허용해주세요.\n브라우저·설정에서 권한을 확인한 뒤 다시 시도해주세요.',
    this.icon = Icons.mic_off,
    required this.onRetry,
    this.onFake,
  });

  final String title;
  final String message;
  final IconData icon;
  final VoidCallback onRetry;

  /// (개발용) 마이크 없이 진행. null이면 버튼 숨김.
  final VoidCallback? onFake;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 56, color: AppColors.danger),
          const SizedBox(height: 16),
          Text(title,
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          Text(message,
              textAlign: TextAlign.center,
              style: const TextStyle(color: AppColors.textSecondary)),
          const SizedBox(height: 24),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.accent),
            onPressed: onRetry,
            child: const Text('다시 시도'),
          ),
          if (onFake != null) ...[
            const SizedBox(height: 8),
            TextButton(
              onPressed: onFake,
              child: const Text('(개발용) 가짜 녹음으로 진행',
                  style: TextStyle(fontSize: 12, color: AppColors.hint)),
            ),
          ],
        ],
      ),
    );
  }
}
