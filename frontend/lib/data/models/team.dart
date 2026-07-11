/// 프레젠테이션 팀 (spec §3). 팀 이름 중복 허용, 팀장 = leader_id.
class Team {
  const Team({
    required this.id,
    required this.name,
    required this.leaderId,
    this.members = const [],
    this.sessionCount = 0,
  });

  final String id;
  final String name;
  final String leaderId;
  final List<TeamMember> members;
  final int sessionCount;

  /// 카드 부제 "준서, 서진" 형태.
  String get membersLabel => members.map((m) => m.name).join(', ');

  bool isLeader(String userId) => leaderId == userId;

  factory Team.fromJson(Map<String, dynamic> json) => Team(
        id: json['id'] as String,
        name: json['name'] as String,
        leaderId: json['leader_id'] as String? ?? '',
        members: (json['members'] as List<dynamic>? ?? [])
            .map((e) => TeamMember.fromJson(e as Map<String, dynamic>))
            .toList(),
        sessionCount: json['session_count'] as int? ?? 0,
      );
}

class TeamMember {
  const TeamMember({required this.userId, required this.name});
  final String userId;
  final String name;

  factory TeamMember.fromJson(Map<String, dynamic> json) => TeamMember(
        userId: json['user_id'] as String,
        name: json['name'] as String? ?? '탈퇴한 사용자',
      );
}

/// 초대 미리보기 (GET /invites/{token} — 인증 불필요, spec §3.1).
class InvitePreview {
  const InvitePreview({
    required this.teamName,
    required this.memberCount,
    required this.sessionCount,
    this.inviterName,
  });

  final String teamName;
  final int memberCount;
  final int sessionCount;
  final String? inviterName;

  factory InvitePreview.fromJson(Map<String, dynamic> json) => InvitePreview(
        teamName: json['team_name'] as String,
        memberCount: json['member_count'] as int? ?? 0,
        sessionCount: json['session_count'] as int? ?? 0,
        inviterName: json['inviter_name'] as String?,
      );
}

/// 초대 링크 (POST/GET /teams/{id}/invites/link).
class InviteLink {
  const InviteLink({required this.token, required this.url, this.expiresAt});

  final String token;
  final String url;
  final DateTime? expiresAt;

  factory InviteLink.fromJson(Map<String, dynamic> json) => InviteLink(
        token: json['token'] as String,
        url: json['url'] as String,
        expiresAt: json['expires_at'] == null
            ? null
            : DateTime.parse(json['expires_at'] as String),
      );
}
