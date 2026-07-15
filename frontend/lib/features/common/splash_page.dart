import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';

/// 앱 시작 시 세션 복원(AuthController.booting)이 끝날 때까지 보여주는 로딩 화면.
///
/// 새로고침으로 access 토큰이 사라져도 저장된 세션으로 복원하는 동안, 로그인/홈
/// 판단을 미루고 이 화면을 띄워 화면 깜빡임을 막는다 (app_router 참고).
class SplashPage extends StatelessWidget {
  const SplashPage({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: AppColors.background,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              '말꼬리',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w800,
                color: AppColors.textPrimary,
              ),
            ),
            SizedBox(height: 24),
            SizedBox(
              width: 24,
              height: 24,
              child: CircularProgressIndicator(
                strokeWidth: 2.5,
                color: AppColors.primary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
