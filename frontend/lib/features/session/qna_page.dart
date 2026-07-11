import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/enums.dart';
import '../../data/models/qna.dart';
import '../../data/repositories/session_repository.dart';
import '../common/app_back_button.dart';
import '../common/polling_builder.dart';
import '../common/responsive_page.dart';

/// 질의응답 (와이어프레임 f1~f3) — GET /qna 폴링이 단일 소스 (spec §4.4).
///
/// Step 1 범위: 폴링 + 질문/TTS 상태 + 답변 제출(202) + 꼬리질문 등장까지의
/// **데이터 배선**. 실제 TTS 재생/마이크 녹음은 Step 3에서 교체.
class QnaPage extends StatefulWidget {
  const QnaPage({super.key, required this.sessionId});
  final String sessionId;

  @override
  State<QnaPage> createState() => _QnaPageState();
}

class _QnaPageState extends State<QnaPage> {
  bool _submitting = false;

  @override
  Widget build(BuildContext context) {
    final repo = context.read<SessionRepository>();

    return Scaffold(
      appBar: AppBar(leading: const AppBackButton()),
      body: SafeArea(
        child: ResponsivePage(
          child: PollingBuilder<QnaState>(
            fetch: () => repo.getQna(widget.sessionId),
            // 질의응답이 끝날 때까지 계속 폴링 (질문 생성 대기도 포함).
            isDone: (q) => q.status == QnaStatus.ended,
            onDone: (q) {
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (context.mounted) {
                  context.pushReplacement(
                      '/sessions/${widget.sessionId}/qna/complete');
                }
              });
            },
            builder: (context, snap, retry) {
              final qna = snap.data;
              if (snap.error != null) {
                return _ErrorRetry(error: snap.error!, onRetry: retry);
              }
              if (qna == null || qna.questions.isEmpty) {
                return const _GeneratingView();
              }
              final current = qna.currentQuestion ?? qna.questions.first;
              return _QuestionView(
                qna: qna,
                question: current,
                submitting: _submitting,
                onSubmitAnswer: () => _submitAnswer(repo, current.id),
                onPass: () async {
                  await repo.passQuestion(widget.sessionId, current.id);
                },
                onEnd: () async {
                  await repo.endQna(widget.sessionId);
                },
              );
            },
          ),
        ),
      ),
    );
  }

  Future<void> _submitAnswer(SessionRepository repo, String questionId) async {
    setState(() => _submitting = true);
    try {
      // Step 3에서 실제 답변 녹음 파일로 교체.
      await repo.submitAnswer(
        widget.sessionId,
        questionId,
        fileName: 'answer.m4a',
        bytes: utf8.encode('mock-answer-audio'),
      );
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }
}

class _GeneratingView extends StatelessWidget {
  const _GeneratingView();

  @override
  Widget build(BuildContext context) {
    return const Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        CircularProgressIndicator(color: AppColors.accent),
        SizedBox(height: 24),
        Text('AI 청중이 질문을 만들고 있어요…',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
        SizedBox(height: 8),
        Text('슬라이드와 발표 내용을 분석 중이에요.',
            style: TextStyle(color: AppColors.textSecondary)),
      ],
    );
  }
}

class _QuestionView extends StatelessWidget {
  const _QuestionView({
    required this.qna,
    required this.question,
    required this.submitting,
    required this.onSubmitAnswer,
    required this.onPass,
    required this.onEnd,
  });

  final QnaState qna;
  final Question question;
  final bool submitting;
  final VoidCallback onSubmitAnswer;
  final VoidCallback onPass;
  final VoidCallback onEnd;

