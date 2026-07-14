import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/enums.dart';
import '../../data/models/qna.dart';
import '../../data/models/report.dart';
import '../../data/models/transcript.dart';
import '../../data/repositories/session_repository.dart';
import '../../state/session_controller.dart';
import '../common/app_back_button.dart';
import '../common/polling_builder.dart';
import '../common/responsive_page.dart';
import '../report/report_widgets.dart';

/// 이전 발표 상세 (와이어프레임 07 g1·g2 + 08 h1) — 스크립트/Q&A/리포트 탭.
/// spec §5.1: 탭은 세션 하위 리소스(transcript·qna·report)를 재사용한다.
class SessionDetailPage extends StatelessWidget {
  const SessionDetailPage({super.key, required this.sessionId});
  final String sessionId;

  @override
  Widget build(BuildContext context) {
    final name =
        context.read<SessionController>().byId(sessionId)?.name ?? '발표 상세';

    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          leading: const AppBackButton(),
          title: Text(name),
          bottom: const TabBar(
            labelColor: AppColors.textPrimary,
            unselectedLabelColor: AppColors.textSecondary,
            indicatorColor: AppColors.accent,
            tabs: [
              Tab(text: '스크립트'),
              Tab(text: 'Q&A 로그'),
              Tab(text: '리포트'),
            ],
          ),
        ),
        body: SafeArea(
          child: ResponsivePage(
            child: TabBarView(
              children: [
                _TranscriptTab(sessionId: sessionId),
                _QnaLogTab(sessionId: sessionId),
                _ReportTab(sessionId: sessionId),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 스크립트
// ---------------------------------------------------------------------------
class _TranscriptTab extends StatelessWidget {
  const _TranscriptTab({required this.sessionId});
  final String sessionId;

  @override
  Widget build(BuildContext context) {
    final repo = context.read<SessionRepository>();
    return FutureBuilder<Transcript>(
      future: repo.getTranscript(sessionId),
      builder: (context, snap) {
        if (snap.hasError) return _Message('불러오지 못했어요: ${snap.error}');
        if (!snap.hasData) return const _Loading();
        final t = snap.data!;
        if (t.status == AsyncStatus.failed) {
          return _Message(t.error?.message ?? '전사에 실패했어요');
        }
        if (t.status != AsyncStatus.ready) {
          return const _Loading(label: '전사를 준비하고 있어요…');
        }
        if (t.segments.isEmpty) return const _Message('전사 내용이 없어요.');
        return ListView.separated(
          padding: const EdgeInsets.symmetric(vertical: 16),
          itemCount: t.segments.length,
          separatorBuilder: (_, _) => const SizedBox(height: 16),
          itemBuilder: (context, i) {
            final seg = t.segments[i];
            return Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: AppColors.surface,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(seg.ts,
                      style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: AppColors.textSecondary,
                          fontFeatures: [FontFeature.tabularFigures()])),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(seg.text,
                      style: const TextStyle(fontSize: 14, height: 1.55)),
                ),
              ],
            );
          },
        );
      },
    );
  }
}

// ---------------------------------------------------------------------------
// Q&A 로그
// ---------------------------------------------------------------------------
class _QnaLogTab extends StatelessWidget {
  const _QnaLogTab({required this.sessionId});
  final String sessionId;

  @override
  Widget build(BuildContext context) {
    final repo = context.read<SessionRepository>();
    return FutureBuilder<QnaState>(
      future: repo.getQna(sessionId),
      builder: (context, snap) {
        if (snap.hasError) return _Message('불러오지 못했어요: ${snap.error}');
        if (!snap.hasData) return const _Loading();
        final qna = snap.data!;
        if (qna.questions.isEmpty) return const _Message('질의응답 기록이 없어요.');
        return ListView.separated(
          padding: const EdgeInsets.symmetric(vertical: 16),
          itemCount: qna.questions.length,
          separatorBuilder: (_, _) => const SizedBox(height: 14),
          itemBuilder: (context, i) => _QnaLogItem(question: qna.questions[i]),
        );
      },
    );
  }
}

class _QnaLogItem extends StatelessWidget {
  const _QnaLogItem({required this.question});
  final Question question;

