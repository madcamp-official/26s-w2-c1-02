class AppUser {
  const AppUser({
    required this.id,
    required this.name,
    this.username,
    this.email,
  });

  final String id;
  final String name;

  /// 로그인 아이디 (소셜 전용 가입자는 null).
  final String? username;
  final String? email;

  factory AppUser.fromJson(Map<String, dynamic> json) => AppUser(
        id: json['id'] as String,
        name: json['name'] as String? ?? '탈퇴한 사용자',
        username: json['username'] as String?,
        email: json['email'] as String?,
      );
}
