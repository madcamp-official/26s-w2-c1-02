import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../state/auth_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 마이페이지 (기능 명세 6): 계정 정보 확인 + 로그아웃.
class MyPage extends StatelessWidget {
  const MyPage({super.key});

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final user = auth.user;

    return Scaffold(
      appBar: AppBar(
        leading: const AppBackButton(),
        title: const Text('마이페이지'),
      ),
      body: SafeArea(
        child: ResponsivePage(
          child: ListView(
            padding: const EdgeInsets.symmetric(vertical: 24),
            children: [
              const SizedBox(height: 8),
              Center(
                child: CircleAvatar(
                  radius: 44,
                  backgroundColor: AppColors.surface,
                  child: const Icon(Icons.person,
                      size: 44, color: AppColors.textSecondary),
                ),
              ),
              const SizedBox(height: 24),
              _InfoRow(label: '이름', value: user?.name ?? '-'),
              const Divider(height: 1),
              _InfoRow(label: '이메일', value: user?.email ?? '-'),
              const Divider(height: 1),
              _InfoRow(label: '사용자 ID', value: user?.id ?? '-'),
              const SizedBox(height: 40),
              SizedBox(
                height: 52,
                child: OutlinedButton(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.danger,
                    side: const BorderSide(color: AppColors.danger),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12)),
                  ),
                  onPressed: () async {
                    await context.read<AuthController>().logout();
                    if (context.mounted) context.go('/login');
                  },
                  child: const Text('로그아웃',
                      style: TextStyle(fontWeight: FontWeight.w700)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Row(
        children: [
          SizedBox(
            width: 88,
            child: Text(label,
                style: const TextStyle(color: AppColors.textSecondary)),
          ),
          Expanded(
            child: Text(value,
                style: const TextStyle(fontWeight: FontWeight.w600)),
          ),
        ],
      ),
    );
  }
}
