/// 청중(질문자) 유형 — 발표 만들기에서 선택. Figma "청중/질문자 유형 선택".
/// 질의응답 화면의 캐릭터(테토교수/에겐교수/꼰대교수)와 매핑된다.
enum AudienceType {
  teto('테토청중', '테토교수'),
  egen('에겐청중', '에겐교수'),
  kkondae('꼰대청중', '꼰대교수'),
  etc('기타', '교수');

  const AudienceType(this.label, this.professorLabel);

  /// 선택 라디오에 노출되는 라벨.
  final String label;

  /// 질의응답 시 질문자로 등장하는 캐릭터 이름.
  final String professorLabel;

  static AudienceType fromName(String name) => AudienceType.values.firstWhere(
        (e) => e.name == name,
        orElse: () => AudienceType.etc,
      );
}
