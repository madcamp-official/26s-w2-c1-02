import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/theme/app_colors.dart';

/// 초대코드 표시 다이얼로그 (email-verification-plan §11-2).
///
/// 팀 초대는 초대코드로 통일 — 팀 생성 완료·팀 상세 "+ 초대"가 공유한다.
/// 코드를 큼직하게 보여주고 복사 버튼을 제공한다. 참여자는 홈의
/// "초대코드로 참여" 입력에 이 코드를 넣는다.
Future<void> showInviteCodeDialog(BuildContext context, String code) {
  return showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      title: const Text('팀 초대코드', textAlign: TextAlign.center),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 20),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(14),
            ),
            child: SelectableText(
              code,
              textAlign: TextAlign.center,
              style: const TextStyle(
                  fontSize: 28, fontWeight: FontWeight.w800, letterSpacing: 4),
            ),
          ),
          const SizedBox(height: 12),
          const Text(
            '팀원에게 코드를 공유하세요.\n홈의 "초대코드로 참여"에 입력하면 합류돼요.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 12, color: AppColors.textSecondary),
          ),
        ],
      ),
      actionsAlignment: MainAxisAlignment.center,
      actions: [
        FilledButton.icon(
          style: FilledButton.styleFrom(backgroundColor: AppColors.primary),
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: code));
            if (context.mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('초대코드가 복사됐어요')));
            }
          },
          icon: const Icon(Icons.copy, size: 16),
          label: const Text('복사'),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('닫기'),
        ),
      ],
    ),
  );
}
