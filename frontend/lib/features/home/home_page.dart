import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/team.dart';
import '../../state/auth_controller.dart';
import '../../state/team_controller.dart';
import '../common/responsive_page.dart';

/// 메인페이지 (Figma: 메인페이지).
/// "user님, 반가워요" + 내 프레젠테이션 팀 목록 + 추가 FAB + 마이페이지 진입.
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
        backgroundColor: AppColors.surface,
        foregroundColor: AppColors.textPrimary,
        elevation: 0,
        onPressed: () => context.push('/teams/new'),
        child: const Icon(Icons.add),
      ),
      body: SafeArea(
        child: ResponsivePage(
          child: RefreshIndicator(
            onRefresh: () => context.read<TeamController>().load(),
            child: ListView(
              padding: const EdgeInsets.only(top: 24, bottom: 96),
              children: [
                Text('$userName님, 반가워요',
                    style: const TextStyle(
                        fontSize: 26, fontWeight: FontWeight.w800)),
                const SizedBox(height: 8),
                const Text('내 프레젠테이션 팀',
                    style: TextStyle(
                        fontSize: 16, color: AppColors.textSecondary)),
                const SizedBox(height: 16),
                if (teamCtrl.loading && teamCtrl.teams.isEmpty)
                  const Padding(
                    padding: EdgeInsets.only(top: 48),
                    child: Center(child: CircularProgressIndicator()),
                  )
                else
                  ...teamCtrl.teams.map((t) => _TeamCard(team: t)),
              ],
            ),
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
      padding: const EdgeInsets.only(bottom: 20),
      child: Material(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: () => context.push('/teams/${team.id}'),
          child: Container(
            height: 150,
            width: double.infinity,
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(team.name,
                    style: const TextStyle(
                        fontSize: 18, fontWeight: FontWeight.w800)),
                const SizedBox(height: 4),
                Text(team.membersLabel,
                    style: const TextStyle(
                        fontSize: 13, color: AppColors.textSecondary)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
