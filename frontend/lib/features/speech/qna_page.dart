import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/qna.dart';
import '../../data/models/speech.dart';
import '../../data/repositories/speech_repository.dart';
import '../../state/speech_controller.dart';
import '../common/responsive_page.dart';

/// 질의응답 화면 (Figma: 질의응답 Q1/Q3/Q5).
///
/// LLM이 생성한 질문을 하나씩 보여주고, 사용자가 음성으로 답변(목: 답변중…)한 뒤
/// 제출하면 다음 질문으로 넘어간다. 청중 유형에 따라 질문자 캐릭터가 달라진다.
class QnaPage extends StatefulWidget {
  const QnaPage({super.key, required this.speechId});
  final String speechId;

  @override
  State<QnaPage> createState() => _QnaPageState();
}

class _QnaPageState extends State<QnaPage> {
  Speech? _speech;
  List<QnaItem> _questions = [];
  int _current = 0;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    final ctrl = context.read<SpeechController>();
    final speech = await ctrl.ensureLoaded(widget.speechId);
    // 목 저장소에서 직접 질문 생성(추후 백엔드 LLM 연동으로 교체).
    final questions =
        await MockSpeechRepository().generateQna(widget.speechId);
    if (!mounted) return;
    setState(() {
      _speech = speech;
      _questions = questions;
      _loading = false;
    });
  }

  void _submitAnswer() {
    if (_current < _questions.length - 1) {
      setState(() => _current++);
    } else {
      _finish();
    }
  }

  Future<void> _finish() async {
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('질의응답 완료'),
        content: const Text('모든 질문에 답변했어요.\n분석 리포트는 추후 제공됩니다.'),
        actions: [
          FilledButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('확인'),
          ),
        ],
      ),
    );
    if (mounted) context.go('/teams/${_speech?.teamId ?? ''}');
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    final title = _speech?.name ?? 'speech';
    final qNumber = _questions[_current].index;
    final professor = _speech?.audienceType.professorLabel ?? '교수';

    return Scaffold(
      appBar: AppBar(),
      body: SafeArea(
        child: ResponsivePage(
          child: Column(
            children: [
              const Spacer(flex: 2),
              Text(title,
                  style: const TextStyle(
                      fontSize: 22, fontWeight: FontWeight.w800)),
              Text('Q$qNumber.',
                  style: const TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.w800,
                      color: AppColors.accent)),
              const SizedBox(height: 24),

              // 질문자 캐릭터 자리 (실제 캐릭터 이미지 assets는 추후 추가)
              CircleAvatar(
                radius: 56,
                backgroundColor: AppColors.surface,
                child: const Icon(Icons.person,
                    size: 56, color: AppColors.textSecondary),
              ),
              const SizedBox(height: 10),
              Text(professor,
                  style: const TextStyle(fontWeight: FontWeight.w800)),
              const SizedBox(height: 24),

              // 질문 내용
              Text(_questions[_current].question,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 15)),
              const SizedBox(height: 24),

              // 답변 녹음 표시(목)
              Container(
                width: 160,
                height: 160,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(color: AppColors.accent, width: 3),
                ),
                alignment: Alignment.center,
                child: Text('Q$qNumber\n답변중…',
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: AppColors.accent)),
              ),
              const Spacer(flex: 3),
              SizedBox(
                width: double.infinity,
                height: 56,
                child: FilledButton(
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12)),
                  ),
                  onPressed: _submitAnswer,
                  child: Text(
                    _current < _questions.length - 1
                        ? 'Q$qNumber 답변 제출하기'
                        : 'Q$qNumber 답변 제출하고 마치기',
                    style: const TextStyle(
                        fontSize: 17, fontWeight: FontWeight.w800),
                  ),
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
