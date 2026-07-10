import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_colors.dart';
import '../../data/models/speech.dart';
import '../../data/models/team.dart';
import '../../state/speech_controller.dart';
import '../../state/team_controller.dart';
import '../common/app_back_button.dart';
import '../common/responsive_page.dart';

/// 프레젠테이션 팀 화면 (Figma: 프레젠테이션 팀 화면).
/// 스피치 목록 + 스피치 추가(+) + 팀원 초대하기 / 팀 나가기.
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
      context.read<SpeechController>().load(widget.teamId);
    });
  }

  @override
  Widget build(BuildContext context) {
    final team = context.watch<TeamController>().byId(widget.teamId);
    final speeches =
        context.watch<SpeechController>().speechesOf(widget.teamId);

    return Scaffold(
      appBar: AppBar(leading: const AppBackButton()),
      body: SafeArea(
        child: ResponsivePage(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(team?.name ?? '팀',
                  style: const TextStyle(
                      fontSize: 26, fontWeight: FontWeight.w800)),
              const SizedBox(height: 4),
              Text(team?.membersLabel ?? '',
                  style: const TextStyle(
                      fontSize: 14, color: AppColors.textSecondary)),
              const SizedBox(height: 20),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.only(bottom: 16),
                  children: [
                    ...speeches.map((s) => _SpeechCard(speech: s)),
                    _AddSpeechCard(
                      onTap: () => context
                          .push('/teams/${widget.teamId}/speeches/new'),
                    ),
                  ],
                ),
              ),
              _BottomActions(team: team, teamId: widget.teamId),
              const SizedBox(height: 8),
            ],
          ),
        ),
      ),
    );
  }
}

class _SpeechCard extends StatelessWidget {
  const _SpeechCard({required this.speech});
  final Speech speech;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Material(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          // 기능 명세 3): 지금은 페이지 이동만(발표중 화면). 세부 기능은 추후.
          onTap: () => context.push('/speeches/${speech.id}/present'),
          child: Container(
            height: 130,
            width: double.infinity,
            padding: const EdgeInsets.all(20),
            alignment: Alignment.topLeft,
            child: Text(speech.name,
                style: const TextStyle(
                    fontSize: 18, fontWeight: FontWeight.w800)),
          ),
        ),
      ),
    );
  }
}

class _AddSpeechCard extends StatelessWidget {
  const _AddSpeechCard({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(16),
      onTap: onTap,
      child: Container(
        height: 130,
        width: double.infinity,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: AppColors.border, width: 1.5),
        ),
        // 점선 느낌은 실제 구현 시 dotted_border 패키지로 교체 가능.
        child: const Center(
          child: Icon(Icons.add, size: 32, color: AppColors.textPrimary),
        ),
      ),
    );
  }
}

class _BottomActions extends StatelessWidget {
  const _BottomActions({required this.team, required this.teamId});
  final Team? team;
  final String teamId;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: SizedBox(
            height: 52,
            child: TextButton(
              style: TextButton.styleFrom(
                backgroundColor: AppColors.surface,
                foregroundColor: AppColors.textPrimary,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12)),
              ),
              onPressed: () {
                // TODO: 팀원 초대 (실제 인증/초대 로직 연동 시 구현)
              },
              child: const Text('팀원 초대하기'),
            ),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: SizedBox(
            height: 52,
            child: FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.danger,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12)),
              ),
              onPressed: () => _confirmLeave(context),
              child: const Text('팀 나가기',
                  style: TextStyle(fontWeight: FontWeight.w700)),
            ),
          ),
        ),
      ],
    );
  }

  Future<void> _confirmLeave(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('팀 나가기'),
        content: Text('${team?.name ?? '이 팀'}에서 나갈까요?'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('취소')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('나가기'),
          ),
        ],
      ),
    );
    if (ok == true && context.mounted) {
      await context.read<TeamController>().leave(teamId);
      if (context.mounted) context.go('/');
    }
  }
}
