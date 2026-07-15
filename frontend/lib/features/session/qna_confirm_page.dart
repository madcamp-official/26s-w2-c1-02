import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/network/api_client.dart';
import '../../core/theme/app_colors.dart';
import '../../data/repositories/session_repository.dart';
import '../../state/session_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 질의응답 전환 확인 (와이어프레임 e3).
class QnaConfirmPage extends StatefulWidget {
  const QnaConfirmPage({super.key, required this.sessionId});
  final String sessionId;

  @override
  State<QnaConfirmPage> createState() => _QnaConfirmPageState();
}

class _QnaConfirmPageState extends State<QnaConfirmPage> {
  bool _busy = false;

  /// 질문 생성 시작(202) 후 Q&A 화면으로. 실패해도 화면이 무반응이면 안 된다 —
  /// 이미 시작된 세션(QNA_ALREADY_STARTED)은 그냥 Q&A로 이동하고,
  /// 그 외 오류는 스낵바로 알리고 버튼을 되살린다.
  Future<void> _start() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await context.read<SessionRepository>().generateQna(widget.sessionId);
    } on ApiException catch (e) {
      if (e.code != 'QNA_ALREADY_STARTED') {
        // 뒤로가기로 재진입해 다시 누른 경우 등은 이동만 하면 된다.
        if (mounted) {
          setState(() => _busy = false);
          ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('질의응답을 시작하지 못했어요: ${e.message}')));
        }
        return;
      }
    } catch (e) {
      if (mounted) {
        setState(() => _busy = false);
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('질의응답을 시작하지 못했어요: $e')));
      }
      return;
    }
    if (mounted) {
      context.pushReplacement('/sessions/${widget.sessionId}/qna');
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = context.watch<SessionController>().byId(widget.sessionId);

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
                  onPressed: _busy ? null : _start,
                  child: Text(_busy ? '시작하는 중…' : '질의응답 시작하기',
                      style: const TextStyle(
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
