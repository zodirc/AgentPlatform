"""服务器回合在意图改稿之前留下影子快照，撤销能找回被放弃的修订。"""

import inspect
from uuid import uuid4

from app.controller.turn_controller import _intent_baseline, start_turn
from app.policy.shadow_git import restore_turn
from app.writing.candidates import latest_pending_patch, remember_pending_patch
from app.writing.intents import resolve_intent


def test_start_turn_snapshots_before_intent():
    source = inspect.getsource(start_turn)
    assert "before_apply=_intent_baseline" in source


def test_server_reject_baseline_restores_patch(tmp_path):
    work = tmp_path / "book"
    work.mkdir()
    remember_pending_patch(
        {
            "patch_id": "patch-1",
            "path": "outline.md",
            "old_text": "旧",
            "new_text": "新",
            "status": "pending",
        },
        workspace_root=work,
    )
    turn_id = uuid4()
    resolve_intent(
        {"kind": "reject_patch", "patch_id": "patch-1"},
        message="不用这个修订",
        workspace_root=work,
        before_apply=_intent_baseline(str(work), turn_id),
    )
    assert latest_pending_patch(workspace_root=work) is None
    restored = restore_turn(work, turn_id=str(turn_id))
    assert any(path.endswith("pending_patches.json") for path in restored)
    again = latest_pending_patch(workspace_root=work)
    assert again is not None
    assert again["patch_id"] == "patch-1"
