import 'presentation_type.dart';

/// 프레젠테이션 팀. 필요한 정보: 이름 + 유형 + 팀원(Figma 주석).
/// 팀 이름은 한 계정 내에서 중복 허용.
class Team {
  const Team({
    required this.id,
    required this.name,
    required this.type,
    required this.memberNames,
  });

  final String id;
  final String name;
  final PresentationType type;
  final List<String> memberNames;

  /// 카드 부제에 쓰이는 "user, user2" 형태.
  String get membersLabel => memberNames.join(', ');

  Team copyWith({
    String? name,
    PresentationType? type,
    List<String>? memberNames,
  }) =>
      Team(
        id: id,
        name: name ?? this.name,
        type: type ?? this.type,
        memberNames: memberNames ?? this.memberNames,
      );

  factory Team.fromJson(Map<String, dynamic> json) => Team(
        id: json['id'].toString(),
        name: json['name'] as String,
        type: PresentationType.fromName(json['type'] as String? ?? 'etc'),
        memberNames: (json['member_names'] as List<dynamic>? ?? [])
            .map((e) => e.toString())
            .toList(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'type': type.name,
        'member_names': memberNames,
      };
}
