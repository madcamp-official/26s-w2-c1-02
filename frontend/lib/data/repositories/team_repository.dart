import '../models/presentation_type.dart';
import '../models/team.dart';

abstract class TeamRepository {
  Future<List<Team>> fetchTeams();
  Future<Team> getTeam(String id);
  Future<Team> createTeam({
    required String name,
    required PresentationType type,
    required List<String> memberNames,
  });
  Future<void> leaveTeam(String id);
}

/// 인메모리 목 구현. Figma 메인페이지의 teamname1~3을 시드로 제공.
class MockTeamRepository implements TeamRepository {
  final List<Team> _teams = [
    const Team(
      id: 't_1',
      name: 'teamname1',
      type: PresentationType.schoolTeamProject,
      memberNames: ['user', 'user2'],
    ),
    const Team(
      id: 't_2',
      name: 'teamname2',
      type: PresentationType.companyPtInterview,
      memberNames: ['user', 'user3', 'user4'],
    ),
    const Team(
      id: 't_3',
      name: 'teamname3',
      type: PresentationType.executiveReport,
      memberNames: ['user', 'user3', 'user5'],
    ),
  ];

  int _seq = 100;

  @override
  Future<List<Team>> fetchTeams() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    return List.unmodifiable(_teams);
  }

  @override
  Future<Team> getTeam(String id) async {
    await Future<void>.delayed(const Duration(milliseconds: 100));
    return _teams.firstWhere((t) => t.id == id);
  }

  @override
  Future<Team> createTeam({
    required String name,
    required PresentationType type,
    required List<String> memberNames,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 200));
    final team = Team(
      id: 't_${_seq++}',
      name: name,
      type: type,
      // 생성자 본인(user)은 항상 포함.
      memberNames: ['user', ...memberNames],
    );
    _teams.add(team);
    return team;
  }

  @override
  Future<void> leaveTeam(String id) async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    _teams.removeWhere((t) => t.id == id);
  }
}
