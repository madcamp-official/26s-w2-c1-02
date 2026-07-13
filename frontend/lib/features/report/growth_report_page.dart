import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/enums.dart';
import '../../data/models/report.dart';
import '../../data/repositories/session_repository.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';
import 'report_widgets.dart';

/// 성장 리포트 (와이어프레임 08 h2) — 회차별 전략 점수 추이.
/// GET /users/me/report/growth. 시리즈는 sparse(회차마다 물어본 전략만)이라
/// 전략별로 존재하는 회차만 이어 그린다(gap은 건너뜀).
class GrowthReportPage extends StatefulWidget {
  const GrowthReportPage({super.key});

  @override
  State<GrowthReportPage> createState() => _GrowthReportPageState();
}

class _GrowthReportPageState extends State<GrowthReportPage> {
  String _range = 'all'; // all | recent5

  @override
  Widget build(BuildContext context) {
    final repo = context.read<SessionRepository>();
    return Scaffold(
      appBar: AppBar(
        leading: const AppBackButton(fallbackLocation: '/me'),
        title: const Text('성장 리포트'),
      ),
      body: SafeArea(
        child: ResponsivePage(
          child: FutureBuilder<GrowthReport>(
            future: repo.getGrowthReport(range: _range),
            builder: (context, snap) {
              if (snap.hasError) {
                return _centered('불러오지 못했어요: ${snap.error}');
              }
              if (!snap.hasData) {
                return const Center(
                    child: CircularProgressIndicator(color: AppColors.accent));
              }
              final report = snap.data!;
              // x축 시간순 보장 (스펙이 정렬을 명시하지 않음 → FE가 정렬).
              final series = [...report.series]
                ..sort((a, b) => a.date.compareTo(b.date));

              return ListView(
                padding: const EdgeInsets.symmetric(vertical: 20),
                children: [
                  _RangeToggle(
                    range: _range,
                    onChanged: (r) => setState(() => _range = r),
                  ),
                  const SizedBox(height: 20),
                  if (series.isEmpty)
                    _centered('아직 완료된 발표가 없어요.\n발표를 마치면 여기에 추이가 쌓여요.')
                  else ...[
                    _GrowthChart(series: series),
                    const SizedBox(height: 16),
                    if (series.length == 1)
                      const Text('회차가 2회 이상 쌓이면 추이선이 그려져요.',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                              fontSize: 12, color: AppColors.textSecondary)),
                    const SizedBox(height: 8),
                    _Legend(series: series),
                    if (report.insight != null) ...[
                      const SizedBox(height: 24),
                      _GrowthInsight(text: report.insight!),
                    ],
                  ],
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  Widget _centered(String msg) => Padding(
        padding: const EdgeInsets.only(top: 80),
        child: Text(msg,
            textAlign: TextAlign.center,
            style: const TextStyle(color: AppColors.textSecondary)),
      );
}

/// 시리즈에 등장한 전략을 enum 순서로 (sparse 대응).
List<QuestionStrategy> _plottedStrategies(List<GrowthPoint> series) {
  final present = <QuestionStrategy>{};
  for (final p in series) {
    present.addAll(p.typeScores.keys);
  }
  return QuestionStrategy.values.where(present.contains).toList();
}

class _RangeToggle extends StatelessWidget {
  const _RangeToggle({required this.range, required this.onChanged});
  final String range;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    Widget seg(String value, String label) {
      final on = range == value;
      return Expanded(
        child: GestureDetector(
          onTap: () => onChanged(value),
          child: Container(
            height: 38,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: on ? AppColors.primary : Colors.transparent,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(label,
                style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: on ? AppColors.onPrimary : AppColors.textSecondary)),
          ),
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
          color: AppColors.surface, borderRadius: BorderRadius.circular(12)),
      child: Row(children: [seg('all', '전체'), seg('recent5', '최근 5회')]),
    );
  }
}

class _GrowthChart extends StatelessWidget {
  const _GrowthChart({required this.series});
  final List<GrowthPoint> series;

  @override
  Widget build(BuildContext context) {
    final strategies = _plottedStrategies(series);
    return SizedBox(
      height: 240,
      width: double.infinity,
      child: CustomPaint(
        painter: _GrowthChartPainter(series: series, strategies: strategies),
      ),
    );
  }
}

class _GrowthChartPainter extends CustomPainter {
  _GrowthChartPainter({required this.series, required this.strategies});
  final List<GrowthPoint> series;
  final List<QuestionStrategy> strategies;

  static const double _leftPad = 34;
  static const double _bottomPad = 28;
  static const double _topPad = 8;
  static const double _rightPad = 8;

  @override
  void paint(Canvas canvas, Size size) {
    final plot = Rect.fromLTRB(
        _leftPad, _topPad, size.width - _rightPad, size.height - _bottomPad);
    final n = series.length;

    double xForIndex(int i) => n == 1
        ? plot.center.dx
        : plot.left + plot.width * (i / (n - 1));
    double yForScore(double v) => plot.bottom - plot.height * v.clamp(0, 1);

    // --- 격자 + Y 라벨 (0 / 50 / 100%) ---
    final grid = Paint()
      ..color = AppColors.surface
      ..strokeWidth = 1;
    final labelStyle = const TextStyle(
        fontSize: 10, color: AppColors.hint, fontWeight: FontWeight.w600);
    for (final frac in [0.0, 0.5, 1.0]) {
      final y = yForScore(frac);
      canvas.drawLine(Offset(plot.left, y), Offset(plot.right, y), grid);
      _text(canvas, '${(frac * 100).round()}%', Offset(0, y - 6), labelStyle,
          width: _leftPad - 6, align: TextAlign.right);
    }

    // --- 전략별 추이선 (존재하는 회차만 연결) ---
    for (final s in strategies) {
      final pts = <Offset>[];
      for (var i = 0; i < n; i++) {
        final v = series[i].typeScores[s];
        if (v != null) pts.add(Offset(xForIndex(i), yForScore(v)));
      }
      if (pts.isEmpty) continue;
      final color = strategyColor(s);
      final line = Paint()
        ..color = color
        ..strokeWidth = 2.5
        ..strokeCap = StrokeCap.round
        ..style = PaintingStyle.stroke;
      if (pts.length > 1) {
        final path = Path()..moveTo(pts.first.dx, pts.first.dy);
        for (final p in pts.skip(1)) {
          path.lineTo(p.dx, p.dy);
        }
        canvas.drawPath(path, line);
      }
      final dot = Paint()..color = color;
      final dotBg = Paint()..color = AppColors.background;
      for (final p in pts) {
        canvas.drawCircle(p, 4.5, dotBg);
        canvas.drawCircle(p, 3, dot);
      }
    }

    // --- X 라벨 (회차명) ---
    for (var i = 0; i < n; i++) {
      _text(canvas, series[i].name, Offset(xForIndex(i) - 40, plot.bottom + 8),
          const TextStyle(fontSize: 10, color: AppColors.textSecondary),
          width: 80, align: TextAlign.center);
    }
  }

  void _text(Canvas canvas, String s, Offset at, TextStyle style,
      {required double width, TextAlign align = TextAlign.left}) {
    final tp = TextPainter(
      text: TextSpan(text: s, style: style),
      textAlign: align,
      textDirection: TextDirection.ltr,
      maxLines: 1,
      ellipsis: '…',
    )..layout(maxWidth: width);
    tp.paint(canvas, at);
  }

  @override
  bool shouldRepaint(_GrowthChartPainter old) =>
      old.series != series || old.strategies != strategies;
}

class _Legend extends StatelessWidget {
  const _Legend({required this.series});
  final List<GrowthPoint> series;

  @override
  Widget build(BuildContext context) {
    final strategies = _plottedStrategies(series);
    return Wrap(
      alignment: WrapAlignment.center,
      spacing: 14,
      runSpacing: 8,
      children: strategies.map((s) {
        final latest = _latest(s);
        return Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
                width: 10,
                height: 10,
                decoration: BoxDecoration(
                    color: strategyColor(s), shape: BoxShape.circle)),
            const SizedBox(width: 6),
            Text(
                latest == null
                    ? s.label
                    : '${s.label} ${(latest * 100).round()}%',
                style: const TextStyle(fontSize: 12)),
          ],
        );
      }).toList(),
    );
  }

  /// 그 전략을 가진 가장 최근(마지막) 회차의 점수.
  double? _latest(QuestionStrategy s) {
    for (final p in series.reversed) {
      final v = p.typeScores[s];
      if (v != null) return v;
    }
    return null;
  }
}

class _GrowthInsight extends StatelessWidget {
  const _GrowthInsight({required this.text});
  final String text;
  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
          color: AppColors.surfaceAlt, borderRadius: BorderRadius.circular(16)),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.trending_up, size: 20, color: Color(0xFF10B981)),
          const SizedBox(width: 10),
          Expanded(
              child:
                  Text(text, style: const TextStyle(fontSize: 14, height: 1.5))),
        ],
      ),
    );
  }
}
