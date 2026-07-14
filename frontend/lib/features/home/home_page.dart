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
  final code = await showDialog<String>(
    context: context,
    builder: (_) => const _InviteCodeDialog(),
  );
  final trimmed = code?.trim().toUpperCase() ?? '';
  if (trimmed.isEmpty || !context.mounted) return;
  context.push('/invites/$trimmed'); // 미리보기(팀명·인원) → 수락은 기존 화면 몫
}

/// 초대코드 입력 다이얼로그.
///
/// 컨트롤러를 State가 소유해야 한다 — showDialog 밖에서 만들고 pop 직후
/// dispose하면, 닫힘 애니메이션 동안 살아 있는 TextField가 폐기된 컨트롤러를
/// 참조해 예외가 나며 화면이 먹통이 된다(QA에서 '취소' 시 재현된 버그).
class _InviteCodeDialog extends StatefulWidget {
  const _InviteCodeDialog();

  @override
  State<_InviteCodeDialog> createState() => _InviteCodeDialogState();
}

class _InviteCodeDialogState extends State<_InviteCodeDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose(); // 라우트가 완전히 제거된 뒤 호출 — 애니메이션 안전
    super.dispose();
  }

  static final _buttonShape =
      RoundedRectangleBorder(borderRadius: BorderRadius.circular(12));

  @override
  Widget build(BuildContext context) {
    final border = OutlineInputBorder(
      borderRadius: BorderRadius.circular(12),
      borderSide: const BorderSide(color: AppColors.accent, width: 1.4),
    );
    return Dialog(
      backgroundColor: AppColors.background,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(24, 24, 24, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('초대코드를 입력해주세요',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
            const SizedBox(height: 16),
            TextField(
              controller: _controller,
              autofocus: true,
              maxLength: 8,
              textCapitalization: TextCapitalization.characters,
              textAlign: TextAlign.center,
              style: const TextStyle(
                  fontSize: 22, fontWeight: FontWeight.w700, letterSpacing: 4),
              decoration: InputDecoration(
                counterText: '',
                enabledBorder: border,
                focusedBorder: border.copyWith(
                    borderSide: const BorderSide(
                        color: AppColors.accent, width: 1.8)),
              ),
              onSubmitted: (v) => Navigator.pop(context, v),
            ),
            const SizedBox(height: 20),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(44),
                      backgroundColor: AppColors.background,
                      foregroundColor: AppColors.accent,
                      side: const BorderSide(
                          color: AppColors.accent, width: 1.4),
                      shape: _buttonShape,
                    ),
                    onPressed: () => Navigator.pop(context),
                    child: const Text('취소',
                        style: TextStyle(fontWeight: FontWeight.w700)),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      minimumSize: const Size.fromHeight(44),
                      backgroundColor: AppColors.accent,
                      foregroundColor: Colors.white,
                      shape: _buttonShape,
                    ),
                    onPressed: () => Navigator.pop(context, _controller.text),
                    child: const Text('확인',
                        style: TextStyle(fontWeight: FontWeight.w700)),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
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
