import 'audience_type.dart';

/// 하나의 발표(스피치). 발표 만들기 화면에서 생성된다.
class Speech {
  const Speech({
    required this.id,
    required this.teamId,
    required this.name,
    this.materialFileName,
    this.audienceType = AudienceType.teto,
    this.audienceDetail,
    this.questionCount = 3,
    this.durationMinutes = 5,
  });

  final String id;
  final String teamId;
  final String name;

  /// 업로드한 발표 자료(PDF) 파일명. 지금은 파일명만 저장.
  final String? materialFileName;

  final AudienceType audienceType;

  /// 청중 유형이 '기타'일 때의 자유 서술.
  final String? audienceDetail;

  /// 생성할 질문 개수(꼬리물기 최대 3단계).
  final int questionCount;

  /// 발표 제한 시간(분).
  final int durationMinutes;

  factory Speech.fromJson(Map<String, dynamic> json) => Speech(
        id: json['id'].toString(),
        teamId: json['team_id'].toString(),
        name: json['name'] as String,
        materialFileName: json['material_file_name'] as String?,
        audienceType:
            AudienceType.fromName(json['audience_type'] as String? ?? 'teto'),
        audienceDetail: json['audience_detail'] as String?,
        questionCount: json['question_count'] as int? ?? 3,
        durationMinutes: json['duration_minutes'] as int? ?? 5,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'team_id': teamId,
        'name': name,
        'material_file_name': materialFileName,
        'audience_type': audienceType.name,
        'audience_detail': audienceDetail,
        'question_count': questionCount,
        'duration_minutes': durationMinutes,
      };
}
