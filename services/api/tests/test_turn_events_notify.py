"""父表插入后，门铃载荷是这一行的 turn_id。"""

from __future__ import annotations

import subprocess
import threading
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")


def _dsn() -> str | None:
    explicit = __import__("os").environ.get("NOTIFY_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    probe = subprocess.run(
        [
            "docker",
            "inspect",
            "-f",
            "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            "agent-postgres",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    ip = probe.stdout.strip()
    if probe.returncode != 0 or not ip:
        return None
    return f"postgresql://agent:agent@{ip}:5432/agent"


def test_parent_insert_notifies_the_turn_id() -> None:
    dsn = _dsn()
    if dsn is None:
        pytest.skip("agent-postgres is not reachable")
    try:
        listener = psycopg.connect(dsn, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"agent-postgres refused the connection: {exc}")
    box: dict[str, str] = {}

    def wait() -> None:
        for note in listener.notifies(timeout=5):
            box["channel"] = note.channel
            box["payload"] = note.payload
            return

    user_id = uuid.uuid4()
    work_id = uuid.uuid4()
    session_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    run_id = uuid.uuid4()
    listener.execute("LISTEN turn_events_channel")
    thread = threading.Thread(target=wait)
    thread.start()
    try:
        with psycopg.connect(dsn, autocommit=True) as writer:
            writer.execute(
                "INSERT INTO end_users (id, username, password_hash) VALUES (%s, %s, %s)",
                (user_id, f"notify-{user_id.hex[:8]}", "x"),
            )
            writer.execute(
                "INSERT INTO works (id, owner_user_id, work_root) VALUES (%s, %s, %s)",
                (work_id, user_id, f"/tmp/notify-{work_id}"),
            )
            writer.execute(
                """
                INSERT INTO sessions (id, owner_user_id, work_id)
                VALUES (%s, %s, %s)
                """,
                (session_id, user_id, work_id),
            )
            writer.execute(
                """
                INSERT INTO turns (id, session_id, scenario_id, user_input)
                VALUES (%s, %s, 'writing', 'notify')
                """,
                (turn_id, session_id),
            )
            writer.execute(
                "INSERT INTO runs (id, turn_id) VALUES (%s, %s)",
                (run_id, turn_id),
            )
            writer.execute(
                """
                INSERT INTO turn_events (
                    turn_id, stream_id, sequence, type, run_id, trace_id, turn_created_at
                )
                SELECT %s, %s, 1, 'turn.created', %s, %s, created_at
                FROM turns WHERE id = %s
                """,
                (turn_id, turn_id, run_id, uuid.uuid4(), turn_id),
            )
        thread.join(6)
        assert box.get("channel") == "turn_events_channel"
        assert box.get("payload") == str(turn_id)
    finally:
        thread.join(6)
        listener.close()
        with psycopg.connect(dsn, autocommit=True) as writer:
            writer.execute("DELETE FROM turn_events WHERE turn_id = %s", (turn_id,))
            writer.execute("DELETE FROM runs WHERE id = %s", (run_id,))
            writer.execute("DELETE FROM turns WHERE id = %s", (turn_id,))
            writer.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
            writer.execute("DELETE FROM works WHERE id = %s", (work_id,))
            writer.execute("DELETE FROM end_users WHERE id = %s", (user_id,))
