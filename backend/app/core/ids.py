"""Prefix ID 생성기 (db-schema.md D2).

모든 PK는 Stripe식 prefix 문자열: 'usr_' + base62 랜덤 20자.
1:1 자식 테이블(materials/recordings/transcripts/reports/answers)은
부모 PK를 재사용하므로 자체 prefix가 없다.
"""

import secrets

_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_RANDOM_LENGTH = 20

# db-schema.md ID prefix 규약 (9종)
ID_PREFIXES = frozenset({
    "usr",   # users
    "team",  # teams
    "inv",   # team_email_invites
    "lnk",   # team_invite_links
    "ses",   # sessions
    "q",     # questions
    "soc",   # social_accounts
    "rt",    # refresh_tokens
    "emv",   # email_verifications
    "pwr",   # password_resets
})


def new_id(prefix: str) -> str:
    """규약된 prefix로 새 ID를 생성한다. 예: new_id("usr") → 'usr_3xK9...'(24자)."""
    if prefix not in ID_PREFIXES:
        raise ValueError(f"알 수 없는 ID prefix: {prefix!r} (허용: {sorted(ID_PREFIXES)})")
    random_part = "".join(secrets.choice(_BASE62) for _ in range(_RANDOM_LENGTH))
    return f"{prefix}_{random_part}"
