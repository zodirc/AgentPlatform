"""CLI entry for make sync* (progress + takeover)."""

from __future__ import annotations

import json

from app.retrieval import sync_cli


def test_configure_cli_logging_warning_quiets_httpx() -> None:
    sync_cli._configure_cli_logging("WARNING")
    import logging

    assert logging.getLogger().level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.WARNING


def test_main_sources_with_takeover(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "app.retrieval.index_scheduler.request_sync_takeover",
        lambda wait_s=20.0: {
            "cancel_gen": 3,
            "killed_pids": [9],
            "db_terminated": [11],
            "prior_phase": "embed",
        },
    )
    uninstall_calls = {"n": 0}

    def fake_install():
        def uninstall():
            uninstall_calls["n"] += 1

        return uninstall

    monkeypatch.setattr(
        "app.retrieval.sync_progress.install_cli_progress_sink", fake_install
    )

    async def fake_sync(*, reason="make"):
        return {"status": "ok", "reason": reason, "indexed_files": 1}

    monkeypatch.setattr(
        "app.retrieval.index_scheduler.run_sources_index_sync", fake_sync
    )

    code = sync_cli.main(["--reason", "test", "--mode", "sources", "--takeover-wait", "1"])
    assert code == 0
    assert uninstall_calls["n"] == 1
    out = capsys.readouterr()
    assert "接管" in out.err
    payload = json.loads(out.out.strip().splitlines()[-1])
    assert payload["status"] == "ok"


def test_main_ops_beir_without_takeover(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "app.retrieval.sync_progress.install_cli_progress_sink",
        lambda: (lambda: None),
    )

    async def fake_ops(*, reason="make"):
        return {"status": "error", "reason": reason}

    monkeypatch.setattr(
        "app.retrieval.index_scheduler.run_ops_beir_index_sync", fake_ops
    )
    code = sync_cli.main(["--mode", "ops-beir", "--no-takeover", "--reason", "ci"])
    assert code == 1
    out = capsys.readouterr()
    assert "接管" not in out.err
    assert json.loads(out.out.strip())["status"] == "error"
