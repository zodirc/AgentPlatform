from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.end_user.passwords import hash_password, verify_password
from app.services.end_user.tokens import issue_token, verify_token


def test_password_roundtrip() -> None:
    hashed = hash_password("secret-pass")
    assert verify_password("secret-pass", hashed)
    assert not verify_password("wrong", hashed)


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current() -> None:
    import sys
    from unittest.mock import AsyncMock, MagicMock, patch
    from uuid import uuid4

    sys.modules.setdefault("asyncpg", MagicMock())
    from app.services.end_user.users import UserError, change_password

    user_id = uuid4()
    pool = MagicMock()
    pool.fetchrow = AsyncMock(
        return_value={"password_hash": hash_password("old-secret"), "status": "active"}
    )
    pool.execute = AsyncMock()
    with patch("app.services.end_user.users.get_pool", new_callable=AsyncMock, return_value=pool):
        with pytest.raises(UserError) as exc:
            await change_password(user_id, "wrong", "new-secret")
    assert exc.value.code == "bad_password"
    pool.execute.assert_not_called()


@pytest.mark.asyncio
async def test_change_password_updates_hash() -> None:
    import sys
    from unittest.mock import AsyncMock, MagicMock, patch
    from uuid import uuid4

    sys.modules.setdefault("asyncpg", MagicMock())
    from app.services.end_user.users import change_password

    user_id = uuid4()
    pool = MagicMock()
    pool.fetchrow = AsyncMock(
        return_value={"password_hash": hash_password("old-secret"), "status": "active"}
    )
    pool.execute = AsyncMock()
    with patch("app.services.end_user.users.get_pool", new_callable=AsyncMock, return_value=pool):
        await change_password(user_id, "old-secret", "new-secret")
    pool.execute.assert_awaited_once()
    args = pool.execute.await_args.args
    assert args[1] == user_id
    assert verify_password("new-secret", args[2])


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
