import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/team.dart';
import '../../state/auth_controller.dart';
import '../../state/team_controller.dart';
import '../common/responsive_page.dart';

/// 메인 페이지 (와이어프레임 b1) — 내 팀 목록 + 팀 추가 + 마이페이지 진입.
class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<TeamController>().load();
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController>();
    final teamCtrl = context.watch<TeamController>();
    final userName = auth.user?.name ?? 'user';

    return Scaffold(
      appBar: AppBar(
        title: const Text('말꼬리',
            style: TextStyle(
                fontWeight: FontWeight.w800, color: AppColors.accent)),
        actions: [
          IconButton(
            tooltip: '마이페이지',
            icon: const Icon(Icons.account_circle_outlined),
            onPressed: () => context.push('/me'),
          ),
          const SizedBox(width: 8),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        backgroundColor: AppColors.accent,
        foregroundColor: Colors.white,
        onPressed: () => context.push('/teams/new'),
        child: const Icon(Icons.add),
      ),
      body: SafeArea(
        child: ResponsivePage(
          child: RefreshIndicator(
            onRefresh: () => context.read<TeamController>().load(),
            child: ListView(
              padding: const EdgeInsets.only(top: 16, bottom: 96),
              children: [
                Text('$userName님, 반가워요',
                    style: const TextStyle(
                        fontSize: 26, fontWeight: FontWeight.w800)),
                const SizedBox(height: 8),
                const Text('내 프레젠테이션 팀',
                    style: TextStyle(
                        fontSize: 14, color: AppColors.textSecondary)),
                const SizedBox(height: 16),
                if (teamCtrl.loading && teamCtrl.teams.isEmpty)
                  const Padding(
                    padding: EdgeInsets.only(top: 48),
                    child: Center(child: CircularProgressIndicator()),
                  )
                else ...[
                  ...teamCtrl.teams.map((t) => _TeamCard(team: t)),
                  _JoinByCodeCard(onTap: () => _joinByCode(context)),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 초대코드 입력 → 기존 초대 수락 화면(/invites/{code}) 재사용 (§11-2).
Future<void> _joinByCode(BuildContext context) async {
  final controller = TextEditingController();
  final code = await showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      title: const Text('초대코드로 참여'),
      content: TextField(
        controller: controller,
        autofocus: true,
        maxLength: 8,
        textCapitalization: TextCapitalization.characters,
        textAlign: TextAlign.center,
        style: const TextStyle(
            fontSize: 22, fontWeight: FontWeight.w700, letterSpacing: 4),
        decoration: const InputDecoration(
            hintText: '8자 코드', counterText: ''),
        onSubmitted: (v) => Navigator.pop(ctx, v),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(ctx), child: const Text('취소')),
        FilledButton(
          style: FilledButton.styleFrom(backgroundColor: AppColors.primary),
          onPressed: () => Navigator.pop(ctx, controller.text),
          child: const Text('확인'),
        ),
      ],
    ),
  );
  controller.dispose();
  final trimmed = code?.trim().toUpperCase() ?? '';
  if (trimmed.isEmpty || !context.mounted) return;
  context.push('/invites/$trimmed'); // 미리보기(팀명·인원) → 수락은 기존 화면 몫
}

/// 팀 목록 하단의 "초대코드로 참여" 진입 카드.
class _JoinByCodeCard extends StatelessWidget {
  const _JoinByCodeCard({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(vertical: 18),
          decoration: BoxDecoration(
            border: Border.all(color: AppColors.hint.withValues(alpha: 0.6)),
            borderRadius: BorderRadius.circular(16),
          ),
          child: const Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.key, size: 18, color: AppColors.textSecondary),
              SizedBox(width: 8),
              Text('초대코드로 참여',
                  style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: AppColors.textSecondary)),
            ],
          ),
        ),
      ),
    );
  }
}

class _TeamCard extends StatelessWidget {
  const _TeamCard({required this.team});
  final Team team;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Material(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: () => context.push('/teams/${team.id}'),
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.all(20),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(team.name,
                          style: const TextStyle(
                              fontSize: 17, fontWeight: FontWeight.w800)),
                      const SizedBox(height: 4),
                      Text('${team.membersLabel} · 발표 ${team.sessionCount}회',
                          style: const TextStyle(
                              fontSize: 13, color: AppColors.textSecondary)),
                    ],
                  ),
                ),
                const Icon(Icons.chevron_right, color: AppColors.hint),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
