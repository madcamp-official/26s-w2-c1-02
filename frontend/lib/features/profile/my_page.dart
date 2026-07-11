import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../state/auth_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 마이페이지 (와이어프레임 i1) — 계정 정보 · 성장 리포트 · 로그아웃 · 탈퇴.
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
              Center(
                child: CircleAvatar(
                  radius: 40,
                  backgroundColor: AppColors.accent.withValues(alpha: 0.15),
                  child: Text(user?.name.characters.first ?? '?',
                      style: const TextStyle(
                          fontSize: 28,
                          fontWeight: FontWeight.w800,
                          color: AppColors.accent)),
                ),
              ),
              const SizedBox(height: 16),
              Center(
                child: Text(user?.name ?? '-',
                    style: const TextStyle(
                        fontSize: 19, fontWeight: FontWeight.w700)),
              ),
              Center(
                child: Text(user?.email ?? '-',
                    style: const TextStyle(
                        fontSize: 13, color: AppColors.textSecondary)),
              ),
              const SizedBox(height: 24),
              _row(context, Icons.badge_outlined, '아이디',
                  trailing: user?.username ?? '-'),
              _row(context, Icons.insights_outlined, '성장 리포트',
                  onTap: () => context.push('/me/growth')),
              _row(context, Icons.lock_outline, '비밀번호 변경',
                  onTap: () => context.push('/me/password')),
              _row(context, Icons.logout, '로그아웃', onTap: () async {
                await context.read<AuthController>().logout();
                if (context.mounted) context.go('/login');
              }),
              _row(context, Icons.person_off_outlined, '회원 탈퇴',
                  danger: true, onTap: () => _confirmDelete(context)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _row(BuildContext context, IconData icon, String label,
      {String? trailing, VoidCallback? onTap, bool danger = false}) {
    final color = danger ? AppColors.danger : AppColors.textPrimary;
    return Column(
      children: [
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: Icon(icon, color: color),
          title: Text(label, style: TextStyle(color: color)),
          trailing: trailing != null
              ? Text(trailing,
                  style: const TextStyle(color: AppColors.textSecondary))
              : (onTap != null
                  ? const Icon(Icons.chevron_right, color: AppColors.hint)
                  : null),
          onTap: onTap,
        ),
        const Divider(height: 1),
      ],
    );
  }

  /// 탈퇴 확인 다이얼로그 (와이어프레임 i3) — 익명화 정책 안내 (db-schema §7.1).
  Future<void> _confirmDelete(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('정말 탈퇴할까요?'),
        content: const Text('계정 정보는 삭제되지만, 팀의 발표 기록은\n'
            "'탈퇴한 사용자' 이름으로 보존돼요."),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('취소')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('탈퇴'),
          ),
        ],
      ),
    );
    if (ok == true && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('탈퇴 API 연동은 Step 4에서 (DELETE /users/me)')));
    }
  }
}
