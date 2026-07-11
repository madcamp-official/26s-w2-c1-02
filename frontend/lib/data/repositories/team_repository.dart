import '../../core/network/api_client.dart';
import '../models/team.dart';

class TeamRepository {
  TeamRepository(this._api);

  final ApiClient _api;

  Future<List<Team>> fetchTeams() async {
    final json = await _api.get('/teams') as Map<String, dynamic>;
    return (json['items'] as List<dynamic>)
        .map((e) => Team.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Team> getTeam(String id) async {
    final json = await _api.get('/teams/$id') as Map<String, dynamic>;
    return Team.fromJson(json);
  }

  Future<Team> createTeam(String name) async {
    final json =
        await _api.post('/teams', body: {'name': name}) as Map<String, dynamic>;
    return Team.fromJson(json);
  }

  Future<void> leaveTeam(String id) => _api.post('/teams/$id/leave');

  Future<void> deleteTeam(String id) => _api.delete('/teams/$id');

  // ---- 초대 ----

  Future<void> inviteByEmail(String teamId, String email) =>
      _api.post('/teams/$teamId/invites', body: {'email': email});

  Future<InviteLink> createInviteLink(String teamId) async {
    final json =
        await _api.post('/teams/$teamId/invites/link') as Map<String, dynamic>;
    return InviteLink.fromJson(json);
  }

  Future<InvitePreview> previewInvite(String token) async {
    final json = await _api.get('/invites/$token') as Map<String, dynamic>;
    return InvitePreview.fromJson(json);
  }

  Future<void> acceptInvite(String token) => _api.post('/invites/$token/accept');

  Future<void> declineInvite(String token) =>
      _api.post('/invites/$token/decline');
}
