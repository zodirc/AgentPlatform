from __future__ import annotations

from uuid import uuid4

from app.services.command.idempotency import remember, replay


def test_replay_none_without_client_request_id() -> None:
    turn_id = uuid4()
    remember(turn_id, None, {"ok": True})
    assert replay(turn_id, None) is None


def test_remember_then_replay_same_pair() -> None:
    turn_id = uuid4()
    cid = uuid4()
    remember(turn_id, cid, {"status": "approved"})
    assert replay(turn_id, cid) == {"status": "approved"}
    assert replay(turn_id, uuid4()) is None
    remember(turn_id, cid, {"status": "denied"})
    assert replay(turn_id, cid) == {"status": "denied"}
