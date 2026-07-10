import 'package:flutter/material.dart';

/// Rehearsal.io 색상 팔레트. Figma 시안 기준.
class AppColors {
  AppColors._();

  static const Color background = Color(0xFFFFFFFF);
  static const Color textPrimary = Color(0xFF111111);
  static const Color textSecondary = Color(0xFF666666);
  static const Color hint = Color(0xFFAAAAAA);

  /// 카드/입력 박스의 옅은 회색.
  static const Color surface = Color(0xFFE3E3E3);
  static const Color surfaceAlt = Color(0xFFEDEDED);
  static const Color border = Color(0xFF111111);

  /// 주요 CTA(검정 버튼): "발표 시작하기", "프레젠테이션 팀 만들기".
  static const Color primary = Color(0xFF111111);
  static const Color onPrimary = Color(0xFFFFFFFF);

  /// 발표/질의응답 강조색(앰버): "발표 마치기", "질의응답으로 넘어가기".
  static const Color accent = Color(0xFFFFA726);

  /// 위험/시간초과: "팀 나가기", 발표시간 초과 타이머.
  static const Color danger = Color(0xFFF52222);
}
