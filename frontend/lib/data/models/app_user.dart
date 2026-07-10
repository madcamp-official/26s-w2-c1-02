class AppUser {
  const AppUser({
    required this.id,
    required this.name,
    this.email,
  });

  final String id;
  final String name;
  final String? email;

  factory AppUser.fromJson(Map<String, dynamic> json) => AppUser(
        id: json['id'].toString(),
        name: json['name'] as String,
        email: json['email'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'email': email,
      };
}