  @override
  Widget build(BuildContext context) {
    final answer = question.answer;
    final color = strategyColor(question.strategy);
    return Container(
      // 꼬리질문은 살짝 들여쓰기.
      margin: EdgeInsets.only(left: question.isFollowUp ? 20 : 0),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surfaceAlt,
        borderRadius: BorderRadius.circular(16),
        border: question.isFollowUp
            ? Border(left: BorderSide(color: color, width: 3))
            : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(question.persona.professorLabel,
                  style: const TextStyle(
                      fontSize: 12, fontWeight: FontWeight.w800)),
              const SizedBox(width: 6),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.14),
                    borderRadius: BorderRadius.circular(8)),
                child: Text(question.strategy.label,
                    style: TextStyle(
                        fontSize: 10.5,
                        fontWeight: FontWeight.w700,
                        color: color)),
              ),
              if (question.isFollowUp) ...[
                const SizedBox(width: 6),
                const Text('꼬리질문',
                    style: TextStyle(
                        fontSize: 10.5,
                        fontWeight: FontWeight.w700,
                        color: AppColors.accent)),
              ],
            ],
          ),
          const SizedBox(height: 8),
          Text('Q. ${question.text}',
              style: const TextStyle(fontSize: 14, height: 1.5)),
          if (!question.evidence.isEmpty) ...[
            const SizedBox(height: 6),
            Text(_evidenceText(question.evidence),
                style: const TextStyle(fontSize: 11, color: AppColors.accent)),
          ],
          const SizedBox(height: 10),
          _AnswerLine(answer: answer),
        ],
      ),
    );
  }

  String _evidenceText(Evidence e) {
    final slides = e.slides.map((s) => '슬라이드 $s').join(', ');
    final refs = e.transcriptRefs.map((t) => '발표 $t').join(', ');
    final sep = e.slides.isNotEmpty && e.transcriptRefs.isNotEmpty ? ' · ' : '';
    return '근거: $slides$sep$refs';
  }
}

class _AnswerLine extends StatelessWidget {
  const _AnswerLine({required this.answer});
  final AnswerInfo? answer;

  @override
  Widget build(BuildContext context) {
    final a = answer;
    final (text, muted) = switch (a?.status) {
      null || AnswerStatus.pending => ('답변하지 않았어요', true),
      AnswerStatus.failed => ('답변 변환에 실패했어요', true),
      _ => a!.text == null || a.text!.isEmpty
          ? ('패스했어요', true)
          : ('A. ${a.text}', false),
    };
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(muted ? Icons.remove_circle_outline : Icons.record_voice_over,
            size: 16,
            color: muted ? AppColors.hint : AppColors.textSecondary),
        const SizedBox(width: 8),
        Expanded(
          child: Text(text,
              style: TextStyle(
                  fontSize: 13.5,
                  height: 1.5,
                  fontStyle: muted ? FontStyle.italic : FontStyle.normal,
                  color: muted ? AppColors.hint : AppColors.textPrimary)),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// 리포트
// ---------------------------------------------------------------------------
class _ReportTab extends StatelessWidget {
  const _ReportTab({required this.sessionId});
  final String sessionId;

  @override
  Widget build(BuildContext context) {
    final repo = context.read<SessionRepository>();
    return PollingBuilder<Report>(
      fetch: () => repo.getReport(sessionId),
      isDone: (r) => r.status.isDone,
      builder: (context, snap, retry) {
        final r = snap.data;
        if (snap.error != null) {
          // 404 등 — 아직 리포트가 없을 수 있음.
          return _Message('리포트를 불러오지 못했어요.\n${snap.error}');
        }
        if (r == null) return const _Loading();
        if (r.status == AsyncStatus.failed) {
          return _Message(
            r.error?.message ?? '리포트 생성에 실패했어요',
            action: '다시 생성',
            onAction: () async {
              // 202 접수 확정 후 폴링 재시작 — 접수 전에 GET이 먼저 가면
              // 옛 failed를 보고 폴링이 즉시 끝나는 레이스가 있다.
              await repo.regenerateReport(sessionId);
              retry();
            },
          );
        }
        if (r.status != AsyncStatus.ready) {
          return const _Loading(label: '리포트를 생성하고 있어요…');
        }
        return ReportView(report: r);
      },
    );
  }
}

// ---------------------------------------------------------------------------
// 공통 소품
// ---------------------------------------------------------------------------
class _Loading extends StatelessWidget {
  const _Loading({this.label});
  final String? label;
  @override
  Widget build(BuildContext context) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator(color: AppColors.accent),
            if (label != null) ...[
              const SizedBox(height: 16),
              Text(label!,
                  style: const TextStyle(color: AppColors.textSecondary)),
            ],
          ],
        ),
      );
}

class _Message extends StatelessWidget {
  const _Message(this.text, {this.action, this.onAction});
  final String text;
  final String? action;
  final VoidCallback? onAction;
  @override
  Widget build(BuildContext context) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(text,
                textAlign: TextAlign.center,
                style: const TextStyle(color: AppColors.textSecondary)),
            if (action != null && onAction != null) ...[
              const SizedBox(height: 12),
              FilledButton(
                  style: FilledButton.styleFrom(
                      backgroundColor: AppColors.accent),
                  onPressed: onAction,
                  child: Text(action!)),
            ],
          ],
        ),
      );
}
