import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import 'app_back_button.dart';
import 'responsive_page.dart';

/// Step 1 라우트 골격용 페이지.
/// 어떤 화면인지(와이어프레임 그룹·구현 예정 Step)를 표시해 팀원이
/// 라우팅/딥링크를 미리 검증할 수 있게 한다.
class PlaceholderPage extends StatelessWidget {
  const PlaceholderPage({
    super.key,
    required this.title,
    required this.wireframe,
    required this.plannedStep,
    this.description,
  });

  final String title;

  /// 예: '06 질의응답 (f4)'
  final String wireframe;

  /// 예: 'Step 3 (Day 5)'
  final String plannedStep;
  final String? description;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(leading: const AppBackButton(), title: Text(title)),
      body: SafeArea(
        child: ResponsivePage(
          child: Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.construction,
                    size: 48, color: AppColors.accent),
                const SizedBox(height: 16),
                Text(title,
                    style: const TextStyle(
                        fontSize: 20, fontWeight: FontWeight.w800)),
                const SizedBox(height: 8),
                Text('와이어프레임: $wireframe',
                    style: const TextStyle(color: AppColors.textSecondary)),
                Text('구현 예정: $plannedStep',
                    style: const TextStyle(color: AppColors.textSecondary)),
                if (description != null) ...[
                  const SizedBox(height: 12),
                  Text(description!,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                          fontSize: 13, color: AppColors.textSecondary)),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
