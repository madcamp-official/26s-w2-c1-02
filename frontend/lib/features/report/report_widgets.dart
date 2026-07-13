import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/enums.dart';
import '../../data/models/report.dart';

/// 전략별 고정 색상 — 단일 리포트 막대·성장 라인에서 공통 사용.
Color strategyColor(QuestionStrategy s) => switch (s) {
      QuestionStrategy.detailProbe => const Color(0xFFFFAA00), // amber
      QuestionStrategy.bigPicture => const Color(0xFF3B82F6), // blue
      QuestionStrategy.basicConcept => const Color(0xFF10B981), // green
      QuestionStrategy.numericVerification => const Color(0xFF8B5CF6), // purple
    };

/// 단일 세션 리포트 렌더 (spec §5.2). ready 상태의 [Report]만 받는다.
/// 07 발표 상세의 리포트 탭에서 사용.
class ReportView extends StatelessWidget {
  const ReportView({super.key, required this.report});
  final Report report;

  @override
  Widget build(BuildContext context) {
    final habits = report.speakingHabits;
    // sparse 대응: 존재하는 전략만, 점수 내림차순.
    final scores = report.typeScores.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));

    return ListView(
      padding: const EdgeInsets.symmetric(vertical: 20),
      children: [
        if (report.insight != null) ...[
          _InsightCard(text: report.insight!),
          const SizedBox(height: 24),
        ],

        const _SectionTitle('전략별 답변 점수'),
        const SizedBox(height: 12),
        if (scores.isEmpty)
          const Text('채점된 질문이 없어요.',
              style: TextStyle(color: AppColors.textSecondary))
        else
          ...scores.map((e) => _ScoreBar(strategy: e.key, score: e.value)),

        if (report.strongTypes.isNotEmpty || report.weakTypes.isNotEmpty) ...[
          const SizedBox(height: 20),
          _StrengthRow(label: '강점', types: report.strongTypes, strong: true),
          const SizedBox(height: 8),
          _StrengthRow(label: '보완', types: report.weakTypes, strong: false),
        ],

        if (habits != null) ...[
          const SizedBox(height: 28),
          const _SectionTitle('발표 습관'),
          const SizedBox(height: 12),
          _HabitsCard(habits: habits),
        ],
      ],
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Text(text,
      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800));
}

class _InsightCard extends StatelessWidget {
  const _InsightCard({required this.text});
  final String text;
  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.accent.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.lightbulb_outline, size: 20, color: AppColors.accent),
          const SizedBox(width: 10),
          Expanded(
            child: Text(text,
                style: const TextStyle(fontSize: 14, height: 1.5)),
          ),
        ],
      ),
    );
  }
}

class _ScoreBar extends StatelessWidget {
  const _ScoreBar({required this.strategy, required this.score});
  final QuestionStrategy strategy;
  final double score;

  @override
  Widget build(BuildContext context) {
    final color = strategyColor(strategy);
    final pct = (score.clamp(0, 1) * 100).round();
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(strategy.label,
                    style: const TextStyle(
                        fontSize: 13, fontWeight: FontWeight.w600)),
              ),
              Text('$pct%',
                  style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w800,
                      color: color)),
            ],
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: LinearProgressIndicator(
              value: score.clamp(0, 1).toDouble(),
              minHeight: 8,
              backgroundColor: AppColors.surface,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

class _StrengthRow extends StatelessWidget {
  const _StrengthRow(
      {required this.label, required this.types, required this.strong});
  final String label;
  final List<QuestionStrategy> types;
  final bool strong;

  @override
  Widget build(BuildContext context) {
    if (types.isEmpty) return const SizedBox.shrink();
    final color = strong ? const Color(0xFF10B981) : AppColors.danger;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 40,
          child: Text(label,
              style: TextStyle(
                  fontSize: 13, fontWeight: FontWeight.w800, color: color)),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Wrap(
            spacing: 6,
            runSpacing: 6,
            children: types
                .map((t) => Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: color.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(t.label,
                          style: TextStyle(fontSize: 12, color: color)),
                    ))
                .toList(),
          ),
        ),
      ],
    );
  }
}

class _HabitsCard extends StatelessWidget {
  const _HabitsCard({required this.habits});
  final SpeakingHabits habits;

  String _mmss(int s) =>
      '${(s ~/ 60).toString().padLeft(2, '0')}:${(s % 60).toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
          color: AppColors.surfaceAlt, borderRadius: BorderRadius.circular(16)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _Metric(
                  label: '분당 단어',
                  value: '${habits.wordsPerMinute.round()}',
                  unit: 'WPM'),
              _Metric(
                  label: '필러 워드',
                  value: '${habits.fillerWordCount}',
                  unit: '회'),
              _Metric(
                label: '발표 시간',
                value: _mmss(habits.actualSeconds),
                unit: '/ ${_mmss(habits.timeLimitSeconds)}',
                danger: habits.overTime,
              ),
            ],
          ),
          if (habits.fillerWords.isNotEmpty) ...[
            const SizedBox(height: 16),
            const Divider(height: 1),
            const SizedBox(height: 12),
            const Text('자주 쓴 간투사',
                style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: AppColors.textSecondary)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: habits.fillerWords
                  .map((f) => Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 10, vertical: 5),
                        decoration: BoxDecoration(
                          color: AppColors.background,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: AppColors.surface),
                        ),
                        child: Text('“${f.word}” ${f.count}',
                            style: const TextStyle(fontSize: 12)),
                      ))
                  .toList(),
            ),
          ],
          if (habits.overTime) ...[
            const SizedBox(height: 12),
            Text(
                '제한시간을 ${_mmss(habits.actualSeconds - habits.timeLimitSeconds)} 초과했어요.',
                style: const TextStyle(fontSize: 12, color: AppColors.danger)),
          ],
        ],
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({
    required this.label,
    required this.value,
    required this.unit,
    this.danger = false,
  });
  final String label;
  final String value;
  final String unit;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: const TextStyle(
                  fontSize: 11.5, color: AppColors.textSecondary)),
          const SizedBox(height: 4),
          Text(value,
              style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w800,
                  color: danger ? AppColors.danger : AppColors.textPrimary)),
          Text(unit,
              style: const TextStyle(
                  fontSize: 11, color: AppColors.textSecondary)),
        ],
      ),
    );
  }
}
