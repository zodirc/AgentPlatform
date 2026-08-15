from app.services.ops.official_runner import trim_official_logs
from app.services.ops.l1.turn_driver import _ast_progress_should_emit


def test_trim_keeps_last_workspace_index_per_instance() -> None:
    logs: list[dict] = []
    logs.append(
        {
            "kind": "log",
            "message": "[L1] workspace_index astropy__astropy-14182 status=ready files=935/935 ephemeral=1",
        }
    )
    for i in range(1600):
        logs.append({"kind": "log", "message": f"[L1] · turn.thinking.delta n={i}"})
    logs.append(
        {
            "kind": "log",
            "message": "[L1] workspace_index astropy__astropy-14995 status=ready files=903/903 ephemeral=1",
        }
    )
    out = trim_official_logs(logs, limit=1500)
    messages = [str(x.get("message") or "") for x in out]
    assert any("14182" in m and "status=ready" in m for m in messages)
    assert any("14995" in m for m in messages)
    assert len(out) <= 1501


def test_trim_keeps_early_coding_pass_line() -> None:
    logs: list[dict] = [
        {
            "kind": "log",
            "message": "[L1] coding plan n=5 tier=n5 parallel=2",
        },
        {
            "kind": "log",
            "message": "[L1] coding 1/5 astropy__astropy-12907 status=pass patch_source=git_diff",
        },
    ]
    for i in range(1600):
        logs.append({"kind": "log", "message": f"[L1] · noise {i}"})
    logs.append(
        {
            "kind": "log",
            "message": "[L1] coding 5/5 astropy__astropy-6938 status=pass patch_source=git_diff",
        }
    )
    out = trim_official_logs(logs, limit=1500)
    messages = [str(x.get("message") or "") for x in out]
    assert any("coding plan n=5" in m for m in messages)
    assert any("12907" in m and "status=pass" in m for m in messages)
    assert any("6938" in m for m in messages)


def test_ast_progress_skips_small_building_ticks() -> None:
    last = "[L1] workspace_index x status=building files=10/900 gen=1 ephemeral=1"
    nxt = "[L1] workspace_index x status=building files=20/900 gen=1 ephemeral=1"
    assert not _ast_progress_should_emit(
        last, nxt, status="building", files_done=20, files_total=900
    )
    jump = "[L1] workspace_index x status=building files=120/900 gen=1 ephemeral=1"
    assert _ast_progress_should_emit(
        last, jump, status="building", files_done=120, files_total=900
    )
    ready = "[L1] workspace_index x status=ready files=900/900 gen=1 ephemeral=1"
    assert _ast_progress_should_emit(
        last, ready, status="ready", files_done=900, files_total=900
    )


def test_trim_keeps_suite_start_and_case_finished() -> None:
    logs: list[dict] = [
        {"kind": "log", "message": "[L1] suite start retrieval"},
        {"kind": "case_finished", "case_id": "official.retrieval"},
    ]
    for i in range(1600):
        logs.append({"kind": "log", "message": f"[L1] · noise {i}"})
    logs.append({"kind": "log", "message": "[L1] suite start context"})
    out = trim_official_logs(logs, limit=1500)
    messages = [str(x.get("message") or "") for x in out]
    kinds = [str(x.get("kind") or "") for x in out]
    assert any("suite start retrieval" in m for m in messages)
    assert any("suite start context" in m for m in messages)
    assert "case_finished" in kinds
