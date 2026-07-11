import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/enums.dart';
import '../../data/models/session.dart';
import '../../data/models/team.dart';
import '../../data/repositories/team_repository.dart';
import '../../state/auth_controller.dart';
import '../../state/session_controller.dart';
import '../../state/team_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 팀 페이지 (와이어프레임 c3) — 세션 목록 + 새 발표 + 팀 관리 시트(c4).
class TeamDetailPage extends StatefulWidget {
  const TeamDetailPage({super.key, required this.teamId});
  final String teamId;

  @override
  State<TeamDetailPage> createState() => _TeamDetailPageState();
}

class _TeamDetailPageState extends State<TeamDetailPage> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<SessionController>().load(widget.teamId);
      if (context.read<TeamController>().byId(widget.teamId) == null) {
        context.read<TeamController>().load();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final team = context.watch<TeamController>().byId(widget.teamId);
    final sessions = context.watch<SessionController>().sessionsOf(widget.teamId);

    return Scaffold(
      appBar: AppBar(
        leading: const AppBackButton(),
        actions: [
          IconButton(
            tooltip: '팀 관리',
            icon: const Icon(Icons.more_horiz),
            onPressed: () => _showManageSheet(team),
          ),
        ],
      ),
      body: SafeArea(
        child: ResponsivePage(
          child: ListView(
            padding: const EdgeInsets.only(top: 8, bottom: 32),
            children: [
              Text(team?.name ?? '팀',
                  style: const TextStyle(
                      fontSize: 26, fontWeight: FontWeight.w800)),
              const SizedBox(height: 8),
              if (team != null)
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    ...team.members.map((m) => Chip(
                          label: Text(
                            m.userId == team.leaderId
                                ? '${m.name} (팀장)'
                                : m.name,
                            style: const TextStyle(fontSize: 12),
                          ),
                          backgroundColor: m.userId == team.leaderId
                              ? AppColors.accent.withValues(alpha: 0.15)
                              : AppColors.surface,
                        )),
                    ActionChip(
                      label: const Text('+ 초대', style: TextStyle(fontSize: 12)),
                      onPressed: () => _copyInviteLink(team),
                    ),
                  ],
                ),
              const SizedBox(height: 24),
              const Text('발표 세션',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              const SizedBox(height: 12),
              ...sessions.map((s) => _SessionCard(session: s)),
              _AddSessionCard(
                onTap: () =>
                    context.push('/teams/${widget.teamId}/sessions/new'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _copyInviteLink(Team team) async {
    final link =
        await context.read<TeamRepository>().createInviteLink(team.id);
    await Clipboard.setData(ClipboardData(text: link.url));
    if (mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('초대 링크가 클립보드에 복사됐어요')));
    }
  }

  /// 팀 관리 바텀시트 (와이어프레임 c4).
  void _showManageSheet(Team? team) {
    if (team == null) return;
    final myId = context.read<AuthController>().user?.id;
    final isLeader = myId != null && team.isLeader(myId);

    showModalBottomSheet<void>(
      context: context,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('팀 관리',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            ),
            ListTile(
              leading: const Icon(Icons.person_add_alt),
              title: const Text('팀원 초대하기'),
              onTap: () {
                Navigator.pop(ctx);
                _copyInviteLink(team);
              },
            ),
            ListTile(
              leading: const Icon(Icons.logout),
              title: const Text('팀 나가기'),
              onTap: () async {
                Navigator.pop(ctx);
                await context.read<TeamController>().leave(team.id);
                if (mounted) context.go('/');
              },
            ),
            ListTile(
              enabled: isLeader,
              leading: Icon(Icons.delete_outline,
                  color: isLeader ? AppColors.danger : AppColors.hint),
              title: Text('팀 삭제',
                  style: TextStyle(
                      color: isLeader ? AppColors.danger : AppColors.hint)),
              subtitle:
                  isLeader ? null : const Text('팀장만 삭제할 수 있어요'),
              onTap: !isLeader
                  ? null
                  : () async {
                      Navigator.pop(ctx);
                      await context
                          .read<TeamController>()
                          .deleteTeam(team.id);
                      if (mounted) context.go('/');
                    },
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }
}

class _SessionCard extends StatelessWidget {
  const _SessionCard({required this.session});
  final Session session;

  String get _statusLabel => switch (session.status) {
        SessionStatus.draft => '준비 중',
        SessionStatus.recordingInProgress => '발표 중',
        SessionStatus.transcribing => '전사 중',
        SessionStatus.generatingQuestions => '질문 생성 중',
        SessionStatus.qna => '질의응답 중',
        SessionStatus.completed => '완료',
        SessionStatus.failed => '실패',
      };

  @override
  Widget build(BuildContext context) {
    final done = session.status == SessionStatus.completed;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: () => done
              ? context.push('/sessions/${session.id}')
              : context.push('/teams/${session.teamId}/sessions/new'),
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.all(18),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(session.name,
                          style: const TextStyle(
                              fontSize: 16, fontWeight: FontWeight.w800)),
                      const SizedBox(height: 4),
                      Text(
                        '질문 ${session.questionCount}개 · ${session.timeLimitMinutes}분 · '
                        '${session.personas.map((p) => p.label).join('/')}',
                        style: const TextStyle(
                            fontSize: 12, color: AppColors.textSecondary),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                  decoration: BoxDecoration(
                    color: done
                        ? AppColors.accent.withValues(alpha: 0.15)
                        : AppColors.background,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(_statusLabel,
                      style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: done
                              ? AppColors.accent
                              : AppColors.textSecondary)),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _AddSessionCard extends StatelessWidget {
  const _AddSessionCard({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(16),
      onTap: onTap,
      child: Container(
        height: 80,
        width: double.infinity,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.hint, width: 1.4),
        ),
        child: const Center(
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.add, color: AppColors.textSecondary),
              SizedBox(width: 8),
              Text('새 발표 시작',
                  style: TextStyle(
                      fontWeight: FontWeight.w600,
                      color: AppColors.textSecondary)),
            ],
          ),
        ),
      ),
    );
  }
}
