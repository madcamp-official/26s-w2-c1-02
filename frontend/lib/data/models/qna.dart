/// 질의응답 한 건. LLM이 발표 자료 기반으로 생성한 질문 + 사용자 답변.
/// 꼬리물기(follow-up)는 [followUpDepth]로 표현(최대 3단계).
class QnaItem {
  const QnaItem({
    required this.index,
    required this.question,
    this.answer,
    this.followUpDepth = 0,
  });

  /// 1-based 질문 번호 (Q1, Q2 ...).
  final int index;
  final String question;
  final String? answer;
  final int followUpDepth;

  QnaItem copyWith({String? answer}) => QnaItem(
        index: index,
        question: question,
        answer: answer ?? this.answer,
        followUpDepth: followUpDepth,
      );

  factory QnaItem.fromJson(Map<String, dynamic> json) => QnaItem(
        index: json['index'] as int,
        question: json['question'] as String,
        answer: json['answer'] as String?,
        followUpDepth: json['follow_up_depth'] as int? ?? 0,
      );

  Map<String, dynamic> toJson() => {
        'index': index,
        'question': question,
        'answer': answer,
        'follow_up_depth': followUpDepth,
      };
}
