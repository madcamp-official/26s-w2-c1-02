/// 프레젠테이션(팀) 유형 — 단일 선택. Figma "어떤 프레젠테이션인가요?"
enum PresentationType {
  schoolTeamProject('학교 팀프로젝트 발표'),
  companyPtInterview('기업 PT 면접'),
  executiveReport('직장 임원보고'),
  etc('그 외');

  const PresentationType(this.label);
  final String label;

  static PresentationType fromName(String name) =>
      PresentationType.values.firstWhere(
        (e) => e.name == name,
        orElse: () => PresentationType.etc,
      );
}
