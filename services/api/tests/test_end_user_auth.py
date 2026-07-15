from __future__ import annotations

from uuid import uuid4

from app.services.end_user.passwords import hash_password, verify_password
from app.services.end_user.tokens import issue_token, verify_token


def test_password_roundtrip() -> None:
    hashed = hash_password("secret-pass")
    assert verify_password("secret-pass", hashed)
    assert not verify_password("wrong", hashed)


def test_token_roundtrip() -> None:
    user_id = uuid4()
    token = issue_token(user_id=user_id, username="alice")
    payload = verify_token(token)
    assert payload is not None
    assert payload["sub"] == str(user_id)
    assert payload["username"] == "alice"


def test_token_rejects_tamper() -> None:
    token = issue_token(user_id=uuid4(), username="alice")
    assert verify_token(token + "x") is None