  @override
  Widget build(BuildContext context) {
    final primaries = qna.questions.where((q) => !q.isFollowUp).length;
    final answer = question.answer;
    final answering = answer != null &&
        answer.status != AnswerStatus.pending; // 제출됨(처리 중 포함)

    return Column(
      children: [
        Row(
          children: [
            const Spacer(),
            Text('Q${question.order}${question.isFollowUp ? '-꼬리' : ''} / $primaries',
                style: const TextStyle(
                    fontWeight: FontWeight.w700, color: AppColors.accent)),
          ],
        ),
        const Spacer(),
        if (question.isFollowUp)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
            decoration: BoxDecoration(
              color: AppColors.accent.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Text('꼬리질문',
                style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: AppColors.accent)),
          ),
        const SizedBox(height: 12),
        CircleAvatar(
          radius: 40,
          backgroundColor: AppColors.accent.withValues(alpha: 0.15),
          child: Text(question.persona.label.characters.first,
              style: const TextStyle(
                  fontSize: 26,
                  fontWeight: FontWeight.w800,
                  color: AppColors.accent)),
        ),
        const SizedBox(height: 8),
        Text(question.persona.professorLabel,
            style: const TextStyle(fontWeight: FontWeight.w800)),
        const SizedBox(height: 16),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(16),
          ),
          child: Text('"${question.text}"',
              style: const TextStyle(fontSize: 15, height: 1.5)),
        ),
        const SizedBox(height: 8),
        if (!question.evidence.isEmpty)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: AppColors.accent.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(
              '근거: '
              '${question.evidence.slides.map((s) => '슬라이드 $s').join(', ')}'
              '${question.evidence.slides.isNotEmpty && question.evidence.transcriptRefs.isNotEmpty ? ' · ' : ''}'
              '${question.evidence.transcriptRefs.map((t) => '발표 $t').join(', ')}',
              style: const TextStyle(fontSize: 11.5, color: AppColors.accent),
            ),
          ),
        const SizedBox(height: 16),
        _ttsStatus(),
        const Spacer(flex: 2),
        if (answering) _answerStatus(answer),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          height: 56,
          child: FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AppColors.accent,
              shape:
                  RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
            onPressed: (submitting || answering) ? null : onSubmitAnswer,
            child: Text(
                answering ? '답변 처리 중… (폴링)' : '답변 완료 (mock 오디오 제출)',
                style: const TextStyle(fontWeight: FontWeight.w800)),
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: TextButton(
                style: TextButton.styleFrom(
                    backgroundColor: AppColors.surface,
                    foregroundColor: AppColors.textPrimary),
                onPressed: answering ? null : onPass,
                child: const Text('모르겠어요 · 패스'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextButton(
                style: TextButton.styleFrom(
                    backgroundColor: AppColors.surface,
                    foregroundColor: AppColors.danger),
                onPressed: onEnd,
                child: const Text('질의응답 마치기'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
      ],
    );
  }

  Widget _ttsStatus() {
    final tts = question.tts;
    return switch (tts.status) {
      AsyncStatus.ready => Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.volume_up, size: 18, color: AppColors.accent),
            const SizedBox(width: 6),
            Text('질문 음성 준비됨 — 재생은 Step 3 (${tts.audioUrl})',
                style: const TextStyle(
                    fontSize: 12, color: AppColors.textSecondary)),
          ],
        ),
      AsyncStatus.failed => const Text('TTS 생성 실패',
          style: TextStyle(fontSize: 12, color: AppColors.danger)),
      _ => const Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            SizedBox(
                width: 14,
                height: 14,
                child: CircularProgressIndicator(
                    strokeWidth: 2, color: AppColors.accent)),
            SizedBox(width: 8),
            Text('질문 음성 합성 중…',
                style:
                    TextStyle(fontSize: 12, color: AppColors.textSecondary)),
          ],
        ),
    };
  }

  Widget _answerStatus(AnswerInfo answer) {
    final label = switch (answer.status) {
      AnswerStatus.processing => '답변을 텍스트로 변환하고 있어요…'
          '${answer.followUpStatus == FollowUpStatus.pending ? ' (꼬리질문 판정 대기)' : ''}',
      AnswerStatus.ready => answer.followUpStatus == FollowUpStatus.pending
          ? '꼬리질문 여부를 판단하고 있어요…'
          : '답변 완료: ${answer.text ?? ''}',
      AnswerStatus.failed => '답변 변환 실패 — 다시 제출해주세요',
      AnswerStatus.pending => '',
    };
    return Text(label,
        textAlign: TextAlign.center,
        style: TextStyle(
            fontSize: 12.5,
            color: answer.status == AnswerStatus.failed
                ? AppColors.danger
                : AppColors.textSecondary));
  }
}

class _ErrorRetry extends StatelessWidget {
  const _ErrorRetry({required this.error, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const Icon(Icons.error_outline, size: 48, color: AppColors.danger),
        const SizedBox(height: 12),
        Text('$error', textAlign: TextAlign.center),
        const SizedBox(height: 12),
        FilledButton(onPressed: onRetry, child: const Text('다시 시도')),
      ],
    );
  }
}
